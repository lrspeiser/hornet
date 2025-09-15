from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Callable, Optional
from .openai_helpers import call_openai

# Chunked pipeline to avoid context-limit errors and to improve quality:
# 1) Summarize each file individually (small prompts) → file_summaries
# 2) Aggregate summaries into a repo-level PRD and test plan (no raw code)
# 3) Generate each test runner in its own small call, based on the plan

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".autotestgen", "dist", "build", "__pycache__"}
BIN_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".tar", ".jar", ".exe", ".dmg", ".app"}
# Broad default set of text/code extensions for initial scans
DEFAULT_EXTS = [
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs",
    ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".txt",
]
MAX_FILE_CHARS = 40_000  # cap per-file content


def _iter_text_files(repo: Path, include_ext: List[str] | None = None, max_files: int | None = None) -> List[Path]:
    files: List[Path] = []
    inc_set = None
    if include_ext:
        inc_set = {e.strip().lower() for e in include_ext if e.strip()}
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_dir():
            continue
        if p.suffix.lower() in BIN_EXTS:
            continue
        if inc_set is not None and p.suffix.lower() not in inc_set:
            continue
        try:
            b = p.read_bytes()
        except Exception:
            continue
        # crude binary check
        if b"\x00" in b:
            continue
        files.append(p)
        if max_files is not None and len(files) >= max_files:
            break
    return files


