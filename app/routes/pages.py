"""Webbsidor: kortvyn (klientrenderad) och dokumentationsvyn (serverrenderad)."""

from pathlib import Path

import markdown
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import database as db
from app.config import BASE_DIR, SERVICE_HOST, SHARE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=["fenced_code", "tables"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/docs/{name}", response_class=HTMLResponse)
def service_docs(request: Request, name: str):
    svc = db.get_service(name)
    if svc is None:
        raise HTTPException(404, f"Ingen tjänst med namnet '{name}' är registrerad.")

    error = None
    content_html = None
    if svc.get("docs_path"):
        path = Path(svc["docs_path"])
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            error = (
                f"Dokumentationsfilen kunde inte läsas: {path}. "
                "Kontrollera att sökvägen finns och är läsbar."
            )
        else:
            if path.suffix.lower() in (".html", ".htm"):
                # HTML-dokumentation serveras som fristående sida, inte i templaten
                return HTMLResponse(text)
            content_html = _render_markdown(text)
    if content_html is None and error is None and svc.get("docs_md"):
        content_html = _render_markdown(svc["docs_md"])

    service_url = (
        f"http://{SERVICE_HOST}:{svc['port']}{svc.get('url_path') or '/'}"
        if svc.get("port") is not None
        else None
    )
    return templates.TemplateResponse(request, "docs.html", {
        "service": svc,
        "content_html": content_html,
        "error": error,
        "service_url": service_url,
    })


@router.get("/share/{uid}")
def share_root(uid: str):
    share = db.get_share(uid)
    if share is None:
        raise HTTPException(404, "Delningen finns inte eller har gått ut.")
    # Kanonisk URL med filnamn (så webbläsaren namnger nedladdningen rätt)
    return RedirectResponse(f"/share/{uid}/{share['filename']}", status_code=302)


@router.get("/share/{uid}/{filename}")
def share_file(uid: str, filename: str):
    share = db.get_share(uid)
    if share is None or share["filename"] != filename:
        raise HTTPException(404, "Delningen finns inte eller har gått ut.")
    path = SHARE_DIR / uid / share["filename"]
    if not path.is_file():
        raise HTTPException(404, "Delningens fil saknas.")
    # inline: bilder/PDF/HTML visas i webbläsaren, annat laddas ned
    return FileResponse(
        path,
        media_type=share["content_type"] or "application/octet-stream",
        content_disposition_type="inline",
    )
