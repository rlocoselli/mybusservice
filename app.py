from flask import Flask, jsonify, request, make_response, render_template, Response
from datetime import timedelta, datetime
from functools import wraps
from time import perf_counter
from urllib.parse import unquote
from uuid import uuid4
import csv
import io
import os
import re
from werkzeug.exceptions import HTTPException
from CustomJSONEncoder import CustomJSONEncoder
from flasgger import Swagger
from flasgger.utils import swag_from as flasgger_swag_from
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from util.constants import NoDatabaseFound
from util.converter import rowConverter
from databaseMeuBusao import getConnectionCursor
from logging_database import assign_password_to_user, authenticate_app_user, create_application_request_log, create_line_utilization_log, ensure_logging_database, get_application_usage_sources, get_application_usage_summary, get_application_usage_timeline, get_line_utilization_summary, get_line_utilization_timeline, is_logging_database_ready, list_app_users

import simplejson as json
import jwt
import sqlite3
from developer_keys import authenticate_developer, create_key, identify_key, list_keys, register_developer, revoke_key
from developer_copy import COPY as DEVELOPER_COPY, LANGUAGES as DEVELOPER_LANGUAGES

SWAGGER_DOCS_DIR = "swagger"


def swag_from(filename, *args, **kwargs):
    if isinstance(filename, str) and filename.endswith(".yml") and not os.path.dirname(filename):
        filename = os.path.join(SWAGGER_DOCS_DIR, filename)
    return flasgger_swag_from(filename, *args, **kwargs)

def getCities():
        print ("Getting Cities")
        try:
            c = getConnectionCursor("postgres")
        except Exception as err:
            print (err)
            return NoDatabaseFound
            
        c.execute("SELECT datname FROM pg_database")
        
        rows = c.fetchall()
        
        cities = []
        
        for row in rows:
            if "_" in row[0] and "pycache" not in row[0]:
                cities.append(row[0])
        
        return cities

app = Flask(__name__)

app.json_encoder = CustomJSONEncoder

app.config['JSON_AS_ASCII'] = False
app.config ['SECRET_KEY'] = os.getenv("SECRET_KEY", "aooeioeriureoireo")

app.config['SWAGGER'] = {
    'title': 'My Bus Service - Meu Busao',
    'uiversion': 3,
    "specs_route": "/apidocs/",
    "components": {
        "schemas": {
            "Color": {
                "type": "string",
                "enum":["black"]
            }
        }
    }
}

template = {
  "swagger": "2.0",
  "cities": {"in": "path","required":"true","name":"city","enum": getCities()},
  "info": {
    "title": "My Bus Service - Meu Busao",
    "description": "API to manage GTFS across different cities",
    "version": "1.0.1"
  },
  "operationId": "getmyData"
}

swagger = Swagger(app,template=template)
LOGGING_DATABASE_NAME = "mybus"

def service_error_response(err, status_code=500, message="Service error"):
    print(err)
    return jsonify({"message": message, "error": str(err)}), status_code


def database_unavailable_response(err=None):
    error_message = str(err) if err else "No database Found"
    return service_error_response(error_message)


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    return jsonify({"message": err.name, "error": err.description}), err.code


@app.errorhandler(Exception)
def handle_unexpected_exception(err):
    return service_error_response(err)

def normalize_gtfs_date(date_value: str) -> str:
    if not date_value:
        return ""

    date_value = date_value.strip()

    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_value, date_format).strftime("%Y%m%d")
        except ValueError:
            pass

    digits_only = re.sub(r"\D", "", date_value)
    if len(digits_only) == 8:
        try:
            return datetime.strptime(digits_only, "%Y%m%d").strftime("%Y%m%d")
        except ValueError:
            return ""

    return ""


def get_weekday_column_for_gtfs_date(normalized_date: str) -> str:
    weekday_columns = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    return weekday_columns[datetime.strptime(normalized_date, "%Y%m%d").weekday()]


def get_token_subject():
    if request.environ.get("api_key_subject"):
        return request.environ["api_key_subject"]
    token = request.headers.get("token")

    if not token:
        return None

    try:
        data = jwt.decode(token, app.config['SECRET_KEY'])
        return data.get("user")
    except Exception:
        return None


def get_request_duration_ms():
    started_at = request.environ.get("request_started_at")

    if not started_at:
        return None

    return round((perf_counter() - started_at) * 1000, 3)


def parse_dashboard_filter_args():
    return {
        "city": request.args.get("city"),
        "route_id": request.args.get("routeId") or request.args.get("route"),
        "start_at": request.args.get("fromDate"),
        "end_at": request.args.get("toDate"),
    }


