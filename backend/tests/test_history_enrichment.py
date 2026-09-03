import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import selectinload, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.importer import ImportService
from app.main import _enrich_day_histories, _enrich_geny_course_details
from app.models import HorseHistory, Meeting, Race, Runner


def test_history_enrichment_commits_each_horse_before_the_next_request():
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
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Course test",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        distance_m=2000,
    )
    race.runners = [
        Runner(number=1, horse_name="PREMIER", horse_external_id="one"),
        Runner(number=2, horse_name="SECOND", horse_external_id="two"),
    ]
    db.add(race)
    db.commit()
    db.close()

    class Provider:
        name = "test"

        def __init__(self):
            self.calls = 0

        async def get_horse_history(self, horse_id, discipline=None, horse_name=None, race_date=None):
            self.calls += 1
            if self.calls == 1:
                return {
                    "data": {
                        "historique": [
                            {
                                "date": (day - timedelta(days=20)).isoformat(),
                                "hippodrome": "Test",
                                "discipline": "Plat",
                                "distance": 2000,
                                "position": 2,
                            }
                        ]
                    },
                    "meta": {"source": "Geny", "status": "ok"},
                }
            raise asyncio.CancelledError()

    provider = Provider()
    try:
        with patch("app.main.SessionLocal", Session), patch("app.main.provider_factory", lambda: provider):
            asyncio.run(_enrich_day_histories(day, asyncio.Lock()))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("the test provider should cancel on its second request")

    check = Session()
    runner = check.scalar(
        select(Runner)
        .where(Runner.number == 1)
        .options(selectinload(Runner.history))
    )
    assert runner is not None
    assert len(runner.history) == 1
    assert runner.raw["history_status"] == "ok"
    check.close()


def test_pmu_opponents_survive_the_longer_profile_merge():
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
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Course test",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        distance_m=2000,
    )
    race.runners = [Runner(number=1, horse_name="ALPHA", horse_external_id="alpha")]
    db.add(race)
    db.commit()
    db.close()

    shared_date = (day - timedelta(days=20)).isoformat()

    class Provider:
        name = "pmu"

        async def get_detailed_performances(self, _day, _code):
            return {"data": {"runners": [{
                "number": 1,
                "horse_name": "ALPHA",
                "historique": [{
                    "date": shared_date,
                    "hippodrome": "Test",
                    "distance": 2000,
                    "position": 1,
                    "adversaires": [{"horse_name": "RIVAL", "position": 2}],
                    "allocation_eur": 30000,
                }],
            }]}}

        async def get_horse_history(self, *_args, **_kwargs):
            return {
                "data": {"historique": [
                    {"date": shared_date, "hippodrome": "Test", "distance": 2000, "position": 1, "terrain": "Bon"},
                    {"date": (day - timedelta(days=50)).isoformat(), "hippodrome": "Autre", "distance": 1800, "position": 3},
                ]},
                "meta": {"source": "Geny", "status": "ok"},
            }

    with patch("app.main.SessionLocal", Session), patch("app.main.provider_factory", lambda: Provider()):
        asyncio.run(_enrich_day_histories(day, asyncio.Lock()))

    check = Session()
    runner = check.scalar(select(Runner).options(selectinload(Runner.history)))
    assert runner is not None
    assert len(runner.history) == 2
    shared = next(row for row in runner.history if row.race_date.isoformat() == shared_date)
    assert shared.going == "Bon"
    assert shared.opponents[0]["horse_name"] == "RIVAL"
    assert "PMU performances détaillées" in runner.raw["history_source"]
    assert "Geny" in runner.raw["history_source"]
    assert runner.raw["opponent_network_rows"] == 1
    check.close()


