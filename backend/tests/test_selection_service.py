from app.selection_service import choose, performance_selection_index, placed_selection_index


def candidate(name, **overrides):
    item={
        "meeting_code":"R1","track":"TEST","race_id":1,"race_code":"C1","race_name":"Course",
        "number":1,"horse_name":name,"performance":60,"placed":60,"hidden_potential":52,
        "robustness":55,"uncertainty":65,"race_rank":1,"sample_size":2,"form":49,
        "consistency":42,"progression":57,"aptitude":50,"class_score":50,"dq_risk":0,
    }
    item.update(overrides)
    return item


def test_weak_two_run_profile_does_not_beat_documented_daily_reference():
    short=candidate("DEUX COURSES 6P 0P",performance=66,placed=65)
    proven=candidate(
        "REFERENCE SOLIDE",number=2,performance=64,placed=68,hidden_potential=55,
        robustness=74,uncertainty=24,sample_size=9,form=72,consistency=78,
        progression=58,aptitude=70,class_score=68,
    )
    assert performance_selection_index(proven) > performance_selection_index(short)
    assert placed_selection_index(proven) > placed_selection_index(short)
    assert choose([short,proven],"horse")["horse_name"] == "REFERENCE SOLIDE"
    assert choose([short,proven],"placed")["horse_name"] == "REFERENCE SOLIDE"


def test_exceptional_lightly_raced_horse_remains_eligible():
    exceptional=candidate(
        "JEUNE EXCEPTIONNEL",performance=88,placed=79,hidden_potential=76,
        robustness=67,uncertainty=68,sample_size=2,form=95,consistency=90,
        progression=68,aptitude=82,class_score=84,
    )
    ordinary=candidate(
        "CHEVAL DOCUMENTE",number=2,performance=65,placed=67,hidden_potential=54,
        robustness=70,uncertainty=25,sample_size=10,form=67,consistency=72,
        progression=54,aptitude=66,class_score=64,
    )
    assert choose([ordinary,exceptional],"horse")["horse_name"] == "JEUNE EXCEPTIONNEL"


def test_selection_card_explains_the_reasoning_and_sample_size():
    pick=choose([candidate("EXPLIQUE")],"horse")
    assert pick["sample_size"] == 2
    assert pick["selection_score"] == performance_selection_index(candidate("EXPLIQUE"))
    assert "Échantillon court" in pick["selection_reason"]
    assert "Confiance documentaire" in pick["selection_reason"]


def test_undocumented_field_does_not_create_a_daily_pick():
    assert choose([candidate("SANS HISTORIQUE", sample_size=0)], "horse") is None


def test_no_designation_kind_is_published_without_objective_evidence():
    item = candidate("AUCUNE PREUVE", sample_size=0)
    for kind in ("placed", "outsider", "tocard", "heart"):
        assert choose([item], kind) is None


def test_outsider_and_tocard_are_not_fabricated_without_an_outside_rank():
    items = [candidate("A", race_rank=1), candidate("B", race_rank=2), candidate("C", race_rank=3)]
    assert choose(items, "outsider") is None
    assert choose(items, "tocard") is None
