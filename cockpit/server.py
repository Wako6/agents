#!/usr/bin/env python3
"""Cockpit Project Manager V3.3 — prototype en lecture seule, sur données FICTIVES ou sur des COPIES minimisées de runs.

    python3 -I -B cockpit/server.py [--port 8765] [--copies <dossier hors dépôt>]

Sécurité du prototype : écoute sur 127.0.0.1 uniquement, GET et HEAD uniquement, jeton de session, contrôle de Host et d'Origin,
aucune ressource externe, sortie filtrée par liste d'autorisation. Il n'importe pas pmx, ne lance aucun processus et ne lit que
fixtures/demo.json, les fichiers de ui/ et, avec --copies, les copies validées par adapter.py. Aucun chemin n'est construit à partir
d'une requête.
"""
import argparse, collections, copy, datetime, hmac, http.cookies, http.server, importlib.util, ipaddress, json, pathlib, re, secrets, socketserver, sys, threading, time, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
SCHEMA = "pm-cockpit/1"
STATIC = {"/": ("ui/index.html", "text/html; charset=utf-8"), "/app.js": ("ui/app.js", "text/javascript; charset=utf-8"), "/app.css": ("ui/app.css", "text/css; charset=utf-8"), "/live.js": ("ui/live.js", "text/javascript; charset=utf-8")}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Cache-Control": "no-store"}
VIEWS = ("projects", "teams", "tasks", "pipeline", "decisions", "security")
MAX_STREAMS = 8

ENUMS = {"task": ("OPEN", "IN_PROGRESS", "READY_FOR_VERIFICATION", "READY_FOR_REVIEW", "BLOCKED", "ESCALATED", "STALE", "DONE"),
         "attempt": ("running", "done", "failed", "aborted", "interrupted"),
         "liveness": ("OBSERVED_ALIVE", "OBSERVED_GONE"),
         "verify": ("PASS", "FAIL", "INCONCLUSIVE"),
         "review": ("APPROVE", "CHANGES_REQUESTED", "UNPARSEABLE"),
         "stop": ("IN_PROGRESS", "STOPPED", "UNRESOLVED"),
         "phase": ("done", "active", "blocked", "pending"),
         "proof": ("OBSERVED", "DECLARED", "NOT_MEASURED"),
         "severity": ("info", "warning", "critical"),
         "source": ("OK", "PARTIAL", "UNREADABLE")}

# Liste d'autorisation : (nom → règle). Tout champ absent d'ici est retiré. Règles : "text", "ts", "int", "bool", (enum,), [élément], {objet}.
ATTEMPT = {"n": "int", "adapter": "text", "branch": "text", "worktree": "text", "started": "ts", "ended": "ts", "result": ("attempt",), "liveness": ("liveness",), "observed_at": "ts", "settled": "text", "cgroup": "text"}
TASK = {"key": "text", "wi": "text", "title": "text", "team": "text", "status": ("task",), "files": ["text"], "depends_on": ["text"], "attempts": [ATTEMPT], "budget": "text", "commit": "text", "blocker": "text",
        "verify": {"verdict": ("verify",), "commit": "text", "runner": "text", "tests": "int", "failed": "int", "ts": "ts"},
        "review": {"verdict": ("review",), "by": "text", "commit": "text", "uncovered": ["text"], "findings": "text", "ts": "ts"}}
RUN = {"id": "text", "title": "text", "parent_wi": "text", "created": "ts", "updated": "ts", "observed_at": "ts", "source": ("source",), "source_note": "text", "base": "text",
       "pipeline": [{"key": "text", "label": "text", "state": ("phase",), "detail": "text"}],
       "teams": [{"name": "text", "adapter": "text", "role": "text", "task": "text", "cgroup": "text", "processes": "int", "observed_at": "ts"}],
       "tasks": [TASK],
       "decisions": [{"ts": "ts", "kind": "text", "by": "text", "text": "text"}],
       "security": {"stop": {"state": ("stop",), "reason": "text", "ack_by": "text"},
                    "items": [{"label": "text", "value": "text", "proof": ("proof",), "note": "text"}]},
       "events": [{"seq": "int", "ts": "ts", "kind": "text", "task": "text", "severity": ("severity",), "text": "text"}]}
