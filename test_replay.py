import json
import os
import unittest

import replay

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

FAKE_SECRETS = ["FAKE_SECRET_TOKEN_12345", "FAKE_COOKIE_VALUE_67890",
                "FAKE_LOG_TOKEN_abcde"]


def load(name):
    return replay.load_capture(os.path.join(FIXTURES, name))


class RedactTests(unittest.TestCase):
    def test_bearer_token_removed(self):
        out = replay.redact("Authorization: Bearer abcdefgh12345678")
        self.assertNotIn("abcdefgh12345678", out)
        self.assertIn("REDACTED", out)

    def test_key_value_secret_removed(self):
        out = replay.redact("POST /x token=hunter2secret -> 403")
        self.assertNotIn("hunter2secret", out)

    def test_redact_is_idempotent(self):
        once = replay.redact("password=abc12345")
        self.assertEqual(once, replay.redact(once))


class ValidateTests(unittest.TestCase):
    def test_missing_url_rejected(self):
        with self.assertRaises(replay.CaptureError):
            replay.validate_capture({"steps": []})

    def test_non_list_section_rejected(self):
        with self.assertRaises(replay.CaptureError):
            replay.validate_capture({"url": "https://x", "steps": "no"})


class TimelineTests(unittest.TestCase):
    def test_events_sorted_by_t(self):
        cap = load("planted-bug.json")
        events, failures = replay.build_timeline(cap)
        ts = [e["t"] for e in events]
        self.assertEqual(ts, sorted(ts))

    def test_repeated_console_errors_deduped(self):
        cap = load("planted-bug.json")
        events, _ = replay.build_timeline(cap)
        errors = [e for e in events if e["kind"] == "console/error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["count"], 3)


class PlantedBugTests(unittest.TestCase):
    """The owner's agreed planted-bug acceptance tests."""

    def test_bug_capture_fails_and_names_403(self):
        cap = load("planted-bug.json")
        verdict, failures = replay.check_capture(cap)
        self.assertEqual(verdict, "BUG REPRODUCED")
        self.assertTrue(any("403" in f and "200" in f for f in failures),
                        failures)
        report, _, _ = replay.build_report(cap)
        self.assertIn("BUG REPRODUCED", report)
        self.assertIn("403", report)
        self.assertIn("#pay-button", report)  # the step is on the timeline

    def test_fixed_capture_passes(self):
        cap = load("planted-bug-fixed.json")
        verdict, failures = replay.check_capture(cap)
        self.assertEqual(verdict, "ALL EXPECTATIONS PASS")
        self.assertEqual(failures, [])

    def test_healthy_capture_passes(self):
        cap = load("healthy.json")
        verdict, _ = replay.check_capture(cap)
        self.assertEqual(verdict, "ALL EXPECTATIONS PASS")

    def test_unexpected_4xx_fails_without_expected_status(self):
        raw = {"url": "https://x.example",
               "network": [{"t": 1, "method": "GET",
                            "url": "https://x.example/a", "status": 500}]}
        verdict, failures = replay.check_capture(
            replay.validate_capture(raw))
        self.assertEqual(verdict, "BUG REPRODUCED")

    def test_secrets_appear_nowhere(self):
        cap = load("planted-bug.json")
        report, _, _ = replay.build_report(cap)
        spec = replay.generate_spec(cap)
        for secret in FAKE_SECRETS:
            self.assertNotIn(secret, report)
            self.assertNotIn(secret, spec)


class SpecTests(unittest.TestCase):
    def test_spec_contains_steps_and_assertions(self):
        cap = load("planted-bug.json")
        spec = replay.generate_spec(cap)
        self.assertIn("@playwright/test", spec)
        self.assertIn("page.goto", spec)
        self.assertIn("#pay-button", spec)
        self.assertIn("expected POST", spec)
        self.assertIn("toEqual([])", spec)


class RecordSkipTests(unittest.TestCase):
    def test_record_without_playwright_is_honest_skip(self):
        try:
            import playwright  # noqa: F401
            self.skipTest("playwright installed; skip path not applicable")
        except ImportError:
            pass
        cap, reason = replay.record_capture("https://example.com")
        self.assertIsNone(cap)
        self.assertIn("playwright not installed", reason)


if __name__ == "__main__":
    unittest.main()
