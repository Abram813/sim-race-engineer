#!/usr/bin/env python3
"""Print the CI environment so it can be attached to a workflow artifact."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys


def command_version(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable ({exc})"


def main() -> int:
    info = {
        "runner_os": os.environ.get("RUNNER_OS", ""),
        "runner_arch": os.environ.get("RUNNER_ARCH", ""),
        "runner_image": os.environ.get("ImageOS", ""),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "uv": command_version(["uv", "--version"]),
    }
    print("RaceCoach CI environment")
    for key, value in info.items():
        print(f"{key}: {value}")
    print()
    print(json.dumps(info, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
