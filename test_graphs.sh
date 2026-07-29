#!/usr/bin/env bash

set -euo pipefail

BASE_URL="${BASE_URL:-https://mybusservice.herokuapp.com}"
IDENTIFICATOR="${IDENTIFICATOR:-}"
CITY="${CITY:-}"
ROUTE_ID="${ROUTE_ID:-}"
FROM_DATE="${FROM_DATE:-2026-03-01}"
TO_DATE="${TO_DATE:-2026-03-18}"
OUT_DIR="${OUT_DIR:-./exports}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

PASS_COUNT=0
FAIL_COUNT=0

if [[ -z "$IDENTIFICATOR" ]]; then
  echo "ERROR: IDENTIFICATOR is required."
  echo "Example: IDENTIFICATOR=my-id ./test_graphs.sh"
  exit 1
fi

mkdir -p "$OUT_DIR"

status_ok() {
  local message="$1"
  PASS_COUNT=$((PASS_COUNT + 1))
  echo "[OK] $message"
}

status_fail() {
  local message="$1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo "[KO] $message"
}

json_request() {
  local method="$1"
  local url="$2"
  local label="$3"
  local temp_body
  local http_code

  temp_body="$(mktemp)"
  http_code="$(curl -sS -X "$method" -H "token: $TOKEN" -o "$temp_body" -w "%{http_code}" "$url" || true)"

  if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    status_ok "$label ($http_code)"
  else
    status_fail "$label ($http_code)"
    echo "  URL: $url"
    echo "  BODY: $(cat "$temp_body")"
  fi

  rm -f "$temp_body"
}

download_request() {
  local url="$1"
  local output_file="$2"
  local label="$3"
  local http_code

  http_code="$(curl -sS -L -H "token: $TOKEN" -o "$output_file" -w "%{http_code}" "$url" || true)"

  if [[ "$http_code" =~ ^2[0-9][0-9]$ ]] && [[ -s "$output_file" ]]; then
    status_ok "$label ($http_code) -> $output_file"
  else
    status_fail "$label ($http_code)"
    echo "  URL: $url"
    if [[ -f "$output_file" ]]; then
      echo "  SIZE: $(wc -c < "$output_file") bytes"
    fi
  fi
}

build_query() {
  local query="?fromDate=$FROM_DATE&toDate=$TO_DATE"

  if [[ -n "$CITY" ]]; then
    query="$query&city=$CITY"
  fi

  if [[ -n "$ROUTE_ID" ]]; then
    query="$query&routeId=$ROUTE_ID"
  fi

  printf "%s" "$query"
}

echo "== Meu Busao Heroku graph checks =="
echo "BASE_URL=$BASE_URL"
echo "FROM_DATE=$FROM_DATE"
echo "TO_DATE=$TO_DATE"
echo "CITY=${CITY:-<all>}"
echo "ROUTE_ID=${ROUTE_ID:-<all>}"
echo

LOGIN_RESPONSE="$(curl -sS -H "id: $IDENTIFICATOR" "$BASE_URL/login" || true)"
TOKEN="$(printf "%s" "$LOGIN_RESPONSE" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin).get("token", ""))' 2>/dev/null || true)"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: token could not be extracted from /login response."
  echo "Response: $LOGIN_RESPONSE"
  exit 1
fi

echo "Token acquired: ${TOKEN:0:18}..."
echo

QUERY="$(build_query)"

json_request "POST" "$BASE_URL/admin/setupMyBusLoggingDatabase" "bootstrap mybus"

json_request "GET" "$BASE_URL/logs/application-usage/timeline$QUERY" "application usage timeline"
json_request "GET" "$BASE_URL/logs/application-usage/summary$QUERY" "application usage summary"
json_request "GET" "$BASE_URL/logs/line-utilization/timeline$QUERY" "line utilization timeline"
json_request "GET" "$BASE_URL/logs/line-utilization/summary$QUERY" "line utilization summary"

download_request "$BASE_URL/logs/export/application-usage.csv$QUERY" "$OUT_DIR/application_usage_export.csv" "export application usage csv"
download_request "$BASE_URL/logs/export/line-utilization.csv$QUERY" "$OUT_DIR/line_utilization_export.csv" "export line utilization csv"
download_request "$BASE_URL/logs/export/dashboard.pdf$QUERY" "$OUT_DIR/dashboard_export.pdf" "export dashboard pdf"

echo
echo "== Summary =="
echo "Pass: $PASS_COUNT"
echo "Fail: $FAIL_COUNT"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  exit 1
fi
