#!/usr/bin/env python3
"""Tests de l'arrêt critique vérifié (scope systemd utilisateur, cgroup v2) : uniquement des processus factices lancés ici.

Chaque test lance aussi un processus témoin étranger, qui consigne tout SIGTERM reçu : il doit rester intact.
Usage : python3 -I tests/pilot/test_stop.py -v
"""
import importlib.util, json, os, pathlib, shutil, signal, subprocess, sys, textwrap, time, types, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pmx  # noqa: E402

PY = sys.executable
AGENT = textwrap.dedent("""\
    import os, pathlib, signal, sys, time
    mode, base = sys.argv[1], pathlib.Path(sys.argv[2])
    def beat(name):
        (base / f"{name}.pid").write_text(str(os.getpid()))
        for _ in range(300):
            with (base / f"{name}.beat").open("a") as f:
                f.write(f"{time.time()}\\n")
            time.sleep(0.1)
    if mode in ("ignore", "escape"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with (base / "launches.log").open("a") as f:
        f.write("x\\n")
    if mode == "leave":  # livre son travail et laisse un descendant détaché qui continue d'écrire
        cwd, out = pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4])
        (cwd / "src").mkdir(exist_ok=True)
        (cwd / "src" / "b.js").write_text("// ok\\n")
        (cwd / "test").mkdir(exist_ok=True)
        out.write_text("Status: DONE\\n")
        if os.fork() == 0:
            os.setsid()
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            for fd in (0, 1, 2):
                os.dup2(os.open(os.devnull, os.O_RDWR), fd)
            beat("left")
        os._exit(0)
    if mode == "escape" and os.fork() == 0:
        os.setsid()
        if os.fork() != 0:
            os._exit(0)
        beat("escaped")
        os._exit(0)
    beat("agent")
""")
WITNESS = textwrap.dedent("""\
    import pathlib, signal, sys, time
    log = pathlib.Path(sys.argv[1])
    signal.signal(signal.SIGTERM, lambda *_: log.write_text("SIGTERM"))
    log.with_suffix(".ready").write_text("ok")
    time.sleep(300)
""")


def load_pmx():
    spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STOP_VERIFY_S = 1.0
    return m


def alive(pid):
    try:
        return pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


TRACKING = load_pmx().team_tracking_problem()