def test_program_refresh_preserves_history_and_opponent_checkpoints():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    day=date.today()+timedelta(days=1)
    db=Session()
    meeting=Meeting(race_date=day,code="R1",track="Test")
    race=Race(meeting=meeting,code="R1C1",name="Course",scheduled_at=datetime.now()+timedelta(hours=2),discipline="Plat")
    runner=Runner(number=1,horse_name="ALPHA",raw={
        "history_status":"ok","history_rows":5,
        "opponent_enrichment_version":"checkpoint","opponent_network_rows":3,
    })
    race.runners=[runner]; db.add(race); db.commit()

    class Provider:
        name="test"

    importer=ImportService(Provider())
    asyncio.run(importer._upsert_runners(
        db,race,{"data":{"partants":[{"num":1,"name":"ALPHA","poids":55}]}},False,
    ))
    db.commit(); db.refresh(runner)
    assert runner.raw["history_status"]=="ok"
    assert runner.raw["opponent_enrichment_version"]=="checkpoint"
    assert runner.raw["opponent_network_rows"]==3
    db.close()


def test_history_storage_uses_exact_course_id_and_bounds_legacy_race_code():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    day=date.today()
    meeting=Meeting(race_date=day,code="R1",track="Test")
    race=Race(
        meeting=meeting,code="R1C1",name="Course",scheduled_at=datetime.now(),discipline="Plat",
    )
    runner=Runner(number=1,horse_name="ALPHA")
    race.runners=[runner]
    db.add(race); db.flush()

    class Provider:
        name="test"

    long_name="Prix historique avec un nom volontairement beaucoup trop long"
    payload={"data":{"historique":[
        {
            "date":"2026-08-10","hippodrome":"Vincennes","distance":2700,
            "code_course":long_name,"nom_course":long_name,
            "geny_course_id":"101","position":1,
        },
        {
            "date":"2026-08-10","hippodrome":"Vincennes","distance":2700,
            "code_course":long_name,"nom_course":long_name,
            "geny_course_id":"102","position":4,
        },
    ]}}
    importer=ImportService(Provider())
    assert importer._replace_history(db,runner,payload)==2
    db.commit()
    assert {item.raw["geny_course_id"] for item in runner.history}=={"101","102"}
    assert all(len(item.race_code or "")<=32 for item in runner.history)
    assert all(item.raw["nom_course"]==long_name for item in runner.history)
    db.close()


def test_new_card_reuses_only_an_exact_official_horse_identity():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    db=Session()
    old_day=date.today()-timedelta(days=10)
    old_meeting=Meeting(race_date=old_day,code="R1",track="Ancien")
    old_race=Race(
        meeting=old_meeting,code="R1C1",name="Ancienne course",
        scheduled_at=datetime.now()-timedelta(days=10),discipline="Plat",
    )
    old_runner=Runner(
        number=4,horse_name="ALPHA",horse_external_id="official-alpha",
        raw={
            "history_source":"PMU performances détaillées + Geny",
            "history_status":"ok","history_rows":2,
            "opponent_enrichment_version":"old-card-only",
        },
    )
    old_runner.history=[
        HorseHistory(
            race_date=old_day-timedelta(days=20),track="Test",distance_m=2000,
            position=1,opponents=[{"horse_name":"BETA","position":2}],raw={},
        ),
        HorseHistory(
            race_date=old_day-timedelta(days=40),track="Autre",distance_m=1800,
            position=3,opponents=[],raw={},
        ),
    ]
    old_race.runners=[old_runner]
    new_meeting=Meeting(race_date=date.today(),code="R2",track="Nouveau")
    new_race=Race(
        meeting=new_meeting,code="R2C1",name="Nouvelle course",
        scheduled_at=datetime.now()+timedelta(hours=2),discipline="Plat",
    )
    db.add_all([old_race,new_race]); db.commit()

    class Provider:
        name="test"

    importer=ImportService(Provider())
    asyncio.run(importer._upsert_runners(
        db,new_race,{"data":{"partants":[{
            "num":7,"name":"ALPHA","idcheval":"official-alpha",
        }]}},False,
    ))
    db.commit()
    current=db.scalar(
        select(Runner)
        .where(Runner.race_id==new_race.id)
        .options(selectinload(Runner.history))
    )
    assert current is not None
    assert len(current.history)==2
    assert current.history[0].opponents[0]["horse_name"]=="BETA"
    assert current.raw["history_status"]=="pending"
    assert current.raw["history_rows"]==2
    assert current.raw["history_cache_reused_from"]==old_runner.id
    assert "opponent_enrichment_version" not in current.raw
    db.close()


