#!/usr/bin/env python3
"""Aucun outil MCP externe pour les agents lancés par pmx, et revues croisées renforcées. CLI factices : aucun modèle, aucun réseau.

Usage : python3 -I tests/pilot/test_mcp.py -v
"""
import importlib.util, json, os, pathlib, shutil, subprocess, sys, textwrap, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pmx  # noqa: E402

PY = sys.executable
FAKE_SECRET = "PMXFAKE-mcp-secret-value"
STUB = textwrap.dedent(f"""\
    #!{PY} -I
    import json, os, pathlib, subprocess, sys, tempfile
    here = pathlib.Path(__file__).resolve().parent
    cli, a = pathlib.Path(__file__).name, sys.argv[1:]
    state = json.loads((here / "state.json").read_text())
    if cli == "codex" and a[-3:] == ["mcp", "list", "--json"]:
        if state.get("list_fails"):
            sys.exit(1)
        off = {{x.split(".")[1] for x in a if x.endswith(".enabled=false")}}
        names = state["names"] + (state.get("appears") or []) * bool(off)
        print(state["raw"] if state.get("raw") else json.dumps([{{"name": n, "enabled": n not in off or bool(state.get("ignore_disable"))}} for n in names]))
        sys.exit(0)
    with (here / "calls.jsonl").open("a") as f:
        f.write(json.dumps({{"cli": cli, "argv": [x if len(x) < 300 else "<prompt>" for x in a], "env_names": sorted(os.environ), "connectors": os.environ.get("ENABLE_CLAUDEAI_MCP_SERVERS"),
                             "cgroup": open("/proc/self/cgroup").read().strip()}}) + "\\n")
    prompt = a[a.index("-p") + 1] if cli == "claude" else a[-1]
    out = pathlib.Path(a[a.index("-o") + 1]) if cli == "codex" else pathlib.Path(tempfile.mktemp())
    pf = pathlib.Path(tempfile.mktemp()); pf.write_text(prompt)
    fake = {str(HERE / "fake_agent.py")!r}
    if "Tu es reviewer" in prompt:
        args = ["review", str(pf), str(out), "APPROVE"]
    elif "Tour " in prompt and " sur " in prompt and "tentative" not in prompt:
        args = ["debate", str(pf), str(out), "consensus"]
    else:
        args = ["team", str(pf), str(out), os.getcwd(), "ok"]
    rc = subprocess.run([sys.executable, "-I", fake, *args]).returncode
    if cli == "claude" and out.exists():
        sys.stdout.write(out.read_text())
    sys.exit(rc)
""")
POINTS = "\n".join(f"{i}. point — VÉRIFIÉ par lecture" for i in range(1, 11))


