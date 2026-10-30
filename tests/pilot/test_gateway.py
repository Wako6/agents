#!/usr/bin/env python3
"""Tests de la passerelle réseau pmx_gateway (opt-in) — services amont SIMULÉS, jetons et clés fictifs, aucune API réelle,
aucun accès Internet (réseau amont Docker `--internal`). Prérequis docker : image locale alpine:3.22 (équipes) et
PMX_GATEWAY_IMAGE (défaut : python:3.13-alpine épinglée par digest) ; sinon les tests docker sont ignorés.
Usage : python3 -I tests/pilot/test_gateway.py -v
"""
import importlib.util, ipaddress, json, os, pathlib, re, socket, subprocess, sys, threading, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_docker  # noqa: E402
import test_pmx  # noqa: E402
from test_docker import AGENT_DIR, IMAGE, own_containers  # noqa: E402

GW_IMAGE = os.environ.get("PMX_GATEWAY_IMAGE", "python@sha256:8bcfa47b04b853a17aaf909362b847b2112fd6ec4105ea553ef9a43bafbb5916")
MOCK = HERE / "gateway" / "mock_upstream.py"
KEYS = {"anthropic": "FAKE-UPSTREAM-ANTHROPIC-0001", "openai": "FAKE-UPSTREAM-OPENAI-0001"}

spec = importlib.util.spec_from_file_location("pmx_gateway", HERE.parents[1] / "skills" / "project-manager" / "scripts" / "pmx_gateway.py")
gwmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gwmod)


def gw_ready():
    return test_docker.DOCKER and subprocess.run(["docker", "image", "inspect", GW_IMAGE], capture_output=True).returncode == 0


def ip(*parts):
    """Adresse IPv4 fictive construite à l'exécution (aucune adresse privée écrite en clair dans le dépôt)."""
    return ".".join(map(str, parts))


class DestinationPolicy(unittest.TestCase):
    """Politique de destination de la passerelle (sans Docker, résolution simulée)."""

    def check(self, host, addrs, port=443, allow_private=False):
        fake = lambda h, p, type=None: [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, p)) for a in addrs]
        return gwmod.destination_problem(host, port, allow_private, resolve=fake)[0]

    def test_g01_public_destination_allowed(self):
        self.assertIsNone(self.check("api.anthropic.com", ["160.79.104.10"]))

    def test_g02_private_loopback_metadata_docker_refused(self):
        cases = [("intranet", [ip(10, 20, 30, 40)]), ("x", [ip(192, 168, 1, 10)]), ("x", [ip(172, 17, 0, 1)]), ("cgnat", ["100.64.0.1"]),
                 ("lo", ["127.0.0.1"]), ("lo6", ["::1"]), ("meta", ["169.254.169.254"]), ("meta6", ["fe80::1"]), ("any", ["0.0.0.0"]),
                 ("mapped", ["::ffff:" + ip(10, 0, 0, 1)]), ("ula", ["fd00::1"]), ("multi", ["239.1.1.1"])]
        for host, addrs in cases:
            with self.subTest(host=host, addrs=addrs):
                self.assertIsNotNone(self.check(host, addrs))
        self.assertIsNotNone(self.check("host.docker.internal", ["8.8.8.8"]))  # nom interdit, quelle que soit l'adresse
        self.assertIsNotNone(self.check("gateway.docker.internal", ["8.8.8.8"]))
        self.assertIsNotNone(self.check("metadata.google.internal", ["8.8.8.8"]))
        self.assertIsNotNone(self.check("example.com", ["8.8.8.8"], port=2375))  # API Docker
        self.assertIsNotNone(self.check("rebind.example", ["8.8.8.8", ip(10, 0, 0, 5)]))  # une seule adresse privée suffit

    def test_g03_allow_private_never_opens_loopback_metadata_docker(self):
        self.assertIsNone(self.check("mock-anthropic", [ip(172, 30, 0, 2)], 8081, allow_private=True))
        for host, addrs, port in (("lo", ["127.0.0.1"], 80), ("meta", ["169.254.169.254"], 80), ("host.docker.internal", [ip(10, 20, 30, 40)], 80),
                                  ("mock", [ip(172, 30, 0, 2)], 2375)):
            with self.subTest(host=host):
                self.assertIsNotNone(self.check(host, addrs, port, allow_private=True))


