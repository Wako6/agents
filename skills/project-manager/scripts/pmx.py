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
import argparse, datetime, fcntl, fnmatch, hashlib, json, os, pathlib, re, shlex, shutil, signal, subprocess, sys, time, urllib.parse

SCHEMA = "pm-v3/1"
EXIT_OK, EXIT_FAIL, EXIT_HUMAN, EXIT_CRITICAL, EXIT_WAIT, EXIT_USAGE = 0, 1, 2, 3, 10, 64
STATUSES = ("OPEN", "IN_PROGRESS", "READY_FOR_VERIFICATION", "READY_FOR_REVIEW", "BLOCKED", "ESCALATED", "STALE", "DONE")
MARKERS = ("<<CONSENSUS>>", "<<CONTINUE>>", "<<WAIT_HUMAN>>")
DEFAULTS = {
    "enabled": False, "max_parallel": 2, "max_attempts": 3, "auto_retry": True, "team_timeout_s": 1800, "verify_timeout_s": 600,
    "debate": {"max_rounds": 3, "order": ["claude", "codex"], "agents": {"claude": {"adapter": "drop"}, "codex": {"adapter": "codex-cli"}}},
    "teams": {}, "cross_review": {}, "worktree_root": None, "branch_prefix": "pilot/", "integration_branch": "pilot/integration",
    "protected_branches": ["main", "master", "develop", "production", "release/*", "hotfix/*"],
    "mode": None, "confinement": None, "verify_commands": [], "allowed_test_commands": [], "sensitive_paths": [], "integration_policy": ".claude/pmx.integration-policy.json",
}
# Chemins qui exigent toujours une validation humaine (secrets, permissions, hooks/garde-fous, CI/production).
SENSITIVE = [
    ("secret", [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "*secret*", "*credential*", "*token*", ".npmrc", ".pypirc", ".netrc"]),
    ("guardrail", [".claude/*", ".claude/**", ".git/*", ".git", "*/.git", "*/.git/*", ".gitattributes", ".gitmodules", ".githooks/*", ".husky/*", "hooks/*", "*/hooks/*", "*settings*.json", ".pre-commit-config.yaml", "CODEOWNERS", "ai_rules/*", ".claude/rules/*"]),
    ("production", [".gitlab-ci.yml", ".github/workflows/*", "deploy/*", "k8s/*", "helm/*", "terraform/*", "*.tf", "Dockerfile", "docker-compose*.yml"]),
]
# Commandes de test : exécutées sans shell ; ces caractères signalent une tentative d'enchaînement ou de substitution.
SHELL_META = re.compile(r"[;&|$`<>(){}\\\n\r]")
# Variables posées par les CLI d'agents dans les commandes qu'elles lancent : une intégration réelle n'y est jamais confirmée.
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")


# ---------------------------------------------------------------- utilitaires

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def die(msg, code=EXIT_FAIL):
    print(f"✘ {msg}", file=sys.stderr)
    sys.exit(code)


# Git lancé par pmx touche des contenus écrits par les équipes : aucun hook (y compris post-checkout, post-commit,
# reference-transaction), aucun fsmonitor, aucune configuration globale ou système (pilotes de filtre ou de diff, textconv,
# alias), aucun transport réseau. La configuration locale du dépôt reste celle de l'humain (jamais modifiable par une équipe).
GIT_SAFE = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.allow=never", "-c", "core.sshCommand=false"]


def git_env(extra=None):
    e = {k: v for k, v in os.environ.items() if k not in ("GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS", "GIT_DIR", "GIT_WORK_TREE")}
    e.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}, **(extra or {}))
    return e


def git(root, *args, check=True, env=None):
    p = subprocess.run([*GIT_SAFE, "-C", str(root), *args], capture_output=True, text=True, env=git_env(env))
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
        probs = bypass_problems(self) + mode_problems(self)
        if probs:
            die("configuration refusée — " + " ; ".join(probs), EXIT_USAGE)

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

# ---------------------------------------------------------------- profils d'exécution et garde-fous des permissions natives

HYBRID = "host-agents+docker-verification"
# Drapeaux ou réglages qui désactivent les permissions ou le sandbox natifs d'une CLI : jamais acceptés, quel que soit le mode.
BYPASS = re.compile(r"dangerously|bypass(?:Permissions|-approvals)|--yolo\b|danger-full-access|sandbox_mode\s*=\s*\"?danger", re.I)
HOST_ADAPTERS = ("codex-cli", "claude-cli", "drop", "cmd")


def agent_configs(ctx):
    """(nom, configuration) de chaque agent lancé par pmx : équipes, reviewers, débatteurs."""
    out = []
    for name, t in ctx.o["teams"].items():
        out.append((f"équipe {name}", t))
        if isinstance(t.get("reviewer"), dict):
            out.append((f"reviewer de {name}", t["reviewer"]))
    for side, d in ((ctx.o.get("debate") or {}).get("agents") or {}).items():
        out.append((f"débat {side}", d))
    return out


def bypass_problems(ctx):
    """Contournements des permissions natives dans les configurations d'agents (argv, modèle, réglages claude)."""
    probs = []
    for who, c in agent_configs(ctx):
        if BYPASS.search(json.dumps({k: v for k, v in c.items() if k != "label"})):
            probs.append(f"{who} : contournement des permissions ou du sandbox natifs refusé")
        if c.get("adapter") == "claude-cli" and c.get("settings"):
            sp = (ctx.root / c["settings"]).resolve()
            try:
                txt = sp.read_text(encoding="utf-8")
                mode = (json.loads(txt).get("permissions") or {}).get("defaultMode")
            except (OSError, ValueError) as e:
                probs.append(f"{who} : réglages {c['settings']} illisibles ({type(e).__name__})")
                continue
            if mode not in (None, "default", "acceptEdits", "plan", "dontAsk") or BYPASS.search(txt.replace("dangerously", "")):
                probs.append(f"{who} : defaultMode {mode!r} refusé dans {c['settings']}")
    return probs


