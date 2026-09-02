from datetime import date, datetime
import asyncio
from types import SimpleNamespace

from app.providers.pmu import PmuProvider


def test_normalize_pmu_program_and_runners():
    day=date(2026,9,1)
    program=PmuProvider.normalize_program({"programme":{"reunions":[{
        "numOfficiel":1,"hippodrome":{"libelleCourt":"DEAUVILLE"},
        "courses":[{"numOrdre":2,"libelle":"PRIX TEST","heureDepart":"14:30","discipline":"PLAT","distance":1600}]
    }]}},day)
    race=program["data"]["reunions"][0]["courses"][0]
    assert race["code_course"]=="R1C2"
    assert race["distance"]==1600

    runners=PmuProvider.normalize_runners({"participants":[{
        "numPmu":4,"nom":"CHEVAL TEST","musique":"1p2p","statut":"PARTANT",
        "jockey":{"libelleCourt":"A. TEST"},"placeCorde":3
    }]})
    runner=runners["data"]["partants"][0]
    assert runner["num"]==4
    assert runner["jockey_driver"]=="A. TEST"
    assert runner["np"] is False


def test_normalize_provisional_and_official_results():
    payload={"programme":{"reunions":[{
        "numOfficiel":1,"hippodrome":{"libelleCourt":"DEAUVILLE"},"courses":[
            {"numOrdre":1,"statut":"ARRIVEE_PROVISOIRE","ordreArrivee":[4,2,7]},
            {"numOrdre":2,"statut":"RESULTAT_DEFINITIF","ordreArrivee":[3,8,1],"arriveeDefinitive":True},
        ]
    }]}}
    rows=PmuProvider.normalize_results(payload)["data"]["results"]
    assert rows[0]["result_status"]=="provisional"
    assert rows[0]["arrivee"]==[4,2,7]
    assert rows[1]["result_status"]=="official"
    assert rows[1]["arrivee"]==[3,8,1]


def test_result_entries_keep_pmu_runner_numbers_and_ranks():
    from app.importer import _result_entries, _result_number

    entries = _result_entries({"participants": [{"numPmu": 4, "rang": 1}, {"numero": 8, "rang": 2}]})
    # The importer accepts PMU's numPmu spelling as well as flat numbers.
    assert [_result_number(entry) for entry in entries] == [4, 8]


def test_normalize_results_accepts_nested_official_order_and_skips_invalid_codes():
    payload={"programme":{"reunions":[
        {"numOfficiel":1,"hippodrome":{"libelleCourt":"DEAUVILLE"},"courses":[
            {"numOrdre":3,"statut":"OFFICIEL","resultat":{"classement":[{"numPmu":9,"rang":1},{"numero":2,"rang":2}]}},
            {"statut":"OFFICIEL","ordreArrivee":[1,2]},
        ]}
    ]}}
    rows=PmuProvider.normalize_results(payload)["data"]["results"]
    assert len(rows) == 1
    assert rows[0]["code_course"] == "R1C3"
    assert rows[0]["result_status"] == "official"
    assert rows[0]["arrivee"][0]["numPmu"] == 9


def test_importer_never_downgrades_an_official_arrival():
    from app.importer import ImportService
    from app.models import RaceResult

    class Provider:
        async def get_results(self, day):
            return {"data": {"results": [{
                "code_course": "R1C1", "arrivee": [7, 4], "result_status": "provisional",
            }]}}

    race = SimpleNamespace(
        result=RaceResult(official_order=[4, 7], raw={"result_status": "official"}),
        status="finished",
    )

    class DB:
        def scalar(self, statement):
            return race
        def commit(self):
            return None

    asyncio.run(ImportService(Provider()).import_results(DB(), date(2026, 9, 2)))
    assert race.result.status == "official"
    assert race.result.official_order == [4, 7]


def test_french_provisoire_status_is_normalized_before_storage():
    from app.models import RaceResult
    assert RaceResult(raw={"result_status": "provisoire"}).status == "provisional"


def test_results_without_track_use_the_meeting_code_not_the_first_matching_race():
    from app.database import Base
    from app.importer import ImportService
    from app.models import Meeting, Race
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    day = date(2026, 9, 2)
    with Session(engine) as db:
        r1 = Meeting(race_date=day, code="R1", track="Paris")
        r2 = Meeting(race_date=day, code="R2", track="Lyon")
        r1.races = [Race(code="R1C1", name="R1", scheduled_at=datetime.now(), discipline="Plat")]
        r2.races = [Race(code="R2C1", name="R2", scheduled_at=datetime.now(), discipline="Plat")]
        db.add_all([r1, r2])
        db.commit()

        class Provider:
            async def get_results(self, _day):
                return {"data": {"results": [{"code_course": "R2C1", "arrivee": [7, 4], "result_status": "official"}]}}

        import asyncio
        asyncio.run(ImportService(Provider()).import_results(db, day))
        target = db.scalar(select(Race).where(Race.code == "R2C1"))
        other = db.scalar(select(Race).where(Race.code == "R1C1"))
        assert target.result is not None and target.result.official_order == [7, 4]
        assert other.result is None


def test_international_discipline_labels_keep_trot_and_galop_families():
    from app.importer import _normalize_discipline
    assert _normalize_discipline("Harness racing") == "Trot attelé"
    assert _normalize_discipline("Mounted trot") == "Trot monté"
    assert _normalize_discipline("Thoroughbred flat") == "Plat"
