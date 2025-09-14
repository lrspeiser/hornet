# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

Common commands and workflow
- Python setup
  ```bash path=null start=null
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  ```

- CLI entry (Typer)
  ```bash path=null start=null
  # Initialize state for a target repo (creates .autotestgen/ inside the target)
  python -m app.main init /path/to/target/repo

  # Generate PRD + fixtures + per-function runner scripts for the target repo
  python -m app.main generate /path/to/target/repo

  # Run all generated scripts and record results in SQLite
  python -m app.main run /path/to/target/repo

  # Serve the dashboard (open http://127.0.0.1:8000/?repo=/absolute/path/to/target/repo)
  python -m app.main serve
  ```

- Run a single function’s runner (after generate)
  ```bash path=null start=null
  # Execute a specific generated script directly in the target repo
  python /path/to/target/repo/.autotestgen/tests/<function_name>__runner.py
  ```

- Git (push to main)
  ```bash path=null start=null
  git add -A && git commit -m "<message>" && git push origin main
  ```

- Optional: Git LFS when adding large assets
  ```bash path=null start=null
  git lfs install --local
  git lfs track "<pattern>"
  git add .gitattributes
  git commit -m "Track large assets with Git LFS"
  git push origin main
  ```

Architecture and structure (big picture)
- Purpose
  - This repo provides a scaffold that reverse-engineers a lightweight PRD from source code, plans test data, generates per-function runner scripts, executes them, and surfaces results in a small dashboard.

- End-to-end flow (orchestrated by app/main.py)
  1) Scan: app/core/repo_scanner.py discovers functions in a target repo via pluggable language analyzers and returns DiscoveredFunction items.
  2) PRD: app/core/requirements_extractor.py composes a reverse-engineered requirements.md from discoveries.
  3) Fixtures: app/core/test_data_planner.py writes a fixtures.json with typed placeholders per function.
  4) Test scripts: app/core/test_generator.py emits self-contained per-function runner scripts: .autotestgen/tests/<function>__runner.py
  5) Execution + logging: app/core/runner.py executes each runner, capturing stdout/stderr/status and logging to SQLite.

- State and artifacts (live in the target repo)
  - Root: .autotestgen/
    - autotestgen.db — SQLite database
    - requirements.md — reverse-engineered PRD
    - fixtures.json — test-data plan
    - tests/ — generated per-function runner scripts
    - runs/ — reserved path for run artifacts

- Dashboard (FastAPI + Jinja)
  - app/dashboard/api.py exposes pages:
    - GET / — pick repo and (optionally) a run; lists functions with last status and timing
    - GET /function/{name} — shows parsed stdout and stderr for a specific function
    - POST /api/run — kicks off a synchronous run over generated scripts
  - app/dashboard/db.py and app/dashboard/models.py define SQLite access and two tables:
    - TestRun(id, repo, started_at, finished_at)
    - FunctionRun(test_run_id, function_name, script_path, status, stdout, stderr, duration_ms, created_at)

- Plugin system
  - Contract (app/core/interfaces.py): LanguagePlugin requires discover_functions, derive_requirements, plan_test_data, generate_test_script.
  - Implementations (app/plugins/languages/):
    - PythonPlugin (implemented) — uses ast to discover def signatures and docstrings
    - JavaScriptPlugin (stub) — placeholder for future tree-sitter-based parsing
  - Registration (app/plugins/languages/base.py): all_plugins() returns enabled plugin instances. Add new languages by implementing the interface and returning the instance here.

- Configuration helpers (app/config.py)
  - repo_state_dir(), db_path(), tests_dir(), runs_dir(), prd_path(), fixtures_path() centralize paths under .autotestgen/ within the target repo.

Notes
- Minimal runtime dependencies are listed in requirements.txt and include: fastapi, uvicorn[standard], SQLAlchemy>=2.0, Jinja2, typer[all], tree_sitter, rich.
- The per-function runner prints a JSON summary; the aggregator considers a function "pass" only if all its cases pass.
