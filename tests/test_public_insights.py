import unittest
from unittest.mock import patch

import app as service


class PublicInsightsTests(unittest.TestCase):
    def test_developer_key_reads_city_insights_but_not_admin_summary(self):
        with patch.object(service, "identify_key", return_value="website"), \
             patch.object(service, "is_logging_database_ready", return_value=True), \
             patch.object(service, "create_application_request_log"), \
             patch.object(service, "get_line_utilization_summary", return_value=[{"city":"Grenoble_France", "routeId":"12", "totalBoardings":7}]) as summary:
            client = service.app.test_client()
            headers = {"X-API-Key":"mb_live_example"}
            response = client.get("/insights/lines/Grenoble_France?routeId=12", headers=headers)
            denied = client.get("/logs/line-utilization/summary", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"][0]["totalBoardings"], 7)
        self.assertEqual(summary.call_args.kwargs["city"], "Grenoble_France")
        self.assertEqual(summary.call_args.kwargs["route_id"], "12")
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
