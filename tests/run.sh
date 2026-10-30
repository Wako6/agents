#!/usr/bin/env bash
# Suite de tests du Project Manager V3 — tout s'exécute dans un HOME et des dépôts jetables.
# Ne touche jamais ~/.claude réel ni aucun dépôt réel. Les tests de compatibilité « demo » travaillent sur une
# COPIE de quelques fichiers du dépôt désigné par COMPAT_REPO (optionnel, lecture seule) ; sans COMPAT_REPO ils sont ignorés.
# Usage : tests/run.sh   ou   COMPAT_REPO=/chemin/projet tests/run.sh     (exit 0 si tout passe)
set -uo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
SANDBOX="$(mktemp -d)"
REAL_HOME="$HOME"
# état des SEULS chemins que le kit pourrait écrire dans le ~/.claude réel (Claude Code écrit lui-même ses transcriptions ailleurs dans ~/.claude)
kitstate() { for p in skills agents rules CLAUDE.md settings.json .project-manager-v3-kit; do q="$REAL_HOME/.claude/$p"; if [ -e "$q" ]; then echo "$p $(find "$q" -type f 2>/dev/null | sort | xargs -r sha256sum 2>/dev/null | sha256sum)"; else echo "$p absent"; fi; done; }
REAL_BEFORE="$(kitstate)"
export HOME="$SANDBOX/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL="$SANDBOX/gitconfig"; printf '[user]\n\tname = t\n\temail = t@invalid\n[init]\n\tdefaultBranch = main\n' > "$GIT_CONFIG_GLOBAL"
PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf '  ✔ %s\n' "$1"; }
ko()   { FAIL=$((FAIL+1)); printf '  ✘ %s\n' "$1"; }
skip() { SKIP=$((SKIP+1)); printf '  – %s (ignoré : %s)\n' "$1" "$2"; }
check(){ if ( set +o pipefail; eval "$2" ) >/dev/null 2>&1; then ok "$1"; else ko "$1"; fi; }
code() { ( set +o pipefail; eval "$2" ) >/dev/null 2>&1; local c=$?; if [ "$c" = "$3" ]; then ok "$1 (code $c)"; else ko "$1 (code $c, attendu $3)"; fi; }
sha(){ sha256sum "$1" | cut -d' ' -f1; }
PM="$KIT/skills/project-manager"
CFG="python3 -I -B $PM/scripts/pm_config.py"
GUARD="$PM/hooks/review-guard.sh"
newrepo() { mkdir -p "$1" && git -C "$1" init -q && git -C "$1" commit -q --allow-empty -m init; }

