# OpenAI integration for Hornet

This project can generate a reverse‑engineered PRD and unit test runners using OpenAI.

Setup (local, per-user)
- Create a file at ~/.hornet/.env with:
  OPENAI_API_KEY=<your_openai_key>

- Alternatively, export the environment variable in your shell profile:
  export OPENAI_API_KEY=<your_openai_key>

Security notes
- Do NOT embed API keys into the app bundle or DMG. Anyone with the DMG can extract the key.
- Keys should remain user-local (e.g., ~/.hornet/.env, macOS Keychain) and never be committed to git.

Usage in the Hornet app
- Click “Choose folder” to select your target repo.
- Click “Generate via OpenAI” to:
  1) Snapshot source files (text only, size-limited) from the selected repo.
  2) Send them to OpenAI to produce:
     - requirements.md (reverse‑engineered PRD)
     - *.py unit test runner scripts
  3) Write outputs under ~/.hornet/<repo-name>/ (requirements.md and tests/).
- Then use “Run tests” to execute the generated runners.

Notes
- The generator caps file count and size to stay within model context limits.
- Logging is verbose; check ~/.hornet/<repo-name>/runs for per-script logs and the app’s log pane.