def build_csv_response(filename, fieldnames, rows):
    csv_stream = io.StringIO(newline="")
    writer = csv.DictWriter(csv_stream, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for row in rows:
        writer.writerow(row)

    content = csv_stream.getvalue()
    csv_stream.close()

    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def build_dashboard_pdf_response(filters, application_summary, application_timeline, line_summary, line_timeline):
    filename = f"dashboard_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    y_position = page_height - 44

    def write_line(text, size=10, bold=False, spacing=14):
        nonlocal y_position

        if y_position < 56:
            pdf.showPage()
            y_position = page_height - 44

        font_name = "Helvetica-Bold" if bold else "Helvetica"
        pdf.setFont(font_name, size)
        pdf.drawString(36, y_position, str(text))
        y_position -= spacing

    total_requests = sum(int(item.get("requestCount") or 0) for item in application_summary)
    total_errors = sum(int(item.get("errorCount") or 0) for item in application_summary)
    total_boardings = sum(int(item.get("totalBoardings") or 0) for item in line_summary)

    write_line("Meu Busao Dashboard Export", size=16, bold=True, spacing=20)
    write_line(f"Generated at: {datetime.utcnow().isoformat()} UTC")
    write_line(
        "Filters: "
        f"city={filters.get('city') or 'all'}, "
        f"route={filters.get('route_id') or 'all'}, "
        f"from={filters.get('start_at') or 'none'}, "
        f"to={filters.get('end_at') or 'none'}"
    )
    write_line("")

    write_line("Global KPI", bold=True)
    write_line(f"Total API requests: {total_requests}")
    write_line(f"Total API errors: {total_errors}")
    write_line(f"Total boardings: {total_boardings}")
    write_line(f"Timeline points (API): {len(application_timeline)}")
    write_line(f"Timeline points (Utilization): {len(line_timeline)}")
    write_line("")

    write_line("Top API endpoints", bold=True)
    for item in application_summary[:10]:
        endpoint = item.get("endpoint") or "n/a"
        method = item.get("method") or "n/a"
        count = item.get("requestCount") or 0
        city = item.get("city") or "n/a"
        write_line(f"- {method} {endpoint} | city={city} | requests={count}")
    write_line("")

    write_line("Top lines by boardings", bold=True)
    for item in line_summary[:10]:
        line_name = item.get("lineName") or item.get("routeId") or "n/a"
        city = item.get("city") or "n/a"
        boardings = item.get("totalBoardings") or 0
        events = item.get("eventCount") or 0
        write_line(f"- {line_name} | city={city} | boardings={boardings} | events={events}")

    pdf.showPage()
    pdf.save()
    buffer.seek(0)

    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def to_optional_int(value, field_name):
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{field_name} must be an integer") from err


def to_optional_float(value, field_name):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{field_name} must be a number") from err


def build_request_log_payload(response):
    view_args = request.view_args or {}
    sensitive_path = request.path == "/login" or request.path.startswith("/developer/") or request.path == "/admin/users/password"
    request_payload = request.get_json(silent=True) if request.method in ("POST", "PUT", "PATCH") and not sensitive_path else None

    if request_payload is not None and not isinstance(request_payload, (dict, list)):
        request_payload = {"value": request_payload}

    return {
        "request_id": request.environ.get("request_tracking_id") or str(uuid4()),
        "application_name": request.headers.get("X-Client-Application"),
        "endpoint": request.endpoint,
        "method": request.method,
        "path": request.path,
        "city": view_args.get("city") or request.args.get("city"),
        "route_id": view_args.get("routeId") or view_args.get("route") or request.args.get("routeId") or request.args.get("route"),
        "line_name": request.args.get("lineName") or request.args.get("line") or view_args.get("lineName"),
        "direction": request.args.get("direction") or view_args.get("direction"),
        "stop_id": view_args.get("stopId") or request.args.get("stopId"),
        "query_params": {key: value for key, value in request.args.to_dict(flat=False).items() if key.lower() not in ("id", "token", "api_key", "password")},
        "request_payload": request_payload,
        "response_status": response.status_code,
        "duration_ms": get_request_duration_ms(),
        "client_ip": request.headers.get("X-Forwarded-For") or request.remote_addr,
        "user_agent": request.headers.get("User-Agent"),
        "token_subject": get_token_subject(),
    }

def token_required(f):
    @wraps(f)
    def decorated (*args, **kwargs):
        token = request.headers.get("X-API-Key") or request.headers.get("token")

        if not token:
            return jsonify({'message' : 'Token is missing'}), 403
        
        if token.startswith("mb_live_"):
            if request.method != "GET" or request.path.startswith(("/admin/", "/logs/")):
                return jsonify({"message": "API keys can only read transport data"}), 403
            subject = identify_key(token, LOGGING_DATABASE_NAME)
            if subject == "RATE_LIMITED":
                return jsonify({"message": "API key rate limit exceeded (120 requests per minute)"}), 429
            if not subject:
                return jsonify({"message": "API key is invalid or revoked"}), 403
            request.environ["api_key_subject"] = subject
        else:
            try:
                jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            except Exception:
                return jsonify({'message' : 'Token is invalid'}), 403
        
        return f(*args, **kwargs)
    return decorated


def admin_token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("token", "")
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
        except Exception:
            return jsonify({"message": "Admin token is invalid"}), 403
        if data.get("scope") != "admin":
            return jsonify({"message": "Administrator access required"}), 403
        return f(*args, **kwargs)
    return decorated


@app.before_request
def capture_request_started_at():
    request.environ["request_started_at"] = perf_counter()
    request.environ["request_tracking_id"] = str(uuid4())


@app.after_request
def persist_application_usage_log(response):
    if request.endpoint == "static" or request.path.startswith("/apidocs"):
        return response

    if not is_logging_database_ready(LOGGING_DATABASE_NAME):
        return response

    try:
        create_application_request_log(build_request_log_payload(response), LOGGING_DATABASE_NAME)
    except Exception as err:
        print(err)

    return response

@app.route('/login', methods=["GET", "POST"])
@swag_from("login.yml")
def login():
    try:
        payload = request.get_json(silent=True) if request.method == "POST" else None
        username = payload.get("username") if isinstance(payload, dict) else None
        password = payload.get("password") if isinstance(payload, dict) else None

        if username or password:
            if not is_logging_database_ready(LOGGING_DATABASE_NAME):
                return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

            authenticated_user = authenticate_app_user(username, password, LOGGING_DATABASE_NAME)
            if authenticated_user:
                token = jwt.encode({"user" : authenticated_user["username"], "scope": "admin", "exp" : datetime.utcnow() + timedelta(minutes=30)}, app.config ["SECRET_KEY"])
                return jsonify({
                    "token" : token.decode("UTF-8"),
                    "user": authenticated_user,
                    "authSource": "postgresql",
                })

            return jsonify({"message": "Nom d'utilisateur ou mot de passe invalide."}), 401

        auth = request.headers.get("id") or request.args.get("id")

        db = "./config.db"

        conn = sqlite3.connect(db)

        c = conn.cursor()

        c.execute("select count(1) from users where identificator = ?", (auth,))

        data = c.fetchall()

        if int(data[0][0]) > 0:
            token = jwt.encode({"user" : auth, "exp" : datetime.utcnow() + timedelta(minutes=30)}, app.config ["SECRET_KEY"])
            return jsonify({"token" : token.decode("UTF-8"), "authSource": "sqlite"})

        return make_response('Could not verify! Login Failed',401, {'Err-Message' : 'Login Failed'})
    except Exception as err:
        return service_error_response(err)


@app.route('/developer', methods=["GET"])
def developerPortal():
    requested = request.args.get("lang", "").lower().split("-")[0]
    browser = next((code.lower().split("-")[0] for code, quality in request.accept_languages
                    if quality > 0 and code.lower().split("-")[0] in DEVELOPER_LANGUAGES), "pt")
    lang = requested if requested in DEVELOPER_LANGUAGES else browser
    return render_template("developer_portal.html", lang=lang, languages=DEVELOPER_LANGUAGES, copy=DEVELOPER_COPY[lang])


@app.route('/developer/register', methods=["POST"])
def developerRegister():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"code": "invalid_json"}), 400
    try:
        username = register_developer(payload.get("username"), payload.get("password"), LOGGING_DATABASE_NAME)
        return jsonify({"username": username, "message": "Account created"}), 201
    except ValueError as err:
        return jsonify({"code": str(err)}), 400
    except Exception as err:
        print(err)
        return jsonify({"code": "server_error"}), 500


