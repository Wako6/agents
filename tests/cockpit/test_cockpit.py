#!/usr/bin/env python3
"""Prototype du cockpit V3.3 : lecture seule, loopback, aucune fuite, états inconnus. Données fictives ; aucun agent, aucun appel à pmx.

Usage : python3 -I -B tests/cockpit/test_cockpit.py -v
"""
import ast, http.client, json, pathlib, re, socket, sys, threading, time, unittest

KIT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "cockpit"))
import server as cockpit  # noqa: E402


# Marqueurs fictifs : aucun nom réel de personne, de service ou d'infrastructure n'est écrit dans ce dépôt public.
FORBIDDEN_MARKERS = ("MARQUEUR-CONNECTEUR-PERSONNEL", "MARQUEUR-INFRASTRUCTURE-INTERNE", "MARQUEUR-RUN-REEL")
FIXTURE_PATTERNS = [re.compile(p) for p in (
    r"WI-[0-9]{8}-", r"\bpm-v[0-9]{2}\b", "/ho" + r"me/[a-z]", "/Us" + r"ers/[A-Za-z]", "/mn" + r"t/[a-z]/", r"\b[A-Za-z]:\\+[A-Za-z]",
    "gh" + r"[pos]_[A-Za-z0-9]{8}", "github" + r"_pat_", "gl" + r"pat-", r"\bsk-[A-Za-z0-9]{8}", "BEGIN " + r"[A-Z ]*PRIVATE", r"[A-Za-z0-9._%+-]+" + chr(64) + r"[A-Za-z0-9-]+\.[A-Za-z]",
    r"(?<![0-9.])(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]+\.[0-9]+", r"(?i)\b(?:password|passwd|api[_-]?key|token)\s*[:=]\s*\S")]


def fixture_findings(raw):
    """Données réelles repérées dans une fixture : marqueurs interdits et formes génériques (chemins, jetons, e-mails, adresses, identifiants de run)."""
    return [x for x in FORBIDDEN_MARKERS if x in raw] + [p.pattern for p in FIXTURE_PATTERNS if p.search(raw)]