def test_failed_refresh_keeps_cached_facts_but_marks_them_partial():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    day=date.today()+timedelta(days=1)
    db=Session()
    meeting=Meeting(race_date=day,code="R1",track="Test")
    race=Race(
        meeting=meeting,code="R1C1",name="Course",
        scheduled_at=datetime.now()+timedelta(hours=2),discipline="Plat",
    )
    runner=Runner(number=1,horse_name="ALPHA",horse_external_id="alpha",raw={"history_status":"ok"})
    runner.history=[HorseHistory(
        race_date=day-timedelta(days=20),track="Test",distance_m=2000,
        position=2,opponents=[],raw={},
    )]
    race.runners=[runner]; db.add(race); db.commit(); db.close()

    class Provider:
        name="test"

        async def get_horse_history(self,*_args,**_kwargs):
            raise RuntimeError("source temporairement indisponible")

    with patch("app.main.SessionLocal",Session),patch("app.main.provider_factory",lambda:Provider()):
        asyncio.run(_enrich_day_histories(day,asyncio.Lock()))

    check=Session()
    stored=check.scalar(select(Runner).options(selectinload(Runner.history)))
    assert stored is not None
    assert len(stored.history)==1
    assert stored.raw["history_status"]=="partial"
    assert stored.raw["history_rows"]==1
    assert "temporairement indisponible" in stored.raw["history_last_error"]
    check.close()


def test_exact_geny_course_is_downloaded_once_and_attached_to_every_matching_history():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session=sessionmaker(bind=engine,expire_on_commit=False)
    day=date.today()+timedelta(days=1)
    db=Session()
    meeting=Meeting(race_date=day,code="R1",track="Test")
    race=Race(
        meeting=meeting,code="R1C1",name="Course",
        scheduled_at=datetime.now()+timedelta(hours=2),discipline="Plat",distance_m=2000,
    )
    alpha=Runner(number=1,horse_name="ALPHA",horse_external_id="pmu-alpha",raw={"history_status":"ok"})
    beta=Runner(number=2,horse_name="BETA",horse_external_id="pmu-beta",raw={"history_status":"ok"})
    alpha.history=[HorseHistory(
        race_date=day-timedelta(days=30),track="Ancien",race_code="Prix exact",distance_m=1800,
        position=1,opponents=[],raw={"geny_course_id":"777","geny_horse_id":"101"},
    )]
    beta.history=[HorseHistory(
        race_date=day-timedelta(days=30),track="Ancien",race_code="Prix exact",distance_m=1800,
        position=2,opponents=[],raw={"geny_course_id":"777","geny_horse_id":"202"},
    )]
    race.runners=[alpha,beta]
    db.add(race); db.commit(); db.close()

    class Provider:
        def __init__(self):
            self.calls=0

        async def get_historical_course(self,course_id):
            self.calls+=1
            assert str(course_id)=="777"
            return {
                "data":{"course_id":"777","participants":[
                    {"horse_name":"ALPHA","geny_horse_id":"101","position":1},
                    {"horse_name":"BETA","geny_horse_id":"202","position":2},
                    {"horse_name":"GAMMA","geny_horse_id":"303","position":3},
                ]},
                "meta":{"source":"Geny course détaillée","status":"ok"},
            }

    provider=Provider()
    with patch("app.main.SessionLocal",Session):
        remaining=asyncio.run(_enrich_geny_course_details(day,asyncio.Lock(),provider))
    assert remaining is False
    assert provider.calls==1

    check=Session()
    runners=check.scalars(select(Runner).options(selectinload(Runner.history)).order_by(Runner.number)).all()
    assert [item["horse_name"] for item in runners[0].history[0].opponents]==["BETA","GAMMA"]
    assert [item["horse_name"] for item in runners[1].history[0].opponents]==["ALPHA","GAMMA"]
    assert runners[0].history[0].raw["geny_course_lookup_status"]=="ok"
    assert runners[0].raw["opponent_network_status"]=="complete"
    assert runners[0].raw["geny_course_rows_linked"]==1
    check.close()
