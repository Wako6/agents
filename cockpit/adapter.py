#!/usr/bin/env python3
"""Adaptateur du cockpit : lit des COPIES minimisées de runs, jamais les runs eux-mêmes. Lecture seule.

Il n'importe pas pmx, ne lance aucune commande et n'écrit rien. Un fichier reçu est refusé en entier au moindre écart :
nom, type, lien symbolique, taille, JSON, schéma, champ non prévu ou donnée d'apparence sensible.
"""
import json, os, pathlib, re, stat

SCHEMA_ID = "pm-cockpit-copy/1"
MAX_FILE = 2 * 1024 * 1024
MAX_FILES = 200
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\.copy\.json")
TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")
WORD = re.compile(r"[A-Za-z0-9_.-]{1,40}")
ROOT_MARKERS = (".git", ".claude", "ai_memory", "run.json", "events.jsonl")
# Données d'apparence sensible, cherchées dans les octets : une copie conforme n'a aucune raison d'en contenir.
SENSITIVE = [re.compile(p) for p in (
    rb"(?:gh[pos]|github_pat|glpat|xox[abp]|AKIA)[-_A-Za-z0-9]{8,}", rb"\bsk-[A-Za-z0-9]{8,}", rb"-----BEGIN [A-Z ]*PRIVATE",
    rb"/(?:home|Users|root|tmp)/", rb"/mnt/[a-z]/", rb"[A-Za-z]:\\\\", rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]",
    rb"(?<![0-9.])(?:10|127|192\.168|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]+\.[0-9]+", rb"(?i)\b(?:password|passwd|api[_-]?key|token|secret)\b\"?\s*[:=]")]


class Refused(Exception):
    """Motif sous forme de code : jamais de contenu du fichier refusé."""


def ref(prefix):
    return re.compile(prefix + r"-[0-9a-f]{10}")


ACTOR = re.compile(r"(?:[HA]-[0-9a-f]{10}|consensus|none)")
T, E, W, C = ref("T"), ref("E"), ref("W"), ref("C")
ATTEMPT = {"n": int, "adapter": WORD, "started": TS, "ended": TS, "result": WORD, "settled": WORD, "tracked": bool}
EVENT = {"seq": int, "ts": TS, "kind": WORD, "task": T, "attempt": int, "verdict": WORD, "result": WORD}
SCHEMA = {
    "schema": re.compile(re.escape(SCHEMA_ID)), "captured": TS, "sources": [WORD], "events_malformed": int,
    "project": {"id": ref("P")},
    "run": {"id": ref("R"), "created": TS, "updated": TS, "base": C},
    "debate": {"status": WORD, "turns": int, "needs_human": bool},
    "decision": {"by": ACTOR, "ts": TS},
    "plan": {"status": WORD, "approved_by": ACTOR, "approved": TS, "waves": [[T]]},
    "teams": [{"id": E, "adapter": WORD}],
    "tasks": [{"id": T, "wi": W, "status": WORD, "team": E, "depends_on": [T], "files": int, "budget_base": int, "commit": C, "attempts": [ATTEMPT],
               "verify": {"verdict": WORD, "commit": C, "runner": WORD, "tests": int, "failed": int, "integrity_problems": int, "ts": TS},
               "review": {"verdict": WORD, "by": E, "commit": C, "uncovered": int, "ts": TS}}],
    "helpers": [{"kind": WORD, "ended": TS, "tracked": bool}],
    "stop_evidence": [{"kind": WORD, "state": WORD, "ts": TS, "task": T, "attempt": int, "problems": int,
                       "attempts": [{"task": T, "attempt": int, "before": bool, "populated_after": bool, "killed": bool, "term": int, "errors": int}]}],
    "stop": {"state": WORD, "reason_kind": WORD, "ack_by": ACTOR, "ack_ts": TS, "problems": int, "started": TS, "ended": TS},
    "integration": {"commit": C, "by": ACTOR, "ts": TS, "merged": int},
    "events": [EVENT]}
REQUIRED = ("schema", "captured", "sources", "project", "run", "tasks", "events")


