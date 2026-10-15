"""Start the complete Entrix AI local demo from one terminal.

Usage:
    python run.py
    python run.py --install

The launcher starts FastAPI on http://127.0.0.1:8000 and Vite on
http://127.0.0.1:5173. Press Ctrl+C once to stop both processes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def run_install() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".[dev]"],
        cwd=BACKEND,
        check=True,
    )
    subprocess.run(["npm.cmd", "install"], cwd=FRONTEND, check=True)


def stop_process(process: subprocess.Popen[object]) -> None:
    """Stop a launcher-owned process and, on Windows, its child process tree."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install Python and Node dependencies first",
    )
    parser.add_argument(
        "--no-seed", action="store_true", help="Do not seed an empty local database"
    )
    args = parser.parse_args()

    if not command_exists("npm.cmd"):
        raise SystemExit(
            "Node.js/npm is required. Install Node.js 20+ and rerun this command."
        )

    if args.install:
        run_install()

    environment = os.environ.copy()
    environment["PYTHONPATH"] = (
        str(BACKEND) + os.pathsep + environment.get("PYTHONPATH", "")
    )

    if not args.no_seed:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--if-empty"],
            cwd=ROOT,
            env=environment,
            check=True,
        )

    if not (FRONTEND / "node_modules").exists():
        raise SystemExit(
            "Frontend dependencies are missing. Run: python run.py --install"
        )

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--port",
                "8000",
            ],
            cwd=BACKEND,
            env=environment,
        ),
        subprocess.Popen(
            ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1"], cwd=FRONTEND
        ),
    ]
    print(
        "\nEntrix AI is starting. Open http://127.0.0.1:5173 (Ctrl+C stops both services).\n",
        flush=True,
    )

    try:
        exit_code = processes[0].wait()
        if exit_code:
            raise SystemExit(exit_code)
    except KeyboardInterrupt:
        print("\nStopping Entrix AI services...")
    finally:
        for process in processes:
            stop_process(process)
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
