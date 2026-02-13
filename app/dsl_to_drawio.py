"""
DSL → draw.io: Renders Architecture DSL to valid diagrams.net mxGraph XML.
Enterprise-quality security reference architecture: horizontal swimlanes,
trust boundaries, deterministic grid layout, orthogonal flows, legend.
"""

from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants (deterministic grid engine)
# ---------------------------------------------------------------------------
CANVAS_WIDTH = 1400
ZONE_HEADER_HEIGHT = 32
NODE_W = 160
NODE_H = 60
GAP_X = 40
GAP_Y = 40
PADDING = 40
TB_HEIGHT = 24
LEGEND_HEIGHT = 160
LEGEND_WIDTH = 400

# Enterprise styles (visible stroke + fill)
STYLE_APP = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=1;"
STYLE_SERVICE = "rounded=1;whiteSpace=wrap;html=1;fillColor=#d5e8d4;strokeColor=#82b366;strokeWidth=1;"
STYLE_API = "shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;strokeWidth=1;"
STYLE_DATA_STORE = "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#fff2cc;strokeColor=#d6b656;strokeWidth=1;"
STYLE_IDENTITY = "shape=ellipse;whiteSpace=wrap;html=1;fillColor=#e1d5e7;strokeColor=#9673a6;strokeWidth=1;"
STYLE_SECURITY = "shape=shield;whiteSpace=wrap;html=1;fillColor=#f8cecc;strokeColor=#b85450;strokeWidth=2;"
STYLE_VENDOR = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;dashed=1;strokeWidth=1;"
STYLE_EXTERNAL = "rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;dashed=1;strokeWidth=1;"
STYLE_EDGE_SOLID = "endArrow=block;html=1;rounded=0;curved=0;orthogonalLoop=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;strokeColor=#6c8ebf;strokeWidth=2;"
STYLE_EDGE_DASHED = "endArrow=block;html=1;rounded=0;dashed=1;curved=0;orthogonalLoop=1;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;strokeColor=#999999;strokeWidth=1;"
STYLE_TB = "shape=rect;fillColor=none;strokeColor=#b85450;strokeWidth=2;dashed=1;html=1;"
STYLE_LEGEND = "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;fontSize=11;"


def _node_style(node_type: str) -> str:
    m = {
        "app": STYLE_APP,
        "service": STYLE_SERVICE,
        "api": STYLE_API,
        "data_store": STYLE_DATA_STORE,
        "identity": STYLE_IDENTITY,
        "security_control": STYLE_SECURITY,
        "vendor": STYLE_VENDOR,
        "external": STYLE_EXTERNAL,
    }
    return m.get(node_type, STYLE_APP)


def _flow_style(flow_type: str) -> str:
    if flow_type in ("log", "telemetry"):
        return STYLE_EDGE_DASHED
    return STYLE_EDGE_SOLID


def _flow_label(f: dict[str, Any]) -> str:
    if f.get("label"):
        return str(f["label"])
    parts = [f.get("protocol") or "", f.get("auth") or "", f.get("data_class") or ""]
    return " | ".join(p for p in parts if p).strip() or " "