def load_pmx():
    spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Mcp(test_pmx.Pilot):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for cli in ("claude", "codex"):
            (self.bin / cli).write_text(STUB)
            (self.bin / cli).chmod(0o755)
        self.state(names=["chrome-devtools", "docs_1"])
        self.env["PATH"] = f"{self.bin}{os.pathsep}{self.env['PATH']}"
        self.env["PMXFAKE_API_TOKEN"] = FAKE_SECRET

    def state(self, **k):
        (self.bin / "state.json").write_text(json.dumps(k))

    def calls(self):
        f = self.bin / "calls.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []

    def cfg(self):
        self.config({"team-a": {"adapter": "claude-cli"}, "team-b": {"adapter": "codex-cli"}})
        c = self.root / ".claude" / "project-manager.config.json"
        d = json.loads(c.read_text())
        d["orchestration"]["debate"]["agents"] = {"claude": {"adapter": "claude-cli"}, "codex": {"adapter": "codex-cli"}}
        c.write_text(json.dumps(d))

    def assert_no_mcp(self, call):
        a = call["argv"]
        if call["cli"] == "claude":
            for x in ("--strict-mcp-config", "--disallowedTools=mcp__*"):
                self.assertIn(x, a)
            self.assertEqual(a[a.index("--mcp-config") + 1], '{"mcpServers":{}}')
            self.assertEqual(call["connectors"], "false")
        else:
            for n in ("chrome-devtools", "docs_1"):
                self.assertIn(f"mcp_servers.{n}.enabled=false", a)
            for f in ("apps", "plugins", "remote_plugin", "tool_suggest", "skill_mcp_dependency_install", "hooks"):
                self.assertEqual(a[a.index("--disable", 0):].count(f) >= 1, True, f)
            self.assertIn('web_search="disabled"', a)

    def full_cycle(self):
        self.cfg()
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("verify", "--run", run, code=0)
        self.pmx("review", "run", "--run", run, code=0)
        return run

    def test_01_every_agent_role_has_no_external_mcp_and_keeps_native_tools_and_cgroup(self):
        run = self.full_cycle()
        calls = self.calls()
        self.assertGreaterEqual(len(calls), 6)  # débat (au moins 2 tours), 2 équipes, 2 revues
        for c in calls:
            self.assert_no_mcp(c)
            self.assertIn("pmx-team-", c["cgroup"])  # scope conservé pour tous les rôles
            if c["cli"] == "claude":
                self.assertIn(c["argv"][c["argv"].index("--tools") + 1], ("Read,Grep,Glob", "Read,Grep,Glob,Edit,Write,Bash"))
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertEqual({h["kind"] for h in st["helpers"]}, {"debate", "review"})

    def test_02_no_secret_reaches_agents_logs_or_state(self):
        self.full_cycle()
        for c in self.calls():
            self.assertNotIn("PMXFAKE_API_TOKEN", c["env_names"])
        for f in (self.root / "ai_memory").rglob("*"):
            if f.is_file():
                self.assertNotIn(FAKE_SECRET, f.read_text(errors="replace"), f)

    def test_03_codex_refused_when_servers_cannot_be_listed_or_disabled(self):
        for bad in ({"names": [], "list_fails": True}, {"names": [], "raw": "pas du json"}, {"names": ["a.b"]}, {"names": ["a"], "ignore_disable": True}, {"names": ["a"], "appears": ["nouveau"]}):
            self.state(**bad)
            self.cfg()
            run, _ = self.to_approved_codex()
            self.assertEqual([c for c in self.calls() if c["cli"] == "codex" and "exec" in c["argv"]], [], bad)
            self.tmp_reset()

    def to_approved_codex(self):
        """Débat par un agent factice : le refus doit porter sur le lancement de l'équipe Codex."""
        c = self.root / ".claude" / "project-manager.config.json"
        d = json.loads(c.read_text())
        d["orchestration"]["debate"]["agents"] = {"claude": test_pmx.debater("continue,consensus"), "codex": test_pmx.debater("consensus")}
        c.write_text(json.dumps(d))
        run, wis = self.to_approved([self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run)
        self.pmx("wait", "--run", run, "--interval", "0.3")
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        self.assertNotEqual(st["tasks"]["b"]["attempts"][-1].get("result"), "done")
        return run, wis

    def tmp_reset(self):
        self.tearDown()
        self.setUp()

    def test_04_native_confinement_and_generated_policy_unchanged(self):
        m = load_pmx()
        (self.root / ".claude" / "s.json").write_text(json.dumps({"permissions": {"defaultMode": "acceptEdits", "allow": ["Read"], "deny": ["Edit(.mcp.json)"]}}))
        self.cfg()
        ctx = m.Ctx(self.root)
        ctx.o.update(mode=m.HYBRID, confinement="native")
        wt = self.tmp / "wt"
        wt.mkdir()
        pf = self.tmp / "p.md"
        pf.write_text("x")
        argv, _ = m.agent_argv(ctx, {"adapter": "claude-cli", "settings": ".claude/s.json"}, pf, self.tmp / "o", wt, "write")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")  # ni hook ni règle `allow` venus du dépôt
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Edit,Write")
        gen = json.loads(pathlib.Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertTrue(gen["sandbox"]["enabled"] and gen["sandbox"]["failIfUnavailable"])
        self.assertFalse(gen["sandbox"]["allowUnsandboxedCommands"])
        self.assertEqual(gen["sandbox"]["network"]["allowedDomains"], [])
        self.assertIn("Bash", gen["permissions"]["deny"])
        old = os.environ["PATH"]
        os.environ["PATH"] = f"{self.bin}{os.pathsep}{old}"
        try:
            cx, _ = m.agent_argv(ctx, {"adapter": "codex-cli"}, pf, self.tmp / "o", wt, "read")
        finally:
            os.environ["PATH"] = old
        self.assertIn('default_permissions="pmx-ro"', cx)
        self.assertIn("permissions.pmx-ro.network.enabled=false", cx)
        self.assertIn("mcp_servers.chrome-devtools.enabled=false", cx)

    def test_05_setting_sources_only_when_confined_default_mode_keeps_user_settings(self):
        m = load_pmx()
        self.cfg()
        ctx = m.Ctx(self.root)
        pf = self.tmp / "p.md"
        pf.write_text("x")
        argv, _ = m.agent_argv(ctx, {"adapter": "claude-cli"}, pf, self.tmp / "o", self.tmp, "write")
        self.assertNotIn("--setting-sources", argv)
        self.assertIn("--strict-mcp-config", argv)

    def test_06_connector_variable_applies_to_children_only(self):
        m = load_pmx()
        self.assertEqual(m.agent_env()["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertNotEqual(os.environ.get("ENABLE_CLAUDEAI_MCP_SERVERS"), "false")  # le processus principal n'est pas touché

    def test_07_user_connections_never_written(self):
        self.full_cycle()
        home = pathlib.Path(self.env["HOME"])
        self.assertEqual(sorted(p.name for p in home.iterdir()), [])  # ni ~/.claude, ni ~/.codex, ni ~/.claude.json

    def test_08_project_codex_config_is_sensitive(self):
        m = load_pmx()
        for p in (".codex/config.toml", ".codex/hooks/a.sh", ".mcp.json"):
            self.assertEqual(m.classify(p), "guardrail", p)
        self.cfg()
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([{**self.task("a", "team-a", ["src/a.js"]), "files": [".codex/config.toml"]}])), code=1)
        self.assertIn("chemin sensible (guardrail)", p.stdout)

    def test_09_review_prompt_requires_all_points_and_honesty(self):
        m = load_pmx()
        self.assertEqual(len(m.REVIEW_POINTS), 10)
        text = m.REVIEW_PROMPT.format(root="r", checkout="c", test="t", wi="w", title="ti", team="te", decision="d", acceptance="a", files="f", commit="co", diff="di",
                                      points="\n".join(f"{i}. {x}" for i, x in enumerate(m.REVIEW_POINTS, 1)))
        for x in m.REVIEW_POINTS:
            self.assertIn(x, text)
        for x in ("NON VÉRIFIÉ", "une lecture n'est pas une exécution", "CHANGES_REQUESTED seulement s'il existe un Blocker ou un Major", "`VERDICT: APPROVE`"):
            self.assertIn(x, text)

    def test_10_review_coverage_is_reported_and_never_changes_the_verdict(self):
        m = load_pmx()
        self.assertEqual(m.review_uncovered(POINTS), [])
        self.assertEqual(m.review_uncovered("1. a — NON VÉRIFIÉ : pas de shell\n" + "\n".join(POINTS.splitlines()[1:])), [])
        self.assertEqual(len(m.review_uncovered("Tout va bien.\nVERDICT: APPROVE")), 10)
        self.assertEqual(m.review_uncovered(POINTS.replace("6. point — VÉRIFIÉ par lecture\n", "")), ["Problèmes de sécurité"])
        run = self.full_cycle()
        st = json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())
        for t in st["tasks"].values():
            self.assertEqual(t["review"]["verdict"], "APPROVE")
            self.assertEqual(len(t["review"]["uncovered"]), 10)  # le relecteur factice n'en rend aucun : signalé, verdict inchangé


for _n in [n for n in dir(test_pmx.Pilot) if n.startswith("test_")]:
    setattr(Mcp, _n, None)


if __name__ == "__main__":
    unittest.main()
