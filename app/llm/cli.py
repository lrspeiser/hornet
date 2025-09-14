from __future__ import annotations
import argparse
from pathlib import Path
from typing import Optional
from .generate import generate_with_openai


def slugify(name: str) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    return s.strip("-_") or "repo"


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Hornet LLM generation CLI")
    p.add_argument("generate", help="subcommand", nargs="?")
    p.add_argument("--repo", required=False, help="Path to target repository")
    p.add_argument("--out", required=False, help="Output base directory (defaults to ~/.hornet/<repo-name>)")
    args = p.parse_args(argv)

    if args.generate != "generate":
        p.print_help()
        return 2

    if not args.repo:
        print("--repo is required")
        return 2

    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        print(f"Repo not found: {repo}")
        return 2

    if args.out:
        out_base = Path(args.out).expanduser().resolve()
    else:
        out_base = Path.home() / ".hornet" / slugify(repo.name)

    out = generate_with_openai(repo, out_base)
    print("== Hornet LLM generation complete ==")
    if out.get("requirements_md"):
        print(f"PRD: {out['requirements_md']}")
    print(f"Tests generated: {len(out.get('tests', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())