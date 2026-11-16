from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import creator, editor
from app.config import settings
from app.db import get_session
from app.keitaro import KeitaroClient, KeitaroError, get_keitaro
from app.models import Campaign, Stream
from app.schemas import AddOffer, CampaignCreate, CampaignOut, FetchRequest, OfferOut, PinRequest, StreamOut

app = FastAPI(title="Keitaro wrapper")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(KeitaroError)
def keitaro_error(_, exc: KeitaroError):
    return JSONResponse(status_code=502, content={"detail": f"Ошибка Keitaro ({exc.status}): {exc.message}"})


@app.exception_handler(editor.EditorError)
def editor_error(_, exc: editor.EditorError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


# ---------- сериализация ----------

def stream_out(stream: Stream) -> StreamOut:
    return StreamOut(
        id=stream.id,
        keitaro_id=stream.keitaro_id,
        name=stream.name,
        position=stream.position,
        has_offers=stream.has_offers,
        dirty=editor.stream_dirty(stream),
        offers=[
            OfferOut(
                id=l.id,
                offer_id=l.offer_id,
                offer_name=l.offer_name,
                status=l.status,
                share=l.share,
                published_share=l.published_share,
                pinned=l.pinned,
            )
            for l in stream.offers
        ],
    )


def campaign_out(campaign: Campaign) -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        keitaro_id=campaign.keitaro_id,
        name=campaign.name,
        alias=campaign.alias,
        country=campaign.country,
        created_by_wrapper=campaign.created_by_wrapper,
        streams=[stream_out(s) for s in campaign.streams],
    )


def get_campaign(session: Session, keitaro_id: int) -> Campaign:
    campaign = session.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        raise HTTPException(404, "Кампания ещё не загружена — нажмите Fetch streams")
    return campaign


def get_stream(session: Session, stream_id: int) -> Stream:
    stream = session.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(404, "Поток не найден")
    return stream


# ---------- справочники ----------

@app.get("/api/meta")
def meta(kt: KeitaroClient = Depends(get_keitaro)):
    """Домены, группы и источники для формы создания."""
    pick = lambda items: [{"id": i["id"], "name": i.get("name", "")} for i in items]  # noqa: E731
    return {
        "domains": pick(kt.domains()),
        "groups": pick(kt.campaign_groups()),
        "sources": pick(kt.traffic_sources()),
        "prefix": settings.campaign_prefix,
    }


@app.get("/api/offers")
def search_offers(q: str = "", kt: KeitaroClient = Depends(get_keitaro)):
    """Поиск оффера по ID или части названия (для выпадающего списка)."""
    q = q.strip().lower()
    found = []
    for offer in kt.offers():
        if not q or q in str(offer["id"]) or q in offer.get("name", "").lower():
            found.append({"id": offer["id"], "name": offer.get("name", "")})
    return found[:30]


# ---------- создаватор ----------

@app.post("/api/campaigns", response_model=CampaignOut)
def create_campaign(
    body: CampaignCreate, session: Session = Depends(get_session), kt: KeitaroClient = Depends(get_keitaro)
):
    campaign = creator.create_campaign(session, kt, **body.model_dump())
    return campaign_out(campaign)


# ---------- редактор ----------

@app.get("/api/campaigns")
def list_campaigns(session: Session = Depends(get_session)):
    rows = session.scalars(select(Campaign).order_by(Campaign.id.desc())).all()
    return [{"keitaro_id": c.keitaro_id, "name": c.name, "country": c.country} for c in rows]


@app.post("/api/campaigns/fetch", response_model=CampaignOut)
def fetch(body: FetchRequest, session: Session = Depends(get_session), kt: KeitaroClient = Depends(get_keitaro)):
    return campaign_out(editor.fetch_campaign(session, kt, body.keitaro_id))


@app.get("/api/campaigns/{keitaro_id}", response_model=CampaignOut)
def campaign_detail(keitaro_id: int, session: Session = Depends(get_session)):
    return campaign_out(get_campaign(session, keitaro_id))


@app.post("/api/streams/{stream_id}/offers", response_model=StreamOut)
def add_offer(
    stream_id: int, body: AddOffer, session: Session = Depends(get_session), kt: KeitaroClient = Depends(get_keitaro)
):
    stream = get_stream(session, stream_id)
    name = next((o.get("name", "") for o in kt.offers() if o["id"] == body.offer_id), None)
    if name is None:
        raise HTTPException(404, f"Оффер #{body.offer_id} не найден в Keitaro")
    editor.add_offer(session, stream, body.offer_id, name)
    return stream_out(stream)


@app.post("/api/stream-offers/{link_id}/remove", response_model=StreamOut)
def remove_offer(link_id: int, session: Session = Depends(get_session)):
    return stream_out(editor.remove_offer(session, link_id))


@app.post("/api/stream-offers/{link_id}/bring-back", response_model=StreamOut)
def bring_back(link_id: int, session: Session = Depends(get_session)):
    return stream_out(editor.bring_back(session, link_id))


@app.post("/api/stream-offers/{link_id}/pin", response_model=StreamOut)
def pin(link_id: int, body: PinRequest, session: Session = Depends(get_session)):
    return stream_out(editor.set_pin(session, link_id, body.pinned, body.share))


@app.post("/api/streams/{stream_id}/push", response_model=StreamOut)
def push(stream_id: int, session: Session = Depends(get_session), kt: KeitaroClient = Depends(get_keitaro)):
    stream = get_stream(session, stream_id)
    editor.push(session, kt, stream)
    return stream_out(stream)


@app.post("/api/streams/{stream_id}/cancel", response_model=StreamOut)
def cancel(stream_id: int, session: Session = Depends(get_session)):
    stream = get_stream(session, stream_id)
    editor.cancel(session, stream)
    return stream_out(stream)

