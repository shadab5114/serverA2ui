"""System prompt snapshot.

The fixture was written by the Node implementation (buildSystemPrompt(mergeBasicLayout(
loadLocalCatalog()))) and the Python prompt matched it byte for byte before Node was
retired in P4. It now guards against accidental drift. After an INTENTIONAL change to
the catalog, the layout schemas or the prompt text, refresh it:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/test_prompt_parity.py
"""

from __future__ import annotations

import os
from pathlib import Path

from app.generation.prompt import build_system_prompt
from app.grounding.catalog import generation_catalog, load_catalog

FIXTURE = Path(__file__).parent / "fixtures" / "system_prompt.node.txt"


def test_prompt_matches_snapshot():
    actual = build_system_prompt(generation_catalog()).encode("utf-8")
    if os.getenv("UPDATE_SNAPSHOTS") == "1":
        FIXTURE.write_bytes(actual)
    expected = FIXTURE.read_bytes()
    if actual != expected:
        i = next((k for k, (a, b) in enumerate(zip(actual, expected)) if a != b), min(len(actual), len(expected)))
        raise AssertionError(
            f"prompt differs from the snapshot at byte {i} (now {len(actual)} bytes, snapshot {len(expected)} bytes). "
            "If the change is intentional, rerun with UPDATE_SNAPSHOTS=1.\n"
            f"now:      {actual[max(0, i - 80):i + 80]!r}\nsnapshot: {expected[max(0, i - 80):i + 80]!r}"
        )


def test_generation_catalog_adds_layout_without_touching_the_gate_catalog():
    gen, raw = generation_catalog(), load_catalog()
    for name in ("Column", "Row", "List", "Divider"):
        assert name in gen["components"] and name in gen["names"]
        assert name not in raw["components"]
    assert len(raw["components"]) == 35
