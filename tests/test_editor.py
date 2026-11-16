"""Сценарии из видео с редактором, проверенные на фейковом Keitaro."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_session
from app.keitaro import get_keitaro
from app.main import app
from app.weights import distribute


class FakeKeitaro:
    """Хранит кампании и потоки в памяти, как это делал бы Keitaro."""

    def __init__(self):
        self.offers_list = [{"id": i, "name": f"Offer {i}"} for i in range(1, 8)]
        self.campaigns = {}
        self.stream_store = {}
        self.next_id = 100

    def _id(self):
        self.next_id += 1
        return self.next_id

    def domains(self):
        return [{"id": 1, "name": "https://in.example.xyz/"}]

    def campaign_groups(self):
        return [{"id": 2, "name": "FORTESTS"}]

    def traffic_sources(self):
        return [{"id": 3, "name": "FORTESTS"}]

    def offers(self):
        return self.offers_list

    def campaign(self, cid):
        return self.campaigns[cid]

    def create_campaign(self, payload):
        cid = self._id()
        self.campaigns[cid] = {"id": cid, **payload}
        return self.campaigns[cid]

    def streams(self, cid):
        return [s for s in self.stream_store.values() if s["campaign_id"] == cid]

    def create_stream(self, payload):
        sid = self._id()
        self.stream_store[sid] = {"id": sid, "offers": [], **payload}
        return self.stream_store[sid]

    def update_stream(self, sid, payload):
        self.stream_store[sid].update(payload)
        return self.stream_store[sid]


@pytest.fixture
def ctx(monkeypatch):
    # Префикс из .env разработчика не должен влиять на тесты
    monkeypatch.setattr(settings, "campaign_prefix", "")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    kt = FakeKeitaro()
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_keitaro] = lambda: kt
    yield TestClient(app), kt
    app.dependency_overrides.clear()


def create(client):
    r = client.post(
        "/api/campaigns",
        json={"name": "test_x_c1", "country": "au", "offer_id": 1, "domain_id": 1, "group_id": 2, "source_id": 3},
    )
    assert r.status_code == 200, r.text
    return r.json()


def offer_stream(campaign):
    return next(s for s in campaign["streams"] if s["has_offers"])


def shares(stream):
    return {o["offer_id"]: (o["share"], o["status"]) for o in stream["offers"]}


def test_distribute():
    assert distribute([], 3) == [34, 33, 33]
    assert distribute([25], 2) == [38, 37]
    assert distribute([], 4) == [25, 25, 25, 25]
    assert distribute([60, 50], 1) == [0]


def test_creator_builds_two_streams(ctx):
    client, kt = ctx
    c = create(client)
    geo, offers = sorted(kt.streams(c["keitaro_id"]), key=lambda s: s["position"])
    assert geo["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU"]}]
    assert geo["action_payload"] == "https://google.com"
    assert offers["offers"] == [{"offer_id": 1, "share": 100, "state": "active"}]
    camp = kt.campaigns[c["keitaro_id"]]
    assert (camp["domain_id"], camp["group_id"], camp["traffic_source_id"]) == (1, 2, 3)
    # поток без офферов показывается просто как поток
    geo_out = next(s for s in c["streams"] if not s["has_offers"])
    assert geo_out["offers"] == []


def test_add_push_cancel(ctx):
    client, kt = ctx
    c = create(client)
    s = offer_stream(c)

    for oid in (2, 3):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": oid}).json()
    assert {k: v[0] for k, v in shares(s).items()} == {1: 34, 2: 33, 3: 33}
    assert s["dirty"] is True
    # в Keitaro пока только один оффер
    assert len(kt.stream_store[s["keitaro_id"]]["offers"]) == 1

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert s["dirty"] is False
    assert sorted(o["share"] for o in kt.stream_store[s["keitaro_id"]]["offers"]) == [33, 33, 34]

    # добавили и отменили — оффер исчезает из базы, веса возвращаются
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 4}).json()
    assert {k: v[0] for k, v in shares(s).items()} == {1: 25, 2: 25, 3: 25, 4: 25}
    s = client.post(f"/api/streams/{s['id']}/cancel").json()
    assert 4 not in shares(s)
    assert s["dirty"] is False
    assert {k: v[0] for k, v in shares(s).items()} == {1: 34, 2: 33, 3: 33}


def test_remove_and_bring_back(ctx):
    client, kt = ctx
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 2}).json()
    s = client.post(f"/api/streams/{s['id']}/push").json()

    link = next(o for o in s["offers"] if o["offer_id"] == 2)
    s = client.post(f"/api/stream-offers/{link['id']}/remove").json()
    assert shares(s)[2] == (0, "pending_remove")
    assert shares(s)[1] == (100, "active")
    assert s["dirty"] is True

    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert shares(s)[2] == (0, "removed")
    assert [o["offer_id"] for o in kt.stream_store[s["keitaro_id"]]["offers"]] == [1]

    s = client.post(f"/api/stream-offers/{link['id']}/bring-back").json()
    assert shares(s)[2] == (50, "pending_add")
    s = client.post(f"/api/streams/{s['id']}/push").json()
    assert shares(s)[2] == (50, "active")
    assert len(kt.stream_store[s["keitaro_id"]]["offers"]) == 2


def test_removed_in_keitaro_goes_to_archive(ctx):
    client, kt = ctx
    c = create(client)
    s = offer_stream(c)
    for oid in (2, 3):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": oid}).json()
    client.post(f"/api/streams/{s['id']}/push")

    # кто-то удалил оффер 3 прямо в Keitaro
    raw = kt.stream_store[s["keitaro_id"]]
    raw["offers"] = [o for o in raw["offers"] if o["offer_id"] != 3]

    c = client.post("/api/campaigns/fetch", json={"keitaro_id": c["keitaro_id"]}).json()
    s = offer_stream(c)
    assert shares(s)[3] == (0, "removed")
    assert s["dirty"] is False


def test_pinned_share_survives(ctx):
    client, kt = ctx
    s = offer_stream(create(client))
    for oid in (2, 3, 4):
        s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": oid}).json()
    first = next(o for o in s["offers"] if o["offer_id"] == 1)
    s = client.post(f"/api/stream-offers/{first['id']}/pin", json={"pinned": True}).json()
    assert shares(s)[1][0] == 25

    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 5}).json()
    got = {k: v[0] for k, v in shares(s).items()}
    assert got[1] == 25
    assert sum(got.values()) == 100
    assert sorted(got[k] for k in (2, 3, 4, 5)) == [18, 19, 19, 19]

    client.post(f"/api/streams/{s['id']}/push")
    pushed = {o["offer_id"]: o["share"] for o in kt.stream_store[s["keitaro_id"]]["offers"]}
    assert pushed[1] == 25 and sum(pushed.values()) == 100


def test_pin_over_100_rejected(ctx):
    client, _ = ctx
    s = offer_stream(create(client))
    s = client.post(f"/api/streams/{s['id']}/offers", json={"offer_id": 2}).json()
    a, b = s["offers"]
    client.post(f"/api/stream-offers/{a['id']}/pin", json={"pinned": True, "share": 70})
    r = client.post(f"/api/stream-offers/{b['id']}/pin", json={"pinned": True, "share": 40})
    assert r.status_code == 400


def test_bad_country(ctx):
    client, _ = ctx
    r = client.post(
        "/api/campaigns",
        json={"name": "test_x", "country": "Australia", "offer_id": 1, "domain_id": 1, "group_id": 2, "source_id": 3},
    )
    assert r.status_code == 422
