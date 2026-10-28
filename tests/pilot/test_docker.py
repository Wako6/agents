#!/usr/bin/env python3
"""Tests de l'adaptateur docker de pmx — conteneurs réels, agent factice `docker-agent/agent.sh` (aucune CLI réelle, aucun réseau).
Prérequis : démon Docker joignable et image locale (`PMX_DOCKER_IMAGE`, défaut alpine:3.22 ; jamais téléchargée : --pull never).
Sans ces prérequis, les tests sont ignorés. pmx ne touche qu'aux conteneurs qu'il a créés (label pmx.pilot + pmx.root).
Usage : python3 -I tests/pilot/test_docker.py -v
"""
import json, os, pathlib, re, signal, subprocess, sys, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pmx  # noqa: E402
from test_pmx import FAKE, PMX, PY  # noqa: E402

IMAGE = os.environ.get("PMX_DOCKER_IMAGE", "alpine:3.22")
AGENT_DIR = HERE / "docker-agent"


def docker_ready():
    try:
        ok = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return ok


DOCKER = docker_ready()


VRUN = {"adapter": "docker", "docker": {"image": IMAGE, "cpus": 1.0, "memory": "256m", "pids": 64, "tmpfs_size": "32m"}}


def dteam(behavior, **lim):
    d = {"image": IMAGE, "argv": ["sh", "/agent/agent.sh", "{prompt_file}", behavior], "agent_dir": str(AGENT_DIR),
         "cpus": 1.0, "memory": "256m", "pids": 64, "tmpfs_size": "64m"}
    d.update(lim)
    return {"adapter": "docker", "label": f"docker-{behavior}", "docker": d,
            "reviewer": {"adapter": "cmd", "argv": [PY, "-I", str(FAKE), "review", "{prompt_file}", "{out_file}", "APPROVE"]}}


def own_containers(root):
    p = subprocess.run(["docker", "ps", "-a", "--filter", "label=pmx.pilot=1", "--filter", f"label=pmx.root={root}", "--format", "{{.Names}} {{.State}}"],
                       capture_output=True, text=True)
    return [l for l in p.stdout.splitlines() if l.strip()]


