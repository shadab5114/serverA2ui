"""validate_and_repair_graph must match Node's validateAndRepairGraph on every fixture.

Fixtures: tests/fixtures/graph_check/*.json = {input, output (after in-place repair), result},
recorded from the Node implementation (scripts/dump-parity-fixtures.mjs, retired with it in P4).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.generation.graph_check import validate_and_repair_graph

CASES = sorted((Path(__file__).parent / "fixtures" / "graph_check").glob("*.json"))


def test_fixtures_exist():
    assert len(CASES) >= 10


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_matches_node(path: Path):
    case = json.loads(path.read_text(encoding="utf-8"))
    doc = copy.deepcopy(case["input"])
    result = validate_and_repair_graph(doc)
    assert result == case["result"]
    # the in-place repair must produce the same document, key order included
    assert json.dumps(doc) == json.dumps(case["output"])