@app.route('/developer/keys', methods=["POST"])
def developerKeys():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"code": "invalid_json"}), 400
    try:
        developer_id = authenticate_developer(payload.get("username"), payload.get("password"), LOGGING_DATABASE_NAME)
        if not developer_id:
            return jsonify({"code": "invalid_credentials"}), 401
        action = payload.get("action")
        if action == "list":
            return jsonify({"keys": list_keys(developer_id, LOGGING_DATABASE_NAME)})
        if action == "create":
            response = jsonify(create_key(developer_id, payload.get("name"), LOGGING_DATABASE_NAME))
            response.headers["Cache-Control"] = "no-store"
            return response, 201
        if action == "revoke":
            key_id = payload.get("keyId")
            if not isinstance(key_id, int) or isinstance(key_id, bool):
                return jsonify({"code": "invalid_key_id"}), 400
            if not revoke_key(developer_id, key_id, LOGGING_DATABASE_NAME):
                return jsonify({"code": "key_not_found"}), 404
            return jsonify({"message": "Key revoked"})
        return jsonify({"code": "invalid_action"}), 400
    except ValueError as err:
        return jsonify({"code": str(err)}), 400
    except Exception as err:
        print(err)
        return jsonify({"code": "server_error"}), 500


@app.route('/admin/setupMyBusLoggingDatabase', methods=["POST"])
@swag_from("setupMyBusLoggingDatabase.yml")
@token_required
def setupMyBusLoggingDatabase():
    try:
        result = ensure_logging_database(LOGGING_DATABASE_NAME)
        status_code = 201 if result["database_created"] or result["created_tables"] else 200
        return jsonify({
            "message": "Logging database is ready",
            "database": LOGGING_DATABASE_NAME,
            "databaseCreated": result["database_created"],
            "createdTables": result["created_tables"],
            "availableTables": result["available_tables"],
            "procedures": result["procedures"],
            "users": result["users"],
        }), status_code
    except Exception as err:
        return service_error_response(err)


@app.route('/admin/usage-dashboard', methods=["GET"])
def usageDashboard():
    return render_template("usage_dashboard.html")


@app.route('/admin/login', methods=["GET"])
def adminLogin():
    return render_template("admin_login.html")


@app.route('/admin/user-management', methods=["GET"])
def userManagement():
    return render_template("user_management.html")


