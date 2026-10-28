#!/usr/bin/env python3
"""Service amont SIMULÉ pour les tests de la passerelle pmx (aucune API réelle, données fictives).
  mock_upstream.py --kind anthropic|openai --key <clé amont factice attendue> --log <fichier> [--port 8081]
Chemins : /v1/messages (anthropic), /v1/responses (openai), /slow, /redirect, /big, /echo.
Le journal note, pour chaque requête : méthode, chemin, noms d'en-têtes reçus, clé amont correcte ou non, et si une valeur
d'en-tête commence par le préfixe des jetons d'équipe (`pmxgw_`) — ce qui ne doit jamais arriver.
"""
import argparse, http.server, json, socketserver, time

ap = argparse.ArgumentParser()
ap.add_argument("--kind", required=True)
ap.add_argument("--key", required=True)
ap.add_argument("--log", required=True)
ap.add_argument("--port", type=int, default=8081)
A = ap.parse_args()


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def reply(self, status, obj=None, raw=None, headers=()):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def handle_any(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        got = self.headers.get("x-api-key") or (self.headers.get("authorization") or "").removeprefix("Bearer ")
        rec = {"ts": time.time(), "kind": A.kind, "method": self.command, "path": self.path.split("?")[0], "header_names": sorted(k.lower() for k in self.headers),
               "upstream_key_ok": got == A.key, "team_token_seen": any(v.strip().removeprefix("Bearer ").startswith("pmxgw_") for v in self.headers.values()),
               "body_bytes": len(body), "client": self.client_address[0]}
        with open(A.log, "a") as f:
            f.write(json.dumps(rec) + "\n")
        p = self.path.split("?")[0]
        if p == "/slow":
            time.sleep(10)
            return self.reply(200, {"slow": True})
        if p == "/redirect":
            return self.reply(302, {}, headers=[("Location", "http://169.254.169.254/latest/meta-data/iam")])
        if p == "/big":
            return self.reply(200, raw=b"x" * (3 << 20))
        if p == "/echo":
            return self.reply(200, {"header_names": rec["header_names"], "upstream_key_ok": rec["upstream_key_ok"]})
        if not rec["upstream_key_ok"]:
            return self.reply(401, {"error": "invalid upstream key"})
        if A.kind == "anthropic" and p == "/v1/messages":
            return self.reply(200, {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "mock-anthropic"}],
                                    "usage": {"input_tokens": 12, "output_tokens": 7}})
        if A.kind == "openai" and p == "/v1/responses":
            return self.reply(200, {"object": "response", "output": [{"type": "message", "content": [{"type": "output_text", "text": "mock-openai"}]}],
                                    "usage": {"input_tokens": 11, "output_tokens": 5, "total_tokens": 16}})
        return self.reply(404, {"error": "not found"})

    do_GET = do_POST = handle_any


class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


S(("0.0.0.0", A.port), H).serve_forever()
