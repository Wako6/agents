#!/usr/bin/env python3
"""
rules_sync — synchronisation contrôlée ai_rules/ → .claude/rules/

Sens unique : ai_rules/ (source de vérité, curée par rules-curator) → .claude/rules/ai-rules*.md (généré).
Ne modifie jamais ai_rules/. Ne touche jamais aux autres fichiers de .claude/rules/.

Une entrée ai_rules est exportée vers les règles natives si elle porte `Autoload: yes`.
Si elle porte aussi `Paths: <glob>[, <glob>]`, elle est regroupée dans un fichier à portée
`paths:` (chargé seulement quand un fichier correspondant est lu/édité) ; sinon dans
`ai-rules.md` (chargé à chaque session).

Usage :
  rules_sync.py --ai-rules ai_rules --out .claude/rules [--check] [--write]
    --check  : valide et signale (doublons, INDEX incohérent, dépréciée exportée) ; exit 1 si anomalie
    --write  : (ré)génère les fichiers ai-rules*.md (après --check implicite)
  Par défaut : --check seul (ne rien écrire est le comportement sûr).

Ce que le script détecte (structurel) : ID dupliqué, titre dupliqué (normalisé), entrée absente de
INDEX.md ou présente dans INDEX sans fichier, entrée `Deprecated` encore `Autoload: yes`,
Autoload sans Rule, champ Paths vide. Les contradictions SÉMANTIQUES entre règles ne sont pas
détectables par script : elles relèvent du mode `review` de rules-curator (checklist dans rules-wiki.md).
"""
import argparse, re, sys, pathlib, hashlib, json

ENTRY_RE = re.compile(r'^### (?P<id>[A-Z]+-\d{3}) — (?P<title>.+?)\s*$', re.M)
FIELD_RE = re.compile(r'^(?P<k>Scope|Origin|Added|Verified|Deprecated|Autoload|Paths):\s*(?P<v>.*)$', re.M)
RULE_RE = re.compile(r'^\*\*(?:Rule|Decision|Pitfall|Rule / Decision / Pitfall)[^*]*\*\*\s*(?P<v>.+?)$', re.M)
HOW_RE = re.compile(r'^\*\*How to apply:\*\*\s*(?P<v>.+?)$', re.M)
TOPIC_OF = {"CONV": "conventions", "DEC": "decisions", "PIT": "pitfalls", "SEC": "security", "PERF": "performance"}
HEADER = "<!-- GÉNÉRÉ par rules_sync.py depuis ai_rules/ — ne pas éditer à la main ; modifier ai_rules/ puis relancer la synchro -->\n"

def norm(s): return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()

def parse(ai_rules: pathlib.Path):
    entries, problems = [], []
    for f in sorted(ai_rules.glob("*.md")):
        if f.name == "INDEX.md": continue
        text = f.read_text(encoding="utf-8")
        spans = list(ENTRY_RE.finditer(text))
        for i, m in enumerate(spans):
            body = text[m.end(): spans[i+1].start() if i+1 < len(spans) else len(text)]
            fields = {k: v.strip() for k, v in FIELD_RE.findall(body)}
            rule = (RULE_RE.search(body) or HOW_RE.search(body))
            e = {"id": m["id"], "title": m["title"].strip(), "file": f.name, "fields": fields,
                 "rule": rule["v"].strip() if rule else "", "how": (HOW_RE.search(body)["v"].strip() if HOW_RE.search(body) else "")}
            entries.append(e)
    # INDEX
    idx = ai_rules / "INDEX.md"
    index_ids = set(re.findall(r'\|\s*([A-Z]+-\d{3})\s*\|', idx.read_text(encoding="utf-8"))) if idx.exists() else set()
    deprecated_in_index = set(re.findall(r'^#\s*DEPRECATED.*?\|\s*([A-Z]+-\d{3})\s*\|', idx.read_text(encoding="utf-8"), re.M)) if idx.exists() else set()
    # contrôles
    seen_id, seen_title = {}, {}
    for e in entries:
        if e["id"] in seen_id: problems.append(f"DUPLICATE-ID {e['id']} dans {seen_id[e['id']]} et {e['file']}")
        seen_id.setdefault(e["id"], e["file"])
        t = norm(e["title"])
        if t in seen_title and seen_title[t] != e["id"]: problems.append(f"DUPLICATE-TITLE '{e['title']}' : {seen_title[t]} et {e['id']}")
        seen_title.setdefault(t, e["id"])
        if idx.exists() and e["id"] not in index_ids: problems.append(f"NOT-IN-INDEX {e['id']} ({e['file']})")
        auto = e["fields"].get("Autoload", "no").lower() in ("yes", "true", "1")
        dep = bool(e["fields"].get("Deprecated")) or e["id"] in deprecated_in_index
        if auto and dep: problems.append(f"DEPRECATED-BUT-AUTOLOAD {e['id']}")
        if auto and not e["rule"]: problems.append(f"AUTOLOAD-WITHOUT-RULE {e['id']}")
        if "Paths" in e["fields"] and not e["fields"]["Paths"].strip(): problems.append(f"EMPTY-PATHS {e['id']}")
        e["autoload"], e["deprecated"] = auto, dep
    for i in sorted(index_ids - {e["id"] for e in entries}):
        problems.append(f"INDEX-WITHOUT-ENTRY {i}")
    return entries, problems

