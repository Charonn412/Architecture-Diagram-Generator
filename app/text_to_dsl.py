"""
Text → DSL: Converts natural language (or structured text) into Architecture DSL JSON.
- If OPENAI_API_KEY is set: uses LLM to produce DSL, with validation/repair loop.
- Otherwise: deterministic stub generator from keyword extraction.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from app.dsl import (
    ArchitectureDSL,
    Control,
    Flow,
    Group,
    Node,
    TrustBoundary,
    Zone,
    get_json_schema,
    validate_dsl,
)

# Maximum repair attempts when using LLM
MAX_REPAIR_ATTEMPTS = 2


def _stub_dsl_from_text(text: str) -> dict[str, Any]:
    """
    Deterministic stub: build a minimal valid DSL from keywords in text.
    No proprietary names; generic zones and components.
    """
    t = (text or "").lower()
    zones_list: list[dict[str, Any]] = []
    nodes_list: list[dict[str, Any]] = []
    flows_list: list[dict[str, Any]] = []
    groups_list: list[dict[str, Any]] = []
    trust_boundaries_list: list[dict[str, Any]] = []
    controls_list: list[dict[str, Any]] = []

    # Infer zones from keywords
    zone_keywords = [
        ("internet", "Internet", "#fff2cc"),
        ("dmz", "DMZ", "#ffe6cc"),
        ("cloud", "Cloud", "#dae8fc"),
        ("tenant", "Tenant", "#e1d5e7"),
        ("on-prem", "On-Premises", "#d5e8d4"),
        ("internal", "Internal", "#d5e8d4"),
        ("data", "Data Layer", "#f8cecc"),
        ("identity", "Identity", "#e1d5e7"),
        ("vendor", "Vendor / External", "#f5f5f5"),
    ]
    for i, (kw, name, color) in enumerate(zone_keywords):
        if kw in t or name.lower() in t:
            zones_list.append({"id": f"z{i}", "name": name, "order": i, "color": color})

    if not zones_list:
        zones_list = [
            {"id": "z0", "name": "External", "order": 0, "color": "#fff2cc"},
            {"id": "z1", "name": "Perimeter", "order": 1, "color": "#ffe6cc"},
            {"id": "z2", "name": "Internal", "order": 2, "color": "#d5e8d4"},
        ]

    zone_ids = [z["id"] for z in zones_list]
    # Trust boundaries between consecutive zones
    for i in range(len(zone_ids) - 1):
        trust_boundaries_list.append({
            "id": f"tb{i + 1}",
            "label": f"TB{i + 1}",
            "between_zones": [zone_ids[i], zone_ids[i + 1]],
        })

    # Nodes: infer from keywords
    node_id = 0
    if "api" in t or "gateway" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "API Gateway", "zone": zone_ids[min(1, len(zone_ids) - 1)],
            "type": "api", "tags": [],
        })
        node_id += 1
    if "waf" in t or "firewall" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "WAF / Firewall", "zone": zone_ids[0] if zone_ids else "z0",
            "type": "security_control", "tags": [],
        })
        node_id += 1
    if "app" in t or "application" in t or "service" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "Application Service", "zone": zone_ids[-1] if zone_ids else "z2",
            "type": "service", "tags": [],
        })
        node_id += 1
    if "database" in t or "db" in t or "store" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "Database", "zone": zone_ids[-1] if zone_ids else "z2",
            "type": "data_store", "tags": [],
        })
        node_id += 1
    if "identity" in t or "idp" in t or "oauth" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "Identity Provider", "zone": zone_ids[min(1, len(zone_ids) - 1)] if zone_ids else "z1",
            "type": "identity", "tags": [],
        })
        node_id += 1
    if "user" in t or "client" in t:
        nodes_list.append({
            "id": f"n{node_id}", "label": "User / Client", "zone": zone_ids[0] if zone_ids else "z0",
            "type": "external", "tags": [],
        })
        node_id += 1

    if not nodes_list:
        nodes_list = [
            {"id": "n0", "label": "Client", "zone": zone_ids[0], "type": "external", "tags": []},
            {"id": "n1", "label": "Web App", "zone": zone_ids[-1], "type": "service", "tags": []},
            {"id": "n2", "label": "Database", "zone": zone_ids[-1], "type": "data_store", "tags": []},
        ]
        node_id = 3

    # Flows: connect first few nodes
    node_ids = [n["id"] for n in nodes_list]
    if len(node_ids) >= 2:
        flows_list.append({
            "id": "f0", "source": node_ids[0], "target": node_ids[1],
            "flow_type": "api", "protocol": "HTTPS", "auth": "OAuth2", "data_class": "PII", "label": None,
        })
    if len(node_ids) >= 3:
        flows_list.append({
            "id": "f1", "source": node_ids[1], "target": node_ids[2],
            "flow_type": "data", "protocol": "TLS", "auth": "mTLS", "data_class": "Confidential", "label": None,
        })

    # Optional controls
    if "encrypt" in t or "tls" in t:
        controls_list.append({
            "id": "c0", "scope": node_ids[:2] if node_ids else [], "control_type": "Encryption (TLS)",
        })

    return {
        "title": "Security Reference Architecture",
        "zones": zones_list,
        "trust_boundaries": trust_boundaries_list,
        "groups": groups_list,
        "nodes": nodes_list,
        "flows": flows_list,
        "controls": controls_list,
    }


def _call_llm_for_dsl(text: str, profile: str, detail_level: str, schema: dict[str, Any]) -> str | None:
    """Call OpenAI to produce DSL JSON. Returns JSON string or None on failure."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        return None
    client = OpenAI(api_key=api_key)
    prompt = f"""You are a security architect. Convert the following architecture description into a strict JSON object that matches this schema.

Schema (follow exactly):
{json.dumps(schema, indent=2)}

Requirements:
- Use only the fields defined in the schema. No extra fields.
- zones: list of {{"id": string, "name": string, "order": number (0=top), "color": hex or name}}
- trust_boundaries: list of {{"id": string, "label": string, "between_zones": [zone_id, zone_id]}}
- groups: list of {{"id": string, "label": string, "zone": zone_id, "children": [node_id or group_id]}}
- nodes: list of {{"id": string, "label": string, "zone": zone_id, "type": "app"|"service"|"api"|"data_store"|"identity"|"security_control"|"vendor"|"external", "tags": []}}
- flows: list of {{"id": string, "source": node_id, "target": node_id, "flow_type": "api"|"auth"|"data"|"log"|"telemetry"|"generic", "protocol": string, "auth": string, "data_class": string, "label": null or string}}
- controls: list of {{"id": string, "scope": [id, ...], "control_type": string}}

Profile: {profile}. Detail level: {detail_level}.

Architecture description:
---
{text[:8000]}
---

Respond with ONLY the JSON object, no markdown code fence or explanation."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        return content
    except Exception:
        return None


def _repair_dsl_with_llm(current_json: str, validation_errors: list[str], schema: dict[str, Any]) -> str | None:
    """Ask LLM to fix the JSON given validation errors. Returns repaired JSON string or None."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        return None
    client = OpenAI(api_key=api_key)
    prompt = f"""The following JSON is invalid for our architecture schema. Fix it so it validates.

Validation errors:
{chr(10).join(validation_errors)}

Current JSON:
{current_json}

Schema (for reference):
{json.dumps(schema, indent=2)}

Respond with ONLY the corrected JSON object, no markdown or explanation."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        return content
    except Exception:
        return None


def text_to_dsl(
    text: str,
    profile: str = "Generic Security Reference",
    detail_level: str = "standard",
    use_llm: bool | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Convert text to Architecture DSL (dict).
    - use_llm True: try LLM (if OPENAI_API_KEY set); fallback to stub on failure.
    - use_llm False: use stub only.
    - use_llm None: try LLM if key present, else stub.

    Returns (dsl_dict, errors). If errors non-empty, dsl_dict may still be the stub (when LLM failed).
    """
    errors: list[str] = []
    schema = get_json_schema()
    dsl_dict: dict[str, Any] | None = None
    raw_json_str: str | None = None

    try_llm = use_llm if use_llm is not None else bool(os.environ.get("OPENAI_API_KEY"))

    if try_llm:
        raw_json_str = _call_llm_for_dsl(text, profile, detail_level, schema)
        if raw_json_str:
            try:
                dsl_dict = json.loads(raw_json_str)
            except json.JSONDecodeError as e:
                errors.append(f"LLM returned invalid JSON: {e}")
                dsl_dict = None

    if dsl_dict is None and not try_llm:
        dsl_dict = _stub_dsl_from_text(text)
    elif dsl_dict is None and try_llm:
        dsl_dict = _stub_dsl_from_text(text)
        errors.append("LLM unavailable or returned invalid response; used stub generator.")

    if dsl_dict is None:
        return (None, errors or ["Failed to produce DSL."])

    # Validation and optional repair loop
    model, validation_errors = validate_dsl(dsl_dict)
    attempt = 0
    while model is None and validation_errors and try_llm and attempt < MAX_REPAIR_ATTEMPTS:
        raw_json_str = json.dumps(dsl_dict, indent=2)
        repaired = _repair_dsl_with_llm(raw_json_str, validation_errors, schema)
        if repaired:
            try:
                dsl_dict = json.loads(repaired)
                model, validation_errors = validate_dsl(dsl_dict)
            except json.JSONDecodeError:
                validation_errors = ["Repair produced invalid JSON"]
        attempt += 1

    if model is None:
        return (dsl_dict, validation_errors)  # Return stub or last attempt with errors

    return (model.model_dump(mode="json"), [])
