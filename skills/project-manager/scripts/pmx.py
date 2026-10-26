#!/usr/bin/env python3
"""pmx — orchestrateur pilote du Project Manager V3 : débat Claude–Codex borné, deux équipes parallèles en worktrees,
vérification indépendante, revue croisée, intégration locale contrôlée. Python stdlib, aucune dépendance.

Lancé UNIQUEMENT depuis la session lead (cascade guard du skill). Registre unique : `ai_memory/WORK_ITEMS.md` (backend
ledger) — pmx n'en crée pas d'autre ; l'état technique d'exécution (PID, worktrees, tours de débat) vit dans
`ai_memory/runs/<run>/run.json` + `events.jsonl` (journal append-only), jamais les statuts de work items.

  pmx.py --root <repo> doctor                                   préflight lecture seule
  pmx.py --root <repo> start   --title T --request FICHIER      réserve le WI parent, ouvre un run
  pmx.py --root <repo> debate  next|submit|show --run R ...     débat Claude–Codex (≤ max_rounds tours)
  pmx.py --root <repo> decide  --run R --by consensus|human:<nom> [--text ...]
  pmx.py --root <repo> plan    submit|approve --run R ...       plan structuré, détection des collisions, gate « go »
  pmx.py --root <repo> dispatch|tick|wait --run R               lancement et suivi des équipes
  pmx.py --root <repo> report  --run R --task K --status done|failed --file F   (équipe externe « drop »)
  pmx.py --root <repo> verify|review|integrate --run R ...      vérification, revue croisée, intégration locale
  pmx.py --root <repo> status|evidence|resume|abort --run R

Codes de sortie : 0 ok · 1 échec / refus · 2 décision humaine requise · 3 échec critique (équipes arrêtées)
· 10 en attente d'un agent externe (drop) · 64 usage.
"""
import argparse, datetime, fcntl, fnmatch, json, os, pathlib, re, shlex, shutil, signal, subprocess, sys, time

SCHEMA = "pm-v3/1"
EXIT_OK, EXIT_FAIL, EXIT_HUMAN, EXIT_CRITICAL, EXIT_WAIT, EXIT_USAGE = 0, 1, 2, 3, 10, 64
STATUSES = ("OPEN", "IN_PROGRESS", "READY_FOR_VERIFICATION", "READY_FOR_REVIEW", "BLOCKED", "ESCALATED", "STALE", "DONE")
MARKERS = ("<<CONSENSUS>>", "<<CONTINUE>>", "<<WAIT_HUMAN>>")
DEFAULTS = {
    "enabled": False, "max_parallel": 2, "max_attempts": 3, "auto_retry": True, "team_timeout_s": 1800, "verify_timeout_s": 600,
    "debate": {"max_rounds": 3, "order": ["claude", "codex"], "agents": {"claude": {"adapter": "drop"}, "codex": {"adapter": "codex-cli"}}},
    "teams": {}, "cross_review": {}, "worktree_root": None, "branch_prefix": "pilot/", "integration_branch": "pilot/integration",
    "protected_branches": ["main", "master", "develop", "production", "release/*", "hotfix/*"],
    "verify_commands": [], "sensitive_paths": [], "integration_policy": ".claude/pmx.integration-policy.json",
}
# Chemins qui exigent toujours une validation humaine (secrets, permissions, hooks/garde-fous, CI/production).
SENSITIVE = [
    ("secret", [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "*secret*", "*credential*", "*token*", ".npmrc", ".pypirc", ".netrc"]),
    ("guardrail", [".claude/*", ".claude/**", ".git/*", ".githooks/*", ".husky/*", "hooks/*", "*/hooks/*", "*settings*.json", ".pre-commit-config.yaml", "CODEOWNERS", "ai_rules/*", ".claude/rules/*"]),
    ("production", [".gitlab-ci.yml", ".github/workflows/*", "deploy/*", "k8s/*", "helm/*", "terraform/*", "*.tf", "Dockerfile", "docker-compose*.yml"]),
]


# ---------------------------------------------------------------- utilitaires

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def die(msg, code=EXIT_FAIL):
    print(f"✘ {msg}", file=sys.stderr)
    sys.exit(code)


def git(root, *args, check=True, env=None):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} → {p.returncode}: {p.stderr.strip()}")
    return p.stdout.strip()


GIT_ID = ["-c", "user.name=pmx-pilot", "-c", "user.email=pmx-pilot@invalid", "-c", "commit.gpgsign=false"]


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pmx-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def tail(text, n=50):
    lines = (text or "").rstrip().splitlines()
    return "\n".join(lines[-n:])


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # un zombie (enfant terminé non récolté) n'est plus vivant
    try:
        st = pathlib.Path(f"/proc/{pid}/stat").read_text()
        return st.split(") ", 1)[1][:1] != "Z"
    except OSError:
        return True


def match_any(path, patterns):
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if fnmatch.fnmatch(path, pat) or ("/" not in pat and fnmatch.fnmatch(name, pat)):
            return True
        if pat.endswith("/**") and path.startswith(pat[:-3] + "/"):
            return True
    return False


def classify(path, extra=()):
    """Catégorie sensible d'un chemin (ou None). Les motifs du projet (`sensitive_paths`) s'ajoutent, ne retirent rien."""
    for cat, pats in SENSITIVE:
        if match_any(path, pats):
            return cat
    if match_any(path, list(extra)):
        return "project-sensitive"
    return None


# ---------------------------------------------------------------- contexte projet

