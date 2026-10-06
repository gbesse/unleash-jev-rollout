"""Turn qualitative rollout feedback into durable Prometheus counters."""
import argparse
from contextlib import contextmanager
import hmac
import io
import json
import os
from pathlib import Path
import re
import sqlite3
from wsgiref.simple_server import make_server

from jev import evaluate, fixture_evaluator

MAX_BODY = 32 * 1024
LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@contextmanager
def open_state(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, flag TEXT NOT NULL, environment TEXT NOT NULL, choice TEXT NOT NULL, outcome TEXT NOT NULL, probability REAL NOT NULL, policy_version TEXT NOT NULL)")
    try:
        yield db
    finally:
        db.close()


def validate_config(config):
    if not isinstance(config, dict) or not isinstance(config.get("flags"), list) or not isinstance(config.get("environments"), list):
        raise ValueError("invalid_config")
    if any(not isinstance(x, str) or not LABEL.fullmatch(x)
           for x in config["flags"] + config["environments"]):
        raise ValueError("invalid_config")
    return config


def process(event, db, policy, judge, config):
    if not isinstance(event, dict):
        raise ValueError("invalid_event")
    event_id, flag, environment, text = (event.get(k) for k in ("id", "flag", "environment", "text"))
    if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 128
            or not isinstance(flag, str) or flag not in config["flags"]
            or not isinstance(environment, str) or environment not in config["environments"]
            or not isinstance(text, str) or not text.strip() or len(text) > 16000):
        raise ValueError("invalid_event")
    existing = db.execute("SELECT flag,environment,choice,outcome,probability,policy_version FROM feedback WHERE id=?",
                          (event_id,)).fetchone()
    if existing:
        if existing[0] != flag or existing[1] != environment:
            raise ValueError("id_conflict")
        return {"id": event_id, "flag": existing[0], "environment": existing[1],
                "choice": existing[2], "outcome": existing[3], "probability": existing[4],
                "policy_version": existing[5], "cached": True}
    result = judge("Flag: " + flag + "\nEnvironment: " + environment + "\nFeedback: " + text)
    db.execute("INSERT INTO feedback VALUES(?,?,?,?,?,?,?)",
               (event_id, flag, environment, result["choice"], result["outcome"],
                result["probability"], result["policy_version"]))
    db.commit()
    return {"id": event_id, "flag": flag, "environment": environment, **result,
            "cached": False}


def metrics(db, config, version):
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version):
        raise ValueError("invalid_policy_version")
    output = ["# HELP jev_rollout_feedback_total Versioned Jev rollout feedback decisions.",
              "# TYPE jev_rollout_feedback_total counter"]
    counts = {(flag, env, outcome): count for flag, env, outcome, count in
              db.execute("SELECT flag,environment,outcome,COUNT(*) FROM feedback WHERE policy_version=? GROUP BY flag,environment,outcome", (version,))}
    dedicated = []
    for flag in config["flags"]:
        for environment in config["environments"]:
            for outcome in ("regression", "no_regression", "review"):
                count = counts.get((flag, environment, outcome), 0)
                output.append(f'jev_rollout_feedback_total{{flag="{flag}",environment="{environment}",outcome="{outcome}",policy_version="{version}"}} {count}')
            # Unleash external safeguards cannot filter custom labels: one metric name per flag/env.
            name = f"jev_rollout_regressions_{flag}_{environment}_total"
            dedicated.append(f"# TYPE {name} counter")
            dedicated.append(f"{name} {counts.get((flag, environment, 'regression'), 0)}")
    return "\n".join(output + dedicated) + "\n"


def make_app(state_path, token, policy, judge, config):
    if not isinstance(token, str) or len(token) < 16:
        raise ValueError("invalid_ingest_token")
    config = validate_config(config)

    def app(environ, start_response):
        method, path = environ.get("REQUEST_METHOD"), environ.get("PATH_INFO")
        if method == "GET" and path == "/metrics":
            with open_state(state_path) as db:
                body = metrics(db, config, policy["version"]).encode()
            start_response("200 OK", [("Content-Type", "text/plain; version=0.0.4"),
                                      ("Content-Length", str(len(body)))])
            return [body]
        if method != "POST" or path != "/ingest":
            start_response("404 Not Found", [("Content-Type", "application/json")]); return [b"{}"]
        if not hmac.compare_digest(environ.get("HTTP_AUTHORIZATION", ""), "Bearer " + token):
            start_response("401 Unauthorized", [("Content-Type", "application/json")]); return [b"{}"]
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = -1
        if length < 1 or length > MAX_BODY:
            start_response("413 Payload Too Large", [("Content-Type", "application/json")]); return [b"{}"]
        try:
            event = json.loads(environ["wsgi.input"].read(length))
            with open_state(state_path) as db:
                result = process(event, db, policy, judge, config)
        except (json.JSONDecodeError, ValueError):
            start_response("400 Bad Request", [("Content-Type", "application/json")]); return [b"{}"]
        except Exception:
            start_response("503 Service Unavailable", [("Content-Type", "application/json")]); return [b"{}"]
        body = json.dumps(result).encode()
        start_response("200 OK", [("Content-Type", "application/json"),
                                  ("Content-Length", str(len(body)))])
        return [body]
    return app


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--demo", action="store_true")
    modes.add_argument("--serve", action="store_true")
    modes.add_argument("--metrics", action="store_true")
    parser.add_argument("--state", default=".local/rollout.sqlite")
    args = parser.parse_args()
    with open("examples/policy.json", encoding="utf-8") as source:
        policy = json.load(source)
    with open("examples/config.json", encoding="utf-8") as source:
        config = validate_config(json.load(source))
    if args.demo:
        with open("examples/fixtures.json", encoding="utf-8") as source:
            judge = fixture_evaluator(json.load(source), policy)
        with open_state(":memory:") as db, open("examples/feedback.jsonl", encoding="utf-8") as source:
            for line in source:
                process(json.loads(line), db, policy, judge, config)
            print(metrics(db, config, policy["version"]), end="")
        return
    if args.metrics:
        with open_state(args.state) as db:
            print(metrics(db, config, policy["version"]), end="")
        return
    key = os.environ["TYPESAFE_API_KEY"]
    app = make_app(args.state, os.environ["JEV_INGEST_TOKEN"], policy,
                   lambda text: evaluate(text, policy, key), config)
    with make_server("127.0.0.1", int(os.environ.get("PORT", "8093")), app) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
