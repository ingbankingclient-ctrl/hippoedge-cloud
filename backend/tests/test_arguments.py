from datetime import date, datetime, timedelta

from app.arguments import build_block_argument
from app.models import HorseHistory, Meeting, Race, Runner, RunnerScore


def make_history(days: int, position: int, distance: int, margin: float) -> HorseHistory:
    return HorseHistory(
        runner_id=1,
        race_date=date.today() - timedelta(days=days),
        track="Evangeline Downs",
        distance_m=distance,
        position=position,
        disqualified=False,
        margin_to_winner=margin,
        going="DIRT",
        opponents=[],
        raw={},
    )


def make_case():
    meeting = Meeting(id=1, race_date=date.today(), code="R1", track="Evangeline Downs")
    race = Race(
        id=1,
        meeting=meeting,
        meeting_id=1,
        code="R1C4",
        name="Test",
        scheduled_at=datetime.now(),
        discipline="Galop",
        distance_m=1200,
        surface="DIRT",
    )
    runner = Runner(id=1, race_id=1, number=2, horse_name="GREY TEST", weight_kg=54.5, draw=4)
    runner.history = [
        make_history(7, 2, 1200, 1.5),
        make_history(20, 4, 1100, 3.0),
        make_history(35, 5, 1200, 4.0),
    ]
    score = RunnerScore(
        performance=71,
        placed=75,
        hidden_potential=63,
        robustness=74,
        uncertainty=48,
        line_strength=66,
        reasons=["Progression récente mesurable"],
        breakdown={
            "opponent_network": {
                "eligible": True,
                "linked_races": 4,
                "confirmed_lines": 3,
                "chain_examples": ["GREY TEST → RIVAL A → RIVAL B"],
                "today_bridge_examples": [],
            }
        },
    )
    return race, runner, score


def test_player_argument_leads_with_racing_facts_not_only_scores():
    race, runner, score = make_case()
    text = build_block_argument(race, runner, score, "performance")
    assert "2e" in text
    assert "1200 m" in text
    assert "Evangeline Downs" in text
    assert "/100" not in text


def test_network_argument_uses_verified_chain_example():
    race, runner, score = make_case()
    text = build_block_argument(race, runner, score, "network")
    assert "GREY TEST → RIVAL A → RIVAL B" in text


def test_placed_argument_explains_repeatability_with_results():
    race, runner, score = make_case()
    text = build_block_argument(race, runner, score, "placed")
    assert "trois premiers" in text or "cinq premiers" in text
    assert "dernières courses" in text
