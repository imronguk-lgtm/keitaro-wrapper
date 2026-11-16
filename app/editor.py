"""Логика редактора офферов: синхронизация с Keitaro, правки, публикация."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.keitaro import KeitaroClient
from app.models import Campaign, Stream, StreamOffer
from app.weights import recalc


class EditorError(Exception):
    pass


def stream_dirty(stream: Stream) -> bool:
    """Есть ли в потоке неопубликованные изменения (поток «жёлтый»)."""
    for link in stream.offers:
        if link.included != link.published:
            return True
        if link.included and link.share != link.published_share:
            return True
    return False


# ---------- загрузка из Keitaro ----------

def fetch_campaign(session: Session, kt: KeitaroClient, keitaro_id: int) -> Campaign:
    """Fetch streams: подтянуть кампанию и потоки из Keitaro.

    Keitaro считается источником правды: локальные неопубликованные правки
    сбрасываются, а офферы, которые знала обёртка, но которых больше нет
    в Keitaro, уходят в архив (статус removed), а не удаляются.
    """
    data = kt.campaign(keitaro_id)
    campaign = session.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_id)
        session.add(campaign)
    campaign.name = data.get("name", "")
    campaign.alias = data.get("alias")
    campaign.fetched_at = datetime.now()
    session.flush()

    offer_names = {o["id"]: o.get("name", "") for o in kt.offers()}
    seen_streams = set()

    for raw in kt.streams(keitaro_id):
        seen_streams.add(raw["id"])
        stream = session.scalar(select(Stream).where(Stream.keitaro_id == raw["id"]))
        if stream is None:
            stream = Stream(keitaro_id=raw["id"], campaign=campaign)
            session.add(stream)
        stream.name = raw.get("name")
        stream.position = raw.get("position") or 0

        raw_offers = {o["offer_id"]: o for o in (raw.get("offers") or [])}
        stream.has_offers = bool(raw_offers) or bool(stream.offers)
        session.flush()

        existing = {link.offer_id: link for link in stream.offers}
        for offer_id, raw_offer in raw_offers.items():
            link = existing.get(offer_id)
            if link is None:
                link = StreamOffer(stream=stream, offer_id=offer_id)
                session.add(link)
            link.offer_name = offer_names.get(offer_id, link.offer_name or f"#{offer_id}")
            link.included = link.published = link.ever_published = True
            link.share = link.published_share = int(raw_offer.get("share") or 0)

        for offer_id, link in existing.items():
            if offer_id in raw_offers:
                continue
            if link.ever_published:
                # Был в Keitaro, теперь нет → в архив
                link.included = link.published = False
                link.share = link.published_share = 0
            else:
                # Добавлен в обёртке и не опубликован → правка сбрасывается
                session.delete(link)

    # Потоки, удалённые в Keitaro, удаляем и у себя
    for stream in list(campaign.streams):
        if stream.keitaro_id not in seen_streams:
            session.delete(stream)

    session.commit()
    session.refresh(campaign)
    return campaign


# ---------- правки в обёртке (без обращения к Keitaro) ----------

def _get_link(session: Session, link_id: int) -> StreamOffer:
    link = session.get(StreamOffer, link_id)
    if link is None:
        raise EditorError("Привязка оффера не найдена")
    return link


def add_offer(session: Session, stream: Stream, offer_id: int, offer_name: str) -> StreamOffer:
    link = next((l for l in stream.offers if l.offer_id == offer_id), None)
    if link is not None and link.included:
        raise EditorError("Этот оффер уже есть в потоке")
    if link is None:
        # stream=stream сам добавляет привязку в stream.offers
        link = StreamOffer(stream=stream, offer_id=offer_id, offer_name=offer_name, included=True)
        session.add(link)
    else:
        link.included = True  # оффер из архива → «вернуть»
    stream.has_offers = True
    recalc(stream.offers)
    session.commit()
    return link


def remove_offer(session: Session, link_id: int) -> Stream:
    link = _get_link(session, link_id)
    stream = link.stream
    if not link.included:
        raise EditorError("Оффер уже удалён")
    if not link.ever_published:
        session.delete(link)  # ещё ни разу не публиковали — просто убираем
        stream.offers.remove(link)
    else:
        link.included = False
        link.pinned = False
    recalc(stream.offers)
    session.commit()
    return stream


def bring_back(session: Session, link_id: int) -> Stream:
    link = _get_link(session, link_id)
    if link.included:
        raise EditorError("Оффер и так в потоке")
    link.included = True
    recalc(link.stream.offers)
    session.commit()
    return link.stream


def set_pin(session: Session, link_id: int, pinned: bool, share: int | None) -> Stream:
    link = _get_link(session, link_id)
    if not link.included:
        raise EditorError("Закрепить можно только оффер, который есть в потоке")
    if pinned:
        new_share = link.share if share is None else share
        others = sum(l.share for l in link.stream.offers if l.included and l.pinned and l.id != link.id)
        if not 0 <= new_share <= 100 or others + new_share > 100:
            raise EditorError("Сумма закреплённых весов не может быть больше 100%")
        link.share = new_share
    link.pinned = pinned
    recalc(link.stream.offers)
    session.commit()
    return link.stream


def cancel(session: Session, stream: Stream) -> None:
    """Отменить неопубликованные изменения потока."""
    for link in list(stream.offers):
        if not link.ever_published:
            session.delete(link)
            stream.offers.remove(link)
            continue
        link.included = link.published
        link.share = link.published_share
    session.commit()


# ---------- публикация ----------

def push(session: Session, kt: KeitaroClient, stream: Stream) -> None:
    """Отправить офферы потока в Keitaro."""
    included = [l for l in stream.offers if l.included]
    if included and sum(l.share for l in included) != 100:
        raise EditorError("Сумма весов должна быть 100%")
    payload = {
        "offers": [{"offer_id": l.offer_id, "share": l.share, "state": "active"} for l in included]
    }
    kt.update_stream(stream.keitaro_id, payload)

    for link in stream.offers:
        link.published = link.included
        link.published_share = link.share if link.included else 0
        if link.included:
            link.ever_published = True
    session.commit()
