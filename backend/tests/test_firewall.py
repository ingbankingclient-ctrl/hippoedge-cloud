from app.utils import sanitize_objective_payload
from app.utils import parse_iso_or_local, to_float


def test_market_and_prediction_fields_are_removed_recursively():
    raw={"cheval":"A","cote":3.2,"Note_IA":95,"nested":{"popularite":99,"record":"1'13\"2"},"pronostics":[1,2,3]}
    out=sanitize_objective_payload(raw)
    assert out["cheval"]=="A"
    assert "cote" not in out
    assert "Note_IA" not in out
    assert "popularite" not in out["nested"]
    assert out["nested"]["record"]=="1'13\"2"
    assert "pronostics" not in out


def test_firewall_blocks_english_and_numbered_external_selection_aliases():
    out = sanitize_objective_payload({
        "selection_8": [1, 2, 3],
        "Sélection_9": [4],
        "favoriteRank": 1,
        "predictionsExternes": [4],
        "external_score": 98,
        "record": "1'14\"2",
    })
    assert out == {"record": "1'14\"2"}


def test_iso_schedule_is_not_prefixed_with_the_date_twice():
    assert parse_iso_or_local("2026-09-02", "2026-09-02T14:30").hour == 14
    assert parse_iso_or_local("2026-09-02", "14:30").minute == 30
    assert parse_iso_or_local("2026-09-02", "2026-09-02T12:00:00Z").hour == 14


def test_objective_arrival_key_is_not_confused_with_editorial_ranking():
    out = sanitize_objective_payload({
        "classement": [{"numPmu": 4, "rang": 1}],
        "classement_externe": [4, 2],
        "classement_presse": [2, 4],
    })
    assert out["classement"] == [{"numPmu": 4, "rang": 1}]
    assert "classement_externe" not in out
    assert "classement_presse" not in out


def test_numeric_provider_values_are_localized_and_finite():
    assert to_float("35 000 €") == 35000
    assert to_float("1\u202f234,5 kg") == 1234.5
    assert to_float(float("nan")) is None