class Stop(test_pmx.Pilot):
    def setUp(self):
        super().setUp()
        self.base = self.tmp / "agents"
        self.base.mkdir()
        (self.tmp / "stop_agent.py").write_text(AGENT)
        (self.tmp / "witness.py").write_text(WITNESS)
        self.log = self.tmp / "witness.log"
        self.witness = subprocess.Popen([PY, "-I", str(self.tmp / "witness.py"), str(self.log)], start_new_session=True)
        for _ in range(100):
            if self.log.with_suffix(".ready").exists():
                break
            time.sleep(0.05)
        self.runs = []

    def tearDown(self):
        foreign_intact = self.witness.poll() is None and not self.log.exists()
        self.witness.kill()
        self.witness.wait()
        for run in self.runs:  # filet : aucun processus de test ne survit au test, même en échec
            for t in self.state(run)["tasks"].values():
                for a in t["attempts"]:
                    if a.get("cgroup"):
                        try:
                            pathlib.Path("/sys/fs/cgroup" + a["cgroup"], "cgroup.kill").write_text("1")
                        except OSError:
                            pass
        for f in self.base.glob("*.pid"):
            pid = int(f.read_text())
            if alive(pid):
                os.kill(pid, 9)
        super().tearDown()
        self.assertTrue(foreign_intact, "processus étranger touché")

    def state(self, run):
        return json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())

    def save(self, run, st):
        (self.root / "ai_memory" / "runs" / run / "run.json").write_text(json.dumps(st))

    def go(self, mode="ignore", first="outside"):
        b = {**self.stub(mode), "label": "stop", "reviewer": test_pmx.team("ok")["reviewer"]}
        self.config({"team-a": test_pmx.team(first), "team-b": b})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.runs.append(run)
        self.pmx("dispatch", "--run", run, code=0)
        self.wait_file(self.base / ("escaped.pid" if mode == "escape" else "agent.pid"))
        return run, wis

    def stub(self, mode):
        return {"adapter": "cmd", "argv": [PY, "-I", str(self.tmp / "stop_agent.py"), mode, str(self.base), "{cwd}", "{out_file}"]}

    def manager(self, *a):
        return subprocess.Popen([PY, "-I", "-B", str(test_pmx.PMX), "--root", str(self.root), *a], env=self.env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def to_debate(self):
        """Un débat dont le premier tour est un agent qui ignore SIGTERM."""
        self.config({"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
        c = self.root / ".claude" / "project-manager.config.json"
        cfg = json.loads(c.read_text())
        cfg["orchestration"]["debate"]["agents"]["claude"] = self.stub("ignore")
        c.write_text(json.dumps(cfg))
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.runs.append(run)
        return run

    def to_review(self):
        """Deux tâches prêtes pour la revue, avec des relecteurs qui ignorent SIGTERM."""
        self.config({"team-a": {**test_pmx.team("ok"), "reviewer": self.stub("ignore")}, "team-b": {**test_pmx.team("ok"), "reviewer": self.stub("ignore")}})
        run, _ = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.runs.append(run)
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("verify", "--run", run, code=0)
        return run

    def assert_helper_stopped(self, run):
        st = self.state(run)
        self.assertTrue(st["helpers"])
        for h in st["helpers"]:
            self.assertIsNotNone(h["ended"])
            self.assertFalse(pathlib.Path("/sys/fs/cgroup" + h["cgroup"]).exists())
        self.assertFalse(alive(self.apid()))

    def wait_file(self, f):
        for _ in range(200):
            if f.exists() and f.read_text().strip():
                return
            time.sleep(0.05)
        self.fail(f"{f} absent")

    def violation_ready(self):
        time.sleep(3)  # team-a écrit hors périmètre à 2,5 s : le premier passage de surveillance déclenche l'arrêt

    def apid(self, name="agent"):
        return int((self.base / f"{name}.pid").read_text())

    def wait_stop(self, run):
        return self.pmx("wait", "--run", run, "--interval", "0.3", code=3)

    def writes_after(self, name, t0):
        return sum(float(x) > t0 for x in (self.base / f"{name}.beat").read_text().splitlines())

    def assert_blocked(self, run):
        """Arrêt non résolu : plus aucune équipe, plus d'intégration."""
        for args in (("dispatch", "--run", run), ("integrate", "--run", run, "--dry-run"), ("verify", "--run", run), ("reopen", "--run", run, "--task", "b", "--by", "human:x", "--reason", "r")):
            p = self.pmx(*args, code=3)
            self.assertIn("arrêt critique non résolu", p.stdout + p.stderr)


@unittest.skipIf(TRACKING, f"scope systemd utilisateur indisponible : {TRACKING}")
class WithCgroup(Stop):
    def assert_stopped(self, run, p):
        st = self.state(run)
        self.assertEqual(st["stop"]["state"], "STOPPED", st["stop"])
        self.assertIn("équipes arrêtées", p.stdout)
        self.assertIn("arrêt vérifié", p.stdout)
        for t in st["tasks"].values():
            for a in t["attempts"]:
                self.assertFalse(pathlib.Path("/sys/fs/cgroup" + a["cgroup"]).exists(), a["cgroup"])
        ev = [json.loads(x) for x in (self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()]
        self.assertEqual(ev[-1]["state"], "STOPPED")
        self.assertTrue(all(r["populated_after"] is False for r in ev[-1]["attempts"]))

    def test_01_main_process_stops_normally(self):
        run, wis = self.go("normal")
        p = self.wait_stop(run)
        self.assert_stopped(run, p)
        self.assertFalse(alive(self.apid()))
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")

    def test_02_descendant_ignoring_sigterm_survives_dead_leader_then_is_killed(self):
        run, _ = self.go("ignore")
        leader = self.state(run)["tasks"]["b"]["attempts"][0]["pid"]
        pgid = os.getpgid(self.apid())
        p = self.wait_stop(run)
        t0 = time.time()
        self.assert_stopped(run, p)
        self.assertFalse(alive(leader))
        self.assertFalse(alive(self.apid()))
        self.assertEqual(self.writes_after("agent", t0), 0)
        ev = json.loads((self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()[-1])
        row = next(r for r in ev["attempts"] if r["task"] == "b")
        self.assertTrue(row["killed"])  # SIGTERM n'a pas suffi
        self.assertIn(leader, row["term"])
        self.assertEqual(pgid, leader)

    def test_03_descendant_leaving_process_group_is_killed(self):
        run, _ = self.go("escape")
        pid = self.apid("escaped")
        self.assertNotEqual(os.getpgid(pid), self.state(run)["tasks"]["b"]["attempts"][0]["pid"])
        p = self.wait_stop(run)
        t0 = time.time()
        self.assert_stopped(run, p)
        self.assertFalse(alive(pid))
        self.assertEqual(self.writes_after("escaped", t0), 0)

    def test_04_reused_pid_foreign_process_untouched(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        st = self.state(run)
        st["tasks"]["b"]["attempts"][0]["pid"] = self.witness.pid  # PID enregistré, désormais porté par un étranger
        self.save(run, st)
        p = self.wait_stop(run)
        self.assertEqual(self.state(run)["stop"]["state"], "STOPPED", p.stdout)
        self.assertFalse(alive(self.apid()))  # la vraie tentative est arrêtée par son cgroup
        self.assertIsNone(self.witness.poll())
        self.assertFalse(self.log.exists())

    def test_05_leader_already_dead_descendants_still_stopped(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        leader = self.state(run)["tasks"]["b"]["attempts"][0]["pid"]
        os.kill(leader, signal.SIGKILL)
        for _ in range(100):
            if not alive(leader):
                break
            time.sleep(0.05)
        self.assertTrue(alive(self.apid()))
        p = self.wait_stop(run)
        self.assert_stopped(run, p)
        self.assertFalse(alive(self.apid()))

    def test_06_empty_groups_reported_stopped_without_signal(self):
        self.config({"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
        run, _ = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.runs.append(run)
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        p = self.pmx("abort", "--run", run, code=3)
        self.assert_stopped(run, p)
        ev = json.loads((self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()[-1])
        self.assertTrue(all(r["term"] == [] and not r.get("killed") for r in ev["attempts"]))

    def test_07_uncertain_identity_no_signal_stays_unresolved(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        st = self.state(run)
        a = st["tasks"]["b"]["attempts"][0]
        real = dict(a)
        for bad in ({"cgroup": "/init.scope"}, {"unit": "init.scope", "cgroup": "/init.scope"}, {"cgroup": a["cgroup"].rsplit("/", 1)[0] + "/../" + a["unit"]}):
            a.update(real, **bad)
            self.assertIsNone(load_pmx().attempt_cgroup(a), bad)
        a.update(real, cgroup="/init.scope")
        self.save(run, st)
        p = self.wait_stop(run)
        self.assertIn("ARRÊT NON RÉSOLU", p.stdout)
        self.assertNotIn("équipes arrêtées", p.stdout)
        self.assertIn("identité incertaine", p.stdout)
        self.assertEqual(self.state(run)["stop"]["state"], "UNRESOLVED")
        self.assertTrue(alive(self.apid()))  # aucun signal : l'agent n'a pas pu être confirmé, et on le dit
        self.assert_blocked(run)
        self.assertEqual(self.state(run)["stop"]["state"], "UNRESOLVED")
        st = self.state(run)
        st["tasks"]["b"]["attempts"][0].update(cgroup=real["cgroup"])  # pour le filet de tearDown
        self.save(run, st)

    def test_08_signal_failure_is_unresolved_then_rechecked(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        m = load_pmx()
        def refuse(*_a):
            raise PermissionError(1, "refusé")
        real, m.signal.pidfd_send_signal = m.signal.pidfd_send_signal, refuse
        try:
            rc = m.abort_all(m.Ctx(self.root), run, "essai")
        finally:
            m.signal.pidfd_send_signal = real
        self.assertEqual(rc, m.EXIT_CRITICAL)
        st = self.state(run)["stop"]
        self.assertEqual(st["state"], "UNRESOLVED")
        self.assertTrue(any("SIGTERM (PermissionError)" in x for x in st["problems"]), st)
        self.assert_blocked(run)
        self.pmx("tick", "--run", run, code=3)  # revérification : plus rien de vivant, plus d'erreur
        self.assertEqual(self.state(run)["stop"]["state"], "STOPPED")

    def test_09a_kill_failure_keeps_process_declared_alive(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        m = load_pmx()
        m.cgroup_kill = lambda cg: "cgroup.kill (PermissionError)"
        m.abort_all(m.Ctx(self.root), run, "essai")
        st = self.state(run)["stop"]
        self.assertEqual(st["state"], "UNRESOLVED")
        self.assertTrue(any("encore actifs" in x for x in st["problems"]), st)
        self.assertTrue(alive(self.apid()))
        self.assert_blocked(run)
        rc, text = self.pmx_tty("stop-ack", "--run", run, "--by", "human:x", code=0)  # processus survivant : l'incident est consigné, rien ne change
        self.assertIn("verdict technique inchangé : UNRESOLVED", text)
        st = self.state(run)["stop"]
        self.assertEqual(st["state"], "UNRESOLVED")
        self.assertEqual(st["ack"]["alive_seen"], [self.state(run)["tasks"]["b"]["attempts"][0]["unit"]])
        self.assertTrue(alive(self.apid()))
        self.assert_blocked(run)
        self.pmx("tick", "--run", run, code=3)
        self.assertEqual(self.state(run)["stop"]["state"], "STOPPED")
        self.assertFalse(alive(self.apid()))

    def test_09b_unreadable_verification_is_never_success(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        m = load_pmx()
        m.cgroup_populated = lambda cg: None
        m.abort_all(m.Ctx(self.root), run, "essai")
        st = self.state(run)["stop"]
        self.assertEqual(st["state"], "UNRESOLVED")
        self.assertTrue(any("indéterminé" in x for x in st["problems"]), st)
        self.assert_blocked(run)

    def test_10_manager_interrupted_during_stop(self):
        run, wis = self.go("ignore")
        self.violation_ready()
        code = ("import importlib.util, os, sys\n"
                f"s = importlib.util.spec_from_file_location('pmx', {str(test_pmx.PMX)!r}); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                "m.cgroup_kill = lambda cg: os._exit(137)\n"  # mort brutale entre SIGTERM et SIGKILL
                f"m.main(['--root', {str(self.root)!r}, 'abort', '--run', {run!r}])\n")
        self.assertEqual(subprocess.run([PY, "-I", "-B", "-c", code], env=self.env, capture_output=True).returncode, 137)
        st = self.state(run)
        self.assertEqual(st["stop"]["state"], "IN_PROGRESS")
        self.assertTrue(alive(self.apid()))
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assert_blocked(run)
        self.assertIn("IN_PROGRESS", self.pmx("status", "--run", run, code=0).stdout)
        p = self.pmx("tick", "--run", run, code=3)  # le passage suivant reprend la procédure jusqu'au bout
        self.assert_stopped(run, p)
        self.assertFalse(alive(self.apid()))

    def test_11_two_parallel_teams_one_violates(self):
        run, wis = self.go("ignore")
        st = self.state(run)
        a, b = (st["tasks"][k]["attempts"][0] for k in "ab")
        self.assertNotEqual(a["unit"], b["unit"])
        self.assertTrue(pathlib.Path("/sys/fs/cgroup" + b["cgroup"]).exists())
        self.assertEqual(self.pmx("tick", "--run", run).returncode, 0)  # avant la violation : aucune équipe touchée
        self.assertTrue(alive(self.apid()))
        p = self.wait_stop(run)
        self.assert_stopped(run, p)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")

    def test_13_ack_is_administrative_and_recovery_is_a_new_run(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        st = self.state(run)
        real = st["tasks"]["b"]["attempts"][0]["cgroup"]
        st["tasks"]["b"]["attempts"][0]["cgroup"] = "/init.scope"
        self.save(run, st)
        self.wait_stop(run)
        self.pmx("stop-ack", "--run", run, "--by", "x", code=64)
        rc, text = self.pmx_tty("stop-ack", "--run", run, "--by", "human:x", agent_env=True, code=2)
        self.assertIn("session d'agent", text)
        self.pmx_tty("stop-ack", "--run", run, "--by", "human:x", answer="non", code=2)
        self.assertNotIn("ack", self.state(run)["stop"])
        self.pmx_tty("stop-ack", "--run", run, "--by", "human:x", code=0)
        for _ in range(2):  # reprise impossible : ni l'acquittement ni la revérification ne prouvent l'arrêt
            self.pmx("tick", "--run", run, code=3)
            stop = self.state(run)["stop"]
            self.assertEqual(stop["state"], "UNRESOLVED")
            self.assertEqual(stop["ack"]["by"], "human:x")  # conservé d'une vérification à l'autre
            self.assert_blocked(run)
        out = self.pmx("status", "--run", run, code=0).stdout
        self.assertIn("verdict technique : UNRESOLVED", out)
        self.assertIn("Acquittement administratif", out)
        self.assertIn("récupération manuelle", out)
        self.assertNotIn("équipes arrêtées", out)
        other = self.pmx("start", "--title", "Reprise", "--request", "q", code=0).stdout.strip()  # procédure distincte : un nouveau run
        self.assertNotEqual(other, run)
        self.pmx("debate", "next", "--run", other, code=0)
        self.assertEqual(self.state(run)["stop"]["state"], "UNRESOLVED")
        st = self.state(run)
        st["tasks"]["b"]["attempts"][0]["cgroup"] = real
        self.save(run, st)


    def test_22_cgroup_being_removed_is_empty_other_errors_are_not(self):
        m = load_pmx()
        class Broken:
            def __init__(self, code):
                self.code = code
            def __truediv__(self, _name):
                return self
            def read_text(self):
                raise OSError(self.code, "x")
            def write_text(self, _t):
                raise OSError(self.code, "x")
        for code, populated, term_errs, kill_err in ((m.errno.ENODEV, False, 0, None), (m.errno.ENOENT, False, 0, None), (m.errno.EIO, None, 1, "cgroup.kill (OSError)"), (m.errno.EACCES, None, 1, "cgroup.kill (PermissionError)")):
            self.assertIs(m.cgroup_populated(Broken(code)), populated)
            self.assertEqual(len(m.cgroup_term(Broken(code), "/x")[1]), term_errs)
            self.assertEqual(m.cgroup_kill(Broken(code)), kill_err)

    def test_15_debate_manager_killed_then_agent_stopped(self):
        run = self.to_debate()
        mgr = self.manager("debate", "next", "--run", run)
        self.wait_file(self.base / "agent.pid")
        os.kill(mgr.pid, signal.SIGKILL)
        mgr.wait()
        self.assertTrue(alive(self.apid()))  # orphelin, mais déjà enregistré
        self.pmx("tick", "--run", run, code=0)
        self.assert_helper_stopped(run)
        ev = json.loads((self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()[-1])
        self.assertEqual((ev["kind"], ev["state"]), ("helper_end", "STOPPED"))

    def test_16_review_manager_killed_then_agent_stopped(self):
        run = self.to_review()
        mgr = self.manager("review", "run", "--run", run)
        self.wait_file(self.base / "agent.pid")
        os.kill(mgr.pid, signal.SIGKILL)
        mgr.wait()
        self.assertTrue(alive(self.apid()))
        self.pmx("tick", "--run", run, code=0)
        self.assert_helper_stopped(run)
        self.assertTrue(list(self.tmp.glob("wt/**/_review-*")) or (self.root / "ai_memory" / "runs" / run / "reviews").exists())

    def test_17_critical_stop_during_debate(self):
        run = self.to_debate()
        mgr = self.manager("debate", "next", "--run", run)
        self.wait_file(self.base / "agent.pid")
        p = self.pmx("abort", "--run", run, code=3)
        self.assertIn("arrêt vérifié", p.stdout)
        self.assert_helper_stopped(run)
        self.assertNotEqual(mgr.wait(timeout=30), 0)
        self.assertEqual(self.state(run)["stop"]["state"], "STOPPED")

    def test_18_critical_stop_during_review_starts_no_other_reviewer(self):
        run = self.to_review()
        mgr = self.manager("review", "run", "--run", run)
        self.wait_file(self.base / "agent.pid")
        p = self.pmx("abort", "--run", run, code=3)
        self.assertIn("arrêt vérifié", p.stdout)
        self.assert_helper_stopped(run)
        self.assertEqual(mgr.wait(timeout=30), 3)
        self.assertEqual(len((self.base / "launches.log").read_text().splitlines()), 1)

    def test_19_normal_end_stops_surviving_descendant_before_commit(self):
        self.config({"team-a": test_pmx.team("ok"), "team-b": {**self.stub("leave"), "reviewer": test_pmx.team("ok")["reviewer"]}})
        run, wis = self.to_approved([self.task("b", "team-b", ["src/b.js"])])
        self.runs.append(run)
        self.pmx("dispatch", "--run", run, code=0)
        self.wait_file(self.base / "left.pid")
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        t0 = time.time()
        self.assertFalse(alive(self.apid("left")))
        self.assertEqual(self.writes_after("left", t0), 0)
        a = self.state(run)["tasks"]["b"]["attempts"][0]
        self.assertEqual(a["settled"], "descendants arrêtés")
        self.assertFalse(pathlib.Path("/sys/fs/cgroup" + a["cgroup"]).exists())
        ev = json.loads((self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()[-1])
        self.assertEqual((ev["kind"], ev["state"], ev["attempts"][0]["before"], ev["attempts"][0]["populated_after"]), ("attempt_end", "STOPPED", True, False))
        self.assertEqual(self.status_of(next(iter(wis))), "READY_FOR_VERIFICATION")
        self.assertNotIn("stop", self.state(run))

    def test_20_normal_end_without_proof_is_unresolved_and_not_committed(self):
        self.config({"team-a": test_pmx.team("ok"), "team-b": {**self.stub("leave"), "reviewer": test_pmx.team("ok")["reviewer"]}})
        run, wis = self.to_approved([self.task("b", "team-b", ["src/b.js"])])
        self.runs.append(run)
        self.pmx("dispatch", "--run", run, code=0)
        self.wait_file(self.base / "left.pid")
        res = None
        for _ in range(200):
            res = next((self.root / "ai_memory" / "runs" / run / "tasks" / "b").glob("result-a*.json"), None)
            if res:
                break
            time.sleep(0.05)
        self.assertTrue(res)
        m = load_pmx()
        m.cgroup_kill = lambda cg: "cgroup.kill (PermissionError)"
        self.assertEqual(m.cmd_tick(m.Ctx(self.root), types.SimpleNamespace(run=run)), m.EXIT_CRITICAL)
        st = self.state(run)
        self.assertEqual(st["stop"]["state"], "UNRESOLVED")
        self.assertNotIn("commit", st["tasks"]["b"]["attempts"][0])
        self.assertEqual(self.status_of(next(iter(wis))), "BLOCKED")
        self.assertTrue(alive(self.apid("left")))
        self.assert_blocked(run)


class WithoutCgroup(Stop):
    def setUp(self):
        super().setUp()
        b = self.tmp / "bin"
        b.mkdir()
        for tool in ("git", "sh", "cat", "sleep"):
            os.symlink(shutil.which(tool), b / tool)
        self.env["PATH"] = str(b)

    def test_14_without_cgroup_stop_is_never_declared_success(self):
        run, _ = self.go("normal")
        a = self.state(run)["tasks"]["b"]["attempts"][0]
        self.assertNotIn("cgroup", a)
        p = self.wait_stop(run)
        self.assertIn("ARRÊT NON RÉSOLU", p.stdout)
        self.assertIn("aucun moyen de prouver", p.stdout)
        self.assertFalse(alive(self.apid()))  # groupe confirmé : arrêté, mais les descendants hors groupe restent invérifiables
        self.assert_blocked(run)

    def test_21_normal_end_without_cgroup_is_reported_unverified(self):
        self.config({"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
        run, _ = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.assertIn("non vérifiées", self.pmx("status", "--run", run, code=0).stdout)
        ev = json.loads((self.root / "ai_memory" / "runs" / run / "stop-evidence.jsonl").read_text().splitlines()[-1])
        self.assertEqual(ev["state"], "UNVERIFIED")

    def test_04b_reused_pid_detected_by_start_time(self):
        run, _ = self.go("ignore")
        self.violation_ready()
        st = self.state(run)
        st["tasks"]["b"]["attempts"][0]["pid"] = self.witness.pid  # autre heure de démarrage
        self.save(run, st)
        p = self.wait_stop(run)
        self.assertIn("identité du groupe non établie", p.stdout)
        self.assertIsNone(self.witness.poll())
        self.assertFalse(self.log.exists())

    def test_12_no_signal_to_foreign_group_with_dead_leader(self):
        run, _ = self.go("normal")
        self.violation_ready()
        pf = self.tmp / "member.pid"
        lead = subprocess.Popen(["sh", "-c", f"sleep 60 & echo $! > {pf}"], start_new_session=True, env=self.env)
        lead.wait()
        self.wait_file(pf)
        member = int(pf.read_text())
        self.addCleanup(lambda: alive(member) and os.kill(member, 9))
        st = self.state(run)
        st["tasks"]["b"]["attempts"][0]["pid"] = lead.pid  # PGID étranger dont le chef est mort : ce que SIGKILL inconditionnel tuait
        self.save(run, st)
        p = self.wait_stop(run)
        self.assertIn("ARRÊT NON RÉSOLU", p.stdout)
        self.assertTrue(alive(member))


for _n in [n for n in dir(test_pmx.Pilot) if n.startswith("test_")]:
    setattr(Stop, _n, None)


if __name__ == "__main__":
    unittest.main()
