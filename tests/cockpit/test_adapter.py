#!/usr/bin/env python3
"""Adaptateur et extracteur du cockpit, flux SSE. Données fictives construites ici ; aucun vrai run, aucun agent, aucun appel à pmx.

Usage : python3 -I -B tests/cockpit/test_adapter.py -v
"""
import ast, http.client, json, os, pathlib, re, shutil, socket, stat, subprocess, sys, tempfile, threading, time, unittest

KIT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT / "cockpit"))
import adapter  # noqa: E402
import extract  # noqa: E402
import server as cockpit  # noqa: E402

H = "a" * 10
TS = "2099-01-02T03:04:05Z"


def copy_doc(**over):
    t, e, c = f"T-{H}", f"E-{H}", f"C-{H}"
    doc = {"schema": adapter.SCHEMA_ID, "captured": TS, "sources": ["run.json", "events.jsonl"], "events_malformed": 0, "project": {"id": f"P-{H}"}, "run": {"id": f"R-{H}", "created": TS, "updated": TS, "base": c},
           "debate": {"status": "consensus", "turns": 2, "needs_human": False}, "decision": {"by": f"H-{H}", "ts": TS}, "plan": {"status": "approved", "approved_by": f"A-{H}", "approved": TS, "waves": [[t]]},
           "teams": [{"id": e, "adapter": "claude-cli"}], "tasks": [{"id": t, "wi": f"W-{H}", "team": e, "depends_on": [], "files": 2, "budget_base": 0, "commit": c,
                                                                     "attempts": [{"n": 1, "adapter": "claude-cli", "started": TS, "ended": TS, "result": "done", "settled": "verified", "tracked": True}],
                                                                     "verify": {"verdict": "PASS", "commit": c, "runner": "docker", "tests": 5, "failed": 0, "integrity_problems": 0, "ts": TS},
                                                                     "review": {"verdict": "APPROVE", "by": e, "commit": c, "uncovered": 0, "ts": TS}}],
           "helpers": [{"kind": "review", "ended": TS, "tracked": True}], "events": [{"seq": 1, "ts": TS, "kind": "run_started"}, {"seq": 2, "ts": TS, "kind": "team_started", "task": t, "attempt": 1}]}
    doc.update(over)
    return doc


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="cockpit-test-"))
        self.root = self.tmp / "copies"
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, doc, name="r1.copy.json"):
        (self.root / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def load(self):
        return adapter.load_dir(self.root, (KIT,))

    def run_only(self):
        ps, ref = self.load()
        self.assertEqual(ref, [])
        return ps[0]["runs"][0]

    def assert_refused(self, code):
        ps, ref = self.load()
        self.assertEqual(ps, [], code)
        self.assertEqual(len(ref), 1, code)
        self.assertIn(code, ref[0])


class Reading(Base):
    def test_01_valid_copy_keeps_relations_and_all_phases(self):
        self.put(copy_doc(integration={"commit": f"C-{H}", "by": f"H-{H}", "ts": TS, "merged": 1}))
        r = self.run_only()
        self.assertEqual({p["key"]: p["state"] for p in r["pipeline"]}["teams"], "done")
        t = r["tasks"][0]
        self.assertEqual((t["team"], t["verify"]["verdict"], t["review"]["verdict"]), ("E-aaaa", "PASS", "APPROVE"))
        self.assertEqual(r["teams"][0]["task"], t["key"])
        self.assertEqual(r["teams"][0]["adapter"], "claude-cli")
        self.assertTrue(any(d["kind"] == "Décision" for d in r["decisions"]))
        self.assertTrue(any(d["kind"] == "Intégration locale" for d in r["decisions"]))

    def test_02_invalid_schema_is_refused(self):
        for bad, code in (({"schema": "autre/9"}, "non conforme"), ({"tasks": "x"}, "liste attendue"), ({"captured": "hier"}, "non conforme"), ({"run": {"id": "R-court"}}, "non conforme")):
            self.put(copy_doc(**bad))
            self.assert_refused(code)
        d = copy_doc()
        del d["run"]
        self.put(d)
        self.assert_refused("obligatoire")
        (self.root / "r1.copy.json").write_text("{pas du json", encoding="utf-8")
        self.assert_refused("JSON invalide")
        (self.root / "r1.copy.json").write_text('{"a": NaN}', encoding="utf-8")
        self.assert_refused("JSON invalide")

    def test_03_forbidden_field_is_refused_at_every_depth(self):
        d = copy_doc(prompt="x")
        self.put(d)
        self.assert_refused("champ non autorisé")
        d = copy_doc()
        d["tasks"][0]["attempts"][0]["brief"] = "x"
        self.put(d)
        self.assert_refused("champ non autorisé")
        d = copy_doc()
        d["events"][0]["reason"] = "x"
        self.put(d)
        self.assert_refused("champ non autorisé")
        for field in ("title", "os_user", "tty", "worktree", "branch", "pid", "report"):
            d = copy_doc()
            d["tasks"][0][field] = "x"
            self.put(d)
            self.assert_refused("champ non autorisé")

    def test_04_sensitive_looking_value_refuses_the_whole_file(self):
        at = chr(64)
        for raw in ("gh" + "p_" + "a" * 20, "gl" + "pat-" + "b" * 20, "sk-" + "c" * 20, "-----BEGIN " + "RSA PRIVATE KEY-----", "contact" + at + "exemple.org", "/ho" + "me/quelquun", "/Us" + "ers/quelquun", "/mn" + "t/c/x", "C:" + "\\Users\\q", "10." + "1.2.3", "password=" + "abc", "/t" + "mp/x"):
            d = copy_doc()
            d["run"]["created"] = raw  # même dans un champ dont le type serait refusé : l'analyse des octets passe d'abord
            self.put(d)
            self.assert_refused("sensible")

    def test_05_oversized_file_is_refused(self):
        (self.root / "r1.copy.json").write_bytes(b" " * (adapter.MAX_FILE + 1))
        self.assert_refused("volumineux")

    def test_06_symlink_is_refused_and_target_never_read(self):
        secret = self.tmp / "dehors.json"
        secret.write_text(json.dumps(copy_doc()))
        (self.root / "r1.copy.json").symlink_to(secret)
        self.assert_refused("lien symbolique")
        link = self.tmp / "lien"
        link.symlink_to(self.root)
        with self.assertRaises(adapter.Refused):
            adapter.load_dir(link, (KIT,))

    def test_07_path_traversal_and_special_files_are_refused(self):
        with self.assertRaises(adapter.Refused):
            adapter.check_root(str(self.root) + "/../copies")
        for name in ("../r.copy.json", "x/../r.copy.json", ".copy.json", "r.json", "r.copy.json.bak", "a b.copy.json"):
            with self.assertRaises(adapter.Refused):
                adapter.read_regular(0, name)
        os.mkfifo(self.root / "r1.copy.json")
        self.assert_refused("spécial")

    def test_08_unknown_states_show_as_unknown_never_success(self):
        d = copy_doc()
        d["debate"]["status"] = "etat_futur"
        d["plan"]["status"] = "etat_futur"
        d["tasks"][0]["attempts"][0]["result"] = "etat_futur"
        d["tasks"][0]["verify"]["verdict"] = "ETAT_FUTUR"
        d["tasks"][0]["review"]["verdict"] = "ETAT_FUTUR"
        d["tasks"][0]["attempts"][0]["settled"] = "etat_futur"
        self.put(d)
        r = cockpit.project(self.run_only(), cockpit.RUN)
        t = r["tasks"][0]
        self.assertNotIn("status", t)  # absent de la copie : l'écran dira « Inconnu »
        self.assertEqual(t["verify"]["verdict"]["value"], "UNKNOWN")
        self.assertEqual(t["review"]["verdict"]["value"], "UNKNOWN")
        self.assertEqual(t["attempts"][0]["result"]["value"], "UNKNOWN")
        p = {x["key"]: x["state"]["value"] for x in r["pipeline"]}
        self.assertEqual(p["debate"], "UNKNOWN")
        self.assertEqual(p["plan"], "UNKNOWN")
        self.assertNotEqual(p["teams"], "done")
        self.assertNotEqual(p["verify"], "done")
        self.assertNotEqual(p["review"], "done")

    def test_09_missing_evidence_never_becomes_done(self):
        d = copy_doc()
        for k in ("decision", "plan", "debate"):
            del d[k]
        del d["tasks"][0]["verify"], d["tasks"][0]["review"]
        d["tasks"][0]["attempts"] = []
        d["events"] = []
        self.put(d)
        p = {x["key"]: x["state"] for x in self.run_only()["pipeline"]}
        self.assertEqual(set(p.values()), {"pending"}, p)

    def test_10_no_process_liveness_is_invented(self):
        self.put(copy_doc())
        r = self.run_only()
        self.assertNotIn("liveness", r["tasks"][0]["attempts"][0])
        self.assertNotIn("processes", r["teams"][0])
        self.assertIn("sans observation des processus", r["source_note"])
        self.assertEqual(r["source"], "PARTIAL")
        items = {i["label"]: i["proof"] for i in r["security"]["items"]}
        self.assertEqual(items["Restriction MCP"], "NOT_MEASURED")
        self.assertEqual(items["Processus du run"], "NOT_MEASURED")


class Stop(Base):
    def test_11_unresolved_stop_blocks_the_pipeline(self):
        self.put(copy_doc(stop={"state": "UNRESOLVED", "reason_kind": "sensitive_path", "problems": 2, "started": TS}))
        r = self.run_only()
        self.assertEqual(r["security"]["stop"]["state"], "UNRESOLVED")
        self.assertEqual({p["key"]: p["state"] for p in r["pipeline"]}["teams"], "blocked")

    def test_12_acknowledgement_changes_neither_verdict_nor_pipeline(self):
        base = {"state": "UNRESOLVED", "reason_kind": "sensitive_path", "problems": 1}
        self.put(copy_doc(stop=base))
        before = self.run_only()
        self.put(copy_doc(stop={**base, "ack_by": f"H-{H}", "ack_ts": TS}))
        after = self.run_only()
        self.assertEqual(after["security"]["stop"]["state"], "UNRESOLVED")
        self.assertEqual(after["pipeline"], before["pipeline"])
        self.assertEqual(after["security"]["stop"]["ack_by"], "humain aaaa")
        d = next(x for x in after["decisions"] if x["kind"] == "Acquittement administratif")
        self.assertIn("ne prouve rien", d["text"])
        self.assertIn("ne débloque rien", d["text"])

    def test_13_interrupted_stop_stays_blocking_and_keeps_its_value(self):
        self.put(copy_doc(stop={"state": "IN_PROGRESS", "problems": 0}))
        r = cockpit.project(self.run_only(), cockpit.RUN)
        self.assertEqual(r["security"]["stop"]["state"]["value"], "IN_PROGRESS")
        self.assertEqual(next(p for p in r["pipeline"] if p["key"] == "teams")["state"]["value"], "blocked")

    def test_14_missing_or_duplicated_events_are_reported_not_filled(self):
        d = copy_doc()
        d["events"] = [{"seq": 1, "ts": TS, "kind": "run_started"}, {"seq": 2, "ts": TS, "kind": "plan_approved"}, {"seq": 2, "ts": TS, "kind": "plan_approved"}, {"seq": 5, "ts": TS, "kind": "integrated"}]
        self.put(d)
        r = self.run_only()
        self.assertEqual([e["seq"] for e in r["events"]], [1, 2, 5])
        self.assertIn("2 événement(s) manquant(s)", r["source_note"])
        self.assertIn("1 événement(s) dupliqué(s)", r["source_note"])
        d["events_malformed"] = 3
        self.put(d)
        self.assertIn("3 ligne(s) de journal illisible(s)", self.run_only()["source_note"])

    def test_15_relation_to_unknown_task_or_team_is_refused(self):
        d = copy_doc()
        d["events"][1]["task"] = "T-" + "b" * 10
        self.put(d)
        self.assert_refused("relation")
        d = copy_doc()
        d["tasks"][0]["team"] = "E-" + "b" * 10
        self.put(d)
        self.assert_refused("relation")


class Isolation(Base):
    def test_16_real_run_or_project_folder_is_refused(self):
        for marker in ("run.json", "events.jsonl", "ai_memory", ".git", ".claude"):
            d = self.tmp / f"faux-{marker.strip('.')}"
            d.mkdir()
            (d / marker).mkdir() if "." not in marker or marker.startswith(".") else (d / marker).write_text("{}")
            with self.assertRaises(adapter.Refused, msg=marker):
                adapter.load_dir(d, (KIT,))
        with self.assertRaises(adapter.Refused):
            adapter.load_dir(KIT / "cockpit" / "fixtures", (KIT,))

    def test_17_only_copy_files_are_opened(self):
        (self.root / "notes.md").write_text("contenu quelconque")
        self.put(copy_doc())
        ps, ref = self.load()
        self.assertEqual(len(ref), 1)  # refusé par son nom, sans lecture
        self.assertEqual(ref[0], "nom de fichier refusé")
        self.assertEqual(len(ps), 1)

    def test_18_code_cannot_execute_or_write_through_the_reader(self):
        for name, forbidden_calls in (("adapter.py", ("system", "popen", "remove", "unlink", "rename", "mkdir", "write", "chmod", "exec", "fork", "spawn")), ("server.py", ("system", "popen"))):
            src = (KIT / "cockpit" / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            mods = {n.name.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.Import) for n in x.names} | {x.module.split(".")[0] for x in ast.walk(tree) if isinstance(x, ast.ImportFrom)}
            self.assertFalse(mods & {"subprocess", "pmx", "pty", "shutil", "multiprocessing", "ctypes", "socket"}, name)
            calls = {x.func.attr for x in ast.walk(tree) if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and isinstance(x.func.value, ast.Name) and x.func.value.id == "os"}
            self.assertFalse(calls & set(forbidden_calls), name)
        src = (KIT / "cockpit" / "adapter.py").read_text(encoding="utf-8")
        for flag in ("O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "open("):
            if flag == "open(":
                self.assertNotIn(" open(", src)
            else:
                self.assertNotIn(flag, src)
        ex = ast.parse((KIT / "cockpit" / "extract.py").read_text(encoding="utf-8"))
        mods = {n.name.split(".")[0] for x in ast.walk(ex) if isinstance(x, ast.Import) for n in x.names}
        self.assertFalse(mods & {"subprocess", "pmx", "pty", "shutil", "socket", "http", "urllib"})
        self.assertNotIn("extract", (KIT / "cockpit" / "server.py").read_text(encoding="utf-8"))
        code = (KIT / "cockpit" / "extract.py").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'read_source\(run_dir(?:\.parents\[1\])? / "([^"]+)"\)', code)), {"run.json", "events.jsonl", "WORK_ITEMS.md"})
        self.assertEqual(code.count("read_source("), 4)  # sa définition et ces trois lectures : aucune autre source
        self.assertNotIn("stop-evidence.jsonl\"", code)  # aucun vrai fichier de preuves d'arrêt ne peut être ouvert à cette étape
        self.assertEqual(code.count("stop_evidence_records("), 1)  # sa définition, jamais appelée par l'outil


