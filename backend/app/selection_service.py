from __future__ import annotations

from typing import Callable, Iterable
import math

from .utils import clip


PUBLIC_FIELDS = (
    "meeting_code",
    "track",
    "race_id",
    "race_code",
    "race_name",
    "number",
    "horse_name",
    "performance",
    "placed",
    "hidden_potential",
    "robustness",
    "uncertainty",
    "history_rows",
    "evidence_status",
    "data_confidence",
)


def _number(item: dict, key: str, default: float = 50.0) -> float:
    try:
        value = item.get(key, default)
        number = float(default if value is None else value)
        return float(default) if not math.isfinite(number) else number
    except (TypeError, ValueError):
        return float(default)


def _sample_size(item: dict) -> int:
    try:
        return max(0, int(item.get("sample_size") or 0))
    except (TypeError, ValueError):
        return 0


def _race_rank(item: dict) -> int:
    try:
        return max(0, int(item.get("race_rank") or 0))
    except (TypeError, ValueError):
        return 0


def _history_rows(item: dict) -> int:
    try:
        return max(0, int(item.get("history_rows") or 0))
    except (TypeError, ValueError):
        return 0


def _confidence(item: dict) -> float:
    return clip(100 - _number(item, "uncertainty", 65))


def _evidence_weight(item: dict, *, placed: bool = False) -> float:
    """Return how much a raw score may move away from the neutral prior.

    A short career is not an exclusion.  It simply leaves more of the score at
    the neutral 50/100 prior until strong results confirm the profile.
    """
    n = _sample_size(item)
    base = (0.38 + n * 0.085) if placed else (0.48 + n * 0.07)
    proof = max(
        _number(item, "form"),
        _number(item, "class_score"),
        _number(item, "aptitude"),
    )
    if proof >= 82:
        base += 0.05
    return clip(base, 0.38 if placed else 0.48, 1.0)


def _confirmed(raw: float, item: dict, *, placed: bool = False) -> float:
    weight = _evidence_weight(item, placed=placed)
    return clip(50 + (raw - 50) * weight)


def performance_selection_index(item: dict) -> float:
    """Cross-race index for Best of meeting / Horse of the day.

    The raw Performance score remains important, but it is confronted with
    documentary depth, current form, class, aptitude, scenario robustness and
    uncertainty before horses from different races are compared.
    """
    n = _sample_size(item)
    uncertainty = _number(item, "uncertainty", 65)
    raw = _number(item, "performance")
    confirmed = _confirmed(raw, item)
    form = _number(item, "form")
    cls = _number(item, "class_score")
    aptitude = _number(item, "aptitude")
    robust = _number(item, "robustness")
    hidden = _number(item, "hidden_potential")
    value = (
        confirmed * 0.56
        + form * 0.13
        + cls * 0.09
        + aptitude * 0.07
        + robust * 0.07
        + _confidence(item) * 0.05
        + hidden * 0.03
    )
    # Keep exceptional lightly-raced horses eligible, but do not promote a
    # merely less-bad result (for example 0p -> 6p) as a daily certainty.
    strongest_proof = max(form, cls, aptitude)
    if n <= 2 and strongest_proof < 70:
        value -= 5
    if n <= 3 and uncertainty >= 65:
        value -= 2
    if n <= 3 and form < 50:
        value -= 2
    # A two-run profile with no strong objective proof must not become the
    # Horse of the day merely because the rest of the field is incomplete.
    # Exceptional lightly-raced profiles remain eligible when form, class or
    # aptitude itself supplies that proof.
    if n <= 2 and strongest_proof < 70:
        value = min(value, 54.0)
    elif n <= 3 and max(form, cls, aptitude) < 60 and uncertainty >= 65:
        value = min(value, 57.0)
    return round(clip(value), 1)


def placed_selection_index(item: dict) -> float:
    """Reliability-first index for Best placed selection."""
    n = _sample_size(item)
    uncertainty = _number(item, "uncertainty", 65)
    confirmed = _confirmed(_number(item, "placed"), item, placed=True)
    robust = _number(item, "robustness")
    consistency = _number(item, "consistency", 45)
    form = _number(item, "form")
    aptitude = _number(item, "aptitude")
    cls = _number(item, "class_score")
    value = (
        confirmed * 0.44
        + robust * 0.18
        + consistency * 0.13
        + form * 0.10
        + _confidence(item) * 0.08
        + aptitude * 0.05
        + cls * 0.02
    )
    if n <= 2 and max(form, consistency) < 75:
        value -= 6
    if n <= 3 and uncertainty >= 65:
        value -= 3
    if n <= 2 and max(form, consistency, aptitude) < 70:
        value = min(value, 54.0)
    return round(clip(value), 1)


def outsider_selection_index(item: dict) -> float:
    confirmed = _confirmed(_number(item, "performance"), item)
    return round(
        clip(
            _number(item, "hidden_potential") * 0.30
            + confirmed * 0.28
            + _number(item, "robustness") * 0.16
            + _number(item, "form") * 0.08
            + _number(item, "class_score") * 0.08
            + _confidence(item) * 0.06
            + _number(item, "progression") * 0.04
        ),
        1,
    )


