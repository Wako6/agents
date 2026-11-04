#!/usr/bin/env python3
"""Validation RÉELLE de l'absence d'outils MCP externes — opt-in, consomme l'usage des abonnements Claude et Codex déjà connectés.

  PMX_LIVE=1 python3 -I -B tests/pilot/live_mcp.py <dossier-neuf>

Projet fictif jetable. Seul un serveur MCP local factice peut être appelé : la consigne n'appelle aucun outil réel, et les connexions
de l'utilisateur ne sont pas modifiées. Argv réels de pmx, confinement natif. Écrit <dossier>/RESULTS.json.
"""
import glob, importlib.util, json, os, pathlib, shutil, subprocess, sys, threading, time

HERE = pathlib.Path(__file__).resolve().parent
KIT = HERE.parents[1]
CHECKS = []


def check(name, ok, detail=None):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"{'✔' if ok else '✘'} {name}" + (f" — {str(detail)[:200]}" if not ok and detail is not None else ""))


def load_pmx():
    s = importlib.util.spec_from_file_location("pmx", KIT / "skills/project-manager/scripts/pmx.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


FAKE = """import json, os, sys
log = sys.argv[1]
def note(**k):
    open(log, "a").write(json.dumps(k) + "\\n")
note(ev="start")
for line in sys.stdin:
    m = json.loads(line); i, meth = m.get("id"), m.get("method")
    if meth == "initialize":
        r = {"protocolVersion": m["params"].get("protocolVersion"), "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}
    elif meth == "tools/list":
        r = {"tools": [{"name": "probe_ro", "description": "Fictive tool.", "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}}]}
    elif meth == "tools/call":
        note(ev="call"); r = {"content": [{"type": "text", "text": "FAKE"}]}
    elif i is not None:
        r = {}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": i, "result": r}), flush=True)
"""
CALL = "Projet fictif. Appelle une seule fois l'outil MCP probe_ro du serveur fake s'il existe. N'utilise aucun autre outil MCP ni connecteur. Termine par CALLED ou UNAVAILABLE."
HI = "Réponds uniquement OK. N'appelle aucun outil."


def descendants(root):
    """Lignes de commande des descendants de `root`, y compris ceux qui ont changé de session."""
    kids = {}
    for d in glob.glob("/proc/[0-9]*/stat"):
        try:
            pid = int(d.split("/")[2])
            kids.setdefault(int(open(d).read().rsplit(")", 1)[1].split()[1]), []).append(pid)
        except (OSError, IndexError, ValueError):
            pass
    out, todo = [], [root]
    while todo:
        for k in kids.get(todo.pop(), []):
            todo.append(k)
            try:
                out.append([x.decode(errors="replace") for x in open(f"/proc/{k}/cmdline", "rb").read().split(b"\0") if x])
            except OSError:
                pass
    return out


def mcp_servers_among(cmds, base):
    """Processus de serveur MCP : le mot `mcp` hors de la CLI Codex, dont les propres arguments citent les serveurs désactivés,
    et hors du chemin de ce banc, que le sandbox de chaque commande cite aussi."""
    found = set()
    for a in cmds:
        if not a or os.path.basename(a[0]) == "codex" or (len(a) > 1 and a[1].endswith("/bin/codex")):
            continue
        line = " ".join(a)
        if "mcp" in line.replace(str(base), "").lower() or "fake_mcp_probe" in line:
            found.add(line)
    return sorted(found)


def run_watched(argv, cwd, env, base):
    seen, p = set(), subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL)
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            seen.update(mcp_servers_among(descendants(p.pid), base))
            time.sleep(0.1)
    th = threading.Thread(target=watch)
    th.start()
    out, err = p.communicate(timeout=240)
    stop.set()
    th.join()
    return p.returncode, out, err, sorted(seen)


