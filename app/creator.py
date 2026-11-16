"""«Создаватор» кампаний: кампания + 2 потока в Keitaro одним действием."""

import secrets
import string

from sqlalchemy.orm import Session

from app.config import settings
from app.editor import fetch_campaign
from app.keitaro import KeitaroClient
from app.models import Campaign


def _alias() -> str:
    """Короткий случайный идентификатор кампании в ссылке, как делает сам Keitaro."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(7))


def campaign_payload(name: str, domain_id: int, group_id: int, source_id: int) -> dict:
    return {
        "name": name,
        "alias": _alias(),
        "type": "position",  # потоки проверяются по порядку: сначала гео-фильтр, потом офферы
        "state": "active",
        "domain_id": domain_id,
        "group_id": group_id,
        "traffic_source_id": source_id,
    }


def geo_stream_payload(campaign_id: int, country: str) -> dict:
    """Поток 1: все из страны → редирект на fallback_url (Google)."""
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": f"{country} → Google",
        "position": 1,
        "state": "active",
        "action_type": "http",
        "schema": "redirect",
        "action_payload": settings.fallback_url,  # URL редиректа для action_type=http
        "filter_or": False,
        "filters": [{"name": "country", "mode": "accept", "payload": [country]}],
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    """Поток 2: все остальные → оффер."""
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Offers",
        "position": 2,
        "state": "active",
        "schema": "landings",
        "action_type": "http",
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


def create_campaign(
    session: Session,
    kt: KeitaroClient,
    *,
    name: str,
    country: str,
    offer_id: int,
    domain_id: int,
    group_id: int,
    source_id: int,
) -> Campaign:
    created = kt.create_campaign(campaign_payload(name, domain_id, group_id, source_id))
    keitaro_id = created["id"]
    kt.create_stream(geo_stream_payload(keitaro_id, country))
    kt.create_stream(offer_stream_payload(keitaro_id, offer_id))

    campaign = fetch_campaign(session, kt, keitaro_id)
    campaign.country = country
    campaign.created_by_wrapper = True
    session.commit()
    return campaign
