from datetime import date, datetime, timedelta

from app.models import HorseHistory, Meeting, Race, Runner
from app.opponent_network import build_opponent_network
from app.scoring import score_race


def history(runner_id, days, position, opponents, allocation=30000):
    return HorseHistory(
        runner_id=runner_id,
        race_date=date.today() - timedelta(days=days),
        track=f"Piste {days}",
        race_code=f"Prix {days}",
        discipline="Plat",
        distance_m=2000,
        position=position,
        field_size=12,
        opponents=opponents,
        raw={"allocation_eur": allocation, "result_status": "PLACE"},
    )


def race_with(*runners):
    meeting = Meeting(id=1, race_date=date.today(), code="R1", track="Test")
    race = Race(
        id=1,
        meeting=meeting,
        meeting_id=1,
        code="R1C1",
        name="Test réseau",
        scheduled_at=datetime.now() + timedelta(hours=1),
        discipline="Plat",
        distance_m=2000,
        class_name="Classe 2",
    )
    race.runners = list(runners)
    return race


def test_a_beaten_rival_who_wins_later_confirms_the_line():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA")
    b = Runner(id=2, race_id=1, number=2, horse_name="BETA")
    c = Runner(id=3, race_id=1, number=3, horse_name="GAMMA")
    a.history = [
        history(1, 90, 1, [
            {"horse_name": "RIVAL X", "position": 2},
            {"horse_name": "RIVAL Y", "position": 3},
            {"horse_name": "RIVAL Z", "position": 4},
        ], 30000),
        history(1, 70, 2, [
            {"horse_name": "RIVAL M", "position": 1},
            {"horse_name": "RIVAL N", "position": 3},
            {"horse_name": "RIVAL O", "position": 4},
        ], 32000),
    ]
    # RIVAL X repeats later and wins at a higher level.
    b.history = [history(2, 40, 4, [
        {"horse_name": "RIVAL X", "position": 1},
        {"horse_name": "AUTRE 1", "position": 2},
        {"horse_name": "AUTRE 2", "position": 3},
    ], 50000)]
    c.history = [history(3, 30, 4, [
        {"horse_name": "RIVAL N", "position": 1},
        {"horse_name": "AUTRE 3", "position": 2},
        {"horse_name": "AUTRE 4", "position": 3},
    ], 18000)]
    cards = build_opponent_network(race_with(a, b, c), [a, b, c])
    assert cards[1].eligible is True
    assert cards[1].confirmed_lines >= 1
    assert cards[1].higher_or_equal_confirmations >= 1
    assert "RIVAL X" in cards[1].paragraph


def test_second_degree_chain_is_counted_and_depth_is_capped_at_three_edges():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA")
    b = Runner(id=2, race_id=1, number=2, horse_name="BETA")
    c = Runner(id=3, race_id=1, number=3, horse_name="GAMMA")
    a.history = [
        history(1, 100, 1, [{"horse_name": "X", "position": 2}, {"horse_name": "A1", "position": 3}, {"horse_name": "A2", "position": 4}]),
        history(1, 95, 2, [{"horse_name": "A3", "position": 1}, {"horse_name": "A4", "position": 3}, {"horse_name": "A5", "position": 4}]),
    ]
    b.history = [history(2, 70, 4, [{"horse_name": "X", "position": 1}, {"horse_name": "Y", "position": 2}, {"horse_name": "B1", "position": 3}], 32000)]
    c.history = [history(3, 30, 4, [{"horse_name": "Y", "position": 1}, {"horse_name": "C1", "position": 2}, {"horse_name": "C2", "position": 3}], 35000)]
    card = build_opponent_network(race_with(a, b, c), [a, b, c])[1]
    assert card.indirect_chains >= 1
    assert card.as_dict()["max_depth"] == 3


def test_a_b_c_d_chain_is_counted_explained_and_kept_independent():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA")
    b = Runner(id=2, race_id=1, number=2, horse_name="BETA")
    c = Runner(id=3, race_id=1, number=3, horse_name="GAMMA")
    a.history = [
        history(1, 120, 1, [
            {"horse_name": "BRAVO", "position": 2},
            {"horse_name": "AUX 1", "position": 3},
            {"horse_name": "AUX 2", "position": 4},
        ], 30000),
        history(1, 110, 2, [
            {"horse_name": "AUX 3", "position": 1},
            {"horse_name": "AUX 4", "position": 3},
            {"horse_name": "AUX 5", "position": 4},
        ], 32000),
    ]
    # BRAVO (B) bat CHARLIE (C), puis CHARLIE bat DELTA (D), toujours plus tard.
    b.history = [history(2, 80, 4, [
        {"horse_name": "BRAVO", "position": 1},
        {"horse_name": "CHARLIE", "position": 2},
        {"horse_name": "B AUX", "position": 3},
    ], 35000)]
    c.history = [history(3, 40, 4, [
        {"horse_name": "CHARLIE", "position": 1},
        {"horse_name": "DELTA", "position": 2},
        {"horse_name": "C AUX", "position": 3},
    ], 38000)]
    card = build_opponent_network(race_with(a, b, c), [a, b, c])[1]
    payload = card.as_dict()
    assert card.eligible is True
    assert payload["third_degree_chains"] >= 1
    assert payload["max_depth"] == 3
    assert "A→B→C→D" in card.paragraph
    assert any("BRAVO" in example and "CHARLIE" in example and "DELTA" in example for example in payload["chain_examples"])
    assert payload["affects_main_scores"] is False


