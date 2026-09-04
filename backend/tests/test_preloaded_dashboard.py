from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import _future_engagements, day_dashboard, settings
from app.models import AnalysisSnapshot, HorseHistory, Meeting, Race, Runner


def test_dashboard_counts_precomputed_races_and_future_engagements():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    day = date.today()
    db = Session()

    meeting = Meeting(race_date=day, code="R1", track="Today")
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Today race",
        scheduled_at=datetime.now() + timedelta(hours=1),
        discipline="Plat",
        distance_m=1600,
    )
    alpha = Runner(
        number=1,
        horse_name="ALPHA",
        horse_external_id="horse-alpha",
        raw={"history_status": "ok", "history_checked_at": datetime.now().isoformat()},
    )
    alpha.history = [
        HorseHistory(
            race_date=day - timedelta(days=10),
            track="Old",
            position=2,
            raw={"geny_course_id": "100", "geny_course_lookup_status": "ok"},
        )
    ]
    beta = Runner(
        number=2,
        horse_name="BETA",
        horse_external_id="horse-beta",
        raw={"history_status": "ok", "history_checked_at": datetime.now().isoformat()},
    )
    race.runners = [alpha, beta]
    db.add(race)
    db.flush()
    db.add(
        AnalysisSnapshot(
            race_id=race.id,
            methodology_version=settings.methodology_version,
            data_hash="test",
            summary={},
        )
    )

    future_meeting = Meeting(race_date=day + timedelta(days=4), code="R2", track="Future")
    future_race = Race(
        meeting=future_meeting,
        code="R2C3",
        name="Future race",
        scheduled_at=datetime.now() + timedelta(days=4, hours=2),
        discipline="Plat",
        distance_m=1800,
    )
    future_race.runners = [
        Runner(number=4, horse_name="ALPHA", horse_external_id="horse-alpha")
    ]
    db.add(future_race)
    db.commit()

    dashboard = day_dashboard(day, db)
    assert dashboard["ready"] is True
    assert dashboard["activity"]["courses_analyzed"] == 1
    assert dashboard["activity"]["horses_analyzed"] == 2
    assert dashboard["engagements"]["count"] == 1
    assert dashboard["engagements"]["within_7_days"] == 1
    assert dashboard["engagements"]["items"][0]["horse_name"] == "ALPHA"
    assert dashboard["engagements"]["items"][0]["next"]["race_code"] == "R2C3"
    db.close()


def test_future_engagement_falls_back_to_normalized_name_when_external_id_missing():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    day = date.today()
    db = Session()

    meeting = Meeting(race_date=day, code="R1", track="Today")
    race = Race(
        meeting=meeting,
        code="R1C1",
        name="Today",
        scheduled_at=datetime.now(),
        discipline="Trot",
    )
    race.runners = [Runner(number=1, horse_name="Étoile d'Or", raw={"history_status": "ok"})]
    db.add(race)

    meeting2 = Meeting(race_date=day + timedelta(days=2), code="R3", track="Future")
    race2 = Race(
        meeting=meeting2,
        code="R3C2",
        name="Next",
        scheduled_at=datetime.now() + timedelta(days=2),
        discipline="Trot",
    )
    race2.runners = [Runner(number=7, horse_name="ETOILE D OR")]
    db.add(race2)
    db.commit()

    rows = _future_engagements(day, db)
    assert len(rows) == 1
    assert rows[0]["next"]["days_after"] == 2
    db.close()
