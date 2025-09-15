#!/usr/bin/env python3
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import sys, os, io, traceback, time, runpy, re, json, contextlib

APP_NAME = "Hornet"
STORE_ROOT = Path.home() / ".hornet"

# ---- Project index helpers (stored alongside tests) ----

def _meta_path(base: Path) -> Path:
    return base / "meta.json"


def _read_meta(base: Path) -> dict:
    mp = _meta_path(base)
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_meta(base: Path, meta: dict) -> None:
    try:
        _meta_path(base).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        pass


def _list_projects() -> list[dict]:
    projects: list[dict] = []
    if not STORE_ROOT.exists():
        return projects
    for base in sorted([p for p in STORE_ROOT.iterdir() if p.is_dir()]):
        meta = _read_meta(base)
        tests = base / "tests"
        projects.append({
            "slug": base.name,
            "base": base,
            "tests": tests,
            "repo_path": meta.get("repo_path"),
            "updated_at": meta.get("updated_at"),
            "last_run": meta.get("last_run"),
            "tests_count": meta.get("tests_count"),
            "prd_path": meta.get("prd_path"),
        })
    return projects


def slugify(name: str) -> str:
    # Safe folder name for filesystem
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    return s.strip("-_") or "repo"


def ensure_store(selected_dir: Path) -> dict:
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    repo_name = slugify(selected_dir.name)
    base = STORE_ROOT / repo_name
    tests = base / "tests"
    runs = base / "runs"
    base.mkdir(exist_ok=True)
    tests.mkdir(exist_ok=True)
    runs.mkdir(exist_ok=True)

    # Seed example files once
    example = tests / "example_runner.py"
    readme = tests / "README.txt"
    if not example.exists():
        example.write_text(
            """
import os, sys, json
from pathlib import Path

target = os.environ.get("HORNET_TARGET_REPO_PATH", "")
if target and target not in sys.path:
    sys.path.insert(0, target)

# TODO: import your target code here and call functions to test.
# For now, we just print a JSON message.
print(json.dumps({
    "runner": "example_runner",
    "target_repo": target,
    "message": "Customize this runner to import functions from your repo and assert results.",
    "ok": True
}))
""".lstrip(),
            encoding="utf-8",
        )
    if not readme.exists():
        readme.write_text(
            f"""
This folder stores your Hornet-managed unit test runners for: {selected_dir}

- Write Python scripts that execute functions from your target repo.
- Hornet sets HORNET_TARGET_REPO_PATH so you can import from the target without installation:

    import os, sys
    sys.path.insert(0, os.environ.get("HORNET_TARGET_REPO_PATH", ""))

- Print results (JSON or text). Exceptions will be captured as failures.
- Click "Run tests" in the app to execute all *.py files in this folder (except those starting with _).
""".lstrip(),
            encoding="utf-8",
        )

    # Update meta
    meta = _read_meta(base)
    now = int(time.time())
    if "created_at" not in meta:
        meta["created_at"] = now
    meta["repo_path"] = str(selected_dir)
    meta["slug"] = base.name
    _write_meta(base, meta)

    return {"base": base, "tests": tests, "runs": runs}


class HornetApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True)
        self.selected_dir: Path | None = None
        self.store_paths: dict | None = None
        self._build_ui()

    def _build_ui(self):
        self.master.title(f"{APP_NAME} Test Runner")
        self.master.geometry("820x560")

        # Top controls
        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=12)

        self.path_var = tk.StringVar(value="No folder selected")
        ttk.Label(top, textvariable=self.path_var).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Choose folder", command=self.choose_folder).pack(side="left")
        ttk.Button(top, text="Open tests folder", command=self.open_tests_folder).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Run tests", command=self.run_tests).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Set API Key", command=self.set_api_key).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Generate via OpenAI", command=self.generate_via_openai).pack(side="left", padx=(8, 0))

        # Info line
        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var).pack(fill="x", padx=12)

        # Projects list
        proj_frame = ttk.LabelFrame(self, text="Projects")
        proj_frame.pack(fill="x", padx=12, pady=(8, 0))
        proj_top = ttk.Frame(proj_frame)
        proj_top.pack(fill="x", padx=8, pady=8)
        ttk.Button(proj_top, text="Refresh", command=self.refresh_projects).pack(side="left")
        ttk.Button(proj_top, text="Load", command=self.load_selected_project).pack(side="left", padx=(8,0))
        ttk.Button(proj_top, text="Run", command=self.run_selected_project_tests).pack(side="left", padx=(8,0))
        ttk.Button(proj_top, text="Open tests", command=self.open_selected_project_tests).pack(side="left", padx=(8,0))
        ttk.Button(proj_top, text="Update via OpenAI", command=self.update_selected_project).pack(side="left", padx=(8,0))
        self.projects_list = tk.Listbox(proj_frame, height=6)
        self.projects_list.pack(fill="x", padx=8, pady=(0,8))
        self._projects_cache: list[dict] = []
        self.refresh_projects()

        # Log output
        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=12, pady=12)
        self.log_text = tk.Text(log_frame, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        # Bottom bar
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bottom, text="Clear log", command=self.clear_log).pack(side="left")
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right")

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.master.update_idletasks()

    def clear_log(self):
        self.log_text.delete("1.0", "end")

    def choose_folder(self):
        path = filedialog.askdirectory(title="Select a target repository folder")
        if not path:
            return
        self.selected_dir = Path(path)
        self.path_var.set(str(self.selected_dir))
        self.store_paths = ensure_store(self.selected_dir)
        self.info_var.set(f"Tests: {self.store_paths['tests']} | Runs: {self.store_paths['runs']}")
        self.log(f"Selected target: {self.selected_dir}")
        self.log(f"Test storage: {self.store_paths['tests']}")

    def open_tests_folder(self):
        if not self.store_paths:
            messagebox.showinfo(APP_NAME, "Select a folder first.")
            return
        tests = self.store_paths["tests"]
        try:
            if sys.platform == "darwin":
                os.system(f"open '{tests}'")
            elif os.name == "nt":
                os.startfile(str(tests))  # type: ignore[attr-defined]
            else:
                os.system(f"xdg-open '{tests}'")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to open folder: {e}")

    # ---- Projects panel helpers ----
    def refresh_projects(self):
        self._projects_cache = _list_projects()
        self.projects_list.delete(0, "end")
        for proj in self._projects_cache:
            label = f"{proj['slug']}"
            if proj.get("repo_path"):
                label += f" — {proj['repo_path']}"
            else:
                label += " — (repo not linked)"
            self.projects_list.insert("end", label)

    def _selected_project(self) -> dict | None:
        sel = self.projects_list.curselection()
        if not sel:
            return None
        idx = sel[0]
        if 0 <= idx < len(self._projects_cache):
            return self._projects_cache[idx]
        return None

    def load_selected_project(self):
        proj = self._selected_project()
        if not proj:
            messagebox.showinfo(APP_NAME, "Select a project in the list.")
            return
        base = proj["base"]
        meta = _read_meta(base)
        self.store_paths = {"base": base, "tests": base / "tests", "runs": base / "runs"}
        repo_path = meta.get("repo_path")
        if repo_path:
            self.selected_dir = Path(repo_path)
            self.path_var.set(repo_path)
        else:
            self.selected_dir = None
            self.path_var.set(f"Project: {proj['slug']} (no linked repo)")
        self.info_var.set(f"Tests: {self.store_paths['tests']} | Runs: {self.store_paths['runs']}")
        self.log(f"Loaded project {proj['slug']}")

    def open_selected_project_tests(self):
        proj = self._selected_project()
        if not proj:
            messagebox.showinfo(APP_NAME, "Select a project in the list.")
            return
        tests = proj["tests"]
        try:
            if sys.platform == "darwin":
                os.system(f"open '{tests}'")
            elif os.name == "nt":
                os.startfile(str(tests))  # type: ignore[attr-defined]
            else:
                os.system(f"xdg-open '{tests}'")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Failed to open folder: {e}")

    def run_selected_project_tests(self):
        proj = self._selected_project()
        if not proj:
            messagebox.showinfo(APP_NAME, "Select a project in the list.")
            return
        base = proj["base"]
        meta = _read_meta(base)
        repo_path = meta.get("repo_path")
        if repo_path:
            self.selected_dir = Path(repo_path)
            self.store_paths = {"base": base, "tests": base / "tests", "runs": base / "runs"}
            self.path_var.set(repo_path)
            self.run_tests()
        else:
            messagebox.showinfo(APP_NAME, "No linked repository path found for this project. Click 'Load' then 'Choose folder' to link it.")

    def update_selected_project(self):
        proj = self._selected_project()
        if not proj:
            messagebox.showinfo(APP_NAME, "Select a project in the list.")
            return
        base = proj["base"]
        meta = _read_meta(base)
        repo_path = meta.get("repo_path")
        if not repo_path:
            messagebox.showinfo(APP_NAME, "No linked repository path. Click 'Load' then 'Choose folder' to link it, or select a folder and re-run generate.")
            return
        # Use existing generate flow but force base and selected_dir
        try:
            self.selected_dir = Path(repo_path)
            self.store_paths = {"base": base, "tests": base / "tests", "runs": base / "runs"}
            def _progress(msg: str):
                self.log(msg)
            from app.llm.generate import generate_with_openai
            default_exts = [".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".txt"]
            written = generate_with_openai(self.selected_dir, base, include_ext=default_exts, max_files=600, progress=_progress)
            # Update meta on success
            meta.update({
                "updated_at": int(time.time()),
                "tests_count": len(written.get("tests", [])),
                "prd_path": written.get("requirements_md"),
            })
            _write_meta(base, meta)
            self.info_var.set(f"Tests: {self.store_paths['tests']} | Runs: {self.store_paths['runs']}")
            self.log(f"Update complete. Generated {len(written.get('tests', []))} runner(s)")
        except Exception as e:
            tb = traceback.format_exc()
            self.log(f"Update via OpenAI failed: {e}\n{tb}")
            messagebox.showerror(APP_NAME, f"Update failed: {e}\nSee log pane for details.")

    def _discover_test_scripts(self) -> list[Path]:
        if not self.store_paths:
            return []
        tests_dir = self.store_paths["tests"]
        candidates = []
        for p in sorted(tests_dir.glob("*.py")):
            if p.name.startswith("_"):
                continue
            candidates.append(p)
        return candidates

    def set_api_key(self):
        # Prompt in a simple dialog for API key; store in ~/.hornet/.env per OPENAI.md
        dialog = tk.Toplevel(self.master)
        dialog.title("Set OpenAI API Key")
        dialog.geometry("520x160")
        ttk.Label(dialog, text="OPENAI_API_KEY (will be written to ~/.hornet/.env)").pack(pady=(12,4))
        entry = ttk.Entry(dialog, width=60, show="*")
        entry.pack(padx=12)
        status = tk.StringVar(value="")
        ttk.Label(dialog, textvariable=status).pack(pady=4)
        def save_key():
            key = entry.get().strip()
            if not key:
                status.set("Enter a key.")
                return
            envp = Path.home() / ".hornet/.env"
            envp.parent.mkdir(parents=True, exist_ok=True)
            # Append or replace OPENAI_API_KEY line
            content = ""
            if envp.exists():
                content = envp.read_text(encoding="utf-8")
                lines = [ln for ln in content.splitlines() if not ln.startswith("OPENAI_API_KEY=")]
                content = "\n".join(lines)
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"OPENAI_API_KEY={key}\n"
            envp.write_text(content, encoding="utf-8")
            status.set(f"Saved to {envp}")
        ttk.Button(dialog, text="Save", command=save_key).pack(pady=(6,12))

    def generate_via_openai(self):
        if not self.selected_dir:
            messagebox.showinfo(APP_NAME, "Select a folder first.")
            return
        try:
            from app.llm.generate import generate_with_openai
        except Exception as e:
            messagebox.showerror(APP_NAME, f"OpenAI modules not available: {e}. See OPENAI.md")
            return
        base = ensure_store(self.selected_dir)["base"]
        self.log("Calling OpenAI to generate PRD and tests… (see OPENAI.md)")
        try:
            def _progress(msg: str):
                self.log(msg)
            # Start with a broad set; the generator has its own fallbacks too.
            default_exts = [".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".sh", ".yaml", ".yml", ".toml", ".json", ".md", ".txt"]
            written = generate_with_openai(self.selected_dir, base, include_ext=default_exts, max_files=600, progress=_progress)
            prd = written.get("requirements_md")
            tests = written.get("tests", [])
            if prd:
                self.log(f"PRD → {prd}")
            self.log(f"Generated {len(tests)} test runner(s)")
            self.info_var.set(f"Tests: {base / 'tests'} | Runs: {base / 'runs'}")
        except Exception as e:
            tb = traceback.format_exc()
            self.log(f"OpenAI generation failed: {e}\n{tb}")
            messagebox.showerror(APP_NAME, f"Generation failed: {e}\nSee log pane for details.")

    def run_tests(self):
        if not self.store_paths:
            messagebox.showinfo(APP_NAME, "Select a folder or load a project first.")
            return
        if not self.selected_dir:
            # Try to infer from meta
            base = self.store_paths["base"]
            meta = _read_meta(base)
            rp = meta.get("repo_path")
            if rp:
                self.selected_dir = Path(rp)
                self.path_var.set(rp)
            else:
                messagebox.showinfo(APP_NAME, "No linked repository path. Use 'Choose folder' or 'Load' a project with a linked repo.")
                return
        scripts = self._discover_test_scripts()
        if not scripts:
            messagebox.showinfo(APP_NAME, "No test scripts found in tests folder. Add *.py files and try again.")
            return

        target_repo = str(self.selected_dir)
        tests_dir = self.store_paths["tests"]
        runs_dir = self.store_paths["runs"]
        ts_label = time.strftime("%Y%m%d-%H%M%S")
        summary = []
        self.clear_log()
        self.log(f"Running {len(scripts)} script(s) against: {target_repo}")

        # Ensure target repo path available to children
        prev_env = os.environ.get("HORNET_TARGET_REPO_PATH")
        os.environ["HORNET_TARGET_REPO_PATH"] = target_repo
        try:
            for script in scripts:
                self.log(f"▶ {script.name}")
                buf_out, buf_err = io.StringIO(), io.StringIO()
                t0 = time.time()
                status = "pass"
                try:
                    # Provide __name__ == "__main__" and expose HORNET_TARGET_REPO_PATH
                    g = {"__name__": "__main__"}
                    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                        runpy.run_path(str(script), init_globals=g)
                except SystemExit as e:
                    status = "fail" if int(getattr(e, "code", 1) or 1) != 0 else "pass"
                except Exception:
                    status = "fail"
                    traceback.print_exc(file=buf_err)
                dt_ms = int((time.time() - t0) * 1000)
                out_s = buf_out.getvalue().strip()
                err_s = buf_err.getvalue().strip()
                log_path = runs_dir / f"{ts_label}__{script.stem}.log"
                log_path.write_text(
                    json.dumps({
                        "script": script.name,
                        "target_repo": target_repo,
                        "status": status,
                        "duration_ms": dt_ms,
                        "stdout": out_s,
                        "stderr": err_s,
                    }, indent=2),
                    encoding="utf-8",
                )
                self.log(f"   status={status} duration={dt_ms}ms -> {log_path.name}")
                if out_s:
                    self.log(f"   stdout: {out_s[:500] + ('…' if len(out_s)>500 else '')}")
                if err_s:
                    self.log(f"   stderr: {err_s[:500] + ('…' if len(err_s)>500 else '')}")
                summary.append((script.name, status, dt_ms))
        finally:
            if prev_env is None:
                os.environ.pop("HORNET_TARGET_REPO_PATH", None)
            else:
                os.environ["HORNET_TARGET_REPO_PATH"] = prev_env

        passed = sum(1 for _, s, _ in summary if s == "pass")
        failed = sum(1 for _, s, _ in summary if s == "fail")
        self.status_var.set(f"Done — pass: {passed}, fail: {failed}")
        self.log(f"Finished. pass={passed} fail={failed}")

        # Update meta last_run
        try:
            base = self.store_paths["base"]
            meta = _read_meta(base)
            meta["last_run"] = int(time.time())
            _write_meta(base, meta)
        except Exception:
            pass


def main():
    root = tk.Tk()
    # Try to use a decent default ttk theme
    try:
        style = ttk.Style()
        if sys.platform == "darwin":
            style.theme_use("aqua")
    except Exception:
        pass
    HornetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
