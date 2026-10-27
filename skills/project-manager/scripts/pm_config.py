#!/usr/bin/env python3
"""pm_config — configuration de projet du Project Manager V3 (lecture seule, aucune dépendance).

  pm_config.py resolve  --root <repo> [--config <fichier>]   → JSON résolu sur stdout
  pm_config.py validate --root <repo> [--config <fichier>]   → exit 0 valide, 1 invalide
  pm_config.py detect   --root <repo>                        → backend détecté sans configuration

Codes de sortie : 0 ok · 1 configuration invalide / référentiel illisible · 2 confirmation humaine requise
(backend détecté mais non configuré, ou projet neuf) · 3 conflit (signaux de deux registres) · 64 usage.
N'écrit jamais rien. Ne lit que la configuration, le fichier référentiel désigné et quelques fichiers
de signaux (ai_memory/, ai_rules/, CLAUDE.md).
"""
import argparse, json, pathlib, re, sys

SCHEMA = "pm-v3/1"
TOP_KEYS = {"schema", "work_items", "profile", "reading_map", "proof", "multi_team", "language", "orchestration", "_comment"}
GITLAB_KEYS = {"referential", "project", "integration_branch", "state_labels", "production_branch"}
BACKENDS = {"ledger", "gitlab-issues"}
TICK = re.compile(r"`([^`]+)`")


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def table_row(text, label):
    """Première ligne de tableau Markdown dont la 1re cellule contient `label` → 2e cellule, sinon None."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2 and label in cells[0]:
            return cells[1]
    return None


def detect(root):
    am, rules = root / "ai_memory", root / "ai_rules"
    ledger = [str(p.relative_to(root)) for p in (am / "WI_COUNTER.lock", am / "WORK_ITEMS.md") if p.exists()]
    gitlab = []
    rs = read(am / "REPO_STATE.md") or ""
    if re.search(r"^\s*-?\s*(active_issues|gitlab_reachable)\b", rs, re.M):
        gitlab.append("ai_memory/REPO_STATE.md (active_issues/gitlab_reachable)")
    if (am / "PENDING_GITLAB.md").exists():
        gitlab.append("ai_memory/PENDING_GITLAB.md")
    for f in sorted(rules.glob("*.md")) if rules.is_dir() else []:
        if re.search(r"gitlab issues?(/labels)? (are|is) the task registry", read(f) or "", re.I):
            gitlab.append(f"{f.relative_to(root)} (decision: GitLab issues registry)")
            break
    cm = read(root / "CLAUDE.md") or ""
    if table_row(cm, "labels d'état") or table_row(cm, "state labels"):
        gitlab.append("CLAUDE.md (referential with state labels)")
    if ledger and gitlab:
        return 3, {"result": "conflict", "ledger_signals": ledger, "gitlab_signals": gitlab}
    if ledger:
        return 0, {"result": "ledger", "ledger_signals": ledger}
    if gitlab:
        return 2, {"result": "gitlab-issues-to-confirm", "gitlab_signals": gitlab}
    return 2, {"result": "new-project", "suggested_backend": "ledger"}


def resolve(root, cfg_path):
    errors, warnings = [], []
    raw = read(cfg_path)
    if raw is None:
        code, det = detect(root)
        return code, {"configured": False, "detection": det}
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        return 1, {"configured": True, "errors": [f"JSON invalide : {e}"]}
    if cfg.get("schema") != SCHEMA:
        errors.append(f"schema attendu {SCHEMA!r}, trouvé {cfg.get('schema')!r}")
    for k in sorted(set(cfg) - TOP_KEYS):
        warnings.append(f"clé inconnue : {k}")
    wi = cfg.get("work_items") or {}
    backend = wi.get("backend")
    if backend not in BACKENDS:
        errors.append(f"work_items.backend doit valoir {sorted(BACKENDS)}, trouvé {backend!r}")
    out = {"configured": True, "backend": backend, "profile": cfg.get("profile"), "reading_map": cfg.get("reading_map") or ["CLAUDE.md"],
           "proof": cfg.get("proof"), "multi_team": cfg.get("multi_team") or {"enabled": False}, "language": cfg.get("language") or {"user": "fr", "memory": "en"}}
    if backend == "gitlab-issues":
        g = wi.get("gitlab") or {}
        for k in sorted(set(g) - GITLAB_KEYS):
            warnings.append(f"clé gitlab inconnue : {k}")
        ref = g.get("referential")
        direct = {k: g.get(k) for k in ("project", "integration_branch", "state_labels") if g.get(k) is not None}
        if ref and direct:
            errors.append("gitlab : référentiel ET valeurs directes — une seule source autorisée")
        vals = dict(direct)
        if ref:
            f = root / ref.get("file", "")
            text = read(f)
            if text is None:
                errors.append(f"référentiel illisible : {ref.get('file')!r}")
            else:
                rows = ref.get("rows") or {}
                for key, label in (("project", rows.get("project")), ("integration_branch", rows.get("integration")), ("state_labels", rows.get("state_labels"))):
                    if not label:
                        errors.append(f"référentiel : ligne non désignée pour {key}"); continue
                    cell = table_row(text, label)
                    toks = TICK.findall(cell) if cell else []
                    if not toks:
                        errors.append(f"référentiel : ligne {label!r} absente ou sans valeur entre accents graves"); continue
                    vals[key] = toks if key == "state_labels" else toks[0]
                vals["source"] = f"{ref.get('file')} (référentiel)"
        for k in ("project", "integration_branch", "state_labels"):
            if not vals.get(k):
                errors.append(f"gitlab.{k} manquant")
        if isinstance(vals.get("state_labels"), list) and len(set(vals["state_labels"])) != len(vals["state_labels"]):
            errors.append("gitlab.state_labels contient un doublon")
        vals["production_branch"] = g.get("production_branch")
        if vals.get("production_branch") and vals.get("production_branch") == vals.get("integration_branch"):
            errors.append("la branche de production ne peut pas être la branche d'intégration")
        out["gitlab"] = vals
        # cohérence avec le registre réel : un ledger présent en plus est un conflit
        code, det = detect(root)
        if det.get("ledger_signals"):
            errors.append(f"ledger présent dans un projet gitlab-issues : {det['ledger_signals']} (second registre interdit)")
    elif backend == "ledger":
        code, det = detect(root)
        if det.get("gitlab_signals"):
            warnings.append(f"signaux GitLab dans un projet ledger : {det['gitlab_signals']} (vérifier qu'aucun second registre n'est tenu)")
    orch = cfg.get("orchestration")
    if orch is not None:
        out["orchestration"] = {"enabled": bool(orch.get("enabled")), "teams": sorted((orch.get("teams") or {}))}
        if orch.get("enabled") and backend != "ledger":
            errors.append("orchestration (pilote pmx) : backend ledger requis ; gitlab-issues reste sur multi-team.md")
        if orch.get("enabled") and len(orch.get("teams") or {}) < 1:
            errors.append("orchestration.enabled sans équipe déclarée")
    prof = cfg.get("profile")
    if prof and not (root / prof).exists():
        errors.append(f"profil introuvable : {prof}")
    out["errors"], out["warnings"] = errors, warnings
    return (1 if errors else 0), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["resolve", "validate", "detect"])
    ap.add_argument("--root", required=True)
    ap.add_argument("--config")
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    if not root.is_dir():
        print(f"racine introuvable : {root}", file=sys.stderr); return 64
    if a.cmd == "detect":
        code, out = detect(root)
    else:
        cfg = pathlib.Path(a.config) if a.config else root / ".claude" / "project-manager.config.json"
        code, out = resolve(root, cfg)
    if a.cmd == "validate":
        print("VALIDE" if code == 0 else f"NON VALIDE (code {code})")
        for e in out.get("errors", []): print("  ✘", e)
        for w in out.get("warnings", []): print("  ⚠", w)
        if "detection" in out: print("  détection :", json.dumps(out["detection"], ensure_ascii=False))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