class Ctx:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        if not (self.root / ".git").exists():
            die(f"pas un dépôt git (checkout principal attendu) : {self.root}", EXIT_USAGE)
        # cascade guard technique : le lead tourne depuis le checkout principal, jamais depuis un worktree lié
        gd, cd = git(self.root, "rev-parse", "--git-dir"), git(self.root, "rev-parse", "--git-common-dir")
        if pathlib.Path(self.root, gd).resolve() != pathlib.Path(self.root, cd).resolve():
            die("pmx doit tourner dans la session lead, depuis le checkout principal (worktree lié détecté)", EXIT_USAGE)
        cfg_path = self.root / ".claude" / "project-manager.config.json"
        try:
            self.cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            die(f"configuration projet illisible ({cfg_path}) : {e}", EXIT_USAGE)
        if self.cfg.get("schema") != SCHEMA:
            die(f"schema {SCHEMA} attendu", EXIT_USAGE)
        self.backend = (self.cfg.get("work_items") or {}).get("backend")
        o = json.loads(json.dumps(DEFAULTS))
        for k, v in (self.cfg.get("orchestration") or {}).items():
            if isinstance(v, dict) and isinstance(o.get(k), dict):
                o[k].update(v)
            else:
                o[k] = v
        self.o = o
        self.am = self.root / "ai_memory"
        self.lockf = self.am / ".pmx.lock"
        wt = o.get("worktree_root") or f"../{self.root.name}.worktrees"
        self.wt_root = (self.root / wt).resolve()

    def require_enabled(self):
        if self.backend != "ledger":
            die("pilote : backend `ledger` requis (le variant gitlab-issues reste celui de multi-team.md)", EXIT_USAGE)
        if not self.o.get("enabled"):
            die("orchestration.enabled=false dans la configuration : le workflow V3 standard s'applique", EXIT_USAGE)
        if not self.o.get("teams"):
            die("orchestration.teams vide", EXIT_USAGE)

    def lock(self):
        self.am.mkdir(exist_ok=True)
        fh = open(self.lockf, "a+")
        fcntl.flock(fh, fcntl.LOCK_EX)
        return fh

    def run_dir(self, run):
        return self.am / "runs" / run

    def load_run(self, run):
        p = self.run_dir(run) / "run.json"
        if not p.exists():
            die(f"run inconnu : {run}", EXIT_USAGE)
        return json.loads(p.read_text(encoding="utf-8"))

    def save_run(self, st):
        st["updated"] = now()
        write_atomic(self.run_dir(st["run"]) / "run.json", json.dumps(st, indent=2, ensure_ascii=False) + "\n")

    def event(self, run, kind, **data):
        line = json.dumps({"ts": now(), "pid": os.getpid(), "event": kind, **data}, ensure_ascii=False) + "\n"
        d = self.run_dir(run)
        d.mkdir(parents=True, exist_ok=True)
        fd = os.open(d / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def events(self, run):
        p = self.run_dir(run) / "events.jsonl"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def is_protected(self, branch):
        return any(fnmatch.fnmatch(branch, p) for p in self.o["protected_branches"])


# ---------------------------------------------------------------- registre ledger (unique)

WI_HEAD = re.compile(r"^### (WI-\d{8}-[A-Z0-9]+-\d{3}) — (.*)$")
WI_FIELD = re.compile(r"^- ([a-z_]+): (.*)$")
LEDGER_HEADER = "# Work Items\n\n> Registry (ledger backend) — the single work-item registry of this project. Written by the lead session only.\n\n"


def bslug(root):
    try:
        b = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    except RuntimeError:
        return "NONGIT"
    b = re.sub(r"^(feature|feat|fix|hotfix|bugfix|release)/", "", b)
    return (re.sub(r"[^A-Za-z0-9]", "", b)[:6] or "NONGIT").upper()


def ledger_blocks(text):
    blocks, cur = {}, None
    for i, line in enumerate(text.splitlines()):
        m = WI_HEAD.match(line)
        if m:
            cur = m.group(1)
            blocks[cur] = {"_title": m.group(2), "_line": i}
            continue
        if line.startswith("#"):
            cur = None
            continue
        fm = WI_FIELD.match(line)
        if cur and fm:
            blocks[cur][fm.group(1)] = fm.group(2)
    return blocks


def wi_reserve(ctx, title, fields):
    """Protocole de réservation V3 (backend-ledger.md) : upsert de LA ligne du slug dans WI_COUNTER.lock, puis entrée."""
    slug, today = bslug(ctx.root), datetime.date.today().strftime("%Y%m%d")
    lockp, items, index = ctx.am / "WI_COUNTER.lock", ctx.am / "WORK_ITEMS.md", ctx.am / "INDEX.md"
    lines = lockp.read_text(encoding="utf-8").splitlines() if lockp.exists() else []
    cur = next((l.split("=", 1)[1] for l in lines if l.startswith(slug + "=")), None)
    if cur is None and items.exists():  # verrou absent : plus haut ID existant du slug
        ids = sorted(re.findall(rf"WI-{today}-{slug}-(\d{{3}})", items.read_text(encoding="utf-8")))
        cur = f"WI-{today}-{slug}-{ids[-1]}" if ids else None
    n = int(cur.rsplit("-", 1)[1]) + 1 if cur and cur.split("-")[1] == today else 1
    wi = f"WI-{today}-{slug}-{n:03d}"
    text = items.read_text(encoding="utf-8") if items.exists() else LEDGER_HEADER
    if wi in ledger_blocks(text):
        die(f"unicité du WI non vérifiable ({wi} existe déjà) → BLOCKED")
    if any(l.startswith(slug + "=") for l in lines):
        new = [f"{slug}={wi}" if l.startswith(slug + "=") else l for l in lines]
    else:
        new = lines + [f"{slug}={wi}"]
    write_atomic(lockp, "\n".join(new) + "\n")
    base = {"status": "OPEN", "created": now(), "toa": "explorer", "executor": "—", "attempt_count": "0", "parent": "—",
            "depends_on": "[]", "session": "—", "worktree": "—", "files_probably_touched": "[]", "links": "—"}
    base.update({k: str(v) for k, v in fields.items()})
    block = f"\n### {wi} — {title}\n" + "".join(f"- {k}: {v}\n" for k, v in base.items())
    write_atomic(items, text.rstrip("\n") + "\n" + block)
    _index_upsert(index, wi, title, base["status"], base.get("executor", "—"), base.get("links", "—"))
    return wi


def _index_upsert(index, wi, title, status, roles, notes):
    lines = index.read_text(encoding="utf-8").splitlines() if index.exists() else ["# ai_memory index", ""]
    row = f"{wi} | {title} | {status} | {roles} | {notes}"
    lines = [row if l.startswith(wi + " |") else l for l in lines]
    if row not in lines:
        lines.append(row)
    write_atomic(index, "\n".join(lines) + "\n")


def wi_get(ctx, wi):
    items = ctx.am / "WORK_ITEMS.md"
    b = ledger_blocks(items.read_text(encoding="utf-8")) if items.exists() else {}
    if wi not in b:
        die(f"work item absent du registre : {wi}")
    return b[wi]


def wi_set(ctx, wi, **fields):
    """Met à jour les champs d'UNE entrée, sans réécrire les autres. Statut : valeurs du modèle commun uniquement."""
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(fields["status"])
    items = ctx.am / "WORK_ITEMS.md"
    lines = items.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if (m := WI_HEAD.match(l)) and m.group(1) == wi), None)
    if start is None:
        die(f"work item absent du registre : {wi}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    fields = {**{k: str(v) for k, v in fields.items()}, "updated": now()}
    for k, v in fields.items():
        idx = next((i for i in range(start + 1, end) if (m := WI_FIELD.match(lines[i])) and m.group(1) == k), None)
        if idx is None:
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            lines.insert(end, f"- {k}: {v}")
            end += 1
        else:
            lines[idx] = f"- {k}: {v}"
    write_atomic(items, "\n".join(lines) + "\n")
    b = ledger_blocks("\n".join(lines))[wi]
    _index_upsert(ctx.am / "INDEX.md", wi, b["_title"], b.get("status", "?"), b.get("executor", "—"), b.get("links", "—"))


def wi_status(ctx, wi):
    return wi_get(ctx, wi).get("status", "?")


def role_note(ctx, role, wi, body):
    p = ctx.am / f"{datetime.date.today().isoformat()}__ROLE-{role}__{wi}.md"
    if p.exists():
        body = p.read_text(encoding="utf-8").rstrip() + "\n\n---\n\n" + body
    write_atomic(p, body.rstrip() + "\n")
    return p.relative_to(ctx.root)


# ---------------------------------------------------------------- adaptateurs d'agents

def agent_argv(ctx, acfg, prompt_file, out_file, cwd, mode):
    """Commande d'un agent, ou None pour un agent externe (« drop » : fichiers échangés avec la session lead)."""
    a = acfg.get("adapter")
    prompt = pathlib.Path(prompt_file).read_text(encoding="utf-8")
    if a == "codex-cli":
        argv = ["codex", "exec", "--sandbox", "read-only" if mode == "read" else "workspace-write", "--skip-git-repo-check",
                "--ephemeral", "-C", str(cwd), "-o", str(out_file)]
        if acfg.get("model"):
            argv += ["-m", acfg["model"]]
        return argv + [prompt], False
    if a == "claude-cli":
        tools = "Read,Grep,Glob" if mode == "read" else "Read,Grep,Glob,Edit,Write,Bash"
        argv = ["claude", "-p", prompt, "--output-format", "text", "--tools", tools,
                "--permission-mode", "default" if mode == "read" else "acceptEdits"]
        if acfg.get("settings"):  # politique pilote passée explicitement, jamais la config globale
            argv += ["--settings", str((ctx.root / acfg["settings"]).resolve())]
        if acfg.get("model"):
            argv += ["--model", acfg["model"]]
        return argv, True  # sortie sur stdout
    if a == "cmd":
        sub = {"prompt_file": str(prompt_file), "out_file": str(out_file), "cwd": str(cwd), "mode": mode}
        return [x.format(**sub) for x in acfg["argv"]], bool(acfg.get("stdout_is_output"))
    if a == "drop":
        return None, False
    die(f"adaptateur inconnu : {a!r}", EXIT_USAGE)


def run_agent_sync(ctx, acfg, prompt_file, out_file, cwd, mode, log_file, timeout):
    argv, to_stdout = agent_argv(ctx, acfg, prompt_file, out_file, cwd, mode)
    if argv is None:
        return None
    with open(log_file, "a", encoding="utf-8") as log:
        shown = [x if len(x) < 300 else f"<prompt {len(x)} car.>" for x in argv]
        log.write(f"\n[{now()}] $ {' '.join(shlex.quote(x) for x in shown)}\n")
        log.flush()
        try:
            p = subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            log.write(f"[{now()}] TIMEOUT {timeout}s\n")
            return 124
        except FileNotFoundError as e:
            log.write(f"[{now()}] introuvable : {e}\n")
            return 127
        log.write(p.stdout[-20000:] + "\n" + p.stderr[-20000:] + f"\n[{now()}] exit {p.returncode}\n")
    if to_stdout:
        write_atomic(pathlib.Path(out_file), p.stdout)
    return p.returncode


# ---------------------------------------------------------------- doctor (phase A automatisée, lecture seule)

def cmd_doctor(ctx, a):
    rows = []
    def chk(name, argv):
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=30)
            rows.append((name, "ok" if p.returncode == 0 else f"code {p.returncode}", (p.stdout or p.stderr).strip().splitlines()[0][:70] if (p.stdout or p.stderr).strip() else ""))
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            rows.append((name, "absent", str(e)[:70]))
    chk("git", ["git", "--version"])
    chk("node", ["node", "--version"])
    chk("codex", ["codex", "--version"])
    chk("codex login", ["codex", "login", "status"])
    chk("claude", ["claude", "--version"])
    chk("claudex (optionnel)", ["sh", "-c", "command -v claudex"])
    for name, st, info in rows:
        print(f"  {'✔' if st == 'ok' else '–'} {name:<20} {st:<8} {info}")
    remotes = git(ctx.root, "remote").split()
    print(f"  {'⚠' if remotes else '✔'} remotes : {remotes or 'aucun (pilote local)'}")
    print(f"  backend : {ctx.backend} · orchestration.enabled : {ctx.o['enabled']} · équipes : {', '.join(ctx.o['teams']) or '—'}")
    print(f"  worktrees : {ctx.wt_root} · intégration : {ctx.o['integration_branch']} (protégée : {ctx.is_protected(ctx.o['integration_branch'])})")
    for team, t in ctx.o["teams"].items():
        print(f"  équipe {team} : adaptateur {t.get('adapter')} ({t.get('label', '')})")
    return EXIT_OK


# ---------------------------------------------------------------- run

def cmd_start(ctx, a):
    ctx.require_enabled()
    req = pathlib.Path(a.request).read_text(encoding="utf-8") if a.request and pathlib.Path(a.request).exists() else (a.request or "")
    if not req.strip():
        die("demande vide", EXIT_USAGE)
    with ctx.lock():
        wi = wi_reserve(ctx, a.title, {"toa": "explorer", "executor": "project-manager (pmx pilot)", "session": "lead"})
        d = ctx.run_dir(wi)
        d.mkdir(parents=True, exist_ok=True)
        write_atomic(d / "request.md", req.rstrip() + "\n")
        st = {"run": wi, "parent_wi": wi, "title": a.title, "created": now(), "base": git(ctx.root, "rev-parse", "HEAD"),
              "base_branch": git(ctx.root, "rev-parse", "--abbrev-ref", "HEAD"),
              "debate": {"status": "pending", "turns": []}, "decision": None, "plan": None, "tasks": {}, "integration": None}
        ctx.save_run(st)
        wi_set(ctx, wi, links=f"ai_memory/runs/{wi}/")
    ctx.event(wi, "run_started", title=a.title)
    print(wi)
    return EXIT_OK


# ---------------------------------------------------------------- débat (protocole Claudex, borné)

DEBATE_RULES = """Tu participes à un débat technique structuré avec un autre agent de code, sous contrôle humain (protocole inspiré de Claudex).
- Phase de débat STRICTEMENT en lecture seule : n'écris, ne modifie et ne crée aucun fichier ; n'exécute rien qui écrive.
- Dépôt concerné : {root} (tu peux lire CLAUDE.md, ai_rules/INDEX.md, STACK_SPEC.md, le code).
- Réponds au DERNIER message de l'autre agent, point par point ; sois concret (fichiers, fonctions, tests) ; pas de flatterie.
- Ne cède que sur argument ; signale explicitement ce sur quoi vous êtes d'accord et ce qui reste en désaccord.
- Tour {turn} sur {max_turns} au maximum ({max_rounds} tours de débat). Au-delà, un humain arbitre.

Termine OBLIGATOIREMENT ta réponse par un bloc ```json``` de la forme :
{{"position": "<ta position en 1-3 phrases>", "agreements": ["..."], "disagreements": ["..."], "questions_for_user": ["..."], "proposal": "<la décision que tu proposes, actionnable>"}}
puis, SEULE sur la dernière ligne, exactement un marqueur :
<<CONSENSUS>> si tu acceptes la proposition de l'autre agent telle quelle (ou si vos propositions sont identiques en substance) ;
<<CONTINUE>> s'il reste un désaccord à débattre ;
<<WAIT_HUMAN>> si seule une décision humaine peut trancher.
"""


def parse_turn(text):
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    marker = lines[-1] if lines and lines[-1] in MARKERS else None
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", re.S)
    data = None
    for b in reversed(blocks):
        try:
            data = json.loads(b)
            break
        except json.JSONDecodeError:
            continue
    return marker, data


def debate_prompt(ctx, st, side):
    o = ctx.o["debate"]
    turns, max_turns = st["debate"]["turns"], o["max_rounds"] * len(o["order"])
    req = (ctx.run_dir(st["run"]) / "request.md").read_text(encoding="utf-8")
    hist = "".join(f"\n--- Tour {i + 1} · {t['side']} ---\n{(ctx.run_dir(st['run']) / t['file']).read_text(encoding='utf-8').strip()}\n"
                   for i, t in enumerate(turns))
    rules = DEBATE_RULES.format(root=ctx.root, turn=len(turns) + 1, max_turns=max_turns, max_rounds=o["max_rounds"])
    first = "Tu ouvres le débat : propose une approche argumentée." if not turns else "Historique verbatim du débat ci-dessous ; réponds au dernier tour."
    return f"{rules}\nTu es l'agent « {side} ».\n\n## Demande utilisateur\n{req}\n\n## Débat\n{first}\n{hist or '(aucun tour encore)'}\n"


def debate_state(ctx, st):
    """Calcule l'état du débat à partir des tours enregistrés (source unique : run.json + fichiers de tours)."""
    o, turns = ctx.o["debate"], st["debate"]["turns"]
    max_turns = o["max_rounds"] * len(o["order"])
    if turns and turns[-1]["marker"] == "<<WAIT_HUMAN>>":
        return "awaiting_human", None
    if len(turns) >= 2 and turns[-1]["marker"] == "<<CONSENSUS>>" and turns[-2]["marker"] == "<<CONSENSUS>>":
        return "consensus", None
    if len(turns) >= max_turns:
        return "no_consensus", None
    return "running", o["order"][len(turns) % len(o["order"])]


