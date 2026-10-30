#!/usr/bin/env python3
"""Mesure (opt-in) : deux équipes docker factices en parallèle via pmx — chevauchement, CPU, mémoire, latence de démarrage.
Usage : python3 -I -B tests/pilot/docker_measure.py <dossier-neuf>   → RESULTS.json + RESULTS.md (+ dépôt jetable conservé)
Données fictives uniquement ; aucun réseau ; ne touche qu'aux conteneurs créés pour ce dépôt jetable (label pmx.root).
"""
import datetime, json, os, pathlib, re, subprocess, sys, threading, time

HERE = pathlib.Path(__file__).resolve().parent
PMX = HERE.parents[1] / "skills" / "project-manager" / "scripts" / "pmx.py"
IMAGE = os.environ.get("PMX_DOCKER_IMAGE", "alpine:3.22")
PY = sys.executable


def sh(*a, cwd=None, check=True):
    p = subprocess.run(a, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"{a} → {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()


def parse_ts(s):
    s = re.sub(r"(\.\d{6})\d*", r"\1", s.replace("Z", "+00:00"))
    return datetime.datetime.fromisoformat(s)


def main(out):
    out = pathlib.Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"dossier non vide : {out}")
    root = out / "repo"
    root.mkdir(parents=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(out / "gitconfig")}
    (out / "gitconfig").write_text("[user]\n\tname = t\n\temail = t@invalid\n[init]\n\tdefaultBranch = main\n")
    git = lambda *a: subprocess.run(["git", "-C", str(root), *a], env=env, check=True, capture_output=True)
    git("init", "-q")
    (root / "README.md").write_text("demo fictive\n")
    (root / ".claude").mkdir()
    dteam = lambda: {"adapter": "docker", "docker": {"image": IMAGE, "argv": ["sh", "/agent/agent.sh", "{prompt_file}", "work"],
                                                      "agent_dir": str(HERE / "docker-agent"), "cpus": 1.0, "memory": "256m", "pids": 64}}
    deb = {"adapter": "cmd", "argv": [PY, "-I", str(HERE / "fake_agent.py"), "debate", "{prompt_file}", "{out_file}", "consensus"]}
    cfg = {"schema": "pm-v3/1", "work_items": {"backend": "ledger"}, "multi_team": {"enabled": True},
           "orchestration": {"enabled": True, "teams": {"team-a": dteam(), "team-b": dteam()}, "worktree_root": "../wt",
                             "debate": {"agents": {"claude": deb, "codex": deb}}, "allowed_test_commands": ["test -f src/a.js", "test -f src/b.js"]}}
    (root / ".claude" / "project-manager.config.json").write_text(json.dumps(cfg))
    git("add", "-A"); git("commit", "-qm", "init")
    pmx = lambda *a, code=0: sh(PY, "-I", str(PMX), "--root", str(root), *a, check=code == 0)
    run = pmx("start", "--title", "Mesure docker", "--request", "deux modules")
    pmx("debate", "next", "--run", run); pmx("decide", "--run", run, "--by", "consensus")
    plan = out / "plan.json"
    plan.write_text(json.dumps({"tasks": [{"key": k, "title": f"module {k}", "team": f"team-{k}", "files": [f"src/{k}.js"], "test_command": f"test -f src/{k}.js",
                                           "acceptance": ["fichier présent"]} for k in ("a", "b")]}))
    subprocess.run([PY, "-I", str(PMX), "--root", str(root), "plan", "submit", "--run", run, "--file", str(plan)], capture_output=True)
    pmx("plan", "approve", "--run", run, "--by", "mesure")

    host = {"cpus": os.cpu_count(), "mem_total_mib": int(re.search(r"MemTotal:\s+(\d+)", open("/proc/meminfo").read()).group(1)) // 1024,
            "loadavg_before": open("/proc/loadavg").read().split()[:3], "docker": sh("docker", "version", "--format", "{{.Server.Version}}")}
    samples, stop = [], threading.Event()

    def sampler():
        while not stop.is_set():
            names = sh("docker", "ps", "--filter", "label=pmx.pilot=1", "--filter", f"label=pmx.root={root}", "--format", "{{.Names}}", check=False).split()
            if names:
                for line in sh("docker", "stats", "--no-stream", "--format", "{{json .}}", *names, check=False).splitlines():
                    d = json.loads(line)
                    samples.append({"t": time.time(), "name": d["Name"], "cpu_pct": float(d["CPUPerc"].rstrip("%") or 0),
                                    "mem": d["MemUsage"].split("/")[0].strip(), "mem_pct": float(d["MemPerc"].rstrip("%") or 0), "pids": int(d["PIDs"] or 0)})
            time.sleep(0.2)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t0 = time.time()
    pmx("dispatch", "--run", run)
    pmx("wait", "--run", run, "--interval", "0.3")
    wall = time.time() - t0
    stop.set(); th.join()
    pmx("evidence", "--run", run)
    par = json.loads((root / "ai_memory" / "runs" / run / "parallelism.json").read_text())
    events = [json.loads(l) for l in (root / "ai_memory" / "runs" / run / "events.jsonl").read_text().splitlines()]
    containers = {}
    for k in ("a", "b"):
        ev = json.loads(next((root / "ai_memory" / "runs" / run / "tasks" / k).glob("container-*.json")).read_text())
        started_evt = next(e for e in events if e["event"] == "team_started" and e["task"] == k)
        cs, cf = parse_ts(ev["state"]["StartedAt"]), parse_ts(ev["state"]["FinishedAt"])
        containers[k] = {"name": ev["name"], "exit": ev["state"]["ExitCode"], "oom": ev["state"]["OOMKilled"],
                         "startup_latency_s": round((cs - parse_ts(started_evt["ts"])).total_seconds(), 2),
                         "container_runtime_s": round((cf - cs).total_seconds(), 2), "limits": {k2: ev["host_config"][k2] for k2 in ("NanoCpus", "Memory", "PidsLimit")}}
    def to_mib(s):
        m = re.match(r"([\d.]+)\s*([KMG]i?B|B)", s)
        n, u = float(m.group(1)), m.group(2)
        return n * {"B": 1 / 2**20, "KiB": 1 / 1024, "kB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}.get(u, 1)
    per = {}
    for s in samples:
        p = per.setdefault(s["name"], {"samples": 0, "cpu_peak_pct": 0.0, "mem_peak_mib": 0.0, "pids_peak": 0})
        p["samples"] += 1
        p["cpu_peak_pct"] = max(p["cpu_peak_pct"], s["cpu_pct"])
        p["mem_peak_mib"] = round(max(p["mem_peak_mib"], to_mib(s["mem"])), 1)
        p["pids_peak"] = max(p["pids_peak"], s["pids"])
    both = sorted({round(s["t"], 1) for s in samples if sum(1 for x in samples if abs(x["t"] - s["t"]) < 0.15) >= 2})
    res = {"run": run, "wall_s": round(wall, 2), "overlap": par["overlaps"], "containers": containers, "stats": per,
           "samples_with_both_running": len(both), "host": host, "loadavg_after": open("/proc/loadavg").read().split()[:3],
           "statuses": sh("grep", "-E", "^- status:", str(root / "ai_memory" / "WORK_ITEMS.md")).splitlines()}
    (out / "RESULTS.json").write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    (out / "samples.json").write_text(json.dumps(samples, indent=1) + "\n")
    md = [f"# Mesure — deux équipes docker en parallèle ({datetime.date.today()})", "",
          f"Hôte : {host['cpus']} CPU logiques, {host['mem_total_mib']} Mio, Docker {host['docker']}. Charge factice par équipe : ~48 Mo gardés + boucle active 4 s ; limites 1 CPU / 256 Mio / 64 pids.", "",
          f"- Durée totale (dispatch → fin de `wait`) : **{res['wall_s']} s**",
          f"- Chevauchement mesuré par pmx : **{', '.join(f"{o['a']} ‖ {o['b']} : {o['seconds']} s" for o in par['overlaps'])}**", "",
          "| Équipe | Conteneur | Latence de démarrage | Durée conteneur | CPU pic | Mémoire pic | PIDs pic | Sortie |", "|---|---|---|---|---|---|---|---|"]
    for k, c in containers.items():
        s = per.get(c["name"], {})
        md.append(f"| {k} | `{c['name']}` | {c['startup_latency_s']} s | {c['container_runtime_s']} s | {s.get('cpu_peak_pct', '?')} % | {s.get('mem_peak_mib', '?')} Mio | {s.get('pids_peak', '?')} | {c['exit']} (oom={c['oom']}) |")
    md += ["", f"Échantillons `docker stats` : {len(samples)} (période ~0,2 s + durée de `docker stats`, chaque appel ~1–2 s) ; la mesure est grossière.",
           f"Charge moyenne hôte avant / après : {host['loadavg_before']} / {res['loadavg_after']}."]
    (out / "RESULTS.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
