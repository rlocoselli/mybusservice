"""Check configured GTFS Realtime feeds without exposing provider credentials."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from threading import Lock
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2


FEED_TYPES = {
    "tripUpdates": ("trip_update", 90),
    "vehiclePositions": ("vehicle", 90),
    "serviceAlerts": ("alert", 600),
}
MAX_FEED_BYTES = 5 * 1024 * 1024
CACHE_SECONDS = 30
_cache = {}
_cache_lock = Lock()


def configured_feeds():
    raw = os.getenv("GTFS_REALTIME_FEEDS", "{}")
    try:
        configuration = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("GTFS_REALTIME_FEEDS must be valid JSON") from error
    if not isinstance(configuration, dict):
        raise ValueError("GTFS_REALTIME_FEEDS must map city IDs to feeds")

    result = {}
    for city, feeds in configuration.items():
        if not isinstance(city, str) or not city or not isinstance(feeds, dict):
            raise ValueError("Each city must have a feed object")
        result[city] = {}
        for feed_type, value in feeds.items():
            if feed_type not in FEED_TYPES:
                raise ValueError("Unknown GTFS Realtime feed type")
            entry = {"url": value} if isinstance(value, str) else value
            if not isinstance(entry, dict) or not isinstance(entry.get("url"), str):
                raise ValueError("Each feed needs a URL")
            url = entry["url"]
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("GTFS Realtime URLs must use HTTPS without embedded credentials")
            headers = entry.get("headers", {})
            if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
                raise ValueError("Feed headers must contain string names and values")
            result[city][feed_type] = {"url": url, "headers": headers}
    return result


def _check_feed(city, feed_type, entry):
    cache_key = (city, feed_type, entry["url"], tuple(sorted(entry["headers"].items())))
    now = monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]

    result = {"type": feed_type, "status": "error", "checkedAt": datetime.now(timezone.utc).isoformat()}
    message = None
    try:
        request = Request(entry["url"], headers={"Accept": "application/x-protobuf", **entry["headers"]})
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise HTTPError(entry["url"], response.status, "Unexpected status", None, None)
            payload = response.read(MAX_FEED_BYTES + 1)
        if len(payload) > MAX_FEED_BYTES:
            result["detail"] = "Feed exceeds size limit"
        else:
            message = gtfs_realtime_pb2.FeedMessage()
            message.ParseFromString(payload)
            if not message.IsInitialized():
                result["detail"] = "Invalid GTFS Realtime protobuf"
                message = None
            else:
                entity_field, freshness_seconds = FEED_TYPES[feed_type]
                result["entityCount"] = sum(entity.HasField(entity_field) for entity in message.entity)
                timestamp = message.header.timestamp if message.header.HasField("timestamp") else None
                if timestamp:
                    result["feedTimestamp"] = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                    age = max(0, int(datetime.now(timezone.utc).timestamp() - timestamp))
                    result["ageSeconds"] = age
                    result["status"] = "stale" if age > freshness_seconds else ("empty" if not result["entityCount"] else "ok")
                else:
                    result["status"] = "no_timestamp"
    except HTTPError as error:
        result["detail"] = f"HTTP {error.code}"
    except (URLError, TimeoutError, OSError):
        result["detail"] = "Feed could not be reached"
    except (DecodeError, ValueError, OverflowError):
        result["detail"] = "Invalid GTFS Realtime protobuf"

    with _cache_lock:
        _cache[cache_key] = (now, result, message)
    return result


def _translated_text(value, language):
    translations = value.translation
    preferred = language.lower().split("-")[0]
    match = next((item for item in translations if item.language.lower().split("-")[0] == preferred), None)
    return (match or (translations[0] if translations else None)).text if translations else ""


def get_realtime_entities(city, feed_type, language="pt"):
    """Return fresh, bounded public vehicle positions or service alerts."""
    if feed_type not in ("vehiclePositions", "serviceAlerts"):
        raise ValueError("Unsupported realtime entity type")
    entry = configured_feeds().get(city, {}).get(feed_type)
    if not entry:
        return {"supported": False, "connected": False, "status": "not_configured", "items": []}

    status = _check_feed(city, feed_type, entry)
    result = {"supported": True, "connected": status["status"] in ("ok", "empty"),
              "status": status["status"], "feedTimestamp": status.get("feedTimestamp"), "items": []}
    if not result["connected"]:
        return result

    cache_key = (city, feed_type, entry["url"], tuple(sorted(entry["headers"].items())))
    with _cache_lock:
        message = _cache[cache_key][2]
    if message is None:
        return result

    now = datetime.now(timezone.utc).timestamp()
    if feed_type == "vehiclePositions":
        for entity in message.entity:
            if not entity.HasField("vehicle") or not entity.vehicle.HasField("position"):
                continue
            vehicle = entity.vehicle
            timestamp = vehicle.timestamp if vehicle.HasField("timestamp") else message.header.timestamp
            if not timestamp or not -30 <= now - timestamp <= 90:
                continue
            position = vehicle.position
            if not -90 <= position.latitude <= 90 or not -180 <= position.longitude <= 180:
                continue
            result["items"].append({
                "vehicle_id": vehicle.vehicle.id if vehicle.HasField("vehicle") else entity.id,
                "route_id": vehicle.trip.route_id if vehicle.HasField("trip") else "",
                "lat": position.latitude,
                "lon": position.longitude,
                "timestamp": timestamp,
            })
    else:
        for entity in message.entity:
            if not entity.HasField("alert"):
                continue
            alert = entity.alert
            if alert.active_period and not any(
                (not period.HasField("start") or period.start <= now)
                and (not period.HasField("end") or now <= period.end)
                for period in alert.active_period
            ):
                continue
            result["items"].append({
                "id": entity.id,
                "title": _translated_text(alert.header_text, language) if alert.HasField("header_text") else "",
                "description": _translated_text(alert.description_text, language) if alert.HasField("description_text") else "",
                "route_ids": sorted({selector.route_id for selector in alert.informed_entity if selector.HasField("route_id")}),
                "effect": alert.effect if alert.HasField("effect") else None,
            })
    result["items"] = result["items"][:500]
    return result


def get_realtime_status(city=None, known_cities=()):
    configuration = configured_feeds()
    cities = [city] if city else sorted(set(configuration) | set(known_cities))
    tasks = [(name, feed_type, entry)
             for name in cities
             for feed_type, entry in configuration.get(name, {}).items()]
    with ThreadPoolExecutor(max_workers=6) as executor:
        checked = list(executor.map(lambda task: _check_feed(*task), tasks))

    results = {name: {"city": name, "feeds": [], "status": "not_configured"} for name in cities}
    for (name, _, _), feed in zip(tasks, checked):
        results[name]["feeds"].append(feed)
    for result in results.values():
        if result["feeds"]:
            statuses = {feed["status"] for feed in result["feeds"]}
            result["status"] = "error" if "error" in statuses else "stale" if "stale" in statuses else "no_timestamp" if "no_timestamp" in statuses else "empty" if statuses == {"empty"} else "ok"
    return list(results.values())