@app.route('/logs/line-utilization', methods=["POST"])
@swag_from("createLineUtilizationLog.yml")
@token_required
def createLineUtilizationLog():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"message": "A JSON object body is required"}), 400

        city = payload.get("city")
        route_id = payload.get("routeId")
        line_name = payload.get("lineName")

        if not city:
            return jsonify({"message": "city is required"}), 400
        if not route_id and not line_name:
            return jsonify({"message": "routeId or lineName is required"}), 400

        created_log = create_line_utilization_log({
            "application_name": payload.get("applicationName") or request.headers.get("X-Client-Application"),
            "city": city,
            "route_id": route_id,
            "line_name": line_name,
            "direction": payload.get("direction"),
            "trip_id": payload.get("tripId"),
            "stop_id": payload.get("stopId"),
            "vehicle_id": payload.get("vehicleId"),
            "boardings": to_optional_int(payload.get("boardings"), "boardings"),
            "alightings": to_optional_int(payload.get("alightings"), "alightings"),
            "occupancy": to_optional_int(payload.get("occupancy"), "occupancy"),
            "occupancy_rate": to_optional_float(payload.get("occupancyRate"), "occupancyRate"),
            "utilization_source": payload.get("source"),
            "observed_at": payload.get("observedAt"),
            "extra_data": payload.get("extraData"),
        }, LOGGING_DATABASE_NAME)

        return jsonify({
            "message": "Line utilization log created",
            "id": created_log["id"],
            "createdAt": created_log["created_at"],
            "observedAt": created_log["observed_at"],
        }), 201
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/line-utilization/summary', methods=["GET"])
@swag_from("getLineUtilizationSummary.yml")
@admin_token_required
def getLineUtilizationSummary():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        summary = get_line_utilization_summary(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())

        return jsonify(summary)
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/line-utilization/timeline', methods=["GET"])
@swag_from("getLineUtilizationTimeline.yml")
@admin_token_required
def getLineUtilizationTimeline():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        timeline = get_line_utilization_timeline(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())

        return jsonify(timeline)
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/application-usage/summary', methods=["GET"])
@swag_from("getApplicationUsageSummary.yml")
@admin_token_required
def getApplicationUsageSummary():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        summary = get_application_usage_summary(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())

        return jsonify(summary)
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/application-usage/timeline', methods=["GET"])
@swag_from("getApplicationUsageTimeline.yml")
@admin_token_required
def getApplicationUsageTimeline():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        timeline = get_application_usage_timeline(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())

        return jsonify(timeline)
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/application-usage/sources', methods=["GET"])
@swag_from("getApplicationUsageSources.yml")
@admin_token_required
def getApplicationUsageSources():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409
        return jsonify(get_application_usage_sources(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args()))
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/export/application-usage.csv', methods=["GET"])
@swag_from("exportApplicationUsageCsv.yml")
@admin_token_required
def exportApplicationUsageCsv():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        summary = get_application_usage_summary(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())
        filename = f"application_usage_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

        return build_csv_response(
            filename,
            [
                "city",
                "routeId",
                "endpoint",
                "method",
                "requestCount",
                "averageDurationMs",
                "successCount",
                "errorCount",
                "lastRequestAt",
            ],
            summary,
        )
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/export/line-utilization.csv', methods=["GET"])
@swag_from("exportLineUtilizationCsv.yml")
@admin_token_required
def exportLineUtilizationCsv():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        summary = get_line_utilization_summary(LOGGING_DATABASE_NAME, **parse_dashboard_filter_args())
        filename = f"line_utilization_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

        return build_csv_response(
            filename,
            [
                "city",
                "routeId",
                "lineName",
                "direction",
                "eventCount",
                "totalBoardings",
                "totalAlightings",
                "averageOccupancy",
                "averageOccupancyRate",
                "lastObservedAt",
            ],
            summary,
        )
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/logs/export/dashboard.pdf', methods=["GET"])
@swag_from("exportDashboardPdf.yml")
@admin_token_required
def exportDashboardPdf():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        filters = parse_dashboard_filter_args()
        application_summary = get_application_usage_summary(LOGGING_DATABASE_NAME, **filters)
        application_timeline = get_application_usage_timeline(LOGGING_DATABASE_NAME, **filters)
        line_summary = get_line_utilization_summary(LOGGING_DATABASE_NAME, **filters)
        line_timeline = get_line_utilization_timeline(LOGGING_DATABASE_NAME, **filters)

        return build_dashboard_pdf_response(filters, application_summary, application_timeline, line_summary, line_timeline)
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)


@app.route('/admin/users', methods=["GET"])
@swag_from("getAppUsers.yml")
@admin_token_required
def getAppUsers():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        return jsonify(list_app_users(LOGGING_DATABASE_NAME))
    except Exception as err:
        return service_error_response(err)


@app.route('/admin/users/password', methods=["POST"])
@swag_from("assignUserPassword.yml")
@admin_token_required
def assignUserPassword():
    try:
        if not is_logging_database_ready(LOGGING_DATABASE_NAME):
            return jsonify({"message": "Logging database is not ready. Call /admin/setupMyBusLoggingDatabase first."}), 409

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"message": "A JSON object body is required"}), 400

        result = assign_password_to_user(
            payload.get("username"),
            payload.get("password"),
            LOGGING_DATABASE_NAME,
        )

        return jsonify({
            "message": "Password assigned successfully",
            "username": result["username"],
            "passwordHashAlgorithm": result["passwordHashAlgorithm"],
        })
    except ValueError as err:
        return jsonify({"message": str(err)}), 400
    except Exception as err:
        return service_error_response(err)

@app.route('/getCalendar/<string:city>', methods=["GET"])
@swag_from("getCalendar.yml")
@token_required
def getCalendar(city) -> str:
    try:
        c = getConnectionCursor(city)
            
        c.execute("select * from calendar")
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print(err)
        return database_unavailable_response(err)

@app.route('/getCalendarDates/<string:city>', methods=["GET"])
@swag_from("getCalendarDates.yml")
@token_required
def getCalendarDates(city) -> str:
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        c.execute("select * from calendar_dates")
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)
    