class Extraction(Base):
    POISON = "PMXFAKE-" + "poison-"

    def source(self, run="WI-20991231-MAIN-001"):
        at = chr(64)
        path, secret = "/ho" + "me/quelquun/projet/.env", "gh" + "p_" + "z" * 20
        p = self.POISON
        rd = self.tmp / "projet" / "ai_memory" / "runs" / run
        (rd / "tasks" / "a").mkdir(parents=True)
        st = {"run": run, "parent_wi": run, "title": p + "titre", "created": TS, "updated": TS, "base": "abc123", "os_user": p, "debate": {"status": "consensus", "turns": [{"data": p, "file": path, "side": "claude"}], "needs_human": False, "doc": path, "proposal": p},
              "decision": {"by": "human:" + p, "text": p + secret, "ts": TS, "debate_status": "consensus"}, "plan": {"status": "approved", "file": path, "waves": [["a"]], "approved_by": "personne" + at + "exemple.org", "approved": TS},
              "tasks": {"a": {"wi": "WI-1", "title": p, "team": "team-" + "secrete", "files": [path], "test_command": p, "acceptance": [p], "depends_on": [], "branch": p, "commit": "abcdef", "tree": "fed", "budget_base": 1,
                              "attempts": [{"n": 1, "adapter": "claude-cli", "branch": p, "worktree": path, "brief": path, "report": path, "pid": 4242, "started": TS, "ended": TS, "result": "done", "settled": "vérifiée", "cgroup": "/cg/" + p, "unit": p}],
                              "verify": {"verdict": "PASS", "commit": "abcdef", "tree": "fed", "runner": "docker", "note": path, "evidence": path, "integrity": [p], "ts": TS, "results": [{"command": p, "exit": 0, "output": f"{p}{secret}\nRan 7 tests in 0.1s\nOK\n"}]},
                              "review": {"verdict": "APPROVE", "by": "team-b:codex-cli", "commit": "abcdef", "file": path, "ts": TS, "uncovered": [p]}}},
              "stop": {"state": "UNRESOLVED", "reason": f"a : {path} : chemin sensible (secret)", "tasks": ["a"], "problems": [p, path], "started": TS, "ack": {"by": "human:" + p, "ts": TS, "alive_seen": [p]}},
              "integration": {"target": p, "commit": "abcdef", "tree": "x", "approved_by": "personne-fictive", "confirmation": {"via": "tty", "tty": "/dev/" + p, "os_user": p}, "ts": TS, "results": [p], "merged": ["a"]}, "helpers": [{"kind": "review", "key": p, "unit": p, "cgroup": p, "owner": 1, "ended": TS}]}
        (rd / "run.json").write_text(json.dumps(st), encoding="utf-8")
        ev = [{"ts": TS, "pid": 1, "event": "run_started", "title": p}, {"ts": TS, "event": "task_reopened", "task": "a", "by": "human:" + p, "reason": p}, "pas un objet", {"ts": TS, "event": "evenement_futur", "x": p, "task": p}, {"ts": TS, "event": "critical_abort", "reason": path, "stopped": [p], "verdict": "UNRESOLVED"}]
        (rd / "events.jsonl").write_text("\n".join(json.dumps(e) for e in ev) + "\n{tronqué", encoding="utf-8")
        for name in ("tasks/a/brief-a1.md", "tasks/a/team-a1.log", "tasks/a/report-a1.md", "stop-evidence.jsonl"):
            (rd / name).write_text(self.POISON + secret)
        (self.tmp / "projet" / "ai_memory" / "WORK_ITEMS.md").write_text(self.POISON)
        return rd

    def run_extract(self, rd, out=None):
        out = out or self.tmp / "sortie"
        extract.main(["--run-dir", str(rd), "--out", str(out)])
        return out

    def test_19_nothing_sensitive_or_free_text_survives_extraction(self):
        rd = self.source()
        out = self.run_extract(rd)
        files = list(out.iterdir())
        self.assertEqual(len(files), 1)
        raw = files[0].read_text(encoding="utf-8")
        for x in (self.POISON, "gh" + "p_", "/ho" + "me", "exemple.org", "personne-fictive", "team-" + "secrete", "WI-1", "abcdef", "abc123", "human:", "tty", "os_user", "4242", "worktree", "brief", "report", "title", "text"):
            self.assertNotIn(x, raw, x)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)

    def test_20_structure_stop_and_relations_are_kept(self):
        out = self.run_extract(self.source())
        doc = json.loads(next(out.iterdir()).read_text(encoding="utf-8"))
        adapter.validate_document(doc)
        self.assertEqual(doc["sources"], ["run.json", "events.jsonl"])
        self.assertEqual(doc["stop"]["state"], "UNRESOLVED")
        self.assertEqual(doc["stop"]["reason_kind"], "sensitive_path")
        self.assertEqual(doc["stop"]["problems"], 2)
        self.assertRegex(doc["stop"]["ack_by"], r"^H-")
        self.assertEqual(doc["tasks"][0]["verify"]["tests"], 7)
        self.assertEqual(doc["tasks"][0]["verify"]["integrity_problems"], 1)
        self.assertEqual(doc["events_malformed"], 2)
        self.assertEqual([e["kind"] for e in doc["events"]], ["run_started", "task_reopened", "unknown_event", "critical_abort"])
        self.assertEqual([e["seq"] for e in doc["events"]], [1, 2, 4, 5])  # la ligne illisible laisse un trou visible
        self.assertEqual(doc["events"][1]["task"], doc["tasks"][0]["id"])
        self.assertEqual(doc["plan"]["waves"][0][0], doc["tasks"][0]["id"])
        self.assertTrue(doc["tasks"][0]["attempts"][0]["tracked"])

    def test_21_sources_are_untouched_and_other_files_are_never_needed(self):
        rd = self.source()
        for name in ("tasks/a/brief-a1.md", "tasks/a/team-a1.log", "tasks/a/report-a1.md", "stop-evidence.jsonl"):
            (rd / name).chmod(0)
        before = {p.name: p.stat().st_mtime_ns for p in (rd / "run.json", rd / "events.jsonl")}
        raw = {p: (rd / p).read_bytes() for p in ("run.json", "events.jsonl")}
        self.run_extract(rd)  # réussit alors que ces fichiers sont illisibles : ils ne sont pas ouverts
        self.assertEqual({p: (rd / p).read_bytes() for p in raw}, raw)
        self.assertEqual({p.name: p.stat().st_mtime_ns for p in (rd / "run.json", rd / "events.jsonl")}, before)

    def test_22_output_location_and_source_links_are_checked(self):
        rd = self.source()
        for bad in (KIT / "copies-interdites", rd / "copies", self.tmp / "projet" / "copies", self.tmp / "projet"):
            with self.assertRaises(SystemExit, msg=bad):
                extract.main(["--run-dir", str(rd), "--out", str(bad)])
        self.assertFalse((KIT / "copies-interdites").exists())
        (self.tmp / "existant").mkdir()
        with self.assertRaises(SystemExit):
            extract.main(["--run-dir", str(rd), "--out", str(self.tmp / "existant")])
        real = rd / "run.json"
        moved = self.tmp / "ailleurs.json"
        real.rename(moved)
        real.symlink_to(moved)
        with self.assertRaises(OSError):
            extract.main(["--run-dir", str(rd), "--out", str(self.tmp / "s2")])
        self.assertFalse((self.tmp / "s2").exists())

    def test_23_homonymous_runs_get_distinct_unlinkable_pseudonyms(self):
        a = self.source()
        b_root = self.tmp / "autre" / "ai_memory" / "runs"
        b_root.mkdir(parents=True)
        shutil.copytree(a, b_root / a.name)
        out = self.tmp / "s3"
        extract.main(["--run-dir", str(a), "--run-dir", str(b_root / a.name), "--out", str(out)])
        docs = [json.loads(p.read_text()) for p in out.iterdir()]
        self.assertEqual(len(docs), 2)
        self.assertNotEqual(docs[0]["run"]["id"], docs[1]["run"]["id"])
        self.assertNotEqual(docs[0]["tasks"][0]["id"], docs[1]["tasks"][0]["id"])
        self.assertNotEqual(docs[0]["teams"][0]["id"], docs[1]["teams"][0]["id"])
        self.assertEqual([p.name for p in self.tmp.iterdir() if ".partiel" in p.name], [])

    def test_24_unrecognized_values_are_dropped_or_replaced_by_a_marker(self):
        rd = self.source()
        st = json.loads((rd / "run.json").read_text())
        st["updated"] = "/ho" + "me/quelquun"  # écarté par le contrôle d'horodatage, donc absent
        st["debate"]["status"] = "/ho" + "me/quelquun"  # remplacé par un marqueur
        (rd / "run.json").write_text(json.dumps(st))
        doc = json.loads(next(self.run_extract(rd).iterdir()).read_text())
        self.assertNotIn("updated", doc["run"])
        self.assertEqual(doc["debate"]["status"], "UNRECOGNIZED")


