#!/usr/bin/env python3
"""Tests du profil `host-agents+docker-verification` : agents factices SUR L'HÔTE (adaptateur cmd), vérification en conteneur.
Aucune CLI réelle, aucun réseau. La partie qui vérifie en conteneur est ignorée sans Docker ou sans l'image locale.
Usage : python3 -I tests/pilot/test_hybrid.py -v
"""
import json, os, pathlib, shutil, subprocess, sys, time, unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_docker  # noqa: E402
import test_pmx  # noqa: E402

HYBRID = "host-agents+docker-verification"
SETTINGS_OK = {"permissions": {"defaultMode": "acceptEdits", "allow": ["Read"], "deny": ["Bash(docker:*)", "Bash(curl:*)"]}}


class Hybrid(test_docker.Docker):
    def hconfig(self, teams=None, policy_isolated=True, **orch):
        o = {"mode": HYBRID, "confinement": "native", "verify_runner": test_docker.VRUN, "allowed_test_commands": [f"test -f {f}" for f in test_pmx.FILES]}
        o.update(orch)
        self.config(teams or {"team-a": test_pmx.team("slow"), "team-b": test_pmx.team("slow")}, **o)
        pol = self.root / ".claude" / "pmx.integration-policy.json"
        pol.write_text(json.dumps({**json.loads(pol.read_text()), "require_isolated_verification": policy_isolated}))
        self.git("add", "-A")
        self.git("commit", "-qm", "hybrid config")

    def start_refused(self, why):
        p = self.pmx("start", "--title", "Demo", "--request", "q", code=64)  # refus dès la première commande
        self.assertIn(why, p.stderr)
        self.assertFalse((self.root / "ai_memory" / "runs").exists() and any((self.root / "ai_memory" / "runs").iterdir()))

    def test_h01_mode_requires_docker_verification(self):
        self.hconfig(verify_runner={"adapter": "host"})
        self.start_refused("verify_runner.adapter = docker obligatoire")

    def test_h02_mode_requires_isolation_policy(self):
        self.hconfig(policy_isolated=False)
        self.start_refused("require_isolated_verification=true obligatoire")

    def test_h03_mode_refuses_containerized_agents_and_gateway(self):
        self.hconfig({"team-a": test_docker.dteam("ok"), "team-b": test_pmx.team("ok")})
        self.start_refused("doit tourner sur l'hôte")
        self.hconfig(gateway={"image": "x"})
        self.start_refused("orchestration.gateway non utilisée")

    def test_h04_claude_cli_needs_explicit_settings_denying_docker(self):
        (self.root / ".claude" / "s.json").write_text(json.dumps({"permissions": {"defaultMode": "acceptEdits", "deny": ["Bash(curl:*)"]}}))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": test_pmx.team("ok")})
        self.start_refused("doivent refuser Bash(docker:*)")
        self.hconfig({"team-a": {"adapter": "claude-cli"}, "team-b": test_pmx.team("ok")})
        self.start_refused("sans réglages de permissions explicites")
        (self.root / ".claude" / "s.json").write_text(json.dumps(SETTINGS_OK))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": test_pmx.team("ok")})
        self.pmx("start", "--title", "Demo", "--request", "q", code=0)

    def test_h05_permission_bypass_refused_in_every_mode(self):
        bad_settings = self.root / ".claude" / "bypass.json"
        bad_settings.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions", "deny": ["Bash(docker:*)"]}}))
        cases = [({"adapter": "cmd", "argv": ["claude", "-p", "{prompt_file}", "--dangerously-skip-permissions"]}, "contournement"),
                 ({"adapter": "cmd", "argv": ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "{prompt_file}"]}, "contournement"),
                 ({"adapter": "cmd", "argv": ["codex", "exec", "--sandbox", "danger-full-access", "{prompt_file}"]}, "contournement"),
                 ({"adapter": "codex-cli", "model": "o3 --yolo"}, "contournement"),
                 ({"adapter": "claude-cli", "settings": ".claude/bypass.json"}, "defaultMode 'bypassPermissions' refusé")]
        for mode in (None, HYBRID):
            for team_cfg, why in cases:
                with self.subTest(mode=mode, cfg=team_cfg):
                    extra = {"mode": mode} if mode else {"mode": None, "verify_runner": {"adapter": "host"}}
                    self.hconfig({"team-a": team_cfg, "team-b": test_pmx.team("ok")}, **extra)
                    self.start_refused(why)

    def test_h06_no_silent_fallback_when_docker_is_missing(self):
        self.hconfig({"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        nodocker = self.tmp / "bin"
        nodocker.mkdir()
        for tool in ("git", "test"):
            os.symlink(shutil.which(tool), nodocker / tool)
        env = {**self.env, "PATH": str(nodocker)}
        p = subprocess.run([test_pmx.PY, "-I", str(test_pmx.PMX), "--root", str(self.root), "verify", "--run", run], capture_output=True, text=True,
                           env=env, start_new_session=True, timeout=120)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("conteneur non créé", p.stdout)
        v = self.run_state(run)["tasks"]["a"]["verify"]
        self.assertEqual((v["verdict"], v["runner"]), ("INCONCLUSIVE", "docker"))  # jamais exécuté sur l'hôte

    def test_h07_full_cycle_host_agents_docker_verification(self):
        self.hconfig()
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["test/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        self.pmx("wait", "--run", run, "--interval", "0.3", code=0)
        self.pmx("evidence", "--run", run, code=0)
        st = self.run_state(run)
        self.assertNotEqual(st["tasks"]["a"]["attempts"][0]["worktree"], st["tasks"]["b"]["attempts"][0]["worktree"])
        self.assertGreater(json.loads((self.root / "ai_memory" / "runs" / run / "parallelism.json").read_text())["overlaps"][0]["seconds"], 1.0)
        self.pmx("verify", "--run", run, code=0)
        st = self.run_state(run)
        for k in ("a", "b"):
            self.assertEqual(st["tasks"][k]["verify"]["runner"], "docker")
            self.assertTrue(list((self.root / "ai_memory" / "runs" / run / "verify" / k).glob("container-*.json")))
        self.pmx("review", "run", "--run", run, code=0)
        self.pmx("integrate", "--run", run, "--approved-by", "tester", code=2)  # outil d'agent : refus (C3)
        rc, out = self.pmx_tty("integrate", "--run", run, "--approved-by", "tester", code=0)
        self.assertIn("✔ politique : tests sur l'arbre fusionné en conteneur isolé", out)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "DONE")

    def test_h08_scope_violation_stops_host_teams(self):
        self.hconfig({"team-a": test_pmx.team("outside"), "team-b": test_pmx.team("crash")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("hors périmètre", p.stdout + p.stderr)
        for wi in wis:
            self.assertEqual(self.status_of(wi), "BLOCKED")

    def test_h10_redirected_git_pointer_is_critical_before_any_git(self):
        self.hconfig({"team-a": test_pmx.team("gitptr"), "team-b": test_pmx.team("ok")})
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        self.pmx("dispatch", "--run", run, code=0)
        p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
        self.assertIn("pointeur .git redirigé", p.stdout + p.stderr)
        self.assertIn("aucune commande git lancée", p.stdout + p.stderr)
        self.assertEqual(self.status_of(next(iter(wis))), "BLOCKED")

    # ------------------------------------------------------------------ confinement natif (préflight, sans CLI réelle)

    def stub_bin(self, codex_sandbox_behavior=None, drop=()):
        """PATH de test : outils réels sauf `drop`, et un faux `codex` dont la sous-commande sandbox se comporte comme demandé."""
        b = self.tmp / f"bin-{time.time_ns()}"
        b.mkdir()
        for tool in ("git", "test", "sh", "cat", "docker", "bwrap", "socat", "python3", "claude", "systemd-run", "env"):
            src = shutil.which(tool)
            if src and tool not in drop:
                os.symlink(src, b / tool)
        if codex_sandbox_behavior:
            script = {"open": 'shift; while [ "$1" != "--" ]; do shift; done; shift; exec "$@"',  # exécute SANS sandbox
                      "broken": 'echo "sandbox cassé" >&2; exit 1'}[codex_sandbox_behavior]
            (b / "codex").write_text(f'#!/bin/sh\nif [ "$1" = sandbox ]; then {script}; fi\nexit 0\n')
            (b / "codex").chmod(0o755)
        return {**self.env, "PATH": str(b)}

    def dispatch_with(self, env, teams):
        self.hconfig(teams)
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        p = subprocess.run([test_pmx.PY, "-I", str(test_pmx.PMX), "--root", str(self.root), "dispatch", "--run", run], capture_output=True, text=True,
                           env=env, start_new_session=True, timeout=120)
        return run, p

    def test_h11_hybrid_requires_native_confinement(self):
        self.hconfig(confinement=None)
        self.start_refused('confinement = "native" obligatoire')

    def test_h12_missing_sandbox_prerequisite_stops_before_any_launch(self):
        for tool in ("bwrap", "socat"):
            with self.subTest(tool=tool):
                run, p = self.dispatch_with(self.stub_bin(drop=(tool,)), {"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
                self.assertEqual(p.returncode, 64, p.stdout + p.stderr)
                self.assertIn(f"{tool} absent", p.stderr)
                self.assertEqual(self.run_state(run)["tasks"]["a"]["attempts"], [])  # aucun agent lancé

    def test_h13_open_or_broken_codex_sandbox_stops_dispatch(self):
        for behavior, why in (("open", "sandbox Codex NON fermé"), ("broken", "sandbox Codex inutilisable")):
            with self.subTest(behavior=behavior):
                run, p = self.dispatch_with(self.stub_bin(codex_sandbox_behavior=behavior), {"team-a": {"adapter": "codex-cli"}, "team-b": test_pmx.team("ok")})
                self.assertEqual(p.returncode, 64, p.stdout + p.stderr)
                self.assertIn(why, p.stderr)
                self.assertEqual(self.run_state(run)["tasks"]["a"]["attempts"], [])

    def test_h14_user_sandbox_block_is_refused(self):
        (self.root / ".claude" / "s.json").write_text(json.dumps({**SETTINGS_OK, "sandbox": {"enabled": False}}))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": test_pmx.team("ok")})
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        p = self.pmx("debate", "next", "--run", run, code=64)  # refus avant le premier agent (débat)
        self.assertIn("bloc `sandbox` interdit", p.stderr)

    @unittest.skipUnless(shutil.which("codex") and shutil.which("claude"), "CLI codex/claude absentes")
    def test_h15_generated_confinement_arguments(self):
        import importlib.util
        (self.root / ".claude" / "s.json").write_text(json.dumps(SETTINGS_OK))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": {"adapter": "codex-cli"}})
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        ctx = m.Ctx(self.root)
        wt = self.tmp / "wt" / "x"
        wt.mkdir(parents=True)
        pf = self.tmp / "brief.md"
        pf.write_text("brief")
        argv, _ = m.agent_argv(ctx, ctx.o["teams"]["team-b"], pf, self.tmp / "o.md", wt, "write")
        self.assertNotIn("--sandbox", argv)
        self.assertIn('default_permissions="pmx-ws"', argv)
        fsarg = next(x for x in argv if x.startswith("permissions.pmx-ws.filesystem="))
        for frag in ('":root"="deny"', '":minimal"="read"', '":tmpdir"="deny"', '":slash_tmp"="deny"'):
            self.assertIn(frag, fsarg)
        self.assertIn("permissions.pmx-ws.network.enabled=false", argv)
        ro, _ = m.agent_argv(ctx, ctx.o["teams"]["team-b"], pf, self.tmp / "o.md", wt, "read")
        self.assertIn('default_permissions="pmx-ro"', ro)
        argv, _ = m.agent_argv(ctx, ctx.o["teams"]["team-a"], pf, self.tmp / "o.md", wt, "write")
        gen = json.loads(pathlib.Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertTrue(gen["permissions"]["blockReadsOutsideWorkingDirectories"])
        sb = gen["sandbox"]
        self.assertEqual((sb["enabled"], sb["failIfUnavailable"], sb["allowUnsandboxedCommands"]), (True, True, False))
        self.assertEqual(sb["filesystem"]["allowRead"], [str(wt.resolve())])  # chemin ABSOLU du worktree
        self.assertEqual(sb["filesystem"]["allowWrite"], [str(wt.resolve())])
        for d in ("~/", "/mnt", "/run/WSL", "/var/run/docker.sock", "/tmp"):
            self.assertIn(d, sb["filesystem"]["denyRead"])
        self.assertEqual(sb["network"]["allowedDomains"], [])
        self.assertFalse(str(pathlib.Path(argv[argv.index("--settings") + 1])).startswith(str(wt)))  # réglages hors worktree
        ro, _ = m.agent_argv(ctx, ctx.o["teams"]["team-a"], pf, self.tmp / "o.md", wt, "read")
        self.assertEqual(json.loads(pathlib.Path(ro[ro.index("--settings") + 1]).read_text())["sandbox"]["filesystem"]["allowWrite"], [])
        os.environ["WSL_INTEROP"] = "/run/WSL/0_interop"
        self.assertNotIn("WSL_INTEROP", m.agent_env())

    # ------------------------------------------------------------------ artefacts du sandbox Claude : le garde-fou reste sans exception

    VIOLATIONS = (("viol-empty", ".claude/settings.json : chemin sensible"), ("viol-nonempty", ".claude/settings.json : chemin sensible"),
                  ("viol-readonly", ".claude/settings.json : chemin sensible"), ("viol-placeholders", ".claude/settings.json : chemin sensible"),
                  ("viol-symlink", "lien symbolique"), ("viol-modify", ".claude/project-manager.config.json : chemin sensible"),
                  ("viol-mcp", ".mcp.json : chemin sensible"), ("viol-fifo", "fichier spécial"), ("viol-livemount", ".claude/settings.json : chemin sensible"))

    def test_h16_sensitive_changes_always_stop_both_teams_and_keep_evidence(self):
        for behavior, why in self.VIOLATIONS:
            if behavior == "viol-livemount" and not shutil.which("bwrap"):
                continue
            with self.subTest(behavior=behavior):
                self.tmp_reset()
                self.hconfig({"team-a": test_pmx.team(behavior), "team-b": test_pmx.team("crash")})
                run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"]), self.task("b", "team-b", ["src/b.js"])])
                self.pmx("dispatch", "--run", run, code=0)
                pid_b = self.run_state(run)["tasks"]["b"]["attempts"][0]["pid"]
                p = self.pmx("wait", "--run", run, "--interval", "0.3", code=3)
                self.assertIn(why, p.stdout + p.stderr)
                time.sleep(1.5)
                self.assertFalse(pathlib.Path(f"/proc/{pid_b}").exists() and "Z" not in pathlib.Path(f"/proc/{pid_b}/stat").read_text().split(") ")[1][:1])
                for wi in wis:
                    self.assertEqual(self.status_of(wi), "BLOCKED")  # les deux équipes
                st = self.run_state(run)
                self.assertTrue(pathlib.Path(st["tasks"]["a"]["attempts"][0]["worktree"]).exists())  # preuves conservées
                self.assertIn("critical_abort", (self.root / "ai_memory" / "runs" / run / "events.jsonl").read_text())
                self.assertEqual(self.git("rev-parse", st["tasks"]["a"]["attempts"][0]["branch"]), self.git("rev-parse", "main"))  # aucun commit

    def test_h19_changed_paths_for_tracked_untracked_renamed_deleted(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        def fresh(*files):
            (self.root / "t").mkdir(exist_ok=True)
            for f in files:
                (self.root / f).parent.mkdir(parents=True, exist_ok=True)
                (self.root / f).write_text("a\n")
            self.git("add", "-A")
            self.git("commit", "-qm", "base")
        fresh("a/one.js", "a/two.js", ".claude/keep.json", "b/old.js")
        (self.root / "a" / "one.js").write_text("b\n")  # suivi modifié, en première ligne
        self.assertEqual(m.changed_paths(self.root, "HEAD"), ({"a/one.js"}, set()))
        self.git("checkout", "-q", "--", "a/one.js")
        (self.root / ".claude" / "keep.json").unlink()  # suivi supprimé, en première ligne : le point initial ne se perd pas
        self.assertEqual(m.changed_paths(self.root, "HEAD"), ({".claude/keep.json"}, {".claude/keep.json"}))
        self.assertEqual(m.classify(".claude/keep.json"), "guardrail")
        self.git("checkout", "-q", "--", ".claude/keep.json")
        (self.root / ".envnew").write_text("x\n")  # non suivi
        self.assertEqual(m.changed_paths(self.root, "HEAD"), ({".envnew"}, set()))
        (self.root / ".envnew").unlink()
        self.git("mv", "b/old.js", "b/new.js")  # renommé, indexé
        self.assertEqual(m.changed_paths(self.root, "HEAD"), ({"b/old.js", "b/new.js"}, {"b/old.js"}))
        self.git("mv", "b/new.js", "b/old.js")
        (self.root / "b" / "old.js").rename(self.root / "b" / "moved.js")  # renommé, non indexé
        self.assertEqual(m.changed_paths(self.root, "HEAD"), ({"b/old.js", "b/moved.js"}, {"b/old.js"}))
        (self.root / "b" / "moved.js").rename(self.root / "b" / "old.js")
        self.git("mv", "a/two.js", "a/three.js")  # renommé puis commité : vu par le diff base..HEAD
        base = self.git("rev-parse", "HEAD")
        self.git("commit", "-qm", "rename")
        self.assertEqual(m.changed_paths(self.root, base), ({"a/two.js", "a/three.js"}, {"a/two.js"}))

    def test_h20_mcp_json_refused_in_plans_and_during_execution(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.classify(".mcp.json"), "guardrail")
        self.assertEqual(m.classify("sub/dir/.mcp.json"), "guardrail")
        self.hconfig()
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("debate", "next", "--run", run, code=0)
        self.pmx("decide", "--run", run, "--by", "consensus", code=0)
        for f in (".mcp.json", "src/.mcp.json"):
            t = {**self.task("a", "team-a", ["src/a.js"]), "files": [f]}
            p = self.pmx("plan", "submit", "--run", run, "--file", str(self.plan([t])), code=1)
            self.assertIn("chemin sensible (guardrail)", p.stdout, f)
        self.assertIn("Edit(.mcp.json)", json.loads((HERE.parents[1] / "adapters" / "pilot-hybrid" / "settings.hybrid.json").read_text())["permissions"]["deny"])

    def test_h21_disable_autoupdater_changes_no_protection(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        (self.root / ".claude" / "s.json").write_text(json.dumps(SETTINGS_OK))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": test_pmx.team("ok")})
        ctx = m.Ctx(self.root)
        old = dict(os.environ)
        try:
            os.environ["DISABLE_AUTOUPDATER"] = "0"  # valeur de l'hôte sans effet
            env = m.agent_env()
            self.assertEqual(env["DISABLE_AUTOUPDATER"], "1")
            self.assertEqual({k: v for k, v in env.items() if "AUTOUPDATER" in k}, {"DISABLE_AUTOUPDATER": "1"})  # une seule variable ajoutée
            with_var = m.claude_confined_settings(ctx, ctx.o["teams"]["team-a"], self.tmp, "write", self.tmp / "a.json").read_text()
            probs_with = m.bypass_problems(ctx) + m.mode_problems(ctx)
            del os.environ["DISABLE_AUTOUPDATER"]
            without = m.claude_confined_settings(ctx, ctx.o["teams"]["team-a"], self.tmp, "write", self.tmp / "b.json").read_text()
            self.assertEqual(with_var, without)  # réglages de sandbox et de permissions identiques
            self.assertEqual(probs_with, m.bypass_problems(ctx) + m.mode_problems(ctx))
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_h22_no_cgroup_tracking_refuses_agents_without_fallback(self):
        run, p = self.dispatch_with(self.stub_bin(drop=("systemd-run",)), {"team-a": test_pmx.team("ok"), "team-b": test_pmx.team("ok")})
        self.assertEqual(p.returncode, 64, p.stdout + p.stderr)
        self.assertIn("suivi des tentatives par cgroup indisponible", p.stdout + p.stderr)
        self.assertEqual(json.loads((self.root / "ai_memory" / "runs" / run / "run.json").read_text())["tasks"]["a"]["attempts"], [])

    def test_h18_first_status_line_path_is_not_truncated(self):
        # `git status --porcelain` commence par une espace pour un fichier suivi modifié : son chemin ne doit perdre aucun caractère
        import importlib.util
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        (self.root / "xsrc").mkdir()
        (self.root / "xsrc" / "a.js").write_text("a\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "suivi")
        (self.root / "xsrc" / "a.js").write_text("b\n")
        paths, _ = m.changed_paths(self.root, "HEAD")
        self.assertEqual(paths, {"xsrc/a.js"})  # et non « src/a.js », qu'un périmètre aurait autorisé
        self.hconfig()
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        wi = next(iter(wis))
        ctx = m.Ctx(self.root)
        wt = self.tmp / "wt-x"
        self.git("worktree", "add", "-q", "-b", "x", str(wt))
        (wt / "xsrc" / "a.js").write_text("c\n")
        bad, _ = m.scope_check(ctx, {"files": ["src/a.js"], "wi": wi}, str(wt), "HEAD")
        self.assertTrue(any("xsrc/a.js : hors périmètre" in b for b in bad), bad)

    @unittest.skipUnless(shutil.which("claude"), "CLI claude absente")
    def test_h17_confined_claude_team_has_no_shell(self):
        import importlib.util
        (self.root / ".claude" / "s.json").write_text(json.dumps({"permissions": {"defaultMode": "acceptEdits", "allow": ["Read", "Bash(python3 -B -m unittest:*)"], "deny": ["Bash(docker:*)"]}}))
        self.hconfig({"team-a": {"adapter": "claude-cli", "settings": ".claude/s.json"}, "team-b": test_pmx.team("ok")},
                     debate=("consensus", "consensus"))
        run, wis = self.to_approved([self.task("a", "team-a", ["src/a.js"])])
        spec = importlib.util.spec_from_file_location("pmx", test_pmx.PMX)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        ctx = m.Ctx(self.root)
        wt = self.tmp / "wt" / "x"
        wt.mkdir(parents=True)
        pf = self.tmp / "brief.md"
        pf.write_text("brief")
        acfg = ctx.o["teams"]["team-a"]
        argv, _ = m.agent_argv(ctx, acfg, pf, self.tmp / "o.md", wt, "write")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Grep,Glob,Edit,Write")
        gen = json.loads(pathlib.Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertIn("Bash", gen["permissions"]["deny"])  # l'emporte sur la règle allow de la politique de l'équipe
        self.assertIn("Bash(docker:*)", gen["permissions"]["deny"])  # politique conservée
        self.assertTrue(gen["sandbox"]["enabled"] and gen["sandbox"]["failIfUnavailable"])  # sandbox non affaibli
        self.assertFalse(gen["sandbox"]["allowUnsandboxedCommands"])
        brief = m.team_brief(ctx, ctx.load_run(run), "a", 1, wt, self.tmp / "r.md")
        self.assertIn("aucun outil shell", brief)
        self.assertIn("pmx verify", brief)
        section = brief.split("## Vérification attendue")[1].split("## ")[0]
        self.assertNotIn("colle la sortie", section)
        self.assertIn("remplace", section)  # la ligne du rôle `developer` sur le lancement des tests ne s'applique pas
        # lecture (débat, revue) : jamais de shell, quel que soit le mode
        ro, _ = m.agent_argv(ctx, acfg, pf, self.tmp / "o.md", wt, "read")
        self.assertEqual(ro[ro.index("--tools") + 1], "Read,Grep,Glob")
        # capacité conservée : un seul point de décision ; le bloc sandbox et les règles restent générés
        m.CONFINED_CLAUDE_TEAM_SHELL = True
        argv, _ = m.agent_argv(ctx, acfg, pf, self.tmp / "o.md", wt, "write")
        self.assertIn("Bash", argv[argv.index("--tools") + 1])
        gen2 = json.loads(pathlib.Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertNotIn("Bash", gen2["permissions"]["deny"])
        self.assertEqual(gen2["sandbox"], gen["sandbox"])
        self.assertIn("colle la sortie", m.team_brief(ctx, ctx.load_run(run), "a", 1, wt, self.tmp / "r.md").split("## Vérification attendue")[1].split("## ")[0])
        m.CONFINED_CLAUDE_TEAM_SHELL = False
        # hors confinement natif : comportement 3.1 inchangé (aucun sandbox, donc aucun artefact)
        ctx.o["confinement"] = None
        argv, _ = m.agent_argv(ctx, acfg, pf, self.tmp / "o.md", wt, "write")
        self.assertIn("Bash", argv[argv.index("--tools") + 1])
        self.assertEqual(argv[argv.index("--settings") + 1], str((self.root / ".claude" / "s.json").resolve()))  # réglages de l'équipe, sans ajout
        # confinement natif hors profil hybride : shell conservé, autres protections inchangées
        ctx.o["confinement"], ctx.o["mode"] = "native", "default"
        argv, _ = m.agent_argv(ctx, acfg, pf, self.tmp / "o.md", wt, "write")
        self.assertIn("Bash", argv[argv.index("--tools") + 1])
        gen3 = json.loads(pathlib.Path(argv[argv.index("--settings") + 1]).read_text())
        self.assertNotIn("Bash", gen3["permissions"]["deny"])
        self.assertEqual(gen3["sandbox"], gen["sandbox"])
        ctx.o["mode"] = m.HYBRID
        # les autres adaptateurs ne dépendent pas de ce choix
        cx, _ = m.agent_argv(ctx, {"adapter": "codex-cli"}, pf, self.tmp / "o.md", wt, "write")
        self.assertIn('default_permissions="pmx-ws"', cx)
        self.assertNotIn("--tools", cx)

    def test_h09_example_adapter_is_consistent(self):
        kit = HERE.parents[1] / "adapters" / "pilot-hybrid"
        cfg = json.loads((kit / "project-manager.config.json").read_text())
        (self.root / ".claude" / "project-manager.config.json").write_text(json.dumps(cfg))
        shutil.copy(kit / "settings.hybrid.json", self.root / ".claude" / "settings.hybrid.json")
        shutil.copy(kit / "pmx.integration-policy.json", self.root / ".claude" / "pmx.integration-policy.json")
        run = self.pmx("start", "--title", "Demo", "--request", "q", code=0).stdout.strip()
        self.pmx("verify", "--run", run, code=0)  # toutes les exigences du profil satisfaites par l'exemple livré


for _n in [n for n in dir(test_docker.Docker) if n.startswith("test_")]:
    setattr(Hybrid, _n, None)


if __name__ == "__main__":
    unittest.main()