@app.route('/getStopTimeByRouteAndDirectionAndWeekday/<string:city>/<string:weekday>/<string:routeId>',  methods=["GET"])
@swag_from("getStopTimeByRouteAndDirectionAndWeekday.yml")
@token_required
def getStopTimeByRouteAndDirectionAndWeekday(city, weekday, routeId) -> str:
    
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None
    
    try:
        try:
            c = getConnectionCursor(city)
        except Exception as err:
            print (err)
            return database_unavailable_response()
            
        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [routeId]
        if direction:
            params.append(direction_like)

        c.execute("select distinct a.trip_id,a.route_id,a.trip_headsign,a.service_id,a.shape_id,a.wheelchair_accessible,a.bikes_allowed," +
                        " stop_name, arrival_time, departure_time, s.stop_id,st.stop_sequence" +
                        " from trip a join calendar c on a.service_id = c.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                " where c." + weekday + " = '1' and a.route_id = %s" + direction_filter +
                        " and  to_char(CURRENT_DATE,'yyyyMMdd') <= end_date and to_char(CURRENT_DATE,'yyyyMMdd') >= start_date" +
                " order by st.stop_sequence, arrival_time", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print (err)
        return database_unavailable_response(err)

@app.route('/getStopTimeByRouteAndDirectionAndWeekdayAndStopId/<string:city>/<string:weekday>/<string:routeId>/<string:stopId>', methods=["GET"])
@swag_from("getStopTimeByRouteAndDirectionAndWeekdayAndStopId.yml")
@token_required
def getStopTimeByRouteAndDirectionAndWeekdayAndStopId(city, weekday, routeId,stopId) -> str:
    
    stopId = unquote(stopId)
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None
    
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [routeId, stopId]
        if direction:
            params.append(direction_like)

        c.execute("select distinct '0' as trip_id,a.route_id,a.trip_headsign,'0' as service_id,a.shape_id,a.wheelchair_accessible,a.bikes_allowed," +
                        " stop_name, arrival_time, departure_time, s.stop_id,st.stop_sequence" +
                        " from trip a join calendar c on a.service_id = c.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                        " where c." + weekday + " = '1' and a.route_id = %s and s.stop_id = %s" + direction_filter +
                        " and  to_char(CURRENT_DATE,'yyyyMMdd') <= end_date and to_char(CURRENT_DATE,'yyyyMMdd') >= start_date" +
                        " order by arrival_time", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getStopsByRouteAndDirection/<string:city>/<string:weekday>/<string:routeId>', methods=["GET"])
@swag_from("getStopsByRouteAndDirection.yml")
@token_required
def getStopsByRouteAndDirection(city, weekday, routeId) -> str:
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None

    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [routeId]
        if direction:
            params.append(direction_like)

        c.execute("select distinct s.stop_name,s.stop_id,s.stop_lat,s.stop_lon,s.parent_station, s.location_type,st.stop_sequence, max(a.shape_id) shape_id" +
                        " from trip a join calendar c on a.service_id = c.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                        " where c." + weekday + " = '1' and a.route_id = %s" + direction_filter +
                        " group by s.stop_name,s.stop_id,s.stop_lat,s.stop_lon,s.parent_station, s.location_type,st.stop_sequence" + 
                        " order by st.stop_sequence", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getStopTimeByRouteAndDirectionAndDate/<string:city>/<string:date>/<string:routeId>',  methods=["GET"])
@swag_from("getStopTimeByRouteAndDirectionAndDate.yml")
@token_required
def getStopTimeByRouteAndDirectionAndDate(city, date, routeId) -> str:
    
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None
    
    try:
        try:
            c = getConnectionCursor(city)
        except Exception as err:
            print (err)
            return database_unavailable_response()
            
        normalized_date = normalize_gtfs_date(date)
        if not normalized_date:
            return jsonify([])

        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)

        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [normalized_date, normalized_date, normalized_date, normalized_date, routeId]
        if direction:
            params.append(direction_like)

        c.execute("with active_services as (" +
                        " select cd.service_id" +
                        " from calendar_dates cd" +
                        " where cd.datet = %s and coalesce(cd.exception_type::text,'1') = '1'" +
                        " union all" +
                        " select cal.service_id" +
                        " from calendar cal" +
                        " where cal.start_date <= %s and cal.end_date >= %s and cal." + weekday_column + " = '1'" +
                        " and cal.service_id not in (" +
                        "   select cdr.service_id from calendar_dates cdr" +
                        "   where cdr.datet = %s and coalesce(cdr.exception_type::text,'') = '2'" +
                        " )" +
                        ")" +
                        " select distinct a.trip_id,a.route_id,a.trip_headsign,a.service_id,a.shape_id,a.wheelchair_accessible,a.bikes_allowed," +
                        " stop_name, arrival_time, departure_time, s.stop_id,st.stop_sequence" +
                        " from trip a join active_services ac on a.service_id = ac.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                        " where a.route_id = %s" + direction_filter +
                        " order by st.stop_sequence, arrival_time", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print (err)
        return database_unavailable_response(err)

@app.route('/getStopTimeByRouteAndDirectionAndDateAndStopId/<string:city>/<string:date>/<string:routeId>/<string:stopId>', methods=["GET"])
@swag_from("getStopTimeByRouteAndDirectionAndDateAndStopId.yml")
@token_required
def getStopTimeByRouteAndDirectionAndDateAndStopId(city, date, routeId,stopId) -> str:
    
    stopId = unquote(stopId)
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None
    
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        normalized_date = normalize_gtfs_date(date)
        if not normalized_date:
            return jsonify([])

        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)

        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [normalized_date, normalized_date, normalized_date, normalized_date, routeId, stopId]
        if direction:
            params.append(direction_like)

        c.execute("with active_services as (" +
                        " select cd.service_id" +
                        " from calendar_dates cd" +
                        " where cd.datet = %s and coalesce(cd.exception_type::text,'1') = '1'" +
                        " union all" +
                        " select cal.service_id" +
                        " from calendar cal" +
                        " where cal.start_date <= %s and cal.end_date >= %s and cal." + weekday_column + " = '1'" +
                        " and cal.service_id not in (" +
                        "   select cdr.service_id from calendar_dates cdr" +
                        "   where cdr.datet = %s and coalesce(cdr.exception_type::text,'') = '2'" +
                        " )" +
                        ")" +
                        " select distinct '0' as trip_id,a.route_id,a.trip_headsign,'0' as service_id,a.shape_id,a.wheelchair_accessible,a.bikes_allowed," +
                        " stop_name, arrival_time, departure_time, s.stop_id,st.stop_sequence" +
                        " from trip a join active_services ac on a.service_id = ac.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                        " where a.route_id = %s and s.stop_id = %s" + direction_filter +
                        " order by arrival_time", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getStopsByRouteAndDirectionDate/<string:city>/<string:date>/<string:routeId>', methods=["GET"])
@swag_from("getStopsByRouteAndDirectionDate.yml")
@token_required
def getStopsByRouteAndDirectionDate(city, date, routeId) -> str:
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None

    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        normalized_date = normalize_gtfs_date(date)
        if not normalized_date:
            return jsonify([])

        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)

        direction_filter = " and a.trip_headsign ILIKE %s" if direction else ""
        params = [normalized_date, normalized_date, normalized_date, normalized_date, routeId]
        if direction:
            params.append(direction_like)

        c.execute("with active_services as (" +
                        " select cd.service_id" +
                        " from calendar_dates cd" +
                        " where cd.datet = %s and coalesce(cd.exception_type::text,'1') = '1'" +
                        " union all" +
                        " select cal.service_id" +
                        " from calendar cal" +
                        " where cal.start_date <= %s and cal.end_date >= %s and cal." + weekday_column + " = '1'" +
                        " and cal.service_id not in (" +
                        "   select cdr.service_id from calendar_dates cdr" +
                        "   where cdr.datet = %s and coalesce(cdr.exception_type::text,'') = '2'" +
                        " )" +
                        ")" +
                        " select distinct s.stop_name,s.stop_id,s.stop_lat,s.stop_lon,s.parent_station, s.location_type,st.stop_sequence, max(a.shape_id) shape_id" +
                        " from trip a join active_services ac on a.service_id = ac.service_id" +
                        " join stopstime st on st.trip_id = a.trip_id" +
                        " join stops s on st.stop_id  = s.stop_id" +
                        " where a.route_id = %s" + direction_filter +
                        " group by s.stop_name,s.stop_id,s.stop_lat,s.stop_lon,s.parent_station, s.location_type,st.stop_sequence" + 
                        " order by st.stop_sequence", params)
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        return database_unavailable_response(err)



@app.route('/getRouteByTrip/<string:city>/<string:tripId>', methods=["GET"])
@swag_from("getRoutebyTrip.yml")
@token_required
def getRouteByTrip(city, tripId) -> str:
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        c.execute("select * from trip where trip_id = %s", (tripId, ))
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        return database_unavailable_response(err)

@app.route('/getDirectionByRoute/<string:city>/<string:routeId>', methods=["GET"])
@swag_from("getDirections.yml")
@token_required
def getDirectionByRoute(city, routeId) -> str:
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        c.execute("select distinct trip_headsign from trip where route_id = %s", (routeId, ))
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print (err)
        return database_unavailable_response(err)

@app.route('/getShape/<string:city>', methods=["GET"])
@swag_from("getShape.yml")
@token_required
def getShape(city) -> str:
    try:
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()
            
        c.execute("select * from shape")
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)

@app.route('/getShapeById/<string:city>', methods=["GET"])
@swag_from("getShapeById.yml")
@token_required
def getShapeById(city) -> str:
    try:
        shapeId = request.args.get("shapeId")
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()

        print("test")

        c.execute("select shape_pt_lat,shape_pt_lon,shape_pt_sequence from shape where shape_id = %s order by shape_pt_sequence", (shapeId,))
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print(err)
        return database_unavailable_response(err)


@app.route('/getShapeByTripId/<string:city>', methods=["GET"])
@swag_from("getShapeByTripId.yml")
@token_required
def getShapeByTripId(city) -> str:
    try:
        tripId = request.args.get("tripId")
        try:
            c = getConnectionCursor(city)
        except:
            return database_unavailable_response()

        sql= "select s.* from shape s inner join trip t on t.shape_id =s.shape_id and t.trip_id = %s order by shape_pt_sequence"

        c.execute(sql, (tripId,))
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)

    except Exception as err:
        print(err)
        return database_unavailable_response(err)


