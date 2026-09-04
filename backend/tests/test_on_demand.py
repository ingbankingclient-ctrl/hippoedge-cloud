import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import _enrich_race_histories_on_demand
from app.models import HorseHistory, Meeting, Race, Runner


def test_on_demand_history_fetches_only_clicked_race():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    day = date.today() + timedelta(days=1)
    db = Session()
    meeting = Meeting(race_date=day, code="R1", track="Test")
    first = Race(
        meeting=meeting,
        code="R1C1",
        name="Course 1",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        distance_m=2000,
    )
    first.runners = [Runner(number=1, horse_name="ALPHA", horse_external_id="alpha")]
    second = Race(
        meeting=meeting,
        code="R1C2",
        name="Course 2",
        scheduled_at=datetime.now() + timedelta(hours=3),
        discipline="Plat",
        distance_m=1800,
    )
    second.runners = [Runner(number=1, horse_name="BETA", horse_external_id="beta")]
    db.add_all([first, second])
    db.commit()
    first_id = first.id
    second_id = second.id
    db.close()

    class Provider:
        def __init__(self):
            self.calls = []

        async def get_horse_history(self, horse_id, discipline=None, horse_name=None, race_date=None):
            self.calls.append(horse_name)
            return {
                "data": {"historique": [{
                    "date": (day - timedelta(days=10)).isoformat(),
                    "hippodrome": "Ancien",
                    "distance": 2000,
                    "position": 2,
                }]},
                "meta": {"source": "Test", "status": "ok"},
            }

    provider = Provider()
    with patch("app.main.SessionLocal", Session):
        asyncio.run(_enrich_race_histories_on_demand(first_id, asyncio.Lock(), provider))

    assert provider.calls == ["ALPHA"]
    check = Session()
    first_runner = check.scalar(
        select(Runner).where(Runner.race_id == first_id).options(selectinload(Runner.history))
    )
    second_runner = check.scalar(
        select(Runner).where(Runner.race_id == second_id).options(selectinload(Runner.history))
    )
    assert first_runner is not None and len(first_runner.history) == 1
    assert second_runner is not None and len(second_runner.history) == 0
    check.close()


def test_persistent_historical_course_cache_reuses_one_download_across_current_races():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    day = date.today() + timedelta(days=1)
    db = Session()
    meeting = Meeting(race_date=day, code="R1", track="Test")
    first = Race(
        meeting=meeting,
        code="R1C1",
        name="Course 1",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        distance_m=2000,
    )
    alpha = Runner(number=1, horse_name="ALPHA", horse_external_id="alpha")
    alpha.history = [
        HorseHistory(
            race_date=day - timedelta(days=20),
            track="Ancien",
            distance_m=1800,
            position=1,
            raw={"geny_course_id": "777", "geny_horse_id": "101"},
            opponents=[],
        )
    ]
    first.runners = [alpha]
    second = Race(
        meeting=meeting,
        code="R1C2",
        name="Course 2",
        scheduled_at=datetime.now() + timedelta(hours=3),
        discipline="Plat",
        distance_m=1800,
    )
    beta = Runner(number=1, horse_name="BETA", horse_external_id="beta")
    beta.history = [
        HorseHistory(
            race_date=day - timedelta(days=20),
            track="Ancien",
            distance_m=1800,
            position=2,
            raw={"geny_course_id": "777", "geny_horse_id": "202"},
            opponents=[],
        )
    ]
    second.runners = [beta]
    db.add_all([first, second])
    db.commit()
    first_id, second_id = first.id, second.id
    db.close()

    class Provider:
        def __init__(self):
            self.calls = 0

        async def get_historical_course(self, course_id):
            self.calls += 1
            return {
                "data": {
                    "course_id": str(course_id),
                    "participants": [
                        {"horse_name": "ALPHA", "geny_horse_id": "101", "position": 1},
                        {"horse_name": "BETA", "geny_horse_id": "202", "position": 2},
                    ],
                },
                "meta": {"source": "Geny", "status": "ok"},
            }

    from app.main import _enrich_geny_course_details

    provider = Provider()
    with patch("app.main.SessionLocal", Session):
        asyncio.run(_enrich_geny_course_details(day, asyncio.Lock(), provider, race_id=first_id))
        asyncio.run(_enrich_geny_course_details(day, asyncio.Lock(), provider, race_id=second_id))

    assert provider.calls == 1
    check = Session()
    rows = check.scalars(select(Runner).options(selectinload(Runner.history))).all()
    by_name = {runner.horse_name: runner for runner in rows}
    assert by_name["ALPHA"].history[0].raw["geny_course_lookup_status"] == "ok"
    assert by_name["BETA"].history[0].raw["geny_course_lookup_status"] == "ok"
    check.close()
