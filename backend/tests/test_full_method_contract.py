from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.analysis_service import REQUIRED_ANALYSIS_BLOCKS, generate_analysis
from app.database import Base
from app.main import history_status
from app.models import HorseHistory, Meeting, Race, Runner


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_every_permanent_block_is_exposed_even_when_some_have_no_signal():
    db = _session()
    today = date.today()
    meeting = Meeting(race_date=today, code="R1", track="Ellerslie")
    race = Race(
        meeting=meeting,
        code="R1C3",
        name="YOURRIDE BM65",
        scheduled_at=datetime.now() + timedelta(hours=2),
        discipline="Plat",
        distance_m=2200,
        class_name="BM65",
        going="Soft 6",
    )
    runner = Runner(number=2, horse_name="DOUBLE TAKE", horse_external_id="horse-2", race=race, recent_form="1p3p4p")
    runner.history = [
        HorseHistory(
            race_date=today - timedelta(days=365),
            track="Ellerslie",
            race_code="YOURRIDE BM65",
            discipline="Plat",
            distance_m=2200,
            class_name="BM65",
            position=1,
            raw={"nom_course": "YOURRIDE BM65"},
        ),
        HorseHistory(race_date=today - timedelta(days=30), track="Te Aroha", discipline="Plat", distance_m=2100, position=3),
        HorseHistory(race_date=today - timedelta(days=60), track="Ellerslie", discipline="Plat", distance_m=2200, position=4),
    ]
    db.add(race)

    future_meeting = Meeting(race_date=today + timedelta(days=7), code="R2", track="Te Rapa")
    future_race = Race(
        meeting=future_meeting,
        code="R2C5",
        name="Future BM65",
        scheduled_at=datetime.now() + timedelta(days=7, hours=2),
        discipline="Plat",
        distance_m=2200,
        class_name="BM65",
    )
    future_race.runners = [Runner(number=5, horse_name="DOUBLE TAKE", horse_external_id="horse-2")]
    db.add(future_race)
    db.commit()
    db.refresh(race)

    snapshot = generate_analysis(db, race)
    summary = snapshot.summary
    assert summary["method_complete"] is True
    assert summary["missing_blocks"] == []
    assert summary["required_blocks"] == REQUIRED_ANALYSIS_BLOCKS
    assert set(summary["completed_blocks"]) == set(REQUIRED_ANALYSIS_BLOCKS)
    assert summary["house_target"]["independent"] is True
    assert summary["house_target"]["affects_scores"] is False
    assert summary["house_target"]["selection"] == [2]
    target = summary["house_target"]["detail"][0]
    assert target["status"] == "signal_fort"
    assert "même intitulé" in target["argument"]
    assert target["future_engagements"][0]["days_after"] == 7
    assert summary["future_engagements"]["items"][0]["number"] == 2
    assert "robustness_top3" in summary
    assert "low_volatility_top3" in summary
    assert "reinforced_parameters" in summary


def test_unique_historical_course_counter_does_not_count_same_race_twice():
    db = _session()
    today = date.today()
    meeting = Meeting(race_date=today, code="R1", track="Test")
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Course",
        scheduled_at=datetime.now() + timedelta(hours=1),
        discipline="Plat",
        distance_m=1600,
    )
    for number in (1, 2):
        runner = Runner(number=number, horse_name=f"HORSE {number}", race=race, raw={"history_status": "ok"})
        runner.history = [
            HorseHistory(
                race_date=today - timedelta(days=10),
                track="Test",
                position=number,
                raw={"geny_course_id": "123456", "geny_course_lookup_status": "ok"},
            )
        ]
    db.add(race)
    db.commit()

    status = history_status(today, db)
    assert status["historical_race_rows"] == 2
    assert status["historical_race_rows_linked"] == 2
    assert status["historical_unique_courses_total"] == 1
    assert status["historical_unique_courses_linked"] == 1
    assert status["historical_unique_courses_pending"] == 0
