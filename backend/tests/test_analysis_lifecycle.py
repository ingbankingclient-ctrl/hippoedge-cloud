from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analysis_service import generate_analysis, lock_latest_snapshot
from app.database import Base
from app.models import HorseHistory, Meeting, Race, RaceResult, Runner


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_result_cannot_rewrite_the_pre_race_snapshot():
    db = _session()
    meeting = Meeting(race_date=date.today(), code="R1", track="Vincennes")
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Course test",
        scheduled_at=datetime.now() + timedelta(hours=1),
        discipline="Trot attelé",
        distance_m=2100,
    )
    runner = Runner(number=1, horse_name="TEST", race=race, recent_form="1a2a")
    runner.history = [
        HorseHistory(race_date=date.today() - timedelta(days=days), position=position, discipline="Trot attelé")
        for days,position in ((10,1),(25,2),(40,3))
    ]
    db.add(race)
    db.commit()
    db.refresh(race)

    snapshot = generate_analysis(db, race)
    assert snapshot.summary["snapshot_phase"] == "pre_race"
    assert snapshot.summary["winning_pick_label"].startswith("n°1")
    locked = lock_latest_snapshot(db, race)
    original_id = locked.id
    original_summary = dict(locked.summary)

    race.result = RaceResult(official_order=[1], raw={"result_status": "official"})
    db.commit()
    db.refresh(race)
    after = generate_analysis(db, race, lock=False)
    assert after.id == original_id
    assert after.summary == original_summary


def test_late_race_cannot_be_locked_retroactively():
    db = _session()
    meeting = Meeting(race_date=date.today(), code="R1", track="Vincennes")
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Course passée",
        scheduled_at=datetime.now() - timedelta(minutes=5),
        discipline="Trot attelé",
        distance_m=2100,
    )
    race.runners = [Runner(number=1, horse_name="TEST", recent_form="1a2a")]
    db.add(race)
    db.commit()
    db.refresh(race)
    generate_analysis(db, race)
    try:
        lock_latest_snapshot(db, race)
    except ValueError as exc:
        assert "déjà passé" in str(exc)
    else:
        raise AssertionError("Un snapshot post-départ ne doit jamais être verrouillé")


def test_pre_race_snapshot_cannot_be_locked_after_the_departure():
    db = _session()
    meeting = Meeting(race_date=date.today(), code="R1", track="Vincennes")
    race = Race(
        meeting=meeting,
        code="R1C2",
        name="Course devenue passée",
        scheduled_at=datetime.now() + timedelta(minutes=20),
        discipline="Trot attelé",
        distance_m=2100,
    )
    race.runners = [Runner(number=1, horse_name="TEST", recent_form="1a2a")]
    db.add(race)
    db.commit()
    db.refresh(race)
    snapshot = generate_analysis(db, race)
    assert snapshot.summary["snapshot_phase"] == "pre_race"
    # Simulate the user waiting until after the start before pressing Figer.
    race.scheduled_at = datetime.now() - timedelta(minutes=1)
    db.commit()
    try:
        lock_latest_snapshot(db, race)
    except ValueError as exc:
        assert "déjà passé" in str(exc)
    else:
        raise AssertionError("Un snapshot pré-course ne doit pas être verrouillé après le départ")


def test_empty_evidence_cannot_create_a_winning_pick():
    db = _session()
    meeting = Meeting(race_date=date.today(), code="R1", track="Deauville")
    race = Race(
        meeting=meeting,
        code="R1C3",
        name="Course sans historique",
        scheduled_at=datetime.now() + timedelta(hours=1),
        discipline="Plat",
        distance_m=2000,
    )
    race.runners = [Runner(number=14, horse_name="DEBUTANTE", raw={"history_status": "history_incomplete"})]
    db.add(race)
    db.commit()
    db.refresh(race)
    snapshot = generate_analysis(db, race)
    assert snapshot.summary["top3_performance"] == []
    assert snapshot.summary["winning_pick"] is None
    assert snapshot.summary["rational_place"] is None


def test_incomplete_field_does_not_publish_a_race_hierarchy():
    db=_session()
    meeting=Meeting(race_date=date.today(),code="R2",track="Test")
    race=Race(
        meeting=meeting,code="R2C1",name="Lot incomplet",
        scheduled_at=datetime.now()+timedelta(hours=2),discipline="Plat",distance_m=1800,
    )
    for number in range(1,5):
        runner=Runner(number=number,horse_name=f"CHEVAL {number}",race=race,recent_form="1p2p3p")
        if number==1:
            runner.history=[
                HorseHistory(race_date=date.today()-timedelta(days=days),position=position,discipline="Plat")
                for days,position in ((10,1),(20,2),(30,3))
            ]
    db.add(race); db.commit(); db.refresh(race)
    snapshot=generate_analysis(db,race)
    quality=snapshot.summary["data_quality"]
    assert quality["field_coverage_percent"]==25
    assert quality["field_coverage_ready"] is False
    assert snapshot.summary["winning_pick"] is None
    assert snapshot.summary["top3_performance"]==[]