class Ledger(Extraction):
    def ledger(self, rd, text=None):
        at = chr(64)
        (self.tmp / "projet" / "ai_memory" / "WORK_ITEMS.md").write_text(text or f"""# Work Items

### WI-0 — {self.POISON}parent
- status: DONE
- links: /ho""" + f"""me/quelquun

### WI-1 — {self.POISON}titre
- created: 2099-01-01T00:00:00Z
- status: READY_FOR_REVIEW
- status: DONE
- blocker: {self.POISON}motif
- session: {self.POISON}session
- links: /ho""" + f"""me/quelquun/{self.POISON}
- owner: personne{at}exemple.org

### WI-2 — autre tâche d'un autre run
- status: BLOCKED
""", encoding="utf-8")

    def extract_with(self, rd, name="sortie"):
        out = self.tmp / name
        extract.main(["--run-dir", str(rd), "--with-work-items", "--out", str(out)])
        return json.loads(next(out.iterdir()).read_text(encoding="utf-8")), next(out.iterdir()).read_text(encoding="utf-8")

    def test_50_only_status_of_known_work_items_is_extracted(self):
        rd = self.source()
        self.ledger(rd)
        doc, raw = self.extract_with(rd)
        self.assertEqual(doc["tasks"][0]["status"], "READY_FOR_REVIEW")  # la première valeur du bon work item, pas celle d'un autre
        self.assertIn("WORK_ITEMS.md", doc["sources"])
        for x in (self.POISON, "WI-1", "WI-2", "WI-0", "exemple.org", "/ho" + "me", "BLOCKED", "blocker", "session", "links", "owner", "titre"):
            self.assertNotIn(x, raw, x)
        self.assertNotIn("statut des tâches non extrait", adapter.to_run(doc)["source_note"])

    def test_51_unknown_status_stays_unknown_and_missing_stays_absent(self):
        rd = self.source()
        self.ledger(rd, "### WI-1 — x\n- status: /ho" + "me/quelquun/secret\n")
        doc, raw = self.extract_with(rd)
        self.assertEqual(doc["tasks"][0]["status"], "UNRECOGNIZED")
        self.assertNotIn("quelquun", raw)
        self.assertEqual(cockpit.project(adapter.to_run(doc), cockpit.RUN)["tasks"][0]["status"]["value"], "UNKNOWN")
        self.ledger(rd, "### WI-9 — x\n- status: DONE\n")
        doc, _ = self.extract_with(rd, "sortie2")
        self.assertNotIn("status", doc["tasks"][0])

    def test_52_output_is_all_or_nothing_when_a_source_is_refused(self):
        rd = self.source()
        led = self.tmp / "projet" / "ai_memory" / "WORK_ITEMS.md"
        led.unlink()
        with self.assertRaises(OSError):
            extract.main(["--run-dir", str(rd), "--with-work-items", "--out", str(self.tmp / "s4")])
        real = self.tmp / "ailleurs.md"
        real.write_text("### WI-1 — x\n- status: DONE\n")
        led.symlink_to(real)
        with self.assertRaises(OSError):
            extract.main(["--run-dir", str(rd), "--with-work-items", "--out", str(self.tmp / "s5")])
        for n in ("s4", "s5"):
            self.assertFalse((self.tmp / n).exists())
        self.assertEqual([p.name for p in self.tmp.iterdir() if ".partiel" in p.name], [])

    def test_53_write_failure_or_invalid_doc_leaves_no_output(self):
        rd = self.source()
        real = extract.adapter.parse_bytes
        extract.adapter.parse_bytes = lambda _raw: (_ for _ in ()).throw(adapter.Refused("essai"))
        try:
            with self.assertRaises(adapter.Refused):
                extract.main(["--run-dir", str(rd), "--out", str(self.tmp / "s6")])
        finally:
            extract.adapter.parse_bytes = real
        self.assertFalse((self.tmp / "s6").exists())
        reals = extract.os.rename
        extract.os.rename = lambda *_a: (_ for _ in ()).throw(OSError("essai"))
        try:
            with self.assertRaises(OSError):
                extract.main(["--run-dir", str(rd), "--out", str(self.tmp / "s7")])
        finally:
            extract.os.rename = reals
        self.assertFalse((self.tmp / "s7").exists())  # le nom final n'apparaît jamais sans une sortie complète

    def test_54_sources_including_ledger_are_unchanged(self):
        rd = self.source()
        self.ledger(rd)
        led = self.tmp / "projet" / "ai_memory" / "WORK_ITEMS.md"
        files = [rd / "run.json", rd / "events.jsonl", led]
        before = [(f.read_bytes(), f.stat().st_mtime_ns) for f in files]
        self.extract_with(rd)
        self.assertEqual([(f.read_bytes(), f.stat().st_mtime_ns) for f in files], before)

    def test_55_no_pseudonym_is_shared_between_projects(self):
        a = self.source()
        self.ledger(a)
        b_project = self.tmp / "autre"
        shutil.copytree(self.tmp / "projet", b_project)
        out = self.tmp / "s8"
        extract.main(["--run-dir", str(a), "--run-dir", str(b_project / "ai_memory" / "runs" / a.name), "--with-work-items", "--out", str(out)])
        raws = [p.read_bytes() for p in out.iterdir()]
        self.assertEqual(len(raws), 2)
        self.assertEqual(extract.pseudonym_collisions(raws), set())
        self.assertEqual(extract.pseudonym_collisions([b'{"x": "T-' + b"a" * 10 + b'"}', b'{"y": "T-' + b"a" * 10 + b'"}']), {"T-" + "a" * 10})
        real = extract.pseudonym_collisions
        extract.pseudonym_collisions = lambda _d: {"T-" + "a" * 10}
        try:
            with self.assertRaises(SystemExit):
                extract.main(["--run-dir", str(a), "--out", str(self.tmp / "s9")])
        finally:
            extract.pseudonym_collisions = real
        self.assertFalse((self.tmp / "s9").exists())