echo "# 1. Structure du kit"
check "un seul skill public (skills/project-manager)" "[ \"\$(find '$KIT/skills' -name SKILL.md | wc -l)\" = 1 ] && [ -f '$PM/SKILL.md' ]"
for f in "$PM/SKILL.md" "$KIT"/agents/*.md "$KIT"/optional-agents/*.md; do
  check "frontmatter name + description : ${f#"$KIT"/}" "python3 -I - '$f' <<'PY'
import sys,re
t=open(sys.argv[1]).read(); m=re.match(r'^---\n(.*?)\n---\n',t,re.S); assert m
fm=m.group(1); assert re.search(r'^name: [a-z0-9-]+$',fm,re.M); assert re.search(r'^description: \".+\"$',fm,re.M)
PY"
done
check "description du skill ≤ 1024 caractères" "[ \"\$(sed -n 's/^description: //p' '$PM/SKILL.md' | head -1 | tr -d '\n' | wc -m)\" -le 1024 ]"
check "nom d'agent == nom de fichier" "for f in '$KIT'/agents/*.md '$KIT'/optional-agents/*.md; do n=\$(sed -n 's/^name: //p' \$f | head -1); [ \"\$n\" = \"\$(basename \$f .md)\" ] || exit 1; done"
check "model : valeurs documentées" "! grep -hE '^model:' '$KIT'/agents/*.md '$KIT'/optional-agents/*.md | grep -vE '^model: (inherit|haiku|sonnet|opus|fable|claude-[a-z0-9.-]+)$'"
check "références citées par SKILL.md : toutes présentes" "for r in \$(grep -ohE 'references/[a-z-]+\.md' '$PM/SKILL.md' | sort -u); do [ -f '$PM'/\$r ] || exit 1; done"
check "protocoles ex-skills présents et routés (problem-solver, memory-clean)" "grep -q 'problem-solver.md' '$PM/SKILL.md' && grep -q 'memory-clean.md' '$PM/SKILL.md' && [ -f '$PM/references/problem-solver.md' ] && [ -f '$PM/references/memory-clean.md' ]"
check "rôles cités par le runbook présents comme agents" "for r in explorer code-base-analyst solution-architect developer devops-engineer verifier feature-lead backend-reviewer-analyst frontend-reviewer-analyst django-reviewer rules-curator memory-cleaner; do [ -f '$KIT'/agents/\$r.md ] || exit 1; grep -q \"\\\`\$r\\\`\" '$PM/references/manager-runbook.md' || exit 1; done"
check "aucun agent dupliqué (django-reviewer-analyst fusionné)" "[ ! -e '$KIT/agents/django-reviewer-analyst.md' ]"
check "cascade guard : Skill interdit à tous les agents" "for f in '$KIT'/agents/*.md '$KIT'/optional-agents/*.md; do grep -qE '^disallowedTools: .*\bSkill\b' \$f || exit 1; done"
check "cascade guard : Agent interdit à tous sauf feature-lead" "for f in '$KIT'/agents/*.md '$KIT'/optional-agents/*.md; do [ \"\$(basename \$f)\" = feature-lead.md ] && continue; grep -qE '^disallowedTools: .*\bAgent\b' \$f || exit 1; done"
check "verifier et reviewers sans outil Write (note/rapport inline)" "for a in verifier django-reviewer backend-reviewer-analyst frontend-reviewer-analyst ../optional-agents/flutter-reviewer-analyst ../optional-agents/flutter-analyst; do grep -E '^tools:' '$KIT'/agents/\$a.md | grep -q Write && exit 1; done; true"
check "reviewers : hook review-guard déclaré" "for a in django-reviewer backend-reviewer-analyst frontend-reviewer-analyst ../optional-agents/flutter-reviewer-analyst ../optional-agents/flutter-analyst; do grep -q 'review-guard.sh' '$KIT'/agents/\$a.md || exit 1; done"
check "aucun ID WI sans BSLUG (bug A2, motif corrigé)" "! grep -rqE 'WI-YYYYMMDD-#' '$KIT/agents' '$KIT/skills' '$KIT/rules'"
check "aucun chemin de note en gras (bug A1)" "! grep -rqE '(DD|[0-9])\*\*ROLE-' '$KIT/agents' '$KIT/skills'"
check "aucun résidu de conversion Codex" "! grep -rIE 'Codex CLI user|main Codex conversation|spawned sub-agent' '$KIT/agents' '$KIT/skills' | grep -q ."
check "aucune dépendance obligatoire à Codex/Claudex" "! grep -rEi '(codex|claudex)[^.]*(is required|must be installed|obligatoire)' '$KIT/skills' '$KIT/agents' | grep -q ."
check "frontmatter YAML valide (pyyaml si présent)" "python3 -I - '$KIT' <<'PY'
import pathlib,re,sys
try:
    import yaml
except ImportError:
    sys.exit(0)
k=pathlib.Path(sys.argv[1])
for f in list((k/'agents').rglob('*.md'))+list((k/'optional-agents').glob('*.md'))+[k/'skills/project-manager/SKILL.md']:
    d=yaml.safe_load(re.match(r'^---\n(.*?)\n---\n',f.read_text(),re.S).group(1)); assert d['name'] and d['description']
PY"
check "routage : intentions FR présentes (statut, analyse, multi-équipes, implémentation, mémoire, règles, question)" "for t in 'Status / resume' 'Analysis / decision' 'Multi-feature / multi-team' 'Implementation' 'Memory housekeeping' 'Rules / knowledge' 'Question only'; do grep -q \"\$t\" '$PM/SKILL.md' || exit 1; done && grep -q 'nettoie la mémoire' '$PM/SKILL.md' && grep -q 'cadrer' '$PM/SKILL.md'"
check "work items : table de correspondance des 8 statuts" "for s in OPEN IN_PROGRESS READY_FOR_VERIFICATION READY_FOR_REVIEW BLOCKED ESCALATED STALE DONE; do grep -q \"\\\`\$s\\\`\" '$PM/references/work-items.md' || exit 1; done && for l in todo doing tests review blocked; do grep -q \"\\\`\$l\\\`\" '$PM/references/work-items.md' || exit 1; done"
check "garde-fous du PM de demo conservés (S7, accord par opération, merge humain, session lead, mode local)" "grep -q 'INTÉGRÉE' '$PM/references/backend-gitlab.md' && grep -q 'INCERTAINE' '$PM/references/backend-gitlab.md' && grep -q 'One explicit user approval per outgoing operation' '$PM/SKILL.md' && grep -q 'No merge by the AI' '$PM/SKILL.md' && grep -q 'PENDING_GITLAB.md' '$PM/references/backend-gitlab.md' && grep -q 'lead session' '$PM/SKILL.md'"
check "triage des règles en deux temps (propose / apply)" "grep -q 'step: propose' '$KIT/agents/rules-curator.md' && grep -q 'step: apply' '$KIT/agents/rules-curator.md' && grep -q 'step: propose' '$PM/references/rules-wiki.md'"
check "aucune règle d'installation de settings/hooks/policy dans le kit" "[ ! -e '$KIT/settings.json' ] && [ ! -d '$KIT/hooks' ] && ! find '$KIT' -name policy.json | grep -q ."

echo "# 2. review-guard (V3 durci)"
G() { printf '%s' "$1" | CLAUDE_PROJECT_DIR=/repo "$GUARD" 2>/dev/null; }
for c in 'curl -s http://x/api/items' 'curl -sI http://x' 'git diff main' 'python manage.py test' 'rg -n TODO src' "wget -qO- http://x" 'git branch -a' 'find . -name "*.py"'; do
  check "autorise : $c" "G '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":$(python3 -I -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$c")}}'"
done
for c in 'env' 'curl -X POST http://x/api' 'curl -d a=1 http://x' 'curl -o out http://x' 'curl --request DELETE http://x' 'http POST http://x' 'wget http://x/f' 'find . -delete' 'git branch -D x' 'echo x > y' 'git add -A && git commit -m x' 'python manage.py migrate' 'rm -rf x' 'cat a; rm b' 'echo $(id)'; do
  check "refuse : $c" "! G '{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":$(python3 -I -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$c")}}'"
done
for t in Write Edit MultiEdit NotebookEdit; do
  check "refuse l'outil $t (même vers ai_doc/reports)" "! G '{\"tool_name\":\"$t\",\"tool_input\":{\"file_path\":\"/repo/ai_doc/reports/R.md\"}}'"
done

echo "# 3. Règles natives et rules_sync"
check "règles : frontmatter optionnel valide" "for f in '$KIT'/rules/*.md '$KIT'/templates/project-rules/*.md; do python3 -I - \$f <<'PY' || exit 1
import sys,re
t=open(sys.argv[1]).read()
if t.startswith('---'):
    m=re.match(r'^---\n(.*?)\n---\n',t,re.S); assert m
    for l in m.group(1).splitlines(): assert re.match(r'^(paths|description):',l) or l.startswith('  ')
assert t.strip()
PY
done"
check "règle globale neutre vis-à-vis du backend (pas d'identifiant imposé)" "grep -q 'Registre unique' '$KIT/rules/00-kit-workflow.md' && grep -q '#NN' '$KIT/rules/00-kit-workflow.md'"
check "règle globale : un accord par opération sortante" "grep -q 'un accord explicite par opération sortante' '$KIT/rules/00-kit-workflow.md'"
check "rules_sync --check sur l'exemple" "python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$KIT/templates/ai_rules-example' --out '$SANDBOX/r1' --check"
check "rules_sync --write puis idempotent" "python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$KIT/templates/ai_rules-example' --out '$SANDBOX/r2' --write && [ -f '$SANDBOX/r2/ai-rules.md' ] && python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$KIT/templates/ai_rules-example' --out '$SANDBOX/r2' --write | grep -c 'rien à faire' >/dev/null"
check "rules_sync détecte un doublon d'ID" "! python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$KIT/tests/fixtures/ai_rules-duplicate' --out '$SANDBOX/r3' --check"
check "rules_sync détecte une dépréciée exportée" "! python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$KIT/tests/fixtures/ai_rules-deprecated' --out '$SANDBOX/r4' --check"

echo "# 4. Configuration de projet et détection du registre"
mk() { newrepo "$SANDBOX/$1"; }
mk p-ledger; mkdir -p "$SANDBOX/p-ledger/ai_memory"; echo 'MAIN=WI-20260325-MAIN-004' > "$SANDBOX/p-ledger/ai_memory/WI_COUNTER.lock"
code "détection : ledger existant (compat V2)" "$CFG detect --root '$SANDBOX/p-ledger'" 0
mk p-new
code "détection : projet neuf → confirmation" "$CFG detect --root '$SANDBOX/p-new'" 2
mk p-gl; mkdir -p "$SANDBOX/p-gl/ai_memory"; printf -- '- active_issues: []\n- gitlab_reachable: true\n' > "$SANDBOX/p-gl/ai_memory/REPO_STATE.md"
code "détection : signaux GitLab seuls → confirmation" "$CFG detect --root '$SANDBOX/p-gl'" 2
mk p-both; mkdir -p "$SANDBOX/p-both/ai_memory"; cp "$SANDBOX/p-gl/ai_memory/REPO_STATE.md" "$SANDBOX/p-both/ai_memory/"; touch "$SANDBOX/p-both/ai_memory/WORK_ITEMS.md"
code "détection : deux registres → conflit" "$CFG detect --root '$SANDBOX/p-both'" 3
mkdir -p "$SANDBOX/p-new/.claude"; cp "$KIT/adapters/generic/project-manager.config.json" "$SANDBOX/p-new/.claude/"
code "configuration générique (ledger) valide" "$CFG validate --root '$SANDBOX/p-new'" 0
mk p-bad; mkdir -p "$SANDBOX/p-bad/.claude"; printf '| `<projet>` | `g/p` | x |\n| `<intégration>` | `dev` | x |\n| labels d'"'"'état | `todo` · `doing` | x |\n' > "$SANDBOX/p-bad/CLAUDE.md"
echo '{"schema":"pm-v3/1","work_items":{"backend":"gitlab-issues","gitlab":{"referential":{"file":"CLAUDE.md","rows":{"project":"`<projet>`","integration":"`<intégration>`","state_labels":"labels d'"'"'état"}},"project":"g/p"}}}' > "$SANDBOX/p-bad/.claude/project-manager.config.json"
code "configuration invalide : référentiel ET valeur directe" "$CFG validate --root '$SANDBOX/p-bad'" 1
echo '{"schema":"pm-v3/1","work_items":{"backend":"gitlab-issues","gitlab":{"referential":{"file":"CLAUDE.md","rows":{"project":"`<absent>`","integration":"`<intégration>`","state_labels":"labels d'"'"'état"}}}}}' > "$SANDBOX/p-bad/.claude/project-manager.config.json"
code "configuration invalide : ligne de référentiel absente (jamais de valeur par défaut)" "$CFG validate --root '$SANDBOX/p-bad'" 1
echo '{"schema":"pm-v3/1","work_items":{"backend":"gitlab-issues","gitlab":{"project":"g/p","integration_branch":"dev","state_labels":["todo","doing"]}}}' > "$SANDBOX/p-bad/.claude/project-manager.config.json"; mkdir -p "$SANDBOX/p-bad/ai_memory"; touch "$SANDBOX/p-bad/ai_memory/WORK_ITEMS.md"
code "configuration invalide : second registre (ledger dans un projet GitLab)" "$CFG validate --root '$SANDBOX/p-bad'" 1
echo '{"schema":"pm-v3/1","work_items":{"backend":"jira"}}' > "$SANDBOX/p-new/.claude/x.json"
code "configuration invalide : backend inconnu" "$CFG validate --root '$SANDBOX/p-new' --config '$SANDBOX/p-new/.claude/x.json'" 1

echo "# 5. Installateur et rollback"
check "dry-run n'écrit rien" "'$KIT/install.sh' --dry-run && [ ! -d '$HOME/.claude' ]"
check "installation initiale (scope user, hors dépôt)" "cd '$SANDBOX' && '$KIT/install.sh' --with-rules | grep -c 'à créer, 0 identiques' >/dev/null"
check "idempotence (0 création, 0 mise à jour, 0 conflit)" "cd '$SANDBOX' && '$KIT/install.sh' --with-rules | grep -c '0 à créer, .* 0 à mettre à jour, 0 conflit' >/dev/null"
check "un seul skill installé, ex-skills absents" "[ -f '$HOME/.claude/skills/project-manager/SKILL.md' ] && [ ! -e '$HOME/.claude/skills/project-problem-solver' ] && [ ! -e '$HOME/.claude/skills/project-memory-clean' ]"
echo '# modif utilisateur' >> "$HOME/.claude/agents/verifier.md"
check "fichier modifié par l'utilisateur → conflit, non écrasé" "cd '$SANDBOX' && '$KIT/install.sh' | grep -c '1 conflit' >/dev/null && grep -q 'modif utilisateur' '$HOME/.claude/agents/verifier.md'"
check "--merge dépose .kit-new sans écraser" "cd '$SANDBOX' && '$KIT/install.sh' --merge >/dev/null && [ -f '$HOME/.claude/agents/verifier.md.kit-new' ] && grep -q 'modif utilisateur' '$HOME/.claude/agents/verifier.md'"
check "--force sauvegarde puis écrase" "cd '$SANDBOX' && '$KIT/install.sh' --force >/dev/null && ! grep -q 'modif utilisateur' '$HOME/.claude/agents/verifier.md' && grep -rq 'modif utilisateur' '$HOME/.claude/.project-manager-v3-kit/'"
check "rollback restaure le fichier utilisateur" "'$KIT/rollback.sh' --dest '$HOME/.claude' >/dev/null && grep -q 'modif utilisateur' '$HOME/.claude/agents/verifier.md'"
check "settings / hooks / policy / CLAUDE.md jamais créés" "[ ! -e '$HOME/.claude/settings.json' ] && [ ! -d '$HOME/.claude/hooks' ] && [ ! -e '$HOME/.claude/policy.json' ] && [ ! -e '$HOME/.claude/CLAUDE.md' ]"
check "aucun rm -rf dans install.sh / rollback.sh" "! grep -vE '^\s*#' '$KIT/install.sh' '$KIT/rollback.sh' | grep -c 'rm -rf' >/dev/null"
code "--adapter refusé hors scope projet" "cd '$SANDBOX' && '$KIT/install.sh' --adapter gitlab-multi-team --dry-run" 64
H2="$SANDBOX/h2"; mkdir -p "$H2"
check "skill étranger préexistant (scope user) : tout le skill en conflit, aucun hybride" "mkdir -p '$H2/skills/project-manager' && echo mine > '$H2/skills/project-manager/SKILL.md' && cd '$SANDBOX' && '$KIT/install.sh' --dest '$H2' >/dev/null && grep -q '^mine$' '$H2/skills/project-manager/SKILL.md' && [ \"\$(ls '$H2/skills/project-manager')\" = SKILL.md ]"

echo "# 6. Tests négatifs demandés"
mk neg-shadow; mkdir -p "$SANDBOX/neg-shadow/.claude/skills/project-manager"; echo poc > "$SANDBOX/neg-shadow/.claude/skills/project-manager/SKILL.md"
code "conflit de noms : scope user depuis un dépôt qui a son propre project-manager → refus" "cd '$SANDBOX/neg-shadow' && '$KIT/install.sh' --dest '$SANDBOX/h3'" 65
check "conflit de noms : --allow-shadowing permet de passer en connaissance de cause" "cd '$SANDBOX/neg-shadow' && '$KIT/install.sh' --dest '$SANDBOX/h3' --allow-shadowing --dry-run"
mkdir -p "$SANDBOX/ro/locked"; chmod 555 "$SANDBOX/ro/locked"
code "permissions insuffisantes → refus, rien écrit" "'$KIT/install.sh' --dest '$SANDBOX/ro/locked/.claude'" 77
check "permissions insuffisantes : aucune écriture" "[ ! -e '$SANDBOX/ro/locked/.claude' ]"
chmod 755 "$SANDBOX/ro/locked"
mk neg-git; touch "$SANDBOX/neg-git/.git/MERGE_HEAD"
code "état git inattendu (merge en cours) → refus" "cd '$SANDBOX/neg-git' && '$KIT/install.sh' --scope project" 73
rm -f "$SANDBOX/neg-git/.git/MERGE_HEAD"
mkdir -p "$SANDBOX/neg-git/.claude/agents"; echo wip > "$SANDBOX/neg-git/.claude/agents/verifier.md.kit-new"; git -C "$SANDBOX/neg-git" add -A >/dev/null; echo x > "$SANDBOX/neg-git/.claude/agents/verifier.md.kit-new"
echo "local" > "$SANDBOX/neg-git/.claude/agents/verifier.md"; git -C "$SANDBOX/neg-git" add .claude/agents/verifier.md && git -C "$SANDBOX/neg-git" commit -qm v && echo "local2" > "$SANDBOX/neg-git/.claude/agents/verifier.md"
code "état git inattendu (chemin cible modifié non commité, --force) → refus" "cd '$SANDBOX/neg-git' && '$KIT/install.sh' --scope project --force" 73
check "--allow-dirty passe outre en connaissance de cause (dry-run)" "cd '$SANDBOX/neg-git' && '$KIT/install.sh' --scope project --force --allow-dirty --dry-run"
mkdir -p "$SANDBOX/fakebin"; for c in sha256sum find awk sed mktemp cp mv git date dirname basename cat tr sort cut tail grep mkdir rmdir rm printf ls chmod env bash; do p="$(command -v $c)" && ln -sf "$p" "$SANDBOX/fakebin/$c"; done
code "dépendance manquante (python3 absent du PATH) → refus" "PATH='$SANDBOX/fakebin' bash '$KIT/install.sh' --dest '$SANDBOX/h4'" 69
H5="$SANDBOX/h5"
code "reprise interrompue : interruption simulée après 3 écritures" "cd '$SANDBOX' && PMV3_TEST_ABORT_AFTER=3 '$KIT/install.sh' --dest '$H5'" 99
check "reprise interrompue : verrou présent" "[ -f '$H5/.project-manager-v3-kit/install.lock' ]"
code "reprise interrompue : nouvelle installation refusée tant que non annulée" "cd '$SANDBOX' && '$KIT/install.sh' --dest '$H5'" 75
check "reprise interrompue : rollback annule et lève le verrou" "'$KIT/rollback.sh' --dest '$H5' >/dev/null && [ ! -f '$H5/.project-manager-v3-kit/install.lock' ] && [ -z \"\$(find '$H5' -type f ! -path '*/.project-manager-v3-kit/*' | head -1)\" ]"
check "reprise interrompue : réinstallation complète ensuite" "cd '$SANDBOX' && '$KIT/install.sh' --dest '$H5' | grep -c '0 conflit' >/dev/null"

echo "# 7. Scope projet et adaptateur"
mk proj; check "scope projet : hooks des reviewers réécrits vers \${CLAUDE_PROJECT_DIR}" "cd '$SANDBOX/proj' && '$KIT/install.sh' --scope project --with-rules >/dev/null && grep -q 'CLAUDE_PROJECT_DIR}/.claude/skills/project-manager/hooks/review-guard.sh' .claude/agents/django-reviewer.md && [ -f .claude/rules/00-kit-workflow.md ] && [ -f .claude/rules/10-ai-memory-layout.md ]"
mk proj2; check "scope projet + adaptateur générique : configuration valide" "cd '$SANDBOX/proj2' && '$KIT/install.sh' --scope project --adapter generic >/dev/null && $CFG validate --root '$SANDBOX/proj2'"

echo "# 8. Compatibilité : projet GitLab multi-équipes (fixture synthétique)"
G="$SANDBOX/gl-project"; newrepo "$G"
AD="$KIT/adapters/gitlab-multi-team"
( cd "$G" && { printf '# Projet exemple\n\n'; sed -n '/^| Clé/,$p' "$AD/referentiel.example.md"; } > CLAUDE.md && mkdir -p ai_rules ai_memory .claude/skills/project-manager .claude/agents .claude/hooks \
  && printf 'DECISION | DEC-001 | GitLab issues/labels are the task registry | decisions.md#dec-001 | Verified: 2026-01-01\n' > ai_rules/INDEX.md \
  && printf '### DEC-001 — GitLab issues/labels are the task registry\nScope: all\n' > ai_rules/decisions.md \
  && printf -- '- active_issues: []\n- gitlab_reachable: true\n' > ai_memory/REPO_STATE.md \
  && echo 'ancien PM du projet' > .claude/skills/project-manager/SKILL.md && echo 'agent du projet' > .claude/agents/explorer.md \
  && echo '#!/bin/sh' > .claude/hooks/proof-gate.sh && echo '{"deny":[]}' > .claude/settings.json && echo 'tests' > .claude/test-command \
  && git add -A && git commit -qm fixture )
gbefore="$(cd "$G" && find CLAUDE.md .claude/settings.json .claude/test-command .claude/hooks ai_rules -type f | sort | xargs sha256sum | sha256sum)"
code "GitLab : détection sans configuration → gitlab-issues à confirmer" "$CFG detect --root '$G'" 2
check "GitLab : adaptateur résolu depuis le Référentiel (groupe/projet, develop, 5 labels)" "$CFG resolve --root '$G' --config '$AD/project-manager.config.json' | python3 -I -c 'import json,sys; d=json.load(sys.stdin); g=d[\"gitlab\"]; assert g[\"project\"]==\"groupe/projet\" and g[\"integration_branch\"]==\"develop\" and g[\"state_labels\"]==[\"todo\",\"doing\",\"tests\",\"review\",\"blocked\"], g; assert d[\"errors\"]==[\"profil introuvable : .claude/project-manager.profile.md\"], d[\"errors\"]'"
code "GitLab : installation scope projet sans --force (skill étranger = unité en conflit)" "cd '$G' && '$KIT/install.sh' --scope project --adapter gitlab-multi-team" 0
check "GitLab : skill project-manager existant intact" "cd '$G' && [ -z \"\$(git status --porcelain -- .claude/skills)\" ]"
check "GitLab : agent homonyme existant intact" "cd '$G' && git diff --quiet -- .claude/agents/explorer.md"
check "GitLab : garde-fous inchangés (CLAUDE.md, settings, test-command, hooks, ai_rules)" "[ \"\$(cd '$G' && find CLAUDE.md .claude/settings.json .claude/test-command .claude/hooks ai_rules -type f | sort | xargs sha256sum | sha256sum)\" = \"$gbefore\" ]"
check "GitLab : configuration valide une fois le profil déposé" "$CFG validate --root '$G'"
check "GitLab : rollback rend le projet identique" "'$KIT/rollback.sh' --dest '$G/.claude' >/dev/null && cd '$G' && [ -z \"\$(git status --porcelain -- . ':!.claude/.project-manager-v3-kit')\" ]"
if [ -n "${COMPAT_REPO:-}" ] && [ -f "$COMPAT_REPO/CLAUDE.md" ]; then
  C="$SANDBOX/compat-copy"; newrepo "$C"; cp -p "$COMPAT_REPO/CLAUDE.md" "$C/"; [ -d "$COMPAT_REPO/ai_rules" ] && cp -rp "$COMPAT_REPO/ai_rules" "$C/"
  mkdir -p "$C/ai_memory"; cp -p "$COMPAT_REPO/ai_memory/REPO_STATE.md" "$C/ai_memory/" 2>/dev/null || true
  code "projet réel (copie) : détection sans écriture" "$CFG detect --root '$C'; test \$? -le 3" 0
  [ -d "$C/ai_rules" ] && check "projet réel (copie) : rules_sync --check" "python3 -I '$PM/scripts/rules_sync.py' --ai-rules '$C/ai_rules' --out '$SANDBOX/compat-rules' --check"
else
  skip "compatibilité sur la copie d'un projet réel" "COMPAT_REPO non défini"
fi

echo "# 9. Workflow GitLab simulé (faux serveur local, jeton factice, aucune requête réelle)"
if command -v glab >/dev/null 2>&1; then
  python3 -I - "$SANDBOX" <<'PY' > "$SANDBOX/glab-sim.log" 2>&1
import http.server, json, os, subprocess, sys, tempfile, threading
sb = sys.argv[1]; cap = []
class H(http.server.BaseHTTPRequestHandler):
    def _h(self, m):
        n = int(self.headers.get("Content-Length") or 0); b = self.rfile.read(n).decode() if n else ""
        cap.append((m, self.path, b))
        body = {"id": 1, "iid": 7, "path_with_namespace": "g/p", "default_branch": "dev", "state": "opened", "labels": ["todo"], "web_url": "http://x/i/7", "title": "t", "author": {"username": "u"}, "issues_enabled": True, "permissions": {"project_access": {"access_level": 50}}}
        data = json.dumps(body).encode(); self.send_response(201 if m == "POST" else 200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self): self._h("GET")
    def do_POST(self): self._h("POST")
    def do_PUT(self): self._h("PUT")
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", 0), H); host = f"127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
cfg = tempfile.mkdtemp(dir=sb)
open(os.path.join(cfg, "config.yml"), "w").write(f"hosts:\n  {host}:\n    token: fake-offline-token\n    api_protocol: http\n    api_host: {host}\n    git_protocol: https\n")
os.chmod(os.path.join(cfg, "config.yml"), 0o600)
env = {k: v for k, v in os.environ.items() if not k.startswith(("GITLAB_", "GLAB_"))}
env.update(GLAB_CONFIG_DIR=cfg, GITLAB_HOST=host, NO_PROXY="127.0.0.1", no_proxy="127.0.0.1", GLAB_NO_PROMPT="1", NO_COLOR="1")
R = ["-R", f"{host}/g/p"]
steps = [["issue", "create", *R, "--title", "F1 — t", "--description", "spec", "--label", "todo", "--yes"],
         ["issue", "update", "7", *R, "--label", "doing", "--unlabel", "todo"],
         ["issue", "update", "7", *R, "--label", "blocked", "--unlabel", "doing"],
         ["issue", "close", "7", *R]]
for s in steps:
    subprocess.run(["glab", *s], env=env, capture_output=True, text=True, timeout=30, cwd=sb)
srv.shutdown()
w = [(m, p, b) for m, p, b in cap if m in ("POST", "PUT")]
for m, p, b in w: print(m, p, b[:200])
def has(m, frag, *keys):
    return any(mm == m and frag in p and all(k in (p + b) for k in keys) for mm, p, b in w)
ok = (has("POST", "/issues", "todo") and has("PUT", "/issues/7", "doing", "todo") and has("PUT", "/issues/7", "blocked", "doing") and has("PUT", "/issues/7", "close"))
print("SIM", "PASS" if ok else "FAIL")
PY
  if grep -q '^SIM PASS' "$SANDBOX/glab-sim.log"; then ok "glab : create todo → doing → blocked → close (un label d'état à la fois, requêtes capturées localement)"; else ko "glab : transitions de labels simulées (voir $SANDBOX/glab-sim.log)"; fi
else
  skip "workflow GitLab simulé" "glab absent"
fi

echo "# 10. Distribution GitHub (branche claude = racine de ~/.claude)"
check "arborescence : skill, agents, règle globale, scripts, docs" "for p in skills/project-manager/SKILL.md skills/project-manager/references/manager-runbook.md skills/project-manager/scripts/pm_config.py skills/project-manager/scripts/rules_sync.py skills/project-manager/hooks/review-guard.sh rules/00-kit-workflow.md templates/project-rules/10-ai-memory-layout.md install.sh rollback.sh README.md CLAUDE.md .gitignore VERSION docs/INSTALL.md docs/MIGRATION.md docs/ROLLBACK.md docs/TESTS.md docs/MATRIX-V1-V2-V3.md; do [ -e '$KIT'/\$p ] || exit 1; done"
check "agents : 12 fichiers à plat dans agents/ (aucun sous-dossier découvert récursivement)" "[ \"\$(find '$KIT/agents' -mindepth 1 -type d | wc -l)\" = 0 ] && [ \"\$(find '$KIT/agents' -name '*.md' | wc -l)\" = 12 ]"
check "agents optionnels hors de agents/ (non chargés par un clone)" "[ \"\$(ls '$KIT'/optional-agents/*.md | wc -l)\" = 4 ]"
check "règles : un seul fichier, à plat dans rules/ (pas de sous-dossier)" "[ \"\$(find '$KIT/rules' -type f | wc -l)\" = 1 ] && [ \"\$(find '$KIT/rules' -mindepth 1 -type d | wc -l)\" = 0 ]"
check "aucun doublon de skill (noms uniques)" "[ \"\$(grep -h '^name:' '$KIT'/skills/*/SKILL.md | sort | uniq -d | wc -l)\" = 0 ] && [ \"\$(find '$KIT' -name SKILL.md | wc -l)\" = 1 ]"
check "aucun nom d'agent en double (agents + optionnels)" "[ \"\$(grep -h '^name:' '$KIT'/agents/*.md '$KIT'/optional-agents/*.md | sort | uniq -d | wc -l)\" = 0 ]"
check "scripts exécutables" "for f in install.sh rollback.sh tests/run.sh skills/project-manager/hooks/review-guard.sh skills/project-manager/scripts/pm_config.py skills/project-manager/scripts/rules_sync.py; do [ -x '$KIT'/\$f ] || exit 1; done"
check "aucune donnée sensible ni référence locale (chemins personnels, IP privées, clés, jetons, e-mails)" "! grep -rnIE '/home/[a-z]|/Users/[A-Za-z]|/mnt/c/|/tmp/claude-|scratchpad|claude-backups|\.local/state/claude|(^|[^0-9.])(10|172\.(1[6-9]|2[0-9]|3[01])|192\.168)\.[0-9]+\.[0-9]+([^0-9]|$)|glpat-|glrt-|gldt-|ghp_|github_pat_|BEGIN [A-Z ]*PRIVATE|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z.]{2,}' '$KIT' --exclude-dir=.git | grep -v 'tests/run.sh' | grep -q ."
check "aucun cache, journal ni fichier temporaire" "[ -z \"\$(find '$KIT' \( -name __pycache__ -o -name '*.pyc' -o -name '*.log' -o -name '*.jsonl' -o -name '.env*' -o -name '*.kit-new' -o -name '*.pmv3-tmp' \) -not -path '*/.git/*' | head -1)\" ]"
check "README : chemins cités présents dans l'arborescence" "for p in skills/project-manager/SKILL.md optional-agents rules/00-kit-workflow.md templates/project-rules adapters/generic adapters/gitlab-multi-team install.sh rollback.sh docs/MIGRATION.md; do grep -q \"\$p\" '$KIT/README.md' && [ -e '$KIT'/\$p ] || exit 1; done"
check "README : commande de clone documentée pour une première installation seulement" "grep -q 'git clone --branch claude --single-branch' '$KIT/README.md' && grep -qi 'première installation' '$KIT/README.md'"
ORI="$SANDBOX/origin"; mkdir -p "$ORI"; cp -a "$KIT/." "$ORI/"; git -C "$ORI" init -q -b claude && git -C "$ORI" add -A && git -C "$ORI" commit -qm dist
check ".gitignore : tous les fichiers du kit sont suivis" "[ \"\$(git -C '$ORI' ls-files | wc -l)\" = \"\$(cd '$ORI' && find . -type f -not -path './.git/*' | wc -l)\" ]"
check "git : modes exécutables enregistrés (100755)" "for f in install.sh rollback.sh tests/run.sh skills/project-manager/hooks/review-guard.sh skills/project-manager/scripts/pm_config.py skills/project-manager/scripts/rules_sync.py; do git -C '$ORI' ls-files -s \$f | grep -q '^100755' || exit 1; done"
FH="$SANDBOX/fresh-home"; mkdir -p "$FH"
check "clone direct dans un ~/.claude absent (faux HOME)" "git clone -q --branch claude --single-branch 'file://$ORI' '$FH/.claude'"
check "clone : skill, agents et règle aux chemins de Claude Code" "[ -f '$FH/.claude/skills/project-manager/SKILL.md' ] && [ \"\$(find '$FH/.claude/agents' -name '*.md' | wc -l)\" = 12 ] && [ -f '$FH/.claude/rules/00-kit-workflow.md' ] && [ -x '$FH/.claude/skills/project-manager/hooks/review-guard.sh' ]"
check "clone : chemin du hook des reviewers = \$HOME/.claude/skills/project-manager/hooks/review-guard.sh" "grep -q '\"\$HOME/.claude/skills/project-manager/hooks/review-guard.sh\"' '$FH/.claude/agents/django-reviewer.md' && HOME='$FH' sh -c 'test -x \"\$HOME/.claude/skills/project-manager/hooks/review-guard.sh\"'"
check "clone : références internes du skill résolues depuis le dossier du skill" "for r in \$(grep -ohE 'references/[a-z-]+\.md|scripts/[a-z_]+\.py' '$FH/.claude/skills/project-manager/SKILL.md' | sort -u); do [ -f '$FH/.claude/skills/project-manager/'\$r ] || exit 1; done"
check "clone : données personnelles créées ensuite jamais suivies par git" "cd '$FH/.claude' && mkdir -p projects/p/s backups plans plugins agents skills/mon-skill && echo '{}' > settings.json && echo '{\"t\":1}' > .credentials.json && echo x > history.jsonl && echo x > projects/p/s.jsonl && echo x > backups/b && echo '---' > agents/mon-agent.md && echo x > skills/mon-skill/SKILL.md && echo x > rules/perso.md && [ -z \"\$(git status --porcelain --untracked-files=all)\" ]"
check "clone : install.sh lancé depuis le clone → « rien à installer », aucune écriture" "HOME='$FH' '$FH/.claude/install.sh' --with-rules | grep -c 'rien à installer' >/dev/null && [ ! -e '$FH/.claude/.project-manager-v3-kit' ]"
code "clone dans un ~/.claude déjà non vide → refusé par git (la doc ne le recommande pas en mise à jour)" "git clone -q --branch claude --single-branch 'file://$ORI' '$FH/.claude'" 128
check "clone : mise à jour par git pull --ff-only (fichiers personnels intacts)" "echo '# v2' >> '$ORI/VERSION' && git -C '$ORI' commit -qam bump && git -C '$FH/.claude' pull -q --ff-only && grep -q 'v2' '$FH/.claude/VERSION' && [ -f '$FH/.claude/.credentials.json' ] && [ -f '$FH/.claude/agents/mon-agent.md' ]"
EH="$SANDBOX/existing-home"; mkdir -p "$EH/.claude/agents" "$EH/.claude/skills/autre-skill" "$EH/.claude/rules"; echo '{"model":"x"}' > "$EH/.claude/settings.json"; echo 'mes préférences' > "$EH/.claude/CLAUDE.md"; echo '---' > "$EH/.claude/agents/mon-agent.md"; echo s > "$EH/.claude/skills/autre-skill/SKILL.md"; echo r > "$EH/.claude/rules/perso.md"
ebefore="$(cd "$EH/.claude" && find . -type f | sort | xargs sha256sum | sha256sum)"
KC="$SANDBOX/kit-clone"; git clone -q --branch claude --single-branch "file://$ORI" "$KC"
check "config existante : installation non destructive depuis un clone séparé" "cd '$SANDBOX' && HOME='$EH' '$KC/install.sh' --with-rules >/dev/null && [ -f '$EH/.claude/skills/project-manager/SKILL.md' ] && [ -f '$EH/.claude/rules/00-kit-workflow.md' ]"
check "config existante : fichiers personnels inchangés (settings, CLAUDE.md, agent, skill, règle)" "[ \"\$(cat '$EH/.claude/CLAUDE.md')\" = 'mes préférences' ] && [ \"\$(cat '$EH/.claude/settings.json')\" = '{\"model\":\"x\"}' ] && [ -f '$EH/.claude/agents/mon-agent.md' ] && [ -f '$EH/.claude/skills/autre-skill/SKILL.md' ] && [ -f '$EH/.claude/rules/perso.md' ]"
check "config existante : idempotence" "cd '$SANDBOX' && HOME='$EH' '$KC/install.sh' --with-rules | grep -c '0 à créer, .* 0 à mettre à jour, 0 conflit' >/dev/null"
check "config existante : rollback → état initial exact" "HOME='$EH' '$KC/rollback.sh' --dest '$EH/.claude' >/dev/null && [ \"\$(cd '$EH/.claude' && find . -type f -not -path './.project-manager-v3-kit/*' | sort | xargs sha256sum | sha256sum)\" = \"$ebefore\" ]"
EH2="$SANDBOX/existing-home2"; mkdir -p "$EH2/.claude/agents"; echo 'mon explorer personnel' > "$EH2/.claude/agents/explorer.md"; echo '{}' > "$EH2/.claude/settings.json"
e2before="$(cd "$EH2/.claude" && find . -type f | sort | xargs sha256sum | sha256sum)"
check "config existante : agent personnel homonyme → conflit, puis --force, puis rollback --all → état initial exact" "cd '$SANDBOX' && HOME='$EH2' '$KC/install.sh' | grep -c '1 conflit' >/dev/null && grep -q 'mon explorer personnel' '$EH2/.claude/agents/explorer.md' && HOME='$EH2' '$KC/install.sh' --force >/dev/null && ! grep -q 'mon explorer personnel' '$EH2/.claude/agents/explorer.md' && '$KC/rollback.sh' --dest '$EH2/.claude' --all >/dev/null && [ \"\$(cd '$EH2/.claude' && find . -type f -not -path './.project-manager-v3-kit/*' | sort | xargs sha256sum | sha256sum)\" = \"$e2before\" ]"
check "installateur : exécution sans écriture → aucun nouveau manifeste" "cd '$SANDBOX' && n1=\$(ls '$HOME/.claude/.project-manager-v3-kit'/manifest-2*.tsv | wc -l) && '$KIT/install.sh' >/dev/null && n2=\$(ls '$HOME/.claude/.project-manager-v3-kit'/manifest-2*.tsv | wc -l) && [ \"\$n1\" = \"\$n2\" ]"
check "~/.claude réel : chemins du kit (skills, agents, rules, CLAUDE.md, settings.json, état de l'installateur) inchangés" "[ \"\$(REAL_HOME='$REAL_HOME'; for p in skills agents rules CLAUDE.md settings.json .project-manager-v3-kit; do q=\"\$REAL_HOME/.claude/\$p\"; if [ -e \"\$q\" ]; then echo \"\$p \$(find \"\$q\" -type f 2>/dev/null | sort | xargs -r sha256sum 2>/dev/null | sha256sum)\"; else echo \"\$p absent\"; fi; done)\" = \"$REAL_BEFORE\" ]"