@unittest.skipUnless(gw_ready(), "Docker, alpine:3.22 ou l'image de la passerelle indisponible")
class GatewayDocker(test_docker.Docker):
    def setUp(self):
        super().setUp()
        self.mocklog = self.tmp / "mocklog"
        self.mocklog.mkdir(mode=0o777)
        self.keys = self.tmp / "keys.json"
        self.keys.write_text(json.dumps(KEYS))
        self.upnet = f"pmx-test-upstream-{os.getpid()}-{time.time_ns() % 10**8}"
        lab = ["--label", "pmx.pilot=1", "--label", f"pmx.root={self.root.resolve()}"]
        subprocess.run(["docker", "network", "create", "--internal", *lab, self.upnet], check=True, capture_output=True)
        for kind, alias in (("anthropic", "mock-anthropic"), ("openai", "mock-openai"), ("anthropic", "mock-intranet")):
            subprocess.run(["docker", "run", "-d", "--name", f"{self.upnet}-{alias}", *lab, "--label", "pmx.kind=mock", "--pull", "never",
                            "--network", self.upnet, "--network-alias", alias, "--user", f"{os.getuid()}:{os.getgid()}", "--read-only",
                            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "64m", "--pids-limit", "32",
                            "--mount", f"type=bind,src={MOCK},dst=/mock.py,readonly", "--mount", f"type=bind,src={self.mocklog},dst=/log",
                            GW_IMAGE, "python3", "-I", "-B", "/mock.py", "--kind", kind, "--key", KEYS[kind], "--log", f"/log/{alias}.jsonl"],
                           check=True, capture_output=True)

    def tearDown(self):
        root = str(self.root.resolve())
        for line in own_containers(self.root.resolve()):
            subprocess.run(["docker", "rm", "-f", line.split()[0]], capture_output=True)
        nets = subprocess.run(["docker", "network", "ls", "--filter", "label=pmx.pilot=1", "--filter", f"label=pmx.root={root}", "--format", "{{.Name}}"],
                              capture_output=True, text=True).stdout.split()
        for n in nets:
            subprocess.run(["docker", "network", "rm", n], capture_output=True)
        super().tearDown()

    def gwconfig(self, teams, gw_extra=None, **orch):
        gw = {"image": GW_IMAGE, "upstream_network": self.upnet, "keys_file": str(self.keys), "token_ttl_s": 300,
              "routes": {"anthropic": {"upstream": "http://mock-anthropic:8081", "allow_private": True, "auth_header": "x-api-key"},
                         "openai": {"upstream": "http://mock-openai:8081", "allow_private": True, "auth_header": "authorization"},
                         "intranet": {"upstream": "http://mock-intranet:8081"},
                         "metadata": {"upstream": "http://169.254.169.254"},
                         "dockerapi": {"upstream": "http://host.docker.internal:2375", "allow_private": True},
                         "loopback": {"upstream": "http://127.0.0.1:8080", "allow_private": True}},
              "limits": {"max_request_bytes": 65536, "upstream_timeout_s": 2, "client_timeout_s": 5, "max_response_bytes": 1048576},
              "quota": {"max_requests": 50}}
        gw.update(gw_extra or {})
        self.config(teams, gateway=gw, **orch)

    def gteam(self, behavior, routes, **d):
        t = test_docker.dteam(behavior, network="gateway", gateway_routes=routes, **d)
        return t

    def gwlog(self, run):
        p = self.root / "ai_memory" / "runs" / run / "gateway" / "log" / "gateway.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def gw_results(self, run, key):
        return dict((n, c) for n, c in re.findall(r"^GW (\S+) (\S+)", self.report(run, key), re.M))

    def all_text(self):
        out = []
        for p in list(self.root.rglob("*")) + list((self.tmp / "wt").rglob("*")) + list(self.mocklog.rglob("*")):
            if p.is_file() and ".git/" not in str(p):
                try:
                    out.append(p.read_text(errors="replace"))
                except OSError:
                    pass
        return "\n".join(out)

    # ------------------------------------------------------------------

    def test_g10_probes_allowed_and_refused(self):
        self.gwconfig({"team-a": self.gteam("gwprobe", ["anthropic", "intranet", "metadata", "dockerapi", "loopback"]),
                       "team-b": self.gteam("gwprobe", ["openai"])})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"], "ROUTE=anthropic OTHER=openai"),
                                     self.dtask("b", "team-b", ["src/b.js"], "ROUTE=openai OTHER=anthropic")])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        a, b = self.gw_results(run, "a"), self.gw_results(run, "b")
        expect = {"own_route": "200", "other_team_route": "403", "unknown_route": "404", "private_network": "403", "cloud_metadata": "403",
                  "docker_api": "403", "loopback": "403", "redirect": "502", "unknown_token": "401", "no_token": "401", "too_large": "413",
                  "upstream_slow": "504", "upstream_big": "200", "absolute_uri": "403", "connect": "405", "internet": "BLOCKED",
                  "mock_upstream_direct": "BLOCKED", "docker_host_api": "BLOCKED", "metadata_direct": "BLOCKED"}
        for k, v in expect.items():
            self.assertEqual(a.get(k), v, f"équipe a : {k}")
        self.assertEqual(b["own_route"], "200")
        self.assertEqual(b["other_team_route"], "403")  # isolation des routes entre équipes
        for k in ("private_network", "cloud_metadata", "docker_api", "loopback"):
            self.assertEqual(b[k], "403")  # route non attribuée à b
        rep = self.report(run, "a")
        self.assertIn("ENV_UPSTREAM_KEY_VISIBLE 0", rep)  # la clé amont n'est jamais dans le conteneur
        decisions = {(r.get("team"), r["decision"]) for r in self.gwlog(run)}
        for d in ("forwarded", "route-not-allowed-for-team", "destination-refused", "redirect-refused", "token-unknown", "request-too-large",
                  "upstream-timeout", "absolute-uri-refused", "connect-refused", "route-unknown", "response-truncated-limit"):
            self.assertTrue(any(x[1] == d for x in decisions), d)
        refused = {r["route"]: r["reason"] for r in self.gwlog(run) if r["decision"] == "destination-refused"}
        self.assertIn("réseau privé", refused["intranet"])
        self.assertIn("lien local", refused["metadata"])
        self.assertIn("nom interdit", refused["dockerapi"])
        self.assertIn("loopback", refused["loopback"])
        mock = [json.loads(l) for f in self.mocklog.glob("*.jsonl") for l in f.read_text().splitlines()]
        self.assertTrue(mock)
        self.assertFalse(any(m["team_token_seen"] for m in mock))  # jeton d'équipe jamais transmis à l'amont
        self.assertTrue(all(m["upstream_key_ok"] for m in mock if m["path"] in ("/v1/messages", "/v1/responses")))  # clé injectée
        self.assertFalse(any(m["kind"] for m in mock if "mock-intranet" in json.dumps(m)))  # l'intranet n'a jamais été contacté
        self.assertFalse((self.mocklog / "mock-intranet.jsonl").exists())
        self.assertFalse(any("/latest/meta-data" in m["path"] for m in mock))  # redirection non suivie
        text = self.all_text()
        self.assertNotIn("FAKE-UPSTREAM", text.replace(json.dumps(KEYS), ""))  # clés amont : seulement dans le fichier fourni
        self.assertIsNone(re.search(r"pmxgw_[0-9a-f]{48}", text))  # aucun jeton d'équipe écrit nulle part
        for wi in wis:
            self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")
        self.assertEqual([l for l in own_containers(self.root.resolve()) if "gateway" in l], [])  # passerelle arrêtée en fin de run
        self.assertTrue(list((self.root / "ai_memory" / "runs" / run / "gateway").glob("container-*.json")))
        nets = subprocess.run(["docker", "network", "ls", "--filter", f"label=pmx.root={self.root.resolve()}", "--format", "{{.Name}}"],
                              capture_output=True, text=True).stdout.split()
        self.assertEqual(nets, [self.upnet])  # réseaux d'équipe supprimés
        self.keep(run, "g10-probes")

    def test_g11_quota_per_team(self):
        self.gwconfig({"team-a": self.gteam("gwquota", ["anthropic"], gateway_quota={"max_requests": 3}), "team-b": self.gteam("gwquota", ["openai"])})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"], "ROUTE=anthropic"), self.dtask("b", "team-b", ["src/b.js"], "ROUTE=openai")])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        a, b = self.gw_results(run, "a"), self.gw_results(run, "b")
        self.assertEqual([a[f"quota_{i}"] for i in range(1, 6)], ["200", "200", "200", "429", "429"])
        self.assertEqual([b[f"quota_{i}"] for i in range(1, 6)], ["200"] * 5)  # quota de a sans effet sur b

    def test_g12_expired_token_and_stolen_token_from_other_network(self):
        self.gwconfig({"team-a": self.gteam("gwexpire", ["anthropic"]), "team-b": self.gteam("gwexpire", ["openai"])})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"], "ROUTE=anthropic"), self.dtask("b", "team-b", ["src/b.js"], "ROUTE=openai")])
        self.pmx("dispatch", "--run", run, code=0)
        st = self.run_state(run)
        ca, gb = st["tasks"]["a"]["attempts"][0]["container"], st["tasks"]["b"]["attempts"][0]["gateway"]
        deadline = time.time() + 20
        while time.time() < deadline and not any(r["decision"] == "forwarded" and r.get("task") == "a" for r in self.gwlog(run)):
            time.sleep(0.2)
        # jeton de a, récupéré par l'humain/test via docker inspect, rejoué depuis le réseau de b : refusé (lié au sous-réseau)
        env = json.loads(subprocess.run(["docker", "inspect", ca], capture_output=True, text=True).stdout)[0]["Config"]["Env"]
        tok_a = next(e.split("=", 1)[1] for e in env if e.startswith("PMX_GATEWAY_TOKEN="))
        p = subprocess.run(["docker", "run", "--rm", "--name", f"pmx-thief-{os.getpid()}", "--label", "pmx.pilot=1", "--label", f"pmx.root={self.root.resolve()}",
                            "--pull", "never", "--network", gb["network"], "--cap-drop", "ALL", "--user", "1000:1000", IMAGE, "sh", "-c",
                            f"wget -q -S -T 5 -O - --header 'x-api-key: {tok_a}' --post-data '{{}}' http://pmx-gateway:8080/anthropic/v1/messages 2>&1 | head -1"],
                           capture_output=True, text=True)
        self.assertIn("403", p.stdout + p.stderr)
        # expiration : l'échéance du jeton de a est avancée dans le fichier des empreintes
        tf = self.root / "ai_memory" / "runs" / run / "gateway" / "state" / "tokens.json"
        data = json.loads(tf.read_text())
        for h, e in data["tokens"].items():
            if e["task"] == "a":
                e["expires"] = time.time() - 1
        tf.write_text(json.dumps(data))
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        a = self.gw_results(run, "a")
        self.assertEqual((a["before_expiry"], a["after_expiry"]), ("200", "401"))
        decisions = [(r.get("task"), r["decision"]) for r in self.gwlog(run)]
        self.assertIn(("a", "token-expired"), decisions)
        self.assertIn(("a", "token-wrong-origin"), decisions)
        self.assertNotIn(tok_a, self.all_text())
        self.assertNotIn(tok_a[6:], self.all_text())

    def test_g13_gateway_not_reachable_from_host_or_lan(self):
        self.gwconfig({"team-a": self.gteam("gwwork", ["anthropic"]), "team-b": self.gteam("gwwork", ["openai"])})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"], "ROUTE=anthropic")])
        self.pmx("dispatch", "--run", run, code=0)
        gname = next(l.split()[0] for l in own_containers(self.root.resolve()) if "gateway" in l)
        info = json.loads(subprocess.run(["docker", "inspect", gname], capture_output=True, text=True).stdout)[0]
        self.assertFalse(info["HostConfig"]["PortBindings"])
        self.assertFalse(info["HostConfig"]["PublishAllPorts"])
        nets = info["NetworkSettings"]["Networks"]
        for n in nets:
            self.assertTrue(json.loads(subprocess.run(["docker", "network", "inspect", n], capture_output=True, text=True).stdout)[0]["Internal"], n)
        ip = next(v["IPAddress"] for v in nets.values() if v["IPAddress"])
        s = socket.socket()
        s.settimeout(2)
        self.assertNotEqual(s.connect_ex((ip, 8080)), 0)  # depuis l'hôte (WSL)
        s.close()
        p = subprocess.run(["docker", "run", "--rm", "--name", f"pmx-lan-{os.getpid()}", "--label", "pmx.pilot=1", "--label", f"pmx.root={self.root.resolve()}",
                            "--pull", "never", "--network", "bridge", "--cap-drop", "ALL", "--user", "1000:1000", IMAGE, "sh", "-c",
                            f"wget -q -T 3 -O /dev/null http://{ip}:8080/_health && echo REACHED || echo BLOCKED"], capture_output=True, text=True)
        self.assertIn("BLOCKED", p.stdout)  # depuis un conteneur du réseau par défaut (« réseau local »)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)

    def test_g14_parallel_teams_full_cycle_with_simulated_apis(self):
        self.gwconfig({"team-a": self.gteam("gwwork", ["anthropic"]), "team-b": self.gteam("gwwork", ["openai"])},
                      verify_runner=test_docker.VRUN, allowed_test_commands=["test -f src/a.js", "test -f src/b.js"])
        pol = self.root / ".claude" / "pmx.integration-policy.json"
        pol.write_text(json.dumps({**json.loads(pol.read_text()), "require_isolated_verification": True}))
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"], "ROUTE=anthropic"), self.dtask("b", "team-b", ["src/b.js"], "ROUTE=openai")])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("evidence", "--run", run, code=0)
        par = json.loads((self.root / "ai_memory" / "runs" / run / "parallelism.json").read_text())
        self.assertGreater(par["overlaps"][0]["seconds"], 2.0)
        for k in ("a", "b"):
            r = self.gw_results(run, k)
            self.assertEqual((r["own_route"], r["own_route_2"]), ("200", "200"))
        fwd = [r for r in self.gwlog(run) if r["decision"] == "forwarded"]
        self.assertEqual(sorted({(r["team"], r["route"]) for r in fwd}), [("team-a", "anthropic"), ("team-b", "openai")])
        self.assertTrue(all(r["tokens_in"] > 0 and r["tokens_out"] > 0 for r in fwd))  # consommation simulée comptée
        self.pmx("verify", "--run", run, code=0)  # vérification isolée : réseau none, sans passerelle
        st = self.run_state(run)
        self.assertTrue(all(st["tasks"][k]["verify"]["runner"] == "docker" for k in ("a", "b")))
        self.pmx("review", "run", "--run", run, code=0)
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=2)
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "DONE")
        self.keep(run, "g14-parallel-full-cycle")

    def test_g15_config_cannot_weaken_isolation(self):
        bad = [({"network": "bridge"}, "réseau 'bridge' refusé"), ({"network": "gateway"}, "gateway_routes"),
               ({"network": "gateway", "gateway_routes": ["evil"]}, "gateway_routes"), ({"gateway_routes": ["anthropic"]}, "sans `network: gateway`")]
        for extra, why in bad:
            with self.subTest(extra=extra):
                self.gwconfig({"team-a": test_docker.dteam("ok", **extra), "team-b": test_docker.dteam("ok")})
                run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
                p = self.pmx("dispatch", "--run", run, code=64)
                self.assertIn(why, p.stderr)
        # la vérification isolée ne peut jamais recevoir de réseau, même avec une passerelle configurée
        self.gwconfig({"team-a": self.gteam("ok", ["anthropic"]), "team-b": test_docker.dteam("ok")},
                      verify_runner={"adapter": "docker", "docker": {**test_docker.VRUN["docker"], "network": "gateway"}})
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        errs = m.verify_runner(m.Ctx(self.root))[2]
        self.assertTrue(any("réseau 'gateway' refusé" in e for e in errs), errs)
        self.assertEqual([l for l in own_containers(self.root.resolve()) if "mock" not in l], [])  # rien n'a été lancé

for _n in [n for n in dir(test_docker.Docker) if n.startswith("test_")]:
    setattr(GatewayDocker, _n, None)


if __name__ == "__main__":
    unittest.main()