def main(base):
    if os.environ.get("PMX_LIVE") != "1":
        raise SystemExit("opt-in : PMX_LIVE=1 requis")
    base = pathlib.Path(base)
    base.mkdir(parents=True)
    fake = base / "fake_mcp_probe.py"
    fake.write_text(FAKE)
    log = base / "fake.log"
    m = load_pmx()
    root = base / "root"
    (root / ".claude").mkdir(parents=True)
    for f in (KIT / "adapters/pilot-hybrid").glob("*.json"):
        shutil.copy(f, root / ".claude" / f.name)
    subprocess.run(["git", "-C", str(root), "init", "-q"])
    ctx = m.Ctx(root)
    team = {"adapter": "claude-cli", "settings": ".claude/settings.hybrid.json"}

    def wt(name):
        w = base / f"wt-{name}"
        (w / ".claude").mkdir(parents=True)
        subprocess.run(["git", "-C", str(w), "init", "-q"])
        (w / ".mcp.json").write_text(json.dumps({"mcpServers": {"fake": {"command": sys.executable, "args": ["-I", str(fake), str(log)]}}}))
        (w / ".claude/settings.json").write_text(json.dumps({"enableAllProjectMcpServers": True, "permissions": {"allow": ["mcp__fake__probe_ro"]},
                                                             "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": f"echo x >> {base}/hook.log"}]}]}}))
        return w

    for role, mode, native in (("développement", "write", ["Edit", "Glob", "Grep", "Read", "Write"]), ("débat et revue", "read", ["Glob", "Grep", "Read"])):
        for kind, prompt in (("présence", HI), ("appel", CALL)):
            name = f"claude-{mode}-{kind}"
            w, g = wt(name), base / f"gen-{name}"
            g.mkdir()
            (g / "p.md").write_text(prompt)
            argv, _ = m.agent_argv(ctx, team, g / "p.md", g / "o", w, mode)
            argv[argv.index("--output-format") + 1] = "stream-json"
            argv += ["--verbose", "--no-session-persistence"]
            log.unlink(missing_ok=True)
            p = subprocess.run(argv, cwd=w, env=m.agent_env(), capture_output=True, text=True, timeout=240, stdin=subprocess.DEVNULL)
            (base / f"{name}.jsonl").write_text(p.stdout)
            evs = [json.loads(x) for x in p.stdout.splitlines() if x.startswith("{")]
            init = next(e for e in evs if e.get("subtype") == "init")
            used = [b["name"] for e in evs if e.get("type") == "assistant" for b in e["message"].get("content", []) if b.get("type") == "tool_use"]
            check(f"Claude {role} ({kind}) : abonnement fonctionnel", p.returncode == 0, p.stderr[-200:])
            check(f"Claude {role} ({kind}) : aucun serveur, aucun outil MCP", not init["mcp_servers"] and not [t for t in init["tools"] if t.startswith("mcp__")], init["mcp_servers"])
            check(f"Claude {role} ({kind}) : outils natifs conservés", sorted(init["tools"]) == native, init["tools"])
            check(f"Claude {role} ({kind}) : serveur du dépôt non démarré, malgré sa règle allow", not log.exists())
            check(f"Claude {role} ({kind}) : aucun appel MCP", not [u for u in used if u.startswith("mcp__")], used)
            check(f"Claude {role} ({kind}) : hook du dépôt non exécuté", not (base / "hook.log").exists())

    for mode in ("write", "read"):
        for kind, prompt in (("présence", HI), ("appel", CALL)):
            name = f"codex-{mode}-{kind}"
            w, g = base / f"wt-{name}", base / f"gen-{name}"
            w.mkdir()
            g.mkdir()
            subprocess.run(["git", "-C", str(w), "init", "-q"])
            (g / "p.md").write_text(prompt)
            argv, _ = m.agent_argv(ctx, {"adapter": "codex-cli"}, g / "p.md", g / "o", w, mode)
            # serveur factice ajouté PUIS désactivé, comme un serveur hérité : témoin de la désactivation par nom
            argv = [argv[0], argv[1], "--json", "-c", f'mcp_servers.fake.command="{sys.executable}"', "-c", f'mcp_servers.fake.args=["-I","{fake}","{log}"]', "-c", "mcp_servers.fake.enabled=false", *argv[2:]]
            log.unlink(missing_ok=True)
            rc, out, err, seen = run_watched(argv, w, m.agent_env(), base)
            (base / f"{name}.jsonl").write_text(out)
            items = [json.loads(x).get("item") or {} for x in out.splitlines() if x.startswith("{")]
            check(f"Codex {mode} ({kind}) : abonnement fonctionnel", rc == 0, err[-200:])
            check(f"Codex {mode} ({kind}) : aucun serveur MCP démarré (serveurs déclarés de l'utilisateur compris)", not seen and not log.exists(), sorted(seen))
            check(f"Codex {mode} ({kind}) : aucun appel MCP", not [i for i in items if i.get("type") == "mcp_tool_call"], items[:3])
            check(f"Codex {mode} ({kind}) : confinement natif présent", any("network.enabled=false" in x for x in argv) and f'default_permissions="pmx-{"ws" if mode == "write" else "ro"}"' in argv)

    # témoin : sans la restriction, un serveur factice démarre et la sonde le voit. Sinon la sonde ne prouverait rien.
    w, g = base / "wt-codex-temoin", base / "gen-codex-temoin"
    w.mkdir()
    g.mkdir()
    subprocess.run(["git", "-C", str(w), "init", "-q"])
    (g / "p.md").write_text(HI)
    witness_log = base / "temoin.log"
    r, o, e, seen = run_watched(["codex", "exec", "--json", "-c", f'mcp_servers.fake.command="{sys.executable}"', "-c", f'mcp_servers.fake.args=["-I","{fake}","{witness_log}"]',
                                 *(x for n, _on in m.codex_mcp_servers(w) for x in ("-c", f"mcp_servers.{n}.enabled=false")), *m.codex_profile_args("read"), "--skip-git-repo-check", "--ephemeral", "-C", str(w), HI], w, m.agent_env(), base)
    check("Témoin Codex : la sonde voit un serveur MCP non désactivé", r == 0 and witness_log.exists() and any("fake_mcp_probe" in x for x in seen), seen)

    (base / "RESULTS.json").write_text(json.dumps({"claude": subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip(),
                                                   "codex": subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip(), "checks": CHECKS}, indent=1, ensure_ascii=False))
    ko = [c for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(ko)}/{len(CHECKS)} conformes")
    return 1 if ko else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
