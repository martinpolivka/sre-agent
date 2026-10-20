import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import demo


class IncidentThreadTests(unittest.TestCase):
    def setUp(self):
        self.since = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        self.title = demo.SCENARIOS["nsg"]["symptom_alert"]

    def thread(self, thread_id, title, created):
        return {
            "id": thread_id,
            "source": "Incident",
            "createdTimestamp": created.isoformat(),
            "incidentDetails": {"incidentTitle": title},
        }

    def resolve(self, threads):
        response = Mock(status_code=200)
        response.json.return_value = {"value": threads}
        with patch.object(demo, "_agent_dataplane_endpoint", return_value="https://agent.invalid"), \
                patch.object(demo, "_dataplane_token", return_value="test-token"), \
                patch.object(demo.requests, "get", return_value=response):
            return demo.resolve_incident_thread({}, self.since, expected_title=self.title)

    def test_native_alert_correlates_only_its_own_thread(self):
        threads = [
            self.thread("other", "Zava-portal-5xx-elevated", self.since + timedelta(seconds=20)),
            self.thread("current", self.title, self.since + timedelta(seconds=5)),
        ]
        self.assertEqual(self.resolve(threads), "current")

    def test_previous_run_and_other_scenarios_do_not_count(self):
        threads = [
            self.thread("other", "Zava-portal-5xx-elevated", self.since),
            self.thread("stale", self.title, self.since - timedelta(minutes=5)),
        ]
        self.assertIsNone(self.resolve(threads))


class NativeMonitorTests(unittest.TestCase):
    def test_native_alert_surfaces_agent_engagement_and_link(self):
        started = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        now = started
        probes = 0

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz) if tz else now.replace(tzinfo=None)

        def advance(seconds):
            nonlocal now
            now += timedelta(seconds=seconds)

        def probe(*_args, **_kwargs):
            nonlocal probes
            probes += 1
            healthy = probes > 1
            return healthy, 200 if healthy else 502, 10

        cfg = {
            "appgw_url": "https://portal.invalid",
            "subscription": "subscription",
            "resource_group": "resource-group",
            "agent_name": "agent",
            "pagerduty": {"api_token": ""},
        }
        with patch.object(demo, "datetime", Clock), \
                patch.object(demo.time, "sleep", side_effect=advance), \
                patch.object(demo, "Live"), \
                patch.object(demo, "probe", side_effect=probe), \
                patch.object(demo, "poll_azmon_alert", return_value=True), \
                patch.object(demo, "resolve_incident_thread", return_value="native-thread") as resolve, \
                patch.object(demo, "_report") as report:
            demo.monitor(cfg, demo.SCENARIOS["nsg"], auto_fix=False)

        resolve.assert_called_once_with(
            cfg, started, expected_title="Zava-quiz-endpoint-unavailable"
        )
        result = report.call_args.args
        self.assertTrue(result[3], "The native incident thread proves agent engagement")
        self.assertTrue(result[4], "Recovery still requires an observed outage")
        self.assertTrue(result[7])
        self.assertTrue(result[9].endswith("/views/thread/native-thread"))


if __name__ == "__main__":
    unittest.main()