def tocard_selection_index(item: dict) -> float:
    # The tocard is intentionally speculative.  Unlike "placed", uncertainty
    # is a feature here, while some internal performance proof remains required.
    return round(
        clip(
            _number(item, "hidden_potential") * 0.37
            + _number(item, "uncertainty", 65) * 0.22
            + _confirmed(_number(item, "performance"), item) * 0.18
            + _number(item, "progression") * 0.10
            + _number(item, "class_score") * 0.08
            + _number(item, "robustness") * 0.05
        ),
        1,
    )


def heart_selection_index(item: dict) -> float:
    return round(
        clip(
            _confirmed(_number(item, "performance"), item) * 0.30
            + _number(item, "hidden_potential") * 0.20
            + _number(item, "robustness") * 0.18
            + _number(item, "form") * 0.12
            + _number(item, "class_score") * 0.08
            + _confidence(item) * 0.08
            + _number(item, "aptitude") * 0.04
        ),
        1,
    )


INDEXERS: dict[str, Callable[[dict], float]] = {
    "horse": performance_selection_index,
    "placed": placed_selection_index,
    "outsider": outsider_selection_index,
    "tocard": tocard_selection_index,
    "heart": heart_selection_index,
}


def _pool(items: list[dict], kind: str) -> list[dict]:
    if kind == "outsider":
        # An outsider is defined relative to its own race.  If a meeting or a
        # day contains no horse outside a Top 3 (for example a tiny test
        # field), publish no outsider rather than relabelling a favourite.
        return [x for x in items if _race_rank(x) > 3]
    if kind == "tocard":
        speculative = [
            x
            for x in items
            if _race_rank(x) > 5
            and _number(x, "hidden_potential") >= 50
        ]
        return speculative
    return items


def _eligible(item: dict, kind: str) -> bool:
    """Prevent a thin neutral dossier from becoming a public daily choice."""
    n = _sample_size(item)
    detailed = _history_rows(item)
    if n <= 0 or detailed <= 0 or item.get("ranking_eligible") is False:
        return False
    strongest = max(
        _number(item, "form"),
        _number(item, "class_score"),
        _number(item, "aptitude"),
    )
    if kind == "placed":
        placed_proof = max(strongest, _number(item, "consistency"))
        return detailed >= 3 or (detailed >= 2 and placed_proof >= 82)
    if kind in {"horse", "heart"}:
        return detailed >= 3 or (detailed >= 2 and strongest >= 82)
    # Outsider and tocard remain speculative, but two objective observations
    # are the strict minimum before the label is shown to a client.
    return detailed >= 2


def _reason(kind: str, item: dict, score: float) -> str:
    n = _sample_size(item)
    confidence = _confidence(item)
    detailed = _history_rows(item)
    if detailed:
        evidence = f"{detailed} performance{'s' if detailed != 1 else ''} détaillée{'s' if detailed != 1 else ''}"
    else:
        evidence = f"{n} résultat{'s' if n != 1 else ''} officiel{'s' if n != 1 else ''}, avec contexte encore partiel"
    if kind == "horse":
        basis = "performance confirmée, forme, classe, aptitude et robustesse"
    elif kind == "placed":
        basis = "score placé confirmé, régularité, robustesse et maîtrise de l’incertitude"
    elif kind == "outsider":
        basis = "potentiel caché, valeur interne et capacité à dépasser son rang de course"
    elif kind == "tocard":
        basis = "potentiel spéculatif et volatilité, avec un minimum de preuve interne"
    else:
        basis = "équilibre entre valeur, potentiel caché, robustesse et confiance"
    suffix = (
        " Échantillon court : le potentiel reste admis, mais la note est réajustée."
        if n <= 3
        else ""
    )
    return (
        f"Retenu après examen de {evidence}. La décision repose sur {basis}. "
        f"Fiabilité des données : {confidence:.0f}/100.{suffix}"
    )


def selection_card(item: dict | None, kind: str) -> dict | None:
    if not item:
        return None
    score = INDEXERS[kind](item)
    card = {key: item.get(key) for key in PUBLIC_FIELDS}
    card.update(
        {
            "selection_kind": kind,
            "selection_score": score,
            "selection_confidence": round(_confidence(item), 1),
            "sample_size": _sample_size(item),
            "selection_reason": _reason(kind, item, score),
        }
    )
    return card


def choose(items: Iterable[dict], kind: str) -> dict | None:
    # Every designation must rest on at least one objective performance. A
    # neutral/empty score is not enough to manufacture an outsider or a tocard.
    documented = [item for item in items if _eligible(item, kind)]
    candidates = _pool(documented, kind)
    if not candidates:
        return None
    indexer = INDEXERS[kind]
    return selection_card(max(candidates, key=indexer), kind)
