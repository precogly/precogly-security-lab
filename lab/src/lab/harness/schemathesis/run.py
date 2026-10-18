"""Run Schemathesis while preserving its exit code and our atexit SARIF report."""

import os
import subprocess

environment = os.environ.copy()
environment["SCHEMATHESIS_HOOKS"] = "/job/hooks.py"
result = subprocess.run(
    [
        "schemathesis",
        "run",
        "http://backend:8000/api/schema/",
    ],
    env=environment,
    cwd="/job",
    check=False,
)
raise SystemExit(result.returncode)
