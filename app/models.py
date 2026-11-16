from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Campaign(Base):
    """Кампания Keitaro, с которой работала обёртка."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(2))  # заполнено, если создана обёрткой
    created_by_wrapper: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    """Поток кампании. Потоки без офферов храним только как «есть такой поток»."""

    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.id"
    )


class StreamOffer(Base):
    """Привязка оффера к потоку.

    Два флага описывают состояние:
      included  — оффер должен быть в потоке (то, что хочет пользователь);
      published — оффер сейчас есть в потоке в Keitaro.

      included + published         → активный
      included + не published      → добавлен, ждёт публикации
      не included + published      → удалён, ждёт публикации
      не included + не published   → в архиве (можно вернуть)
    """

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(Integer)  # ID оффера в Keitaro
    offer_name: Mapped[str] = mapped_column(String(255), default="")

    included: Mapped[bool] = mapped_column(Boolean, default=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    # Был ли оффер хоть раз опубликован. Если нет, то при «Отмене» запись удаляется целиком.
    ever_published: Mapped[bool] = mapped_column(Boolean, default=False)

    share: Mapped[int] = mapped_column(Integer, default=0)  # вес в обёртке, %
    published_share: Mapped[int] = mapped_column(Integer, default=0)  # вес в Keitaro, %
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[Stream] = relationship(back_populates="offers")

    @property
    def status(self) -> str:
        if self.included and self.published:
            return "active"
        if self.included:
            return "pending_add"
        if self.published:
            return "pending_remove"
        return "removed"
