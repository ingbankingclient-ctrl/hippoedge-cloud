from datetime import date, datetime, timedelta
from app.database import Base
from app.models import Meeting, Race, Runner, HorseHistory
from app.scoring import progression_score, score_race, weighted_form


def h(runner_id, days, pos, dq=False, chrono=None):
    return HorseHistory(runner_id=runner_id,race_date=date.today()-timedelta(days=days),position=pos,disqualified=dq,chrono_km_seconds=chrono,discipline="Trot attelé",distance_m=2100,class_name="Course D")


def test_fault_penalizes_placed_more_than_performance():
    m=Meeting(id=1,race_date=date.today(),code="R1",track="Vincennes")
    race=Race(id=1,meeting=m,meeting_id=1,code="R1C1",name="x",scheduled_at=datetime.now(),discipline="Trot attelé",distance_m=2100,class_name="Course D",start_type="Autostart")
    a=Runner(id=1,race_id=1,number=1,horse_name="A",start_position=3,record_km_seconds=73.0)
    a.history=[h(1,10,None,True),h(1,30,2,False,73.2),h(1,50,1,False,73.4),h(1,70,3,False,73.6)]
    b=Runner(id=2,race_id=1,number=2,horse_name="B",start_position=4,record_km_seconds=74.0)
    b.history=[h(2,10,4,False,74.0),h(2,30,4,False,74.1),h(2,50,4,False,74.2),h(2,70,4,False,74.0)]
    cards=score_race(race,[a,b])
    assert cards[1].performance > cards[1].placed - 5  # value remains alive despite DQ
    assert cards[1].breakdown["dq_risk"] > cards[2].breakdown["dq_risk"]


def test_indirect_lines_never_dominate():
    m=Meeting(id=1,race_date=date.today(),code="R1",track="X")
    race=Race(id=1,meeting=m,meeting_id=1,code="R1C1",name="x",scheduled_at=datetime.now(),discipline="Plat",distance_m=2400,class_name="Handicap")
    a=Runner(id=1,race_id=1,number=1,horse_name="A",weight_kg=58,draw=3)
    a.history=[HorseHistory(runner_id=1,race_date=date.today()-timedelta(days=10),position=8,opponents=[{"later_wins":3,"later_places":3}])]
    b=Runner(id=2,race_id=1,number=2,horse_name="B",weight_kg=58,draw=4)
    b.history=[HorseHistory(runner_id=2,race_date=date.today()-timedelta(days=10),position=2,opponents=[])]
    cards=score_race(race,[a,b])
    assert cards[2].performance > cards[1].performance


def test_each_horse_gets_a_factual_paragraph():
    m=Meeting(id=1,race_date=date.today(),code="R1",track="Vincennes")
    race=Race(id=1,meeting=m,meeting_id=1,code="R1C1",name="x",scheduled_at=datetime.now(),discipline="Trot attelé",distance_m=2100)
    runner=Runner(id=1,race_id=1,number=7,horse_name="TEST DU JOUR",recent_form="2a1a",ferrure="D4")
    runner.history=[h(1,10,2,False,73.2),h(1,35,1,False,73.5)]
    card=score_race(race,[runner])[1]
    paragraph=card.breakdown["analysis_text"]
    assert "n°7 TEST DU JOUR" in paragraph
    assert "2 performances documentées" in paragraph
    assert "distance 2100 m" in paragraph
    assert "ferrure D4" in paragraph
    assert "potentiel caché" in paragraph.lower()


def test_two_runs_zero_then_sixth_do_not_create_an_exceptional_progression():
    # Chronological music is 0p -> 6p.  This is an improvement, not proof of a
    # 98/100 progression curve from a single transition.
    history=[h(1,10,6),h(1,35,None)]
    assert progression_score(history) <= 60


def test_official_music_is_used_when_detailed_history_is_temporarily_missing():
    meeting=Meeting(id=1,race_date=date.today(),code="R1",track="Deauville")
    race=Race(id=1,meeting=meeting,meeting_id=1,code="R1C1",name="x",scheduled_at=datetime.now(),discipline="Plat",distance_m=1600)
    runner=Runner(id=1,race_id=1,number=4,horse_name="MUSIQUE OFFICIELLE",recent_form="1p2p5p")
    card=score_race(race,[runner])[1]
    assert card.breakdown["sample_size"] == 3
    assert card.breakdown["history_rows"] == 0
    assert card.performance > 50
    assert "Musique officielle" in " ".join(card.reasons)
    assert weighted_form([], "1p2p5p") > 70