@unittest.skipUnless(DOCKER, f"Docker ou image {IMAGE} indisponible")
class Docker(test_pmx.Pilot):
    def tearDown(self):
        for line in own_containers(self.root.resolve()):  # uniquement les conteneurs de CE dépôt jetable
            subprocess.run(["docker", "rm", "-f", line.split()[0]], capture_output=True)
        super().tearDown()

    def dtask(self, key, team_, files, details=""):
        t = self.task(key, team_, files)
        t["details"] = details
        return t

    def keep(self, run, name):
        """PMX_EVIDENCE_DIR=<dossier> : conserve les preuves du run (sondes, container-*.json, journal) hors du dépôt jetable."""
        dest = os.environ.get("PMX_EVIDENCE_DIR")
        if dest:
            import shutil
            shutil.copytree(self.root / "ai_memory" / "runs" / run, pathlib.Path(dest) / name, dirs_exist_ok=True)

    def evidence(self, run, key):
        return [json.loads(p.read_text()) for p in sorted((self.root / "ai_memory" / "runs" / run / "tasks" / key).glob("container-*.json"))]

    def report(self, run, key, n=1):
        return (self.root / "ai_memory" / "runs" / run / "tasks" / key / f"report-a{n}.md").read_text()

    def assert_policy(self, ev, wt):
        hc = ev["host_config"]
        self.assertFalse(hc["Privileged"])
        self.assertTrue(hc["ReadonlyRootfs"])
        self.assertEqual(hc["CapDrop"], ["ALL"])
        self.assertFalse(hc["CapAdd"])
        self.assertIn("no-new-privileges", " ".join(hc["SecurityOpt"]))
        self.assertEqual(hc["NetworkMode"], "none")
        self.assertEqual(hc["IpcMode"], "private")
        self.assertFalse(hc["PidMode"])
        self.assertGreater(hc["Memory"], 0)
        self.assertGreater(hc["PidsLimit"], 0)
        self.assertEqual(ev["user"], f"{os.getuid()}:{os.getgid()}")
        self.assertNotEqual(ev["user"].split(":")[0], "0")
        self.assertEqual(sorted(ev["env_keys"]), ["HOME", "PATH", "PMX_BRIEF", "PMX_MODE", "PMX_WORK"])
        dests = {m["Destination"]: (m["Source"], m["RW"]) for m in ev["mounts"]}
        self.assertEqual(set(dests), {"/work", "/work/.git", "/pmx/brief.md", "/agent"})
        self.assertEqual(dests["/work"], (str(pathlib.Path(wt).resolve()), True))
        self.assertFalse(dests["/work/.git"][1])
        self.assertFalse(dests["/pmx/brief.md"][1])
        self.assertEqual(dests["/agent"], (str(AGENT_DIR), False))
        for m in ev["mounts"]:
            self.assertNotIn("docker.sock", m["Source"])
            self.assertNotEqual(m["Source"], os.path.expanduser("~"))

    # ------------------------------------------------------------------ configuration

    def test_d01_config_refuses_extra_mounts_privileges_network(self):
        home = pathlib.Path(subprocess.run(["sh", "-c", "getent passwd $(id -u) | cut -d: -f6"], capture_output=True, text=True).stdout.strip())
        cases = [({"mounts": ["/var/run/docker.sock:/var/run/docker.sock"]}, "clé non autorisée 'mounts'"),
                 ({"privileged": True}, "clé non autorisée 'privileged'"),
                 ({"extra_args": ["--privileged"]}, "clé non autorisée 'extra_args'"),
                 ({"network": "bridge"}, "réseau 'bridge' refusé"),
                 ({"agent_dir": str(home)}, "HOME, dépôt, worktrees ou système"),
                 ({"agent_dir": "/"}, "HOME, dépôt, worktrees ou système"),
                 ({"agent_dir": "."}, "dans le dépôt ou les worktrees"),
                 ({"agent_dir": "/var/run"}, "HOME, dépôt, worktrees ou système"),
                 ({"memory": "unlimited"}, "memory invalide"),
                 ({"pids": 0}, "pids hors bornes"),
                 ({"image": "alpine:3.22 --privileged"}, "image invalide")]
        for extra, why in cases:
            with self.subTest(extra=extra):
                self.tmp_reset()
                self.config({"team-a": dteam("ok", **extra), "team-b": dteam("ok")})
                run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
                p = self.pmx("dispatch", "--run", run, code=64)
                self.assertIn(why, p.stderr)
                self.assertFalse((self.tmp / "wt").exists() and any((self.tmp / "wt").iterdir()))  # rien lancé, aucun worktree
                self.assertEqual(own_containers(self.root.resolve()), [])

    def tmp_reset(self):
        for line in own_containers(self.root.resolve()):
            subprocess.run(["docker", "rm", "-f", line.split()[0]], capture_output=True)
        super().tearDown()
        self.setUp()

    def test_d02_policy_check_rejects_unsafe_inspect(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        wt, brief = "/x/wt", "/x/brief.md"
        good = {"HostConfig": {"Privileged": False, "CapAdd": None, "CapDrop": ["ALL"], "ReadonlyRootfs": True, "SecurityOpt": ["no-new-privileges"],
                               "NetworkMode": "none", "PidMode": "", "IpcMode": "private", "UsernsMode": "", "Devices": [], "Memory": 1, "NanoCpus": 1,
                               "PidsLimit": 1, "Tmpfs": {"/tmp": "size=1m"}},
                "Config": {"User": "1000:1000"},
                "Mounts": [{"Type": "bind", "Source": wt, "Destination": "/work", "RW": True},
                           {"Type": "bind", "Source": brief, "Destination": "/pmx/brief.md", "RW": False}]}
        d = {"agent_dir": None}
        self.assertEqual(m.docker_policy(good, d, wt, brief, "write"), [])
        def bad(path, value):
            x = json.loads(json.dumps(good))
            o = x
            for k in path[:-1]:
                o = o[k]
            o[path[-1]] = value
            return m.docker_policy(x, d, wt, brief, "write")
        self.assertTrue(bad(("HostConfig", "Privileged"), True))
        self.assertTrue(bad(("HostConfig", "CapAdd"), ["SYS_ADMIN"]))
        self.assertTrue(bad(("HostConfig", "NetworkMode"), "bridge"))
        self.assertTrue(bad(("HostConfig", "PidMode"), "host"))
        self.assertTrue(bad(("HostConfig", "ReadonlyRootfs"), False))
        self.assertTrue(bad(("Config", "User"), "0:0"))
        self.assertTrue(bad(("Config", "User"), ""))
        self.assertTrue(bad(("HostConfig", "Tmpfs"), {"/tmp": "", "/run": ""}))
        sock = good["Mounts"] + [{"Type": "bind", "Source": "/var/run/docker.sock", "Destination": "/var/run/docker.sock", "RW": True}]
        self.assertTrue(bad(("Mounts",), sock))
        self.assertTrue(bad(("Mounts",), [dict(good["Mounts"][0], Source="/srv/other-team-worktree")] + good["Mounts"][1:]))
        self.assertTrue(m.docker_policy(good, d, wt, brief, "read"))  # /work en écriture alors que la revue est en lecture seule

    # ------------------------------------------------------------------ deux équipes parallèles, cycle complet

    def test_d03_two_containers_in_parallel_full_cycle(self):
        self.config({"team-a": dteam("slow"), "team-b": dteam("slow")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"]), self.dtask("b", "team-b", ["test/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        deadline = time.time() + 20
        while time.time() < deadline and len([l for l in own_containers(self.root.resolve()) if l.endswith("running")]) < 2:
            time.sleep(0.2)
        live = own_containers(self.root.resolve())
        self.assertEqual(len([l for l in live if l.endswith("running")]), 2, live)  # deux conteneurs distincts, simultanés
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("evidence", "--run", run, code=0)
        par = json.loads((self.root / "ai_memory" / "runs" / run / "parallelism.json").read_text())
        self.assertGreater(par["overlaps"][0]["seconds"], 1.0)
        self.keep(run, "d03-parallel")
        st = self.run_state(run)
        for key in ("a", "b"):
            ev = self.evidence(run, key)
            self.assertEqual(len(ev), 1)
            self.assert_policy(ev[0], st["tasks"][key]["attempts"][0]["worktree"])
            self.assertEqual(ev[0]["state"]["ExitCode"], 0)
        self.assertNotEqual(self.evidence(run, "a")[0]["name"], self.evidence(run, "b")[0]["name"])
        self.assertEqual(own_containers(self.root.resolve()), [])  # conteneurs supprimés, preuves gardées
        for wi in wis:
            self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=2)  # sans terminal humain : refus (C3)
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", agent_env=True, code=2)
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        files = self.git("ls-tree", "-r", "--name-only", "pilot/integration").split()
        self.assertIn("src/a.js", files)
        self.assertIn("test/b.js", files)
        self.assertEqual(self.git("remote"), "")

    # ------------------------------------------------------------------ séparation entre équipes (sondes)

    def test_d04_isolation_probes_between_two_teams(self):
        self.config({"team-a": dteam("probe"), "team-b": dteam("probe")})
        home = subprocess.run(["sh", "-c", "getent passwd $(id -u) | cut -d: -f6"], capture_output=True, text=True).stdout.strip()
        wt = (self.tmp / "wt").resolve()
        common = f"{home}:{self.root.resolve()}:{wt}:{self.tmp.resolve()}:{PMX.parent}"
        tasks = [self.dtask("a", "team-a", ["src/a.js"], f"MARKER=marker-aaaa-7f3e OTHER=marker-bbbb-91c2 HOSTPATHS={wt}/b-a1:{common}"),
                 self.dtask("b", "team-b", ["src/b.js"], f"MARKER=marker-bbbb-91c2 OTHER=marker-aaaa-7f3e HOSTPATHS={wt}/a-a1:{common}")]
        (self.tmp / "home" / ".ssh").mkdir()
        (self.tmp / "home" / ".ssh" / "id_ed25519").write_text("FAKE-PRIVATE-KEY-not-real\n")  # secret factice côté hôte
        run, wis = self.to_approved(tasks)
        gitfile = {k: None for k in ("a", "b")}
        self.pmx("dispatch", "--run", run, code=0)
        st = self.run_state(run)
        for k in gitfile:
            gitfile[k] = (pathlib.Path(st["tasks"][k]["attempts"][0]["worktree"]) / ".git").read_text()
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        expected = {"rw_own", "write_gitfile", "tmpfs_limited", "tmp_noexec", "other_team_marker_absent", "home_empty", "env_minimal",
                    "no_secret_files", "no_docker_socket", "mounts_expected", "net_only_loopback", "net_egress_blocked", "docker_api_unreachable",
                    "non_root", "no_new_privs", "no_capabilities", "mount_denied", "su_denied", "chroot_denied", "pid_namespace_private",
                    "symlink_to_host_dead"} | {f"write_outside:{d}" for d in ("/", "/etc", "/usr", "/pmx", "/agent", "/work/.git", "/root", "/var", "/opt")}
        out = {}
        for k in ("a", "b"):
            rep = self.report(run, k)
            probes = re.findall(r"^PROBE (\S+) (OK|FAIL) ?(.*)$", rep, re.M)
            out[k] = probes
            names = {n.split(":")[0] if n.startswith("hostpath_absent") else n for n, _, _ in probes}
            self.assertTrue(expected <= names, expected - names)
            self.assertIn("hostpath_absent", names)
            fails = [p for p in probes if p[1] != "OK"]
            self.assertEqual(fails, [], f"équipe {k} : {fails}")
            self.assertEqual((pathlib.Path(st["tasks"][k]["attempts"][0]["worktree"]) / ".git").read_text(), gitfile[k])
        (self.root / "ai_memory" / "runs" / run / "probes.json").write_text(json.dumps(out, indent=2))
        self.keep(run, "d04-isolation-probes")
        self.assertIn("marker-aaaa-7f3e", (pathlib.Path(st["tasks"]["a"]["attempts"][0]["worktree"]) / "src" / "a.js").read_text())
        for wi in wis:
            self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")  # modifications autorisées conservées et commitées

    # ------------------------------------------------------------------ arrêts

    def test_d05_scope_violation_kills_both_containers(self):
        self.config({"team-a": dteam("outside"), "team-b": dteam("hang")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"]), self.dtask("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("hors périmètre", p.stdout + p.stderr)
        time.sleep(1)
        self.assertEqual([l for l in own_containers(self.root.resolve()) if "running" in l], [])
        ev_b = self.evidence(run, "b")
        self.assertTrue(ev_b and ev_b[0]["state"]["ExitCode"] != 0)  # tué en cours d'exécution, preuve gardée
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assertTrue((self.tmp / "wt" / "a-a1" / "README.md").exists())  # worktree conservé comme preuve

    def test_d06_symlink_is_critical(self):
        self.config({"team-a": dteam("symlink"), "team-b": dteam("ok")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("lien symbolique → /etc/passwd", p.stdout + p.stderr)

    def test_d13_fifo_invisible_to_git_is_critical(self):
        self.config({"team-a": dteam("fifo"), "team-b": dteam("ok")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn(".hidden-pipe : fichier spécial", p.stdout + p.stderr)

    def test_d07_memory_limit_kills_container(self):
        self.config({"team-a": dteam("oom", memory="64m"), "team-b": dteam("ok")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        ev = self.evidence(run, "a")
        self.assertTrue(ev[0]["state"]["OOMKilled"])
        self.assertEqual(ev[0]["host_config"]["Memory"], 64 * 1024 * 1024)
        self.assertEqual(ev[0]["host_config"]["MemorySwap"], 64 * 1024 * 1024)  # pas de swap
        self.assertIn("oom-killed", self.ledger())
        self.assertEqual(self.status_of(next(iter(wis))), "ESCALATED")  # même cause deux fois → arrêt des relances
        self.assertEqual(len(self.run_state(run)["tasks"]["a"]["attempts"]), 2)

    def test_d08_pids_limit_contains_fork_bomb(self):
        self.config({"team-a": dteam("forkbomb", pids=32), "team-b": dteam("ok")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        m = re.search(r"PIDS_MAX (\d+) PIDS_PEAK (\d+) SPAWNED (\d+) FORKS_REFUSED (\d+)", self.report(run, "a"))
        self.assertEqual(int(m.group(1)), 32)
        self.assertLessEqual(int(m.group(2)), 32)  # pic du cgroup
        self.assertLess(int(m.group(3)), 200)  # 200 demandés
        self.assertGreater(int(m.group(4)), 0)  # refus comptés par le noyau

    def test_d09_cpu_quota_throttles(self):
        self.config({"team-a": dteam("cpu", cpus=0.5), "team-b": dteam("ok")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        rep = self.report(run, "a")
        self.assertIn("CPU_MAX 50000 100000", rep)
        self.assertGreater(int(re.search(r"nr_throttled (\d+)", rep).group(1)), 0)

    def test_d10_timeout_stops_container(self):
        self.config({"team-a": dteam("hang"), "team-b": dteam("ok")}, team_timeout_s=4, max_attempts=1)
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.assertEqual(own_containers(self.root.resolve()), [])
        self.assertEqual(self.run_state(run)["tasks"]["a"]["failures"][0]["kind"], "timeout")
        self.assertEqual(self.status_of(next(iter(wis))), "ESCALATED")

    def test_d11_resume_stops_orphan_container(self):
        self.config({"team-a": dteam("hang"), "team-b": dteam("ok")}, auto_retry=False)
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        time.sleep(2)
        st = self.run_state(run)
        att = st["tasks"]["a"]["attempts"][0]
        os.killpg(att["pid"], signal.SIGKILL)  # « coupure » côté hôte : le client docker meurt, le conteneur continue
        time.sleep(1)
        self.assertIn(f"{att['container']} running", own_containers(self.root.resolve()))
        out = self.pmx("resume", "--run", run, code=0).stdout
        self.assertIn("BLOCKED", out)
        self.assertEqual(own_containers(self.root.resolve()), [])
        self.assertTrue(self.evidence(run, "a"))
        self.assertIn("- blocker: interrupted", self.ledger())

    def test_d12_mixed_docker_and_process_teams(self):
        # compatibilité : une équipe docker et une équipe processus (adaptateur cmd du V3.1) dans le même run
        from test_pmx import team
        self.config({"team-a": dteam("slow"), "team-b": team("slow")})
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")
        self.assertTrue(self.evidence(run, "a"))
        self.assertFalse(self.evidence(run, "b"))

    # ------------------------------------------------------------------ vérification isolée (verify_runner docker)

    def real_home(self):
        return subprocess.run(["sh", "-c", "getent passwd $(id -u) | cut -d: -f6"], capture_output=True, text=True).stdout.strip()

    def payload_run(self, script, runner="docker", teams=None, **extra):
        """Une équipe livre `test/check.sh` (script piégé, fictif) ; la commande approuvée `sh test/check.sh` l'exécute à la vérification."""
        pf = self.tmp / "payload.sh"
        pf.write_text(script)
        cfg = {"allowed_test_commands": ["sh test/check.sh"], "verify_commands": []}
        if runner == "docker":
            cfg["verify_runner"] = VRUN
        cfg.update(extra)
        self.config(teams or {"team-a": test_pmx.team(f"copy={pf}"), "team-b": test_pmx.team("ok")}, **cfg)
        t = {**self.task("a", "team-a", ["test/check.sh"]), "test_command": "sh test/check.sh"}
        run, wis = self.to_approved([t])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        return run, next(iter(wis))

    def vresult(self, run):
        v = self.run_state(run)["tasks"]["a"]["verify"]
        return v, v["results"][0]

    def test_v01_tests_cannot_read_home_or_secrets(self):
        (self.tmp / "home" / ".ssh").mkdir()
        secret = self.tmp / "home" / ".ssh" / "id_ed25519"
        secret.write_text("FAKE-KEY-v01-not-real\n")
        run, wi = self.payload_run(f"cat {secret} || exit 7\n[ -d {self.real_home()} ] && echo HOME-VISIBLE\nexit 0\n")
        self.pmx("verify", "--run", run, code=1)
        v, r = self.vresult(run)
        self.assertEqual((v["verdict"], v["runner"], r["runner"], r["exit"]), ("FAIL", "docker", "docker", 7))
        self.assertNotIn("FAKE-KEY", r["output"])
        self.assertNotIn("HOME-VISIBLE", r["output"])
        self.assertIn("No such file", r["output"])

    def test_v02_host_runner_is_not_isolated(self):
        # contraste (mode 3.1 conservé) : le même script lit le secret factice sur l'hôte — signalé « NOT isolated »
        (self.tmp / "home" / ".ssh").mkdir()
        secret = self.tmp / "home" / ".ssh" / "id_ed25519"
        secret.write_text("FAKE-KEY-v02-not-real\n")
        run, wi = self.payload_run(f"cat {secret} || exit 7\nexit 0\n", runner="host")
        self.pmx("verify", "--run", run, code=0)
        v, r = self.vresult(run)
        self.assertEqual((v["verdict"], v["runner"]), ("PASS", "host"))
        self.assertIn("FAKE-KEY-v02", r["output"])  # fuite démontrée en mode hôte
        note = next((self.root / "ai_memory").glob("*__ROLE-verifier__*.md")).read_text()
        self.assertIn("host — NOT isolated", note)

    def test_v03_tests_have_no_network(self):
        run, wi = self.payload_run("wget -q -T 3 -O /dev/null http://1.1.1.1 && echo NET-OK\n"
                                   "wget -q -T 3 -O /dev/null http://host.docker.internal:2375/version && echo DOCKER-API-OK\n"
                                   "echo IFACES $(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | tr '\\n' ',')\nexit 0\n")
        self.pmx("verify", "--run", run, code=0)
        v, r = self.vresult(run)
        self.assertNotIn("NET-OK", r["output"])
        self.assertNotIn("DOCKER-API-OK", r["output"])
        self.assertIn("IFACES lo,", r["output"])

    def test_v04_writes_outside_checkout_are_contained(self):
        targets = [self.root / "PWNED-main", self.tmp / "PWNED-tmp", self.tmp / "home" / "PWNED-home", self.tmp / "wt" / "PWNED-wt"]
        run, wi = self.payload_run("for f in " + " ".join(map(str, targets)) + " /PWNED-root /etc/PWNED /tmp/ephemeral; do\n"
                                   "  (echo x > \"$f\") 2>/dev/null && echo \"WROTE $f\"\ndone\nexit 0\n")
        self.pmx("verify", "--run", run, code=0)
        v, r = self.vresult(run)
        self.assertEqual(re.findall(r"WROTE (\S+)", r["output"]), ["/tmp/ephemeral"])  # seul le tmpfs jetable du conteneur
        for f in targets:
            self.assertFalse(f.exists(), f)
        self.assertEqual(v["integrity"], [])

    def test_v05_head_and_gitdir_cannot_be_changed(self):
        run, wi = self.payload_run("(echo 'gitdir: /tmp/evil' > .git) 2>/dev/null && echo GITFILE-CHANGED\n"
                                   "(mv .git .git.moved) 2>/dev/null && echo GITFILE-MOVED\n(rm -f .git) 2>/dev/null; [ -e .git ] || echo GITFILE-REMOVED\n"
                                   "command -v git >/dev/null && echo GIT-PRESENT\nexit 0\n")
        refs = self.git("for-each-ref")
        self.pmx("verify", "--run", run, code=0)
        v, r = self.vresult(run)
        for marker in ("GITFILE-CHANGED", "GITFILE-MOVED", "GITFILE-REMOVED", "GIT-PRESENT"):
            self.assertNotIn(marker, r["output"])
        self.assertEqual((v["verdict"], v["integrity"]), ("PASS", []))  # C1 actif : HEAD, fichiers, refs, checkout principal inchangés
        self.assertEqual(self.git("for-each-ref").replace(refs, ""), "")

    def test_v06_untracked_file_is_inconclusive(self):
        run, wi = self.payload_run("touch generated-by-tests.txt\nexit 0\n")
        p = self.pmx("verify", "--run", run, code=2)
        v, r = self.vresult(run)
        self.assertEqual((v["verdict"], v["runner"]), ("INCONCLUSIVE", "docker"))
        self.assertIn("?? generated-by-tests.txt", pathlib.Path(v["evidence"]).read_text())
        self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assertTrue(list((self.root / "ai_memory" / "runs" / run / "verify" / "a").glob("container-*.json")))
        self.pmx("integrate", "--run", run, "--dry-run", code=1)  # bloque l'intégration

    def test_v07_cleanup_failure_is_inconclusive(self):
        (self.root / ".gitignore").write_text("build/\n")
        self.git("add", ".gitignore")
        self.git("commit", "-qm", "ignore build")
        run, wi = self.payload_run("mkdir -p build/locked && touch build/locked/f && chmod 500 build/locked\nexit 0\n")
        try:
            p = self.pmx("verify", "--run", run, code=2)
            self.assertIn("nettoyage du checkout impossible", p.stdout)
            self.assertEqual(self.vresult(run)[0]["verdict"], "INCONCLUSIVE")
        finally:
            for d in (self.tmp / "wt").glob("_verify-*/build/locked"):
                d.chmod(0o700)

    def test_v08_interrupted_container_is_inconclusive(self):
        run, wi = self.payload_run("sleep 30\nexit 0\n")
        proc = subprocess.Popen([PY, "-I", str(PMX), "--root", str(self.root), "verify", "--run", run], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=self.env, start_new_session=True)
        killed, deadline = None, time.time() + 30
        while not killed and time.time() < deadline:
            names = subprocess.run(["docker", "ps", "--filter", f"label=pmx.root={self.root.resolve()}", "--filter", "label=pmx.kind=verify",
                                    "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
            if names:
                time.sleep(1)
                subprocess.run(["docker", "kill", names[0]], capture_output=True)
                killed = names[0]
            time.sleep(0.2)
        out = proc.communicate(timeout=120)[0]
        self.assertTrue(killed)
        self.assertEqual(proc.returncode, 2, out)
        self.assertIn("conteneur tué par un signal", out)
        self.assertEqual(self.vresult(run)[0]["verdict"], "INCONCLUSIVE")
        self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assertEqual(len(self.run_state(run)["tasks"]["a"]["attempts"]), 1)  # aucune relance automatique
        p = self.pmx("integrate", "--run", run, "--dry-run", code=1)
        self.assertIn("✘ au moins une tâche READY_FOR_REVIEW", p.stdout)

    def test_v09_impossible_verification_never_falls_back_to_host(self):
        marker = self.tmp / "RAN-ON-HOST"
        run, wi = self.payload_run(f"echo ran > {marker}\nexit 0\n", verify_runner={"adapter": "docker", "docker": {**VRUN["docker"], "image": "pmx-absent-image:none"}})
        p = self.pmx("verify", "--run", run, code=2)
        self.assertIn("conteneur non créé", p.stdout)
        self.assertFalse(marker.exists())
        self.assertEqual(self.vresult(run)[0]["verdict"], "INCONCLUSIVE")

    def test_v10_runner_config_cannot_add_command_or_mount(self):
        for bad in ({"argv": ["sh", "-c", "id"]}, {"mounts": ["/:/host"]}, {"network": "bridge"}):
            with self.subTest(bad=bad):
                self.tmp_reset()
                run, wi = self.payload_run("exit 0\n", verify_runner={"adapter": "docker", "docker": {**VRUN["docker"], **bad}})
                p = self.pmx("verify", "--run", run, code=2)
                self.assertIn("vérification REFUSÉE, rien n'a été exécuté", p.stdout)
                self.assertEqual(list((self.tmp / "wt").glob("_verify-*")), [])

    def test_v11_policy_requires_isolated_verification(self):
        run, wi = self.payload_run("exit 0\n", runner="host")
        pol = self.root / ".claude" / "pmx.integration-policy.json"
        pol.write_text(json.dumps({**json.loads(pol.read_text()), "require_isolated_verification": True}))
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=1)
        self.assertIn("✘ politique : tests sur l'arbre fusionné en conteneur isolé", out)
        self.assertIn("✘ a : vérification faite en conteneur isolé", out)
        self.assertNotIn("pilot/integration", self.git("branch", "--list"))

    def test_v12_full_cycle_docker_teams_isolated_verification_no_git_hook_or_filter(self):
        marker = self.tmp / "HOOK-OR-FILTER-RAN"
        self.config({"team-a": dteam("ok"), "team-b": dteam("ok")}, verify_runner=VRUN,
                    allowed_test_commands=["test -f src/a.js", "test -f src/b.js"], verify_commands=["test -f README.md"])
        pol = self.root / ".claude" / "pmx.integration-policy.json"
        pol.write_text(json.dumps({**json.loads(pol.read_text()), "require_isolated_verification": True}))
        hooks = self.root / ".githooks"
        hooks.mkdir()
        for h in ("pre-commit", "commit-msg", "post-commit", "post-checkout", "pre-merge-commit", "post-merge", "reference-transaction",
                  "post-rewrite", "pre-auto-gc", "post-index-change", "prepare-commit-msg"):
            (hooks / h).write_text(f"#!/bin/sh\necho \"hook {h}\" >> {marker}\n")
            (hooks / h).chmod(0o755)
        (self.root / ".gitattributes").write_text("*.js filter=evil diff=evil\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "hooks (husky-like) and attributes — trusted base")
        self.git("config", "core.hooksPath", ".githooks")  # hooks versionnés, présents dans chaque worktree
        with open(self.tmp / "gitconfig", "a") as g:  # pilotes globaux de l'utilisateur (cf. git-lfs) : jamais utilisés par pmx
            g.write(f"[filter \"evil\"]\n\tclean = sh -c 'echo filter-clean >> {marker}; cat'\n\tsmudge = sh -c 'echo filter-smudge >> {marker}; cat'\n"
                    f"[diff \"evil\"]\n\ttextconv = sh -c 'echo textconv >> {marker}; cat'\n")
        run, wis = self.to_approved([self.dtask("a", "team-a", ["src/a.js"]), self.dtask("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("evidence", "--run", run, code=0)
        self.assertGreater(json.loads((self.root / "ai_memory" / "runs" / run / "parallelism.json").read_text())["overlaps"][0]["seconds"], 0)
        self.pmx("verify", "--run", run, code=0)
        st = self.run_state(run)
        for k in ("a", "b"):
            self.assertEqual((st["tasks"][k]["verify"]["verdict"], st["tasks"][k]["verify"]["runner"]), ("PASS", "docker"))
            self.assertTrue(all(r["runner"] == "docker" for r in st["tasks"][k]["verify"]["results"]))
        self.pmx("review", "run", "--run", run, code=0)
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=2)  # C3 : pas de terminal humain
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        self.assertIn("conteneur isolé", out)
        self.assertIn("✔ politique : tests sur l'arbre fusionné en conteneur isolé", out)
        self.assertIn("runner: docker", (self.root / "ai_doc" / f"DECISIONS__{run}.md").read_text())
        self.assertTrue(list((self.root / "ai_memory" / "runs" / run / "integrate").glob("container-*.json")))
        for wi in wis:
            self.assertEqual(self.status_of(wi), "DONE")
        self.assertFalse(marker.exists(), marker.read_text() if marker.exists() else "")  # aucun hook, filtre ni textconv exécuté par pmx
        self.keep(run, "v12-full-cycle-isolated-verification")
        subprocess.run(["git", "-C", str(self.root), "commit", "-q", "--allow-empty", "-m", "control"], env=self.env, capture_output=True)
        self.assertIn("hook pre-commit", marker.read_text())  # témoin : les hooks sont bien actifs pour un git ordinaire

    def test_v13_git_metadata_files_are_sensitive(self):
        self.config({"team-a": dteam("ok"), "team-b": dteam("ok")})
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        for f in (".gitattributes", "src/.gitattributes", ".gitmodules", "vendor/x/.git/config", ".githooks/post-commit"):
            t = {**self.task("a", "team-a", ["src/a.js"]), "files": [f]}
            p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([t])), code=1)
            self.assertIn("chemin sensible", p.stdout, f)


# Les tests hérités de test_pmx.Pilot (helpers partagés) ne sont pas rejoués ici.
for _n in [n for n in dir(test_pmx.Pilot) if n.startswith("test_")]:
    setattr(Docker, _n, None)


if __name__ == "__main__":
    unittest.main()