def _ensure_list(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj
    return [obj] if obj is not None else []


def _next_id(prefix: str, counter: list[int]) -> str:
    c = counter[0]
    counter[0] += 1
    return f"{prefix}{c}"


def _add_cell(
    root: ET.Element,
    cell_id: str,
    parent_id: str,
    value: str = "",
    style: str = "",
    vertex: bool = False,
    edge: bool = False,
    x: float = 0,
    y: float = 0,
    width: float = 0,
    height: float = 0,
    relative: str = "1",
    source: str | None = None,
    target: str | None = None,
) -> ET.Element:
    cell = ET.SubElement(root, "mxCell", id=cell_id, parent=parent_id)
    if value:
        cell.set("value", value)
    if style:
        cell.set("style", style)
    if vertex:
        cell.set("vertex", "1")
    if edge:
        cell.set("edge", "1")
    geom = ET.SubElement(cell, "mxGeometry", x=f"{x}", y=f"{y}", width=f"{width}", height=f"{height}", relative=relative)
    geom.set("as", "geometry")
    if source is not None:
        cell.set("source", source)
    if target is not None:
        cell.set("target", target)
    return cell


def _serialize_xml_safe(root_elem: ET.Element) -> str:
    """Serialize to XML string with at most one declaration at position 0. No minidom."""
    rough = ET.tostring(root_elem, encoding="unicode", default_namespace="", method="xml")
    # ET.tostring does not add XML declaration by default
    out = '<?xml version="1.0" encoding="UTF-8"?>\n' + rough
    # Safety strip: if somehow multiple declarations, keep only first
    if out.count("<?xml") > 1:
        first = out.index("<?xml")
        second = out.index("?>", first) + 2
        rest = out[second:].lstrip()
        out = out[:second] + "\n" + re.sub(r"<\?xml[^>]*\?>\s*", "", rest)
    assert out.count("<?xml") <= 1, "output must contain at most one XML declaration"
    if out.count("<?xml") == 1:
        assert out.index("<?xml") == 0
    assert "<mxfile" in out
    return out


def dsl_to_drawio(dsl: dict[str, Any]) -> str:
    """
    Convert Architecture DSL to draw.io mxGraph XML.
    Uses validated/prepared DSL: zones exist, nodes reference valid zones,
    deterministic grid layout, nodes parented to zone swimlanes, TBs on root layer.
    """
    from app.dsl_render_validation import validate_and_prepare_dsl

    # Validation expands sparse DSL to meet enterprise density; requires at least one zone
    dsl, val_errors = validate_and_prepare_dsl(dsl, expand_to_meet_density=True)
    if dsl is None:
        raise ValueError("DSL validation failed: " + "; ".join(val_errors))

    zones = sorted(_ensure_list(dsl.get("zones", [])), key=lambda z: z.get("order", 0))
    trust_boundaries = _ensure_list(dsl.get("trust_boundaries", []))
    nodes = _ensure_list(dsl.get("nodes", []))
    flows = _ensure_list(dsl.get("flows", []))
    node_by_id = {n["id"]: n for n in nodes}
    nodes_in_zone: dict[str, list[dict]] = {}
    for n in nodes:
        zid = n.get("zone") or ""
        nodes_in_zone.setdefault(zid, []).append(n)

    ctr = [1]

    def next_id(p: str) -> str:
        return _next_id(p, ctr)

    # Grid layout per zone: content width = CANVAS_WIDTH, content height from required_height
    zone_width = CANVAS_WIDTH
    content_width = zone_width - 2 * PADDING
    cols_max = max(1, int((content_width + GAP_X) / (NODE_W + GAP_X)))
    zone_heights: dict[str, float] = {}
    for z in zones:
        zid = z["id"]
        n_list = nodes_in_zone.get(zid, [])
        n_count = len(n_list)
        rows = math.ceil(n_count / cols_max) if n_count else 1
        required_content_h = PADDING + rows * (NODE_H + GAP_Y)
        zone_heights[zid] = ZONE_HEADER_HEIGHT + required_content_h

    y_cursor = 0.0
    zone_geometry: dict[str, tuple[float, float, float, float]] = {}
    for z in zones:
        zid = z["id"]
        h = zone_heights[zid]
        zone_geometry[zid] = (0, y_cursor, zone_width, h)
        y_cursor += h

    # Trust boundaries between zones (full width, between zones)
    for _ in trust_boundaries:
        y_cursor += TB_HEIGHT
    legend_y = y_cursor + 20

    # Build XML: root layer id="1"
    root_elem = ET.Element("mxfile", host="app.diagrams.net", modified="2025-01-01T00:00:00.000Z")
    diagram = ET.SubElement(root_elem, "diagram", id="security-arch", name="Security Reference Architecture")
    model = ET.SubElement(diagram, "mxGraphModel", dx="1422", dy="794", grid="1", gridSize="10", guides="1", tooltips="1", connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth="1600", pageHeight="3200", math="0", shadow="0")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    # ---------- Zones (swimlane containers) ----------
    zone_cell_ids: dict[str, str] = {}
    for z in zones:
        zid = z["id"]
        x, y, w, h = zone_geometry[zid]
        cell_id = next_id("zone-")
        zone_cell_ids[zid] = cell_id
        fill = (z.get("color") or "#dae8fc").strip()
        style = f"swimlane;horizontal=1;startSize={ZONE_HEADER_HEIGHT};fillColor={fill};strokeColor=#6c8ebf;fontStyle=1;fontSize=12;whiteSpace=wrap;html=1;"
        _add_cell(root, cell_id, "1", value=z.get("name") or zid, style=style, vertex=True, x=x, y=y, width=w, height=h, relative="0")

    # ---------- Nodes (parent = zone mxCell id, geometry relative to zone) ----------
    node_cell_ids: dict[str, str] = {}
    for z in zones:
        zid = z["id"]
        parent_id = zone_cell_ids[zid]
        zx, zy, zw, zh = zone_geometry[zid]
        zone_content_w = zw
        zone_content_h = zh - ZONE_HEADER_HEIGHT
        n_list = nodes_in_zone.get(zid, [])
        cols = max(1, min(cols_max, len(n_list)) if n_list else 1)
        for i, n in enumerate(n_list):
            col = i % cols
            row = i // cols
            x = PADDING + col * (NODE_W + GAP_X)
            y = PADDING + row * (NODE_H + GAP_Y)
            # Layout assertion: in bounds
            assert x >= 0 and y >= 0, "node x,y must be >= 0"
            assert x + NODE_W <= zone_content_w and y + NODE_H <= zone_content_h, "node must be inside zone"
            cell_id = next_id("node-")
            node_cell_ids[n["id"]] = cell_id
            style = _node_style(n.get("type", "app"))
            _add_cell(root, cell_id, parent_id, value=n.get("label", n["id"]), style=style, vertex=True, x=x, y=y, width=NODE_W, height=NODE_H, relative="1")

    # ---------- Trust boundaries (parent to root "1", full width, dashed red) ----------
    for i, tb in enumerate(trust_boundaries):
        between = tb.get("between_zones", [])
        if len(between) < 2:
            continue
        z0, z1 = between[0], between[1]
        if z0 not in zone_geometry or z1 not in zone_geometry:
            continue
        _, y0, _, h0 = zone_geometry[z0]
        y_line = y0 + h0
        label = (tb.get("label") or f"TB{i + 1}").strip()
        cell_id = next_id("tb-")
        _add_cell(root, cell_id, "1", value=label, style=STYLE_TB, vertex=True, x=0, y=y_line, width=CANVAS_WIDTH, height=3, relative="0")
        lbl_id = next_id("tblbl-")
        _add_cell(root, lbl_id, "1", value=label, style="text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontSize=10;fontColor=#b85450;", vertex=True, x=CANVAS_WIDTH // 2 - 40, y=y_line - 16, width=80, height=16, relative="0")

    # ---------- Flows (orthogonal, labeled; skip invalid and log) ----------
    for f in flows:
        src, tgt = f.get("source"), f.get("target")
        if src not in node_cell_ids or tgt not in node_cell_ids:
            logger.warning("Flow %s skipped: source or target node missing (source=%s, target=%s)", f.get("id"), src, tgt)
            continue
        fid = next_id("edge-")
        style = _flow_style(f.get("flow_type", "generic"))
        label = _flow_label(f)
        _add_cell(root, fid, "1", value=label, style=style, edge=True, source=node_cell_ids[src], target=node_cell_ids[tgt], x=0, y=0, width=0, height=0, relative="1")

    # ---------- Legend (root layer) ----------
    legend_text = (
        "Legend&#xa;"
        "• Solid line: API / Auth / Data flow&#xa;"
        "• Dashed line: Log / Telemetry&#xa;"
        "• Red dashed: Trust boundary&#xa;"
        "• Rounded rect: App/Service | Hexagon: API | Cylinder: Data store&#xa;"
        "• Ellipse: Identity | Shield: Control | Dashed border: External/Vendor"
    )
    _add_cell(root, next_id("legend-"), "1", value=legend_text, style=STYLE_LEGEND, vertex=True, x=CANVAS_WIDTH - LEGEND_WIDTH - 20, y=legend_y, width=LEGEND_WIDTH, height=LEGEND_HEIGHT, relative="0")

    return _serialize_xml_safe(root_elem)
