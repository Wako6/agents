#!/usr/bin/env python3
"""Tests du pilote pmx — dépôts jetables, HOME jetable, agents factices (aucune CLI réelle, aucun réseau).
Usage : python3 -I tests/pilot/test_pmx.py -v
"""
import json, os, pathlib, pty, re, select, shutil, signal, subprocess, sys, tempfile, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
PMX = HERE.parents[1] / "skills" / "project-manager" / "scripts" / "pmx.py"
FAKE = HERE / "fake_agent.py"
PY = sys.executable
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")
FILES = ("src/a.js", "src/b.js", "src/c.js", "src/x.js", "test/b.js")  # commandes de test approuvées par défaut : `test -f <fichier>`


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
                "teams": teams, "worktree_root": "../wt", "verify_commands": [], "allowed_test_commands": [f"test -f {f}" for f in FILES]}
        orch.update(extra)
        cfg = {"schema": "pm-v3/1", "work_items": {"backend": "ledger"}, "multi_team": {"enabled": True}, "orchestration": orch}
        (self.root / ".claude" / "project-manager.config.json").write_text(json.dumps(cfg))
        (self.root / ".claude" / "pmx.integration-policy.json").write_text(json.dumps(
            {"mode": "local-only", "target_branch": "pilot/integration", "path_allowlist": ["src/*", "test/*"], "require_review_verdict": ["APPROVE"]}))
        self.git("add", "-A")
        self.git("commit", "-qm", "config")

    def pmx(self, *a, code=None):
        # nouvelle session : aucun terminal de contrôle, comme l'outil Bash d'un agent
        p = subprocess.run([PY, "-I", str(PMX), "--root", str(self.root), *a], capture_output=True, text=True, env=self.env, timeout=120, start_new_session=True)
        if code is not None:
            self.assertEqual(p.returncode, code, f"pmx {a} → {p.returncode}\n{p.stdout}\n{p.stderr}")
        return p

    def pmx_tty(self, *a, answer=None, code=None, agent_env=False):
        """pmx dans un pseudo-terminal (humain à son clavier) ; `answer` None = recopie la phrase demandée."""
        env = {k: v for k, v in self.env.items() if k not in AGENT_ENV}
        if agent_env:
            env["CLAUDECODE"] = "1"
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(PY, [PY, "-I", str(PMX), "--root", str(self.root), *a], env)
        out, sent, deadline = b"", False, time.time() + 120
        while time.time() < deadline:
            if select.select([fd], [], [], 0.5)[0]:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            m = re.search(rb"tapez exactement : (integrer [0-9a-f]+)", out)
            if m and not sent:
                os.write(fd, (answer if answer is not None else m.group(1).decode()).encode() + b"\n")
                sent = True
        os.close(fd)
        rc = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
        text = out.decode("utf-8", "replace")
        if code is not None:
            self.assertEqual(rc, code, f"pmx {a} → {rc}\n{text}")
        return rc, text

    def plan(self, tasks):
        f = self.tmp / "plan.json"
        f.write_text(json.dumps({"tasks": tasks}))
        return f

    def task(self, key, team_, files, deps=()):
        return {"key": key, "title": f"Task {key}", "team": team_, "files": files, "depends_on": list(deps),
                "test_command": "test -f " + " -a -f ".join(files), "acceptance": [f"{f} exists" for f in files]}

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
        glob = {**self.task("a", "team-a", ["src/*.js"]), "test_command": "test -f src/a.js"}
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([glob, self.task("b", "team-b", ["src/b.js"])])), code=1)
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
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
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
        self.pmx("reopen", "--run", run, "--task", "a", "--by", "consensus", "--reason", "x", code=64)  # humain seulement
        self.pmx("reopen", "--run", run, "--task", "a", "--by", "human:tester", "--reason", "brief fixed", code=0)
        self.assertEqual(self.status_of(wi), "OPEN")
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.assertEqual(self.status_of(wi), "ESCALATED")  # nouveau budget de 2, épuisé à nouveau
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 4)

    def test_14_process_team_brief_has_no_out_of_sandbox_report_path(self):
        self.config({"team-a": team("ok"), "team-b": {"adapter": "drop"}})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=10)
        ba = (self.root / "ai_memory" / "runs" / run / "tasks" / "a" / "brief-a1.md").read_text()
        bb = (self.root / "ai_memory" / "runs" / run / "tasks" / "b" / "brief-a1.md").read_text()
        self.assertIn("DERNIER MESSAGE est ton rapport", ba)
        self.assertNotIn("report-a1.md", ba)
        self.assertIn("report-a1.md", bb)

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
        self.assertIn("- blocker: interrupted", self.ledger())

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
        # intégration par vague : a seule, puis c part depuis la branche d'intégration
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        wi_c = next(w for w, k in wis.items() if k == "c")
        self.assertEqual(self.status_of(run), "IN_PROGRESS")  # parent pas fini tant que c n'est pas intégrée
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(st["tasks"]["c"]["attempts"][0]["base"], st["integrations"][0]["commit"])
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        self.assertEqual(self.status_of(wi_c), "DONE")
        self.assertEqual(self.status_of(run), "READY_FOR_REVIEW")
        self.assertIn("src/a.js", self.git("ls-tree", "-r", "--name-only", "pilot/integration"))

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

    # ------------------------------------------------------------------ relances : cause répétée (non-régression)

    def run_failing(self, behavior, max_attempts=3, files=("src/a.js",)):
        self.config({"team-a": team(behavior), "team-b": team("ok")}, max_attempts=max_attempts)
        run, wis = self.to_approved([self.task("a", "team-a", list(files))])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        return run, next(iter(wis)), st

    def test_15_same_cause_stops_after_second_attempt(self):
        run, wi, st = self.run_failing("fail", max_attempts=3)
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 2)  # et non 3 : la cause s'est répétée
        self.assertEqual(self.status_of(wi), "ESCALATED")
        self.assertIn("same cause repeated (attempts 1 and 2", self.ledger())
        esc = (self.root / "ai_doc" / f"ESCALATION__{wi}.md").read_text()
        self.assertIn("| 1 | exit-1 |", esc)
        self.assertIn("| 2 | exit-1 |", esc)
        self.assertIn("pmx reopen --by human", esc)
        ev = (self.root / "ai_memory" / "runs" / run / "events.jsonl").read_text()
        self.assertIn('"decision": "ESCALATED"', ev)
        self.assertIn('"repeat_of": 1', ev)

    def test_16_noise_is_normalized(self):
        run, wi, st = self.run_failing("fail-noisy")
        f = st["tasks"]["a"]["failures"]
        self.assertNotEqual(f[0]["evidence"]["report_excerpt"], f[1]["evidence"]["report_excerpt"])  # textes bruts différents
        self.assertEqual(f[0]["signature"], f[1]["signature"])  # même signature après normalisation
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 2)
        self.assertEqual(self.status_of(wi), "ESCALATED")

    def test_17_distinct_causes_use_full_budget_of_three(self):
        run, wi, st = self.run_failing("fail-distinct")
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 3)  # plafond conservé
        self.assertEqual(len({f["signature"] for f in st["tasks"]["a"]["failures"]}), 3)
        self.assertEqual(self.status_of(wi), "ESCALATED")
        self.assertIn("3 attempts failed (cap 3)", self.ledger())

    def test_18_replay_of_real_demo_reports_stops_at_two(self):
        run, wi, st = self.run_failing("blocked-demo")
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), 2)  # la démo réelle en avait consommé 3
        f = st["tasks"]["a"]["failures"]
        self.assertNotEqual(f[0]["signature"], f[1]["signature"])  # rédaction différente…
        self.assertIn("match 0.83", self.ledger())  # …même cause, preuve du rapprochement enregistrée
        self.assertEqual(f[1]["evidence"]["changed_files"], ["src/a.js"])

    def test_19_escalated_is_never_relaunched_without_human(self):
        run, wi, st = self.run_failing("fail")
        n = len(st["tasks"]["a"]["attempts"])
        for cmd in (("dispatch",), ("tick",), ("wait", "--interval", "0.2"), ("resume",)):
            self.pmx(*cmd, "--run", run)
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual(len(st["tasks"]["a"]["attempts"]), n)
        self.assertEqual(self.status_of(wi), "ESCALATED")
        self.pmx("reopen", "--run", run, "--task", "a", "--by", "lead", "--reason", "x", code=64)

    def test_20_repeated_verifier_failure_escalates(self):
        self.config({"team-a": team("ok"), "team-b": team("ok")}, allowed_test_commands=["grep -q never-there src/a.js"])
        t = self.task("a", "team-a", ["src/a.js"])
        t["test_command"] = "grep -q never-there src/a.js"
        run, wis = self.to_approved([t])
        wi = next(iter(wis))
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("verify", "--run", run, code=1)
        self.assertEqual(self.status_of(wi), "OPEN")  # premier échec : nouvelle cause, relance permise
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("verify", "--run", run, code=1)
        self.assertEqual(self.status_of(wi), "ESCALATED")
        self.assertIn("verifier-fail: grep -q never-there src/a.js → exit 1", self.ledger())

    def test_21_normalization_keeps_significant_differences(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        def rec(kind, text, exit=1, files=("src/a.js",)):
            d = m.normalize_cause(text)
            return {"kind": kind, "detail": d, "signature": f"{kind}: {d}", "evidence": {"exit": exit, "changed_files": list(files)}}
        same = m.same_cause
        self.assertTrue(same(rec("exit-1", "ERR at 2026-10-26T10:00:01Z sha deadbeef01 (3ms)"), rec("exit-1", "ERR at 2026-10-27T11:12:13Z sha 0123abcd99 (9ms)"))[0])
        self.assertFalse(same(rec("exit-1", "test case_1 failed"), rec("exit-1", "test case_2 failed"))[0])  # test différent
        self.assertFalse(same(rec("exit-1", "boom"), rec("exit-2", "boom"))[0])  # code de sortie différent
        self.assertFalse(same(rec("reported-blocked", "cannot write report", 0), rec("reported-blocked", "cannot write report", 0, files=("src/b.js",)))[0])
        self.assertFalse(same(rec("exit-1", "src/a.js: syntax error"), rec("exit-1", "src/b.js: syntax error"))[0])  # fichier différent
        self.assertFalse(same(rec("verifier-fail", "node --test x → exit 1 :: not ok 3"), rec("verifier-fail", "node --test x → exit 1 :: not ok 4"))[0])
        self.assertFalse(same(rec("interrupted", ""), rec("timeout", ""))[0])
        self.assertTrue(same(rec("interrupted", ""), rec("interrupted", ""))[0])


    # ------------------------------------------------------------------ revue PR #1 : C1 intégrité, C2 commandes, C3 confirmation

    def ready_for(self, stage, **extra):
        """Run à une tâche (a, src/a.js) amené jusqu'à `stage` : verification | review."""
        self.config({"team-a": team("ok"), "team-b": team("ok")}, **extra)
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        if stage == "review":
            self.pmx("verify", "--run", run, code=0)
            self.pmx("review", "run", "--run", run, code=0)
        return run, next(iter(wis))

    def run_state(self, run):
        return json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())

    def pwned(self):
        return list(self.tmp.rglob("pwned*"))

    def test_22_plan_refuses_untrusted_and_shell_commands(self):
        # même une entrée approuvée par erreur par l'humain est refusée si elle enchaîne des commandes
        self.config({"team-a": team("ok"), "team-b": team("ok")}, allowed_test_commands=[*(f"test -f {f}" for f in FILES), "test -f src/a.js; touch pwned"])
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        for cmd, why in (("touch pwned", "non approuvée"), ("rm -rf ..", "non approuvée"), ("test -f src/a.js && touch pwned", "non approuvée"),
                         ("test -f $(touch pwned)", "non approuvée"), ("test -f `touch pwned`", "non approuvée"),
                         ("test -f src/a.js\ntouch pwned", "non approuvée"), ("test -f src/a.js; touch pwned", "métacaractère shell"), ("", "test_command")):
            t = self.task("a", "team-a", ["src/a.js"])
            t["test_command"] = cmd
            p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([t])), code=1)
            self.assertIn(why, p.stdout, cmd)
        self.assertEqual(self.run_state(run).get("plan"), None)  # rien d'enregistré
        self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([self.task("a", "team-a", ["src/a.js"])])), code=2)
        self.assertEqual(self.pwned(), [])

    def test_23_tampered_run_state_command_is_never_executed(self):
        run, wi = self.ready_for("verification")
        f = self.root / "ai_memory" / "runs" / run / "run.json"
        st = json.loads(f.read_text())
        st["tasks"]["a"]["test_command"] = "touch pwned"  # run.json réécrit après l'approbation du plan
        f.write_text(json.dumps(st))
        p = self.pmx("verify", "--run", run, code=2)
        self.assertIn("vérification REFUSÉE, rien n'a été exécuté", p.stdout)
        self.assertEqual(self.pwned(), [])
        self.assertEqual(list((self.tmp / "wt").glob("_verify-*")), [])
        self.assertEqual(self.status_of(wi), "READY_FOR_VERIFICATION")

    def test_24_trusted_commands_run_without_shell(self):
        run, wi = self.ready_for("verification", verify_commands=["printf %s *"])
        self.pmx("verify", "--run", run, code=0)
        res = self.run_state(run)["tasks"]["a"]["verify"]["results"]
        self.assertEqual(res[1]["output"], "*")  # pas d'expansion : aucun shell

    def test_25_verify_untracked_file_is_inconclusive_and_kept(self):
        run, wi = self.ready_for("verification", verify_commands=["touch stray.txt", "test -f never.js"])
        p = self.pmx("verify", "--run", run, code=2)
        self.assertIn("verifier INCONCLUSIVE", p.stdout)
        v = self.run_state(run)["tasks"]["a"]["verify"]
        self.assertEqual(v["verdict"], "INCONCLUSIVE")  # ni PASS, ni FAIL ordinaire
        vdir = next((self.tmp / "wt").glob("_verify-a-*"))
        self.assertTrue((vdir / "stray.txt").exists())  # checkout conservé tel quel
        self.assertIn("?? stray.txt", pathlib.Path(v["evidence"]).read_text())
        self.assertEqual(self.status_of(wi), "BLOCKED")
        self.assertIn("- blocker: verifier INCONCLUSIVE: checkout modifié", self.ledger())
        self.assertEqual(len(self.run_state(run)["tasks"]["a"]["attempts"]), 1)  # aucune relance automatique
        self.pmx("verify", "--run", run, "--task", "a", code=2)  # la preuve n'est pas écrasée
        self.assertTrue((vdir / "stray.txt").exists())
        self.pmx("reopen", "--run", run, "--task", "a", "--by", "human:tester", "--reason", "triage", code=0)

    def test_26_verify_head_and_ref_changes_are_inconclusive(self):
        run, wi = self.ready_for("verification", verify_commands=["git commit -q --allow-empty -m sneaky", "git branch sneaky"])
        p = self.pmx("verify", "--run", run, code=2)
        self.assertIn("HEAD du checkout déplacé", p.stdout)
        self.assertIn("références git modifiées pendant les tests : refs/heads/sneaky", p.stdout)
        self.assertEqual(self.status_of(wi), "BLOCKED")

    def test_27_verify_cleanup_failure_is_not_pass(self):
        run, wi = self.ready_for("verification", verify_commands=["git worktree lock ."])
        p = self.pmx("verify", "--run", run, code=2)
        self.assertIn("nettoyage du checkout impossible", p.stdout)
        self.assertEqual(self.run_state(run)["tasks"]["a"]["verify"]["verdict"], "INCONCLUSIVE")
        self.assertNotEqual(self.status_of(wi), "READY_FOR_REVIEW")

    def test_28_integration_needs_confirmation_on_human_terminal(self):
        run, wi = self.ready_for("review")
        refused = lambda: self.assertNotIn("pilot/integration", self.git("branch", "--list"))
        p = self.pmx("integrate", "--run", run, "--approved-by", "tester", code=2)  # outil d'agent : pas de terminal
        self.assertIn("✘ confirmation humaine possible au terminal", p.stdout)
        refused()
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", agent_env=True, code=2)
        self.assertIn("session d'agent détectée (CLAUDECODE)", out)
        refused()
        rc, out = self.pmx_tty("integrate", "--run", run, code=2)  # terminal mais aucun accord déclaré
        refused()
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", answer="oui", code=2)
        self.assertIn("confirmation absente ou incorrecte", out)
        refused()
        self.assertIn("integration_not_confirmed", (self.root / "ai_memory" / "runs" / run / "events.jsonl").read_text())
        self.assertEqual(list((self.tmp / "wt").glob("_integration-*")), [])
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        conf = self.run_state(run)["integration"]["confirmation"]
        self.assertEqual(conf["via"], "tty")
        self.assertTrue(conf["phrase"].startswith("integrer "))
        self.assertIn("not an authentication", (self.root / "ai_doc" / f"DECISIONS__{run}.md").read_text())
        self.assertEqual(self.status_of(wi), "DONE")
        self.assertEqual(self.git("remote"), "")

    def test_29_integration_integrity_failure_keeps_target_and_evidence(self):
        run, wi = self.ready_for("review")
        cfg = self.root / ".claude" / "project-manager.config.json"
        c = json.loads(cfg.read_text())
        c["orchestration"]["verify_commands"] = ["git branch sneaky", "touch stray.txt"]
        cfg.write_text(json.dumps(c))
        p = self.pmx("integrate", "--run", run, "--dry-run", code=2)
        self.assertIn("intégrité du checkout d'intégration NON vérifiée", p.stdout)
        self.assertNotIn("pilot/integration", self.git("branch", "--list"))
        iwt = next((self.tmp / "wt").glob("_integration-*"))
        self.assertTrue((iwt / "stray.txt").exists())
        self.assertTrue(list((self.root / "ai_memory" / "runs" / run / "integrity").glob("integration-*.txt")))
        self.assertEqual(self.status_of(wi), "READY_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()
