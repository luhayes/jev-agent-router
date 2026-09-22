"""Validate user-owned, pre-split labeled data without network or telemetry."""

from pathlib import Path

from jev_agent_router import RouteRequest
from .data import digest, read_json, write_json


def import_dataset(source, output):
    """Keep explicit user splits; reject common leakage and schema mistakes."""
    payload = read_json(source)
    if not isinstance(payload, dict) or set(payload) != {
        "dataset", "criteria_version", "criteria", "instructions", "smoke", "dev", "test"
    }:
        raise ValueError("Expected dataset, criteria_version, criteria, instructions, smoke, dev and test")
    for key in ("dataset", "criteria_version", "instructions"):
        if not isinstance(payload[key], str) or not payload[key].strip() or "\n" in payload[key]:
            raise ValueError(f"{key} must be a nonempty single-line string")
    RouteRequest(state="schema check", criteria=payload["criteria"], instructions=payload["instructions"])
    ids, texts, splits = set(), set(), {}
    for split in ("smoke", "dev", "test"):
        rows = payload[split]
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{split} must be a nonempty list")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"id", "text", "label"}:
                raise ValueError(f"{split}: expected exactly id, text, label")
            if any(not isinstance(row[k], str) or not row[k].strip() for k in row):
                raise ValueError(f"{split}: id, text and label must be nonempty strings")
            if row["label"] not in payload["criteria"]:
                raise ValueError(f"{split}: unknown label")
            normalized = " ".join(row["text"].casefold().split())
            if row["id"] in ids or normalized in texts:
                raise ValueError("Duplicate IDs or normalized text within/across splits; remove leakage first")
            ids.add(row["id"])
            texts.add(normalized)
        if split != "smoke" and {r["label"] for r in rows} != set(payload["criteria"]):
            raise ValueError(f"{split}: every criterion needs labeled examples")
        splits[split] = rows
    manifest = {
        "schema_version": 1,
        "dataset": payload["dataset"],
        "dataset_kind": "custom",
        "synthetic": False,
        "source": "user-supplied; not uploaded by import",
        "revision": digest(payload),
        "criteria": payload["criteria"],
        "criteria_metadata": {"version": payload["criteria_version"], "basis": "user-authored"},
        "instructions": payload["instructions"],
        "split_method": "user-supplied; IDs and normalized exact text disjoint",
        "splits": {name: {"count": len(rows), "sha256": digest(rows)} for name, rows in splits.items()},
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in splits.items():
        write_json(output / f"{name}.json", rows)
    write_json(output / "manifest.json", manifest)
    return manifest