def render(entries):
    """→ {filename: content}"""
    groups = {}
    for e in entries:
        if not e["autoload"] or e["deprecated"]: continue
        paths = [p.strip() for p in e["fields"].get("Paths", "").split(",") if p.strip()]
        key = tuple(paths)
        groups.setdefault(key, []).append(e)
    out = {}
    for key, es in groups.items():
        if key:
            name = "ai-rules-" + hashlib.sha1(",".join(key).encode()).hexdigest()[:8] + ".md"
            fm = "---\npaths:\n" + "".join(f"  - \"{p}\"\n" for p in key) + "---\n"
        else:
            name, fm = "ai-rules.md", ""
        lines = [fm, HEADER, "# Règles projet (extraites de ai_rules/)\n", ""]
        if key: lines.append("Portée : " + ", ".join(f"`{p}`" for p in key) + "\n")
        for e in sorted(es, key=lambda x: x["id"]):
            topic = TOPIC_OF.get(e["id"].split("-")[0], "rule")
            lines.append(f"- **{e['id']}** ({topic}) — {e['rule']}" + (f" _Comment :_ {e['how']}" if e["how"] and e["how"] != e["rule"] else "") + f" (`ai_rules/{e['file']}#{e['id'].lower()}`)")
        out[name] = "\n".join(lines) + "\n"
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ai-rules", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--check", action="store_true"); ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    ai = pathlib.Path(a.ai_rules); out = pathlib.Path(a.out)
    if not ai.is_dir(): print(f"ai_rules introuvable : {ai}", file=sys.stderr); return 2
    entries, problems = parse(ai)
    files = render(entries)
    # diff avec l'existant
    changes = []
    existing = {p.name: p.read_text(encoding="utf-8") for p in out.glob("ai-rules*.md")} if out.is_dir() else {}
    for n, c in files.items():
        if existing.get(n) != c: changes.append(("write", n))
    for n in existing:
        if n not in files: changes.append(("remove-obsolete", n))
    report = {"entries": len(entries), "autoload": sum(1 for e in entries if e["autoload"] and not e["deprecated"]),
              "problems": problems, "pending_changes": changes}
    if a.json: print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"ai_rules : {report['entries']} entrées, {report['autoload']} exportables")
        for p in problems: print("  ✘", p)
        for c, n in changes: print(f"  → {c}: {out/n}")
        if not problems and not changes: print("  ✔ rien à faire")
    if problems: return 1
    if a.write and changes:
        out.mkdir(parents=True, exist_ok=True)
        for c, n in changes:
            if c == "write": (out / n).write_text(files[n], encoding="utf-8")
            else:
                # un fichier généré devenu obsolète est renommé, jamais supprimé
                (out / n).rename(out / (n + ".obsolete"))
        print(f"  ✔ {len(changes)} fichier(s) synchronisé(s) dans {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