@app.route('/getRoutes/<string:city>', methods=["GET"])
@swag_from("getRoute.yml")
@token_required
def getRoutes(city) -> str:
    try:
        try:
            c = getConnectionCursor(city)
        except Exception as Err:
            print (Err)
            return database_unavailable_response()
            
        c.execute("select * from route")
        print ("Executed")
        rows = c.fetchall()
        
        c.close()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        return json.dumps(data)
    
    except Exception as err:
        print (err)
        return database_unavailable_response(err)

@app.route('/getStopsTime/<string:city>')
@swag_from("getStopsTime.yml")
@token_required
def getStopsTime(city) -> str:
    try:
        c = getConnectionCursor(city)

        c.execute("select t.trip_id, arrival_time, departure_time,s.stop_id, stop_name, stop_lat, stop_lon, parent_station, trip_headsign,t.service_id " +
                " from STOPSTIME s inner join STOPS s2" + 
                " on s.stop_id = s2.stop_id" + 
                " inner join trip t" + 
                " on s.trip_id = t.trip_id")
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)

@app.route('/getRouteByStopId/<string:city>/<string:stopId>')
@swag_from("getRoutebyStopId.yml")
@token_required
def getRouteByStopId(city, stopId) -> str:
    stopId = unquote(stopId)
    try:
        c = getConnectionCursor(city)

        c.execute("select route_id,route_long_name, route_short_name, route_color, route_text_color " +
                " from route" + 
                " where route_id in (select route_id from stopstime s inner join trip s2 on s.trip_id = s2.trip_id where stop_id = %s)",(stopId,))
        
        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)