def validate(value, rule, where="racine"):
    if isinstance(rule, dict):
        if not isinstance(value, dict):
            raise Refused(f"objet attendu : {where}")
        for k in value:
            if k not in rule:
                raise Refused(f"champ non autorisé dans {where}")
        for k, v in value.items():
            validate(v, rule[k], f"{where}.{k}")
    elif isinstance(rule, list):
        if not isinstance(value, list) or len(value) > 5000:
            raise Refused(f"liste attendue : {where}")
        for v in value:
            validate(v, rule[0], where + "[]")
    elif rule is int:
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 10**9:
            raise Refused(f"entier attendu : {where}")
    elif rule is bool:
        if not isinstance(value, bool):
            raise Refused(f"booléen attendu : {where}")
    elif not isinstance(value, str) or not rule.fullmatch(value):
        raise Refused(f"valeur non conforme : {where}")


def validate_document(doc):
    validate(doc, SCHEMA)
    missing = [k for k in REQUIRED if k not in doc]
    if missing:
        raise Refused("champ obligatoire absent")
    if doc["schema"] != SCHEMA_ID:
        raise Refused("schéma inconnu")
    known = {t["id"] for t in doc["tasks"]}
    linked = {e["task"] for e in doc["events"] if "task" in e} | {d for t in doc["tasks"] for d in t.get("depends_on", [])}
    for rec in doc.get("stop_evidence", []):
        linked |= {x["task"] for x in [rec, *rec.get("attempts", [])] if "task" in x}
    if linked - known:
        raise Refused("relation vers une tâche inconnue")
    teams = {t["id"] for t in doc.get("teams", [])}
    if {t["team"] for t in doc["tasks"] if "team" in t} - teams:
        raise Refused("relation vers une équipe inconnue")
    return doc


def parse_bytes(raw):
    if len(raw) > MAX_FILE:
        raise Refused("fichier trop volumineux")
    for rx in SENSITIVE:
        if rx.search(raw):
            raise Refused("donnée d'apparence sensible")
    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=lambda _x: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise Refused("JSON invalide") from None
    return validate_document(doc)


def read_regular(dir_fd, name):
    """Sans suivre de lien, depuis le dossier déjà ouvert : ni lien symbolique, ni traversée, ni fichier spécial."""
    if not NAME.fullmatch(name):
        raise Refused("nom de fichier refusé")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError:
        raise Refused("lien symbolique ou fichier illisible") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("fichier spécial")
        if st.st_size > MAX_FILE:
            raise Refused("fichier trop volumineux")
        return os.read(fd, MAX_FILE + 1)
    finally:
        os.close(fd)


def check_root(root, forbidden=()):
    """Le dossier des copies : un vrai dossier, sans lien sur son chemin, hors du dépôt, sans allure de projet ou de run."""
    p = pathlib.Path(root)
    if not p.is_absolute():
        p = pathlib.Path.cwd() / p
    if ".." in p.parts or p != p.resolve():
        raise Refused("chemin refusé : lien symbolique ou traversée")
    if not p.is_dir():
        raise Refused("dossier des copies introuvable")
    for f in forbidden:
        f = pathlib.Path(f).resolve()
        if p == f or f in p.parents:
            raise Refused("les copies doivent rester hors du dépôt")
    if any((p / m).exists() or (p / m).is_symlink() for m in ROOT_MARKERS):
        raise Refused("ce dossier ressemble à un projet ou à un run réel")
    return p


def continuity(events):
    """Événements manquants ou dupliqués dans la copie : signalés et retirés des doublons, jamais comblés."""
    seen, out, dup = set(), [], 0
    for e in sorted(events, key=lambda x: x["seq"]):
        if e["seq"] in seen:
            dup += 1
            continue
        seen.add(e["seq"])
        out.append(e)
    missing = len(range(1, max(seen) + 1)) - len(seen) if seen else 0
    return out, missing, dup