def _read_capped_text(p: Path, cap: int = MAX_FILE_CHARS) -> str:
    try:
        s = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        s = p.read_text(errors="ignore")
    if len(s) > cap:
        # Take head and tail to capture module docstrings and exports
        head = s[: cap // 2]
        tail = s[-cap // 2 :]
        s = head + "\n\n...\n\n" + tail
    return s


def _file_summary_messages(repo_name: str, rel_path: str, content: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    system = (
        "You are an expert code analyst. Given a single source file, return a compact JSON summary with keys: "
        "file (string), overview (string <= 240 chars), exported (array of {name, kind, signature?, brief}), "
        "internal_calls (array of strings), external_deps (array of import/module/package names), "
        "test_suggestions (array of {function, example_args: array, notes?}). Keep it concise."
    )
    user = f"Repo: {repo_name}\nPath: {rel_path}\n===== FILE CONTENT START =====\n{content}\n===== FILE CONTENT END =====\n"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return messages, {"type": "json_object"}


def _aggregate_messages(repo_name: str, file_summaries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    system = (
        "You are drafting a reverse-engineered PRD and a unit-test plan from file-level summaries. "
        "Input is an array of JSON summaries per file (no raw code). Return JSON with keys: "
        "requirements_md (markdown string), tests_plan (array of {file, function, example_args?, priority: 1-5, notes?}). "
        "Group related functions, describe data flows and cross-file dependencies, and keep the PRD concise but useful."
    )
    user = json.dumps({"repo": repo_name, "files": file_summaries})
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return messages, {"type": "json_object"}


def _runner_messages(repo_name: str, func_item: Dict[str, Any]) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    system = (
        "Generate a standalone Python runner script for a single function. "
        "The script must import from the target repo by inserting HORNET_TARGET_REPO_PATH into sys.path. "
        "It should execute a list of example cases, capture pass/fail and exceptions, and print a JSON summary to stdout. "
        "Do NOT use pytest. Return the script text directly as a JSON string in the 'code' key."
    )
    user = json.dumps({"repo": repo_name, "plan": func_item})
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return messages, {"type": "json_object"}


def _chat_json(messages: List[Dict[str, str]], response_format: Dict[str, Any], debug: bool = False) -> Dict[str, Any]:
    raw = call_openai(messages, response_format=response_format, debug=debug)
    try:
        return json.loads(raw)
    except Exception:
        # Strip code fences if present
        stripped = "\n".join([ln for ln in raw.splitlines() if not ln.strip().startswith("```")])
        return json.loads(stripped)


def generate_with_openai(
    target_repo: Path,
    out_base: Path,
    include_ext: List[str] | None = None,
    max_files: int | None = None,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Chunked generation: summarize files -> aggregate -> generate runners.
    Outputs under out_base:
    - requirements.md
    - tests/*.py
    Returns dict with paths and counts.
    """
    out: Dict[str, Any] = {}
    out_base.mkdir(parents=True, exist_ok=True)

    def _emit(msg: str):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    repo_name = target_repo.name
    _emit(f"[1/3] Scanning files in {target_repo} (filters: {include_ext or 'all'}, max_files={max_files or '∞'})")
    paths = _iter_text_files(target_repo, include_ext=include_ext, max_files=max_files)
    if len(paths) == 0:
        # Fallback to defaults if explicit filters yielded nothing
        if include_ext:
            _emit(f"No files found for filters {include_ext}; falling back to defaults: {DEFAULT_EXTS}")
            paths = _iter_text_files(target_repo, include_ext=DEFAULT_EXTS, max_files=max_files)
        if len(paths) == 0:
            _emit("Still no files with defaults; scanning all text files (excluding known binaries)")
            paths = _iter_text_files(target_repo, include_ext=None, max_files=max_files)
    _emit(f"Found {len(paths)} candidate file(s)")

    # 1) Per-file summaries
    file_summaries: List[Dict[str, Any]] = []
    for idx, p in enumerate(paths, start=1):
        rel = str(p.relative_to(target_repo))
        _emit(f"Summarizing [{idx}/{len(paths)}] {rel}")
        content = _read_capped_text(p)
        messages, rf = _file_summary_messages(repo_name, rel, content)
        try:
            summary = _chat_json(messages, rf, debug=True)
            # keep only compact fields to minimize next step
            compact = {
                "file": summary.get("file", rel),
                "overview": (summary.get("overview") or "")[:500],
                "exported": summary.get("exported", []),
                "internal_calls": summary.get("internal_calls", []),
                "external_deps": summary.get("external_deps", []),
                "test_suggestions": summary.get("test_suggestions", []),
            }
            file_summaries.append(compact)
            _emit(f"✓ Summarized {rel} ({len(compact.get('exported', []))} exported, {len(compact.get('internal_calls', []))} calls)")
        except Exception as e:
            # If a single file fails to summarize, skip but continue
            file_summaries.append({"file": rel, "overview": "(summary failed)"})
            _emit(f"! Summary failed for {rel}: {e}")
    out["file_summaries_count"] = len(file_summaries)

    # 2) Aggregate into PRD + test plan
    _emit("[2/3] Aggregating repo-level PRD and test plan…")
    agg_messages, agg_rf = _aggregate_messages(repo_name, file_summaries)
    aggregate = _chat_json(agg_messages, agg_rf, debug=True)
    prd_text = aggregate.get("requirements_md") or ""
    tests_plan = aggregate.get("tests_plan", [])
    _emit(f"Aggregation complete: PRD={'yes' if prd_text else 'no'}, tests_plan items={len(tests_plan)}")

    if prd_text:
        prd_path = out_base / "requirements.md"
        prd_path.write_text(prd_text, encoding="utf-8")
        out["requirements_md"] = str(prd_path)
        _emit(f"PRD → {prd_path}")
    else:
        _emit("No PRD text returned from aggregation step")

    # 3) Generate runners, one per plan item
    tests_dir = out_base / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)

    written_tests: List[str] = []
    if not tests_plan:
        _emit("No tests suggested by aggregation step — 0 runner(s) generated")
    for i, item in enumerate(tests_plan, start=1):
        label = item.get("function") or item.get("file") or f"item{i}"
        _emit(f"[3/3] Generating runner [{i}/{len(tests_plan)}]: {label}")
        try:
            r_messages, r_rf = _runner_messages(repo_name, item)
            runner_payload = _chat_json(r_messages, r_rf, debug=True)
            code = runner_payload.get("code") or runner_payload.get("script") or ""
            # Filename from function and/or file
            base_name = item.get("function") or Path(item.get("file", "test")).stem
            safe = (base_name or "test").replace("/", "_").replace("..", "_") + "__runner.py"
            fp = tests_dir / safe
            fp.write_text(code, encoding="utf-8")
            written_tests.append(str(fp))
            _emit(f"✓ Runner → {fp}")
        except Exception as e:
            # Skip that one test generator failure
            _emit(f"! Runner generation failed for {label}: {e}")
            continue
    out["tests"] = written_tests

    _emit(f"Done — PRD: {'yes' if out.get('requirements_md') else 'no'}, runners: {len(written_tests)}")
    return out
