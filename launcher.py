"""3W+ Windows launcher — starts the Docker Compose stack and opens the browser.

Pack into a standalone .exe with:
    pip install pyinstaller
    pyinstaller --onefile --noconsole --name "3W+" launcher.py

Double-clicking the resulting dist/3W+.exe will:
  1. Verify Docker Desktop is running
  2. Start all services via docker compose
  3. Wait until the backend is healthy
  4. Open http://localhost:5000 in the default browser
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

# ── Locate repo root ──────────────────────────────────────────────────────────
# When running as a PyInstaller .exe the executable lives in <repo>/dist/.
# One level up is the repo root. When running as a plain Python script the
# script lives at the repo root itself.
if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).parent.parent.resolve()
else:
    _ROOT = Path(__file__).parent.resolve()

_COMPOSE_FILE = _ROOT / "infra" / "docker-compose.yml"
_ENV_FILE     = _ROOT / "backend" / ".env"
_ENV_EXAMPLE  = _ROOT / "backend" / ".env.example"
_HEALTH_URL   = "http://localhost:5000/health"
_APP_URL      = "http://localhost:5000"
_POLL_SECS    = 3
_MAX_WAIT     = 120  # seconds


def _docker_running() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _compose(*args: str) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(_COMPOSE_FILE)]
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(_HEALTH_URL, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _ensure_env() -> bool:
    """Copy .env.example to .env if it doesn't exist. Returns False if user cancels."""
    if _ENV_FILE.exists():
        return True
    if not _ENV_EXAMPLE.exists():
        messagebox.showerror(
            "3W+ Launcher",
            f"Configuration file not found:\n{_ENV_EXAMPLE}\n\n"
            "Please clone the full repository.",
        )
        return False
    shutil.copy(_ENV_EXAMPLE, _ENV_FILE)
    messagebox.showinfo(
        "3W+ Launcher",
        f"A default configuration file has been created at:\n{_ENV_FILE}\n\n"
        "Edit it to set POSTGRES_PASSWORD, JWT_SECRET, and (optionally) "
        "ANTHROPIC_API_KEY, then click OK to continue.",
    )
    return True


class LauncherWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("3W+ Launcher")
        self.geometry("440x200")
        self.resizable(False, False)
        self.configure(bg="#001E62")

        tk.Label(
            self, text="3W+ Platform", font=("Segoe UI", 18, "bold"),
            fg="#FFD100", bg="#001E62",
        ).pack(pady=(24, 4))

        self._status = tk.StringVar(value="Initialising…")
        tk.Label(
            self, textvariable=self._status, font=("Segoe UI", 10),
            fg="white", bg="#001E62", wraplength=400,
        ).pack(pady=4)

        self._bar = ttk.Progressbar(self, mode="indeterminate", length=360)
        self._bar.pack(pady=12)
        self._bar.start(12)

        tk.Label(
            self, text="© CelcomDigi — Internal Use Only",
            font=("Segoe UI", 8), fg="#7fa0d0", bg="#001E62",
        ).pack(side="bottom", pady=8)

        self.after(100, self._run)

    def _status_set(self, msg: str):
        self._status.set(msg)
        self.update()

    def _fail(self, msg: str):
        self._bar.stop()
        self._status.set(msg)
        messagebox.showerror("3W+ Launcher", msg)
        self.destroy()

    def _run(self):
        # 1 — Docker
        self._status_set("Checking Docker Desktop…")
        if not _docker_running():
            self._fail(
                "Docker Desktop is not running.\n\n"
                "Please start Docker Desktop and try again."
            )
            return

        # 2 — .env
        self._status_set("Checking configuration…")
        if not _ensure_env():
            self.destroy()
            return

        # 3 — Start services
        self._status_set("Starting 3W+ services…")
        result = _compose("up", "-d", "--remove-orphans")
        if result.returncode != 0:
            self._fail(
                "docker compose up failed:\n\n" + (result.stderr or result.stdout)[:600]
            )
            return

        # 4 — Wait for health
        self._status_set("Waiting for backend to become ready…")
        deadline = time.time() + _MAX_WAIT
        while time.time() < deadline:
            if _healthy():
                break
            time.sleep(_POLL_SECS)
            self.update()
        else:
            self._fail(
                f"Backend did not become healthy within {_MAX_WAIT} s.\n\n"
                "Check Docker logs:\n  docker compose -f infra/docker-compose.yml logs -f"
            )
            return

        # 5 — Open browser
        self._bar.stop()
        self._status_set("Opening browser…")
        webbrowser.open(_APP_URL)
        self.after(1200, self.destroy)


def main():
    app = LauncherWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
