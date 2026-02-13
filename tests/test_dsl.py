"""
Unit tests for Architecture DSL validation (Pydantic + JSON schema).
"""

import pytest
from app.dsl import (
    ArchitectureDSL,
    Zone,
    TrustBoundary,
    Node,
    Group,
    Flow,
    Control,
    validate_dsl,
    get_json_schema,
)


def test_zone_valid():
    z = Zone(id="z0", name="External", order=0, color="#fff2cc")
    assert z.id == "z0"
    assert z.order == 0


def test_validate_dsl_minimal_valid():
    data = {
        "zones": [{"id": "z0", "name": "External", "order": 0, "color": "#fff"}],
        "trust_boundaries": [],
        "groups": [],
        "nodes": [
            {"id": "n0", "label": "Client", "zone": "z0", "type": "external", "tags": []}
        ],
        "flows": [],
        "controls": [],
    }
    model, errors = validate_dsl(data)
    assert model is not None
    assert errors == []
    assert len(model.zones) == 1
    assert model.zones[0].name == "External"
    assert len(model.nodes) == 1


def test_validate_dsl_invalid_zone_order():
    data = {
        "zones": [{"id": "z0", "name": "External", "order": -1, "color": "#fff"}],
        "nodes": [],
        "flows": [],
    }
    model, errors = validate_dsl(data)
    assert model is None
    assert len(errors) >= 1
    assert any("order" in e.lower() or "greater" in e.lower() for e in errors)


def test_validate_dsl_invalid_node_type():
    data = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "nodes": [
            {"id": "n0", "label": "X", "zone": "z0", "type": "invalid_type"}
        ],
        "flows": [],
    }
    model, errors = validate_dsl(data)
    assert model is None
    assert len(errors) >= 1


def test_validate_dsl_flow_source_target():
    data = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "nodes": [
            {"id": "n0", "label": "A", "zone": "z0"},
            {"id": "n1", "label": "B", "zone": "z0"},
        ],
        "flows": [
            {"id": "f0", "source": "n0", "target": "n1", "flow_type": "api", "protocol": "HTTPS"}
        ],
    }
    model, errors = validate_dsl(data)
    assert model is not None
    assert errors == []
    assert len(model.flows) == 1
    assert model.flows[0].source == "n0" and model.flows[0].target == "n1"


def test_get_json_schema():
    schema = get_json_schema()
    assert "properties" in schema
    assert "zones" in schema["properties"]
    assert "nodes" in schema["properties"]
    assert "flows" in schema["properties"]