echo "# 11. Pilote pmx (orchestration multi-agents, agents factices)"
if python3 -I -B "$KIT/tests/pilot/test_pmx.py" >"$SANDBOX/pmx-tests.log" 2>&1; then ok "pilote pmx : $(grep -oE 'Ran [0-9]+ tests' "$SANDBOX/pmx-tests.log")"; else ko "pilote pmx (voir $SANDBOX/pmx-tests.log)"; fi
DIMG="${PMX_DOCKER_IMAGE:-alpine:3.22}"
if docker image inspect "$DIMG" >/dev/null 2>&1; then
  if python3 -I -B "$KIT/tests/pilot/test_docker.py" >"$SANDBOX/pmx-docker-tests.log" 2>&1; then ok "pilote pmx, adaptateur docker (conteneurs réels, agent factice) : $(grep -oE 'Ran [0-9]+ tests' "$SANDBOX/pmx-docker-tests.log")"; else ko "pilote pmx docker (voir $SANDBOX/pmx-docker-tests.log)"; fi
else skip "pilote pmx, adaptateur docker" "Docker ou image $DIMG indisponible"; fi
if python3 -I -B "$KIT/tests/pilot/test_gateway.py" >"$SANDBOX/pmx-gateway-tests.log" 2>&1; then ok "pilote pmx, passerelle réseau (API simulées) : $(grep -oE 'Ran [0-9]+ tests.*|OK.*' "$SANDBOX/pmx-gateway-tests.log" | tr '\n' ' ')"; else ko "pilote pmx passerelle (voir $SANDBOX/pmx-gateway-tests.log)"; fi
if python3 -I -B "$KIT/tests/pilot/test_hybrid.py" >"$SANDBOX/pmx-hybrid-tests.log" 2>&1; then ok "pilote pmx, profil host-agents+docker-verification : $(grep -oE 'Ran [0-9]+ tests.*|OK.*' "$SANDBOX/pmx-hybrid-tests.log" | tr '\n' ' ')"; else ko "pilote pmx profil hybride (voir $SANDBOX/pmx-hybrid-tests.log)"; fi
check "pilote : adaptateur pilot-hybrid valide (pm_config)" "d=\$(mktemp -d); git -C \$d init -q; mkdir -p \$d/.claude; cp '$KIT/adapters/pilot-hybrid/project-manager.config.json' \$d/.claude/; $CFG validate --root \$d"
check "pilote : adaptateur pilot-docker valide (pm_config)" "d=\$(mktemp -d); git -C \$d init -q; mkdir -p \$d/.claude; cp '$KIT/adapters/pilot-docker/project-manager.config.json' \$d/.claude/; $CFG validate --root \$d"
check "pilote : adaptateur pilot-claudex valide (pm_config)" "d=\$(mktemp -d); git -C \$d init -q; mkdir -p \$d/.claude; cp '$KIT/adapters/pilot-claudex/project-manager.config.json' \$d/.claude/; $CFG validate --root \$d"
echo
echo "Résultat : $PASS réussis, $FAIL échoués, $SKIP ignorés  (sandbox: $SANDBOX)"
echo "Rappel : tests statiques et simulés ; ils ne valident pas une session Claude Code réelle (voir docs/TESTS.md)."
[ "$FAIL" = 0 ]
