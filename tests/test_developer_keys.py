import unittest
from unittest.mock import patch

import jwt
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app as service
import developer_keys as keys


class DeveloperKeyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        keys._ready.clear()
        self.engine_patch = patch.object(keys, "_get_engine", return_value=self.engine)
        self.logging_patch = patch.object(service, "is_logging_database_ready", return_value=False)
        self.engine_patch.start()
        self.logging_patch.start()
        self.client = service.app.test_client()

    def tearDown(self):
        self.logging_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()

    def test_create_use_revoke_and_admin_isolation(self):
        account = {"username": "company_1", "password": "a strong example password"}
        self.assertEqual(self.client.post("/developer/register", json=account).status_code, 201)
        created = self.client.post("/developer/keys", json={**account, "action": "create", "name": "Schedule app"})
        self.assertEqual(created.status_code, 201)
        raw = created.get_json()["key"]
        self.assertEqual(keys.identify_key(raw), "company_1")
        self.assertNotIn("key", self.client.post("/developer/keys", json={**account, "action": "list"}).get_json()["keys"][0])

        read_route = service.token_required(lambda: service.jsonify({"ok": True}))
        with service.app.test_request_context("/getRoutes/Grenoble_France", headers={"X-API-Key": raw}):
            self.assertEqual(read_route().status_code, 200)
        self.assertEqual(self.client.get("/admin/users", headers={"token": raw}).status_code, 403)
        legacy = jwt.encode({"user": "legacy"}, service.app.config["SECRET_KEY"])
        if isinstance(legacy, bytes):
            legacy = legacy.decode()
        self.assertEqual(self.client.get("/admin/users", headers={"token": legacy}).status_code, 403)

        self.assertEqual(self.client.post("/developer/keys", json={**account, "action": "revoke", "keyId": created.get_json()["id"]}).status_code, 200)
        self.assertIsNone(keys.identify_key(raw))

    def test_password_never_enters_request_log_payload(self):
        with service.app.test_request_context("/developer/register", method="POST", json={"username": "x", "password": "secret"}):
            payload = service.build_request_log_payload(service.app.response_class(status=400))
        self.assertIsNone(payload["request_payload"])


if __name__ == "__main__":
    unittest.main()
