"""
Unit tests for draw.io XML: well-formedness, structure, and layout.
"""

import xml.etree.ElementTree as ET
import pytest
from app.dsl_to_drawio import dsl_to_drawio


def _parse_drawio_xml(xml_str: str) -> ET.Element:
    """Parse draw.io XML; strip declaration if present for ET.fromstring."""
    s = xml_str.strip()
    if s.startswith("<?xml"):
        end = s.index("?>") + 2
        s = s[end:].lstrip()
    return ET.fromstring(s)


def test_drawio_single_xml_declaration():
    """Output must contain at most one XML declaration and it must be at index 0 if present."""
    dsl = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "trust_boundaries": [],
        "groups": [],
        "nodes": [{"id": "n0", "label": "N", "zone": "z0"}],
        "flows": [],
        "controls": [],
    }
    xml_str = dsl_to_drawio(dsl)
    count = xml_str.count("<?xml")
    assert count <= 1, "output must contain at most one XML declaration"
    if count == 1:
        assert xml_str.index("<?xml") == 0, "XML declaration must appear at the start of the document"
    assert "<mxfile" in xml_str


def test_drawio_well_formed():
    dsl = {
        "zones": [
            {"id": "z0", "name": "External", "order": 0, "color": "#fff2cc"},
            {"id": "z1", "name": "Internal", "order": 1, "color": "#d5e8d4"},
        ],
        "trust_boundaries": [{"id": "tb1", "label": "TB1", "between_zones": ["z0", "z1"]}],
        "groups": [],
        "nodes": [
            {"id": "n0", "label": "Client", "zone": "z0", "type": "external"},
            {"id": "n1", "label": "App", "zone": "z1", "type": "service"},
        ],
        "flows": [{"id": "f0", "source": "n0", "target": "n1", "flow_type": "api", "protocol": "HTTPS"}],
        "controls": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    assert root.tag == "mxfile"


def test_drawio_contains_mxGraphModel():
    dsl = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "trust_boundaries": [],
        "groups": [],
        "nodes": [{"id": "n0", "label": "N", "zone": "z0"}],
        "flows": [],
        "controls": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    assert root.find(".//mxGraphModel") is not None
    assert root.find(".//root") is not None


def test_drawio_empty_dsl_expands():
    """Empty DSL is expanded to meet density; output is valid."""
    xml_str = dsl_to_drawio({})
    root = _parse_drawio_xml(xml_str)
    assert root.tag == "mxfile"
    assert xml_str.count("<?xml") <= 1
    assert "<mxfile" in xml_str


def test_drawio_node_cells_inside_zones():
    """Every node mxCell must have parent equal to a zone cell id."""
    dsl = {
        "zones": [{"id": "z0", "name": "Zone0", "order": 0}, {"id": "z1", "name": "Zone1", "order": 1}],
        "trust_boundaries": [{"id": "tb1", "label": "TB1", "between_zones": ["z0", "z1"]}],
        "nodes": [
            {"id": "n0", "label": "A", "zone": "z0"},
            {"id": "n1", "label": "B", "zone": "z1"},
        ],
        "flows": [{"id": "f0", "source": "n0", "target": "n1", "flow_type": "api"}],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    cells = {c.get("id"): c for c in root.findall(".//mxCell")}
    zone_ids = {c.get("id") for c in root.findall(".//mxCell") if c.get("id", "").startswith("zone-")}
    node_cells = [c for c in root.findall(".//mxCell") if c.get("id", "").startswith("node-")]
    for cell in node_cells:
        parent = cell.get("parent")
        assert parent in zone_ids, f"Node {cell.get('id')} must be inside a zone (parent={parent})"


def test_drawio_at_least_one_node_per_zone_after_expand():
    """After expansion, each zone should have at least one node (structural)."""
    dsl = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "nodes": [{"id": "n0", "label": "N", "zone": "z0"}],
        "flows": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    zone_cells = [c for c in root.findall(".//mxCell") if c.get("id", "").startswith("zone-")]
    node_cells = [c for c in root.findall(".//mxCell") if c.get("id", "").startswith("node-")]
    assert len(zone_cells) >= 1
    assert len(node_cells) >= 1


def test_drawio_tb_lines_exist():
    """Trust boundary lines (tb-) should exist when zones > 1."""
    dsl = {
        "zones": [{"id": "z0", "name": "A", "order": 0}, {"id": "z1", "name": "B", "order": 1}],
        "trust_boundaries": [{"id": "tb1", "label": "TB1", "between_zones": ["z0", "z1"]}],
        "nodes": [{"id": "n0", "label": "N", "zone": "z0"}, {"id": "n1", "label": "M", "zone": "z1"}],
        "flows": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    tb_cells = [c for c in root.findall(".//mxCell") if c.get("id", "").startswith("tb-")]
    assert len(tb_cells) >= 1


def test_drawio_no_negative_coordinates():
    """No vertex cell should have negative x or y in geometry."""
    dsl = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "nodes": [{"id": "n0", "label": "N", "zone": "z0"}],
        "flows": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    for cell in root.findall(".//mxCell"):
        geom = cell.find("mxGeometry")
        if geom is not None and cell.get("vertex") == "1":
            x, y = float(geom.get("x", 0)), float(geom.get("y", 0))
            assert x >= 0, f"Cell {cell.get('id')} has negative x"
            assert y >= 0, f"Cell {cell.get('id')} has negative y"


def test_drawio_node_count_at_least_expected():
    """Output should have at least as many node mxCells as input nodes (after expand)."""
    dsl = {
        "zones": [{"id": "z0", "name": "Z", "order": 0}],
        "nodes": [{"id": "n0", "label": "A", "zone": "z0"}],
        "flows": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    node_cells = [c for c in root.findall(".//mxCell") if c.get("id", "").startswith("node-")]
    assert len(node_cells) >= 1


def test_drawio_with_groups():
    """DSL with groups still renders (groups flattened into zone for grid)."""
    dsl = {
        "zones": [{"id": "z0", "name": "Cloud", "order": 0}],
        "trust_boundaries": [],
        "groups": [{"id": "g0", "label": "Tenant", "zone": "z0", "children": ["n0", "n1"]}],
        "nodes": [
            {"id": "n0", "label": "API", "zone": "z0", "type": "api"},
            {"id": "n1", "label": "DB", "zone": "z0", "type": "data_store"},
        ],
        "flows": [{"id": "f0", "source": "n0", "target": "n1", "flow_type": "data"}],
        "controls": [],
    }
    xml_str = dsl_to_drawio(dsl)
    root = _parse_drawio_xml(xml_str)
    assert root is not None
    assert len([c for c in root.findall(".//mxCell") if c.get("id", "").startswith("node-")]) >= 2
