"""Parsing the Business Value Stream field ('<name> {<id>}') into (name, id)."""

from __future__ import annotations

from teg.ingestion.extraction.value_stream_field import (
    parse_value_stream,
    parse_value_stream_stage,
)


def test_plain_string() -> None:
    assert parse_value_stream("configure price {VS1024}") == ("configure price", "VS1024")
    assert parse_value_stream("Configure, Price and Quote {VSR00074586}") == (
        "Configure, Price and Quote", "VSR00074586")


def test_whitespace_tolerant() -> None:
    assert parse_value_stream("  Resolve Appeal  { VSR00074590 } ") == ("Resolve Appeal", "VSR00074590")


def test_select_object_and_list() -> None:
    assert parse_value_stream({"value": "Receive Care {VS9}"}) == ("Receive Care", "VS9")
    assert parse_value_stream({"name": "Issue Payment {VS3}"}) == ("Issue Payment", "VS3")
    assert parse_value_stream([{"value": "Adjudicate Claim {VS5}"}]) == ("Adjudicate Claim", "VS5")


def test_absent_or_unparseable_is_none() -> None:
    assert parse_value_stream(None) is None
    assert parse_value_stream("") is None
    assert parse_value_stream("no braces here") is None
    assert parse_value_stream([]) is None


def test_parse_value_stream_stage_takes_the_stage_segment() -> None:
    # "<vs> {vs_id} - <stage> {stage_id}" -> the STAGE (last segment), separator stripped.
    assert parse_value_stream_stage("Configure Price {VS1024} - Quote Setup {VSS5}") == (
        "Quote Setup", "VSS5")
    assert parse_value_stream_stage("Resolve Appeal {VSR001} - Intake & Triage {ST1}") == (
        "Intake & Triage", "ST1")
    assert parse_value_stream_stage({"value": "A {V1} - B {S2}"}) == ("B", "S2")


def test_parse_value_stream_stage_cascading_select() -> None:
    # The real field shape: a cascading select - parent = VS, child = stage. Take the CHILD.
    raw = {
        "value": "Fulfill Value-Based Care Arrangement {VSR00074595}",
        "id": "42532",
        "child": {"value": "Determine Payment and Funding {VSS00074635}", "id": "42600"},
    }
    assert parse_value_stream_stage(raw) == ("Determine Payment and Funding", "VSS00074635")


def test_parse_value_stream_stage_none_without_a_stage() -> None:
    assert parse_value_stream_stage(None) is None
    assert parse_value_stream_stage("Resolve Appeal {VSR001}") is None  # VS only, no stage segment
    assert parse_value_stream_stage({"value": "Resolve Appeal {VSR001}"}) is None  # parent only, no child
    assert parse_value_stream_stage("no braces") is None