#Get Stops from DB
@swag_from("getStops.yml")
@app.route('/getStops/<string:city>', methods=["GET"])
def getStops(city) -> str:
    try:
        c = getConnectionCursor(city)
        c.execute("SELECT * FROM stops ")

        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)

#Get Trips from DB
@swag_from("getTrips.yml")
@app.route('/getTrips/<string:city>/<string:route>', methods=["GET"])
def getTrips(city,route) -> str:
    try:
        c = getConnectionCursor(city)
        c.execute("SELECT * FROM trips where route_id = %s", (route,))

        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return service_error_response(err)

#Get Trips from DB
@swag_from("getStopsByTrip.yml")
@app.route('/getStopsByTrip/<string:city>/<string:trip>', methods=["GET"])
def getStopsByTrip(city,trip) -> str:
    try:
        c = getConnectionCursor(city)
        c.execute("select distinct stop_name , stop_lat, stop_lon,stop_sequence from stopstime s ,stops s2 where s.stop_id = s2.stop_id and trip_id = %s order by stop_sequence",(trip,))

        rows = c.fetchall()

        row_headers=[x[0] for x in c.description]
        
        data = rowConverter(rows, row_headers)
        
        c.close()

        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)

@app.route('/getNearbyStops/<string:city>', methods=["GET"])
@swag_from("getNearbyStops.yml")
@token_required
def getNearbyStops(city) -> str:
    try:
        lat = request.args.get("lat")
        lon = request.args.get("lon")
        radius_meters = request.args.get("radiusMeters", 500)

        if lat is None or lon is None:
            return jsonify({"message": "lat and lon query parameters are required"}), 400

        try:
            lat = float(lat)
            lon = float(lon)
            radius_meters = float(radius_meters)
        except ValueError:
            return jsonify({"message": "lat, lon and radiusMeters must be numeric"}), 400

        c = getConnectionCursor(city)
        c.execute(
            "SELECT stop_id, stop_name, stop_lat, stop_lon, parent_station, location_type,"
            " 2 * 6371000 * asin(sqrt("
            "   power(sin(radians((stop_lat - %s) / 2)), 2) +"
            "   cos(radians(%s)) * cos(radians(stop_lat)) * power(sin(radians((stop_lon - %s) / 2)), 2)"
            " )) AS distance_meters"
            " FROM stops"
            " WHERE 2 * 6371000 * asin(sqrt("
            "   power(sin(radians((stop_lat - %s) / 2)), 2) +"
            "   cos(radians(%s)) * cos(radians(stop_lat)) * power(sin(radians((stop_lon - %s) / 2)), 2)"
            " )) <= %s"
            " ORDER BY distance_meters",
            (lat, lat, lon, lat, lat, lon, radius_meters),
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getNextDepartures/<string:city>/<string:stopId>', methods=["GET"])
@swag_from("getNextDepartures.yml")
@token_required
def getNextDepartures(city, stopId) -> str:
    stopId = unquote(stopId)
    try:
        date_param = request.args.get("date")
        time_param = request.args.get("time")
        try:
            limit = int(request.args.get("limit", 10))
        except ValueError:
            return jsonify({"message": "limit must be an integer"}), 400

        now = datetime.now()
        normalized_date = normalize_gtfs_date(date_param) if date_param else now.strftime("%Y%m%d")
        if not normalized_date:
            return jsonify({"message": "Invalid date format"}), 400

        current_time = time_param if time_param else now.strftime("%H:%M:%S")
        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)

        c = getConnectionCursor(city)
        c.execute(
            "WITH active_services AS ("
            " SELECT cd.service_id FROM calendar_dates cd"
            " WHERE cd.datet = %s AND coalesce(cd.exception_type::text,'1') = '1'"
            " UNION ALL"
            " SELECT cal.service_id FROM calendar cal"
            " WHERE cal.start_date <= %s AND cal.end_date >= %s AND cal." + weekday_column + " = '1'"
            " AND cal.service_id NOT IN ("
            "   SELECT cdr.service_id FROM calendar_dates cdr"
            "   WHERE cdr.datet = %s AND coalesce(cdr.exception_type::text,'') = '2'"
            " )"
            ")"
            " SELECT st.departure_time, t.route_id, t.trip_headsign,"
            " s.stop_id, s.stop_name, t.trip_id,"
            " r.route_short_name, r.route_long_name, r.route_color"
            " FROM stopstime st"
            " JOIN trip t ON st.trip_id = t.trip_id"
            " JOIN active_services ac ON t.service_id = ac.service_id"
            " JOIN stops s ON st.stop_id = s.stop_id"
            " LEFT JOIN route r ON t.route_id = r.route_id"
            " WHERE st.stop_id = %s AND st.departure_time >= %s"
            " ORDER BY st.departure_time"
            " LIMIT %s",
            (normalized_date, normalized_date, normalized_date, normalized_date, stopId, current_time, limit),
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/searchStops/<string:city>', methods=["GET"])
@swag_from("searchStops.yml")
@token_required
def searchStops(city) -> str:
    try:
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"message": "q query parameter is required"}), 400

        c = getConnectionCursor(city)
        c.execute(
            "SELECT stop_id, stop_name, stop_lat, stop_lon, parent_station, location_type"
            " FROM stops WHERE stop_name ILIKE %s ORDER BY stop_name LIMIT 50",
            (f"%{query}%",),
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/searchRoutes/<string:city>', methods=["GET"])
@swag_from("searchRoutes.yml")
@token_required
def searchRoutes(city) -> str:
    try:
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"message": "q query parameter is required"}), 400

        c = getConnectionCursor(city)
        c.execute(
            "SELECT route_id, route_short_name, route_long_name, route_color, route_text_color"
            " FROM route WHERE route_short_name ILIKE %s OR route_long_name ILIKE %s"
            " ORDER BY route_short_name LIMIT 50",
            (f"%{query}%", f"%{query}%"),
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getActiveServices/<string:city>/<string:date>', methods=["GET"])
@swag_from("getActiveServices.yml")
@token_required
def getActiveServices(city, date) -> str:
    try:
        normalized_date = normalize_gtfs_date(date)
        if not normalized_date:
            return jsonify({"message": "Invalid date format"}), 400

        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)
        c = getConnectionCursor(city)
        c.execute(
            "SELECT DISTINCT service_id FROM ("
            " SELECT cd.service_id FROM calendar_dates cd"
            " WHERE cd.datet = %s AND coalesce(cd.exception_type::text,'1') = '1'"
            " UNION ALL"
            " SELECT cal.service_id FROM calendar cal"
            " WHERE cal.start_date <= %s AND cal.end_date >= %s AND cal." + weekday_column + " = '1'"
            " AND cal.service_id NOT IN ("
            "   SELECT cdr.service_id FROM calendar_dates cdr"
            "   WHERE cdr.datet = %s AND coalesce(cdr.exception_type::text,'') = '2'"
            " )"
            ") active_svc ORDER BY service_id",
            (normalized_date, normalized_date, normalized_date, normalized_date),
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps({"date": normalized_date, "activeServices": data})
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getFirstLastDeparture/<string:city>/<string:date>/<string:routeId>', methods=["GET"])
@swag_from("getFirstLastDeparture.yml")
@token_required
def getFirstLastDeparture(city, date, routeId) -> str:
    direction = request.args.get("direction")
    direction = direction.strip() if isinstance(direction, str) else None
    direction_like = f"%{direction}%" if direction else None
    try:
        normalized_date = normalize_gtfs_date(date)
        if not normalized_date:
            return jsonify({"message": "Invalid date format"}), 400

        weekday_column = get_weekday_column_for_gtfs_date(normalized_date)
        direction_filter = " AND t.trip_headsign ILIKE %s" if direction else ""
        params = [normalized_date, normalized_date, normalized_date, normalized_date, routeId]
        if direction:
            params.append(direction_like)

        c = getConnectionCursor(city)
        c.execute(
            "WITH active_services AS ("
            " SELECT cd.service_id FROM calendar_dates cd"
            " WHERE cd.datet = %s AND coalesce(cd.exception_type::text,'1') = '1'"
            " UNION ALL"
            " SELECT cal.service_id FROM calendar cal"
            " WHERE cal.start_date <= %s AND cal.end_date >= %s AND cal." + weekday_column + " = '1'"
            " AND cal.service_id NOT IN ("
            "   SELECT cdr.service_id FROM calendar_dates cdr"
            "   WHERE cdr.datet = %s AND coalesce(cdr.exception_type::text,'') = '2'"
            " )"
            ")"
            " SELECT t.route_id, t.trip_headsign,"
            " min(st.departure_time) AS first_departure,"
            " max(st.departure_time) AS last_departure,"
            " count(DISTINCT t.trip_id) AS trip_count"
            " FROM stopstime st"
            " JOIN trip t ON st.trip_id = t.trip_id"
            " JOIN active_services ac ON t.service_id = ac.service_id"
            " WHERE t.route_id = %s" + direction_filter +
            " GROUP BY t.route_id, t.trip_headsign ORDER BY t.trip_headsign",
            params,
        )
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


@app.route('/getAgency/<string:city>', methods=["GET"])
@swag_from("getAgency.yml")
@token_required
def getAgency(city) -> str:
    try:
        c = getConnectionCursor(city)
        c.execute("SELECT * FROM agency")
        rows = c.fetchall()
        row_headers = [x[0] for x in c.description]
        data = rowConverter(rows, row_headers)
        c.close()
        return json.dumps(data)
    except Exception as err:
        return database_unavailable_response(err)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
    )
