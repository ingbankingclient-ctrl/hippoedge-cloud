from datetime import date, timedelta

from app.finisher import finisher_profile, rank_finisher_candidates
from app.models import HorseHistory


def hist(days: int, position: int, raw: dict, margin: float | None = None) -> HorseHistory:
    return HorseHistory(
        runner_id=1,
        race_date=date.today() - timedelta(days=days),
        track="Test",
        position=position,
        disqualified=False,
        margin_to_winner=margin,
        raw=raw,
        opponents=[],
    )


def test_finisher_requires_objective_course_flow_and_ignores_editorial_note():
    profile = finisher_profile([
        hist(10, 2, {"noteFinDeCourse": "A fini très fort, belle chance."}, 0.5),
        hist(20, 3, {"commentaire": "Excellent finisseur."}, 1.0),
    ])
    assert profile.eligible is False
    assert profile.status == "insufficient"
    assert profile.score == 0


def test_finisher_detects_repeated_objective_late_gains():
    profile = finisher_profile([
        hist(8, 2, {"positions_intermediaires": [10, 8, 6, 2]}, 0.8),
        hist(25, 3, {"positions_intermediaires": [11, 9, 7, 3], "rang_dernier_troncon": 2}, 1.2),
        hist(50, 5, {"places_gagnees_fin": 3}, 3.5),
    ])
    assert profile.eligible is True
    assert profile.status == "confirmed"
    assert profile.evidence_runs >= 2
    assert profile.strong_runs >= 1
    assert profile.score >= 72
    assert any("phase finale" in reason for reason in profile.reasons)


def test_finisher_top3_forces_a_real_current_chance_at_number_one():
    candidates = [
        {
            "number": 4, "finisher_score": 95, "evidence_runs": 4,
            "performance": 58, "placed": 61, "beautiful_chance": False, "eligible": True,
        },
        {
            "number": 7, "finisher_score": 86, "evidence_runs": 3,
            "performance": 78, "placed": 80, "beautiful_chance": True, "eligible": True,
        },
        {
            "number": 2, "finisher_score": 82, "evidence_runs": 2,
            "performance": 69, "placed": 72, "beautiful_chance": False, "eligible": True,
        },
    ]
    ranked = rank_finisher_candidates(candidates)
    assert [item["number"] for item in ranked] == [7, 4, 2]
    assert ranked[0]["beautiful_chance"] is True


def test_finisher_top3_is_empty_without_a_beautiful_chance():
    ranked = rank_finisher_candidates([
        {"number": 1, "finisher_score": 90, "evidence_runs": 3, "beautiful_chance": False, "eligible": True},
        {"number": 2, "finisher_score": 85, "evidence_runs": 2, "beautiful_chance": False, "eligible": True},
    ])
    assert ranked == []


def test_late_mover_detects_move_before_final_phase_then_holds():
    from app.finisher import late_mover_profile

    profile = late_mover_profile([
        hist(8, 4, {"positions_intermediaires": [7, 4, 4]}, 2.0),
    ])
    assert profile.eligible is True
    assert profile.status == "probable"
    assert profile.evidence_runs == 1
    assert any("7e → 4e" in reason for reason in profile.reasons)
    assert any("effort soutenu" in reason for reason in profile.reasons)


def test_late_mover_rejects_a_move_that_collapses_before_the_line():
    from app.finisher import late_mover_profile

    profile = late_mover_profile([
        hist(8, 7, {"positions_intermediaires": [8, 4, 7]}, 6.0),
    ])
    assert profile.eligible is False
    assert profile.evidence_runs == 0
    assert profile.contradiction_runs >= 1


def test_late_mover_top3_also_requires_a_real_current_chance_at_number_one():
    from app.finisher import rank_late_mover_candidates

    ranked = rank_late_mover_candidates([
        {"number": 2, "late_mover_score": 93, "evidence_runs": 3, "performance": 60, "placed": 64, "beautiful_chance": False, "eligible": True},
        {"number": 5, "late_mover_score": 84, "evidence_runs": 2, "performance": 76, "placed": 79, "beautiful_chance": True, "eligible": True},
        {"number": 9, "late_mover_score": 80, "evidence_runs": 2, "performance": 68, "placed": 71, "beautiful_chance": False, "eligible": True},
    ])
    assert [item["number"] for item in ranked] == [5, 2, 9]



