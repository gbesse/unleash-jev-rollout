import io
import json
import tempfile
import unittest
from pathlib import Path

from jev import fixture_evaluator, normalize
from rollout import make_app, metrics, open_state, process, validate_config


class RolloutTests(unittest.TestCase):
    def setUp(self):
        with open("examples/policy.json", encoding="utf-8") as source:
            self.policy = json.load(source)
        with open("examples/config.json", encoding="utf-8") as source:
            self.config = validate_config(json.load(source))
        self.event = {"id": "one", "flag": "checkout_v2", "environment": "production",
                      "text": "Payment fails since checkout v2."}

    def test_idempotence_and_metric(self):
        with open_state(":memory:") as db:
            judge = lambda _: normalize("regression", 0.96, self.policy)
            self.assertFalse(process(self.event, db, self.policy, judge, self.config)["cached"])
            self.assertTrue(process(self.event, db, self.policy, judge, self.config)["cached"])
            output = metrics(db, self.config, self.policy["version"])
        self.assertIn("jev_rollout_regressions_checkout_v2_production_total 1", output)
        self.assertIn('outcome="regression",policy_version="0.1.0"} 1', output)

    def test_low_confidence_is_review_not_regression(self):
        with open_state(":memory:") as db:
            process(self.event, db, self.policy,
                    lambda _: normalize("regression", 0.7, self.policy), self.config)
            output = metrics(db, self.config, self.policy["version"])
        self.assertIn("jev_rollout_regressions_checkout_v2_production_total 0", output)
        self.assertIn('outcome="review",policy_version="0.1.0"} 1', output)

    def test_rejects_unknown_flag_and_unauthorized_http(self):
        with open_state(":memory:") as db:
            with self.assertRaises(ValueError):
                process({**self.event, "flag": "unknown"}, db, self.policy,
                        lambda _: normalize("regression", 0.96, self.policy), self.config)
        with tempfile.TemporaryDirectory() as folder:
            app = make_app(str(Path(folder) / "state.sqlite"), "0123456789abcdef",
                           self.policy, lambda _: normalize("regression", 0.96, self.policy), self.config)
            body = json.dumps(self.event).encode()
            status = []
            environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/ingest",
                       "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
            b"".join(app(environ, lambda code, headers: status.append(code)))
            self.assertEqual(status[0], "401 Unauthorized")

    def test_metrics_endpoint_exports_dedicated_series(self):
        with tempfile.TemporaryDirectory() as folder:
            state = str(Path(folder) / "state.sqlite")
            with open_state(state) as db:
                process(self.event, db, self.policy,
                        lambda _: normalize("regression", 0.96, self.policy), self.config)
            app = make_app(state, "0123456789abcdef", self.policy, lambda _: None, self.config)
            status = []
            body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": "/metrics"},
                                lambda code, headers: status.append(code)))
            self.assertEqual(status[0], "200 OK")
            self.assertIn(b"jev_rollout_regressions_checkout_v2_production_total 1", body)


if __name__ == "__main__":
    unittest.main()
