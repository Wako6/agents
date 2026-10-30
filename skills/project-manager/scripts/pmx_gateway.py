#!/usr/bin/env python3
"""pmx_gateway — passerelle de sortie des équipes conteneurisées du pilote pmx (opt-in). Python stdlib, aucune dépendance.

Relais inverse à routes FIXES : `/<route>/<chemin>` → l'amont configuré pour `<route>`. Pas de proxy direct : CONNECT et
URI absolues refusés, aucune destination choisie par l'équipe.
- Jeton par tentative : lié à l'équipe, aux routes autorisées, au sous-réseau Docker de l'équipe et à une échéance. Le fichier
  des jetons ne contient que leurs empreintes SHA-256 ; le jeton est remplacé par la clé amont (jamais vue par l'équipe).
- Destinations : adresses vérifiées APRÈS résolution, puis connexion à l'adresse vérifiée (pas de rebinding DNS). Refus :
  loopback, lien local (169.254/16, fe80::/10 : métadonnées cloud), *.docker.internal, ports de l'API Docker, adresses
  non routables ; réseaux privés refusés sauf amont marqué `allow_private` (services simulés des tests).
- Aucune redirection suivie ni relayée. Quotas par équipe (requêtes, octets, jetons LLM estimés), requêtes simultanées,
  taille des requêtes et des réponses, délais client et amont.
- Journal JSON par décision : jamais d'en-tête, de corps, de requête (query), de jeton ni de clé ; empreinte courte du jeton.

  pmx_gateway.py --config CONFIG.json --state DIR (tokens.json) --keys KEYS.json --log LOG.jsonl [--port 8080]
"""
import argparse, hashlib, http.client, http.server, ipaddress, json, os, re, socket, socketserver, ssl, sys, threading, time, urllib.parse

DOCKER_PORTS = {2375, 2376, 2377}
BLOCKED_NAMES = ("localhost", "metadata", "metadata.google.internal", "metadata.azure.internal", "instance-data")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
       "host", "content-length", "authorization", "x-api-key", "x-pmx-token", "cookie", "forwarded", "x-forwarded-for", "x-real-ip"}
DEFAULT_LIMITS = {"max_request_bytes": 1 << 20, "max_response_bytes": 16 << 20, "upstream_timeout_s": 120, "client_timeout_s": 30,
                  "max_concurrent_per_team": 4}
DEFAULT_QUOTA = {"max_requests": 200, "max_bytes": 64 << 20, "max_tokens": 2_000_000}


def fp(token):
    return hashlib.sha256(token.encode()).hexdigest()


