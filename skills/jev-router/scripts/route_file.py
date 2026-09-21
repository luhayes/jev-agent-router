"""Send a private request file to the existing CLI; no routing logic here."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_file", type=Path)
    parser.add_argument("--cli", default="jev-route", help="Trusted executable path, not shell source")
    parser.add_argument("--test-only-offline", action="store_true")
    args = parser.parse_args()
    try:
        with args.request_file.open("rb") as handle:
            raw = handle.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized request")
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError("expected object")
        command = [args.cli]
        if args.test_only_offline:
            command.append("--test-only-offline")
        result = subprocess.run(
            command,
            input=json.dumps(request, allow_nan=False),
            text=True,
            capture_output=True,
            timeout=50,
            shell=False,
        )
        if result.returncode:
            raise ValueError("child failure")
        payload = json.loads(result.stdout)
        if (
            not isinstance(payload, dict)
            or payload.get("error")
            or payload.get("test_only") is not args.test_only_offline
        ):
            raise ValueError("invalid result")
        decision = payload.get("decision")
        if not isinstance(decision, dict) or decision.get("label") not in request.get("criteria", {}):
            raise ValueError("invalid label")
        print(json.dumps(payload, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"error": "skill_runner_failed_check_input_or_configuration"}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "cancelled"}))
        return 130


if __name__ == "__main__":
    sys.exit(main())
