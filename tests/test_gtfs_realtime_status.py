import io
import json
import os
import unittest
from time import time
from unittest.mock import patch

import jwt
from google.transit import gtfs_realtime_pb2

import app as service
import gtfs_realtime_status as realtime


class FakeResponse(io.BytesIO):
    status = 200


class RealtimeStatusTests(unittest.TestCase):
    def setUp(self):
        realtime._cache.clear()
        self.config = {"Grenoble_France": {
            "tripUpdates": {"url": "https://provider.example/trips.pb", "headers": {"X-API-Key": "private-key"}}
        }}

    def feed_bytes(self, timestamp):
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.timestamp = timestamp
        feed.entity.add(id="trip-1").trip_update.trip.trip_id = "trip-1"
        return feed.SerializeToString()

    def test_valid_feed_and_stale_feed(self):
        with patch.dict(os.environ, {"GTFS_REALTIME_FEEDS": json.dumps(self.config)}):
            with patch.object(realtime, "urlopen", return_value=FakeResponse(self.feed_bytes(int(time())))):
                current = realtime.get_realtime_status("Grenoble_France")[0]
            self.assertEqual(current["status"], "ok")
            self.assertEqual(current["feeds"][0]["entityCount"], 1)
            self.assertNotIn("private-key", str(current))
            self.assertNotIn("provider.example", str(current))

            realtime._cache.clear()
            with patch.object(realtime, "urlopen", return_value=FakeResponse(self.feed_bytes(int(time()) - 120))):
                stale = realtime.get_realtime_status("Grenoble_France")[0]
            self.assertEqual(stale["status"], "stale")

    def test_invalid_feed_and_unconfigured_city(self):
        with patch.dict(os.environ, {"GTFS_REALTIME_FEEDS": json.dumps(self.config)}):
            with patch.object(realtime, "urlopen", return_value=FakeResponse(b"not protobuf")):
                broken = realtime.get_realtime_status("Grenoble_France")[0]
            self.assertEqual(broken["status"], "error")
            self.assertEqual(realtime.get_realtime_status("Unknown_City")[0]["status"], "not_configured")
            all_cities = realtime.get_realtime_status(known_cities=["Grenoble_France", "Unknown_City"])
            self.assertEqual([row["city"] for row in all_cities], ["Grenoble_France", "Unknown_City"])

    def test_admin_endpoint_rejects_regular_token_and_hides_credentials(self):
        admin = jwt.encode({"user": "admin", "scope": "admin"}, service.app.config["SECRET_KEY"])
        if isinstance(admin, bytes):
            admin = admin.decode()
        with patch.dict(os.environ, {"GTFS_REALTIME_FEEDS": json.dumps(self.config)}):
            with patch.object(realtime, "urlopen", return_value=FakeResponse(self.feed_bytes(int(time())))):
                with patch.object(service, "is_logging_database_ready", return_value=False):
                    client = service.app.test_client()
                    self.assertEqual(client.get("/admin/gtfs-realtime/status?city=Grenoble_France").status_code, 403)
                    response = client.get("/admin/gtfs-realtime/status?city=Grenoble_France", headers={"token": admin})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["status"], "ok")
        self.assertNotIn(b"private-key", response.data)
        self.assertNotIn(b"provider.example", response.data)

    def test_fresh_vehicle_and_active_alert_are_exposed_without_feed_url(self):
        now = int(time())
        self.config["Grenoble_France"]["vehiclePositions"] = "https://provider.example/vehicles.pb"
        self.config["Grenoble_France"]["serviceAlerts"] = "https://provider.example/alerts.pb"
        vehicle_feed = gtfs_realtime_pb2.FeedMessage()
        vehicle_feed.header.gtfs_realtime_version = "2.0"
        vehicle_feed.header.timestamp = now
        vehicle = vehicle_feed.entity.add(id="vehicle-1").vehicle
        vehicle.trip.route_id = "12"
        vehicle.vehicle.id = "bus-1"
        vehicle.position.latitude = 45.188
        vehicle.position.longitude = 5.724
        vehicle.timestamp = now
        alert_feed = gtfs_realtime_pb2.FeedMessage()
        alert_feed.header.gtfs_realtime_version = "2.0"
        alert_feed.header.timestamp = now
        alert = alert_feed.entity.add(id="alert-1").alert
        alert.informed_entity.add(route_id="12")
        alert.header_text.translation.add(text="Déviation", language="fr")
        alert.header_text.translation.add(text="Desvio", language="pt")
        alert.active_period.add(start=now - 30, end=now + 300)

        def fetch(request, timeout):
            payload = alert_feed if "alerts" in request.full_url else vehicle_feed
            return FakeResponse(payload.SerializeToString())

        with patch.dict(os.environ, {"GTFS_REALTIME_FEEDS": json.dumps(self.config)}):
            with patch.object(realtime, "urlopen", side_effect=fetch):
                vehicles = realtime.get_realtime_entities("Grenoble_France", "vehiclePositions")
                alerts = realtime.get_realtime_entities("Grenoble_France", "serviceAlerts", "fr")
        self.assertEqual(vehicles["items"][0]["route_id"], "12")
        self.assertEqual(alerts["items"][0]["title"], "Déviation")
        self.assertNotIn("provider.example", str(vehicles) + str(alerts))


if __name__ == "__main__":
    unittest.main()
