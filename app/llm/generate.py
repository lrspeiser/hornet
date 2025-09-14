from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any
from .openai_helpers import read_repo_files, build_prompt, call_openai


def generate_with_openai(target_repo: Path, out_base: Path) -> Dict[str, Any]:
    """
    Snapshot the repo, call OpenAI, and write outputs under out_base.
    Returns a dict with paths to written files.

    Outputs:
    - out_base/requirements.md
    - out_base/tests/*.py
    """
    files = read_repo_files(target_repo)
    messages, response_format = build_prompt(files, target_repo.name)
    content = call_openai(messages, response_format=response_format)
    try:
        payload = json.loads(content)
    except Exception:
        # Some models may wrap JSON in code fences; attempt to strip
        content_stripped = content
        if content_stripped.strip().startswith("```"):
            content_stripped = "\n".join(
                line for line in content_stripped.splitlines()
                if not line.strip().startswith("```")
            )
        payload = json.loads(content_stripped)

    written: Dict[str, Any] = {}
    out_base.mkdir(parents=True, exist_ok=True)

    # Write PRD
    req_md = payload.get("requirements_md") or payload.get("requirements") or ""
    if req_md:
        prd_path = out_base / "requirements.md"
        prd_path.write_text(req_md, encoding="utf-8")
        written["requirements_md"] = str(prd_path)

    # Write tests
    tests = payload.get("tests", {})
    tests_dir = out_base / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_paths = []
    for name, src in tests.items():
        # Ensure .py extension and basic safety
        name = name if name.endswith(".py") else f"{name}.py"
        safe = name.replace("..", "_").replace("/", "_")
        fp = tests_dir / safe
        fp.write_text(src, encoding="utf-8")
        test_paths.append(str(fp))
    written["tests"] = test_paths

    return written