class StopEvidence(Base):
    """Données synthétiques uniquement : aucun vrai fichier stop-evidence.jsonl n'est lu."""
    POISON = "PMXFAKE-" + "preuve-"

    def text(self):
        p = self.POISON
        path = "/ho" + "me/quelquun/" + p
        rows = [{"task": "a", "attempt": 1, "unit": p + "unit.scope", "cgroup": path, "dir": path, "pid": 4242, "pid_start": 99, "term": [111, 222], "errors": [p + "erreur"], "before": True, "populated_after": False, "killed": True},
                {"task": "review:" + p, "attempt": 2, "pid": 4343, "term": [], "errors": [], "before": False, "populated_after": "illisible", "killed": 1}]
        return "\n".join(json.dumps(x) for x in ({"ts": TS, "kind": "attempt_end", "task": "a", "attempt": 1, "state": "STOPPED", "attempts": rows[:1]}, {"ts": TS, "kind": "critical_stop", "state": "UNRESOLVED", "reason": p + path, "tasks": [p], "problems": [p, path], "ack": {"by": "human:" + p}, "attempts": rows}, {"ts": p, "kind": p + " " + path, "state": "/ho" + "me/x"})) + "\n{tronqué"

    def records(self):
        return extract.stop_evidence_records(self.text(), extract.Pseudo(b"k" * 32, "scope"))

    def test_60_only_allowed_fields_survive(self):
        recs, malformed = self.records()
        raw = json.dumps(recs, ensure_ascii=False)
        for x in (self.POISON, "/ho" + "me", "4242", "4343", "unit", "cgroup", "pid", "dir", "reason", "ack", "human", "review:", "111"):
            self.assertNotIn(x, raw, x)
        self.assertEqual(malformed, 1)
        allowed = {"kind", "state", "ts", "task", "attempt", "problems", "attempts"}
        row_allowed = {"task", "attempt", "before", "populated_after", "killed", "term", "errors"}
        for r in recs:
            self.assertLessEqual(set(r), allowed)
            for a in r["attempts"]:
                self.assertLessEqual(set(a), row_allowed)

    def test_61_counts_and_booleans_are_kept_and_bad_values_dropped(self):
        recs, _ = self.records()
        self.assertEqual((recs[0]["kind"], recs[0]["state"], recs[0]["ts"], recs[0]["attempt"]), ("attempt_end", "STOPPED", TS, 1))
        a = recs[0]["attempts"][0]
        self.assertEqual((a["before"], a["populated_after"], a["killed"], a["term"], a["errors"]), (True, False, True, 2, 1))
        self.assertEqual((recs[1]["state"], recs[1]["problems"]), ("UNRESOLVED", 2))
        b = recs[1]["attempts"][1]
        self.assertNotIn("populated_after", b)  # valeur illisible : absente, donc indéterminée, jamais False
        self.assertNotIn("killed", b)
        self.assertNotIn("task", b)
        self.assertEqual(recs[2]["kind"], "UNRECOGNIZED")
        self.assertEqual(recs[2]["state"], "UNRECOGNIZED")
        self.assertNotIn("ts", recs[2])

    def test_62_records_pass_the_reader_and_keep_verdict_separate(self):
        ps = extract.Pseudo(b"k" * 32, "scope")
        recs, _ = extract.stop_evidence_records(self.text(), ps)
        d = copy_doc(stop={"state": "UNRESOLVED", "reason_kind": "sensitive_path", "problems": 2, "ack_by": f"H-{H}", "ack_ts": TS})
        t = ps("T", "a")
        d["tasks"][0]["id"] = t
        d["plan"]["waves"] = [[t]]
        d["events"][1]["task"] = t
        d["stop_evidence"] = recs
        self.put(d)
        r = self.run_only()
        self.assertEqual(r["security"]["stop"]["state"], "UNRESOLVED")  # ni la preuve ni l'acquittement ne changent le verdict
        item = next(i for i in r["security"]["items"] if i["label"] == "Preuves d'arrêt des cgroups")
        self.assertIn("1 indéterminé(s)", item["value"])

    def test_63_reader_refuses_forbidden_fields_in_stop_evidence(self):
        for field in ("pid", "unit", "cgroup", "dir", "reason"):
            d = copy_doc(stop_evidence=[{"kind": "attempt_end", "attempts": [{field: 1}]}])
            self.put(d)
            self.assert_refused("champ non autorisé")
        self.put(copy_doc(stop_evidence=[{"kind": "attempt_end", "reason": "x"}]))
        self.assert_refused("champ non autorisé")
        self.put(copy_doc(stop_evidence=[{"kind": "attempt_end", "task": "T-" + "b" * 10}]))
        self.assert_refused("relation")


