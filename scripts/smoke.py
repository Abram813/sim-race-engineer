#!/usr/bin/env python3
"""End-to-end smoke test for RaceCoach.

This is deliberately dependency-free.  It starts the real app in a subprocess,
checks the demo, uploads the demo CSVs through the same API the browser uses,
changes the selected braking section, and sends Ctrl+C / Ctrl+Break to verify a
clean shutdown.  It also prints the OS, CPU architecture, Python and uv
versions for the handover report.

Run from anywhere:

    uv run python scripts/smoke.py
"""

from __future__ import annotations

import json
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> dict:
    with OPENER.open(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str) -> str:
    with OPENER.open(url, timeout=10) as response:
        return response.read().decode("utf-8")


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(base_url: str, timeout_s: float = 15.0) -> dict:
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return get_json(base_url + "api/health")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"RaceCoach did not become healthy: {last_error}")


def stop_process(proc: subprocess.Popen) -> int:
    if proc.poll() is not None:
        return int(proc.returncode or 0)
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)
    try:
        return int(proc.wait(timeout=15))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError("RaceCoach did not shut down after Ctrl+C / Ctrl+Break.")


def uv_version() -> str:
    try:
        return subprocess.check_output(["uv", "--version"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "uv not found on PATH"


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}/"
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
    output = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "racecoach",
            "serve",
            "--no-browser",
            "--port",
            str(port),
            "--offline",
        ],
        cwd=str(ROOT),
        stdout=output,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    try:
        health = wait_for_health(base_url)
        assert health["status"] == "ok", health
        assert health["offline"] is True, health

        html = get_text(base_url)
        assert "RaceCoach" in html, "The UI HTML did not load."
        assert "Loading demo" in html, "The demo placeholder is missing."

        demo = get_json(base_url + "api/demo")
        analysis = demo["analysis"]
        assert demo["demo"] is True
        assert analysis["summary"]["completed_zones"] == 4, analysis["summary"]
        assert analysis["summary"]["skipped_zones"] == 1, analysis["summary"]
        assert len(analysis["zones"]) == 5
        assert "12 metres earlier" in analysis["zones"][0]["message"]
        assert analysis["zones"][0]["message"] != analysis["zones"][1]["message"]

        reference_csv = get_text(base_url + "api/demo/reference.csv")
        practice_csv = get_text(base_url + "api/demo/practice.csv")
        uploaded = post_json(
            base_url + "api/analyze",
            {
                "reference": {"name": "reference lap.csv", "csv": reference_csv},
                "practice": {"name": "practice lap.csv", "csv": practice_csv},
                "max_gap_m": 25,
            },
        )
        uploaded_analysis = uploaded["analysis"]
        assert uploaded["demo"] is False
        assert uploaded_analysis["summary"]["completed_zones"] == 4
        assert "grid" in uploaded_analysis
        assert len(uploaded_analysis["grid"]["distance_m"]) > 100
        first_message = uploaded_analysis["zones"][0]["message"]
        second_message = uploaded_analysis["zones"][1]["message"]
        assert first_message != second_message, "Changing the selected section did not change the measurement."
        assert "12 metres earlier" in first_message

        returncode = stop_process(proc)
        assert returncode == 0, f"RaceCoach exited with code {returncode}."
        output.seek(0)
        log = output.read()
        assert "Stopped cleanly." in log, log
    except Exception:
        output.seek(0)
        print("---- RaceCoach output ----")
        print(output.read())
        print("--------------------------")
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        raise
    finally:
        output.close()

    print("Environment")
    print(f"  OS:      {platform.platform()}")
    print(f"  Machine: {platform.machine()}")
    print(f"  Python:  {platform.python_version()}")
    print(f"  uv:      {uv_version()}")
    print("SMOKE PASS: app started, demo loaded, section measurement changed, upload analysed, clean shutdown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
