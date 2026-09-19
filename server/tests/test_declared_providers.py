"""Declared data providers (app/data/declared.py): a provider written as JSON, no Python."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.data.declared import load_declared
from app.data.providers import PLANS_LIST, ProviderError, ProviderRegistry, field_matches

ROWS = {
    "_note": "test fixture",
    "catalog": {
        "sessions": [
            {"id": "s1", "title": "Intro to pottery", "city": "Austin", "fee": 40, "online": False,
             "starts": "2026-10-02", "tags": ["craft", "beginner"], "hosts": [{"name": "Ana", "role": "lead"}]},
            {"id": "s2", "title": "Watercolour basics", "city": "Denver", "fee": 0, "online": True,
             "starts": "2026-09-28", "tags": ["art", "beginner"], "hosts": [{"name": "Bo", "role": "lead"}]},
            {"id": "s3", "title": "Advanced glazing", "city": "Austin", "fee": 1200, "online": False,
             "starts": "2026-11-15", "tags": ["craft"], "hosts": [{"name": "Cy", "role": "lead"}, {"name": "Di", "role": "guest"}]},
            {"id": "s4", "title": "Sketching outdoors", "city": "Boise", "fee": 25, "online": False,
             "starts": None, "tags": ["art"], "hosts": []},
        ]
    },
}

SPEC = {
    "description": "Workshop sessions.",
    "source": {"file": "sessions.json", "list": "/catalog/sessions"},
    "sort": {"by": "starts", "order": "asc"},
    "params": {
        "city": {"type": "string", "description": "Only this city.", "filter": {"op": "eq", "field": "city"},
                 "choices": "data", "label": "in {value}"},
        "maxFee": {"type": "number", "description": "Fee cap.", "filter": {"op": "lte", "field": "fee"},
                   "label": "up to ${value:g}"},
        "topic": {"type": "string", "description": "A tag.", "filter": {"op": "eq", "field": "tags/*"}, "choices": "data"},
        "notTag": {"type": "string", "description": "Exclude a tag.", "filter": {"op": "ne", "field": "tags/*"}},
        "host": {"type": "string", "description": "A host's name.", "filter": {"op": "contains", "field": "hosts/*/name"}},
        "onlineOnly": {"type": "boolean", "description": "Only online.", "filter": {"op": "eq", "field": "online", "value": True},
                       "label": "online"},
        "from": {"type": "string", "description": "Starting on or after (YYYY-MM-DD).", "filter": {"op": "gte", "field": "starts"}},
        "limit": {"type": "number", "description": "At most N.", "filter": {"op": "limit"}},
    },
    "computed": {"feeLabel": "${fee:,.2f}", "when": "{starts:date}", "hosts/*/label": "{name} ({role})"},
    "summary": {"all": "All {total} sessions.", "filtered": "{count} of {total} sessions {filters}.", "empty": "No sessions {filters}."},
}


def write(folder: Path, name: str, value: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    write(data, "sessions.json", ROWS)
    write(data / "providers", "sessions.list.json", SPEC)
    return data / "providers", data


@pytest.fixture
def sessions(dirs):
    providers, errors = load_declared(*dirs, taken=set())
    assert not errors
    return providers[0]


def ids(out: dict) -> list[str]:
    return [s["id"] for s in out["sessions"]]


def test_loads_with_fields_read_off_the_data(sessions):
    assert sessions.name == "sessions.list"
    assert {"/sessions", "/sessions/*/title", "/sessions/*/tags/*", "/sessions/*/feeLabel",
            "/sessions/*/hosts/*/label", "/summary", "/count"} <= sessions.fields
    assert field_matches(sessions.fields, "/sessions/2/hosts/0/name")
    assert not field_matches(sessions.fields, "/sessions/0/rating")


def test_describe_lists_params_and_choices_from_the_data(sessions):
    text = sessions.describe()
    assert "city (string, optional): Only this city. One of: Austin, Denver, Boise." in text
    assert "One of: craft, beginner, art." in text


def test_no_params_returns_everything_sorted_with_missing_values_last(sessions):
    out = sessions.call({})
    assert ids(out) == ["s2", "s1", "s3", "s4"]
    assert out["summary"] == "All 4 sessions." and out["count"] == 4


def test_eq_matches_a_choice_case_insensitively_and_rejects_others(sessions):
    out = sessions.call({"city": "austin"})
    assert ids(out) == ["s1", "s3"]
    assert out["summary"] == "2 of 4 sessions in Austin."  # the canonical spelling from the data
    with pytest.raises(ProviderError):
        sessions.call({"city": "Paris"})


def test_numbers_accept_currency_text(sessions):
    assert ids(sessions.call({"maxFee": "$1,000"})) == ["s2", "s1", "s4"]


def test_array_fields_match_any_element(sessions):
    assert ids(sessions.call({"topic": "beginner"})) == ["s2", "s1"]
    assert ids(sessions.call({"notTag": "beginner"})) == ["s3", "s4"]
    assert ids(sessions.call({"host": "di"})) == ["s3"]


def test_a_switch_filters_only_when_on(sessions):
    assert ids(sessions.call({"onlineOnly": "true"})) == ["s2"]
    off = sessions.call({"onlineOnly": "false"})
    assert ids(off) == ["s2", "s1", "s3", "s4"] and off["summary"] == "All 4 sessions."


def test_dates_compare_as_iso_text_and_skip_missing_values(sessions):
    assert ids(sessions.call({"from": "2026-10-01"})) == ["s1", "s3"]


def test_limit_applies_after_sorting(sessions):
    out = sessions.call({"limit": "2"})
    assert ids(out) == ["s2", "s1"]
    assert out["summary"] == "2 of 4 sessions."  # no label, no stray space before the period


def test_computed_fields_format_numbers_dates_and_nested_items(sessions):
    s3 = next(s for s in sessions.call({})["sessions"] if s["id"] == "s3")
    assert s3["feeLabel"] == "$1,200.00" and s3["when"] == "Nov 15, 2026"
    assert [h["label"] for h in s3["hosts"]] == ["Cy (lead)", "Di (guest)"]
    s4 = next(s for s in sessions.call({})["sessions"] if s["id"] == "s4")
    assert s4["when"] == ""  # a null value renders empty


def test_empty_result_and_combined_filter_labels(sessions):
    assert sessions.call({"city": "Boise", "maxFee": "10"})["summary"] == "No sessions in Boise and up to $10."


def test_a_caller_changing_the_output_doesnt_change_the_next_call(sessions):
    first = sessions.call({})
    first["sessions"][0]["title"] = "changed"
    first["sessions"][0]["hosts"].clear()
    again = sessions.call({})["sessions"][0]
    assert again["title"] == "Watercolour basics" and again["hosts"]


def test_derived_cases_exercise_every_param(sessions):
    covered = {name for case in sessions.cases for name in case}
    assert covered == set(SPEC["params"])
    assert sessions.cases[0] == {}
    for case in sessions.cases:
        sessions.call(case)


BROKEN = {
    "typo-field": {"params": {"x": {"type": "string", "description": "d", "filter": {"op": "eq", "field": "citty"}}}},
    "bad-op": {"params": {"x": {"type": "string", "description": "d", "filter": {"op": "like", "field": "city"}}}},
    "bool-no-value": {"params": {"x": {"type": "boolean", "description": "d", "filter": {"op": "eq", "field": "online"}}}},
    "value-not-bool": {"params": {"x": {"type": "string", "description": "d", "filter": {"op": "eq", "field": "online", "value": True}}}},
    "computed-typo": {"computed": {"x": "{titel}"}},
    "bad-sort": {"sort": {"by": "nope"}},
    "no-file": {"source": {"file": "missing.json", "list": "/rows"}},
    "not-a-list": {"source": {"file": "sessions.json", "list": "/catalog"}},
    "half-summary": {"summary": {"all": "All."}},
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_a_broken_declaration_is_reported_not_fatal(dirs, case):
    providers_dir, data_dir = dirs
    write(providers_dir, f"{case}.json", {**SPEC, "params": {}, "computed": {}, **BROKEN[case]})
    providers, errors = load_declared(providers_dir, data_dir, taken=set())
    assert [p.name for p in providers] == ["sessions.list"]  # the good one still loads
    assert len(errors) == 1 and errors[0].startswith(f"{case}.json: ")


def test_name_must_match_file_and_not_shadow_a_code_provider(dirs):
    providers_dir, data_dir = dirs
    write(providers_dir, "a.json", {**SPEC, "name": "b"})
    write(providers_dir, "plans.list.json", SPEC)
    _, errors = load_declared(providers_dir, data_dir, taken={"plans.list"})
    assert len(errors) == 2


def test_registry_serves_both_kinds_and_picks_up_changes_without_a_restart(dirs):
    providers_dir, data_dir = dirs
    registry = ProviderRegistry([PLANS_LIST], lambda: dirs)
    assert set(registry) == {"plans.list", "sessions.list"}
    assert registry["plans.list"] is PLANS_LIST

    write(providers_dir, "cities.list.json", {**SPEC, "params": {}, "computed": {}})
    rows = json.loads((data_dir / "sessions.json").read_text(encoding="utf-8"))
    rows["catalog"]["sessions"].append({**rows["catalog"]["sessions"][0], "id": "s5", "city": "Reno"})
    path = write(data_dir, "sessions.json", rows)
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10**9))  # coarse clocks

    assert "cities.list" in registry
    assert registry["sessions.list"].call({"city": "reno"})["count"] == 1

    write(providers_dir, "cities.list.json", {**SPEC, "sort": {"by": "nope"}})
    assert "cities.list" not in registry and registry.errors