class RuntimeAudit(Base):
    """Observation à l'exécution, avec le journal d'audit de Python : ne voit que ce qui passe par Python, pas un code natif."""

    CHILD = """
import http.client, json, os, pathlib, socket, sys, threading, time
copies, kit, witness, out = sys.argv[1:5]
seen = []
BAD = {"subprocess.Popen", "os.system", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn", "os.spawn", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move", "pty.spawn", "ctypes.dlopen"}
def hook(ev, args):
    if ev in BAD:
        seen.append([ev, str(args[0])[:80] if args else ""])
    elif ev == "open" and len(args) >= 3:
        mode, flags = args[1], args[2]
        wr = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
        if wr:
            seen.append(["write", str(args[0])[:80]])
sys.path.insert(0, kit + "/cockpit")
sys.dont_write_bytecode = True
sys.addaudithook(hook)
pathlib.Path(witness).write_text("x")  # témoin : le journal voit bien une écriture
if not any(s[0] == "write" and "temoin" in s[1] for s in seen):
    sys.exit(9)
os.mkdir(witness + ".d")
if not any(s[0] == "os.mkdir" for s in seen):
    sys.exit(9)
seen.clear()
import server as cockpit
srv = cockpit.Server("127.0.0.1", 0, tick=0.1, heartbeat=0.2, copies=copies)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_port
hdr = {"Host": f"127.0.0.1:{port}", "Cookie": f"cockpit={srv.token}"}
for method in ("GET", "HEAD", "POST", "PUT", "DELETE"):
    for path in ("/", "/app.js", "/live.js", "/api/v1/snapshot", "/x"):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5); c.request(method, path, headers=hdr); c.getresponse().read(); c.close()
s = socket.create_connection(("127.0.0.1", port)); s.sendall(f"GET /api/v1/stream HTTP/1.1\\r\\nHost: 127.0.0.1:{port}\\r\\nCookie: cockpit={srv.token}\\r\\n\\r\\n".encode()); s.settimeout(1); s.recv(4096); s.close()
time.sleep(0.5)
print(json.dumps(list(seen)), flush=True)
os._exit(0)
"""

    def test_70_server_on_copies_neither_writes_nor_spawns_at_runtime(self):
        self.put(copy_doc())
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        witness = self.tmp / "temoin"
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}
        p = subprocess.run([sys.executable, "-I", "-B", "-c", self.CHILD, str(self.root), str(KIT), str(witness), str(self.tmp / "o")], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 0, p.stderr[-600:])
        self.assertEqual(json.loads(p.stdout.strip().splitlines()[-1]), [])
        self.assertEqual({q.name: (q.read_bytes(), q.stat().st_mtime_ns) for q in self.root.iterdir()}, before)


