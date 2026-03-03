Correspond à ce qui se trouve dans le dossier ~/.codex.

Il faut installer `codex-cli`(https://developers.openai.com/codex/cli/) et le mcp `chrome devtools`(https://github.com/ChromeDevTools/chrome-devtools-mcp) pour `codex`.

Sur linux pour que le chrome fonctionne avec `codex` il faut ajouter le flag `--remote-debugging-port=9222` lors du lancement de chrome.

```
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/test --no-first-run
```

