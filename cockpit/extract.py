#!/usr/bin/env python3
"""Extracteur manuel : produit une copie minimisée à partir d'un run. Lecture seule sur les sources. Le serveur du cockpit ne l'utilise jamais.

    python3 -I -B cockpit/extract.py --run-dir <projet>/ai_memory/runs/<run> [--run-dir …] [--with-work-items] --out <dossier-neuf-hors-depot>

Il ouvre seulement run.json et events.jsonl et, avec --with-work-items, le registre du projet pour les seuls statuts des work items du
run. La fonction stop_evidence_records n'est reliée à aucune option : elle ne lit aucun fichier. Il ne conserve que les champs listés ici. Il ne copie ni texte libre ni contenu de journal :
titres, décisions, motifs, chemins, prompts, rapports et sorties de test sont absents. Les identifiants sont remplacés par des
pseudonymes dont la clé, tirée au hasard, n'est jamais écrite : une copie ne permet pas de retrouver les noms d'origine.
"""
import argparse, datetime, hashlib, hmac, importlib.util, json, os, pathlib, re, secrets, stat, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
_s = importlib.util.spec_from_file_location("cockpit_adapter", HERE / "adapter.py")
adapter = importlib.util.module_from_spec(_s)
_s.loader.exec_module(adapter)
MAX_SOURCE = 32 * 1024 * 1024
KNOWN_EVENTS = set(adapter.KINDS)
WI_STATUSES = ("OPEN", "IN_PROGRESS", "READY_FOR_VERIFICATION", "READY_FOR_REVIEW", "BLOCKED", "ESCALATED", "STALE", "DONE")
PSEUDONYM = re.compile(r"\b[RTEWCHA]-[0-9a-f]{10}\b")
SETTLED = {"vérifiée": "verified", "descendants arrêtés": "descendants_stopped", "non résolue": "unresolved", "non vérifiée (pas de cgroup)": "unverified"}


