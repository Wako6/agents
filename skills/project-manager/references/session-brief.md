# Brief de session-feature (à coller en premier message de la nouvelle session)

> Le PM remplit les champs et l'utilisateur ouvre une **nouvelle session Claude Code Desktop sur le même projet, option worktree, branche indiquée**.
> Le brief ne porte que des **paramètres**. Les règles (projet GitLab, branche d'intégration, labels, autorisations) sont celles de la configuration du projet (`.claude/project-manager.config.json` et la source qu'elle désigne — par exemple `CLAUDE.md` § Référentiel), du profil de projet et de `.claude/agents/feature-lead.md`, sans exception propre à une session.

```
Tu es feature-lead (agent .claude/agents/feature-lead.md). Charge-le et applique-le.

issue: #NN
branch: feat/<slug>-<NN>
spec: docs/specs/F<n>-<slug>.md
dependencies: aucune | #12 (MR !34 intégrée dans <intégration> — commit <sha court>)
tier: medium | complex
specialized_review: aucune | django-reviewer

Commence par le préflight et confirme-moi en 3 lignes périmètre / fichiers / risques avant de déléguer quoi que ce soit.
```
