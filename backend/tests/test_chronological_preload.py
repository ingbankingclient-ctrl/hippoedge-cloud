import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import main
from app.models import AnalysisSnapshot, Meeting, Race, Runner


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _runner(number: int):
    return Runner(
        number=number,
        horse_name=f"HORSE {number}",
        raw={
            "history_status": "ok",
            "history_enrichment_version": main.HISTORY_ENRICHMENT_VERSION,
            "history_checked_at": datetime.now().isoformat(),
            "pmu_opponent_enrichment_version": main.PMU_OPPONENT_ENRICHMENT_VERSION,
        },
    )


@pytest.mark.asyncio
async def test_prepares_pending_races_in_start_time_order_and_skips_started(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(main, "SessionLocal", Session)
    db = Session()
    day = date.today()
    meeting = Meeting(race_date=day, code="R1", track="Test")
    now = datetime.now()
    # Insert out of chronological order on purpose.
    r3 = Race(meeting=meeting, code="R1C3", name="Third", scheduled_at=now + timedelta(hours=3), discipline="Plat", runners=[_runner(3)])
    r1 = Race(meeting=meeting, code="R1C1", name="First", scheduled_at=now + timedelta(hours=1), discipline="Plat", runners=[_runner(1)])
    r2 = Race(meeting=meeting, code="R1C2", name="Second", scheduled_at=now + timedelta(hours=2), discipline="Plat", runners=[_runner(2)])
    missed = Race(meeting=meeting, code="R1C0", name="Missed", scheduled_at=now - timedelta(minutes=5), discipline="Plat", runners=[_runner(9)])
    db.add(meeting)
    db.commit()
    ids = {race.code: race.id for race in (r1, r2, r3, missed)}
    db.close()

    calls = []

    async def fake_prepare(race_id, write_lock, provider, request=None):
        calls.append(race_id)
        return object()

    monkeypatch.setattr(main, "_prepare_race_analysis", fake_prepare)
    result = await main._prepare_day_chronological(day, asyncio.Lock(), provider=object())

    assert calls == [ids["R1C1"], ids["R1C2"], ids["R1C3"]]
    assert ids["R1C0"] in result["skipped_started"]


@pytest.mark.asyncio
async def test_ready_race_is_not_reprocessed_until_profile_refresh_due(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(main, "SessionLocal", Session)
    db = Session()
    day = date.today()
    race = Race(
        meeting=Meeting(race_date=day, code="R1", track="Test"),
        code="R1C1",
        name="Ready",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        runners=[_runner(1)],
    )
    db.add(race)
    db.flush()
    db.add(AnalysisSnapshot(
        race_id=race.id,
        generated_at=datetime.now(),
        methodology_version=main.settings.methodology_version,
        data_hash="ready",
        summary={"snapshot_phase": "pre_race", "card_signature": main._race_card_signature(race)},
    ))
    db.commit()
    race_id = race.id
    db.close()

    calls = []

    async def fake_prepare(race_id, write_lock, provider, request=None):
        calls.append(race_id)
        return object()

    monkeypatch.setattr(main, "_prepare_race_analysis", fake_prepare)
    await main._prepare_day_chronological(day, asyncio.Lock(), provider=object())
    assert calls == []

    db = Session()
    runner = db.query(Runner).filter_by(race_id=race_id).one()
    runner.raw = {**runner.raw, "history_checked_at": (datetime.now() - timedelta(hours=2)).isoformat()}
    db.commit()
    db.close()

    await main._prepare_day_chronological(day, asyncio.Lock(), provider=object())
    assert calls == [race_id]


@pytest.mark.asyncio
async def test_preload_loop_always_traverses_today_before_tomorrow(monkeypatch):
    calls = []
    stop = asyncio.Event()
    today = date.today()

    async def fake_day(day, write_lock):
        calls.append(day)
        if len(calls) == 2:
            stop.set()

    monkeypatch.setattr(main, "_prepare_day_chronological_safe", fake_day)
    monkeypatch.setattr(main.settings, "preload_enabled", True)

    # Avoid the five-second cold-start delay.
    original_wait_for = asyncio.wait_for
    counter = {"n": 0}

    async def fast_wait_for(awaitable, timeout):
        counter["n"] += 1
        if counter["n"] == 1:
            awaitable.close() if hasattr(awaitable, "close") else None
            raise asyncio.TimeoutError()
        return await original_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(main.asyncio, "wait_for", fast_wait_for)
    await main.preload_loop(stop, asyncio.Lock())
    assert calls[:2] == [today, today + timedelta(days=1)]


def test_dashboard_exposes_per_race_readiness(monkeypatch):
    Session = _session_factory()
    db = Session()
    day = date.today()
    meeting = Meeting(race_date=day, code="R1", track="Test")
    ready = Race(meeting=meeting, code="R1C1", name="Ready", scheduled_at=datetime.now() + timedelta(hours=1), discipline="Plat", runners=[_runner(1)])
    pending = Race(meeting=meeting, code="R1C2", name="Pending", scheduled_at=datetime.now() + timedelta(hours=2), discipline="Plat", runners=[_runner(2)])
    db.add(meeting)
    db.flush()
    db.add(AnalysisSnapshot(
        race_id=ready.id,
        generated_at=datetime.now(),
        methodology_version=main.settings.methodology_version,
        data_hash="ready",
        summary={"snapshot_phase": "pre_race"},
    ))
    db.commit()

    dashboard = main.day_dashboard(day, db)
    assert ready.id in dashboard["ready_race_ids"]
    assert pending.id in dashboard["pending_race_ids"]
    assert dashboard["activity"]["courses_analyzed"] == 1
    assert dashboard["activity"]["courses_updating"] == 1
    assert dashboard["next_pending_race"]["race_id"] == pending.id
    db.close()


@pytest.mark.asyncio
async def test_ready_race_is_recomputed_when_official_card_changes(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(main, "SessionLocal", Session)
    db = Session()
    day = date.today()
    race = Race(
        meeting=Meeting(race_date=day, code="R1", track="Test"),
        code="R1C1",
        name="Card change",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        runners=[_runner(1), _runner(2)],
    )
    db.add(race)
    db.flush()
    db.add(AnalysisSnapshot(
        race_id=race.id,
        generated_at=datetime.now(),
        methodology_version=main.settings.methodology_version,
        data_hash="ready",
        summary={"snapshot_phase": "pre_race", "card_signature": main._race_card_signature(race)},
    ))
    db.commit()
    race_id = race.id
    runner2_id = race.runners[1].id
    db.close()

    db = Session()
    runner2 = db.get(Runner, runner2_id)
    runner2.scratched = True
    db.commit()
    db.close()

    calls = []
    async def fake_prepare(race_id, write_lock, provider, request=None):
        calls.append(race_id)
        return object()
    monkeypatch.setattr(main, "_prepare_race_analysis", fake_prepare)

    await main._prepare_day_chronological(day, asyncio.Lock(), provider=object())
    assert calls == [race_id]


def test_light_queue_endpoint_reports_each_race_independently():
    Session = _session_factory()
    db = Session()
    day = date.today()
    meeting = Meeting(race_date=day, code="R1", track="Queue")
    r1 = Race(meeting=meeting, code="R1C1", name="Ready", scheduled_at=datetime.now() + timedelta(hours=1), discipline="Plat", runners=[_runner(1)])
    r2 = Race(meeting=meeting, code="R1C2", name="Waiting", scheduled_at=datetime.now() + timedelta(hours=2), discipline="Plat", runners=[_runner(2)])
    db.add(meeting)
    db.flush()
    db.add(AnalysisSnapshot(
        race_id=r1.id,
        generated_at=datetime.now(),
        methodology_version=main.settings.methodology_version,
        data_hash="ready",
        summary={"snapshot_phase": "pre_race"},
    ))
    db.commit()

    queue = main.day_queue(day, db)
    assert queue["courses_analyzed"] == 1
    assert queue["courses_updating"] == 1
    assert queue["ready_race_ids"] == [r1.id]
    assert queue["pending_race_ids"] == [r2.id]
    assert queue["next_pending_race"]["race_id"] == r2.id
    db.close()
