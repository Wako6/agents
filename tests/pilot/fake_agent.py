#!/usr/bin/env python3
"""Agent factice pour les tests de pmx (adaptateur `cmd`) — n'appelle aucune CLI réelle, aucun réseau.

  fake_agent.py debate <prompt> <out> <script>        script = marqueurs par tour, ex. "continue,consensus,consensus"
  fake_agent.py team   <prompt> <out> <cwd> <behavior> behavior = ok | slow | outside | sensitive | fail | crash | blocked
  fake_agent.py review <prompt> <out> <verdict>
"""
import pathlib, re, sys, time

kind, prompt_f, out_f = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
prompt = prompt_f.read_text(encoding="utf-8")

if kind == "debate":
    turn = int(re.search(r"Tour (\d+) sur", prompt).group(1))
    script = sys.argv[4].split(",")
    m = script[min(turn, len(script)) - 1]
    marker = {"continue": "<<CONTINUE>>", "consensus": "<<CONSENSUS>>", "human": "<<WAIT_HUMAN>>"}[m]
    dis = [] if m == "consensus" else [f"désaccord du tour {turn}"]
    body = (f"Position factice au tour {turn}.\n\n```json\n"
            f'{{"position": "pos {turn}", "agreements": ["fonctions pures"], "disagreements": {dis!r}, "questions_for_user": [], "proposal": "deux modules indépendants"}}'
            "\n```\n" + marker + "\n").replace("'", '"')
    out_f.write_text(body, encoding="utf-8")
elif kind == "team":
    cwd, behavior = pathlib.Path(sys.argv[4]), sys.argv[5]
    files = re.findall(r"^- `([^`]+)`$", prompt.split("## Vérification")[0], re.M)
    if behavior == "crash":
        time.sleep(30)  # tué par le test
    if behavior in ("slow", "outside", "sensitive"):
        time.sleep(2.5)
    if behavior == "fail":
        out_f.write_text("Status: FAILED\n", encoding="utf-8")
        sys.exit(1)
    for f in files:
        p = cwd / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"// produit par l'équipe factice ({behavior})\n", encoding="utf-8")
    if behavior == "outside":
        (cwd / "README.md").write_text("hors périmètre\n", encoding="utf-8")
    if behavior == "sensitive":
        (cwd / ".env").write_text("X=1\n", encoding="utf-8")
    status = "BLOCKED" if behavior == "blocked" else "DONE"
    out_f.write_text(f"Work item | Role developer\nStatus: {status}\nFiles touched: {files}\nEvidence: fake\n", encoding="utf-8")
elif kind == "review":
    out_f.write_text(f"Aucun constat Blocker/Major.\n\nVERDICT: {sys.argv[4]}\n", encoding="utf-8")