class Cockpit(unittest.TestCase):
    def setUp(self):
        self.srv = cockpit.Server("127.0.0.1", 0, tick=0.1, heartbeat=0.2)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_port
        self.cookie = f"cockpit={self.srv.token}"

    def tearDown(self):
        self.srv.close_all()

    def req(self, method="GET", path="/", headers=None, auth=True, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
        if auth:
            h["Cookie"] = self.cookie
        c.request(method, path, headers=h)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def snap(self):
        return json.loads(self.req(path="/api/v1/snapshot")[1])

    def run_of(self, snap, rid):
        return next(r for p in snap["projects"] for r in p["runs"] if r["id"] == rid)

    def test_01_refuses_non_loopback_bind(self):
        for host in ("0.0.0.0", "192.0.2.1", "::"):
            with self.assertRaises(SystemExit):
                cockpit.Server(host, 0)

    def test_02_listens_on_loopback_only(self):
        self.assertEqual(self.srv.socket.getsockname()[0], "127.0.0.1")

    def test_03_every_write_method_is_refused(self):
        for m in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            for p in ("/", "/api/v1/snapshot", "/api/v1/stream"):
                r, _ = self.req(m, p)
                self.assertEqual(r.status, 405, (m, p))
                self.assertIn("GET", r.getheader("Allow"))

    def test_04_session_is_required_and_token_compared(self):
        for p in ("/", "/app.js", "/api/v1/snapshot", "/api/v1/stream"):
            self.assertEqual(self.req(path=p, auth=False)[0].status, 401, p)
        self.assertEqual(self.req(path="/api/v1/snapshot", auth=False, headers={"Cookie": "cockpit=faux"})[0].status, 401)
        self.assertEqual(self.req(path="/auth?t=faux", auth=False)[0].status, 403)
        r, _ = self.req(path=f"/auth?t={self.srv.token}&v=tasks", auth=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(r.getheader("Location"), "/#tasks")
        c = r.getheader("Set-Cookie")
        for x in ("HttpOnly", "SameSite=Strict"):
            self.assertIn(x, c)
        self.assertEqual(self.req(path=f"/auth?t={self.srv.token}&v=//exemple.invalid", auth=False)[0].getheader("Location"), "/")

    def test_05_host_and_origin_are_checked(self):
        self.assertEqual(self.req(host="attaquant.invalid", path="/api/v1/snapshot")[0].status, 403)
        self.assertEqual(self.req(path="/api/v1/snapshot", headers={"Origin": "https://attaquant.invalid"})[0].status, 403)
        self.assertEqual(self.req(path="/api/v1/snapshot", headers={"Origin": f"http://127.0.0.1:{self.port}"})[0].status, 200)
        self.assertEqual(self.req(host=f"localhost:{self.port}", path="/api/v1/snapshot")[0].status, 200)

    def test_06_no_file_access_from_request_paths(self):
        for p in ("/../server.py", "/ui/app.js", "/fixtures/demo.json", "/%2e%2e/%2e%2e/etc/passwd", "/app.js/../../server.py", "/server.py"):
            r, b = self.req(path=p)
            self.assertEqual(r.status, 404, p)
            self.assertNotIn(b"import", b)

    def test_07_security_headers_on_every_response(self):
        for p in ("/", "/api/v1/snapshot", "/nope"):
            r, _ = self.req(path=p)
            self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(r.getheader("Cache-Control"), "no-store")
            self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))

    def test_08_allowlist_drops_unknown_fields(self):
        forged = {"id": "r", "os_user": "x", "secret_token": "PMXFAKE", "tasks": [{"key": "a", "prompt": "PMXFAKE", "attempts": [{"n": 1, "pid": 42, "brief": "PMXFAKE"}]}], "security": {"items": [], "confirmation": {"tty": "PMXFAKE"}}}
        out = json.dumps(cockpit.project(forged, cockpit.RUN))
        for x in ("PMXFAKE", "os_user", "pid", "brief", "prompt", "confirmation"):
            self.assertNotIn(x, out)

    def test_09_values_are_masked_as_a_second_barrier(self):
        at = chr(64)
        home = "/" + "home" + "/quelquun/projet/.env"
        drive = "C:" + "\\Users\\quelquun\\x"
        for raw in ("gh" + "p_" + "a" * 20, "token=abcdef", "sk-" + "b" * 20, "contact" + at + "exemple.org", home, drive, "/" + "mnt/c/secret", "10." + "1.2.3", "-----BEGIN " + "RSA PRIVATE KEY-----"):
            self.assertNotIn(raw, cockpit.mask(raw), raw)

    def test_10_unknown_states_never_become_success(self):
        for enum in ("task", "verify", "review", "stop", "phase", "proof", "source", "liveness"):
            self.assertEqual(cockpit.project("ETAT_FUTUR", (enum,)), {"value": "UNKNOWN", "raw": "ETAT_FUTUR"})
        snap = self.snap()
        r = self.run_of(snap, "WI-DEMO-020")
        self.assertEqual(r["tasks"][0]["status"]["value"], "UNKNOWN")
        self.assertEqual(r["tasks"][0]["attempts"][0].get("liveness"), None)
        self.assertEqual(r["source"]["value"], "PARTIAL")
        self.assertIsNone(r["teams"][0]["processes"])
        self.assertEqual(next(p for p in r["pipeline"] if p["key"] == "plan")["state"]["value"], "UNKNOWN")

    def test_11_snapshot_is_labelled_demo_read_only(self):
        s = self.snap()
        self.assertEqual((s["source"], s["read_only"], s["schema"]), ("demo", True, "pm-cockpit/1"))
        self.assertTrue(all(p["profile_active"] is False for p in s["projects"]))
        self.assertTrue(all("(démo)" in p["name"] for p in s["projects"]))

    def test_12_unresolved_stop_and_ack_stay_distinct(self):
        st = self.run_of(self.snap(), "WI-DEMO-010")["security"]["stop"]
        self.assertEqual(st["state"]["value"], "UNRESOLVED")
        self.assertEqual(st["ack_by"], "human:demo")

    def test_13_stream_replays_with_monotonic_sequence_and_resync(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(f"GET /api/v1/stream HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nCookie: {self.cookie}\r\nLast-Event-ID: ancien:1\r\n\r\n".encode())
        buf, deadline = b"", time.time() + 4
        s.settimeout(0.5)
        while time.time() < deadline and buf.count(b"event: update") < 2:
            try:
                buf += s.recv(65536)
            except TimeoutError:
                pass
        s.close()
        self.assertIn(b"text/event-stream", buf)
        hello = json.loads(re.search(rb"event: hello\ndata: (.*)\n", buf).group(1))
        self.assertTrue(hello["resync"])
        seqs = [json.loads(x)["seq"] for x in re.findall(rb"event: update\ndata: (.*)\n", buf)]
        self.assertGreaterEqual(len(seqs), 2)
        self.assertEqual(seqs, sorted(seqs))

    def test_14_stream_slots_are_limited_and_released(self):
        self.srv.slots = 0
        self.assertEqual(self.req(path="/api/v1/stream")[0].status, 503)
        self.srv.slots = 1
        s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        s.sendall(f"GET /api/v1/stream HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nCookie: {self.cookie}\r\n\r\n".encode())
        s.recv(4096)
        s.close()
        for _ in range(40):
            if self.srv.slots == 1:
                break
            time.sleep(0.1)
        self.assertEqual(self.srv.slots, 1)

    def test_15_prototype_cannot_reach_pmx_or_run_commands(self):
        tree = ast.parse((KIT / "cockpit" / "server.py").read_text(encoding="utf-8"))
        imported = {n.name.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for n in x.names} | {x.module.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
        self.assertFalse(imported & {"subprocess", "pmx", "os", "shutil", "pty", "multiprocessing", "ctypes", "urllib3", "requests"}, imported)
        src = (KIT / "cockpit" / "server.py").read_text(encoding="utf-8")
        for x in ("eval(", "exec(", ".write_text", ".unlink", "open("):
            self.assertNotIn(x, src, x)

    def test_16_ui_loads_nothing_external_and_never_injects_html(self):
        ui = KIT / "cockpit" / "ui"
        html, js, css = ((ui / f).read_text(encoding="utf-8") for f in ("index.html", "app.js", "app.css"))
        self.assertIsNone(re.search(r"(src|href)=[\"']?(https?:)?//", html))
        self.assertIsNone(re.search(r"url\(|@import", css))
        for x in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "localStorage", "method:\"POST\""):
            self.assertNotIn(x, js, x)
        self.assertEqual(re.findall(r"fetch\(\"([^\"]+)\"", js), ["/api/v1/snapshot"])

    def test_17_fixture_is_fictional(self):
        path = KIT / "cockpit" / "fixtures" / "demo.json"
        raw = path.read_text(encoding="utf-8")
        self.assertEqual(fixture_findings(raw), [])
        self.assertIn("fictives", raw)
        # la détection fonctionne : chaque donnée injectée dans la fixture, à travers son format JSON réel, est trouvée
        at = chr(64)
        for sample in (*FORBIDDEN_MARKERS, "WI-" + "20990101" + "-MAIN-001", "pm-v" + "99", "/ho" + "me/quelquun/projet", "/Us" + "ers/quelquun", "/mn" + "t/c/x", "C:" + "\\Users\\quelquun",
                       "gh" + "p_" + "a" * 20, "gl" + "pat-" + "b" * 20, "sk-" + "c" * 20, "-----BEGIN " + "RSA PRIVATE KEY-----", "contact" + at + "exemple.org", "10." + "1.2.3", "password=" + "abcdef"):
            doc = json.loads(raw)
            doc["projects"][0]["runs"][0]["tasks"][0]["title"] = sample
            self.assertNotEqual(fixture_findings(json.dumps(doc, ensure_ascii=False)), [], sample)

    def test_18_favicon_stays_refused_and_csp_is_not_weakened(self):
        expected = {"default-src": "'none'", "script-src": "'self'", "style-src": "'self'", "connect-src": "'self'", "base-uri": "'none'", "form-action": "'none'", "frame-ancestors": "'none'"}
        for p in ("/", "/api/v1/snapshot", "/favicon.ico"):
            csp = self.req(path=p)[0].getheader("Content-Security-Policy")
            directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
            self.assertEqual(directives, expected, p)  # égalité stricte : ni img-src, ni directive retirée ou élargie
        self.assertEqual(self.req(path="/favicon.ico")[0].status, 404)
        self.assertNotIn("/favicon.ico", cockpit.STATIC)
        self.assertNotIn("favicon", (KIT / "cockpit" / "server.py").read_text(encoding="utf-8").lower())
        html = (KIT / "cockpit" / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"<link\b[^>]*\brel\s*=\s*[\"']?[^\"'>]*icon", html, re.I))
        self.assertNotIn("favicon", html.lower())


if __name__ == "__main__":
    unittest.main()
