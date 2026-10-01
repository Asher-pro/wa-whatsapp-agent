"""Offline tests for scripts/wa_ops.py.

A local HTTP server stands in for Render and Green API and records every request, so we
can assert the exact shapes we send match the providers' documented APIs without any
real account. Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wa_ops  # noqa: E402

wa_ops.time.sleep = lambda *_: None  # never wait in tests


class Recorder(BaseHTTPRequestHandler):
    routes: dict = {}
    calls: list = []

    def log_message(self, *a):  # silence
        pass

    def _handle(self, verb):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null") if length else None
        Recorder.calls.append({"verb": verb, "path": self.path, "body": body,
                               "headers": {k.lower(): v for k, v in self.headers.items()}})
        for (rverb, prefix), responder in Recorder.routes.items():
            if rverb == verb and self.path.startswith(prefix):
                status, payload = responder(self.path, body) if callable(responder) else responder
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                raw = b"" if payload is None else json.dumps(payload).encode()
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class OpsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        wa_ops.RENDER_API = cls.base + "/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Recorder.routes = {}
        Recorder.calls = []
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / ".env").write_text(
            "GREEN_API_URL={base}\nGREEN_API_INSTANCE=1101\nGREEN_API_TOKEN=greentoken123456\n"
            "RENDER_API_KEY=rnd_abcdefghijklmnop\nANTHROPIC_API_KEY=sk-ant-api03-secretsecret\n"
            "WEBHOOK_TOKEN=whsecret_abcdefgh\nLLM_PROVIDER=anthropic\nLLM_MODEL=claude-haiku-4-5\n"
            .format(base=self.base))

    def tearDown(self):
        self.tmp.cleanup()

    def run_ops(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = wa_ops.main(["--project", str(self.dir), *argv])
        out = buf.getvalue()
        return code, (json.loads(out) if out.strip() else None), out


class TestLocalFiles(OpsTestCase):
    def test_env_roundtrip_and_gitignore(self):
        p = wa_ops.Project(self.dir)
        p.write_env("NEW_KEY", "value with spaces # and hash")
        self.assertEqual(p.read_env()["NEW_KEY"], "value with spaces # and hash")
        p.write_env("NEW_KEY", "plain")
        self.assertEqual(p.read_env()["NEW_KEY"], "plain")
        self.assertEqual((self.dir / ".env").read_text().count("NEW_KEY="), 1)
        self.assertIn(".env", (self.dir / ".gitignore").read_text().splitlines())

    def test_env_set_never_echoes_value(self):
        code, out, raw = self.run_ops("env", "set", "SECRET_THING", "supersecretvalue")
        self.assertEqual(code, 0)
        self.assertNotIn("supersecretvalue", raw)
        self.assertEqual(out["length"], len("supersecretvalue"))

    def test_env_generate(self):
        code, out, raw = self.run_ops("env", "set", "WEBHOOK_TOKEN", "--generate")
        self.assertEqual(code, 0)
        token = wa_ops.Project(self.dir).read_env()["WEBHOOK_TOKEN"]
        self.assertGreaterEqual(len(token), 32)
        self.assertNotIn(token, raw)

    def test_redaction(self):
        data = {"GREEN_API_TOKEN": "abcdef123456", "note": "key sk-ant-api03-zzzzzzzzzzzz here",
                "url": "postgresql://postgres.ref:pa55word@aws-1-eu-central-1.pooler.supabase.com:5432/postgres",
                "key": "PUBLIC_NAME"}
        r = wa_ops.redact(data)
        self.assertNotIn("abcdef123456", json.dumps(r))
        self.assertNotIn("zzzzzzzzzzzz", r["note"])
        self.assertNotIn("pa55word", r["url"])
        self.assertEqual(r["key"], "PUBLIC_NAME")

    def test_state_migrate_v1_to_v2(self):
        v1 = {"version": 1, "current_stage": "maintain", "completed_stages": ["setup"],
              "render_url": "https://x.onrender.com", "render_service_id": "srv-1",
              "render_region": "frankfurt", "custom_future_key": 42}
        (self.dir / ".wa-state.json").write_text(json.dumps(v1))
        code, out, _ = self.run_ops("state", "migrate")
        self.assertEqual(code, 0)
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertEqual(st["version"], 2)
        self.assertEqual(st["render"], {"url": "https://x.onrender.com", "service_id": "srv-1", "region": "frankfurt"})
        self.assertNotIn("render_url", st)
        self.assertEqual(st["custom_future_key"], 42)
        self.assertEqual(st["drift_log"], [])
        self.assertNotIn("plugin_version", st)  # absence = needs upgrade audit
        # idempotent
        code, out, _ = self.run_ops("state", "migrate")
        self.assertFalse(out["migrated"])

    def test_only_build_stamps_plugin_version(self):
        (self.dir / ".wa-state.json").write_text(json.dumps({"version": 2, "current_stage": "connect",
                                                             "completed_stages": ["setup", "characterize", "build", "deploy"]}))
        self.run_ops("state", "stage-done", "deploy", "connect")
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertNotIn("plugin_version", st)  # an old bot must still be offered the upgrade audit
        self.run_ops("state", "stage-done", "build", "deploy")
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertEqual(st["plugin_version"], wa_ops.plugin_version())
        self.assertEqual(st["current_stage"], "deploy")

    def test_migrate_unsticks_v2_bot_at_deploy(self):
        (self.dir / "spec.json").write_text(json.dumps({"tools": ["reminders", "google_calendar", "gmail"]}))
        v1 = {"version": 1, "current_stage": "deploy", "completed_stages": ["setup", "characterize", "build", "deploy"],
              "connected_tools": ["google_calendar"], "render_service_id": "srv-1"}
        (self.dir / ".wa-state.json").write_text(json.dumps(v1))
        self.run_ops("state", "migrate")
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertEqual(st["current_stage"], "connect")  # gmail still to connect
        st["connected_tools"].append("gmail"); st["current_stage"] = "deploy"
        (self.dir / ".wa-state.json").write_text(json.dumps(st))
        self.run_ops("state", "migrate")
        self.assertEqual(json.loads((self.dir / ".wa-state.json").read_text())["current_stage"], "maintain")

    def test_non_secret_env_values_are_not_redacted(self):
        self.run_ops("state", "init")
        self.run_ops("state", "set", "llm.model=claude-haiku-4-5", "llm.provider=anthropic")
        code, out, raw = self.run_ops("state", "get", "llm")
        self.assertEqual(out, {"model": "claude-haiku-4-5", "provider": "anthropic"})
        code, out, raw = self.run_ops("doctor")
        self.assertNotIn("greentoken123456", raw)

    def test_env_set_from_clipboard(self):
        original = wa_ops.read_clipboard
        wa_ops.read_clipboard = lambda: "  sk-ant-api03-fromclipboard\n"
        try:
            code, out, raw = self.run_ops("env", "set", "ANTHROPIC_API_KEY", "--from-clipboard")
        finally:
            wa_ops.read_clipboard = original
        self.assertEqual(code, 0)
        self.assertEqual(wa_ops.Project(self.dir).read_env()["ANTHROPIC_API_KEY"], "sk-ant-api03-fromclipboard")
        self.assertNotIn("fromclipboard", raw)
        self.assertNotIn("warning", out)
        wa_ops.read_clipboard = lambda: "postgresql://postgres.ref:[YOUR-PASSWORD]@aws-1-x.pooler.supabase.com:5432/postgres"
        try:
            code, out, raw = self.run_ops("env", "set", "DATABASE_URL", "--from-clipboard")
        finally:
            wa_ops.read_clipboard = original
        self.assertIn("YOUR-PASSWORD", out["warning"])

    def test_state_set_keeps_ids_as_strings(self):
        self.run_ops("state", "init")
        self.run_ops("state", "set", "green_api.instance_id=7105222798", "render.keep_awake=none",
                     'persistence_details={"provider": "supabase"}', "google.ok=true")
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertEqual(st["green_api"]["instance_id"], "7105222798")
        self.assertEqual(st["persistence_details"], {"provider": "supabase"})
        self.assertIs(st["google"]["ok"], True)

    def test_drift_is_scrubbed(self):
        self.run_ops("state", "init")
        self.run_ops("state", "drift", "--skill", "wa-setup", "--expected", "button X",
                     "--observed", "user 0501234567 dana@example.com saw button Y with rnd_abcdefghijklmnop")
        st = json.loads((self.dir / ".wa-state.json").read_text())
        observed = st["drift_log"][0]["observed"]
        self.assertNotIn("0501234567", observed)
        self.assertNotIn("dana@example.com", observed)
        self.assertNotIn("abcdefghijklmnop", observed)
        code, out, _ = self.run_ops("report-drift")
        self.assertEqual(out["unreported"], 1)
        self.assertIn("button Y", out["body"])

    def test_to_chat_id(self):
        self.assertEqual(wa_ops.to_chat_id("050-123 4567"), "972501234567@c.us")
        self.assertEqual(wa_ops.to_chat_id("+972501234567"), "972501234567@c.us")
        self.assertEqual(wa_ops.to_chat_id("120363@g.us"), "120363@g.us")
        with self.assertRaises(wa_ops.OpsError):
            wa_ops.to_chat_id("12")


class TestGreenApi(OpsTestCase):
    def test_configure_sends_standard_settings_with_bearer_token(self):
        settings = {"webhookUrl": "", "incomingWebhook": "no"}

        def set_settings(path, body):
            settings.update(body)
            return 200, {"saveSettings": True}

        Recorder.routes = {
            ("POST", "/waInstance1101/setSettings/greentoken123456"): set_settings,
            ("GET", "/waInstance1101/getSettings/greentoken123456"): lambda p, b: (200, dict(settings)),
        }
        code, out, raw = self.run_ops("green", "configure", "--webhook-url", "https://bot.onrender.com/webhook/green-api",
                                      "--webhook-token-from-env", "WEBHOOK_TOKEN")
        self.assertEqual(code, 0, raw)
        sent = [c for c in Recorder.calls if "setSettings" in c["path"]][0]["body"]
        self.assertEqual(sent["incomingWebhook"], "yes")
        self.assertEqual(sent["outgoingAPIMessageWebhook"], "no")
        self.assertEqual(sent["enableLidMode"], "no")
        self.assertEqual(sent["webhookUrlToken"], "Bearer whsecret_abcdefgh")
        self.assertNotIn("deviceWebhook", sent)  # temporarily unsupported per Green API docs
        self.assertNotIn("whsecret_abcdefgh", raw)
        self.assertTrue(out["verified"])

    def test_wid_and_errors(self):
        Recorder.routes = {("GET", "/waInstance1101/getSettings/"): (200, {"wid": "972501112222@c.us"})}
        code, out, _ = self.run_ops("green", "wid")
        self.assertEqual(out["bot_phone"], "972501112222")
        Recorder.routes = {("GET", "/waInstance1101/getStateInstance/"): (401, {"message": "no"})}
        code, out, _ = self.run_ops("green", "state")
        self.assertEqual(code, 1)
        self.assertIn("GREEN_API_TOKEN", out["hint"])

    def test_send_formats_chat_id(self):
        Recorder.routes = {("POST", "/waInstance1101/sendMessage/"): (200, {"idMessage": "ABC"})}
        code, out, _ = self.run_ops("green", "send", "0501234567", "בדיקה")
        self.assertEqual(code, 0)
        self.assertEqual(Recorder.calls[-1]["body"], {"chatId": "972501234567@c.us", "message": "בדיקה"})

    def test_chats_uses_get(self):
        Recorder.routes = {("GET", "/waInstance1101/getChats/"): (200, [
            {"id": "1@g.us", "name": "משפחה", "type": "group"}, {"id": "9725@c.us", "name": "x", "type": "user"},
            {"id": "old@g.us", "newChatId": "new@g.us", "name": "צוות", "type": "group"}])}
        code, out, _ = self.run_ops("green", "chats", "--groups")
        self.assertEqual([c["id"] for c in out], ["1@g.us", "new@g.us"])


class TestSmoke(OpsTestCase):
    def test_smoke_sends_token_and_quoted_shape(self):
        Recorder.routes = {("POST", "/webhook/green-api"): (200, {"reply": "שלום!"})}
        code, out, raw = self.run_ops("smoke", "--url", self.base, "--from", "050-123-4567", "--type", "quoted", "--text", "מה נשמע")
        self.assertEqual(code, 0, raw)
        call = Recorder.calls[-1]
        self.assertEqual(call["headers"]["authorization"], "Bearer whsecret_abcdefgh")
        self.assertEqual(call["headers"]["x-debug-sync"], "1")
        self.assertEqual(call["body"]["messageData"]["typeMessage"], "quotedMessage")
        self.assertEqual(call["body"]["messageData"]["extendedTextMessageData"]["text"], "מה נשמע")
        self.assertEqual(call["body"]["senderData"]["sender"], "972501234567@c.us")
        self.assertNotIn("whsecret_abcdefgh", raw)

    def test_smoke_no_auth(self):
        Recorder.routes = {("POST", "/webhook/green-api"): (401, {"detail": "unauthorized"})}
        code, out, _ = self.run_ops("smoke", "--url", self.base, "--from", "972501234567", "--no-auth")
        self.assertEqual(code, 1)
        self.assertNotIn("authorization", Recorder.calls[-1]["headers"])


class TestRender(OpsTestCase):
    def setUp(self):
        super().setUp()
        (self.dir / ".wa-state.json").write_text(json.dumps({"version": 2, "render": {}, "current_stage": "deploy"}))

    def test_create_service_body_matches_openapi(self):
        Recorder.routes = {
            ("GET", "/v1/owners"): (200, [{"owner": {"id": "tea-1", "name": "Dana", "type": "user"}, "cursor": "c"}]),
            ("POST", "/v1/services"): (201, {"service": {"id": "srv-9", "dashboardUrl": "https://dashboard.render.com/web/srv-9",
                                                          "serviceDetails": {"url": "https://roni.onrender.com"}},
                                             "deployId": "dep-1"}),
        }
        code, out, raw = self.run_ops("render", "create-service", "--name", "roni-whatsapp",
                                      "--repo", "https://github.com/dana/roni-whatsapp",
                                      "--env-keys", "GREEN_API_URL,GREEN_API_TOKEN,MISSING_KEY",
                                      "--env", "DATABASE_PATH=/data/conversations.db")
        self.assertEqual(code, 0, raw)
        body = [c for c in Recorder.calls if c["path"] == "/v1/services"][0]["body"]
        # required by OpenAPI: type, name, ownerId; web_service needs serviceDetails.runtime + both commands
        self.assertEqual(body["type"], "web_service")
        self.assertEqual(body["ownerId"], "tea-1")
        self.assertEqual(body["serviceDetails"]["runtime"], "python")
        self.assertIn("buildCommand", body["serviceDetails"]["envSpecificDetails"])
        self.assertIn("startCommand", body["serviceDetails"]["envSpecificDetails"])
        self.assertEqual(body["autoDeployTrigger"], "commit")
        self.assertNotIn("autoDeploy", body)  # deprecated field
        self.assertEqual([e["key"] for e in body["envVars"]], ["GREEN_API_URL", "GREEN_API_TOKEN", "DATABASE_PATH"])
        self.assertNotIn("greentoken123456", raw)
        st = json.loads((self.dir / ".wa-state.json").read_text())
        self.assertEqual(st["render"]["service_id"], "srv-9")
        self.assertEqual(st["render"]["owner_id"], "tea-1")
        self.assertEqual(out["url"], "https://roni.onrender.com")

    def test_free_plan_with_disk_is_refused_locally(self):
        Recorder.routes = {("GET", "/v1/owners"): (200, [{"owner": {"id": "tea-1"}}])}
        code, out, _ = self.run_ops("render", "create-service", "--name", "x", "--repo", "r", "--disk-gb", "1")
        self.assertEqual(code, 2)
        self.assertFalse(any(c["path"] == "/v1/services" for c in Recorder.calls))

    def test_wait_matches_pushed_commit_not_previous_live(self):
        listing = iter([
            [{"deploy": {"id": "dep-old", "status": "live", "createdAt": "2026-10-01T09:00:00Z", "commit": {"id": "aaaa1111"}}}],
            [{"deploy": {"id": "dep-new", "status": "build_in_progress", "createdAt": "2026-10-01T10:00:00Z", "commit": {"id": "bbbb2222"}}},
             {"deploy": {"id": "dep-old", "status": "live", "createdAt": "2026-10-01T09:00:00Z", "commit": {"id": "aaaa1111"}}}],
        ])
        single = iter(["update_in_progress", "live"])
        Recorder.routes = {
            ("GET", "/v1/services/srv-1/deploys?"): lambda p, b: (200, next(listing)),
            ("GET", "/v1/services/srv-1/deploys/dep-new"): lambda p, b: (200, {"id": "dep-new", "status": next(single),
                                                                               "commit": {"id": "bbbb2222"}}),
        }
        code, out, raw = self.run_ops("render", "wait", "--service", "srv-1", "--commit", "bbbb2222")
        self.assertEqual(code, 0, raw)
        self.assertEqual(out["deploy_id"], "dep-new")

    def test_disk_refused_on_free_service(self):
        Recorder.routes = {("GET", "/v1/services/srv-1"): (200, {"id": "srv-1", "serviceDetails": {"plan": "free"}})}
        code, out, _ = self.run_ops("render", "disk", "--service", "srv-1")
        self.assertEqual(code, 2)
        self.assertFalse(any(c["path"] == "/v1/disks" for c in Recorder.calls))

    def test_status_syncs_plan_to_state(self):
        (self.dir / ".wa-state.json").write_text(json.dumps({"version": 2, "render": {"service_id": "srv-1", "plan": "free"}}))
        Recorder.routes = {
            ("GET", "/v1/services/srv-1/deploys"): (200, []),
            ("GET", "/v1/services/srv-1"): (200, {"id": "srv-1", "serviceDetails": {"plan": "starter", "url": "https://x"}}),
        }
        code, out, raw = self.run_ops("render", "status")
        self.assertEqual(code, 0, raw)
        self.assertEqual(json.loads((self.dir / ".wa-state.json").read_text())["render"]["plan"], "starter")

    def test_env_set_uses_per_key_endpoint(self):
        Recorder.routes = {("PUT", "/v1/services/srv-1/env-vars/WEBHOOK_TOKEN"): (200, {"key": "WEBHOOK_TOKEN", "value": "x"})}
        code, out, raw = self.run_ops("render", "env-set", "WEBHOOK_TOKEN", "--service", "srv-1")
        self.assertEqual(code, 0, raw)
        call = Recorder.calls[-1]
        self.assertEqual(call["verb"], "PUT")
        self.assertEqual(call["path"], "/v1/services/srv-1/env-vars/WEBHOOK_TOKEN")
        self.assertEqual(call["body"], {"value": "whsecret_abcdefgh"})
        self.assertFalse(any(c["path"] == "/v1/services/srv-1/env-vars" for c in Recorder.calls))  # never the replace-all PUT
        self.assertNotIn("whsecret_abcdefgh", raw)

    def test_deploy_handles_202_without_body_and_waits(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        listing = iter([
            # first poll: the new deploy isn't listed yet, only yesterday's live one
            [{"deploy": {"id": "dep-old", "status": "live", "createdAt": "2026-01-01T00:00:00Z"}}],
            [{"deploy": {"id": "dep-2", "status": "build_in_progress", "createdAt": now}},
             {"deploy": {"id": "dep-old", "status": "live", "createdAt": "2026-01-01T00:00:00Z"}}],
        ])
        single = iter(["update_in_progress", "live"])
        Recorder.routes = {
            ("POST", "/v1/services/srv-1/deploys"): (202, None),
            ("GET", "/v1/services/srv-1/deploys?"): lambda p, b: (200, next(listing)),
            ("GET", "/v1/services/srv-1/deploys/dep-2"): lambda p, b: (200, {"id": "dep-2", "status": next(single),
                                                                             "commit": {"id": "abc"}}),
        }
        code, out, raw = self.run_ops("render", "deploy", "--service", "srv-1", "--wait")
        self.assertEqual(code, 0, raw)
        self.assertTrue(out["live"])
        self.assertEqual(out["deploy_id"], "dep-2")  # never mistakes the old live deploy for the new one
        self.assertEqual(Recorder.calls[0]["body"], {"clearCache": "do_not_clear"})

    def test_failed_deploy_returns_logs(self):
        (self.dir / ".wa-state.json").write_text(json.dumps({"version": 2, "render": {"service_id": "srv-1", "owner_id": "tea-1"}}))
        Recorder.routes = {
            ("GET", "/v1/services/srv-1/deploys/dep-3"): (200, {"id": "dep-3", "status": "build_failed"}),
            ("GET", "/v1/logs"): (200, {"logs": [{"timestamp": "t2", "message": "error: maturin failed"},
                                                 {"timestamp": "t1", "message": "Collecting pydantic-core"}]}),
        }
        code, out, raw = self.run_ops("render", "wait", "--deploy", "dep-3")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "build_failed")
        self.assertEqual(out["recent_logs"][-1], "t2 error: maturin failed")
        logs_call = [c for c in Recorder.calls if c["path"].startswith("/v1/logs")][0]["path"]
        self.assertIn("ownerId=tea-1", logs_call)
        self.assertIn("resource=srv-1", logs_call)
        self.assertIn("type=build", logs_call)

    def test_rollback_picks_previous_live(self):
        Recorder.routes = {
            ("GET", "/v1/services/srv-1/deploys?"): (200, [
                {"deploy": {"id": "dep-new", "status": "live", "createdAt": "2026-10-02"}},
                {"deploy": {"id": "dep-old", "status": "deactivated", "createdAt": "2026-10-01"}}]),
            ("POST", "/v1/services/srv-1/rollback"): (201, {"id": "dep-rb"}),
        }
        code, out, _ = self.run_ops("render", "rollback", "--service", "srv-1")
        self.assertEqual(code, 0)
        self.assertEqual(Recorder.calls[-1]["body"], {"deployId": "dep-old"})

    def test_unauthorized_hint(self):
        Recorder.routes = {("GET", "/v1/owners"): (401, {"id": "x", "message": "unauthorized"})}
        code, out, _ = self.run_ops("render", "owners")
        self.assertEqual(code, 1)
        self.assertIn("RENDER_API_KEY", out["hint"])


if __name__ == "__main__":
    unittest.main()
