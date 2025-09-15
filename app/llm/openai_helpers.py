from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

# NOTE: See OPENAI.md for how to set up your API key securely.
# We intentionally DO NOT embed secrets in the app or DMG. Keys are read from ~/.hornet/.env or environment.

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

# Minimal app-log helper (mirrors GUI behavior) — logs to ~/.hornet/logs/hornet.log
def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _append_app_log(line: str) -> None:
    try:
        log_path = Path.home() / ".hornet/logs/hornet.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{_ts()}] {line}\n")
    except Exception:
        pass


def load_api_key() -> str | None:
    """
    Load OpenAI API key from environment or from ~/.hornet/.env.
    Order:
    1) OPENAI_API_KEY in environment
    2) ~/.hornet/.env with OPENAI_API_KEY
    """
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    env_path = Path.home() / ".hornet/.env"
    if env_path.exists():
        load_dotenv(env_path)
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return key
    return None


def default_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def is_binary_bytes(b: bytes) -> bool:
    # Heuristic: presence of NUL byte
    return b"\x00" in b


def read_repo_files(repo: Path, max_files: int = 200, max_total_bytes: int = 800_000) -> List[Tuple[str, str]]:
    """
    Return a list of (relative_path, text_content) for text-like files, capped by counts/size.
    Skips hidden, .git, node_modules, venvs, and common binary extensions.
    """
    SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".autotestgen", "dist", "build", "__pycache__"}
    BIN_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".tar", ".jar", ".exe", ".dmg", ".app"}

    total = 0
    out: List[Tuple[str, str]] = []
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if any(part.startswith(".") and str(part) not in {".", ".."} for part in rel.parts):
            # allow dotfile in root? Keep consistent: skip any hidden path part except root
            pass
        # skip selected dirs
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_dir():
            continue
        if p.suffix.lower() in BIN_EXTS:
            continue
        try:
            b = p.read_bytes()
        except Exception:
            continue
        if is_binary_bytes(b):
            continue
        try:
            s = b.decode("utf-8")
        except UnicodeDecodeError:
            try:
                s = b.decode("latin1")
            except Exception:
                continue
        new_total = total + len(s.encode("utf-8"))
        if new_total > max_total_bytes:
            break
        out.append((str(rel), s))
        total = new_total
        if len(out) >= max_files:
            break
    return out


# Legacy bulk prompt builder (no longer used by default); keeping for reference.
# Large repos can exceed model context limits; see app/llm/generate.py for chunked pipeline.
def build_prompt(files: List[Tuple[str, str]], repo_name: str) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    system = (
        "You are an expert software engineer and test architect. "
        "Given a snapshot of a repository, produce: (1) a PRD and (2) test runners. "
        "Return JSON with requirements_md and tests."
    )
    header = f"Repository: {repo_name} — files: {len(files)}\n"
    body_parts = []
    for rel, content in files:
        body_parts.append(f"===== FILE: {rel} =====\n{content}\n")
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": header + "\n".join(body_parts)},
    ]
    return messages, {"type": "json_object"}


def call_openai(messages: List[Dict[str, str]], model: str | None = None, response_format: Dict[str, Any] | None = None, debug: bool = False) -> str:
    if OpenAI is None:
        raise RuntimeError("openai package not available. Did you install 'openai'? See OPENAI.md.")
    key = load_api_key()
    if not key:
        raise RuntimeError("OPENAI_API_KEY not found. Set it in ~/.hornet/.env or environment. See OPENAI.md.")
    client = OpenAI(api_key=key)
    model = model or default_model()
    kwargs: Dict[str, Any] = dict(model=model, messages=messages, temperature=0.2)
    if response_format:
        # Not all models support response_format; try, then fall back
        kwargs["response_format"] = response_format

    if debug:
        try:
            total_chars = sum(len(m.get("content", "")) for m in messages)
            _append_app_log(f"LLM request: model={model}, messages={len(messages)}, total_chars={total_chars}, response_format={'yes' if response_format else 'no'}")
        except Exception:
            pass

    try:
        resp = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
        content = resp.choices[0].message.content or ""
        if debug:
            _append_app_log(f"LLM response: chars={len(content)}")
        return content
    except Exception as e:
        if debug:
            _append_app_log(f"LLM error on first attempt: {e}")
        # Retry without response_format
        kwargs.pop("response_format", None)
        resp = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
        content = resp.choices[0].message.content or ""
        if debug:
            _append_app_log(f"LLM response (no response_format): chars={len(content)}")
        return content
