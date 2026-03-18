"""
dashboard/app.py

FastAPI dashboard — local web UI for viewing application history.
Launch: python main.py --ui
"""
import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from agent import application_tracker

logger = logging.getLogger(__name__)

app = FastAPI(title="Job Application Agent Dashboard")

_DASHBOARD_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_DASHBOARD_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_DASHBOARD_DIR / "templates"))

application_tracker.init_db()


def _load_evidence(job_id: str) -> dict[str, Any]:
    """Load evidence folder data for a given job_id."""
    row = application_tracker.get_application(job_id)
    if not row:
        return {}

    evidence_dir = row.get("evidence_folder")
    result: dict[str, Any] = dict(row)
    result["cover_letter"] = ""
    result["job_description"] = ""
    result["company_research"] = ""
    result["form_fields"] = []
    result["screenshots"] = []

    if not evidence_dir:
        return result

    folder = Path(evidence_dir)
    if not folder.exists():
        return result

    cl_path = folder / "cover_letter.md"
    if cl_path.exists():
        result["cover_letter"] = cl_path.read_text(encoding="utf-8")

    jd_path = folder / "job_description.txt"
    if jd_path.exists():
        result["job_description"] = jd_path.read_text(encoding="utf-8")

    cr_path = folder / "company_research.txt"
    if cr_path.exists():
        result["company_research"] = cr_path.read_text(encoding="utf-8")

    fd_path = folder / "form_data.json"
    if fd_path.exists():
        try:
            fd = json.loads(fd_path.read_text())
            result["form_fields"] = fd.get("fields", [])
        except Exception:
            pass

    screenshots_dir = folder / "screenshots"
    if screenshots_dir.exists():
        result["screenshots"] = [
            f"/screenshots/{p.relative_to(config.APPLICATIONS_DIR)}"
            for p in sorted(screenshots_dir.glob("*.png"))
        ]

    return result


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    status: str = "",
    search: str = "",
    sort: str = "applied_at",
):
    db_stats = application_tracker.stats()
    rows = application_tracker.list_applications(status=status or None, limit=500)

    if search:
        q = search.lower()
        rows = [r for r in rows if q in (r.get("company") or "").lower()
                or q in (r.get("job_title") or "").lower()]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "rows": rows,
        "stats": db_stats,
        "current_status": status,
        "current_search": search,
    })


@app.get("/application/{job_id}", response_class=HTMLResponse)
async def application_detail(request: Request, job_id: str):
    data = _load_evidence(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Application not found")
    return templates.TemplateResponse("detail.html", {"request": request, "app": data})


@app.get("/api/applications")
async def api_applications(status: str = "", limit: int = 500):
    return application_tracker.list_applications(status=status or None, limit=limit)


@app.get("/api/application/{job_id}")
async def api_application_detail(job_id: str):
    data = _load_evidence(job_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return data


@app.get("/screenshots/{path:path}")
async def serve_screenshot(path: str):
    full_path = config.APPLICATIONS_DIR / path
    if not full_path.exists() or not full_path.suffix.lower() == ".png":
        raise HTTPException(status_code=404)
    return FileResponse(str(full_path), media_type="image/png")


@app.get("/export/csv")
async def export_csv_endpoint():
    rows = application_tracker.list_applications(limit=10000)
    if not rows:
        return StreamingResponse(
            io.StringIO("No applications found.\n"),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=applications.csv"},
        )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )
