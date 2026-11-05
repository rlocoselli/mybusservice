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


if __name__ == "__main__":
    unittest.main()
