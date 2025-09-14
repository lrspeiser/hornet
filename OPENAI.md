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
- Click “Generate via OpenAI”:
  - The app now summarizes each file individually to avoid context limits, aggregates a repo-level PRD and test plan, then generates each test runner with small, separate calls.
  - Outputs:
    - requirements.md (reverse‑engineered PRD)
    - tests/*.py (independent runner scripts)
  - Outputs are written under ~/.hornet/<repo-name>/.
- Then use “Run tests” to execute the generated runners.

Notes
- The generator caps file count and size to stay within model context limits.
- Logging is verbose; check ~/.hornet/<repo-name>/runs for per-script logs and the app’s log pane.