SETTLED = {"verified": "vérifiée", "descendants_stopped": "descendants arrêtés", "unresolved": "non résolue", "unverified": "non vérifiée (pas de cgroup)"}
KINDS = {"run_started": "Run démarré", "debate_turn_requested": "Tour de débat demandé", "debate_turn": "Tour de débat reçu", "debate_turn_failed": "Tour de débat en échec", "debate_closed": "Débat clos",
         "decision_recorded": "Décision enregistrée", "plan_submitted": "Plan soumis", "plan_approved": "Plan approuvé", "task_reopened": "Tâche rouverte par décision humaine", "team_started": "Équipe lancée",
         "team_process_begin": "Processus d'équipe démarré", "team_process_end": "Processus d'équipe terminé", "team_reported": "Rapport d'équipe reçu", "team_finished": "Tentative terminée", "retry_decision": "Décision de relance",
         "verified": "Vérification", "verify_refused": "Vérification refusée", "review_requested": "Revue demandée", "reviewed": "Revue reçue", "integration_dry_run": "Intégration à blanc", "integration_failed": "Intégration en échec",
         "integration_refused": "Intégration refusée", "integration_conflict": "Conflit d'intégration", "integration_integrity_failed": "Intégrité d'intégration non vérifiée", "integration_not_confirmed": "Intégration non confirmée", "integrated": "Intégration locale",
         "critical_stop_begin": "Arrêt critique commencé", "critical_abort": "Arrêt critique", "critical_stop_acknowledged": "Arrêt acquitté (ne prouve rien)", "gateway_started": "Passerelle démarrée", "gateway_stopped": "Passerelle arrêtée", "gateway_team_attached": "Équipe attachée à la passerelle"}
CRITICAL = {"critical_abort", "critical_stop_begin", "integration_integrity_failed", "integration_conflict"}
WARNING = {"critical_stop_acknowledged", "debate_turn_failed", "verify_refused", "integration_failed", "integration_refused", "integration_not_confirmed", "retry_decision", "task_reopened"}
ACTOR_LABEL = {"consensus": "consensus", "none": "—"}


def label(ref_id):
    return ref_id[:6] if ref_id else "—"


def actor(value):
    if not value:
        return None
    return ACTOR_LABEL.get(value) or ("humain " if value.startswith("H-") else "acteur ") + value[2:6]


def derive_pipeline(doc, tasks, events):
    """Chaque étape vient d'un champ précis. Sans preuve : `pending`. Valeur non reconnue : elle part telle quelle et s'affichera « Inconnu »."""
    stop = (doc.get("stop") or {}).get("state")
    kinds = {e["kind"] for e in events}
    last = [t["attempts"][-1] for t in tasks if t.get("attempts")]
    debate = (doc.get("debate") or {}).get("status")
    step_debate = {"consensus": "done", "no_consensus": "done", "awaiting_human": "done", "running": "active", None: "pending"}.get(debate, debate)
    plan = (doc.get("plan") or {}).get("status")
    step_plan = {"approved": "done", "proposed": "active", "pending": "pending", None: "pending"}.get(plan, plan)
    if stop in ("UNRESOLVED", "IN_PROGRESS"):
        step_teams = "blocked"
    elif not tasks or len(last) < len(tasks):
        step_teams = "active" if last else "pending"
    elif all(a.get("result") == "done" for a in last):
        step_teams = "done"
    elif any(a.get("result") in ("failed", "aborted", "interrupted") for a in last):
        step_teams = "blocked"
    else:
        step_teams = "active"
    def aggregate(key, good, bad):
        vals = [(t.get(key) or {}).get("verdict") for t in tasks]
        if not tasks or not any(vals):
            return "pending"
        if any(v in bad for v in vals):
            return "blocked"
        if all(v == good for v in vals):
            return "done"
        return "active" if all(v in (good, None) for v in vals) else "unrecognized"
    dry = [e for e in events if e["kind"] == "integration_dry_run"]
    step_dry = "pending" if not dry else "done" if dry[-1].get("verdict") == "PASS" else "blocked"
    return [("request", "Demande", "done" if "run_started" in kinds else "pending", ""), ("debate", "Débat", step_debate, f"{(doc.get('debate') or {}).get('turns', 0)} tour(s)"),
            ("decision", "Décision", "done" if doc.get("decision") else "pending", actor((doc.get("decision") or {}).get("by")) or ""), ("plan", "Plan", step_plan, ""),
            ("teams", "Équipes", step_teams, "Arrêt critique non prouvé" if stop in ("UNRESOLVED", "IN_PROGRESS") else ""), ("verify", "Vérification Docker", aggregate("verify", "PASS", ("FAIL", "INCONCLUSIVE")), ""),
            ("review", "Revue croisée", aggregate("review", "APPROVE", ("CHANGES_REQUESTED", "UNPARSEABLE")), ""), ("dry", "Intégration à blanc", step_dry, ""), ("integrate", "Intégration", "done" if doc.get("integration") else "pending", "")]


