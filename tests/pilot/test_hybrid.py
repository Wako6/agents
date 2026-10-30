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
        for tool in ("git", "test", "sh", "cat", "docker", "bwrap", "socat", "python3", "claude"):
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