def test_resistance_to_finisher_requires_same_objective_finisher_run():
    from app.finisher import finisher_profile, finisher_resistance_profile
    from app.models import Runner, HorseHistory

    race_day = date.today() - timedelta(days=14)
    resistant = Runner(id=3, race_id=1, number=3, horse_name="Charco", scratched=False, raw={})
    finisher = Runner(id=8, race_id=1, number=8, horse_name="Echo Down", scratched=False, raw={})

    resistant.history = [HorseHistory(
        runner_id=3, race_date=race_day, track="Evangeline Downs", race_code="R5", distance_m=1000,
        position=2, disqualified=False, raw={"geny_course_id": "12345"},
        opponents=[{"horse_name": "Echo Down", "position": 3}],
    )]
    finisher.history = [HorseHistory(
        runner_id=8, race_date=race_day, track="Evangeline Downs", race_code="R5", distance_m=1000,
        position=3, disqualified=False,
        raw={"geny_course_id": "12345", "positions_intermediaires": [8, 5, 3]},
        opponents=[{"horse_name": "Charco", "position": 2}],
    )]

    finisher_block = finisher_profile(finisher.history).as_dict()
    assert finisher_block["eligible"] is True
    profile = finisher_resistance_profile(resistant, [resistant, finisher], {8: finisher_block})
    assert profile.eligible is True
    assert profile.support_runs == 1
    assert profile.unique_finishers == 1
    assert any("Echo Down" in reason for reason in profile.reasons)
    assert any("phase finale" in reason for reason in profile.reasons)


def test_resistance_does_not_count_generic_win_from_different_race():
    from app.finisher import finisher_profile, finisher_resistance_profile
    from app.models import Runner, HorseHistory

    finisher_day = date.today() - timedelta(days=10)
    generic_day = date.today() - timedelta(days=30)
    resistant = Runner(id=3, race_id=1, number=3, horse_name="Charco", scratched=False, raw={})
    finisher = Runner(id=8, race_id=1, number=8, horse_name="Echo Down", scratched=False, raw={})
    resistant.history = [HorseHistory(
        runner_id=3, race_date=generic_day, track="Evangeline Downs", race_code="R4", distance_m=1000,
        position=2, disqualified=False, raw={"geny_course_id": "old"},
        opponents=[{"horse_name": "Echo Down", "position": 3}],
    )]
    finisher.history = [
        HorseHistory(
            runner_id=8, race_date=generic_day, track="Evangeline Downs", race_code="R4", distance_m=1000,
            position=3, disqualified=False, raw={"geny_course_id": "old"},
            opponents=[{"horse_name": "Charco", "position": 2}],
        ),
        HorseHistory(
            runner_id=8, race_date=finisher_day, track="Evangeline Downs", race_code="R5", distance_m=1000,
            position=2, disqualified=False,
            raw={"geny_course_id": "finish", "positions_intermediaires": [7, 5, 2]},
            opponents=[],
        ),
    ]
    finisher_block = finisher_profile(finisher.history).as_dict()
    profile = finisher_resistance_profile(resistant, [resistant, finisher], {8: finisher_block})
    assert profile.eligible is False
    assert profile.support_runs == 0


def test_resistance_strengthens_when_multiple_current_finishers_were_contained():
    from app.finisher import finisher_resistance_profile
    from app.models import Runner, HorseHistory

    resistant = Runner(id=3, race_id=1, number=3, horse_name="Resistant", scratched=False, raw={})
    f8 = Runner(id=8, race_id=1, number=8, horse_name="Finisher Eight", scratched=False, raw={})
    f5 = Runner(id=5, race_id=1, number=5, horse_name="Finisher Five", scratched=False, raw={})
    day1 = date.today() - timedelta(days=15)
    day2 = date.today() - timedelta(days=35)
    resistant.history = [
        HorseHistory(runner_id=3, race_date=day1, track="Test", race_code="A", distance_m=1200, position=2, disqualified=False, raw={"geny_course_id":"a"}, opponents=[{"horse_name":"Finisher Eight","position":3}]),
        HorseHistory(runner_id=3, race_date=day2, track="Test", race_code="B", distance_m=1200, position=1, disqualified=False, raw={"geny_course_id":"b"}, opponents=[{"horse_name":"Finisher Five","position":2}]),
    ]
    f8.history = [HorseHistory(runner_id=8, race_date=day1, track="Test", race_code="A", distance_m=1200, position=3, disqualified=False, raw={"geny_course_id":"a"}, opponents=[{"horse_name":"Resistant","position":2}])]
    f5.history = [HorseHistory(runner_id=5, race_date=day2, track="Test", race_code="B", distance_m=1200, position=2, disqualified=False, raw={"geny_course_id":"b"}, opponents=[{"horse_name":"Resistant","position":1}])]
    blocks = {
        8: {"eligible": True, "evidence": [{"date": day1.isoformat(), "track":"Test", "event_token":"id:a", "distance_m":1200, "score":85, "late_gain_places":3, "sectional_rank":2}]},
        5: {"eligible": True, "evidence": [{"date": day2.isoformat(), "track":"Test", "event_token":"id:b", "distance_m":1200, "score":82, "late_gain_places":2, "sectional_rank":3}]},
    }
    profile = finisher_resistance_profile(resistant, [resistant, f8, f5], blocks)
    assert profile.eligible is True
    assert profile.status == "confirmed"
    assert profile.unique_finishers == 2
    assert profile.support_runs == 2
    assert any("2 finisseurs distincts" in reason for reason in profile.reasons)