class Stream(Base):
    def start(self, heartbeat=0.2, tick=0.1, copies=True):
        self.put(copy_doc())
        self.srv = cockpit.Server("127.0.0.1", 0, tick=tick, heartbeat=heartbeat, copies=str(self.root) if copies else None)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.close_all)
        self.port = self.srv.server_port

    def get(self, path="/api/v1/snapshot", method="GET"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, headers={"Host": f"127.0.0.1:{self.port}", "Cookie": f"cockpit={self.srv.token}"})
        r = c.getresponse()
        b = r.read()
        c.close()
        return r, b

    def snap(self):
        return json.loads(self.get()[1])

    def stream(self, last=None, until=lambda buf: False, timeout=4):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        extra = f"Last-Event-ID: {last}\r\n" if last else ""
        s.sendall(f"GET /api/v1/stream HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nCookie: cockpit={self.srv.token}\r\n{extra}\r\n".encode())
        s.settimeout(0.3)
        buf, end = b"", time.time() + timeout
        while time.time() < end and not until(buf):
            try:
                buf += s.recv(65536)
            except TimeoutError:
                pass
        s.close()
        return buf

    @staticmethod
    def events(buf, kind):
        return [json.loads(x) for x in re.findall(rf"event: {kind}\ndata: (.*)\n".encode(), buf)]

    def test_25_snapshot_comes_from_copies_labelled_as_such(self):
        self.start()
        s = self.snap()
        self.assertEqual((s["source"], s["read_only"], s["source_state"]["value"]), ("copies", True, "OK"))
        self.assertEqual(s["projects"][0]["runs"][0]["id"], "R-aaaa")

    def test_26_every_write_attempt_is_refused_on_copies_too(self):
        self.start()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        for m in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            for p in ("/api/v1/snapshot", "/api/v1/stream", "/"):
                self.assertEqual(self.get(p, m)[0].status, 405, (m, p))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)

    def test_27_new_event_in_copy_reaches_the_stream(self):
        self.start()
        hello_seq = self.snap()["seq"]
        def writer():
            time.sleep(0.4)
            d = copy_doc()
            d["events"].append({"seq": 3, "ts": TS, "kind": "verified", "task": f"T-{H}", "verdict": "PASS"})
            self.put(d)
        threading.Thread(target=writer).start()
        buf = self.stream(until=lambda b: b"event: update" in b)
        u = self.events(buf, "update")[0]
        self.assertEqual(u["seq"], hello_seq + 1)
        self.assertEqual(u["event"]["kind"], "verified")
        self.assertEqual(self.snap()["seq"], hello_seq + 1)

    def test_28_reconnection_replays_missed_updates_in_order(self):
        self.start()
        hello = self.events(self.stream(until=lambda b: b"event: hello" in b), "hello")[0]
        inst, seq = hello["instance"], hello["seq"]
        d = copy_doc()
        for n in (3, 4):  # deux événements manqués pendant la coupure
            d["events"].append({"seq": n, "ts": TS, "kind": "verified"})
        self.put(d)
        for _ in range(40):
            if self.snap()["seq"] == seq + 2:
                break
            time.sleep(0.05)
        buf = self.stream(last=f"{inst}:{seq}", until=lambda b: b.count(b"event: update") >= 2)
        self.assertFalse(self.events(buf, "hello")[0]["resync"])
        self.assertEqual([u["seq"] for u in self.events(buf, "update")], [seq + 1, seq + 2])

    def test_29_unprovable_continuity_requires_a_full_snapshot(self):
        self.start()
        inst = self.snap()["instance"]
        for last in ("autre-instance:1", f"{inst}:9999", "illisible", f"{inst}:abc"):
            h = self.events(self.stream(last=last, until=lambda b: b"event: hello" in b), "hello")[0]
            self.assertTrue(h["resync"], last)
        feed = self.srv.demo
        with feed.cond:
            for _ in range(300):
                feed.publish({"changed": True})
        self.assertIsNone(feed.since(1))  # hors de la mémoire bornée : la continuité n'est plus démontrable
        h = self.events(self.stream(last=f"{inst}:1", until=lambda b: b"event: hello" in b), "hello")[0]
        self.assertTrue(h["resync"])

    def test_30_ping_is_visible_and_carries_the_sequence(self):
        self.start()
        buf = self.stream(until=lambda b: b"event: ping" in b)
        self.assertEqual(self.events(buf, "ping")[0]["seq"], self.snap()["seq"])

    def test_31_refused_or_removed_source_is_reported_without_content(self):
        self.start()
        (self.root / "r2.copy.json").write_text(json.dumps(copy_doc(prompt="PMXFAKE-contenu")))
        for _ in range(40):
            s = self.snap()
            if s["source_state"]["value"] == "PARTIAL":
                break
            time.sleep(0.05)
        self.assertEqual(s["source_state"]["value"], "PARTIAL")
        self.assertIn("1 fichier(s) refusé(s)", s["source_note"])
        self.assertNotIn("PMXFAKE", json.dumps(s))
        self.assertEqual(len(s["projects"][0]["runs"]), 1)
        shutil.rmtree(self.root)
        for _ in range(40):
            s = self.snap()
            if s["source_state"]["value"] == "UNREADABLE":
                break
            time.sleep(0.05)
        self.assertEqual(s["source_state"]["value"], "UNREADABLE")
        self.assertEqual(s["projects"], [])  # un dossier disparu ne laisse pas un ancien état présenté comme actuel

    def test_32_run_change_updates_the_snapshot(self):
        self.start()
        seq = self.snap()["seq"]
        other = copy_doc()
        other["run"]["id"] = "R-" + "b" * 10
        self.put(other, "r2.copy.json")
        for _ in range(40):
            s = self.snap()
            if len(s["projects"][0]["runs"]) == 2:
                break
            time.sleep(0.05)
        self.assertEqual(len(s["projects"][0]["runs"]), 2)
        self.assertGreater(s["seq"], seq)
        (self.root / "r2.copy.json").unlink()
        for _ in range(40):
            s = self.snap()
            if len(s["projects"][0]["runs"]) == 1:
                break
            time.sleep(0.05)
        self.assertEqual(len(s["projects"][0]["runs"]), 1)

    def test_33_server_refuses_bad_copies_folder_without_fallback(self):
        for bad in (KIT, self.tmp / "absent"):
            with self.assertRaisesRegex(Exception, "hors du dépôt|introuvable"):
                cockpit.Server("127.0.0.1", 0, copies=str(bad))

    def test_34_csp_and_loopback_are_unchanged_with_copies(self):
        self.start()
        csp = self.get("/")[0].getheader("Content-Security-Policy")
        self.assertEqual(csp, "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.assertEqual(self.srv.socket.getsockname()[0], "127.0.0.1")
        with self.assertRaises(SystemExit):
            cockpit.Server("0.0.0.0", 0, copies=str(self.root))


@unittest.skipUnless(shutil.which("node"), "node absent")
class LiveLogic(unittest.TestCase):
    """Automate du navigateur (ui/live.js), exécuté sans navigateur ni réseau."""

    def run_js(self, steps, start=None):
        code = "const vm=require('vm'),fs=require('fs');const c={};c.globalThis=c;vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),c);const L=c.CockpitLive;let s=L.initial();const out=[];for(const e of JSON.parse(process.argv[2])){const r=L.reduce(s,{at:'T',...e});s=r.state;out.push({phase:s.phase,load:r.load,loss:s.loss&&s.loss.why,lostAt:s.lostAt,dup:s.duplicates,seq:s.seq});}console.log(JSON.stringify(out));"
        p = subprocess.run(["node", "-e", code, str(KIT / "cockpit" / "ui" / "live.js"), json.dumps(steps)], capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    HELLO = {"type": "hello", "instance": "i1", "seq": 5, "resync": True, "heartbeat": 1}
    SNAP = {"type": "snapshot", "instance": "i1", "seq": 5}

    def test_40_live_only_after_stream_and_snapshot(self):
        o = self.run_js([self.HELLO, self.SNAP])
        self.assertEqual(o[0]["phase"], "resync")
        self.assertTrue(o[0]["load"])
        self.assertEqual(o[1]["phase"], "live")
        self.assertIsNone(o[1]["loss"])

    def test_41_error_never_shows_live_and_snapshot_does_not_restore_it(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "error"}, {"type": "snapshot", "instance": "i1", "seq": 5}])
        self.assertEqual(o[2]["phase"], "offline")
        self.assertEqual(o[2]["lostAt"], "T")
        self.assertEqual(o[3]["phase"], "offline")  # une réponse tardive ne rétablit pas « En direct »

    def test_42_reconnection_without_miss_returns_live_without_loss(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "error"}, {**self.HELLO}])
        self.assertEqual(o[-1]["phase"], "live")
        self.assertIsNone(o[-1]["loss"])
        self.assertIsNone(o[-1]["lostAt"])

    def test_43_reconnection_with_replay_stays_syncing_until_proven(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "error"}, {"type": "hello", "instance": "i1", "seq": 7, "resync": False, "heartbeat": 1}, {"type": "update", "seq": 6}, {"type": "snapshot", "instance": "i1", "seq": 6}, {"type": "update", "seq": 7}, {"type": "snapshot", "instance": "i1", "seq": 7}])
        self.assertEqual(o[3]["phase"], "resync_replay")
        self.assertEqual(o[-1]["phase"], "live")
        self.assertIsNone(o[-1]["loss"])

    def test_44_unprovable_reconnection_reports_loss_and_reloads(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "error"}, {"type": "hello", "instance": "i1", "seq": 9, "resync": True, "heartbeat": 1}])
        self.assertEqual(o[-1]["phase"], "resync")
        self.assertTrue(o[-1]["load"])
        self.assertIn("continuité", o[-1]["loss"])

    def test_45_server_restart_reports_loss(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "error"}, {"type": "hello", "instance": "i2", "seq": 1, "resync": True, "heartbeat": 1}])
        self.assertIn("redémarré", o[-1]["loss"])
        self.assertTrue(o[-1]["load"])

    def test_46_gap_reloads_and_reports_duplicate_is_ignored(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "update", "seq": 5}, {"type": "update", "seq": 8}])
        self.assertEqual(o[2]["dup"], 1)
        self.assertFalse(o[2]["load"])
        self.assertEqual(o[2]["phase"], "live")
        self.assertIn("2 mise(s) à jour manquante(s)", o[3]["loss"])
        self.assertTrue(o[3]["load"])
        self.assertEqual(o[3]["phase"], "resync")

    def test_47_silent_stream_goes_offline_and_ping_detects_miss(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "silent"}])
        self.assertEqual(o[-1]["phase"], "offline")
        o = self.run_js([self.HELLO, self.SNAP, {"type": "ping", "seq": 9}])
        self.assertIn("non reçue", o[-1]["loss"])
        self.assertTrue(o[-1]["load"])

    def test_48_failed_snapshot_and_lost_session_are_not_live(self):
        o = self.run_js([self.HELLO, {"type": "snapshot_failed", "expired": False}])
        self.assertEqual(o[-1]["phase"], "stale")
        o = self.run_js([self.HELLO, self.SNAP, {"type": "expired"}, {"type": "snapshot", "instance": "i1", "seq": 5}])
        self.assertEqual(o[-1]["phase"], "expired")

    def test_49_lost_event_from_server_reports_loss(self):
        o = self.run_js([self.HELLO, self.SNAP, {"type": "lost", "seq": 50}])
        self.assertIn("perdues", o[-1]["loss"])
        self.assertTrue(o[-1]["load"])


for _n in [n for n in dir(Extraction) if n.startswith("test_")]:
    setattr(Ledger, _n, None)  # helpers partagés : ces tests ne sont pas rejoués


if __name__ == "__main__":
    unittest.main()