def to_run(doc):
    """Copie validée → modèle du cockpit. Ce que la copie ne contient pas reste absent, donc « Inconnu » à l'écran."""
    events, missing, dup = continuity(doc["events"])
    notes = []
    if "WORK_ITEMS.md" not in doc["sources"]:
        notes.append("statut des tâches non extrait")
    if missing:
        notes.append(f"{missing} événement(s) manquant(s)")
    if dup:
        notes.append(f"{dup} événement(s) dupliqué(s) retiré(s)")
    if doc.get("events_malformed"):
        notes.append(f"{doc['events_malformed']} ligne(s) de journal illisible(s)")
    notes.append("copie figée, sans observation des processus")
    stop = doc.get("stop")
    tasks = []
    for t in doc["tasks"]:
        atts = [{"n": a.get("n"), "adapter": a.get("adapter"), "started": a.get("started"), "ended": a.get("ended"), "result": a.get("result"), "settled": SETTLED.get(a.get("settled"), a.get("settled")), "cgroup": "suivi" if a.get("tracked") else None} for a in t.get("attempts", [])]
        out = {"key": label(t["id"]), "wi": label(t.get("wi")), **({"status": t["status"]} if t.get("status") else {}), "title": f"Tâche {label(t['id'])}", "team": label(t.get("team")), "files": [], "depends_on": [label(d) for d in t.get("depends_on", [])], "attempts": atts, "commit": label(t.get("commit")) if t.get("commit") else None,
               "budget": f"{len(atts) - t.get('budget_base', 0)} tentative(s) du budget courant, {len(atts)} au total"}
        if t.get("verify"):
            out["verify"] = {**t["verify"], "commit": label(t["verify"].get("commit"))}
        if t.get("review"):
            r = t["review"]
            out["review"] = {"verdict": r.get("verdict"), "by": label(r.get("by")), "commit": label(r.get("commit")), "uncovered": ["point absent"] * r.get("uncovered", 0), "ts": r.get("ts")}
        tasks.append(out)
    decisions = []
    if doc.get("decision"):
        decisions.append({"ts": doc["decision"].get("ts"), "kind": "Décision", "by": actor(doc["decision"].get("by")), "text": "Texte non conservé dans la copie."})
    if (doc.get("plan") or {}).get("approved"):
        decisions.append({"ts": doc["plan"]["approved"], "kind": "Plan approuvé", "by": actor(doc["plan"].get("approved_by")), "text": "Plan non conservé dans la copie."})
    decisions += [{"ts": e["ts"], "kind": KINDS[e["kind"]], "by": "—", "text": "Motif non conservé dans la copie."} for e in events if e["kind"] == "task_reopened"]
    if doc.get("integration"):
        decisions.append({"ts": doc["integration"].get("ts"), "kind": "Intégration locale", "by": actor(doc["integration"].get("by")), "text": f"{doc['integration'].get('merged', 0)} tâche(s) intégrée(s)."})
    if stop and stop.get("ack_by"):
        decisions.append({"ts": stop.get("ack_ts"), "kind": "Acquittement administratif", "by": actor(stop["ack_by"]), "text": "Incident consigné : ne prouve rien, ne débloque rien."})
    atts = [a for t in doc["tasks"] for a in t.get("attempts", [])]
    security = {"items": [
        {"label": "Tentatives suivies par cgroup", "value": f"{sum(1 for a in atts if a.get('tracked'))} sur {len(atts)}", "proof": "OBSERVED", "note": "Relevé dans la copie."},
        {"label": "Fins de tentative vérifiées", "value": f"{sum(1 for a in atts if a.get('settled') in ('verified', 'descendants_stopped'))} sur {len(atts)}", "proof": "OBSERVED", "note": "Relevé dans la copie."},
        {"label": "Agents de débat et de revue suivis", "value": f"{sum(1 for h in doc.get('helpers', []) if h.get('tracked'))} sur {len(doc.get('helpers', []))}", "proof": "OBSERVED", "note": "Relevé dans la copie."},
        {"label": "Mode et confinement", "value": "Inconnu", "proof": "NOT_MEASURED", "note": "Configuration du projet non extraite."},
        {"label": "Restriction MCP", "value": "Inconnu", "proof": "NOT_MEASURED", "note": "Non déductible d'une copie."},
        {"label": "Processus du run", "value": "Inconnu", "proof": "NOT_MEASURED", "note": "Une copie n'observe aucun processus."}]}
    rows = [x for rec in doc.get("stop_evidence", []) for x in rec.get("attempts", [])]
    if "stop_evidence" in doc:
        security["items"].insert(0, {"label": "Preuves d'arrêt des cgroups", "value": f"{sum(1 for x in rows if x.get('populated_after') is True)} encore peuplé(s), {sum(1 for x in rows if 'populated_after' not in x)} indéterminé(s), sur {len(rows)}", "proof": "OBSERVED", "note": "Relevé dans la copie ; le verdict d'arrêt reste celui du run."})
    if stop:
        security["stop"] = {"state": stop.get("state"), "reason": stop.get("reason_kind"), "ack_by": actor(stop.get("ack_by"))}
        security["items"].insert(0, {"label": "Problèmes d'arrêt consignés", "value": str(stop.get("problems", 0)), "proof": "OBSERVED", "note": "Le détail n'est pas conservé dans la copie."})
    evs = [{"seq": e["seq"], "ts": e["ts"], "kind": e["kind"], "task": label(e.get("task")) if e.get("task") else None, "severity": "critical" if e["kind"] in CRITICAL else "warning" if e["kind"] in WARNING else "info",
            "text": " ".join(x for x in (KINDS.get(e["kind"], "Événement inconnu"), label(e["task"]) if e.get("task") else "", e.get("verdict") or e.get("result") or "") if x)} for e in events]
    teams = [{"name": label(x["id"]), "adapter": x.get("adapter"), "role": "développement", "task": ", ".join(label(t["id"]) for t in doc["tasks"] if t.get("team") == x["id"])} for x in doc.get("teams", [])]
    return {"id": label(doc["run"]["id"]), "title": f"Copie du run {label(doc['run']['id'])}", "created": doc["run"].get("created"), "updated": doc["run"].get("updated"), "observed_at": doc["captured"],
            "source": "PARTIAL", "source_note": " ; ".join(notes) + ".", "base": label(doc["run"].get("base")), "pipeline": [{"key": k, "label": l, "state": s, "detail": d} for k, l, s, d in derive_pipeline(doc, doc["tasks"], events)],
            "teams": teams, "tasks": tasks, "decisions": decisions, "security": security, "events": evs}


def load_dir(root, forbidden=()):
    """→ (projets du modèle, nombre de fichiers refusés, motifs). Aucun fichier refusé n'apporte de donnée. Le motif est un code, sans contenu."""
    p = check_root(root, forbidden)
    dfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    projects, refused = {}, []
    try:
        names = sorted(os.listdir(dfd))
        if len(names) > MAX_FILES:
            raise Refused("trop de fichiers")
        for name in names:
            try:
                doc = parse_bytes(read_regular(dfd, name))
                run = to_run(doc)
            except Refused as e:
                refused.append(str(e))
                continue
            pid = doc["project"]["id"]
            projects.setdefault(pid, {"id": label(pid), "name": f"Projet {label(pid)}", "backend": "Inconnu", "mode": "Inconnu", "profile": None, "profile_active": False, "source": "PARTIAL", "runs": []})["runs"].append(run)
    finally:
        os.close(dfd)
    return list(projects.values()), refused
