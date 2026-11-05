"""JSON-API för modelljobb (/api/modelljobb/...).

Klientkontraktet är `PUT /api/modelljobb/{uuid}` med hela jobbets läge och
`POST /api/modelljobb/{uuid}/preview` för ett svar att visa. Sidan läser
`GET /api/modelljobb`.
"""

import base64
import binascii
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app import modelljobb

router = APIRouter(prefix="/api/modelljobb")


class SparIn(BaseModel):
    modell: str = Field(min_length=1, max_length=120)
    klara: int = Field(0, ge=0)
    totalt: int | None = Field(None, ge=0)
    fran: int = Field(0, ge=0)
    start: float | None = None
    slut: float | None = None
    # Spårets egen prompt, när den skiljer sig från jobbets.
    prompt: str | None = Field(None, max_length=modelljobb.PROMPT_MAX)
    # Klient VERSION 2: pågående anrop och summerade siffror från modellen.
    anrop_start: float | None = None
    anrop_rubrik: str | None = Field(None, max_length=200)
    tokens: int | None = Field(None, ge=0)
    eval_s: float | None = Field(None, ge=0)
    avklippta: int = Field(0, ge=0)


class FelIn(BaseModel):
    text: str = Field(max_length=300)
    modell: str | None = Field(None, max_length=120)
    tid: float | None = None


class AktuellIn(BaseModel):
    modell: str | None = Field(None, max_length=120)
    rubrik: str | None = Field(None, max_length=200)


class JobbIn(BaseModel):
    beskrivning: str = Field(min_length=1, max_length=200)
    projekt: str | None = Field(None, max_length=80)
    agare: str | None = Field(None, max_length=80)
    endpoint: str | None = Field(None, max_length=300)
    host: str | None = Field(None, max_length=80)
    pid: int | None = None
    version: str | None = Field(None, max_length=20)
    start: float | None = None
    skickad: float | None = None
    klar: bool = False
    # False stänger av ntfy-notiserna för just det här jobbet.
    notis: bool = True
    prompt: str | None = Field(None, max_length=modelljobb.PROMPT_MAX)
    spar: list[SparIn] = Field(default_factory=list, max_length=20)
    fel: list[FelIn] = Field(default_factory=list, max_length=50)
    aktuell: AktuellIn | None = None


class DelIn(BaseModel):
    text: str | None = None
    bild_base64: str | None = Field(None, max_length=280_000)


class MetaIn(BaseModel):
    """Modellens egna siffror för ett svar, t.ex. ur ollamas /api/chat."""
    tokens: int | None = Field(None, ge=0)
    tok_per_s: float | None = Field(None, ge=0)
    total_s: float | None = Field(None, ge=0)
    done_reason: str | None = Field(None, max_length=40)


class PreviewIn(BaseModel):
    spar: str = Field(min_length=1, max_length=120)
    rubrik: str = Field(min_length=1, max_length=200)
    indata: DelIn | None = None
    svar: DelIn | None = None
    format: Literal["text", "json"] = "text"
    jamfor: bool = False
    meta: MetaIn | None = None


@router.get("")
def lista():
    return modelljobb.lista()


@router.get("/klient.py", response_class=PlainTextResponse)
def klient():
    """Klientmodulen, att hämta in i ett projekt med curl."""
    return PlainTextResponse(
        modelljobb.KLIENT.read_text(encoding="utf-8"), media_type="text/x-python; charset=utf-8"
    )


@router.put("/{uuid}")
def spara(uuid: str, payload: JobbIn):
    try:
        return modelljobb.spara(uuid, payload.model_dump())
    except modelljobb.JobbFel as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{uuid}")
def hamta(uuid: str):
    try:
        jobb = modelljobb.hamta(uuid)
    except modelljobb.JobbFel as exc:
        raise HTTPException(400, str(exc)) from exc
    if jobb is None:
        raise HTTPException(404, "Jobbet finns inte.")
    return jobb


@router.delete("/{uuid}")
def ta_bort(uuid: str):
    try:
        if not modelljobb.ta_bort(uuid):
            raise HTTPException(404, "Jobbet finns inte.")
    except modelljobb.JobbFel as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "borttaget", "uuid": uuid}


@router.post("/{uuid}/preview")
def lagg_till_preview(uuid: str, payload: PreviewIn):
    delar = {}
    for namn in modelljobb.DELAR:
        del_ = getattr(payload, namn)
        if del_ is None:
            continue
        bild = None
        if del_.bild_base64:
            try:
                bild = base64.b64decode(del_.bild_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(400, f"Bilden i {namn} är inte giltig base64.") from exc
        delar[namn] = {"text": del_.text, "bild": bild}
    try:
        return modelljobb.lagg_till_preview(
            uuid, payload.spar, payload.rubrik, delar, payload.format, payload.jamfor,
            payload.meta.model_dump(exclude_none=True) if payload.meta else None,
        )
    except modelljobb.JobbFel as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, "Jobbet finns inte. Skicka jobbets läge med PUT först.") from exc


@router.get("/{uuid}/preview/{preview_id}/{del_}")
def preview_bild(uuid: str, preview_id: int, del_: Literal["indata", "svar"]):
    try:
        traff = modelljobb.preview_bild(uuid, preview_id, del_)
    except modelljobb.JobbFel as exc:
        raise HTTPException(400, str(exc)) from exc
    if traff is None:
        raise HTTPException(404, "Bilden finns inte.")
    data, typ = traff
    # Bilderna kommer från vilken klient som helst och serveras från portalens
    # eget ursprung, så webbläsaren får inte gissa typ.
    return Response(data, media_type=typ, headers={
        "X-Content-Type-Options": "nosniff",
        # En preview ändras aldrig under sitt id, så webbläsaren får spara den.
        "Cache-Control": "private, max-age=86400, immutable",
    })