def destination_problem(host, port, allow_private=False, resolve=socket.getaddrinfo):
    """→ (raison du refus | None, adresse vérifiée). Toutes les adresses résolues doivent être acceptables."""
    h = (host or "").lower().rstrip(".")
    if not h:
        return "hôte vide", None
    if h.endswith(".docker.internal") or h == "docker.internal" or h in BLOCKED_NAMES or h.endswith(".localhost") or h.endswith(".local"):
        return f"nom interdit ({h})", None
    if port in DOCKER_PORTS:
        return f"port de l'API Docker ({port})", None
    try:
        infos = resolve(h, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError) as e:
        return f"résolution impossible ({e})", None
    addrs = sorted({i[4][0] for i in infos})
    if not addrs:
        return "aucune adresse", None
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if ip.is_loopback:
            return f"loopback ({ip})", None
        if ip.is_link_local or ip in ipaddress.ip_network("169.254.0.0/16"):
            return f"lien local / métadonnées cloud ({ip})", None
        if ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            return f"adresse non routable ({ip})", None
        if (ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")) and not allow_private:
            return f"réseau privé ({ip})", None
    return None, addrs[0]


class Gateway:
    def __init__(self, config, state_dir, keys_file, log_file):
        self.cfg = json.loads(open(config, encoding="utf-8").read())
        self.limits = {**DEFAULT_LIMITS, **(self.cfg.get("limits") or {})}
        self.default_quota = {**DEFAULT_QUOTA, **(self.cfg.get("quota") or {})}
        self.routes = self.cfg["routes"]
        self.state_dir, self.keys_file, self.log_file = state_dir, keys_file, log_file
        self.lock = threading.Lock()
        self.usage = {}  # équipe → compteurs
        self.active = {}  # équipe → requêtes en cours
        self._tokens, self._tokens_mtime = {}, None

    def tokens(self):
        p = os.path.join(self.state_dir, "tokens.json")
        try:
            m = os.stat(p).st_mtime_ns
            if m != self._tokens_mtime:
                self._tokens, self._tokens_mtime = json.loads(open(p, encoding="utf-8").read()).get("tokens", {}), m
        except (OSError, ValueError):
            self._tokens = {}
        return self._tokens

    def key(self, name):
        try:
            return json.loads(open(self.keys_file, encoding="utf-8").read()).get(name)
        except (OSError, ValueError):
            return None

    def log(self, **rec):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **rec}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self.lock:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pmx-gateway"
    sys_version = ""

    def log_message(self, *a):  # pas de journal d'accès brut (il contiendrait les chemins et requêtes)
        pass

    def deny(self, status, decision, **extra):
        self.send_response(status)
        body = json.dumps({"error": decision}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True
        self.gw.log(decision=decision, status=status, method=self.command, path=self.safe_path(), client=self.client_address[0], **extra)

    def safe_path(self):
        p = urllib.parse.urlsplit(self.path).path if self.path.startswith("/") else "<absolute-uri>"
        return p[:200]

    @property
    def gw(self):
        return self.server.gw

    def do_CONNECT(self):
        self.deny(405, "connect-refused")

    def handle_any(self):
        t0 = time.time()
        if not self.path.startswith("/"):
            return self.deny(403, "absolute-uri-refused")
        if self.path == "/_health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            return self.wfile.write(body)
        parts = urllib.parse.urlsplit(self.path)
        seg = parts.path.lstrip("/").split("/", 1)
        route, rest = seg[0], "/" + (seg[1] if len(seg) > 1 else "")
        r = self.gw.routes.get(route)
        if not r:
            return self.deny(404, "route-unknown", route=route[:40])
        tok = self.headers.get("x-pmx-token") or self.headers.get("x-api-key") or ""
        auth = self.headers.get("authorization") or ""
        if not tok and auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
        entry = self.gw.tokens().get(fp(tok)) if tok else None
        tfp = fp(tok)[:8] if tok else None
        if not entry:
            return self.deny(401, "token-unknown", route=route, token_fp=tfp)
        team = entry["team"]
        ctx = {"route": route, "team": team, "task": entry.get("task"), "token_fp": tfp}
        if time.time() > entry.get("expires", 0):
            return self.deny(401, "token-expired", **ctx)
        if route not in entry.get("routes", []):
            return self.deny(403, "route-not-allowed-for-team", **ctx)
        try:
            if ipaddress.ip_address(self.client_address[0]) not in ipaddress.ip_network(entry["subnet"]):
                return self.deny(403, "token-wrong-origin", **ctx)
        except (KeyError, ValueError):
            return self.deny(403, "token-wrong-origin", **ctx)
        if "chunked" in (self.headers.get("transfer-encoding") or "").lower():
            return self.deny(411, "chunked-request-refused", **ctx)
        try:
            n = int(self.headers.get("content-length") or 0)
        except ValueError:
            return self.deny(400, "bad-content-length", **ctx)
        if n < 0 or n > self.gw.limits["max_request_bytes"]:
            return self.deny(413, "request-too-large", req_bytes=n, **ctx)
        quota = {**self.gw.default_quota, **(entry.get("quota") or {})}
        with self.gw.lock:
            u = self.gw.usage.setdefault(team, {"requests": 0, "bytes": 0, "tokens": 0})
            if u["requests"] >= quota["max_requests"] or u["bytes"] >= quota["max_bytes"] or u["tokens"] >= quota["max_tokens"]:
                over = True
            else:
                over = False
                if self.gw.active.get(team, 0) >= self.gw.limits["max_concurrent_per_team"]:
                    busy = True
                else:
                    busy = False
                    self.gw.active[team] = self.gw.active.get(team, 0) + 1
                    u["requests"] += 1
        if over:
            return self.deny(429, "quota-exceeded", usage=dict(u), **ctx)
        if busy:
            return self.deny(429, "too-many-concurrent", **ctx)
        try:
            self.forward(r, rest, parts.query, n, ctx, t0)
        finally:
            with self.gw.lock:
                self.gw.active[team] -= 1

    def forward(self, r, rest, query, n, ctx, t0):
        body = self.rfile.read(n) if n else b""
        up = urllib.parse.urlsplit(r["upstream"])
        scheme, host = up.scheme, up.hostname
        port = up.port or (443 if scheme == "https" else 80)
        why, ip = destination_problem(host, port, bool(r.get("allow_private")))
        if why:
            return self.deny(403, "destination-refused", reason=why, **ctx)
        path = (up.path.rstrip("/") + rest) + (("?" + query) if query else "")
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["Host"] = host if port in (80, 443) else f"{host}:{port}"
        headers["Accept-Encoding"] = "identity"
        key = self.gw.key(r.get("key", ctx["route"]))
        if key:
            if r.get("auth_header", "x-api-key").lower() == "authorization":
                headers["Authorization"] = f"Bearer {key}"
            else:
                headers["x-api-key"] = key
        tout = self.gw.limits["upstream_timeout_s"]
        try:
            if scheme == "https":
                conn = http.client.HTTPSConnection(host, port, timeout=tout, context=ssl.create_default_context())
                raw = socket.create_connection((ip, port), timeout=tout)
                conn.sock = conn._context.wrap_socket(raw, server_hostname=host)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=tout)
                conn.sock = socket.create_connection((ip, port), timeout=tout)
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
        except socket.timeout:
            return self.deny(504, "upstream-timeout", **ctx)
        except OSError as e:
            return self.deny(502, "upstream-unreachable", reason=type(e).__name__, **ctx)
        if 300 <= resp.status < 400:
            loc = urllib.parse.urlsplit(resp.getheader("location") or "")
            conn.close()
            return self.deny(502, "redirect-refused", location_host=(loc.hostname or "")[:80], **ctx)
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP and k.lower() not in ("set-cookie",):
                self.send_header(k, v)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        limit, sent, tail = self.gw.limits["max_response_bytes"], 0, b""
        decision, tin, tout_ = "forwarded", 0, 0
        try:
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                if not chunk:
                    break
                if sent + len(chunk) > limit:
                    decision = "response-truncated-limit"
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                sent += len(chunk)
                tail = (tail + chunk)[-262144:]
                for m in re.finditer(rb'"input_tokens"\s*:\s*(\d+)', chunk):
                    tin = max(tin, int(m.group(1)))
                for m in re.finditer(rb'"output_tokens"\s*:\s*(\d+)', chunk):
                    tout_ = max(tout_, int(m.group(1)))
        except socket.timeout:
            decision = "upstream-timeout-midstream"
        finally:
            conn.close()
        with self.gw.lock:
            u = self.gw.usage[ctx["team"]]
            u["bytes"] += n + sent
            u["tokens"] += tin + tout_
        self.gw.log(decision=decision, status=resp.status, method=self.command, path=urllib.parse.urlsplit(path).path[:200],
                    req_bytes=n, resp_bytes=sent, tokens_in=tin, tokens_out=tout_, ms=int((time.time() - t0) * 1000),
                    client=self.client_address[0], **ctx)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = handle_any


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--keys", required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args(argv)
    gw = Gateway(a.config, a.state, a.keys, a.log)
    Handler.timeout = gw.limits["client_timeout_s"]
    srv = Server(("0.0.0.0", a.port), Handler)
    srv.gw = gw
    gw.log(decision="listening", port=a.port, routes=sorted(gw.routes))
    print(f"pmx-gateway listening on :{a.port} routes={sorted(gw.routes)}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