def test_sparse_network_is_not_ranked():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA")
    a.history = [history(1, 30, 1, [{"horse_name": "X", "position": 2}])]
    card = build_opponent_network(race_with(a), [a])[1]
    assert card.eligible is False
    assert "non classé" in card.paragraph


def test_beaten_opponents_are_bridged_to_both_results_against_today_rivals():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA")
    c = Runner(id=2, race_id=1, number=2, horse_name="CHARLIE")
    d = Runner(id=3, race_id=1, number=3, horse_name="DELTA")
    a.history = [
        history(1, 100, 1, [
            {"horse_name": "BETA", "position": 2},
            {"horse_name": "AUX 1", "position": 3},
            {"horse_name": "AUX 2", "position": 4},
        ], 30000),
        history(1, 90, 2, [
            {"horse_name": "AUX 3", "position": 1},
            {"horse_name": "AUX 4", "position": 3},
            {"horse_name": "AUX 5", "position": 4},
        ], 32000),
    ]
    # BETA, previously beaten by ALPHA, later beats CHARLIE in a stronger lot.
    c.history = [history(2, 50, 2, [
        {"horse_name": "BETA", "position": 1},
        {"horse_name": "C AUX 1", "position": 3},
        {"horse_name": "C AUX 2", "position": 4},
    ], 50000)]
    # DELTA later beats the same BETA: the opposite direction must not be hidden.
    d.history = [history(3, 30, 1, [
        {"horse_name": "BETA", "position": 2},
        {"horse_name": "D AUX 1", "position": 3},
        {"horse_name": "D AUX 2", "position": 4},
    ], 52000)]
    card = build_opponent_network(race_with(a, c, d), [a, c, d])[1]
    assert card.today_opponent_bridges == 2
    assert card.bridge_supports == 1
    assert card.bridge_counter_signals == 1
    assert any("n°2 CHARLIE" in example for example in card.today_bridge_examples)
    assert any("n°3 DELTA" in example for example in card.today_bridge_examples)
    assert "passerelles" in card.paragraph


def test_opponent_network_has_zero_weight_in_main_performance_score():
    a = Runner(id=1, race_id=1, number=1, horse_name="ALPHA", weight_kg=56, draw=2)
    b = Runner(id=2, race_id=1, number=2, horse_name="BETA", weight_kg=56, draw=2)
    c = Runner(id=3, race_id=1, number=3, horse_name="GAMMA", weight_kg=56, draw=2)
    a.history = [
        history(1, 90, 2, [{"horse_name": "STRONG", "position": 3}, {"horse_name": "AUX A", "position": 4}]),
        history(1, 60, 2, [{"horse_name": "AUX B", "position": 3}, {"horse_name": "AUX C", "position": 4}]),
        history(1, 30, 2, [{"horse_name": "AUX D", "position": 3}, {"horse_name": "AUX E", "position": 4}]),
    ]
    b.history = [
        history(2, 90, 2, [{"horse_name": "WEAK", "position": 3}, {"horse_name": "AUX F", "position": 4}]),
        history(2, 60, 2, [{"horse_name": "AUX G", "position": 3}, {"horse_name": "AUX H", "position": 4}]),
        history(2, 30, 2, [{"horse_name": "AUX I", "position": 3}, {"horse_name": "AUX J", "position": 4}]),
    ]
    c.history = [
        history(3, 20, 4, [{"horse_name": "STRONG", "position": 1}, {"horse_name": "C1", "position": 2}, {"horse_name": "C2", "position": 3}], 50000),
        history(3, 10, 4, [{"horse_name": "C3", "position": 1}, {"horse_name": "C4", "position": 2}, {"horse_name": "C5", "position": 3}], 30000),
        history(3, 5, 4, [{"horse_name": "C6", "position": 1}, {"horse_name": "C7", "position": 2}, {"horse_name": "C8", "position": 3}], 30000),
    ]
    race = race_with(a, b, c)
    cards = score_race(race, [a, b, c])
    assert cards[1].performance == cards[2].performance
    assert cards[1].placed == cards[2].placed
    assert cards[1].breakdown["opponent_network"]["score"] != cards[2].breakdown["opponent_network"]["score"]
    assert cards[1].breakdown["opponent_network"]["affects_main_scores"] is False
