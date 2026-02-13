"""
FastAPI app: text → DSL → draw.io download.
Single-page UI + POST /generate returns .drawio file.
"""

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.dsl_to_drawio import dsl_to_drawio
from app.text_to_dsl import text_to_dsl

app = FastAPI(title="Security Reference Architecture Diagram Generator")

# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    text: str = Field(default="", description="Architecture description")
    profile: str = Field(default="Generic Security Reference", description="Diagram profile")
    detail_level: str = Field(default="standard", description="lite | standard | threat-model")
    use_llm: bool | None = Field(default=None, description="True=force LLM, False=stub only, None=auto")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the single-page frontend."""
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader
    templates_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)))
    template = env.get_template("index.html")
    return template.render()


@app.post("/api/generate")
async def generate(req: GenerateRequest) -> Response:
    """
    Generate .drawio from text.
    Returns draw.io XML as file download, or 422 with validation errors.
    """
    dsl_dict, errors = text_to_dsl(
        text=req.text,
        profile=req.profile,
        detail_level=req.detail_level,
        use_llm=req.use_llm,
    )
    if not dsl_dict:
        raise HTTPException(status_code=422, detail={"errors": errors or ["Failed to produce DSL."]})
    if errors:
        # Still return diagram (e.g. stub) but include warnings
        pass
    try:
        xml = dsl_to_drawio(dsl_dict)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"errors": [str(e)]})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"errors": [str(e)]})
    filename = "security_architecture.drawio"
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/sample")
async def sample_input() -> dict[str, Any]:
    """Return sample input text for the frontend (load sample button)."""
    sample_path = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_input.txt")
    try:
        with open(sample_path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = (
            "Generic security reference: users on the internet access an API gateway in the DMZ. "
            "The gateway talks to identity provider for auth and to internal application services. "
            "Applications use a database. WAF and TLS are in place."
        )
    return {"text": text}


@app.get("/api/health")
async def health():
    return {"status": "ok"}
