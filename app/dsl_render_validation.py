"""
Render-time DSL validation and preparation for draw.io export.
Validates structure, normalizes zone IDs, enforces minimum density (with optional expand).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Enterprise density minimums (expand DSL if below these)
MIN_ZONES = 5
MIN_NODES = 25
MIN_FLOWS = 20
MIN_NODES_HARD = 1  # Fail if nodes < this (explicit error; use 1 when using expand)

# Zone ID normalization: alias -> canonical (lowercase, snake_case)
ZONE_ALIASES: dict[str, str] = {
    "dmz_zone": "dmz",
    "dmz": "dmz",
    "internet": "internet",
    "external": "internet",
    "perimeter": "dmz",
    "internal": "internal",
    "on_prem": "on_prem",
    "on-prem": "on_prem",
    "onprem": "on_prem",
    "cloud": "cloud",
    "tenant": "tenant",
    "data": "data",
    "data_layer": "data",
    "identity": "identity",
    "vendor": "vendor",
}


def _normalize_zone_id(raw: str) -> str:
    """Lowercase, replace non-alphanumeric with underscore, collapse underscores."""
    s = (raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "zone"


def _canonical_zone_id(raw: str) -> str:
    """Map alias to canonical zone id if known, else normalized."""
    normalized = _normalize_zone_id(raw)
    return ZONE_ALIASES.get(normalized, normalized)


def _ensure_list(obj: Any) -> list[Any]:
    if isinstance(obj, list):
        return obj
    return [obj] if obj is not None else []


def _expand_dsl_to_density(
    dsl: dict[str, Any],
    zone_ids: list[str],
    node_by_id: dict[str, dict],
    min_zones: int,
    min_nodes: int,
    min_flows: int,
) -> dict[str, Any]:
    """Add placeholder zones, nodes, and flows so DSL meets minimums. Returns new dsl dict."""
    zones = list(dsl.get("zones", []))
    nodes = list(dsl.get("nodes", []))
    flows = list(dsl.get("flows", []))
    trust_boundaries = list(dsl.get("trust_boundaries", []))
    zone_id_set = {z["id"] for z in zones}
    node_id_set = {n["id"] for n in nodes}

    # Add zones until we have min_zones
    next_z = len(zones)
    while len(zones) < min_zones:
        zid = f"zone_{next_z}"
        zones.append({
            "id": zid,
            "name": f"Zone {next_z + 1}",
            "order": next_z,
            "color": "#e1d5e7",
        })
        zone_id_set.add(zid)
        if len(zones) >= 2:
            trust_boundaries.append({
                "id": f"tb_{next_z}",
                "label": f"TB{len(trust_boundaries) + 1}",
                "between_zones": [zones[-2]["id"], zid],
            })
        next_z += 1

    # Add nodes until we have min_nodes (spread across zones)
    next_n = len(nodes)
    zone_order = sorted(zones, key=lambda z: z.get("order", 0))
    while len(nodes) < min_nodes:
        z = zone_order[next_n % len(zone_order)]
        nid = f"node_{next_n}"
        nodes.append({
            "id": nid,
            "label": f"Component {next_n + 1}",
            "zone": z["id"],
            "type": "service",
            "tags": [],
        })
        node_id_set.add(nid)
        node_by_id[nid] = nodes[-1]
        next_n += 1

    # Add flows until we have min_flows (between consecutive nodes)
    node_list = list(node_by_id.keys())
    next_f = len(flows)
    while len(flows) < min_flows and len(node_list) >= 2:
        i = next_f % (len(node_list) - 1)
        src, tgt = node_list[i], node_list[i + 1]
        flows.append({
            "id": f"flow_{next_f}",
            "source": src,
            "target": tgt,
            "flow_type": "api",
            "protocol": "HTTPS",
            "auth": "",
            "data_class": "",
            "label": None,
        })
        next_f += 1

    return {
        **dsl,
        "zones": zones,
        "nodes": nodes,
        "flows": flows,
        "trust_boundaries": trust_boundaries,
    }


def validate_and_prepare_dsl(
    dsl: dict[str, Any],
    min_zones: int = MIN_ZONES,
    min_nodes: int = MIN_NODES,
    min_flows: int = MIN_FLOWS,
    min_nodes_hard: int = MIN_NODES_HARD,
    expand_to_meet_density: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Validate DSL for rendering and optionally normalize/expand.
    Returns (prepared_dsl, errors). If errors non-empty, prepared_dsl may be None.
    """
    dsl = dsl or {}
    errors: list[str] = []
    zones = sorted(_ensure_list(dsl.get("zones", [])), key=lambda z: z.get("order", 0))
    nodes = _ensure_list(dsl.get("nodes", []))
    flows = _ensure_list(dsl.get("flows", []))
    trust_boundaries = _ensure_list(dsl.get("trust_boundaries", []))

    if not zones and not expand_to_meet_density:
        errors.append("At least one zone is required.")
        return (None, errors)
    if not zones and expand_to_meet_density:
        # Expand from empty: add placeholder zones/nodes/flows
        dsl = _expand_dsl_to_density(
            {**dsl, "zones": [], "nodes": [], "flows": [], "trust_boundaries": []},
            [], {}, min_zones, min_nodes, min_flows,
        )
        return (dsl, [])

    zone_ids = {z["id"] for z in zones}
    node_by_id = {n["id"]: n for n in nodes}

    # Normalize zone IDs (lowercase, snake_case); map aliases to canonical; ensure uniqueness
    zone_id_map: dict[str, str] = {}
    seen_canonical: dict[str, int] = {}
    new_zones: list[dict] = []
    for z in zones:
        c = _canonical_zone_id(z["id"])
        if c in seen_canonical:
            seen_canonical[c] += 1
            new_id = f"{c}_{seen_canonical[c]}"
        else:
            seen_canonical[c] = 0
            new_id = c
        zone_id_map[z["id"]] = new_id
        new_zones.append({**z, "id": new_id})
    zones = new_zones
    zone_ids = {z["id"] for z in zones}

    for n in nodes:
        zid = n.get("zone") or ""
        n["zone"] = zone_id_map.get(zid, zid)
        if n["zone"] not in zone_ids:
            errors.append(f"Node '{n.get('id')}' references invalid zone '{n.get('zone')}'.")
    if errors:
        return (None, errors)

    # Hard minimum: need at least one node
    if len(nodes) < min_nodes_hard:
        errors.append(f"At least {min_nodes_hard} node(s) are required (found {len(nodes)}).")
        return (None, errors)

    # Flows: validate source/target exist
    valid_node_ids = {n["id"] for n in nodes}
    for f in flows:
        if f.get("source") not in valid_node_ids:
            logger.warning("Flow %s references non-existent source node %s", f.get("id"), f.get("source"))
        if f.get("target") not in valid_node_ids:
            logger.warning("Flow %s references non-existent target node %s", f.get("id"), f.get("target"))

    # Empty zone warning
    nodes_per_zone: dict[str, int] = {z["id"]: 0 for z in zones}
    for n in nodes:
        nodes_per_zone[n["zone"]] = nodes_per_zone.get(n["zone"], 0) + 1
    for zid, count in nodes_per_zone.items():
        if count == 0:
            logger.warning("Zone '%s' has zero nodes.", zid)

    # Enterprise density: expand if below minimums
    if expand_to_meet_density and (len(zones) < min_zones or len(nodes) < min_nodes or len(flows) < min_flows):
        dsl = _expand_dsl_to_density(
            {**dsl, "zones": zones, "nodes": nodes, "flows": flows, "trust_boundaries": trust_boundaries},
            [z["id"] for z in zones],
            {n["id"]: n for n in nodes},
            min_zones,
            min_nodes,
            min_flows,
        )
        logger.info("DSL expanded to meet density: zones=%s, nodes=%s, flows=%s", len(dsl["zones"]), len(dsl["nodes"]), len(dsl["flows"]))
    else:
        dsl = {**dsl, "zones": zones, "nodes": nodes, "flows": flows, "trust_boundaries": trust_boundaries}

    return (dsl, [])
