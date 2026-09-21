"""Repository skill contract and real CLI smoke, without provider traffic."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/jev-router"


def test_skill_contract():
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: jev-router\n")
    for reference in ["examples", "safety", "integrations"]:
        assert f"references/{reference}.md" in text
        assert (SKILL / f"references/{reference}.md").is_file()
    for token in ["test_only", "origin", "confidence", "reason", "Do not retry"]:
        assert token in text
    assert "/Users/" not in text


def test_skill_runner_offline(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "state": "invoice",
                "criteria": {"billing": "Payments", "review": "Manual review"},
                "instructions": "Choose a route",
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/route_file.py"),
            str(request),
            "--cli",
            str(Path(sys.executable).parent / "jev-route"),
            "--test-only-offline",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["test_only"] is True
    assert output["decision"]["label"] == "billing"


def test_skill_runner_invalid_file(tmp_path):
    request = tmp_path / "bad.json"
    request.write_text("PRIVATE_DATA_not_json")
    result = subprocess.run(
        [sys.executable, str(SKILL / "scripts/route_file.py"), str(request)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "PRIVATE_DATA" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["error"]