PROJECT = {"id": "text", "name": "text", "backend": "text", "mode": "text", "profile": "text", "profile_active": "bool", "source": ("source",), "runs": [RUN]}
SNAPSHOT = {"schema": "text", "source": "text", "source_state": ("source",), "source_note": "text", "read_only": "bool", "instance": "text", "seq": "int", "generated": "ts", "projects": [PROJECT]}

# Dernier filet, jamais la protection principale : un champ autorisé peut contenir une valeur inattendue.
MASKS = [(re.compile(p), r) for p, r in (
    (r"(?:ghp|gho|ghs|github_pat|glpat|sk|xox[abp]|AKIA)[-_A-Za-z0-9]{8,}", "[masqué:jeton]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "[masqué:clé]"),
    (r"(?i)\b(token|secret|password|passwd|api[_-]?key|bearer)\b\s*[:=]\s*\S+", r"\1=[masqué]"),
    (r"/(?:home|Users|root)/[^\s\"']+", "[chemin masqué]"),
    (r"/mnt/[a-z]/[^\s\"']+", "[chemin masqué]"),
    (r"[A-Za-z]:\\[^\s\"']+", "[chemin masqué]"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[e-mail masqué]"),
    (r"\b(?:10|127|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b", "[adresse masquée]"))]


def mask(text):
    text = str(text)[:2000]
    for rx, rep in MASKS:
        text = rx.sub(rep, text)
    return text


def project(value, rule):
    """Sortie de l'API : ne laisse passer que ce que le schéma autorise. Un état inconnu reste visible comme UNKNOWN, jamais comme un succès."""
    if value is None:
        return None
    if isinstance(rule, dict):
        return {k: project(value.get(k), r) for k, r in rule.items() if k in value} if isinstance(value, dict) else None
    if isinstance(rule, list):
        return [project(x, rule[0]) for x in value][:500] if isinstance(value, list) else []
    if isinstance(rule, tuple):
        v = str(value)
        return {"value": v} if v in ENUMS[rule[0]] else {"value": "UNKNOWN", "raw": mask(v)[:80]}
    if rule == "int":
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    if rule == "bool":
        return value if isinstance(value, bool) else None
    return mask(value)


def resolve_times(obj, now):
    """Les fixtures écrivent « T-120 » (il y a 120 s) : l'ancienneté affichée reste réaliste à chaque lancement."""
    if isinstance(obj, dict):
        return {k: resolve_times(v, now) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_times(v, now) for v in obj]
    if isinstance(obj, str) and re.fullmatch(r"T-\d+", obj):
        return (now - datetime.timedelta(seconds=int(obj[2:]))).isoformat(timespec="seconds").replace("+00:00", "Z")
    return obj


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Feed:
    """Journal des mises à jour : numéro de séquence croissant et mémoire bornée, pour rejouer ou, à défaut, dire que la continuité est perdue."""

    def __init__(self):
        self.instance, self.cond, self.seq, self.ring = secrets.token_hex(4), threading.Condition(), 0, collections.deque(maxlen=256)

    def publish(self, update):
        self.seq += 1
        update = {**update, "seq": self.seq}
        self.ring.append(update)
        self.cond.notify_all()

    def since(self, seq):
        """Mises à jour après `seq`, ou None si la mémoire ne permet plus de les fournir toutes."""
        if seq == self.seq:
            return []
        if seq > self.seq or (self.ring and seq < self.ring[0]["seq"] - 1) or (not self.ring and seq != self.seq):
            return None
        return [u for u in self.ring if u["seq"] > seq]


class Demo(Feed):
    """État fictif rejoué en boucle : chaque étape applique des valeurs et ajoute un événement."""
    source = "demo"

    def __init__(self, path, tick):
        super().__init__()
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self.base, self.timeline, self.tick, self.event_seq = raw["projects"], raw["timeline"], tick, 0
        self.reset()
        self.stop = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def reset(self):
        self.projects, self.step = resolve_times(copy.deepcopy(self.base), datetime.datetime.now(datetime.timezone.utc)), 0
        for p in self.projects:
            for r in p["runs"]:
                for e in r.get("events", []):
                    self.event_seq += 1
                    e["seq"] = self.event_seq

    def find(self, run):
        return next((r for p in self.projects for r in p["runs"] if r["id"] == run), None)

    def apply(self, step):
        r = self.find(step["run"])
        for path, value in step.get("set", []):
            node = r
            for part in path[:-1]:
                node = next(x for x in node if x.get("key", x.get("name")) == part) if isinstance(node, list) else node[part]
            node[path[-1]] = {k: now_iso() if v == "NOW" else v for k, v in value.items()} if isinstance(value, dict) else value
        for key in ("updated", "observed_at"):
            r[key] = now_iso()
        self.event_seq += 1
        ev = {"seq": self.event_seq, "ts": now_iso(), **step["event"]}
        r["events"].append(ev)
        return {"run": r["id"], "event": project(ev, RUN["events"][0])}

    def loop(self):
        while not self.stop.wait(self.tick):
            with self.cond:
                if self.step >= len(self.timeline):
                    self.reset()
                    self.publish({"reset": True})
                else:
                    update = self.apply(self.timeline[self.step])
                    self.step += 1
                    self.publish(update)

    def snapshot(self):
        with self.cond:
            return project({"schema": SCHEMA, "source": self.source, "source_state": "OK", "read_only": True, "instance": self.instance, "seq": self.seq, "generated": now_iso(), "projects": self.projects}, SNAPSHOT)


class Copies(Feed):
    """Copies minimisées, relues périodiquement. Le serveur ne reçoit que ce que l'adaptateur a validé."""
    source = "copies"

    def __init__(self, root, tick):
        super().__init__()
        spec = importlib.util.spec_from_file_location("cockpit_adapter", HERE / "adapter.py")
        sys.dont_write_bytecode = True
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.root, self.tick, self.forbidden = root, tick, (HERE.parent,)
        self.projects, self.state, self.note, self.digest = [], "UNREADABLE", "Copies non encore lues.", None
        self.adapter.check_root(root, self.forbidden)  # un mauvais dossier arrête le lancement, sans repli
        self.refresh()
        self.stop = threading.Event()
        threading.Thread(target=self.loop, daemon=True).start()

    def refresh(self):
        """Une modification, une disparition ou un refus deviennent une mise à jour visible. Le dernier état valide n'est jamais présenté comme actuel."""
        try:
            projects, refused = self.adapter.load_dir(self.root, self.forbidden)
            state = "PARTIAL" if refused else "OK"
            note = f"{len(refused)} fichier(s) refusé(s) : {', '.join(sorted(set(refused)))}." if refused else None
        except (self.adapter.Refused, OSError) as e:
            projects, state, note = [], "UNREADABLE", f"Dossier des copies illisible : {e if isinstance(e, self.adapter.Refused) else type(e).__name__}."
        digest = json.dumps([projects, state, note], sort_keys=True, default=str)
        with self.cond:
            if digest == self.digest:
                return
            old = {r["id"]: {e["seq"] for e in r["events"]} for p in self.projects for r in p["runs"]}
            first = self.digest is None
            self.projects, self.state, self.note, self.digest = projects, state, note, digest
            if first:
                return
            news = [(r["id"], e) for p in projects for r in p["runs"] for e in r["events"] if e["seq"] not in old.get(r["id"], set())]
            for rid, e in news[:200]:
                self.publish({"run": rid, "event": project(e, RUN["events"][0])})
            if not news:
                self.publish({"changed": True})

    def loop(self):
        while not self.stop.wait(self.tick):
            self.refresh()

    def snapshot(self):
        with self.cond:
            return project({"schema": SCHEMA, "source": self.source, "source_state": self.state, "source_note": self.note, "read_only": True, "instance": self.instance, "seq": self.seq, "generated": now_iso(), "projects": self.projects}, SNAPSHOT)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version, sys_version, protocol_version = "cockpit", "", "HTTP/1.1"

    def log_message(self, *_a):
        pass  # aucune URL journalisée : la première contient le jeton

    def respond(self, code, body=b"", ctype="application/json; charset=utf-8", extra=()):
        self.send_response(code)
        for k, v in (*HEADERS.items(), ("Content-Type", ctype), ("Content-Length", str(len(body))), *extra):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, code, msg):
        self.respond(code, json.dumps({"error": msg}).encode())

    def origin_ok(self):
        """Contre le rebinding DNS et les requêtes venues d'un autre site, même si le navigateur envoie le cookie."""
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlsplit(origin).netloc in hosts

    def authed(self):
        try:
            jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return False
        return "cockpit" in jar and hmac.compare_digest(jar["cockpit"].value, self.server.token)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.origin_ok():
            return self.fail(403, "hôte ou origine refusés")
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/auth":
            q = urllib.parse.parse_qs(url.query)
            if not hmac.compare_digest(q.get("t", [""])[0], self.server.token):
                return self.fail(403, "jeton refusé")
            view = q.get("v", [""])[0]
            return self.respond(303, extra=(("Set-Cookie", f"cockpit={self.server.token}; HttpOnly; SameSite=Strict; Path=/"), ("Location", "/" + (f"#{view}" if view in VIEWS else ""))))
        if not self.authed():
            return self.fail(401, "session requise : ouvrez l'adresse affichée au lancement")
        if url.path in STATIC:
            rel, ctype = STATIC[url.path]
            return self.respond(200, (HERE / rel).read_bytes(), ctype)
        if url.path == "/api/v1/snapshot":
            return self.respond(200, json.dumps(self.server.demo.snapshot(), ensure_ascii=False).encode())
        if url.path == "/api/v1/stream":
            return self.stream()
        self.fail(404, "inconnu")

    def do_POST(self):
        self.respond(405, json.dumps({"error": "lecture seule"}).encode(), extra=(("Allow", "GET, HEAD"),))

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = do_POST

    def stream(self):
        with self.server.slots_lock:
            if self.server.slots <= 0:
                return self.fail(503, "trop de flux ouverts")
            self.server.slots -= 1
        demo = self.server.demo
        try:
            self.send_response(200)
            for k, v in (*HEADERS.items(), ("Content-Type", "text/event-stream; charset=utf-8"), ("Connection", "close")):
                self.send_header(k, v)
            self.end_headers()
            self.close_connection = True
            if self.command == "HEAD":
                return
            def emit(kind, data, ident=None):
                self.wfile.write((f"id: {ident}\n" if ident is not None else "").encode() + f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            # Reprise : on rejoue ce qui manque si c'est encore possible. Sinon, resync dit au client que la continuité est perdue.
            mine, _, last = self.headers.get("Last-Event-ID", "").partition(":")
            with demo.cond:
                sent = demo.seq
                missed = demo.since(int(last)) if mine == demo.instance and last.isdigit() else None
            emit("hello", {"instance": demo.instance, "seq": sent, "resync": missed is None, "heartbeat": self.server.heartbeat}, f"{demo.instance}:{sent}")
            for u in missed or []:
                emit("update", u, f"{demo.instance}:{u['seq']}")
            while not self.server.closing:
                with demo.cond:
                    if demo.seq == sent:
                        demo.cond.wait(self.server.heartbeat)
                    batch = demo.since(sent)
                    head = demo.seq
                if batch is None:
                    emit("lost", {"seq": head}, f"{demo.instance}:{head}")
                elif batch:
                    for u in batch:
                        emit("update", u, f"{demo.instance}:{u['seq']}")
                else:
                    emit("ping", {"seq": head})  # visible du client : un flux muet se détecte, un commentaire SSE ne se verrait pas
                sent = head
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            with self.server.slots_lock:
                self.server.slots += 1


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self, host, port, fixture=HERE / "fixtures" / "demo.json", tick=4.0, heartbeat=10.0, copies=None):
        if not ipaddress.ip_address(host).is_loopback:
            raise SystemExit(f"refus : {host} n'est pas une adresse de boucle locale")
        super().__init__((host, port), Handler)
        self.token, self.demo, self.closing, self.heartbeat = secrets.token_urlsafe(32), Copies(copies, min(tick, 2.0)) if copies else Demo(fixture, tick), False, heartbeat
        self.slots, self.slots_lock = MAX_STREAMS, threading.Lock()

    def close_all(self):
        self.closing = True
        self.demo.stop.set()
        with self.demo.cond:
            self.demo.cond.notify_all()
        self.shutdown()
        self.server_close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--copies", help="dossier de copies minimisées, hors du dépôt")
    a = ap.parse_args()
    srv = Server("127.0.0.1", a.port, copies=a.copies)
    print(f"Cockpit ({'COPIES MINIMISÉES' if a.copies else 'DONNÉES FICTIVES'}, lecture seule) : http://127.0.0.1:{srv.server_port}/auth?t={srv.token}\nCtrl-C pour arrêter.", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