def read_source(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SOURCE:
            raise SystemExit(f"source refusée : {pathlib.Path(path).name}")
        return os.read(fd, MAX_SOURCE + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


class Pseudo:
    """La portée (projet et run) évite deux pièges : deux runs homonymes confondus, et des copies recoupables entre elles."""

    def __init__(self, key=None, scope=""):
        self.key, self.scope = key or secrets.token_bytes(32), scope

    def within(self, *scope):
        return Pseudo(self.key, "|".join(map(str, scope)))

    def __call__(self, prefix, value):
        return f"{prefix}-{hmac.new(self.key, f'{self.scope}|{prefix}:{value}'.encode(), hashlib.sha256).hexdigest()[:10]}"

    def actor(self, value):
        if not isinstance(value, str) or not value:
            return None
        if value == "consensus":
            return "consensus"
        return self("H" if value.startswith("human:") else "A", value)


def word(value):
    """Une valeur structurelle reconnaissable, sinon un marqueur : le contenu d'origine n'est jamais recopié."""
    if value is None:
        return None
    return value if isinstance(value, str) and adapter.WORD.fullmatch(value) and adapter.TS.fullmatch(value) is None else "UNRECOGNIZED"


def ts(value):
    return value if isinstance(value, str) and adapter.TS.fullmatch(value) else None


def num(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**9 else None


def reason_kind(text):
    """Le motif est du texte libre, avec des chemins : seule sa catégorie est gardée."""
    t = str(text or "")
    for rx, kind in ((r"chemin sensible", "sensitive_path"), (r"hors périmètre", "out_of_scope"), (r"collision", "collision"), (r"fin de tentative", "attempt_end"), (r"débat ou de revue", "helper"), (r"arrêt demandé", "requested")):
        if re.search(rx, t):
            return kind
    return "other"


def clean(d):
    return {k: v for k, v in d.items() if v is not None}


def count_tests(results):
    """Seuls des nombres sont lus dans la sortie des tests ; elle n'est pas conservée."""
    tests, failed, seen = 0, 0, False
    for r in results or []:
        out = str((r or {}).get("output") or "")
        m = re.search(r"^Ran (\d+) tests?\b", out, re.M)
        if m:
            tests += int(m.group(1))
            seen = True
        f = re.search(r"^FAILED \(([^)]*)\)", out, re.M)
        if f:
            failed += sum(int(x) for x in re.findall(r"(?:failures|errors)=(\d+)", f.group(1)))
    return (tests, failed) if seen else (None, None)


def ledger_statuses(text, wanted):
    """Statut des seuls work items demandés. Tout le reste du registre est ignoré : titres, motifs, liens, chemins, sessions."""
    out, current = {}, None
    for line in text.splitlines():
        head = re.match(r"### (\S+)", line)
        if head:
            current = head.group(1) if head.group(1) in wanted else None
        elif current and current not in out:
            m = re.fullmatch(r"- status: (\S+)\s*", line)
            if m:
                out[current] = m.group(1) if m.group(1) in WI_STATUSES else "UNRECOGNIZED"
    return out


def stop_evidence_records(text, ps):
    """Minimise le contenu d'un stop-evidence.jsonl reçu en argument. Ni texte, ni PID, ni unité, ni cgroup, ni chemin : des états et des nombres."""
    records, malformed = [], 0
    def task(value):
        return ps("T", value) if isinstance(value, str) and value and ":" not in value else None  # « review:clé » désigne un agent auxiliaire
    def flag(row, key):
        return row[key] if isinstance(row.get(key), bool) else None
    for line in text.splitlines():
        try:
            r = json.loads(line)
            if not isinstance(r, dict):
                raise ValueError
        except ValueError:
            malformed += 1
            continue
        rows = [clean({"task": task(a.get("task")), "attempt": num(a.get("attempt")), "before": flag(a, "before"), "populated_after": flag(a, "populated_after"), "killed": flag(a, "killed"), "term": len(a["term"]) if isinstance(a.get("term"), list) else None, "errors": len(a["errors"]) if isinstance(a.get("errors"), list) else None}) for a in r.get("attempts") or [] if isinstance(a, dict)]
        records.append(clean({"kind": word(r.get("kind")), "state": word(r.get("state")), "ts": ts(r.get("ts")), "task": task(r.get("task")), "attempt": num(r.get("attempt")), "problems": len(r["problems"]) if isinstance(r.get("problems"), list) else None, "attempts": rows}))
    return records, malformed


def pseudonym_collisions(docs):
    """Un même pseudonyme dans deux copies : confusion entre projets ou recoupement possible."""
    seen, out = {}, set()
    for i, raw in enumerate(docs):
        for x in set(PSEUDONYM.findall(raw.decode("utf-8"))):
            if seen.setdefault(x, i) != i:
                out.add(x)
    return out


def minimize(run_dir, ps, project_key, captured, with_work_items=False):
    st = json.loads(read_source(run_dir / "run.json"))
    ps = ps.within(project_key, st.get("run"))
    statuses = {}
    if with_work_items:
        wanted = {t.get("wi") for t in (st.get("tasks") or {}).values() if isinstance(t.get("wi"), str)}
        statuses = ledger_statuses(read_source(run_dir.parents[1] / "WORK_ITEMS.md"), wanted)
    tkey = lambda k: ps("T", k)
    tasks, teams = [], {}
    for key, t in (st.get("tasks") or {}).items():
        atts = []
        for a in t.get("attempts") or []:
            atts.append(clean({"n": num(a.get("n")), "adapter": word(a.get("adapter")), "started": ts(a.get("started")), "ended": ts(a.get("ended")), "result": word(a.get("result")), "settled": SETTLED.get(a.get("settled"), "other" if a.get("settled") else None), "tracked": bool(a.get("cgroup"))}))
        team = ps("E", t.get("team")) if t.get("team") else None
        if team:
            teams.setdefault(team, next((x.get("adapter") for x in atts if x.get("adapter")), "UNRECOGNIZED"))
        item = clean({"id": tkey(key), "wi": ps("W", t.get("wi")) if t.get("wi") else None, "status": statuses.get(t.get("wi")), "team": team, "depends_on": [tkey(d) for d in t.get("depends_on") or []], "files": len(t.get("files") or []), "budget_base": num(t.get("budget_base")), "commit": ps("C", t["commit"]) if t.get("commit") else None, "attempts": atts})
        v = t.get("verify")
        if v:
            tests, failed = count_tests(v.get("results"))
            item["verify"] = clean({"verdict": word(v.get("verdict")), "commit": ps("C", v["commit"]) if v.get("commit") else None, "runner": word(v.get("runner")), "tests": tests, "failed": failed, "integrity_problems": len(v.get("integrity") or []), "ts": ts(v.get("ts"))})
        r = t.get("review")
        if r:
            by = str(r.get("by") or "").split(":")[0]
            item["review"] = clean({"verdict": word(r.get("verdict")), "by": ps("E", by) if by else None, "commit": ps("C", r["commit"]) if r.get("commit") else None, "uncovered": len(r.get("uncovered") or []), "ts": ts(r.get("ts"))})
            if by:
                teams.setdefault(ps("E", by), str(r.get("by")).split(":")[1] if ":" in str(r.get("by")) and adapter.WORD.fullmatch(str(r.get("by")).split(":")[1]) else "UNRECOGNIZED")
        tasks.append(item)
    known = {t["id"] for t in tasks}
    events, malformed = [], 0
    for n, line in enumerate(read_source(run_dir / "events.jsonl").splitlines(), 1):
        try:
            e = json.loads(line)
            if not isinstance(e, dict):
                raise ValueError
        except ValueError:
            malformed += 1
            continue
        task = tkey(e["task"]) if isinstance(e.get("task"), str) and tkey(e["task"]) in known else None
        events.append(clean({"seq": n, "ts": ts(e.get("ts")) or captured, "kind": e.get("event") if e.get("event") in KNOWN_EVENTS else "unknown_event", "task": task, "attempt": num(e.get("attempt")), "verdict": word(e.get("verdict")) if e.get("event") in ("verified", "reviewed", "integration_dry_run", "critical_abort") else None, "result": word(e.get("result")) if e.get("event") == "team_finished" else None}))
    doc = {"schema": adapter.SCHEMA_ID, "captured": captured, "sources": ["run.json", "events.jsonl", *(["WORK_ITEMS.md"] if with_work_items else [])], "events_malformed": malformed, "project": {"id": project_key}, "run": clean({"id": ps("R", st.get("run")), "created": ts(st.get("created")), "updated": ts(st.get("updated")), "base": ps("C", st["base"]) if st.get("base") else None}),
           "teams": [{"id": k, "adapter": v} for k, v in teams.items()], "tasks": tasks, "events": events, "helpers": [clean({"kind": word(h.get("kind")), "ended": ts(h.get("ended")), "tracked": bool(h.get("cgroup"))}) for h in st.get("helpers") or []]}
    d = st.get("debate") or {}
    doc["debate"] = clean({"status": word(d.get("status")), "turns": len(d.get("turns") or []), "needs_human": d.get("needs_human") if isinstance(d.get("needs_human"), bool) else None})
    if st.get("decision"):
        doc["decision"] = clean({"by": ps.actor(st["decision"].get("by")), "ts": ts(st["decision"].get("ts"))})
    p = st.get("plan") or {}
    if p:
        doc["plan"] = clean({"status": word(p.get("status")), "approved_by": ps.actor(p.get("approved_by")), "approved": ts(p.get("approved")), "waves": [[tkey(k) for k in w] for w in p.get("waves") or []]})
    s = st.get("stop")
    if s:
        ack = s.get("ack") or {}
        doc["stop"] = clean({"state": word(s.get("state")), "reason_kind": reason_kind(s.get("reason")), "ack_by": ps.actor(ack.get("by")), "ack_ts": ts(ack.get("ts")), "problems": len(s.get("problems") or []), "started": ts(s.get("started")), "ended": ts(s.get("ended"))})
    i = st.get("integration")
    if i:
        doc["integration"] = clean({"commit": ps("C", i["commit"]) if i.get("commit") else None, "by": ps.actor(i.get("approved_by")), "ts": ts(i.get("ts")), "merged": len(i.get("merged") or [])})
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run-dir", action="append", required=True)
    ap.add_argument("--with-work-items", action="store_true", help="statuts des work items du run, lus dans le registre du projet")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out).resolve()
    repo = HERE.parent
    sources = [pathlib.Path(r).resolve() for r in a.run_dir]
    if out == repo or repo in out.parents:
        raise SystemExit("refus : la sortie doit rester hors du dépôt")
    for r in sources:
        project = r.parents[2] if len(r.parents) > 2 else r
        if out == r or r in out.parents or project in out.parents or out == project:
            raise SystemExit("refus : la sortie doit rester hors du run et de son projet")
    if out.exists():
        raise SystemExit("refus : le dossier de sortie existe déjà")
    ps = Pseudo()
    captured = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    docs = []
    for r in sources:
        project = r.parents[2] if len(r.parents) > 2 else r
        doc = minimize(r, ps, ps("P", str(project)), captured, a.with_work_items)
        raw = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
        adapter.parse_bytes(raw)  # la copie doit passer les mêmes contrôles que chez le lecteur, sinon rien n'est écrit
        docs.append((doc["run"]["id"], raw))
    if len({n for n, _r in docs}) != len(docs) or pseudonym_collisions([r for _n, r in docs]):
        raise SystemExit("refus : deux copies partageraient un même pseudonyme")
    tmp = out.with_name(f".{out.name}.partiel-{secrets.token_hex(4)}")
    os.mkdir(tmp, 0o700)  # tout ou rien : la sortie n'apparaît sous son nom qu'une fois complète
    for name, raw in docs:
        fd = os.open(tmp / f"{name}.copy.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    os.rename(tmp, out)
    print(f"{len(docs)} copie(s) écrite(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