def _record_turn(ctx, st, side, text, source):
    n = len(st["debate"]["turns"]) + 1
    rel = f"debate/turn-{n:02d}-{side}.md"
    write_atomic(ctx.run_dir(st["run"]) / rel, text.rstrip() + "\n")
    marker, data = parse_turn(text)
    if marker is None:
        marker = "<<CONTINUE>>"  # marqueur absent ou mal placé : on continue, l'humain le verra dans la synthèse
    if n == 1 and marker == "<<CONSENSUS>>":
        marker = "<<CONTINUE>>"  # pas de consensus sans proposition adverse
    st["debate"]["turns"].append({"side": side, "file": rel, "marker": marker, "data": data, "source": source, "ts": now()})
    ctx.event(st["run"], "debate_turn", n=n, side=side, marker=marker, source=source, structured=data is not None)


def cmd_debate(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    if a.action == "show":
        print((ctx.run_dir(a.run) / "debate" / "DEBATE.md").read_text(encoding="utf-8") if (ctx.run_dir(a.run) / "debate" / "DEBATE.md").exists() else json.dumps(st["debate"], indent=2, ensure_ascii=False))
        return EXIT_OK
    if a.action == "submit":
        state, side = debate_state(ctx, st)
        if state != "running" or side != a.side:
            die(f"tour attendu : {side} (état {state}) — reçu {a.side}")
        with ctx.lock():
            st = ctx.load_run(a.run)
            _record_turn(ctx, st, a.side, pathlib.Path(a.file).read_text(encoding="utf-8"), source=f"drop:{a.side}")
            ctx.save_run(st)
        return _debate_advance(ctx, a.run)
    return _debate_advance(ctx, a.run)


def _debate_advance(ctx, run):
    d = ctx.run_dir(run) / "debate"
    d.mkdir(parents=True, exist_ok=True)
    while True:
        st = ctx.load_run(run)
        state, side = debate_state(ctx, st)
        if state != "running":
            with ctx.lock():
                st = ctx.load_run(run)
                st["debate"]["status"] = state
                path = write_debate_doc(ctx, st)
                ctx.save_run(st)
            ctx.event(run, "debate_closed", status=state, needs_human=st["debate"]["needs_human"])
            print(f"débat clos : {state} · arbitrage humain requis : {'oui' if st['debate']['needs_human'] else 'non'} · {path}")
            return EXIT_HUMAN if st["debate"]["needs_human"] else EXIT_OK
        acfg = ctx.o["debate"]["agents"][side]
        n = len(st["debate"]["turns"]) + 1
        pf, of = d / f"turn-{n:02d}-{side}.prompt.md", d / f"turn-{n:02d}-{side}.answer.md"
        write_atomic(pf, debate_prompt(ctx, st, side))
        st["debate"]["status"] = "running"
        ctx.event(run, "debate_turn_requested", n=n, side=side, adapter=acfg.get("adapter"))
        rc = run_agent_sync(ctx, acfg, pf, of, ctx.root, "read", d / "agents.log", ctx.o["team_timeout_s"])
        if rc is None:
            print(f"EN ATTENTE — tour {n} ({side}, agent externe en lecture seule)\n  prompt : {pf}\n  réponse : écrire le texte VERBATIM dans un fichier puis\n"
                  f"  pmx.py --root {ctx.root} debate submit --run {run} --side {side} --file <fichier>")
            return EXIT_WAIT
        if rc != 0 or not of.exists() or not of.read_text(encoding="utf-8").strip():
            ctx.event(run, "debate_turn_failed", n=n, side=side, rc=rc)
            die(f"tour {n} ({side}) en échec (code {rc}) — voir {d / 'agents.log'} ; relancer `debate next` (une seule fois) ou arbitrer")
        with ctx.lock():
            st = ctx.load_run(run)
            _record_turn(ctx, st, side, of.read_text(encoding="utf-8"), source=acfg.get("adapter"))
            ctx.save_run(st)


def write_debate_doc(ctx, st):
    """Contrat V3 I1 : Positions, Points d'accord, Désaccords non résolus, Questions, Décision proposée."""
    turns = st["debate"]["turns"]
    last = {}
    for t in turns:
        last[t["side"]] = t
    agreements, disagreements, questions = [], [], []
    for t in last.values():
        dd = t.get("data") or {}
        for src, dst in ((dd.get("agreements"), agreements), (dd.get("disagreements"), disagreements), (dd.get("questions_for_user"), questions)):
            for x in src or []:
                if x and x not in dst:
                    dst.append(x)
    unstructured = [t["side"] for t in last.values() if not t.get("data")]
    status = st["debate"]["status"]
    needs_human = status != "consensus" or bool(disagreements) or bool(questions) or bool(unstructured)
    st["debate"]["needs_human"] = needs_human
    closing = turns[-1] if turns else None
    proposal = ((closing or {}).get("data") or {}).get("proposal", "—")
    rounds = -(-len(turns) // len(ctx.o["debate"]["order"]))
    out = [f"# DEBATE — {st['parent_wi']} — {st['title']}", "",
           f"Date : {now()} · Statut : **{status}** · Tours : {rounds}/{ctx.o['debate']['max_rounds']} ({len(turns)} interventions) · Arbitrage humain requis : **{'oui' if needs_human else 'non'}**",
           "Protocole : Claudex (transmission verbatim, marqueurs <<CONSENSUS>>/<<CONTINUE>>/<<WAIT_HUMAN>>), lecture seule, rejoué par pmx (Claudex n'a pas de mode non interactif).", "",
           "## Positions (Claude / Codex)"]
    for side in ctx.o["debate"]["order"]:
        t = last.get(side)
        pos = ((t or {}).get("data") or {}).get("position", "— (bloc structuré absent)" if t else "— (n'a pas parlé)")
        out.append(f"- **{side}** ({(t or {}).get('source', '—')}, dernier marqueur {(t or {}).get('marker', '—')}) : {pos}")
    out += ["", "## Points d'accord"] + ([f"- {x}" for x in agreements] or ["- (aucun déclaré)"])
    out += ["", "## Désaccords non résolus"] + ([f"- {x}" for x in disagreements] or ["- aucun"])
    out += ["", "## Questions pour l'utilisateur"] + ([f"- {x}" for x in questions] or ["- aucune"])
    if unstructured:
        out.append(f"- ⚠ réponse(s) sans bloc structuré : {', '.join(unstructured)} — relire le verbatim")
    out += ["", "## Décision proposée", f"{proposal}", "",
            "Le manager ne tranche jamais un désaccord : il présente, l'utilisateur décide (`pmx decide --by human:<nom>`).", "",
            "## Verbatim", *[f"- tour {i + 1} · {t['side']} · {t['marker']} · `ai_memory/runs/{st['run']}/{t['file']}`" for i, t in enumerate(turns)]]
    rel = pathlib.Path("ai_doc") / f"DEBATE__{st['parent_wi']}__{slugify(st['title'])}.md"
    write_atomic(ctx.root / rel, "\n".join(out) + "\n")
    write_atomic(ctx.run_dir(st["run"]) / "debate" / "DEBATE.md", "\n".join(out) + "\n")
    st["debate"]["doc"] = str(rel)
    st["debate"]["proposal"] = proposal
    return rel


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().encode("ascii", "ignore").decode()).strip("-")
    return s[:40] or "topic"


def cmd_decide(ctx, a):
    st = ctx.load_run(a.run)
    dstat = st["debate"]["status"]
    if dstat in ("pending", "running"):
        die("débat non clos")
    if a.by == "consensus" and st["debate"].get("needs_human"):
        die("arbitrage humain requis (désaccords, questions ou absence de consensus) : --by human:<nom> --text …", EXIT_HUMAN)
    if a.by != "consensus" and not a.by.startswith("human:"):
        die("--by consensus | human:<nom>", EXIT_USAGE)
    text = a.text or st["debate"].get("proposal")
    if not text or text == "—":
        die("décision vide : --text requis", EXIT_USAGE)
    with ctx.lock():
        st = ctx.load_run(a.run)
        st["decision"] = {"text": text, "by": a.by, "ts": now(), "debate_status": dstat}
        rel = pathlib.Path("ai_doc") / f"DECISIONS__{st['parent_wi']}.md"
        p = ctx.root / rel
        prev = p.read_text(encoding="utf-8") if p.exists() else f"# Decision log — {st['parent_wi']} — {st['title']}\n"
        write_atomic(p, prev.rstrip() + f"\n\n## {now()} — debate decision\n- Decided by: {a.by}\n- Debate status: {dstat} ({st['debate'].get('doc')})\n- Decision: {text}\n"
                     "- Durable rule proposal: DEC- candidate for `rules-curator` (two-step triage at closure); never written to ai_rules/ by pmx.\n")
        ctx.save_run(st)
    ctx.event(a.run, "decision_recorded", by=a.by)
    print(f"décision enregistrée ({a.by}) → {rel}")
    return EXIT_OK


# ---------------------------------------------------------------- plan

def plan_waves(tasks):
    """Vagues topologiques ; lève ValueError sur dépendance inconnue ou cycle."""
    keys = {t["key"] for t in tasks}
    deps = {t["key"]: set(t.get("depends_on", [])) for t in tasks}
    for k, ds in deps.items():
        if ds - keys:
            raise ValueError(f"{k} dépend de tâches inconnues : {sorted(ds - keys)}")
    waves, done = [], set()
    while len(done) < len(keys):
        w = sorted(k for k in keys - done if deps[k] <= done)
        if not w:
            raise ValueError(f"cycle de dépendances parmi {sorted(keys - done)}")
        waves.append(w)
        done |= set(w)
    return waves


def ancestors(tasks, key):
    deps = {t["key"]: set(t.get("depends_on", [])) for t in tasks}
    seen, stack = set(), list(deps[key])
    while stack:
        k = stack.pop()
        if k not in seen:
            seen.add(k)
            stack += deps[k]
    return seen


def patterns_overlap(p, q):
    if p == q or fnmatch.fnmatch(p, q) or fnmatch.fnmatch(q, p):
        return True
    # globs dans un même répertoire : on reste conservateur
    wild = lambda s: any(c in s for c in "*?[")
    if wild(p) or wild(q):
        dp, dq = p.rsplit("/", 1)[0] if "/" in p else "", q.rsplit("/", 1)[0] if "/" in q else ""
        return dp.startswith(dq) or dq.startswith(dp)
    return False


def validate_plan(ctx, plan):
    errs, tasks = [], plan.get("tasks") or []
    if not tasks:
        errs.append("aucune tâche")
    seen = set()
    for t in tasks:
        for k in ("key", "title", "team", "files", "test_command", "acceptance"):
            if not t.get(k):
                errs.append(f"{t.get('key', '?')} : champ requis manquant : {k}")
        if t.get("key") in seen:
            errs.append(f"clé dupliquée : {t['key']}")
        seen.add(t.get("key"))
        if t.get("key") and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", t["key"]):
            errs.append(f"{t['key']} : clé invalide (minuscules, chiffres, tirets)")
        if t.get("team") and t["team"] not in ctx.o["teams"]:
            errs.append(f"{t['key']} : équipe inconnue {t['team']!r}")
        for f in t.get("files") or []:
            if f.startswith("/") or ".." in f.split("/"):
                errs.append(f"{t['key']} : chemin hors dépôt {f!r}")
            cat = classify(f, ctx.o["sensitive_paths"])
            if cat:
                errs.append(f"{t['key']} : chemin sensible ({cat}) {f!r} — validation humaine hors pilote")
    if errs:
        return errs, None
    try:
        waves = plan_waves(tasks)
    except ValueError as e:
        return [str(e)], None
    # collisions : deux tâches sans relation de dépendance ne partagent aucun fichier
    for i, t in enumerate(tasks):
        for u in tasks[i + 1:]:
            if t["key"] in ancestors(tasks, u["key"]) or u["key"] in ancestors(tasks, t["key"]):
                continue
            hits = [(p, q) for p in t["files"] for q in u["files"] if patterns_overlap(p, q)]
            if hits:
                errs.append(f"collision de fichiers entre {t['key']} et {u['key']} (parallélisables) : {hits}")
    return errs, waves


def cmd_plan(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    if a.action == "submit":
        if not st.get("decision"):
            die("aucune décision enregistrée : `pmx decide` d'abord", EXIT_HUMAN)
        if st.get("plan") and st["plan"].get("status") in ("approved",):
            die("plan déjà approuvé : tout changement exige une re-confirmation (nouveau run)")
        plan = json.loads(pathlib.Path(a.file).read_text(encoding="utf-8"))
        errs, waves = validate_plan(ctx, plan)
        if errs:
            for e in errs:
                print(f"  ✘ {e}")
            return EXIT_FAIL
        with ctx.lock():
            st = ctx.load_run(a.run)
            st["plan"] = {"status": "proposed", "file": f"ai_memory/runs/{a.run}/plan.json", "waves": waves, "submitted": now()}
            write_atomic(ctx.run_dir(a.run) / "plan.json", json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
            ctx.save_run(st)
        ctx.event(a.run, "plan_submitted", waves=waves)
        print_plan(ctx, plan, waves)
        print("\nGate n°1 : aucun work item créé, aucune équipe lancée avant « go » → `pmx plan approve --run … --by <nom>`")
        return EXIT_HUMAN
    if a.action == "approve":
        if not st.get("plan") or st["plan"]["status"] != "proposed":
            die("aucun plan proposé")
        plan = json.loads((ctx.run_dir(a.run) / "plan.json").read_text(encoding="utf-8"))
        with ctx.lock():
            st = ctx.load_run(a.run)
            for t in plan["tasks"]:
                wi = wi_reserve(ctx, t["title"], {
                    "executor": f"{t['team']} ({ctx.o['teams'][t['team']].get('label', ctx.o['teams'][t['team']].get('adapter'))})",
                    "parent": st["parent_wi"], "depends_on": "[]", "files_probably_touched": json.dumps(t["files"]),
                    "links": f"ai_memory/runs/{a.run}/plan.json"})
                st["tasks"][t["key"]] = {"wi": wi, **{k: t[k] for k in ("title", "team", "files", "test_command", "acceptance")},
                                         "depends_on": t.get("depends_on", []), "attempts": [], "commit": None, "verify": None, "review": None}
            for t in plan["tasks"]:
                wi_set(ctx, st["tasks"][t["key"]]["wi"], depends_on=json.dumps([st["tasks"][d]["wi"] for d in t.get("depends_on", [])]))
            st["plan"].update(status="approved", approved_by=a.by, approved=now())
            wi_set(ctx, st["parent_wi"], status="IN_PROGRESS")
            ctx.save_run(st)
        ctx.event(a.run, "plan_approved", by=a.by, tasks={k: v["wi"] for k, v in st["tasks"].items()})
        for k, v in st["tasks"].items():
            print(f"  {v['wi']}  {k}  → {v['team']}")
        return EXIT_OK
    die("plan submit|approve", EXIT_USAGE)


def print_plan(ctx, plan, waves):
    print(f"Plan — {len(plan['tasks'])} tâche(s), {len(waves)} vague(s), parallélisme max {ctx.o['max_parallel']}")
    by = {t["key"]: t for t in plan["tasks"]}
    for i, w in enumerate(waves, 1):
        print(f"  vague {i} : " + " ‖ ".join(f"{k} [{by[k]['team']}]" for k in w))
    for t in plan["tasks"]:
        print(f"  - {t['key']} : {t['title']} · fichiers {t['files']} · dépend de {t.get('depends_on') or '—'}")


# ---------------------------------------------------------------- équipes

def changed_paths(wt, base):
    """Chemins modifiés dans un worktree par rapport à `base` (commités, indexés, non suivis) + suppressions."""
    out, deleted = set(), set()
    for line in git(wt, "status", "--porcelain=v1", "-uall", "--no-renames").splitlines():
        code, path = line[:2], line[3:]
        out.add(path)
        if "D" in code:
            deleted.add(path)
    for line in git(wt, "diff", "--name-status", "--no-renames", f"{base}..HEAD").splitlines():
        s, path = line.split("\t", 1)
        out.add(path)
        if s.startswith("D"):
            deleted.add(path)
    return out, deleted


def scope_check(ctx, task, wt, base):
    """→ (violations critiques, chemins modifiés). Hors périmètre, sensible ou suppression = échec critique."""
    paths, deleted = changed_paths(wt, base)
    allowed = list(task["files"]) + [f"ai_memory/*__ROLE-*__{task['wi']}.md"]
    bad = []
    for p in sorted(paths):
        cat = classify(p, ctx.o["sensitive_paths"])
        if cat:
            bad.append(f"{p} : chemin sensible ({cat})")
        elif p in deleted:
            bad.append(f"{p} : suppression (validation humaine)")
        elif not match_any(p, allowed):
            bad.append(f"{p} : hors périmètre de {task['wi']}")
    return bad, paths


def team_brief(ctx, st, key, attempt, wt, report):
    t = st["tasks"][key]
    if ctx.o["teams"][t["team"]].get("adapter") == "drop":
        where = f"Écris ton rapport dans `{report}` (hors worktree ; seul fichier extérieur autorisé)"
    else:  # Codex/claude -p : la sortie est capturée par l'orchestrateur ; écrire hors du worktree est impossible (sandbox)
        where = "Ton DERNIER MESSAGE est ton rapport (l'orchestrateur le capture) ; n'écris aucun fichier de rapport, ni dans ni hors du worktree"
    role = load_role(ctx, "developer")
    plan = json.loads((ctx.run_dir(st["run"]) / "plan.json").read_text(encoding="utf-8"))
    spec = next(x for x in plan["tasks"] if x["key"] == key)
    shared = "\n".join(f"### {k}\n{v}" for k, v in plan.items() if k != "tasks") or "—"
    return f"""# Brief d'équipe — {t['wi']} ({key}) · tentative {attempt}

Tu es l'équipe **{t['team']}** du pilote multi-agents, rôle **developer** du Project Manager V3 (définition ci-dessous).
Tu travailles SEUL dans ce worktree isolé : `{wt}` (branche `{ctx.o['branch_prefix']}…`, déjà créée). Une autre équipe travaille en parallèle sur d'autres fichiers.

## Work item
- ID : {t['wi']} · parent : {st['parent_wi']} · tier : complex (pilote)
- Objectif : {t['title']}
- Décision issue du débat (à respecter) : {st['decision']['text']}
- Détails : {spec.get('details', '—')}
- Critères d'acceptation : {json.dumps(t['acceptance'], ensure_ascii=False)}

## Contexte commun du plan (contrat figé par le débat — identique pour les deux équipes)
{shared}

## Périmètre — fichiers autorisés (et SEULEMENT eux)
{chr(10).join(f'- `{f}`' for f in t['files'])}
Tout autre fichier modifié, toute suppression, tout chemin sensible (secrets, `.claude/`, hooks, settings, CI) = **échec critique** :
l'orchestrateur arrête les DEUX équipes. Besoin d'un autre fichier → n'y touche pas, signale-le dans ton rapport (BLOCKED).

## Vérification attendue
- Commande : `{t['test_command']}` (depuis la racine du worktree) — colle la sortie dans ton rapport.

## Interdits (en plus du rôle)
- aucun `git commit`, `git push`, `git stash`, `git checkout` d'une autre branche, aucune MR : l'orchestrateur commite après contrôle du périmètre ;
- aucun accès réseau, aucune installation de dépendance, aucune lecture de secret ; ne sors pas de `{wt}`.

## Rapport final (obligatoire)
{where}, au format note de rôle, avec une ligne `Status: DONE` ou `Status: BLOCKED` :
Work item | Role | Status | Scope | Files touched | Evidence (commande + sortie) | Decisions | Open blockers | Next actions | Recall hints | Proposed Rules (optionnel).

---
## Définition du rôle `developer` (agents/developer.md du kit V3, réutilisée telle quelle)
{role}
"""


def load_role(ctx, role):
    here = pathlib.Path(__file__).resolve()
    for p in (ctx.root / ".claude" / "agents" / f"{role}.md", here.parents[3] / "agents" / f"{role}.md",
              here.parents[2] / "agents" / f"{role}.md", pathlib.Path.home() / ".claude" / "agents" / f"{role}.md"):
        if p.exists():
            return re.sub(r"^---\n.*?\n---\n", "", p.read_text(encoding="utf-8"), flags=re.S).strip()
    return f"(définition `{role}` introuvable : appliquer les règles du brief)"


def dispatch_ready(ctx, run):
    """Lance les tâches prêtes (dépendances DONE, équipe libre, slots disponibles). → liste des tâches en attente d'agent externe."""
    st = ctx.load_run(run)
    if not st.get("plan") or st["plan"]["status"] != "approved":
        die("plan non approuvé (gate « go »)", EXIT_HUMAN)
    waiting, launched = [], []
    with ctx.lock():
        st = ctx.load_run(run)
        running = [k for k, t in st["tasks"].items() if wi_status(ctx, t["wi"]) == "IN_PROGRESS"]
        busy = {st["tasks"][k]["team"] for k in running}
        for key in [k for w in st["plan"]["waves"] for k in w]:
            t = st["tasks"][key]
            if wi_status(ctx, t["wi"]) != "OPEN" or len(running) >= ctx.o["max_parallel"] or t["team"] in busy:
                continue
            if any(wi_status(ctx, st["tasks"][d]["wi"]) != "DONE" for d in t["depends_on"]):
                continue
            base = st["base"]
            if t["depends_on"]:  # dépendance satisfaite = intégrée dans la branche d'intégration locale
                base = git(ctx.root, "rev-parse", ctx.o["integration_branch"])
                for d in t["depends_on"]:
                    if subprocess.run(["git", "-C", str(ctx.root), "merge-base", "--is-ancestor", st["tasks"][d]["commit"], base]).returncode != 0:
                        die(f"{key} : dépendance {d} non intégrée dans {ctx.o['integration_branch']}")
            n = len(t["attempts"]) + 1
            branch = f"{ctx.o['branch_prefix']}{run.lower()}/{key}" + (f"-a{n}" if n > 1 else "")
            if ctx.is_protected(branch):
                die(f"branche protégée refusée : {branch}")
            wt = ctx.wt_root / f"{key}-a{n}"
            ctx.wt_root.mkdir(parents=True, exist_ok=True)
            git(ctx.root, "worktree", "add", "-q", "-b", branch, str(wt), base)
            tdir = ctx.run_dir(run) / "tasks" / key
            tdir.mkdir(parents=True, exist_ok=True)
            report = tdir / f"report-a{n}.md"
            brief = tdir / f"brief-a{n}.md"
            write_atomic(brief, team_brief(ctx, st, key, n, wt, report))
            team = ctx.o["teams"][t["team"]]
            att = {"n": n, "branch": branch, "worktree": str(wt), "base": base, "brief": str(brief), "report": str(report),
                   "adapter": team.get("adapter"), "pid": None, "started": now(), "ended": None, "result": None}
            if team.get("adapter") == "drop":
                waiting.append((key, brief, report))
            else:
                log = open(tdir / f"team-a{n}.log", "a")
                p = subprocess.Popen([sys.executable, "-I", str(pathlib.Path(__file__).resolve()), "--root", str(ctx.root), "_team",
                                      "--run", run, "--task", key, "--attempt", str(n)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                att["pid"] = p.pid
            t["attempts"].append(att)
            wi_set(ctx, t["wi"], status="IN_PROGRESS", session=f"{t['team']} ({att['adapter']}, pid {att['pid'] or 'externe'})",
                   worktree=str(wt), attempt_count=len(t["attempts"]) - 1)
            ctx.event(run, "team_started", task=key, wi=t["wi"], team=t["team"], adapter=att["adapter"], pid=att["pid"], attempt=n, branch=branch)
            running.append(key)
            busy.add(t["team"])
            launched.append(key)
        ctx.save_run(st)
    for k in launched:
        print(f"  ▶ {k} lancée")
    return waiting


def cmd_dispatch(ctx, a):
    ctx.require_enabled()
    waiting = dispatch_ready(ctx, a.run)
    if waiting:
        for key, brief, report in waiting:
            print(f"EN ATTENTE — équipe externe pour {key}\n  brief : {brief}\n  rapport attendu : {report}\n"
                  f"  fin : pmx.py --root {ctx.root} report --run {a.run} --task {key} --status done|failed --file {report}")
        return EXIT_WAIT
    return EXIT_OK


def cmd_team(ctx, a):
    """Processus détaché d'une équipe : exécute l'adaptateur et écrit result.json. N'écrit jamais le registre."""
    st = ctx.load_run(a.run)
    t = st["tasks"][a.task]
    att = t["attempts"][int(a.attempt) - 1]
    tdir = ctx.run_dir(a.run) / "tasks" / a.task
    ctx.event(a.run, "team_process_begin", task=a.task, attempt=int(a.attempt))
    started = now()
    rc = run_agent_sync(ctx, ctx.o["teams"][t["team"]], att["brief"], att["report"], att["worktree"], "write",
                        tdir / f"team-a{a.attempt}.log", ctx.o["team_timeout_s"])
    write_atomic(tdir / f"result-a{a.attempt}.json", json.dumps({"exit": rc, "started": started, "ended": now()}) + "\n")
    ctx.event(a.run, "team_process_end", task=a.task, attempt=int(a.attempt), exit=rc)
    return EXIT_OK


def cmd_report(ctx, a):
    st = ctx.load_run(a.run)
    t = st["tasks"].get(a.task) or die(f"tâche inconnue {a.task}")
    att = t["attempts"][-1]
    if att.get("result"):
        die("tentative déjà close")
    src = pathlib.Path(a.file)
    if src.resolve() != pathlib.Path(att["report"]).resolve():
        write_atomic(pathlib.Path(att["report"]), src.read_text(encoding="utf-8"))
    tdir = ctx.run_dir(a.run) / "tasks" / a.task
    write_atomic(tdir / f"result-a{att['n']}.json", json.dumps({"exit": 0 if a.status == "done" else 1, "started": att["started"], "ended": now(), "via": "report"}) + "\n")
    ctx.event(a.run, "team_reported", task=a.task, status=a.status, attempt=att["n"])
    return cmd_tick(ctx, a)


def abort_all(ctx, run, reason):
    """Échec critique : arrête toutes les équipes, passe leurs WI en BLOCKED. Rien n'est supprimé (worktrees gardés comme preuve)."""
    lk = ctx.lock()
    st = ctx.load_run(run)
    stopped = []
    for key, t in st["tasks"].items():
        if wi_status(ctx, t["wi"]) != "IN_PROGRESS":
            continue
        att = t["attempts"][-1]
        if att.get("pid") and pid_alive(att["pid"]):
            try:
                os.killpg(att["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
        write_atomic(ctx.run_dir(run) / "tasks" / key / "STOP", f"{now()} {reason}\n")
        att.update(ended=now(), result="aborted")
        wi_set(ctx, t["wi"], status="BLOCKED", blocker=f"critical stop: {reason}", restore_state="OPEN")
        stopped.append(key)
    time.sleep(1)
    for t in st["tasks"].values():
        pid = t["attempts"][-1].get("pid") if t["attempts"] else None
        if pid and pid_alive(pid):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    ctx.save_run(st)
    lk.close()
    ctx.event(run, "critical_abort", reason=reason, stopped=stopped)
    print(f"⛔ ÉCHEC CRITIQUE — équipes arrêtées : {stopped or 'aucune en cours'} — {reason}")
    drops = [k for k in stopped if st["tasks"][k]["attempts"][-1]["adapter"] == "drop"]
    if drops:
        print(f"   équipes externes {drops} : la session lead doit arrêter le sous-agent correspondant (fichier STOP écrit).")
    return EXIT_CRITICAL


def cmd_tick(ctx, a):
    """Un passage de surveillance : périmètre, collisions inter-équipes, fins de processus, interruptions, tentatives."""
    st = ctx.load_run(a.run)
    seen, critical = {}, []
    with ctx.lock():
        st = ctx.load_run(a.run)
        for key, t in st["tasks"].items():
            if wi_status(ctx, t["wi"]) != "IN_PROGRESS":
                continue
            att = t["attempts"][-1]
            bad, paths = scope_check(ctx, t, att["worktree"], att["base"])
            if bad:
                critical.append(f"{key} : " + "; ".join(bad))
            for p in paths:
                seen.setdefault(p, []).append(key)
        for p, ks in seen.items():
            if len(ks) > 1:
                critical.append(f"collision : {p} modifié par {ks}")
    if critical:
        return abort_all(ctx, a.run, " | ".join(critical))
    rc_out = EXIT_OK
    with ctx.lock():
        st = ctx.load_run(a.run)
        for key, t in st["tasks"].items():
            if wi_status(ctx, t["wi"]) != "IN_PROGRESS":
                continue
            att = t["attempts"][-1]
            resf = ctx.run_dir(a.run) / "tasks" / key / f"result-a{att['n']}.json"
            if resf.exists():
                res = json.loads(resf.read_text(encoding="utf-8"))
                _finish_attempt(ctx, st, key, res)
            elif att["adapter"] != "drop" and not pid_alive(att["pid"]):
                _finish_attempt(ctx, st, key, {"exit": None, "ended": now(), "interrupted": True})
        ctx.save_run(st)
    return rc_out


def _finish_attempt(ctx, st, key, res):
    t, run = st["tasks"][key], st["run"]
    att = t["attempts"][-1]
    att["ended"] = res.get("ended") or now()
    report = pathlib.Path(att["report"])
    rtext = report.read_text(encoding="utf-8") if report.exists() else ""
    ok = res.get("exit") == 0 and not re.search(r"Status\W{0,5}\s*BLOCKED", rtext)
    wt = att["worktree"]
    if ok:
        bad, paths = scope_check(ctx, t, wt, att["base"])
        if bad or not paths:
            ok = False
            att["failure"] = "; ".join(bad) or "aucun changement produit"
    if ok:
        git(wt, "add", "-A", "--", *sorted(paths))
        git(wt, *GIT_ID, "commit", "-q", "-m", f"pilot({t['wi']}): {t['title']}\n\nTeam: {t['team']} ({att['adapter']}), attempt {att['n']}. Committed by pmx after scope check.")
        att.update(result="done", commit=git(wt, "rev-parse", "HEAD"), tree=git(wt, "rev-parse", "HEAD^{tree}"))
        t["commit"], t["tree"], t["branch"] = att["commit"], att["tree"], att["branch"]
        note = role_note(ctx, "developer", t["wi"], f"# developer note — {t['wi']}\n\n- Work item: {t['wi']}\n- Role: developer ({t['team']}, {att['adapter']})\n"
                         f"- Status: READY_FOR_VERIFICATION\n- Files touched: {sorted(paths)}\n- Evidence: commit {att['commit'][:10]}, tree {att['tree'][:10]}, branch {att['branch']}\n"
                         f"- Team report (verbatim, recorded by the lead):\n\n{rtext.strip() or '(empty)'}\n")
        wi_set(ctx, t["wi"], status="READY_FOR_VERIFICATION", links=str(note))
        ctx.event(run, "team_finished", task=key, wi=t["wi"], result="done", commit=att["commit"], files=sorted(paths))
        print(f"  ✔ {key} terminée → commit {att['commit'][:10]}")
        return
    att["result"] = "interrupted" if res.get("interrupted") else "failed"
    bad, paths = scope_check(ctx, t, wt, att["base"]) if pathlib.Path(wt).exists() else ([], set())
    kind, detail, sig, evidence = failure_record(ctx, t, att, res, rtext, bad, paths)
    att.update(failure=sig, failure_kind=kind)
    ctx.event(run, "team_finished", task=key, wi=t["wi"], result=att["result"], reason=sig, attempt=att["n"])
    decide_retry(ctx, st, key, {"attempt": att["n"], "kind": kind, "detail": detail, "signature": sig, "evidence": evidence, "ts": now()})


# ---------------------------------------------------------------- causes d'échec (relances)

# Ce que la normalisation efface : ce qui change d'une tentative à l'autre sans changer la cause.
# Ce qu'elle garde : type d'échec, code de sortie, commande, nom de test, chemins relatifs, texte du message.
NORMALIZERS = [
    (r"\x1b\[[0-9;]*m", ""),                                             # couleurs ANSI
    (r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?", "<ts>"),        # horodatages
    (r"\b[0-9a-f]{7,40}\b", "<sha>"),                                      # commits, arbres
    (r"/\S*?\.worktrees/[a-z0-9-]+?-a\d+", "<worktree>"),                  # worktree propre à la tentative
    (r"/tmp/\S+", "<tmp>"),
    (r"\b(pid|duration_ms|attempt|tentative)\b\s*[:=#]?\s*\d+(?:\.\d+)?", r"\1 <n>"),
    (r"\(\d+(?:\.\d+)?\s?m?s\)", "(<dur>)"),                                  # durées de test
    (r"[`*>|]+", " "),                                                     # mise en forme Markdown (pas `_` : identifiants)
    (r"\s+", " "),
]
STOPWORDS = {"status", "blocked", "done", "failed", "with", "that", "this", "only", "file", "from", "were", "have", "been",
             "pour", "dans", "avec", "sans", "les", "des", "une", "est", "pas", "the", "and", "not", "but", "was"}
NEAR_REPEAT = 0.5  # recouvrement minimal des mots-clés pour deux explications rédigées par un agent


def normalize_cause(text):
    t = (text or "").lower()
    for pat, sub in NORMALIZERS:
        t = re.sub(pat, sub, t)
    return t.strip(" .;:-—")[:240]


def report_blocker(rtext):
    """Motif déclaré par l'équipe : ligne Status (hors « DONE ») + lignes Open blockers, sinon première ligne utile."""
    lines = [l for l in rtext.splitlines() if l.strip()]
    keep = [l for l in lines if re.search(r"status\W*\s*(blocked|failed)|open blockers", l, re.I)]
    return " | ".join(keep or lines[:1])


def failure_record(ctx, t, att, res, rtext, bad, paths):
    """→ (kind, detail, signature, preuves). `kind` est structurel ; `detail` est normalisé."""
    if res.get("interrupted"):
        kind, detail = "interrupted", ""
    elif res.get("exit") == 124:
        kind, detail = "timeout", ""
    elif bad:
        kind, detail = "scope", "; ".join(bad)
    elif res.get("exit") not in (0, None):
        log = pathlib.Path(att["report"]).parent / f"team-a{att['n']}.log"
        last = next((l for l in reversed((log.read_text(encoding="utf-8", errors="replace") if log.exists() else "").splitlines())
                     if re.search(r"error|erreur|failed|not ok|denied|refus", l, re.I)), "")
        kind, detail = f"exit-{res.get('exit')}", report_blocker(rtext) or last
    elif re.search(r"Status\W{0,5}\s*BLOCKED", rtext):
        kind, detail = "reported-blocked", report_blocker(rtext)
    else:
        kind, detail = "no-changes", ""
    detail = normalize_cause(detail)
    evidence = {"exit": res.get("exit"), "changed_files": sorted(paths), "report_excerpt": tail(rtext, 15),
                "report": att["report"], "log": str(pathlib.Path(att["report"]).parent / f"team-a{att['n']}.log")}
    return kind, detail, f"{kind}: {detail}" if detail else kind, evidence


def keywords(detail):
    """Mots de prose (comparés de façon floue) et identifiants (noms de test, chemins, valeurs : comparés à l'identique)."""
    toks = re.findall(r"[\wà-ÿ./-]+", detail)
    ids = {w.strip(".-") for w in toks if re.search(r"[0-9_/]|\w\.\w", w)}
    words = {w for w in toks if w not in ids and re.fullmatch(r"[a-zà-ÿ]{4,}", w) and w not in STOPWORDS}
    return words, ids


def same_cause(a, b):
    """Même cause ? Exacte sur la signature ; « proche » seulement pour un motif rédigé par un agent, et seulement si
    le type, le code de sortie et les fichiers produits sont identiques (une différence objective n'est jamais masquée)."""
    # une différence objective n'est jamais masquée : code de sortie, fichiers produits (sauf travail partiel interrompu)
    if a["evidence"]["exit"] != b["evidence"]["exit"]:
        return False, 0.0
    if a["kind"] not in ("interrupted", "timeout") and a["evidence"]["changed_files"] != b["evidence"]["changed_files"]:
        return False, 0.0
    if a["signature"] == b["signature"]:
        return True, 1.0
    agent_text = a["kind"] == "reported-blocked" or a["kind"].startswith("exit-")
    if a["kind"] != b["kind"] or not agent_text:
        return False, 0.0
    (ka, ia), (kb, ib) = keywords(a["detail"]), keywords(b["detail"])
    if ia != ib:
        return False, 0.0
    score = len(ka & kb) / len(ka | kb) if ka | kb else 1.0
    return score >= NEAR_REPEAT, round(score, 2)


def decide_retry(ctx, st, key, rec):
    """Applique la politique de relance à un échec enregistré. Relance automatique seulement si : budget non épuisé,
    `auto_retry`, et cause jamais vue depuis la dernière décision humaine. Sinon ESCALATED (ou BLOCKED), dossier écrit."""
    t, run = st["tasks"][key], st["run"]
    history = [x for x in t.setdefault("failures", []) if x["attempt"] > t.get("budget_base", 0)]
    repeat = None
    for prev in history:
        hit, score = same_cause(prev, rec)
        if hit:
            repeat = (prev, score)
            break
    t["failures"].append(rec)
    tries = len(t["attempts"]) - t.get("budget_base", 0)
    if repeat:
        why = f"same cause repeated (attempts {repeat[0]['attempt']} and {rec['attempt']}, match {repeat[1]}): {rec['signature']}"
        status = "ESCALATED"
    elif tries >= ctx.o["max_attempts"]:
        why, status = f"{tries} attempts failed (cap {ctx.o['max_attempts']}): {rec['signature']}", "ESCALATED"
    elif ctx.o["auto_retry"]:
        why, status = f"attempt {tries} failed: {rec['signature']} (new cause, retry allowed)", "OPEN"
    else:
        why, status = rec["signature"], "BLOCKED"
    fields = {"status": status, "attempt_count": tries, "blocker": why}
    if status == "BLOCKED":
        fields["restore_state"] = "OPEN"
    if status != "OPEN":
        fields["links"] = str(escalation_file(ctx, st, key, why))
    wi_set(ctx, t["wi"], **fields)
    ctx.event(run, "retry_decision", task=key, attempt=rec["attempt"], decision=status, signature=rec["signature"],
              repeat_of=repeat[0]["attempt"] if repeat else None, match=repeat[1] if repeat else None)
    icon = {"OPEN": "↻", "ESCALATED": "⛔", "BLOCKED": "✘"}[status]
    print(f"  {icon} {key} → {status} : {why}")
    return status


def escalation_file(ctx, st, key, why):
    """Dossier d'escalade (« present history and evidence ») : toutes les tentatives, leur signature, leurs preuves."""
    t = st["tasks"][key]
    rel = pathlib.Path("ai_doc") / f"ESCALATION__{t['wi']}.md"
    out = [f"# Escalation — {t['wi']} — {t['title']}", "", f"Date: {now()} · Decision: {why}",
           "Automatic retries stopped. Only a human decision reopens this work item (`pmx reopen --by human:<name> --reason …`).", "",
           "| Attempt | Kind | Signature | Exit | Files produced | Report / log |", "|---|---|---|---|---|---|"]
    for f in t.get("failures", []):
        out.append(f"| {f['attempt']} | {f['kind']} | {f['signature'][:120]} | {f['evidence']['exit']} | {', '.join(f['evidence']['changed_files']) or '—'} | {f['evidence']['report']} · {f['evidence']['log']} |")
    for f in t.get("failures", []):
        out += ["", f"## Attempt {f['attempt']} — report excerpt", "```", f["evidence"]["report_excerpt"] or "(empty)", "```"]
    write_atomic(ctx.root / rel, "\n".join(out) + "\n")
    return rel


def cmd_wait(ctx, a):
    ctx.require_enabled()
    deadline = time.time() + (a.timeout or ctx.o["team_timeout_s"] + 60)
    while True:
        rc = cmd_tick(ctx, a)
        if rc == EXIT_CRITICAL:
            return rc
        waiting = dispatch_ready(ctx, a.run)  # relances autorisées et tâches débloquées
        st = ctx.load_run(a.run)
        active = [k for k, t in st["tasks"].items() if wi_status(ctx, t["wi"]) == "IN_PROGRESS"]
        procs = [k for k in active if st["tasks"][k]["attempts"][-1]["adapter"] != "drop"]
        if not procs:
            if active or waiting:
                print(f"en attente d'équipes externes : {active}")
                return EXIT_WAIT
            return EXIT_OK
        if time.time() > deadline:
            return abort_all(ctx, a.run, f"délai d'attente dépassé ({a.timeout}s)")
        time.sleep(a.interval)


# ---------------------------------------------------------------- vérification indépendante (rôle verifier, mécanisé)

def run_checks(ctx, wt, commands, timeout):
    results = []
    for c in commands:
        t0 = time.time()
        try:
            p = subprocess.run(c, shell=True, cwd=str(wt), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            rc, out = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired:
            rc, out = 124, f"TIMEOUT {timeout}s"
        results.append({"command": c, "exit": rc, "seconds": round(time.time() - t0, 2), "output": tail(out)})
    return results


def cmd_verify(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    keys = [a.task] if a.task else [k for k, t in st["tasks"].items() if wi_status(ctx, t["wi"]) == "READY_FOR_VERIFICATION"]
    worst = EXIT_OK
    for key in keys:
        t = st["tasks"][key]
        vdir = ctx.wt_root / f"_verify-{key}-{t['commit'][:8]}"
        if vdir.exists():
            die(f"checkout de vérification déjà présent : {vdir}")
        git(ctx.root, "worktree", "add", "-q", "--detach", str(vdir), t["commit"])
        cmds = [t["test_command"]] + [c for c in ctx.o["verify_commands"] if c != t["test_command"]]
        res = run_checks(ctx, vdir, cmds, ctx.o["verify_timeout_s"])
        dirty = git(vdir, "status", "--porcelain")
        verdict = "PASS" if all(r["exit"] == 0 for r in res) else "FAIL"
        rm = subprocess.run(["git", "-C", str(ctx.root), "worktree", "remove", str(vdir)], capture_output=True, text=True)
        ev = "\n".join(f"$ {r['command']}  → exit {r['exit']} ({r['seconds']}s)\n{r['output']}" for r in res)
        note = role_note(ctx, "verifier", t["wi"], f"# verifier note — {t['wi']}\n\n- Work item: {t['wi']}\n- Role: verifier (pmx, clean detached checkout of {t['commit'][:10]}, tree {t['tree'][:10]})\n"
                         f"- Status: {verdict}\n- Commands run: {cmds}\n- Checkout left dirty by tests: {'yes' if dirty else 'no'}; removed: {'yes' if rm.returncode == 0 else 'no — ' + rm.stderr.strip()}\n"
                         f"- Evidence:\n```\n{ev}\n```\n- Next actions: {'cross review' if verdict == 'PASS' else 'developer (new attempt)'}\n")
        with ctx.lock():
            st = ctx.load_run(a.run)
            st["tasks"][key]["verify"] = {"verdict": verdict, "commit": t["commit"], "tree": t["tree"], "ts": now(), "note": str(note), "results": res}
            if verdict == "PASS":
                wi_set(ctx, t["wi"], status="READY_FOR_REVIEW", links=str(note))
            else:
                first = next((r for r in res if r["exit"] != 0), res[0])
                err = next((l for l in first["output"].splitlines() if re.search(r"not ok|error|assert|fail", l, re.I)), "")
                detail = normalize_cause(f"{first['command']} → exit {first['exit']} :: {err}")
                st["tasks"][key]["attempts"][-1]["failure"] = f"verifier-fail: {detail}"
                decide_retry(ctx, st, key, {"attempt": len(t["attempts"]), "kind": "verifier-fail", "detail": detail, "signature": f"verifier-fail: {detail}",
                                            "evidence": {"exit": first["exit"], "changed_files": [], "report_excerpt": first["output"][-1500:],
                                                         "report": str(note), "log": str(note)}, "ts": now()})
                worst = EXIT_FAIL
            ctx.save_run(st)
        ctx.event(a.run, "verified", task=key, verdict=verdict, commit=t["commit"])
        print(f"  {'✔' if verdict == 'PASS' else '✘'} {key} : verifier {verdict} ({t['commit'][:10]})")
    return worst


# ---------------------------------------------------------------- revue croisée (I2, lecture seule)

REVIEW_PROMPT = """Tu es reviewer pour le pilote multi-agents (revue croisée entre équipes). LECTURE SEULE : tu ne modifies aucun fichier, tu ne corriges rien.
Dépôt : {root}. Checkout détaché du commit revu (pour lire le code et lancer `{test}`) : {checkout}. Work item revu : {wi} — {title}. Produit par l'équipe {team} ; tu appartiens à l'autre équipe.
Décision d'architecture à respecter : {decision}
Critères d'acceptation : {acceptance}
Périmètre autorisé : {files}

Diff (base..commit {commit}) :
```diff
{diff}
```

Rends : constats classés Blocker / Major / Minor / Trivial (fichier:ligne, problème, risque, suggestion), puis le respect de chaque critère d'acceptation.
Termine SEULE sur la dernière ligne par exactement : `VERDICT: APPROVE` ou `VERDICT: CHANGES_REQUESTED` (CHANGES_REQUESTED seulement s'il existe un Blocker ou un Major).
"""


def cmd_review(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    if a.action == "submit":
        return _record_review(ctx, a.run, a.task, pathlib.Path(a.file).read_text(encoding="utf-8"), source="drop")
    rdir = ctx.run_dir(a.run) / "reviews"
    rdir.mkdir(parents=True, exist_ok=True)
    teams = list(ctx.o["teams"])
    waiting = []
    for key, t in st["tasks"].items():
        if wi_status(ctx, t["wi"]) != "READY_FOR_REVIEW" or (t.get("review") and t["review"]["commit"] == t["commit"]):
            continue
        reviewer = ctx.o["cross_review"].get(t["team"]) or next((x for x in teams if x != t["team"]), t["team"])
        acfg = ctx.o["teams"][reviewer].get("reviewer") or ctx.o["teams"][reviewer]
        diff = git(ctx.root, "diff", f"{t['attempts'][-1]['base']}..{t['commit']}")
        pf, of = rdir / f"{key}.prompt.md", rdir / f"{key}.answer.md"
        cdir = ctx.wt_root / f"_review-{key}-{t['commit'][:8]}"
        if not cdir.exists():
            git(ctx.root, "worktree", "add", "-q", "--detach", str(cdir), t["commit"])
        write_atomic(pf, REVIEW_PROMPT.format(root=ctx.root, checkout=cdir, test=t["test_command"], wi=t["wi"], title=t["title"], team=t["team"], decision=st["decision"]["text"],
                                              acceptance=json.dumps(t["acceptance"], ensure_ascii=False), files=t["files"], commit=t["commit"][:10], diff=diff))
        ctx.event(a.run, "review_requested", task=key, reviewer=reviewer, adapter=acfg.get("adapter"))
        rc = run_agent_sync(ctx, acfg, pf, of, cdir, "read", rdir / "agents.log", ctx.o["team_timeout_s"])
        if rc is None:
            waiting.append((key, reviewer, pf))
            continue
        if rc != 0 or not of.exists():
            print(f"  ✘ revue de {key} par {reviewer} en échec (code {rc}) — voir {rdir / 'agents.log'}")
            continue
        _record_review(ctx, a.run, key, of.read_text(encoding="utf-8"), source=f"{reviewer}:{acfg.get('adapter')}")
    for key, reviewer, pf in waiting:
        print(f"EN ATTENTE — revue de {key} par {reviewer} (agent externe, lecture seule)\n  prompt : {pf}\n"
              f"  pmx.py --root {ctx.root} review submit --run {a.run} --task {key} --file <fichier>")
    return EXIT_WAIT if waiting else EXIT_OK


def _record_review(ctx, run, key, text, source):
    m = re.search(r"VERDICT:\s*(APPROVE|CHANGES_REQUESTED)\s*`?\s*$", text.strip())
    verdict = m.group(1) if m else "UNPARSEABLE"
    with ctx.lock():
        st = ctx.load_run(run)
        t = st["tasks"][key]
        n = len(list((ctx.root / "ai_doc" / "reviews").glob(f"PEER__{t['wi']}__*.md"))) + 1 if (ctx.root / "ai_doc" / "reviews").exists() else 1
        rel = pathlib.Path("ai_doc") / "reviews" / f"PEER__{t['wi']}__{n}.md"
        write_atomic(ctx.root / rel, f"# Peer review — {t['wi']} — {t['title']}\n\nReviewer: {source} · Commit: {t['commit']} · Date: {now()} · Verdict: **{verdict}**\n\n{text.strip()}\n")
        t["review"] = {"verdict": verdict, "by": source, "commit": t["commit"], "file": str(rel), "ts": now()}
        ctx.save_run(st)
    cdir = ctx.wt_root / f"_review-{key}-{t['commit'][:8]}"
    if cdir.exists():  # checkout propre créé par pmx ; non forcé : s'il a été modifié, il reste et c'est signalé
        rm = subprocess.run(["git", "-C", str(ctx.root), "worktree", "remove", str(cdir)], capture_output=True, text=True)
        if rm.returncode != 0:
            print(f"  ⚠ checkout de revue modifié, conservé : {cdir}")
    ctx.event(run, "reviewed", task=key, verdict=verdict, by=source)
    print(f"  {'✔' if verdict == 'APPROVE' else '⚠'} {key} : revue {verdict} ({source}) → {rel}  — triage manager (review-triage.md)")
    return EXIT_OK if verdict == "APPROVE" else EXIT_HUMAN


# ---------------------------------------------------------------- intégration locale contrôlée

def cmd_integrate(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    target = ctx.o["integration_branch"]
    checks, fail = [], []
    def c(ok, label):
        checks.append(("✔" if ok else "✘") + " " + label)
        if not ok:
            fail.append(label)
    pol_p = ctx.root / ctx.o["integration_policy"]
    pol = json.loads(pol_p.read_text(encoding="utf-8")) if pol_p.exists() else {}
    c(bool(pol), f"politique explicite présente ({ctx.o['integration_policy']})")
    c(pol.get("mode") == "local-only", "politique : mode local-only")
    c(pol.get("target_branch") == target, f"politique : cible = {target}")
    c(not ctx.is_protected(target), f"cible non protégée ({target})")
    upstream = subprocess.run(["git", "-C", str(ctx.root), "rev-parse", "--abbrev-ref", f"{target}@{{upstream}}"], capture_output=True, text=True)
    c(upstream.returncode != 0, "cible sans branche amont (aucun push possible par pmx, qui n'en contient aucun)")
    if not a.dry_run:
        c(bool(a.approved_by), "accord humain explicite (--approved-by)")
    # intégration par vague : les tâches prêtes (READY_FOR_REVIEW) dont les dépendances sont déjà intégrées (DONE)
    keys = [k for w in st["plan"]["waves"] for k in w if wi_status(ctx, st["tasks"][k]["wi"]) == "READY_FOR_REVIEW"]
    c(bool(keys), "au moins une tâche READY_FOR_REVIEW")
    for k in keys:
        t = st["tasks"][k]
        c(all(wi_status(ctx, st["tasks"][d]["wi"]) == "DONE" for d in t["depends_on"]), f"{k} : dépendances intégrées")
        c((t.get("verify") or {}).get("verdict") == "PASS" and t["verify"]["commit"] == t["commit"], f"{k} : verifier PASS sur le commit livré")
        if "APPROVE" in pol.get("require_review_verdict", ["APPROVE"]):
            c((t.get("review") or {}).get("verdict") == "APPROVE" and t["review"]["commit"] == t["commit"], f"{k} : revue croisée APPROVE")
        if t.get("commit"):
            names = git(ctx.root, "diff", "--name-only", f"{t['attempts'][-1]['base']}..{t['commit']}").split()
            outside = [n for n in names if not match_any(n, pol.get("path_allowlist", []))]
            c(not outside, f"{k} : chemins dans l'allow-list de la politique {outside or ''}")
    print("\n".join(checks))
    if fail:
        ctx.event(a.run, "integration_refused", failed=fail)
        print("intégration REFUSÉE — rien n'a été modifié")
        return EXIT_HUMAN if fail == ["accord humain explicite (--approved-by)"] else EXIT_FAIL
    exists = subprocess.run(["git", "-C", str(ctx.root), "rev-parse", "--verify", "-q", f"refs/heads/{target}"], capture_output=True, text=True)
    old = exists.stdout.strip() if exists.returncode == 0 else None
    start = old or st["base"]
    iwt = ctx.wt_root / f"_integration-{int(time.time())}"
    git(ctx.root, "worktree", "add", "-q", "--detach", str(iwt), start)
    merged = []
    try:
        for k in keys:
            t = st["tasks"][k]
            p = subprocess.run(["git", "-C", str(iwt), *GIT_ID, "merge", "--no-ff", "--no-edit", "-m", f"pilot: integrate {t['wi']} ({k})", t["commit"]], capture_output=True, text=True)
            if p.returncode != 0:
                subprocess.run(["git", "-C", str(iwt), "merge", "--abort"], capture_output=True)
                ctx.event(a.run, "integration_conflict", task=k)
                print(f"✘ conflit à l'intégration de {k} — {target} inchangée ; arbitrage humain\n{tail(p.stdout + p.stderr, 20)}")
                return EXIT_HUMAN
            merged.append(k)
        cmds = list(dict.fromkeys(ctx.o["verify_commands"] + [st["tasks"][k]["test_command"] for k in keys]))
        res = run_checks(ctx, iwt, cmds, ctx.o["verify_timeout_s"])
        new, tree = git(iwt, "rev-parse", "HEAD"), git(iwt, "rev-parse", "HEAD^{tree}")
        verdict = "PASS" if all(r["exit"] == 0 for r in res) else "FAIL"
        for r in res:
            print(f"  $ {r['command']} → exit {r['exit']}")
        if verdict != "PASS" or a.dry_run:
            ctx.event(a.run, "integration_dry_run" if a.dry_run else "integration_failed", verdict=verdict, candidate=new)
            print(f"{'simulation' if a.dry_run else 'ÉCHEC des tests'} : candidat {new[:10]} (tree {tree[:10]}) — {target} inchangée")
            return EXIT_OK if (a.dry_run and verdict == "PASS") else EXIT_FAIL
        # mise à jour atomique et conditionnelle de la seule branche d'intégration locale
        git(ctx.root, "update-ref", "-m", f"pmx integrate {a.run} approved-by {a.approved_by}", f"refs/heads/{target}", new, old or "")
    finally:
        subprocess.run(["git", "-C", str(ctx.root), "worktree", "remove", "--force", str(iwt)], capture_output=True)
    with ctx.lock():
        st = ctx.load_run(a.run)
        st.setdefault("integrations", []).append({"target": target, "commit": new, "merged": merged, "approved_by": a.approved_by, "ts": now()})
        st["integration"] = {"target": target, "previous": old, "commit": new, "tree": tree, "approved_by": a.approved_by, "ts": now(), "results": res, "merged": merged}
        for k in merged:
            wi_set(ctx, st["tasks"][k]["wi"], status="DONE", integrated=f"{target}@{new[:10]}", blocker="—")
        if all(wi_status(ctx, t["wi"]) == "DONE" for t in st["tasks"].values()):
            wi_set(ctx, st["parent_wi"], status="READY_FOR_REVIEW", integrated=f"{target}@{new[:10]} (local; merge to {st['base_branch']} is human-only)")
        ctx.save_run(st)
        p = ctx.root / "ai_doc" / f"DECISIONS__{st['parent_wi']}.md"
        prev = p.read_text(encoding="utf-8") if p.exists() else f"# Decision log — {st['parent_wi']}\n"
        write_atomic(p, prev.rstrip() + f"\n\n## {now()} — local integration\n- Approved by: {a.approved_by}\n- Target: {target} {old[:10] if old else '(new)'} → {new[:10]} (tree {tree[:10]})\n- Merged: {merged}\n- Tests on merged tree: {verdict}\n- Rollback: `git update-ref refs/heads/{target} {old or '<delete branch by hand>'} {new}`\n")
    ctx.event(a.run, "integrated", target=target, commit=new, previous=old, approved_by=a.approved_by, merged=merged)
    print(f"✔ intégré dans {target} : {(old or 'nouvelle')[:10]} → {new[:10]} · aucune fusion vers {st['base_branch']} (humaine uniquement)")
    return EXIT_OK


# ---------------------------------------------------------------- état, preuves, reprise

def cmd_status(ctx, a):
    st = ctx.load_run(a.run)
    pw = wi_get(ctx, st["parent_wi"])
    wts = git(ctx.root, "worktree", "list", "--porcelain")
    evs = ctx.events(a.run)
    print(f"## État des équipes — {now()}  · run {a.run} · {st['title']}")
    print(f"Parent : {st['parent_wi']} {pw.get('status')} · débat : {st['debate']['status']} · décision : {(st.get('decision') or {}).get('by', 'aucune')} · plan : {(st.get('plan') or {}).get('status', 'aucun')}")
    print("\n### Coordination fonctionnelle (registre)")
    print("| WI | Tâche | Statut | Dépendances | Preuve | verifier | revue | Blocage | Prochaine étape |\n|---|---|---|---|---|---|---|---|---|")
    nxt = {"OPEN": "dispatch", "IN_PROGRESS": "wait / report", "READY_FOR_VERIFICATION": "verify", "READY_FOR_REVIEW": "review / integrate (accord humain)",
           "BLOCKED": "arbitrage humain", "ESCALATED": "arbitrage humain", "DONE": "—"}
    for k, t in st["tasks"].items():
        w = wi_get(ctx, t["wi"])
        deps = ", ".join(f"{d}:{wi_status(ctx, st['tasks'][d]['wi'])}" for d in t["depends_on"]) or "—"
        proof = f"commit {t['commit'][:10]} tree {t['tree'][:10]}" if t.get("commit") else "aucune"
        print(f"| {t['wi']} | {k} | {w.get('status')} | {deps} | {proof} | {(t.get('verify') or {}).get('verdict', '—')} | {(t.get('review') or {}).get('verdict', '—')} | {w.get('blocker', '—')} | {nxt.get(w.get('status'), '?')} |")
    print("\n### Orchestration technique (exécution des équipes)")
    print("| Tâche | Équipe | Branche | Worktree (git worktree list) | Activité (observation datée) | Tentatives |\n|---|---|---|---|---|---|")
    for k, t in st["tasks"].items():
        if not t["attempts"]:
            print(f"| {k} | {t['team']} | — | — | inconnu (non lancée) | 0 |")
            continue
        att = t["attempts"][-1]
        listed = "présent" if f"worktree {att['worktree']}" in wts else "absent"
        if att.get("pid"):
            act = f"pid {att['pid']} {'vivant' if pid_alive(att['pid']) else 'terminé'} à {now()}"
        else:
            last = next((e["ts"] for e in reversed(evs) if e.get("task") == k), None)
            act = f"externe — dernier événement {last}" if not att.get("ended") else f"terminé {att['ended']}"
        print(f"| {k} | {t['team']} ({att['adapter']}) | {att['branch']} | {listed} | {act} | {len(t['attempts'])} (budget {len(t['attempts']) - t.get('budget_base', 0)}/{ctx.o['max_attempts']}) |")
    if st.get("integration"):
        i = st["integration"]
        print(f"\nIntégration locale : {i['target']} → {i['commit'][:10]} (accord {i['approved_by']}, {i['ts']})")
    print("\nMode d'orchestration : pmx (pilote) — équipes lancées par la session lead ; aucun push, aucune MR, aucune fusion vers une branche protégée.")
    return EXIT_OK


def intervals(evs):
    """Intervalles d'exécution par tentative : début = lancement ; fin = fin du processus / rapport (sinon passage de surveillance)."""
    iv = {}
    for e in evs:
        k = (e.get("task"), e.get("attempt", 1))
        if e["event"] == "team_started":
            iv[k] = [parse_ts(e["ts"]), None, e.get("pid"), e.get("adapter")]
        elif e["event"] in ("team_process_end", "team_reported") and k in iv:
            iv[k][1] = parse_ts(e["ts"])
        elif e["event"] == "team_finished" and k in iv and iv[k][1] is None:
            iv[k][1] = parse_ts(e["ts"])
    return iv


def cmd_evidence(ctx, a):
    evs = ctx.events(a.run)
    rows = [(f"{k}#a{n}", s, f, pid, ad) for (k, n), (s, f, pid, ad) in intervals(evs).items()]
    print("| Tâche | Adaptateur | PID | Début | Fin | Durée (s) |\n|---|---|---|---|---|---|")
    for k, s, f, pid, ad in rows:
        print(f"| {k} | {ad} | {pid or 'externe'} | {s.isoformat()} | {f.isoformat() if f else '—'} | {round((f - s).total_seconds(), 1) if f else '—'} |")
    overlaps = []
    for i, (k1, s1, f1, *_r) in enumerate(rows):
        for k2, s2, f2, *_q in rows[i + 1:]:
            if f1 and f2 and k1.split("#")[0] != k2.split("#")[0]:
                ov = (min(f1, f2) - max(s1, s2)).total_seconds()
                overlaps.append((k1, k2, ov))
    print()
    for k1, k2, ov in overlaps:
        print(f"Chevauchement {k1} ‖ {k2} : {round(ov, 1)} s → {'PARALLÈLE' if ov > 0 else 'séquentiel'}")
    out = {"tasks": [{"task": k, "adapter": ad, "pid": pid, "start": s.isoformat(), "end": f.isoformat() if f else None} for k, s, f, pid, ad in rows],
           "overlaps": [{"a": k1, "b": k2, "seconds": ov} for k1, k2, ov in overlaps]}
    write_atomic(ctx.run_dir(a.run) / "parallelism.json", json.dumps(out, indent=2) + "\n")
    return EXIT_OK if any(ov > 0 for *_x, ov in overlaps) else EXIT_FAIL


def cmd_resume(ctx, a):
    """Reprise après interruption (I7) : fichiers existants seulement ; une équipe morte sans résultat = tentative interrompue."""
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    print(f"Reprise du run {a.run} — débat {st['debate']['status']}, décision {'oui' if st.get('decision') else 'non'}, plan {(st.get('plan') or {}).get('status', 'aucun')}")
    if st["debate"]["status"] in ("pending", "running"):
        print("→ prochaine action : `debate next`")
        return EXIT_OK
    if not st.get("decision"):
        print("→ prochaine action : `decide`")
        return EXIT_HUMAN
    if not st.get("plan") or st["plan"]["status"] != "approved":
        print("→ prochaine action : `plan submit` / `plan approve` (gate « go »)")
        return EXIT_HUMAN
    rc = cmd_tick(ctx, a)
    if rc == EXIT_CRITICAL:
        return rc
    st = ctx.load_run(a.run)
    for k, t in st["tasks"].items():
        print(f"  {k} {t['wi']} : {wi_status(ctx, t['wi'])}")
    return cmd_status(ctx, a)


def cmd_reopen(ctx, a):
    """Décision humaine sur un WI BLOCKED/ESCALATED : rouvre avec un nouveau budget de tentatives (historique conservé)."""
    if not a.by.startswith("human:"):
        die("--by human:<nom> requis : seule une décision humaine lève une escalade", EXIT_USAGE)
    with ctx.lock():
        st = ctx.load_run(a.run)
        t = st["tasks"].get(a.task) or die(f"tâche inconnue {a.task}")
        cur = wi_status(ctx, t["wi"])
        if cur not in ("BLOCKED", "ESCALATED"):
            die(f"{t['wi']} est {cur} : seule une tâche BLOCKED/ESCALATED se rouvre")
        t["budget_base"] = len(t["attempts"])
        wi_set(ctx, t["wi"], status="OPEN", blocker=f"reopened by {a.by}: {a.reason}")
        ctx.save_run(st)
        p = ctx.root / "ai_doc" / f"DECISIONS__{st['parent_wi']}.md"
        prev = p.read_text(encoding="utf-8") if p.exists() else f"# Decision log — {st['parent_wi']}\n"
        write_atomic(p, prev.rstrip() + f"\n\n## {now()} — reopen {t['wi']} ({a.task}) after {cur}\n- Decided by: {a.by}\n- Reason: {a.reason}\n- Previous attempts kept: {len(t['attempts'])}; new attempt budget: {ctx.o['max_attempts']}\n")
    ctx.event(a.run, "task_reopened", task=a.task, by=a.by, reason=a.reason)
    print(f"{t['wi']} rouvert ({a.by}) — `dispatch` pour relancer")
    return EXIT_OK


def cmd_abort(ctx, a):
    return abort_all(ctx, a.run, a.reason or "arrêt demandé")


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog="pmx", description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor")
    p = sp.add_parser("start"); p.add_argument("--title", required=True); p.add_argument("--request", required=True)
    p = sp.add_parser("debate"); p.add_argument("action", choices=["next", "submit", "show"]); p.add_argument("--run", required=True)
    p.add_argument("--side"); p.add_argument("--file")
    p = sp.add_parser("decide"); p.add_argument("--run", required=True); p.add_argument("--by", required=True); p.add_argument("--text")
    p = sp.add_parser("plan"); p.add_argument("action", choices=["submit", "approve"]); p.add_argument("--run", required=True)
    p.add_argument("--file"); p.add_argument("--by")
    for name in ("dispatch", "tick", "status", "evidence", "resume"):
        sp.add_parser(name).add_argument("--run", required=True)
    p = sp.add_parser("wait"); p.add_argument("--run", required=True); p.add_argument("--timeout", type=int); p.add_argument("--interval", type=float, default=2.0)
    p = sp.add_parser("report"); p.add_argument("--run", required=True); p.add_argument("--task", required=True)
    p.add_argument("--status", choices=["done", "failed"], required=True); p.add_argument("--file", required=True)
    p = sp.add_parser("verify"); p.add_argument("--run", required=True); p.add_argument("--task")
    p = sp.add_parser("review"); p.add_argument("action", choices=["run", "submit"]); p.add_argument("--run", required=True)
    p.add_argument("--task"); p.add_argument("--file")
    p = sp.add_parser("integrate"); p.add_argument("--run", required=True); p.add_argument("--approved-by"); p.add_argument("--dry-run", action="store_true")
    p = sp.add_parser("abort"); p.add_argument("--run", required=True); p.add_argument("--reason")
    p = sp.add_parser("reopen"); p.add_argument("--run", required=True); p.add_argument("--task", required=True)
    p.add_argument("--by", required=True); p.add_argument("--reason", required=True)
    p = sp.add_parser("_team"); p.add_argument("--run", required=True); p.add_argument("--task", required=True); p.add_argument("--attempt", required=True)
    a = ap.parse_args(argv)
    ctx = Ctx(a.root)
    if a.cmd == "plan" and a.action == "approve" and not a.by:
        die("--by <nom> requis (accord humain explicite)", EXIT_USAGE)
    if a.cmd == "debate" and a.action == "submit" and not (a.side and a.file):
        die("debate submit --side … --file …", EXIT_USAGE)
    if a.cmd == "review" and a.action == "submit" and not (a.task and a.file):
        die("review submit --task … --file …", EXIT_USAGE)
    fn = {"doctor": cmd_doctor, "start": cmd_start, "debate": cmd_debate, "decide": cmd_decide, "plan": cmd_plan, "dispatch": cmd_dispatch,
          "tick": cmd_tick, "wait": cmd_wait, "report": cmd_report, "verify": cmd_verify, "review": cmd_review, "integrate": cmd_integrate,
          "status": cmd_status, "evidence": cmd_evidence, "resume": cmd_resume, "abort": cmd_abort, "reopen": cmd_reopen, "_team": cmd_team}[a.cmd]
    return fn(ctx, a)


if __name__ == "__main__":
    sys.exit(main())