def mode_problems(ctx):
    """Exigences du profil déclaré (`orchestration.mode`). Profil hybride : agents sur l'hôte avec leurs permissions natives,
    vérification et tests d'intégration uniquement en conteneur isolé, isolation exigée par la politique d'intégration."""
    m = ctx.o.get("mode")
    if m in (None, "default"):
        return []
    if m != HYBRID:
        return [f"mode inconnu {m!r} (default | {HYBRID})"]
    probs = []
    kind, _d, rerrs = verify_runner(ctx)
    if kind != "docker":
        probs.append("mode hybride : verify_runner.adapter = docker obligatoire")
    probs += rerrs
    pol_p = ctx.root / ctx.o["integration_policy"]
    try:
        pol = json.loads(pol_p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pol = {}
    if pol.get("require_isolated_verification") is not True:
        probs.append(f"mode hybride : require_isolated_verification=true obligatoire dans {ctx.o['integration_policy']}")
    if ctx.o.get("gateway"):
        probs.append("mode hybride : orchestration.gateway non utilisée (agents sur l'hôte) — à retirer")
    if not confined(ctx):
        probs.append('mode hybride : confinement = "native" obligatoire (sandbox natifs des CLI, lectures limitées au worktree)')
    for who, c in agent_configs(ctx):
        if c.get("adapter") not in HOST_ADAPTERS:
            probs.append(f"mode hybride : {who} doit tourner sur l'hôte ({'/'.join(HOST_ADAPTERS)}), pas {c.get('adapter')!r}")
        if c.get("adapter") == "claude-cli":
            sp = (ctx.root / c["settings"]).resolve() if c.get("settings") else None
            deny = []
            if sp and sp.exists():
                try:
                    deny = (json.loads(sp.read_text(encoding="utf-8")).get("permissions") or {}).get("deny") or []
                except ValueError:
                    pass
            if not sp or not sp.exists():
                probs.append(f"mode hybride : {who} sans réglages de permissions explicites (`settings`)")
            elif not any(re.match(r"Bash\(docker[ :]", r) for r in deny):
                probs.append(f"mode hybride : {who} — les réglages doivent refuser Bash(docker:*) (aucun accès Docker aux agents)")
    return probs


# ---------------------------------------------------------------- confinement natif des CLI (orchestration.confinement = "native")

# Lectures refusées aux commandes de Claude (sandbox bubblewrap) ; le worktree est ré-autorisé par son chemin ABSOLU
# (dans un fichier --settings, « . » désignerait le dossier du fichier de réglages, pas le worktree : vérifié en réel).
CONFINED_DENY_READ = ["~/", "/mnt", "/run/WSL", "/mnt/wsl", "/var/run/docker.sock", "/run/docker.sock", "/tmp"]
CLAUDE_MIN_VERSION = (2, 1, 257)  # permissions.blockReadsOutsideWorkingDirectories


def confined(ctx):
    return ctx.o.get("confinement") == "native"


def codex_package_dir():
    """Répertoire d'installation de Codex, seul chemin du HOME lisible dans son sandbox (Codex s'y ré-exécute)."""
    exe = shutil.which("codex")
    if not exe:
        return None
    real = str(pathlib.Path(exe).resolve())
    if "/node_modules/@openai/codex/" in real:
        p = pathlib.Path(real.split("/node_modules/@openai/codex/")[0] + "/node_modules/@openai/codex")
    elif (m := re.match(r"^(.*/releases/[^/]+)/", real)):
        p = pathlib.Path(m.group(1))
    else:
        p = pathlib.Path(real).parent
    home = pathlib.Path(pwd_home()).resolve()
    if p in (home, home / ".codex", pathlib.Path("/")) or (p / "auth.json").exists():
        return None
    return p


def codex_profile_args(mode):
    """Profil de permissions Codex (bêta, officiel) passé en ligne de commande : aucune lecture hors du worktree et des
    chemins système minimaux, aucune écriture hors du worktree, ni /tmp, ni réseau. ~/.codex n'est ni lu ni modifié."""
    pkg = codex_package_dir()
    name, ext = ("pmx-ro", ":read-only") if mode == "read" else ("pmx-ws", ":workspace")
    fs = {":root": "deny", ":minimal": "read", ":tmpdir": "deny", ":slash_tmp": "deny", str(pkg): "read"}
    if mode == "read":
        fs[":workspace_roots"] = "read"
    inline = "{" + ", ".join(f"{json.dumps(k)}={json.dumps(v)}" for k, v in fs.items()) + "}"
    return ["-c", f'permissions.{name}.extends="{ext}"', "-c", f"permissions.{name}.filesystem={inline}",
            "-c", f"permissions.{name}.network.enabled=false", "-c", f'default_permissions="{name}"']


def claude_confined_settings(ctx, acfg, cwd, mode, dest):
    """Réglages claude générés pour UN appel : politique de l'équipe + sandbox imposé + lectures limitées au worktree."""
    base = {}
    if acfg.get("settings"):
        base = json.loads((ctx.root / acfg["settings"]).read_text(encoding="utf-8"))
    if "sandbox" in base:
        die(f"réglages {acfg.get('settings')} : bloc `sandbox` réservé à pmx en confinement natif", EXIT_USAGE)
    perms = dict(base.get("permissions") or {})
    perms["blockReadsOutsideWorkingDirectories"] = True
    w = str(pathlib.Path(cwd).resolve())
    base["permissions"] = perms
    base["sandbox"] = {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                       "filesystem": {"denyRead": CONFINED_DENY_READ, "allowRead": [w], "allowWrite": [w] if mode != "read" else []},
                       "network": {"allowedDomains": []}}
    write_atomic(dest, json.dumps(base, indent=1, ensure_ascii=False) + "\n")
    return dest


def confinement_problems(ctx):
    """Préflight avant tout lancement d'agent réel : prérequis présents et sandbox Codex effectivement fermé (essai sans
    modèle). Toute anomalie = arrêt explicite, jamais d'exécution non isolée."""
    if not confined(ctx):
        return []
    adapters = {c.get("adapter") for _w, c in agent_configs(ctx)}
    probs = [f"{t} absent (prérequis du sandbox natif)" for t in ("bwrap", "socat") if not shutil.which(t)]
    for who, c in agent_configs(ctx):
        if c.get("adapter") == "claude-cli" and c.get("settings"):
            try:
                if "sandbox" in json.loads((ctx.root / c["settings"]).read_text(encoding="utf-8")):
                    probs.append(f"{who} : bloc `sandbox` interdit dans {c['settings']} (généré par pmx)")
            except (OSError, ValueError):
                probs.append(f"{who} : réglages {c['settings']} illisibles")
    if "claude-cli" in adapters:
        v = subprocess.run(["claude", "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL) if shutil.which("claude") else None
        m = re.match(r"(\d+)\.(\d+)\.(\d+)", v.stdout.strip()) if v and v.returncode == 0 else None
        if not m or tuple(map(int, m.groups())) < CLAUDE_MIN_VERSION:
            probs.append(f"Claude Code ≥ {'.'.join(map(str, CLAUDE_MIN_VERSION))} requis (blockReadsOutsideWorkingDirectories)")
    if "codex-cli" in adapters:
        if not codex_package_dir():
            probs.append("installation de Codex introuvable ou non confinable")
        else:
            canary = ctx.am / f".pmx-confinement-{os.getpid()}"
            ws = canary / "ws"
            try:
                ws.mkdir(parents=True, exist_ok=True)
                (ws / "inside.txt").write_text("in\n")
                (canary / "outside.txt").write_text("CANARY\n")
                run = lambda cmd: subprocess.run(["codex", "sandbox", *codex_profile_args("write"), "-P", "pmx-ws", "-C", str(ws), "--", "sh", "-c", cmd],
                                                 capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, env=agent_env())
                ok_in = run("cat inside.txt && echo w > written.txt")
                ok_out = run(f"cat {shlex.quote(str(canary / 'outside.txt'))}")
                if ok_in.returncode != 0 or not (ws / "written.txt").exists():
                    probs.append(f"sandbox Codex inutilisable (worktree inaccessible) : {(ok_in.stderr or ok_in.stdout).strip()[:200]}")
                if ok_out.returncode == 0 or "CANARY" in ok_out.stdout:
                    probs.append("sandbox Codex NON fermé : lecture hors worktree possible")
            except (OSError, subprocess.TimeoutExpired) as e:
                probs.append(f"préflight du sandbox Codex impossible ({type(e).__name__})")
            finally:
                shutil.rmtree(canary, ignore_errors=True)
    return probs


_CONFINEMENT_OK = False


def require_confinement(ctx):
    """Une fois par processus pmx, avant le premier lancement d'agent."""
    global _CONFINEMENT_OK
    if _CONFINEMENT_OK or not confined(ctx):
        return
    probs = confinement_problems(ctx)
    _CONFINEMENT_OK = not probs
    if probs:
        die("confinement natif indisponible — aucun agent lancé : " + " ; ".join(probs), EXIT_USAGE)


def agent_env():
    """Environnement des agents : sans le canal d'interop Windows (WSL_INTEROP)."""
    return {k: v for k, v in os.environ.items() if k not in ("WSL_INTEROP",)}


def agent_argv(ctx, acfg, prompt_file, out_file, cwd, mode):
    """Commande d'un agent, ou None pour un agent externe (« drop » : fichiers échangés avec la session lead)."""
    a = acfg.get("adapter")
    prompt = pathlib.Path(prompt_file).read_text(encoding="utf-8")
    if a == "codex-cli":
        if confined(ctx):  # profil de permissions : lectures limitées au worktree (remplace --sandbox, incompatible)
            argv = ["codex", "exec", *codex_profile_args(mode), "--skip-git-repo-check", "--ephemeral", "-C", str(cwd), "-o", str(out_file)]
        else:
            argv = ["codex", "exec", "--sandbox", "read-only" if mode == "read" else "workspace-write", "--skip-git-repo-check",
                    "--ephemeral", "-C", str(cwd), "-o", str(out_file),
                    # durcissement explicite du sandbox natif, indépendant de ~/.codex/config.toml (jamais lu ni modifié) :
                    # pas de réseau, et ni /tmp ni $TMPDIR inscriptibles — seul le worktree l'est
                    "-c", "sandbox_workspace_write.network_access=false", "-c", "sandbox_workspace_write.exclude_slash_tmp=true",
                    "-c", "sandbox_workspace_write.exclude_tmpdir_env_var=true"]
        if acfg.get("model"):
            argv += ["-m", acfg["model"]]
        return argv + [prompt], False
    if a == "claude-cli":
        tools = "Read,Grep,Glob" if mode == "read" else "Read,Grep,Glob,Edit,Write,Bash"
        argv = ["claude", "-p", prompt, "--output-format", "text", "--tools", tools,
                "--permission-mode", "default" if mode == "read" else "acceptEdits"]
        if confined(ctx):  # réglages générés pour cet appel, hors du worktree, à côté du prompt
            dest = pathlib.Path(prompt_file).with_name(pathlib.Path(prompt_file).name + ".claude-settings.json")
            argv += ["--settings", str(claude_confined_settings(ctx, acfg, cwd, mode, dest))]
        elif acfg.get("settings"):  # politique pilote passée explicitement, jamais la config globale
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


def run_agent_sync(ctx, acfg, prompt_file, out_file, cwd, mode, log_file, timeout, name=None, gateway=None):
    if acfg.get("adapter") == "docker":
        with open(log_file, "a", encoding="utf-8") as log:
            rc, _ev = run_docker_agent(ctx, acfg, prompt_file, out_file, cwd, mode, log, timeout,
                                       name or container_name(ctx, f"{mode}-{os.getpid()}-{time.time_ns()}"), gateway)
        return rc
    argv, to_stdout = agent_argv(ctx, acfg, prompt_file, out_file, cwd, mode)
    if argv is None:
        return None
    with open(log_file, "a", encoding="utf-8") as log:
        shown = [x if len(x) < 300 else f"<prompt {len(x)} car.>" for x in argv]
        log.write(f"\n[{now()}] $ {' '.join(shlex.quote(x) for x in shown)}\n")
        log.flush()
        try:
            p = subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=agent_env())
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


# ---------------------------------------------------------------- adaptateur docker (isolation système, opt-in)

# Seules clés acceptées : aucune ne permet d'ajouter un montage, un argument `docker` libre, un réseau ou un privilège.
DOCKER_DEFAULTS = {"image": None, "argv": None, "cpus": 1.0, "memory": "512m", "pids": 128, "tmpfs_size": "64m",
                   "network": "none", "nofile": 1024, "agent_dir": None, "gateway_routes": None, "gateway_quota": None}
# Répertoires du HOME jamais montés, même à l'intérieur d'un `agent_dir` (identifiants, clés, configuration des CLI).
HOME_SECRETS = (".ssh", ".gnupg", ".aws", ".azure", ".config", ".docker", ".kube", ".claude", ".codex", ".netrc", ".git-credentials", ".npmrc", ".pypirc")
DOCKER_LABEL = "pmx.pilot"


def docker_settings(ctx, acfg, allow_gateway=True):
    """→ (réglages, erreurs). Configuration explicite par équipe ; tout ce qui n'est pas listé est refusé.
    Réseau : `none` (défaut) ou, pour une équipe et si `orchestration.gateway` est configurée, `gateway` (réseau interne
    dédié, seule sortie : la passerelle pmx_gateway, routes `gateway_routes`)."""
    d, errs = dict(DOCKER_DEFAULTS), []
    raw = acfg.get("docker")
    if not isinstance(raw, dict):
        return d, ["adaptateur docker : bloc `docker` requis (image, argv)"]
    for k in sorted(set(raw) - set(DOCKER_DEFAULTS)):
        errs.append(f"docker : clé non autorisée {k!r} (aucun montage, argument ou privilège supplémentaire)")
    d.update({k: v for k, v in raw.items() if k in DOCKER_DEFAULTS})
    if not isinstance(d["image"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?", d["image"] or ""):
        errs.append(f"docker : image invalide {d['image']!r}")
    if not (isinstance(d["argv"], list) and d["argv"] and all(isinstance(x, str) for x in d["argv"])):
        errs.append("docker : argv (liste de chaînes) requis")
    if d["network"] == "gateway" and allow_gateway:
        g, gerrs = gateway_settings(ctx)
        errs += gerrs
        routes = d["gateway_routes"]
        if not (isinstance(routes, list) and routes and all(r in (g or {}).get("routes", {}) for r in routes)):
            errs.append(f"docker : gateway_routes {routes!r} doit lister des routes de orchestration.gateway.routes")
        q = d["gateway_quota"] or {}
        if not (isinstance(q, dict) and all(k in ("max_requests", "max_bytes", "max_tokens") and isinstance(v, int) and v > 0 for k, v in q.items())):
            errs.append(f"docker : gateway_quota invalide {q!r}")
    elif d["network"] != "none":
        errs.append(f"docker : réseau {d['network']!r} refusé (`none`, ou `gateway` pour une équipe avec orchestration.gateway)")
    elif d["gateway_routes"] or d["gateway_quota"]:
        errs.append("docker : gateway_routes / gateway_quota sans `network: gateway`")
    if not (isinstance(d["cpus"], (int, float)) and 0.1 <= d["cpus"] <= (os.cpu_count() or 1)):
        errs.append(f"docker : cpus hors bornes {d['cpus']!r}")
    for k in ("memory", "tmpfs_size"):
        if not (isinstance(d[k], str) and re.fullmatch(r"[1-9]\d{0,5}[mg]", d[k])):
            errs.append(f"docker : {k} invalide {d[k]!r} (ex. 512m)")
    if not (isinstance(d["pids"], int) and 16 <= d["pids"] <= 4096):
        errs.append(f"docker : pids hors bornes {d['pids']!r}")
    if not (isinstance(d["nofile"], int) and 64 <= d["nofile"] <= 65536):
        errs.append(f"docker : nofile hors bornes {d['nofile']!r}")
    if d["agent_dir"] is not None:
        p = pathlib.Path(d["agent_dir"])
        p = (p if p.is_absolute() else ctx.root / p).resolve()
        d["agent_dir"] = str(p)
        errs += [f"docker : agent_dir {p} — {e}" for e in mount_problems(ctx, p)]
    return d, errs


def mount_problems(ctx, p):
    """Raisons de refuser un répertoire monté en lecture seule (programme de l'agent)."""
    home = pathlib.Path(pwd_home()).resolve()
    probs = []
    if not p.is_dir():
        probs.append("répertoire absent")
    if "," in str(p) or "=" in str(p):
        probs.append("caractère interdit dans le chemin (, =)")
    for anc in (home, ctx.root, ctx.wt_root, pathlib.Path("/"), pathlib.Path("/var"), pathlib.Path("/run"), pathlib.Path("/etc")):
        if p == anc or anc.is_relative_to(p):
            probs.append(f"contient ou égale {anc} (HOME, dépôt, worktrees ou système)")
    if p.is_relative_to(ctx.root) or p.is_relative_to(ctx.wt_root):
        probs.append("dans le dépôt ou les worktrees (modifiable par une équipe)")
    if any(part in HOME_SECRETS for part in p.parts) or (p.is_dir() and any((p / s).exists() for s in HOME_SECRETS)):
        probs.append("chemin d'identifiants ou de configuration (.ssh, .claude, .codex, .docker…)")
    if not probs:  # parcours borné : un programme d'agent est un petit répertoire
        for i, x in enumerate(p.rglob("*")):
            if i >= 5000:
                probs.append("répertoire trop volumineux pour un programme d'agent (> 5000 entrées)")
                break
            if x.is_socket() or x.name == "docker.sock":
                probs.append(f"contient une socket ({x})")
                break
    return probs


def pwd_home():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_dir
    except (ImportError, KeyError):
        return os.path.expanduser("~")


def container_name(ctx, label):
    """Nom unique, préfixé et rattaché au dépôt : pmx ne touche jamais un conteneur qu'il n'a pas créé."""
    import hashlib
    h = hashlib.sha1(str(ctx.root).encode()).hexdigest()[:8]
    return re.sub(r"[^a-z0-9_.-]", "-", f"pmx-{h}-{label}".lower())[:120]


def docker_argv(ctx, d, name, argv_in, cwd, mode, labels, prompt_file=None, network="none", env=None, env_pass=()):
    """mode : write (équipe), read (revue, /work en lecture seule), verify (commande de test de confiance, sans brief).
    `env_pass` : noms de variables dont la valeur vient de l'environnement du client docker (jamais dans argv ni journal)."""
    cwd = pathlib.Path(cwd).resolve()
    for p in (cwd, prompt_file):
        if p and ("," in str(p) or "=" in str(p)):
            die(f"docker : caractère interdit (, =) dans {p}", EXIT_USAGE)
    ro = ",readonly" if mode == "read" else ""
    argv = ["docker", "create", "--name", name, "--label", f"{DOCKER_LABEL}=1", "--label", f"pmx.root={ctx.root}",
            *[x for k, v in labels.items() for x in ("--label", f"pmx.{k}={v}")],
            "--pull", "never", "--init", "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--network", network, "--ipc", "private",
            "--cpus", str(d["cpus"]), "--memory", d["memory"], "--memory-swap", d["memory"], "--pids-limit", str(d["pids"]),
            "--ulimit", f"nofile={d['nofile']}:{d['nofile']}",
            "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={d['tmpfs_size']}",
            "--env", "HOME=/tmp", "--env", "PMX_WORK=/work", "--env", f"PMX_MODE={mode}",
            *[x for k, v in (env or {}).items() for x in ("--env", f"{k}={v}")], *[x for k in env_pass for x in ("--env", k)],
            "--mount", f"type=bind,src={cwd},dst=/work{ro}"]
    if (cwd / ".git").exists():  # le pointeur gitdir du worktree : jamais modifiable depuis le conteneur
        argv += ["--mount", f"type=bind,src={cwd / '.git'},dst=/work/.git,readonly"]
    if prompt_file:
        argv += ["--env", "PMX_BRIEF=/pmx/brief.md", "--mount", f"type=bind,src={pathlib.Path(prompt_file).resolve()},dst=/pmx/brief.md,readonly"]
    if d["agent_dir"]:
        argv += ["--mount", f"type=bind,src={d['agent_dir']},dst=/agent,readonly"]
    return argv + ["--workdir", "/work", d["image"], *argv_in]


def docker_policy(inspect, d, cwd, prompt_file, mode, network="none"):
    """Contrôle du conteneur CRÉÉ (avant démarrage), sur la configuration réelle du démon, pas sur la commande."""
    hc, cfg, probs = inspect["HostConfig"], inspect["Config"], []
    if hc.get("Privileged"):
        probs.append("conteneur privilégié")
    if hc.get("CapAdd") or "ALL" not in (hc.get("CapDrop") or []):
        probs.append(f"capacités : add={hc.get('CapAdd')} drop={hc.get('CapDrop')}")
    if not hc.get("ReadonlyRootfs"):
        probs.append("système de fichiers racine en écriture")
    if "no-new-privileges" not in " ".join(hc.get("SecurityOpt") or []):
        probs.append("no-new-privileges absent")
    if hc.get("NetworkMode") != network or len((inspect.get("NetworkSettings") or {}).get("Networks") or {}) > 1:
        probs.append(f"réseau {hc.get('NetworkMode')} (attendu : {network})")
    if network != "none":
        ni = docker("network", "inspect", network)
        if ni.returncode != 0 or not json.loads(ni.stdout)[0].get("Internal"):
            probs.append(f"réseau {network} non interne (route sortante possible)")
    if hc.get("PortBindings") or hc.get("PublishAllPorts"):
        probs.append(f"ports publiés : {hc.get('PortBindings')}")
    if hc.get("PidMode") or hc.get("IpcMode") not in ("private",) or hc.get("UsernsMode") or hc.get("Devices"):
        probs.append(f"espaces de noms partagés ou périphériques : pid={hc.get('PidMode')!r} ipc={hc.get('IpcMode')!r} devices={hc.get('Devices')}")
    if str(cfg.get("User")) in ("", "0", "root") or cfg.get("User", "").startswith("0:"):
        probs.append(f"utilisateur root ({cfg.get('User')!r})")
    if not hc.get("Memory") or not hc.get("NanoCpus") or not hc.get("PidsLimit"):
        probs.append("limites CPU / mémoire / processus absentes")
    w = str(pathlib.Path(cwd).resolve())
    allowed = {(w, "/work", mode != "read"), (str(pathlib.Path(w) / ".git"), "/work/.git", False)}
    if prompt_file:
        allowed.add((str(pathlib.Path(prompt_file).resolve()), "/pmx/brief.md", False))
    if d["agent_dir"]:
        allowed.add((d["agent_dir"], "/agent", False))
    for m in inspect.get("Mounts") or []:
        if m.get("Type") != "bind" or (m.get("Source"), m.get("Destination"), bool(m.get("RW"))) not in allowed:
            probs.append(f"montage inattendu : {m.get('Type')} {m.get('Source')} → {m.get('Destination')} rw={m.get('RW')}")
        if "docker.sock" in str(m.get("Source")):
            probs.append("socket Docker montée")
    if set((hc.get("Tmpfs") or {})) != {"/tmp"}:
        probs.append(f"tmpfs inattendus : {hc.get('Tmpfs')}")
    return probs


def docker(*args, timeout=60, env=None):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              env={**os.environ, **env} if env else None)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(["docker", *args], 127, "", str(e))


def docker_own(ctx, name):
    """Inspect du conteneur s'il a été créé par pmx pour CE dépôt ; sinon None (jamais d'action sur un autre conteneur)."""
    p = docker("inspect", "--type", "container", name)
    if p.returncode != 0:
        return None
    info = json.loads(p.stdout)[0]
    labels = info.get("Config", {}).get("Labels") or {}
    return info if labels.get(DOCKER_LABEL) == "1" and labels.get("pmx.root") == str(ctx.root) else None


def docker_stop(ctx, name):
    info = docker_own(ctx, name)
    if info and info["State"].get("Running"):
        docker("kill", name)
        return True
    return False


def docker_finalize(ctx, name, evidence_dir):
    """Preuve (configuration réelle + état de sortie) écrite hors du conteneur, puis suppression du seul conteneur pmx."""
    info = docker_own(ctx, name)
    if not info:
        return None
    if info["State"].get("Running"):
        docker("kill", name)
        info = docker_own(ctx, name) or info
    hc = info["HostConfig"]
    ev = {"name": name, "image": info["Config"].get("Image"), "user": info["Config"].get("User"), "labels": info["Config"].get("Labels"),
          "env_keys": sorted(e.split("=", 1)[0] for e in info["Config"].get("Env") or []),
          "host_config": {k: hc.get(k) for k in ("Privileged", "ReadonlyRootfs", "CapAdd", "CapDrop", "SecurityOpt", "NetworkMode", "IpcMode",
                                                 "PidMode", "UsernsMode", "Memory", "MemorySwap", "NanoCpus", "PidsLimit", "Ulimits", "Tmpfs", "Devices", "Binds")},
          "mounts": [{k: m.get(k) for k in ("Type", "Source", "Destination", "RW")} for m in info.get("Mounts") or []],
          "state": {k: info["State"].get(k) for k in ("ExitCode", "OOMKilled", "StartedAt", "FinishedAt", "Error")}}
    p = pathlib.Path(evidence_dir) / f"container-{name}.json"
    write_atomic(p, json.dumps(ev, indent=2, ensure_ascii=False) + "\n")
    docker("rm", name)
    return ev


def docker_exec(ctx, d, name, argv_in, cwd, mode, timeout, evidence_dir, log=None, prompt_file=None, labels=None, gateway=None):
    """create → contrôle de la configuration réelle → start --attach → preuve → suppression.
    → (code, stdout, stderr, preuve, motif non concluant ou None). Seul `pmx` (session lead) appelle docker.
    `gateway` = (réseau interne de l'équipe, jeton, routes) : variables d'accès à la passerelle, jeton hors argv."""
    network, env, secret = "none", {}, {}
    if gateway:
        network, token, routes = gateway
        env, secret = gateway_env(routes, token)
    argv = docker_argv(ctx, d, name, argv_in, cwd, mode, {"name": name, "kind": mode, **(labels or {})}, prompt_file, network, env, tuple(secret))
    if log:
        log.write(f"[{now()}] $ {' '.join(shlex.quote(x) for x in argv)}\n")
        log.flush()
    p = docker(*argv[1:], env=secret)
    if p.returncode != 0:
        return 126, "", p.stderr, None, f"conteneur non créé : {p.stderr.strip()[:300]}"
    info = docker_own(ctx, name)
    probs = docker_policy(info, d, cwd, prompt_file, mode, network) if info else ["conteneur introuvable après création"]
    if probs:
        docker_finalize(ctx, name, evidence_dir)
        return 126, "", "", None, f"politique d'isolation non respectée, conteneur non démarré : {probs}"
    why = None
    try:
        r = subprocess.run(["docker", "start", "--attach", name], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        rc, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        docker_stop(ctx, name)
        rc, out, err, why = 124, "", f"TIMEOUT {timeout}s : conteneur arrêté", f"délai dépassé ({timeout}s)"
    ev = docker_finalize(ctx, name, evidence_dir)
    if ev is None:
        why = why or "preuve du conteneur introuvable (supprimé par un tiers ?)"
    elif ev["state"].get("OOMKilled"):
        err += "\nOOMKilled: limite mémoire atteinte, conteneur arrêté par le noyau"
        why = why or "limite mémoire atteinte (OOM)"
    elif rc in (137, 143) or (ev["state"].get("ExitCode") in (137, 143)):
        why = why or f"conteneur tué par un signal (code {rc})"
    return rc, out, err, ev, why


# ---------------------------------------------------------------- passerelle réseau des équipes (pmx_gateway, opt-in)

GATEWAY_ROUTE_ENV = {  # variables posées dans le conteneur d'une équipe, par route (convention des CLI officielles)
    "anthropic": ({"ANTHROPIC_BASE_URL": "http://pmx-gateway:8080/anthropic", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}, "ANTHROPIC_AUTH_TOKEN"),
    "openai": ({"OPENAI_BASE_URL": "http://pmx-gateway:8080/openai/v1"}, "OPENAI_API_KEY"),
}


def gateway_settings(ctx):
    """→ (réglages, erreurs) de `orchestration.gateway`. Aucun montage, port publié ou réseau sortant n'y est configurable
    hormis `upstream_network` (réseau Docker existant, où se trouvent les amonts — internes pour les tests)."""
    g = ctx.o.get("gateway")
    if not isinstance(g, dict):
        return None, ["orchestration.gateway absente"]
    errs = [f"gateway : clé non autorisée {k!r}" for k in sorted(set(g) - {"image", "routes", "limits", "quota", "upstream_network", "keys_file", "token_ttl_s"})]
    if not isinstance(g.get("image"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?(@sha256:[0-9a-f]{64})?", g["image"]):
        errs.append(f"gateway : image invalide {g.get('image')!r}")
    routes = g.get("routes")
    if not isinstance(routes, dict) or not routes:
        errs.append("gateway : routes requises")
        routes = {}
    for name, r in routes.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", name) or not isinstance(r, dict):
            errs.append(f"gateway : route invalide {name!r}")
            continue
        u = urllib.parse.urlsplit(str(r.get("upstream", "")))
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            errs.append(f"gateway : amont invalide pour {name} ({r.get('upstream')!r})")
        if set(r) - {"upstream", "allow_private", "auth_header", "key"}:
            errs.append(f"gateway : clés non autorisées dans la route {name} : {sorted(set(r) - {'upstream', 'allow_private', 'auth_header', 'key'})}")
        if r.get("auth_header", "x-api-key").lower() not in ("x-api-key", "authorization"):
            errs.append(f"gateway : auth_header invalide pour {name}")
    for k in ("limits", "quota"):
        if not isinstance(g.get(k, {}), dict) or not all(isinstance(v, (int, float)) and v > 0 for v in g.get(k, {}).values()):
            errs.append(f"gateway : {k} invalide")
    if not isinstance(g.get("upstream_network"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", g.get("upstream_network") or ""):
        errs.append("gateway : upstream_network (réseau Docker existant) requis")
    kf = pathlib.Path(str(g.get("keys_file") or ""))
    kf = (kf if kf.is_absolute() else ctx.root / kf).resolve()
    if not g.get("keys_file") or not kf.is_file():
        errs.append(f"gateway : keys_file absent ({g.get('keys_file')!r}) — fichier des clés AMONT dédiées, fourni par l'humain")
    elif any(part in HOME_SECRETS for part in kf.parts) or kf.is_relative_to(ctx.wt_root):
        errs.append(f"gateway : keys_file {kf} dans un chemin d'identifiants personnels ou un worktree")
    return {**g, "keys_file": str(kf), "routes": routes}, errs


def gateway_env(routes, token):
    """→ (variables visibles, variables secrètes) pour le conteneur d'une équipe."""
    env, secret = {"PMX_GATEWAY_URL": "http://pmx-gateway:8080"}, {"PMX_GATEWAY_TOKEN": token}
    for r in routes:
        visible, tok_var = GATEWAY_ROUTE_ENV.get(r, ({}, None))
        env.update(visible)
        if tok_var:
            secret[tok_var] = token
    return env, secret


def gateway_dir(ctx, run):
    return ctx.run_dir(run) / "gateway"


def gateway_tokens_update(ctx, run, add=None, remove=None):
    """tokens.json : empreintes SHA-256 seulement (jamais la valeur d'un jeton), remplacement atomique."""
    p = gateway_dir(ctx, run) / "state" / "tokens.json"
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tokens": {}}
    if add:
        cur["tokens"].update(add)
    for h in remove or ():
        cur["tokens"].pop(h, None)
    write_atomic(p, json.dumps(cur, indent=1) + "\n")


def gateway_ensure(ctx, run):
    """Démarre (si besoin) la passerelle du run : non-root, racine RO, cap-drop ALL, no-new-privileges, aucun port publié,
    seul réseau initial = upstream_network ; configuration réelle contrôlée avant démarrage."""
    g, errs = gateway_settings(ctx)
    if errs:
        die("passerelle refusée — " + " ; ".join(errs), EXIT_USAGE)
    name, gdir = container_name(ctx, f"{run}-gateway"), gateway_dir(ctx, run)
    info = docker_own(ctx, name)
    if info and info["State"].get("Running"):
        return name
    if info:
        docker_finalize(ctx, name, gdir)
    ni = docker("network", "inspect", g["upstream_network"])
    if ni.returncode != 0:
        die(f"passerelle : réseau amont {g['upstream_network']} introuvable", EXIT_USAGE)
    (gdir / "state").mkdir(parents=True, exist_ok=True)
    (gdir / "log").mkdir(parents=True, exist_ok=True)
    if not (gdir / "state" / "tokens.json").exists():
        gateway_tokens_update(ctx, run)
    write_atomic(gdir / "config.json", json.dumps({"routes": g["routes"], "limits": g.get("limits", {}), "quota": g.get("quota", {})}, indent=1) + "\n")
    script = pathlib.Path(__file__).resolve().parent / "pmx_gateway.py"
    mounts = [(str(script), "/gateway/pmx_gateway.py", False), (str(gdir / "config.json"), "/gateway/config.json", False),
              (str(gdir / "state"), "/gateway/state", False), (g["keys_file"], "/gateway/keys.json", False), (str(gdir / "log"), "/log", True)]
    argv = ["create", "--name", name, "--label", f"{DOCKER_LABEL}=1", "--label", f"pmx.root={ctx.root}", "--label", "pmx.kind=gateway", "--label", f"pmx.run={run}",
            "--pull", "never", "--init", "--user", f"{os.getuid()}:{os.getgid()}", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--network", g["upstream_network"], "--ipc", "private", "--cpus", "0.5", "--memory", "128m", "--memory-swap", "128m", "--pids-limit", "64",
            "--ulimit", "nofile=1024:1024", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--env", "HOME=/tmp",
            *[x for src, dst, rw in mounts for x in ("--mount", f"type=bind,src={src},dst={dst}" + ("" if rw else ",readonly"))],
            g["image"], "python3", "-I", "-B", "/gateway/pmx_gateway.py", "--config", "/gateway/config.json", "--state", "/gateway/state",
            "--keys", "/gateway/keys.json", "--log", "/log/gateway.jsonl"]
    p = docker(*argv)
    if p.returncode != 0:
        die(f"passerelle non créée : {p.stderr.strip()[:300]}", EXIT_USAGE)
    info = docker_own(ctx, name)
    hc, probs = info["HostConfig"], []
    if hc.get("Privileged") or hc.get("CapAdd") or "ALL" not in (hc.get("CapDrop") or []) or not hc.get("ReadonlyRootfs"):
        probs.append("privilèges ou racine en écriture")
    if hc.get("PortBindings") or hc.get("PublishAllPorts"):
        probs.append("port publié (la passerelle ne doit pas être joignable depuis l'hôte ou le réseau local)")
    if hc.get("NetworkMode") != g["upstream_network"] or str(info["Config"].get("User", "")).split(":")[0] in ("", "0", "root"):
        probs.append("réseau ou utilisateur inattendu")
    got = {(m.get("Source"), m.get("Destination"), bool(m.get("RW"))) for m in info.get("Mounts") or []}
    if got != {(s, d, rw) for s, d, rw in mounts} or any("docker.sock" in str(m[0]) for m in got):
        probs.append(f"montages inattendus : {sorted(got)}")
    if probs:
        docker_finalize(ctx, name, gdir)
        die(f"passerelle : politique non respectée, non démarrée — {probs}", EXIT_CRITICAL)
    if docker("start", name).returncode != 0:
        die("passerelle : démarrage impossible", EXIT_USAGE)
    log = gdir / "log" / "gateway.jsonl"
    for _ in range(100):
        if log.exists() and '"listening"' in log.read_text(encoding="utf-8"):
            break
        time.sleep(0.1)
    else:
        docker_finalize(ctx, name, gdir)
        die("passerelle : pas prête après 10 s", EXIT_USAGE)
    ctx.event(run, "gateway_started", container=name, routes=sorted(g["routes"]), upstream_network=g["upstream_network"])
    return name


def gateway_attach_team(ctx, run, key, n, team, d):
    """Réseau interne dédié à la tentative (aucune route sortante ; seuls l'équipe et la passerelle y sont) + jeton."""
    import secrets as _secrets
    gname = gateway_ensure(ctx, run)
    net = container_name(ctx, f"{run}-{key}-a{n}-net")
    p = docker("network", "create", "--internal", "--label", f"{DOCKER_LABEL}=1", "--label", f"pmx.root={ctx.root}", "--label", f"pmx.run={run}", net)
    if p.returncode != 0 or docker("network", "connect", "--alias", "pmx-gateway", net, gname).returncode != 0:
        die(f"réseau d'équipe {net} : création ou connexion impossible", EXIT_USAGE)
    subnet = json.loads(docker("network", "inspect", net).stdout)[0]["IPAM"]["Config"][0]["Subnet"]
    token = "pmxgw_" + _secrets.token_hex(24)
    ttl = int((ctx.o.get("gateway") or {}).get("token_ttl_s") or ctx.o["team_timeout_s"] + 300)
    h = hashlib.sha256(token.encode()).hexdigest()
    gateway_tokens_update(ctx, run, add={h: {"team": team, "task": key, "attempt": n, "routes": d["gateway_routes"], "subnet": subnet,
                                             "expires": time.time() + ttl, "quota": d["gateway_quota"] or {}}})
    return {"network": net, "subnet": subnet, "token_fp": h[:8], "token_sha256": h, "routes": d["gateway_routes"]}, token


def gateway_detach_team(ctx, run, gw):
    """Révocation du jeton, déconnexion de la passerelle, suppression du réseau de la tentative (ressources pmx seulement)."""
    gateway_tokens_update(ctx, run, remove=[gw["token_sha256"]])
    ni = docker("network", "inspect", gw["network"])
    if ni.returncode == 0:
        labels = json.loads(ni.stdout)[0].get("Labels") or {}
        if labels.get(DOCKER_LABEL) == "1" and labels.get("pmx.root") == str(ctx.root):
            for cid in (json.loads(ni.stdout)[0].get("Containers") or {}):
                docker("network", "disconnect", "--force", gw["network"], cid)
            docker("network", "rm", gw["network"])


def gateway_reap(ctx, run, st):
    """Arrête la passerelle quand plus aucune tentative `gateway` n'est en cours (preuve gardée dans ai_memory/runs/<run>/gateway/)."""
    if not ctx.o.get("gateway") or not any(t["attempts"] and t["attempts"][-1].get("gateway") for t in st["tasks"].values()):
        return
    live = [k for k, t in st["tasks"].items() if t["attempts"] and t["attempts"][-1].get("gateway") and wi_status(ctx, t["wi"]) == "IN_PROGRESS"]
    name = container_name(ctx, f"{run}-gateway")
    if not live and docker_own(ctx, name):
        docker_finalize(ctx, name, gateway_dir(ctx, run))
        ctx.event(run, "gateway_stopped", container=name)


def run_docker_agent(ctx, acfg, prompt_file, out_file, cwd, mode, log, timeout, name, gateway=None):
    d, errs = docker_settings(ctx, acfg)
    if errs:
        log.write(f"[{now()}] configuration docker refusée : {errs}\n")
        return 126, None
    if d["network"] == "gateway" and (mode != "write" or not gateway):
        gateway = None  # revue / débat : jamais de réseau ; une équipe sans jeton émis par dispatch non plus
        if mode == "write":
            log.write(f"[{now()}] équipe `gateway` sans réseau ni jeton émis par dispatch : refus\n")
            return 126, None
    argv_in = [x.format(prompt_file="/pmx/brief.md", cwd="/work", mode=mode) for x in d["argv"]]
    rc, out, err, ev, why = docker_exec(ctx, d, name, argv_in, cwd, mode, timeout, pathlib.Path(log.name).parent, log=log, prompt_file=prompt_file,
                                        gateway=gateway)
    log.write(out[-20000:] + "\n" + err[-20000:] + f"\n[{now()}] exit {rc} (container {name}, oom={bool(ev and ev['state'].get('OOMKilled'))}{', ' + why if why else ''})\n")
    if rc != 124:
        write_atomic(pathlib.Path(out_file), out)
    return rc, ev


def runner_label(kind):
    return ("docker — isolated container (no network, no HOME, no secrets, read-only root, checkout only)" if kind == "docker"
            else "host — NOT isolated (3.1 mode): team code runs on the host with the user's rights")


def verify_runner(ctx):
    """→ (« host » | « docker », réglages, erreurs). `orchestration.verify_runner` : où s'exécutent les commandes de test
    de confiance (verify, integrate). « host » = comportement 3.1 : le code des équipes s'exécute sur l'hôte, NON isolé."""
    vr = ctx.o.get("verify_runner") or {"adapter": "host"}
    if vr.get("adapter", "host") == "host":
        return "host", None, []
    if vr.get("adapter") != "docker":
        return "docker", None, [f"verify_runner : adaptateur inconnu {vr.get('adapter')!r} (host | docker)"]
    raw = vr.get("docker")
    if not isinstance(raw, dict):
        return "docker", None, ["verify_runner : bloc `docker` requis (image, limites)"]
    errs = ["verify_runner.docker : `argv` interdit (seules les commandes de test de confiance s'exécutent)"] if "argv" in raw else []
    d, more = docker_settings(ctx, {"docker": {**raw, "argv": ["-"]}}, allow_gateway=False)  # argv = chaque commande de confiance ; réseau none seulement
    return "docker", d, errs + more


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
    chk("docker (optionnel)", ["docker", "version", "--format", "{{.Server.Version}}"])
    for name, st, info in rows:
        print(f"  {'✔' if st == 'ok' else '–'} {name:<20} {st:<8} {info}")
    remotes = git(ctx.root, "remote").split()
    print(f"  {'⚠' if remotes else '✔'} remotes : {remotes or 'aucun (pilote local)'}")
    print(f"  backend : {ctx.backend} · orchestration.enabled : {ctx.o['enabled']} · équipes : {', '.join(ctx.o['teams']) or '—'}")
    print(f"  worktrees : {ctx.wt_root} · intégration : {ctx.o['integration_branch']} (protégée : {ctx.is_protected(ctx.o['integration_branch'])})")
    for team, t in ctx.o["teams"].items():
        print(f"  équipe {team} : adaptateur {t.get('adapter')} ({t.get('label', '')})")
        if t.get("adapter") == "docker":
            d, errs = docker_settings(ctx, t)
            img = docker("image", "inspect", "--format", "{{.Id}}", d["image"] or "-") if not errs else None
            for e in errs + ([f"image {d['image']} absente localement (--pull never)"] if img is not None and img.returncode != 0 else []):
                print(f"    ✘ {e}")
            if not errs:
                print(f"    docker : {d['image']} · cpus {d['cpus']} · mémoire {d['memory']} · pids {d['pids']} · réseau none · racine RO · cap-drop ALL")
    cprobs = confinement_problems(ctx)
    print(f"  {'✘' if cprobs else '✔' if confined(ctx) else '–'} confinement natif des CLI : {ctx.o.get('confinement') or 'non'}" + (f" — {'; '.join(cprobs)}" if cprobs else ""))
    mprobs = bypass_problems(ctx) + mode_problems(ctx)
    print(f"  {'✘' if mprobs else '✔'} profil : {ctx.o.get('mode') or 'default'}" + (f" — {'; '.join(mprobs)}" if mprobs else ""))
    kind, d, errs = verify_runner(ctx)
    print(f"  {'✔' if kind == 'docker' and not errs else '⚠'} exécution des tests (verify, integrate) : {runner_label(kind)}"
          + (f" — {'; '.join(errs)}" if errs else f" — image {d['image']}" if d else ""))
    for c in trusted_commands(ctx) or ["(aucune : tout plan sera refusé)"]:
        prob = command_problem(ctx, c) if trusted_commands(ctx) else "à déclarer dans verify_commands / allowed_test_commands"
        print(f"  {'✘' if prob else '✔'} commande de test de confiance : {c}{' — ' + prob if prob else ''}")
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
    if a.action == "next":
        require_confinement(ctx)
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
        if t.get("test_command") and (prob := command_problem(ctx, t["test_command"])):
            errs.append(f"{t['key']} : {prob}")
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


def special_files(wt, limit=20000):
    """FIFO, sockets, périphériques du worktree : invisibles pour `git status`, jamais produits par une équipe légitime."""
    found, stack, n = [], [pathlib.Path(wt)], 0
    while stack and n < limit:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            n += 1
            if e.name == ".git" and e.path.count(os.sep) == str(wt).rstrip(os.sep).count(os.sep) + 1:
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append(pathlib.Path(e.path))
            elif not e.is_file(follow_symlinks=False) and not e.is_symlink():
                found.append(os.path.relpath(e.path, wt))
    return found


def gitfile_problem(ctx, wt):
    """Le pointeur `.git` d'un worktree est écrit par Git, dans un répertoire où l'équipe peut écrire. Redirigé vers un faux
    dépôt, il ferait lire à Git (lancé par pmx sur l'hôte) une configuration choisie par l'équipe (filtres, pilotes…).
    Contrôlé AVANT toute commande git sur le worktree : pointeur vers `<dépôt>/.git/worktrees/<nom>` qui pointe en retour."""
    gf = pathlib.Path(wt) / ".git"
    try:
        if gf.is_symlink() or not gf.is_file():
            return "pointeur .git remplacé (lien ou répertoire)"
        txt = gf.read_text(encoding="utf-8", errors="replace").strip()
        if not txt.startswith("gitdir: ") or "\n" in txt:
            return "pointeur .git modifié"
        target = pathlib.Path(txt[8:]).resolve()
        admin = (ctx.root / ".git" / "worktrees").resolve()
        if target.parent != admin or (target / "gitdir").read_text(encoding="utf-8").strip() != str(gf.resolve()):
            return f"pointeur .git redirigé ({target})"
    except OSError as e:
        return f"pointeur .git illisible ({type(e).__name__})"
    return None


def scope_check(ctx, task, wt, base):
    """→ (violations critiques, chemins modifiés). Hors périmètre, sensible ou suppression = échec critique."""
    if pathlib.Path(wt).exists() and (why := gitfile_problem(ctx, wt)):
        return [f".git : {why} — aucune commande git lancée sur ce worktree"], set()
    paths, deleted = changed_paths(wt, base)
    allowed = list(task["files"]) + [f"ai_memory/*__ROLE-*__{task['wi']}.md"]
    bad = [f"{p} : fichier spécial (FIFO, socket ou périphérique)" for p in special_files(wt)]
    for p in sorted(paths):
        cat = classify(p, ctx.o["sensitive_paths"])
        if cat:
            bad.append(f"{p} : chemin sensible ({cat})")
        elif os.path.islink(os.path.join(wt, p)):  # suivi par les tests et outils de l'hôte : jamais accepté d'une équipe
            bad.append(f"{p} : lien symbolique → {os.readlink(os.path.join(wt, p))} (validation humaine)")
        elif p in deleted:
            bad.append(f"{p} : suppression (validation humaine)")
        elif not match_any(p, allowed):
            bad.append(f"{p} : hors périmètre de {task['wi']}")
    return bad, paths


def team_brief(ctx, st, key, attempt, wt, report):
    t = st["tasks"][key]
    if ctx.o["teams"][t["team"]].get("adapter") == "docker":  # chemins vus depuis le conteneur
        wt = "/work"
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
    if any(wi_status(ctx, t["wi"]) == "OPEN" for t in st["tasks"].values()):
        require_confinement(ctx)
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
                    if subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "merge-base", "--is-ancestor", st["tasks"][d]["commit"], base], env=git_env()).returncode != 0:
                        die(f"{key} : dépendance {d} non intégrée dans {ctx.o['integration_branch']}")
            n = len(t["attempts"]) + 1
            branch = f"{ctx.o['branch_prefix']}{run.lower()}/{key}" + (f"-a{n}" if n > 1 else "")
            if ctx.is_protected(branch):
                die(f"branche protégée refusée : {branch}")
            team = ctx.o["teams"][t["team"]]
            if team.get("adapter") == "docker" and (errs := docker_settings(ctx, team)[1]):
                die(f"{key} : configuration docker de {t['team']} refusée — " + " ; ".join(errs), EXIT_USAGE)
            wt = ctx.wt_root / f"{key}-a{n}"
            ctx.wt_root.mkdir(parents=True, exist_ok=True)
            git(ctx.root, "worktree", "add", "-q", "-b", branch, str(wt), base)
            tdir = ctx.run_dir(run) / "tasks" / key
            tdir.mkdir(parents=True, exist_ok=True)
            report = tdir / f"report-a{n}.md"
            brief = tdir / f"brief-a{n}.md"
            write_atomic(brief, team_brief(ctx, st, key, n, wt, report))
            att = {"n": n, "branch": branch, "worktree": str(wt), "base": base, "brief": str(brief), "report": str(report),
                   "adapter": team.get("adapter"), "pid": None, "started": now(), "ended": None, "result": None}
            env_team = None
            if team.get("adapter") == "docker":
                att["container"] = container_name(ctx, f"{run}-{key}-a{n}")
                d = docker_settings(ctx, team)[0]
                if d["network"] == "gateway":  # réseau interne dédié + jeton ; le jeton ne quitte la mémoire que vers le client docker
                    att["gateway"], token = gateway_attach_team(ctx, run, key, n, t["team"], d)
                    env_team = {**os.environ, "PMX_TEAM_GATEWAY_TOKEN": token}
                    ctx.event(run, "gateway_team_attached", task=key, attempt=n, network=att["gateway"]["network"], subnet=att["gateway"]["subnet"],
                              routes=att["gateway"]["routes"], token_fp=att["gateway"]["token_fp"])
            if team.get("adapter") == "drop":
                waiting.append((key, brief, report))
            else:
                log = open(tdir / f"team-a{n}.log", "a")
                p = subprocess.Popen([sys.executable, "-I", str(pathlib.Path(__file__).resolve()), "--root", str(ctx.root), "_team",
                                      "--run", run, "--task", key, "--attempt", str(n)],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=env_team)
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
    with ctx.lock():  # dispatch enregistre la tentative APRÈS le lancement : attendre qu'il ait fini (verrou)
        st = ctx.load_run(a.run)
    t = st["tasks"][a.task]
    att = t["attempts"][int(a.attempt) - 1]
    tdir = ctx.run_dir(a.run) / "tasks" / a.task
    ctx.event(a.run, "team_process_begin", task=a.task, attempt=int(a.attempt))
    started = now()
    gw = att.get("gateway")
    token = os.environ.pop("PMX_TEAM_GATEWAY_TOKEN", None)
    try:
        rc = run_agent_sync(ctx, ctx.o["teams"][t["team"]], att["brief"], att["report"], att["worktree"], "write",
                            tdir / f"team-a{a.attempt}.log", ctx.o["team_timeout_s"], name=att.get("container"),
                            gateway=(gw["network"], token, gw["routes"]) if gw and token else None)
    finally:
        if gw:  # jeton révoqué et réseau retiré dès la fin du conteneur
            gateway_detach_team(ctx, a.run, gw)
    res = {"exit": rc, "started": started, "ended": now()}
    if att.get("container"):
        evf = tdir / f"container-{att['container']}.json"
        state = json.loads(evf.read_text(encoding="utf-8"))["state"] if evf.exists() else {}
        res.update(container=att["container"], oom=bool(state.get("OOMKilled")))
    write_atomic(tdir / f"result-a{a.attempt}.json", json.dumps(res) + "\n")
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
        if att.get("container"):  # le conteneur appartient au démon : tuer le client docker ne l'arrête pas
            docker_stop(ctx, att["container"])
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
    for key in stopped:  # preuve de chaque conteneur arrêté (état, configuration), puis suppression du seul conteneur pmx
        if (c := st["tasks"][key]["attempts"][-1].get("container")):
            docker_finalize(ctx, c, ctx.run_dir(run) / "tasks" / key)
        if (gw := st["tasks"][key]["attempts"][-1].get("gateway")):
            gateway_detach_team(ctx, run, gw)
    gateway_reap(ctx, run, st)
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
                if att.get("container"):  # client docker disparu (coupure) : le conteneur orphelin est arrêté, preuve gardée
                    docker_finalize(ctx, att["container"], ctx.run_dir(a.run) / "tasks" / key)
                if att.get("gateway"):
                    gateway_detach_team(ctx, a.run, att["gateway"])
                _finish_attempt(ctx, st, key, {"exit": None, "ended": now(), "interrupted": True})
        ctx.save_run(st)
        gateway_reap(ctx, a.run, st)
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


FIELD = re.compile(r"^\W*(status|open blockers)\W*:\W*(.*)$", re.I)


def report_blocker(rtext):
    """Motif déclaré par l'équipe : champs `Status` (s'il n'est pas DONE) et `Open blockers` de la note de rôle — en
    début de ligne seulement (pas une mention dans « Proposed Rules ») ; un champ vide prend ses lignes de liste suivantes."""
    lines = rtext.splitlines()
    keep = []
    for i, l in enumerate(lines):
        m = FIELD.match(l)
        if not m:
            continue
        val = m.group(2).strip(" *_")
        if m.group(1).lower() == "status":
            if not re.match(r"done\b", val, re.I):
                keep.append(f"status: {val}")
            continue
        if not val:
            val = " ".join(x.strip(" -*") for x in lines[i + 1:i + 6] if x.strip().startswith(("-", "*")) and not FIELD.match(x))
        keep.append(f"open blockers: {val}")
    first = next((l for l in lines if l.strip()), "")
    return " | ".join(keep) or first


def failure_record(ctx, t, att, res, rtext, bad, paths):
    """→ (kind, detail, signature, preuves). `kind` est structurel ; `detail` est normalisé."""
    if res.get("interrupted"):
        kind, detail = "interrupted", ""
    elif res.get("exit") == 124:
        kind, detail = "timeout", ""
    elif bad:
        kind, detail = "scope", "; ".join(bad)
    elif res.get("oom"):
        kind, detail = f"exit-{res.get('exit')}", "oom-killed: container memory limit reached"
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

def trusted_commands(ctx):
    """Commandes de test de confiance : écrites par l'humain dans `.claude/project-manager.config.json` (chemin garde-fou,
    jamais modifiable par une équipe). Un plan proposé par un agent ne peut que les référencer, pas en introduire."""
    return list(dict.fromkeys(c for c in [*ctx.o["verify_commands"], *ctx.o["allowed_test_commands"]] if isinstance(c, str)))


def command_problem(ctx, cmd):
    """Raison de refuser une commande de test, ou None. Revérifiée à chaque exécution (run.json n'est pas une source de confiance)."""
    if not isinstance(cmd, str) or not cmd.strip():
        return "commande de test vide"
    if cmd not in trusted_commands(ctx):
        return f"commande de test non approuvée (absente de verify_commands / allowed_test_commands) : {cmd!r}"
    if SHELL_META.search(cmd):
        return f"métacaractère shell interdit (commandes exécutées sans shell ; une commande par entrée) : {cmd!r}"
    try:
        shlex.split(cmd)
    except ValueError as e:
        return f"commande de test illisible ({e}) : {cmd!r}"
    return None


def run_checks(ctx, wt, commands, timeout, evidence_dir, label):
    """Exécute les commandes de confiance sur un checkout jetable : dans un conteneur isolé (`verify_runner` docker) ou,
    en mode 3.1, sur l'hôte (NON isolé). Un résultat portant `inconclusive` n'est ni PASS ni FAIL : il bloque."""
    bad = [p for p in map(lambda c: command_problem(ctx, c), commands) if p]
    if bad:  # les appelants filtrent avant ; ceinture et bretelles
        raise RuntimeError("; ".join(bad))
    kind, d, errs = verify_runner(ctx)
    if errs:
        raise RuntimeError("; ".join(errs))
    results = []
    for i, c in enumerate(commands):
        t0 = time.time()
        if kind == "docker":
            name = container_name(ctx, f"verify-{label}-{i}-{time.time_ns()}")
            rc, out, err, ev, why = docker_exec(ctx, d, name, shlex.split(c), wt, "verify", timeout, evidence_dir, labels={"label": label})
            results.append({"command": c, "exit": rc, "seconds": round(time.time() - t0, 2), "output": tail(out + err), "runner": "docker",
                             "container": name, "inconclusive": why})
            continue
        try:
            p = subprocess.run(shlex.split(c), cwd=str(wt), capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            rc, out = p.returncode, p.stdout + p.stderr
        except subprocess.TimeoutExpired:
            rc, out = 124, f"TIMEOUT {timeout}s"
        except OSError as e:
            rc, out = 127, f"{type(e).__name__}: {e}"
        results.append({"command": c, "exit": rc, "seconds": round(time.time() - t0, 2), "output": tail(out), "runner": "host"})
    return results


def repo_snapshot(ctx):
    """Références et état du checkout principal : les commandes de test ne doivent modifier ni l'un ni l'autre."""
    main = [l for l in git(ctx.root, "status", "--porcelain=v1", "-uall").splitlines() if not l[3:].startswith(("ai_memory/runs/", "ai_memory/.pmx.lock"))]
    return {"refs": git(ctx.root, "for-each-ref", "--format=%(refname) %(objectname)").splitlines(), "main": main}


def checkout_problems(ctx, wdir, head, before):
    """Écarts d'intégrité après les tests d'un checkout jetable : HEAD déplacé, fichiers modifiés ou ajoutés, références ou
    checkout principal touchés. Tout écart rend le verdict non concluant (jamais PASS)."""
    probs, after = [], repo_snapshot(ctx)
    cur = git(wdir, "rev-parse", "HEAD", check=False)
    if cur != head:
        probs.append(f"HEAD du checkout déplacé ({head[:10]} → {cur[:10] or 'illisible'})")
    dirty = git(wdir, "status", "--porcelain=v1", "-uall", check=False).splitlines()
    if dirty:
        probs.append(f"checkout modifié par les commandes ({len(dirty)} chemin(s)) : {', '.join(dirty[:10])}")
    refs = sorted(set(before["refs"]) ^ set(after["refs"]))
    if refs:
        probs.append(f"références git modifiées pendant les tests : {', '.join(refs[:10])}")
    main = sorted(set(before["main"]) ^ set(after["main"]))
    if main:
        probs.append(f"checkout principal modifié pendant les tests : {', '.join(main[:10])}")
    return probs


def preserve_evidence(ctx, run, name, wdir, probs, res):
    """Preuve écrite hors du checkout (conservé, jamais supprimé par pmx) : état, diff suivi, fichiers ajoutés, sorties."""
    p = ctx.run_dir(run) / "integrity" / f"{name}.txt"
    parts = [f"# {name} — {now()}", f"checkout conservé : {wdir}", "", "## Écarts", *[f"- {x}" for x in probs], "",
             "## git status", git(wdir, "status", "--porcelain=v1", "-uall", check=False), "",
             "## git diff HEAD (fichiers suivis)", git(wdir, "diff", "HEAD", check=False)[-200000:], "",
             "## Commandes", *[f"$ {r['command']} → exit {r['exit']} ({r['seconds']}s)\n{r['output']}" for r in res]]
    write_atomic(p, "\n".join(parts) + "\n")
    return p


def cmd_verify(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    keys = [a.task] if a.task else [k for k, t in st["tasks"].items() if wi_status(ctx, t["wi"]) == "READY_FOR_VERIFICATION"]
    worst = EXIT_OK
    for key in keys:
        t = st["tasks"][key]
        cmds = [t["test_command"]] + [c for c in ctx.o["verify_commands"] if c != t["test_command"]]
        bad = [p for p in map(lambda c: command_problem(ctx, c), cmds) if p] + verify_runner(ctx)[2]
        if bad:
            ctx.event(a.run, "verify_refused", task=key, reasons=bad)
            print(f"  ✘ {key} : vérification REFUSÉE, rien n'a été exécuté — {'; '.join(bad)}")
            worst = EXIT_HUMAN
            continue
        vdir = ctx.wt_root / f"_verify-{key}-{t['commit'][:8]}"
        if vdir.exists():
            die(f"checkout de vérification déjà présent (preuve d'une vérification précédente ?) : {vdir}", EXIT_HUMAN)
        before = repo_snapshot(ctx)
        git(ctx.root, "worktree", "add", "-q", "--detach", str(vdir), t["commit"])
        res = run_checks(ctx, vdir, cmds, ctx.o["verify_timeout_s"], ctx.run_dir(a.run) / "verify" / key, f"{key}-{t['commit'][:8]}")
        runner = verify_runner(ctx)[0]
        probs = [f"vérification non concluante ({r['command']}) : {r['inconclusive']}" for r in res if r.get("inconclusive")]
        probs += checkout_problems(ctx, vdir, t["commit"], before)
        if not probs:
            rm = subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "worktree", "remove", str(vdir)], capture_output=True, text=True, env=git_env())
            if rm.returncode != 0 or vdir.exists():
                probs.append(f"nettoyage du checkout impossible : {rm.stderr.strip() or 'répertoire toujours présent'}")
        evidence = preserve_evidence(ctx, a.run, f"verify-{key}-{t['commit'][:8]}", vdir, probs, res) if probs else None
        verdict = "INCONCLUSIVE" if probs else "PASS" if all(r["exit"] == 0 for r in res) else "FAIL"
        ev = "\n".join(f"$ {r['command']}  → exit {r['exit']} ({r['seconds']}s)\n{r['output']}" for r in res)
        integ = "clean (HEAD, files, refs and main checkout unchanged; checkout removed)" if not probs else \
            "ALTERED — " + " | ".join(probs) + f"\n- Checkout kept as evidence: {vdir}\n- Integrity evidence: {evidence}"
        nxt = {"PASS": "cross review", "FAIL": "developer (new attempt)", "INCONCLUSIVE": "human triage (pmx reopen --by human:<name>) — no automatic retry"}[verdict]
        note = role_note(ctx, "verifier", t["wi"], f"# verifier note — {t['wi']}\n\n- Work item: {t['wi']}\n- Role: verifier (pmx, clean detached checkout of {t['commit'][:10]}, tree {t['tree'][:10]})\n"
                         f"- Status: {verdict}\n- Commands run (trusted, no shell): {cmds}\n- Runner: {runner_label(runner)}\n- Checkout integrity: {integ}\n"
                         f"- Evidence:\n```\n{ev}\n```\n- Next actions: {nxt}\n")
        with ctx.lock():
            st = ctx.load_run(a.run)
            st["tasks"][key]["verify"] = {"verdict": verdict, "commit": t["commit"], "tree": t["tree"], "ts": now(), "note": str(note), "results": res,
                                          "integrity": probs, "evidence": str(evidence) if evidence else None, "runner": runner}
            if verdict == "PASS":
                wi_set(ctx, t["wi"], status="READY_FOR_REVIEW", links=str(note))
            elif verdict == "INCONCLUSIVE":
                # écart d'intégrité : signal de sécurité, pas un échec ordinaire → jamais de relance automatique
                wi_set(ctx, t["wi"], status="BLOCKED", links=str(note), blocker=f"verifier INCONCLUSIVE: {probs[0]} — evidence {evidence}; human triage")
                worst = EXIT_HUMAN
            else:
                first = next((r for r in res if r["exit"] != 0), res[0])
                err = next((l for l in first["output"].splitlines() if re.search(r"not ok|error|assert|fail", l, re.I)), "")
                detail = normalize_cause(f"{first['command']} → exit {first['exit']} :: {err}")
                st["tasks"][key]["attempts"][-1]["failure"] = f"verifier-fail: {detail}"
                decide_retry(ctx, st, key, {"attempt": len(t["attempts"]), "kind": "verifier-fail", "detail": detail, "signature": f"verifier-fail: {detail}",
                                            "evidence": {"exit": first["exit"], "changed_files": [], "report_excerpt": first["output"][-1500:],
                                                         "report": str(note), "log": str(note)}, "ts": now()})
                worst = worst if worst == EXIT_HUMAN else EXIT_FAIL
            ctx.save_run(st)
        ctx.event(a.run, "verified", task=key, verdict=verdict, commit=t["commit"], integrity=probs, runner=runner)
        print(f"  {'✔' if verdict == 'PASS' else '✘'} {key} : verifier {verdict} ({t['commit'][:10]}) — exécution : {'conteneur isolé' if runner == 'docker' else 'HÔTE, non isolée (mode 3.1)'}")
        for x in probs:
            print(f"    ⚠ {x}")
        if probs:
            print(f"    checkout conservé : {vdir} · preuve : {evidence} · arbitrage humain")
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
    require_confinement(ctx)
    rdir = ctx.run_dir(a.run) / "reviews"
    rdir.mkdir(parents=True, exist_ok=True)
    teams = list(ctx.o["teams"])
    waiting = []
    for key, t in st["tasks"].items():
        if wi_status(ctx, t["wi"]) != "READY_FOR_REVIEW" or (t.get("review") and t["review"]["commit"] == t["commit"]):
            continue
        reviewer = ctx.o["cross_review"].get(t["team"]) or next((x for x in teams if x != t["team"]), t["team"])
        acfg = ctx.o["teams"][reviewer].get("reviewer") or ctx.o["teams"][reviewer]
        diff = git(ctx.root, "diff", "--no-ext-diff", "--no-textconv", f"{t['attempts'][-1]['base']}..{t['commit']}")
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
        rm = subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "worktree", "remove", str(cdir)], capture_output=True, text=True, env=git_env())
        if rm.returncode != 0:
            print(f"  ⚠ checkout de revue modifié, conservé : {cdir}")
    ctx.event(run, "reviewed", task=key, verdict=verdict, by=source)
    print(f"  {'✔' if verdict == 'APPROVE' else '⚠'} {key} : revue {verdict} ({source}) → {rel}  — triage manager (review-triage.md)")
    return EXIT_OK if verdict == "APPROVE" else EXIT_HUMAN


# ---------------------------------------------------------------- intégration locale contrôlée

def agent_session():
    """Variables d'environnement d'une CLI d'agent présentes dans ce processus (liste vide hors agent)."""
    return [v for v in AGENT_ENV if os.environ.get(v)]


def open_human_tty():
    """Terminal de contrôle du processus, ou (None, raison). Ce n'est PAS une authentification : un garde-fou contre une
    intégration réelle déclenchée par un agent (outil Bash sans terminal, ou variables d'agent présentes)."""
    seen = agent_session()
    if seen:
        return None, f"session d'agent détectée ({', '.join(seen)}) : l'intégration réelle se lance par l'humain, dans son propre terminal"
    try:
        return os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY), None
    except OSError as e:
        return None, f"aucun terminal interactif ({e.strerror}) : l'intégration réelle se lance par l'humain, dans son propre terminal"


def cmd_integrate(ctx, a):
    ctx.require_enabled()
    st = ctx.load_run(a.run)
    target = ctx.o["integration_branch"]
    checks, fail, human = [], [], []
    def c(ok, label, needs_human=False):
        checks.append(("✔" if ok else "✘") + " " + label)
        if not ok:
            (human if needs_human else fail).append(label)
    pol_p = ctx.root / ctx.o["integration_policy"]
    pol = json.loads(pol_p.read_text(encoding="utf-8")) if pol_p.exists() else {}
    c(bool(pol), f"politique explicite présente ({ctx.o['integration_policy']})")
    c(pol.get("mode") == "local-only", "politique : mode local-only")
    c(pol.get("target_branch") == target, f"politique : cible = {target}")
    c(not ctx.is_protected(target), f"cible non protégée ({target})")
    upstream = subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "rev-parse", "--abbrev-ref", f"{target}@{{upstream}}"], capture_output=True, text=True, env=git_env())
    c(upstream.returncode != 0, "cible sans branche amont (aucun push possible par pmx, qui n'en contient aucun)")
    tty = None
    if not a.dry_run:
        # --approved-by est une déclaration (nom consigné), pas une preuve : la preuve est la confirmation saisie au terminal
        c(bool(a.approved_by), "accord humain déclaré (--approved-by)", needs_human=True)
        tty, why = open_human_tty()
        c(tty is not None, "confirmation humaine possible au terminal" + (f" — {why}" if why else ""), needs_human=True)
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
    cmds = list(dict.fromkeys(ctx.o["verify_commands"] + [st["tasks"][k]["test_command"] for k in keys]))
    bad = [p for p in map(lambda x: command_problem(ctx, x), cmds) if p]
    c(not bad, "commandes de test de confiance" + (f" — {'; '.join(bad)}" if bad else ""), needs_human=True)
    runner, _d, rerrs = verify_runner(ctx)
    c(not rerrs, f"exécuteur des tests : {runner}" + (f" — {'; '.join(rerrs)}" if rerrs else ""), needs_human=True)
    if pol.get("require_isolated_verification"):
        c(runner == "docker", "politique : tests sur l'arbre fusionné en conteneur isolé (verify_runner docker)")
        for k in keys:
            c((st["tasks"][k].get("verify") or {}).get("runner") == "docker", f"{k} : vérification faite en conteneur isolé")
    print("\n".join(checks))
    if fail or human:
        if tty is not None:
            os.close(tty)
        ctx.event(a.run, "integration_refused", failed=fail + human)
        print("intégration REFUSÉE — rien n'a été modifié")
        return EXIT_FAIL if fail else EXIT_HUMAN
    exists = subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "rev-parse", "--verify", "-q", f"refs/heads/{target}"], capture_output=True, text=True, env=git_env())
    old = exists.stdout.strip() if exists.returncode == 0 else None
    start = old or st["base"]
    iwt = ctx.wt_root / f"_integration-{int(time.time())}"
    git(ctx.root, "worktree", "add", "-q", "--detach", str(iwt), start)
    merged, keep = [], False
    try:
        for k in keys:
            t = st["tasks"][k]
            p = subprocess.run([*GIT_SAFE, "-C", str(iwt), *GIT_ID, "merge", "--no-ff", "--no-edit", "-m", f"pilot: integrate {t['wi']} ({k})", t["commit"]], capture_output=True, text=True, env=git_env())
            if p.returncode != 0:
                subprocess.run([*GIT_SAFE, "-C", str(iwt), "merge", "--abort"], capture_output=True, env=git_env())
                ctx.event(a.run, "integration_conflict", task=k)
                print(f"✘ conflit à l'intégration de {k} — {target} inchangée ; arbitrage humain\n{tail(p.stdout + p.stderr, 20)}")
                return EXIT_HUMAN
            merged.append(k)
        # candidat figé AVANT les tests : un test qui déplace HEAD ne peut pas changer ce qui sera intégré
        new, tree = git(iwt, "rev-parse", "HEAD"), git(iwt, "rev-parse", "HEAD^{tree}")
        before = repo_snapshot(ctx)
        res = run_checks(ctx, iwt, cmds, ctx.o["verify_timeout_s"], ctx.run_dir(a.run) / "integrate", f"integration-{new[:8]}")
        verdict = "PASS" if all(r["exit"] == 0 for r in res) else "FAIL"
        for r in res:
            print(f"  $ {r['command']} → exit {r['exit']} ({'conteneur isolé' if r['runner'] == 'docker' else 'HÔTE, non isolé'})")
        probs = [f"tests non concluants ({r['command']}) : {r['inconclusive']}" for r in res if r.get("inconclusive")]
        probs += checkout_problems(ctx, iwt, new, before)
        if probs:
            keep = True
            ev = preserve_evidence(ctx, a.run, f"integration-{new[:10]}", iwt, probs, res)
            ctx.event(a.run, "integration_integrity_failed", candidate=new, problems=probs, evidence=str(ev))
            for x in probs:
                print(f"  ⚠ {x}")
            print(f"✘ intégrité du checkout d'intégration NON vérifiée — {target} inchangée ; checkout conservé : {iwt} · preuve : {ev} · arbitrage humain")
            return EXIT_HUMAN
        if verdict != "PASS" or a.dry_run:
            ctx.event(a.run, "integration_dry_run" if a.dry_run else "integration_failed", verdict=verdict, candidate=new)
            print(f"{'simulation' if a.dry_run else 'ÉCHEC des tests'} : candidat {new[:10]} (tree {tree[:10]}) — {target} inchangée")
            return EXIT_OK if (a.dry_run and verdict == "PASS") else EXIT_FAIL
        expected = f"integrer {new[:10]}"
        os.write(tty, (f"\nIntégration locale demandée (déclarée par : {a.approved_by})\n  {target} : {(old or '(nouvelle)')[:10]} → {new[:10]} (tree {tree[:10]})\n"
                       f"  tâches : {', '.join(merged)} · tests : {verdict} · aucune opération distante\nPour confirmer, tapez exactement : {expected}\n> ").encode("utf-8"))
        answer = read_line(tty).strip()
        confirmed = {"via": "tty", "tty": os.ttyname(tty) if os.isatty(tty) else "?", "os_user": pwd_name(), "phrase": expected}
        os.close(tty)
        tty = None
        if answer != expected:
            ctx.event(a.run, "integration_not_confirmed", candidate=new, approved_by=a.approved_by)
            print(f"✘ confirmation absente ou incorrecte — {target} inchangée")
            return EXIT_HUMAN
        # mise à jour atomique et conditionnelle de la seule branche d'intégration locale
        git(ctx.root, "update-ref", "-m", f"pmx integrate {a.run} approved-by {a.approved_by} (tty-confirmed)", f"refs/heads/{target}", new, old or "")
    finally:
        if tty is not None:
            os.close(tty)
        if not keep:
            subprocess.run([*GIT_SAFE, "-C", str(ctx.root), "worktree", "remove", "--force", str(iwt)], capture_output=True, env=git_env())
    with ctx.lock():
        st = ctx.load_run(a.run)
        st.setdefault("integrations", []).append({"target": target, "commit": new, "merged": merged, "approved_by": a.approved_by, "confirmation": confirmed, "ts": now()})
        st["integration"] = {"target": target, "previous": old, "commit": new, "tree": tree, "approved_by": a.approved_by, "confirmation": confirmed, "ts": now(), "results": res, "merged": merged}
        for k in merged:
            wi_set(ctx, st["tasks"][k]["wi"], status="DONE", integrated=f"{target}@{new[:10]}", blocker="—")
        if all(wi_status(ctx, t["wi"]) == "DONE" for t in st["tasks"].values()):
            wi_set(ctx, st["parent_wi"], status="READY_FOR_REVIEW", integrated=f"{target}@{new[:10]} (local; merge to {st['base_branch']} is human-only)")
        ctx.save_run(st)
        p = ctx.root / "ai_doc" / f"DECISIONS__{st['parent_wi']}.md"
        prev = p.read_text(encoding="utf-8") if p.exists() else f"# Decision log — {st['parent_wi']}\n"
        write_atomic(p, prev.rstrip() + f"\n\n## {now()} — local integration\n- Approved by (declared): {a.approved_by}\n"
                     f"- Confirmation: typed on the controlling terminal ({confirmed['tty']}, OS user {confirmed['os_user']}) — a guard against agent-triggered integration, not an authentication\n"
                     f"- Target: {target} {old[:10] if old else '(new)'} → {new[:10]} (tree {tree[:10]})\n- Merged: {merged}\n- Tests on merged tree: {verdict}; checkout integrity: clean; runner: {runner_label(runner)}\n"
                     f"- Rollback: `git update-ref refs/heads/{target} {old or '<delete branch by hand>'} {new}`\n")
    ctx.event(a.run, "integrated", target=target, commit=new, previous=old, approved_by=a.approved_by, confirmation=confirmed, merged=merged)
    print(f"✔ intégré dans {target} : {(old or 'nouvelle')[:10]} → {new[:10]} · aucune fusion vers {st['base_branch']} (humaine uniquement)")
    return EXIT_OK


def read_line(fd, limit=200):
    buf = b""
    while len(buf) < limit and not buf.endswith(b"\n"):
        ch = os.read(fd, 1)
        if not ch:
            break
        buf += ch
    return buf.decode("utf-8", "replace")


def pwd_name():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError):
        return str(os.getuid())


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
