"""
Architecture DSL: Pydantic models and JSON Schema for security reference architectures.
Used for validation and as the single source of truth for diagram rendering.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Zone: horizontal band (swimlane) in the diagram
# ---------------------------------------------------------------------------
class Zone(BaseModel):
    id: str = Field(..., description="Unique zone identifier")
    name: str = Field(..., description="Display name of the zone")
    order: int = Field(..., ge=0, description="Vertical order (0 = top)")
    color: str = Field(default="#dae8fc", description="Background color (hex or name)")


# ---------------------------------------------------------------------------
# Trust boundary: dashed separator between zones
# ---------------------------------------------------------------------------
class TrustBoundary(BaseModel):
    id: str = Field(..., description="Unique trust boundary identifier")
    label: str = Field(default="", description="Optional label")
    between_zones: list[str] = Field(
        default_factory=list,
        description="Zone ids that this boundary separates (ordered)",
    )


# ---------------------------------------------------------------------------
# Node: single component (app, API, data store, etc.)
# ---------------------------------------------------------------------------
NodeType = Literal[
    "app",
    "service",
    "api",
    "data_store",
    "identity",
    "security_control",
    "vendor",
    "external",
]


class Node(BaseModel):
    id: str = Field(..., description="Unique node identifier")
    label: str = Field(..., description="Display label")
    zone: str = Field(..., description="Id of the zone this node belongs to")
    type: NodeType = Field(default="app", description="Node type for shape/styling")
    tags: list[str] = Field(default_factory=list, description="Optional tags")


# ---------------------------------------------------------------------------
# Group: nested container within a zone (e.g. "Cloud Tenant", "AI Platform")
# ---------------------------------------------------------------------------
class Group(BaseModel):
    id: str = Field(..., description="Unique group identifier")
    label: str = Field(..., description="Display label")
    zone: str = Field(..., description="Id of the zone this group belongs to")
    children: list[str] = Field(
        default_factory=list,
        description="Ids of nodes or nested groups (order = layout order)",
    )


# ---------------------------------------------------------------------------
# Flow: connection between nodes (with protocol, auth, data class)
# ---------------------------------------------------------------------------
FlowType = Literal["api", "auth", "data", "log", "telemetry", "generic"]


class Flow(BaseModel):
    id: str = Field(..., description="Unique flow identifier")
    source: str = Field(..., description="Source node id")
    target: str = Field(..., description="Target node id")
    flow_type: FlowType = Field(default="generic", description="Determines line style")
    protocol: str = Field(default="", description="e.g. HTTPS, gRPC")
    auth: str = Field(default="", description="e.g. OAuth2, mTLS")
    data_class: str = Field(default="", description="e.g. PII, Public")
    label: str | None = Field(default=None, description="Override auto-generated edge label")


# ---------------------------------------------------------------------------
# Control: security control applied to node/zone/flow/group
# ---------------------------------------------------------------------------
ScopeKind = Literal["node", "zone", "flow", "group"]


class Control(BaseModel):
    id: str = Field(..., description="Unique control identifier")
    scope: list[str] = Field(
        default_factory=list,
        description="Ids of nodes/zones/flows/groups this control applies to",
    )
    control_type: str = Field(..., description="e.g. encryption, MFA, WAF")


# ---------------------------------------------------------------------------
# Root architecture document (DSL)
# ---------------------------------------------------------------------------
class ArchitectureDSL(BaseModel):
    """Root model for the architecture DSL. Legend is auto-generated at render time."""

    title: str | None = Field(default=None, description="Diagram title")
    zones: list[Zone] = Field(default_factory=list, description="Zones (swimlanes)")
    trust_boundaries: list[TrustBoundary] = Field(
        default_factory=list,
        description="Trust boundaries between zones",
    )
    groups: list[Group] = Field(default_factory=list, description="Nested group containers")
    nodes: list[Node] = Field(default_factory=list, description="Components")
    flows: list[Flow] = Field(default_factory=list, description="Data/control flows")
    controls: list[Control] = Field(default_factory=list, description="Security controls")

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# JSON Schema export for LLM / validation
# ---------------------------------------------------------------------------
def get_json_schema() -> dict[str, Any]:
    """Return JSON Schema for ArchitectureDSL (for LLM prompts and validation)."""
    return ArchitectureDSL.model_json_schema()


def validate_dsl(data: dict[str, Any]) -> tuple[ArchitectureDSL | None, list[str]]:
    """
    Validate raw dict against the DSL schema.
    Returns (ArchitectureDSL instance, list of human-friendly error messages).
    If valid, errors is empty and first element is the model.
    """
    errors: list[str] = []
    try:
        model = ArchitectureDSL.model_validate(data)
        return (model, [])
    except Exception as e:
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{loc}: {msg}")
        else:
            errors.append(str(e))
        return (None, errors)
