import re

from pydantic import BaseModel, Field, field_validator

from app.config import settings


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(description="ISO-код страны из двух букв, например AU")
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    source_id: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def check_prefix(cls, value: str) -> str:
        value = value.strip()
        if settings.campaign_prefix and not value.startswith(settings.campaign_prefix):
            raise ValueError(f"Название должно начинаться с {settings.campaign_prefix}")
        return value

    @field_validator("country")
    @classmethod
    def check_country(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("Нужен двухбуквенный код страны, например AU")
        return value


class FetchRequest(BaseModel):
    keitaro_id: int = Field(gt=0)


class AddOffer(BaseModel):
    offer_id: int = Field(gt=0)


class PinRequest(BaseModel):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100)


class OfferOut(BaseModel):
    id: int
    offer_id: int
    offer_name: str
    status: str
    share: int
    published_share: int
    pinned: bool


class StreamOut(BaseModel):
    id: int
    keitaro_id: int
    name: str | None
    position: int
    has_offers: bool
    dirty: bool
    offers: list[OfferOut]


class CampaignOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    alias: str | None
    country: str | None
    created_by_wrapper: bool
    streams: list[StreamOut]
