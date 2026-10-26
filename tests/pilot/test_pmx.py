#!/usr/bin/env python3
"""Tests du pilote pmx — dépôts jetables, HOME jetable, agents factices (aucune CLI réelle, aucun réseau).
Usage : python3 -I tests/pilot/test_pmx.py -v
"""
import json, os, pathlib, re, shutil, signal, subprocess, sys, tempfile, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
PMX = HERE.parents[1] / "skills" / "project-manager" / "scripts" / "pmx.py"
FAKE = HERE / "fake_agent.py"
PY = sys.executable


def team(behavior, review="APPROVE"):
    return {"adapter": "cmd", "label": f"fake-{behavior}", "argv": [PY, "-I", str(FAKE), "team", "{prompt_file}", "{out_file}", "{cwd}", behavior],
            "reviewer": {"adapter": "cmd", "argv": [PY, "-I", str(FAKE), "review", "{prompt_file}", "{out_file}", review]}}


def debater(script):
    return {"adapter": "cmd", "argv": [PY, "-I", str(FAKE), "debate", "{prompt_file}", "{out_file}", script]}


class Pilot(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="pmx-test-"))
        self.env = {**os.environ, "HOME": str(self.tmp / "home"), "GIT_CONFIG_GLOBAL": str(self.tmp / "gitconfig")}
        (self.tmp / "home").mkdir()
        (self.tmp / "gitconfig").write_text("[user]\n\tname = t\n\temail = t@invalid\n[init]\n\tdefaultBranch = main\n")
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        (self.root / "README.md").write_text("demo\n")
        (self.root / ".claude").mkdir()
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *a):
        return subprocess.run(["git", "-C", str(self.root), *a], capture_output=True, text=True, env=self.env, check=True).stdout.strip()

    def config(self, teams, debate=("continue,consensus", "consensus"), **extra):
        orch = {"enabled": True, "max_parallel": 2, "max_attempts": 3, "team_timeout_s": 60,
                "debate": {"max_rounds": 3, "order": ["claude", "codex"], "agents": {"claude": debater(debate[0]), "codex": debater(debate[1])}},
                "teams": teams, "worktree_root": "../wt", "verify_commands": []}
        orch.update(extra)
        cfg = {"schema": "pm-v3/1", "work_items": {"backend": "ledger"}, "multi_team": {"enabled": True}, "orchestration": orch}
        (self.root / ".claude" / "project-manager.config.json").write_text(json.dumps(cfg))
        (self.root / ".claude" / "pmx.integration-policy.json").write_text(json.dumps(
            {"mode": "local-only", "target_branch": "pilot/integration", "path_allowlist": ["src/*", "test/*"], "require_review_verdict": ["APPROVE"]}))
        self.git("add", "-A")
        self.git("commit", "-qm", "config")

    def pmx(self, *a, code=None):
        p = subprocess.run([PY, "-I", str(PMX), "--root", str(self.root), *a], capture_output=True, text=True, env=self.env, timeout=120)
        if code is not None:
            self.assertEqual(p.returncode, code, f"pmx {a} → {p.returncode}\n{p.stdout}\n{p.stderr}")
        return p

    def plan(self, tasks):
        f = self.tmp / "plan.json"
        f.write_text(json.dumps({"tasks": tasks}))
        return f

    def task(self, key, team_, files, deps=()):
        return {"key": key, "title": f"Task {key}", "team": team_, "files": files, "depends_on": list(deps),
                "test_command": " && ".join(f"test -f {f}" for f in files), "acceptance": [f"{f} exists" for f in files]}

    def ledger(self):
        return (self.root / "ai_memory" / "WORK_ITEMS.md").read_text()

    def status_of(self, wi):
        m = re.search(rf"### {wi} — .*?\n(?:- .*\n)*?- status: (\S+)", self.ledger())
        return m.group(1)

    def to_approved(self, tasks):
        run = self.pmx("start", "--title", "Demo feature", "--request", "Ajoute deux modules", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        self.pmx("plan", "submit", "--run", run, "--file", str(self.plan(tasks)), code=2)
        out = self.pmx("plan", "approve", "--run", run, "--by", "tester", code=0).stdout
        wis = dict(re.findall(r"(WI-\S+)\s+(\S+)\s+→", out))
        return run, wis  # {WI: clé de tâche}

    # ------------------------------------------------------------------ tests

    def test_01_single_registry_and_ids(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.assertRegex(run, r"^WI-\d{8}-MAIN-001$")
        self.assertEqual(sorted(wis), [run[:-3] + "002", run[:-3] + "003"])
        lock = (self.root / "ai_memory" / "WI_COUNTER.lock").read_text().splitlines()
        self.assertEqual(lock, [f"MAIN={run[:-3]}003"])
        self.assertEqual(self.ledger().count("### WI-"), 3)
        self.assertIn(f"- parent: {run}", self.ledger())
        for bad in ("PENDING_GITLAB.md", "tasks.json", "registry.json"):
            self.assertFalse(list(self.root.rglob(bad)), bad)
        out = subprocess.run([PY, "-I", str(PMX.parent / "pm_config.py"), "validate", "--root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertNotIn("clé inconnue : orchestration", out.stdout)

    def test_02_debate_consensus_and_doc(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")})
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(st["debate"]["status"], "consensus")
        self.assertEqual(len(st["debate"]["turns"]), 3)  # claude ouvre, codex accepte, claude confirme
        doc = (self.root / st["debate"]["doc"]).read_text()
        for sec in ("Positions (Claude / Codex)", "Points d'accord", "Désaccords non résolus", "Questions pour l'utilisateur", "Décision proposée"):
            self.assertIn(sec, doc)

    def test_03_debate_bounded_three_rounds_needs_human(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")}, debate=("continue", "continue"))
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=2)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(len(st["debate"]["turns"]), 6)
        self.assertEqual(st["debate"]["status"], "no_consensus")
        self.pmx("decide", "--run", run, "--by", "consensus", code=2)
        self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/a.js"])])), code=2)
        self.pmx("decide", "--run", run, "--by", "human:tester", "--text", "option B", code=0)
        self.assertIn("human:tester", (self.root / "ai_doc" / f"DECISIONS__{run}.md").read_text())

    def test_04_plan_rejects_collisions_cycles_sensitive(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")})
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/x.js"]), self.task("b", "team-b", ["src/x.js"])])), code=1)
        self.assertIn("collision", p.stdout)
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/*.js"]), self.task("b", "team-b", ["src/b.js"])])), code=1)
        self.assertIn("collision", p.stdout)
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/a.js"], ["b"]), self.task("b", "team-b", ["src/b.js"], ["a"])])), code=1)
        self.assertIn("cycle", p.stdout)
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", [".env"])])), code=1)
        self.assertIn("sensible", p.stdout)
        # dépendants : même fichier autorisé (pas de parallélisme possible)
        self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/x.js"]), self.task("b", "team-b", ["src/x.js"], ["a"])])), code=2)
        self.pmx("dispatch", "--run", run, code=2)  # pas de « go » → rien ne part
        self.assertFalse((self.tmp / "wt").exists())

    def test_05_parallel_teams_verify_review_integrate(self):
        self.config({"team-a": team("slow"), "team-b": team("slow")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["test/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        ev = self.pmx("evidence", "--run", run, code=0).stdout
        self.assertIn("PARALLÈLE", ev)
        par = json.loads((self.root / "ai_memory" / "runs" / run / "parallelism.json").read_text())
        self.assertGreater(par["overlaps"][0]["seconds"], 1.0)
        self.assertNotEqual(par["tasks"][0]["pid"], par["tasks"][1]["pid"])
        for wi in wis:
            self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        main_before = self.git("rev-parse", "main")
        self.pmx("integrate", "--run", run, code=2)  # sans accord humain : refus
        self.pmx("integrate", "--run", run, "--dry-run", code=0)
        self.assertNotIn("pilot/integration", self.git("branch", "--list"))
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=0)
        self.assertEqual(self.git("rev-parse", "main"), main_before)  # main jamais touchée
        files = self.git("ls-tree", "-r", "--name-only", "pilot/integration").split()
        self.assertIn("src/a.js", files)
        self.assertIn("test/b.js", files)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "DONE")
        self.assertEqual(self.status_of(run), "READY_FOR_REVIEW")
        self.assertEqual(self.git("remote"), "")

    def test_06_scope_violation_stops_both_teams(self):
        self.config({"team-a": team("outside"), "team-b": team("crash")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        pid_b = st["tasks"]["b"]["attempts"][0]["pid"]
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("hors périmètre", p.stdout + p.stderr)
        time.sleep(1.5)
        self.assertFalse(pathlib.Path(f"/proc/{pid_b}").exists() and "Z" not in pathlib.Path(f"/proc/{pid_b}/stat").read_text().split(") ")[1][:1])
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assertIn("critical_abort", (self.root / "ai_memory" / "runs" / run / "events.jsonl").read_text())

    def test_07_sensitive_path_is_critical(self):
        self.config({"team-a": team("sensitive"), "team-b": team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("sensible (secret)", p.stdout + p.stderr)

    def test_08_retries_then_escalate(self):
        self.config({"team-a": team("fail"), "team-b": team("ok")}, max_attempts=2)
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 2)
        wi = next(iter(wis))
        self.assertEqual(self.status_of(wi), "ESCALATED")
        self.assertIn("- attempt_count: 2", self.ledger())

    def test_09_resume_after_interruption(self):
        self.config({"team-a": team("crash"), "team-b": team("ok")}, auto_retry=False)
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        pid = st["tasks"]["a"]["attempts"][0]["pid"]
        time.sleep(0.5)
        os.killpg(pid, signal.SIGKILL)  # « coupure » : l'équipe meurt sans résultat
        time.sleep(0.5)
        out = self.pmx("resume", "--run", run, code=0).stdout
        self.assertIn("BLOCKED", out)
        self.assertIn("interrompu", self.ledger())

    def test_10_drop_adapter_and_report(self):
        self.config({"team-a": {"adapter": "drop", "label": "claude-subagent"}, "team-b": team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        p = self.pmx("dispatch", "--run", run, code=10)
        brief = re.search(r"brief : (\S+)", p.stdout).group(1)
        self.assertIn("Définition du rôle `developer`", pathlib.Path(brief).read_text())
        wt = self.tmp / "wt" / "a-a1"
        (wt / "src").mkdir()
        (wt / "src" / "a.js").write_text("x\n")
        rep = self.tmp / "r.md"
        rep.write_text("Status: DONE\n")
        self.pmx("report", "--run", run, "--task", "a", "--status", "done", "--file", str(rep), code=0)
        self.assertEqual(self.status_of(next(iter(wis))), "READY_FOR_VERIFICATION")

    def test_11_dependency_waits_for_integration(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("c", "team-b", ["src/c.js"], ["a"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(st["tasks"]["c"]["attempts"], [])  # a pas encore intégrée → c ne part pas
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        # intégration partielle refusée tant que c n'est pas prête : la politique exige toutes les tâches
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=1)

    def test_12_lead_guard_refuses_linked_worktree(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")})
        wt = self.tmp / "linked"
        self.git("worktree", "add", "-q", "-b", "x", str(wt))
        p = subprocess.run([PY, "-I", str(PMX), "--root", str(wt), "status", "--run", "X"], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 64)
        self.assertIn("session lead", p.stderr)

    def test_13_protected_integration_branch_refused(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")}, integration_branch="main")
        pol = self.root / ".claude" / "pmx.integration-policy.json"
        pol.write_text(json.dumps({"mode": "local-only", "target_branch": "main", "path_allowlist": ["src/*"]}))
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        p = self.pmx("integrate", "--run", run, "--approved-by", "tester", code=1)
        self.assertIn("✘ cible non protégée (main)", p.stdout)


if __name__ == "__main__":
    unittest.main()
