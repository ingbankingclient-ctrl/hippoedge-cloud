from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
import unicodedata
from typing import Any, Iterable

from .models import HorseHistory, Runner
from .utils import clip


# The finisher module deliberately ignores odds, tipsters, market ranks and
# provider editorial ratings.  It accepts only objective late-race evidence:
# intermediate positions, places gained in the final phase and sectional ranks.
# A final placing by itself can support an already observed late move, but can
# never create a "finisher" label on its own.

_POSITION_SEQUENCE_KEYS = {
    "positionsintermediaires",
    "positionsintermediairescourse",
    "intermediatepositions",
    "runningpositions",
    "positionsparcours",
    "positionparcours",
    "passages",
    "classementsintermediaires",
    "intermediateplaces",
}

_GAIN_KEYS = {
    "placesgagneesfin",
    "placesgagneesfincourse",
    "placesgagneesderniers400m",
    "placesgagneesderniers500m",
    "placesgagneesderniers600m",
    "finalgainplaces",
    "closinggainplaces",
    "lateplacesgained",
}

_SECTION_RANK_KEYS = {
    "rangderniertroncon",
    "rangderniers400m",
    "rangderniers500m",
    "rangderniers600m",
    "finalsectionalrank",
    "lastsectionalrank",
    "closingrank",
    "finishspeedrank",
}

# Explicitly opinion/editorial keys are never consulted, even if they slipped
# through a third-party feed.  Keeping the list here makes the firewall local to
# the feature instead of relying only on the global payload sanitiser.
_FORBIDDEN_TEXT_KEYS = {
    "notefindecourse",
    "commentaire",
    "commentairecourse",
    "commentaireaprescourse",
    "avis",
    "pronostic",
    "prediction",
    "editorial",
}


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    try:
        number = float(match.group().replace(",", "."))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _position_from_item(value: Any) -> int | None:
    if isinstance(value, dict):
        for candidate in ("position", "rang", "rank", "place", "classement"):
            if candidate in value:
                number = _number(value[candidate])
                if number is not None and number > 0:
                    return int(number)
        return None
    number = _number(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _flatten_positions(value: Any) -> list[int]:
    if isinstance(value, dict):
        # Preserve insertion order. Provider payloads generally publish passage
        # points chronologically; sorting arbitrary labels could reverse them.
        values = list(value.values())
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        # Accept compact factual strings such as "12-9-6-3" but never prose.
        text = str(value or "").strip()
        if not text or re.search(r"[A-Za-zÀ-ÿ]", text):
            return []
        values = re.findall(r"\d+", text)
    positions: list[int] = []
    for item in values:
        position = _position_from_item(item)
        if position is not None:
            positions.append(position)
    return positions


def _walk_facts(value: Any) -> tuple[list[list[int]], list[float], list[int]]:
    sequences: list[list[int]] = []
    gains: list[float] = []
    sectional_ranks: list[int] = []

    def walk(node: Any, parent_key: str = "") -> None:
        if isinstance(node, dict):
            for raw_key, raw_value in node.items():
                normalized = _key(raw_key)
                if normalized in _FORBIDDEN_TEXT_KEYS:
                    continue
                if normalized in _POSITION_SEQUENCE_KEYS:
                    positions = _flatten_positions(raw_value)
                    if positions:
                        sequences.append(positions)
                    continue
                if normalized in _GAIN_KEYS:
                    number = _number(raw_value)
                    if number is not None:
                        gains.append(number)
                    continue
                if normalized in _SECTION_RANK_KEYS:
                    number = _number(raw_value)
                    if number is not None and number > 0:
                        sectional_ranks.append(int(number))
                    continue
                walk(raw_value, normalized)
        elif isinstance(node, list):
            for item in node:
                walk(item, parent_key)

    walk(value)
    return sequences, gains, sectional_ranks


def _horse_name_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").upper())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def _event_token(row: HorseHistory) -> str:
    raw = row.raw if isinstance(row.raw, dict) else {}
    course_id = str(raw.get("geny_course_id") or raw.get("course_id") or raw.get("race_id") or "").strip()
    if course_id:
        return f"id:{course_id}"
    return "|".join([
        row.race_date.isoformat(),
        _horse_name_key(row.track),
        _horse_name_key(row.race_code),
        str(row.distance_m or ""),
    ])


def _opponent_position(row: HorseHistory, horse_name: str) -> int | None:
    target = _horse_name_key(horse_name)
    if not target:
        return None
    for opponent in row.opponents or []:
        if not isinstance(opponent, dict):
            continue
        label = (
            opponent.get("horse_name") or opponent.get("nom_cheval") or
            opponent.get("name") or opponent.get("nom") or ""
        )
        if _horse_name_key(label) != target:
            continue
        number = _number(opponent.get("position") or opponent.get("place") or opponent.get("rank"))
        if number is not None and number > 0:
            return int(number)
    return None


def _same_event(row: HorseHistory, evidence: dict[str, Any]) -> bool:
    token = str(evidence.get("event_token") or "")
    if token and token == _event_token(row):
        return True
    if str(evidence.get("date") or "") != row.race_date.isoformat():
        return False
    ev_track = _horse_name_key(evidence.get("track"))
    if ev_track and _horse_name_key(row.track) != ev_track:
        return False
    ev_distance = _number(evidence.get("distance_m"))
    if ev_distance is not None and row.distance_m is not None and int(ev_distance) != int(row.distance_m):
        return False
    return True


def _direct_positions(candidate: Runner, finisher: Runner, evidence: dict[str, Any]) -> tuple[int, int] | None:
    # Require an explicit same-race opponent link in at least one direction.
    for row in candidate.history:
        if not _same_event(row, evidence):
            continue
        opponent_position = _opponent_position(row, finisher.horse_name)
        if row.position is not None and opponent_position is not None:
            return int(row.position), int(opponent_position)
    for row in finisher.history:
        if not _same_event(row, evidence):
            continue
        opponent_position = _opponent_position(row, candidate.horse_name)
        if row.position is not None and opponent_position is not None:
            return int(opponent_position), int(row.position)
    return None


def objective_finisher_signature(history: Iterable[HorseHistory]) -> list[dict[str, Any]]:
    """Small stable signature used by the analysis fingerprint.

    Only late-race objective fields are retained.  Provider comments and market
    data cannot affect the signature or the resulting finisher block.
    """
    signature: list[dict[str, Any]] = []
    for row in sorted(history, key=lambda item: item.race_date, reverse=True):
        sequences, gains, sectional_ranks = _walk_facts(row.raw or {})
        if not (sequences or gains or sectional_ranks):
            continue
        signature.append({
            "date": row.race_date.isoformat(),
            "position": row.position,
            "event_token": _event_token(row),
            "distance_m": row.distance_m,
            "sequences": sequences[:4],
            "gains": gains[:4],
            "sectional_ranks": sectional_ranks[:4],
        })
    return signature


@dataclass
class FinisherProfile:
    score: float
    status: str
    eligible: bool
    evidence_runs: int
    strong_runs: int
    structured_runs: int
    contradiction_runs: int
    reasons: list[str]
    evidence: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "status": self.status,
            "eligible": self.eligible,
            "evidence_runs": self.evidence_runs,
            "strong_runs": self.strong_runs,
            "structured_runs": self.structured_runs,
            "contradiction_runs": self.contradiction_runs,
            "reasons": self.reasons[:5],
            "evidence": self.evidence[:8],
            "independent": True,
            "affects_scores": False,
            "data_policy": "positions_intermediaires_places_gagnees_sectionnels_uniquement",
        }


def _gain_score(gain: float) -> float:
    if gain >= 5:
        return 96.0
    if gain >= 4:
        return 91.0
    if gain >= 3:
        return 85.0
    if gain >= 2:
        return 76.0
    if gain >= 1:
        return 65.0
    return 42.0 if gain == 0 else max(15.0, 42.0 + gain * 8.0)


def _section_rank_score(rank: int) -> float:
    if rank == 1:
        return 97.0
    if rank == 2:
        return 90.0
    if rank == 3:
        return 83.0
    if rank == 4:
        return 73.0
    if rank == 5:
        return 64.0
    return max(35.0, 62.0 - (rank - 5) * 4.0)


def _late_gain_from_sequence(sequence: list[int], final_position: int | None) -> float | None:
    if not sequence or not final_position or final_position <= 0:
        return None
    # If the provider includes the official finish as the last point, use the
    # immediately preceding passage. Otherwise the last published passage is the
    # comparison point to the finish.
    if len(sequence) >= 2 and sequence[-1] == final_position:
        before = sequence[-2]
    else:
        before = sequence[-1]
    return float(before - final_position)


def finisher_profile(history: Iterable[HorseHistory]) -> FinisherProfile:
    rows = sorted(list(history), key=lambda item: item.race_date, reverse=True)[:12]
    evidence: list[dict[str, Any]] = []
    contradiction_runs = 0

    for index, row in enumerate(rows):
        sequences, explicit_gains, sectional_ranks = _walk_facts(row.raw or {})
        gains = list(explicit_gains)
        for sequence in sequences:
            late_gain = _late_gain_from_sequence(sequence, row.position)
            if late_gain is not None:
                gains.append(late_gain)

        signal_scores: list[float] = []
        best_gain = max(gains) if gains else None
        if best_gain is not None:
            signal_scores.append(_gain_score(best_gain))
            if best_gain < 0:
                contradiction_runs += 1
        best_sectional = min(sectional_ranks) if sectional_ranks else None
        if best_sectional is not None:
            signal_scores.append(_section_rank_score(best_sectional))

        if not signal_scores:
            continue

        race_score = sum(signal_scores) / len(signal_scores)
        # The official result may only support a detected late move; it can never
        # create one. A close podium finish slightly strengthens an existing
        # movement/sectional signal.
        if row.position is not None and row.position <= 3:
            race_score += 3.0
            if row.margin_to_winner is not None and row.margin_to_winner <= 3:
                race_score += 2.0
        race_score = clip(race_score)

        if race_score < 60:
            continue
        evidence.append({
            "date": row.race_date.isoformat(),
            "track": row.track,
            "event_token": _event_token(row),
            "distance_m": row.distance_m,
            "position": row.position,
            "margin_to_winner": row.margin_to_winner,
            "late_gain_places": round(best_gain, 1) if best_gain is not None else None,
            "sectional_rank": best_sectional,
            "score": round(race_score, 1),
            "recency_index": index,
        })

    if not evidence:
        return FinisherProfile(
            score=0.0,
            status="insufficient",
            eligible=False,
            evidence_runs=0,
            strong_runs=0,
            structured_runs=0,
            contradiction_runs=contradiction_runs,
            reasons=["Aucun déroulement final objectif exploitable"],
            evidence=[],
        )

    weights = [1.0, .86, .74, .64, .55, .47, .40, .35]
    weighted = 0.0
    weight_total = 0.0
    for i, item in enumerate(evidence[:8]):
        weight = weights[i] if i < len(weights) else .30
        weighted += float(item["score"]) * weight
        weight_total += weight
    base = weighted / weight_total if weight_total else 0.0
    strong_runs = sum(1 for item in evidence if float(item["score"]) >= 80)
    structured_runs = len(evidence)
    repeat_bonus = min(12.0, max(0, len(evidence) - 1) * 4.5)
    strong_bonus = min(7.0, strong_runs * 2.5)
    contradiction_penalty = min(10.0, contradiction_runs * 3.0)
    score = clip(base + repeat_bonus + strong_bonus - contradiction_penalty)

    confirmed = len(evidence) >= 2 and strong_runs >= 1 and score >= 72
    probable = len(evidence) >= 1 and score >= 62
    status = "confirmed" if confirmed else "probable" if probable else "insufficient"
    eligible = status in {"confirmed", "probable"}

    reasons: list[str] = []
    for item in sorted(evidence, key=lambda value: float(value["score"]), reverse=True)[:3]:
        date_label = str(item.get("date") or "")
        track = str(item.get("track") or "").strip()
        prefix = f"{date_label}{' à ' + track if track else ''}"
        if item.get("late_gain_places") is not None and float(item["late_gain_places"]) > 0:
            reasons.append(f"{prefix} : +{float(item['late_gain_places']):g} places dans la phase finale")
        elif item.get("sectional_rank"):
            reasons.append(f"{prefix} : {int(item['sectional_rank'])}e dernier tronçon/sectionnel")
    if confirmed:
        reasons.insert(0, f"Signal répété sur {len(evidence)} courses objectives")
    elif probable:
        reasons.insert(0, "Signal de fin de course objectif à confirmer")

    return FinisherProfile(
        score=score,
        status=status,
        eligible=eligible,
        evidence_runs=len(evidence),
        strong_runs=strong_runs,
        structured_runs=structured_runs,
        contradiction_runs=contradiction_runs,
        reasons=reasons,
        evidence=evidence,
    )


def rank_finisher_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return up to three finishers, with a mandatory current-race chance at #1.

    A horse can be a strong historical finisher without being a good bet/chance
    today.  The user's rule is therefore enforced structurally: no Top 3 is
    published unless at least one finisher also passes the independent
    ``beautiful_chance`` gate supplied by the main HippoEdge scores.
    """
    eligible = [item for item in candidates if item.get("eligible") is True]
    eligible.sort(
        key=lambda item: (
            float(item.get("finisher_score") or 0),
            int(item.get("evidence_runs") or 0),
            float(item.get("placed") or 0),
            float(item.get("performance") or 0),
        ),
        reverse=True,
    )
    chance_candidates = [item for item in eligible if item.get("beautiful_chance") is True]
    if not chance_candidates:
        return []
    first = chance_candidates[0]
    rest = [item for item in eligible if item is not first]
    return [first, *rest[:2]]


@dataclass
class LateMoverProfile:
    score: float
    status: str
    eligible: bool
    evidence_runs: int
    strong_runs: int
    contradiction_runs: int
    reasons: list[str]
    evidence: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "status": self.status,
            "eligible": self.eligible,
            "evidence_runs": self.evidence_runs,
            "strong_runs": self.strong_runs,
            "contradiction_runs": self.contradiction_runs,
            "reasons": self.reasons[:5],
            "evidence": self.evidence[:8],
            "independent": True,
            "affects_scores": False,
            "data_policy": "progression_tardive_positions_intermediaires_uniquement",
        }


def _late_mover_from_sequence(sequence: list[int], final_position: int | None) -> tuple[float, float, int, int] | None:
    """Return (gain before finish, final hold, anchor pos, pre-finish pos).

    A late mover is different from a pure finisher: it makes its move before the
    very last phase, then sustains that effort to the line.  Example 7→4→4:
    +3 places before the finish, then position held.  The signal is rejected if
    the horse gives back more than one place after making the move.
    """
    if len(sequence) < 2 or not final_position or final_position <= 0:
        return None
    if sequence[-1] == final_position and len(sequence) >= 3:
        pre_points = sequence[:-1]
    else:
        pre_points = sequence
    if len(pre_points) < 2:
        return None
    pre_finish = int(pre_points[-1])
    # Look only at the most recent observed part of the run, not an arbitrary
    # early-race position from many checkpoints ago.
    anchors = pre_points[max(0, len(pre_points) - 4):-1]
    if not anchors:
        return None
    anchor = max(int(value) for value in anchors)
    gain_before_finish = float(anchor - pre_finish)
    final_hold = float(pre_finish - int(final_position))
    return gain_before_finish, final_hold, anchor, pre_finish


def late_mover_profile(history: Iterable[HorseHistory]) -> LateMoverProfile:
    rows = sorted(list(history), key=lambda item: item.race_date, reverse=True)[:12]
    evidence: list[dict[str, Any]] = []
    contradiction_runs = 0

    for index, row in enumerate(rows):
        sequences, _explicit_gains, sectional_ranks = _walk_facts(row.raw or {})
        best: dict[str, Any] | None = None
        for sequence in sequences:
            movement = _late_mover_from_sequence(sequence, row.position)
            if movement is None:
                continue
            gain, hold, anchor, pre_finish = movement
            if gain < 2:
                continue
            if hold < -1:
                contradiction_runs += 1
                continue
            score = _gain_score(gain)
            # Holding the move is the defining feature. Continuing to gain in the
            # final phase strengthens it; losing one place is tolerated but penalised.
            score += 6.0 if hold >= 1 else 3.0 if hold == 0 else -6.0
            best_sectional = min(sectional_ranks) if sectional_ranks else None
            if best_sectional is not None and best_sectional <= 5:
                score = (score * 0.78) + (_section_rank_score(best_sectional) * 0.22)
            score = clip(score)
            candidate = {
                "date": row.race_date.isoformat(),
                "track": row.track,
                "position": row.position,
                "anchor_position": anchor,
                "pre_finish_position": pre_finish,
                "places_gained_before_finish": round(gain, 1),
                "final_hold_places": round(hold, 1),
                "sectional_rank": best_sectional,
                "score": round(score, 1),
                "recency_index": index,
            }
            if best is None or float(candidate["score"]) > float(best["score"]):
                best = candidate
        if best is not None and float(best["score"]) >= 62:
            evidence.append(best)

    if not evidence:
        return LateMoverProfile(
            score=0.0,
            status="insufficient",
            eligible=False,
            evidence_runs=0,
            strong_runs=0,
            contradiction_runs=contradiction_runs,
            reasons=["Aucune remontée tardive soutenue objectivement mesurable"],
            evidence=[],
        )

    weights = [1.0, .86, .74, .64, .55, .47, .40, .35]
    weighted = 0.0
    weight_total = 0.0
    for i, item in enumerate(evidence[:8]):
        weight = weights[i] if i < len(weights) else .30
        weighted += float(item["score"]) * weight
        weight_total += weight
    base = weighted / weight_total if weight_total else 0.0
    strong_runs = sum(1 for item in evidence if float(item["score"]) >= 80)
    repeat_bonus = min(10.0, max(0, len(evidence) - 1) * 4.0)
    contradiction_penalty = min(10.0, contradiction_runs * 3.0)
    score = clip(base + repeat_bonus + min(6.0, strong_runs * 2.0) - contradiction_penalty)
    confirmed = len(evidence) >= 2 and score >= 72
    probable = len(evidence) >= 1 and score >= 62
    status = "confirmed" if confirmed else "probable" if probable else "insufficient"

    reasons: list[str] = []
    if confirmed:
        reasons.append(f"Remontée tardive soutenue répétée sur {len(evidence)} courses")
    else:
        reasons.append("Signal de progression tardive à confirmer")
    for item in sorted(evidence, key=lambda value: float(value["score"]), reverse=True)[:3]:
        prefix = f"{item['date']}{' à ' + str(item['track']) if item.get('track') else ''}"
        anchor = int(item["anchor_position"])
        pre_finish = int(item["pre_finish_position"])
        final = int(item["position"]) if item.get("position") else None
        if final:
            reasons.append(
                f"{prefix} : {anchor}e → {pre_finish}e avant la phase finale puis {final}e à l'arrivée, effort soutenu"
            )

    return LateMoverProfile(
        score=score,
        status=status,
        eligible=status in {"confirmed", "probable"},
        evidence_runs=len(evidence),
        strong_runs=strong_runs,
        contradiction_runs=contradiction_runs,
        reasons=reasons,
        evidence=evidence,
    )


def rank_late_mover_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank up to three progressifs tardifs, with a real current chance at #1."""
    eligible = [item for item in candidates if item.get("eligible") is True]
    eligible.sort(
        key=lambda item: (
            float(item.get("late_mover_score") or 0),
            int(item.get("evidence_runs") or 0),
            float(item.get("placed") or 0),
            float(item.get("performance") or 0),
        ),
        reverse=True,
    )
    chance_candidates = [item for item in eligible if item.get("beautiful_chance") is True]
    if not chance_candidates:
        return []
    first = chance_candidates[0]
    rest = [item for item in eligible if item is not first]
    return [first, *rest[:2]]


@dataclass
class FinisherResistanceProfile:
    score: float
    status: str
    eligible: bool
    support_runs: int
    unique_finishers: int
    counter_runs: int
    reasons: list[str]
    evidence: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "status": self.status,
            "eligible": self.eligible,
            "support_runs": self.support_runs,
            "unique_finishers": self.unique_finishers,
            "counter_runs": self.counter_runs,
            "reasons": self.reasons[:6],
            "evidence": self.evidence[:10],
            "independent": True,
            "affects_scores": False,
            "data_policy": "confrontations_directes_uniquement_avec_finisseur_objectivement_demontre",
        }


def finisher_resistance_profile(
    candidate: Runner,
    current_runners: Iterable[Runner],
    finisher_blocks: dict[int, dict[str, Any]],
) -> FinisherResistanceProfile:
    """Measure whether a horse has already resisted current-race finishers.

    A resistance signal is accepted only when the *same historical race* is an
    objective finisher-evidence run for the rival and the candidate actually
    finished ahead of that rival.  Merely having beaten the horse on another day
    does not count.  Editorial comments, odds and market ranks are never used.
    """
    supports: list[dict[str, Any]] = []
    counters: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, str]] = set()

    for finisher in current_runners:
        if finisher.id == candidate.id:
            continue
        block = finisher_blocks.get(finisher.id) or {}
        if block.get("eligible") is not True:
            continue
        for evidence in block.get("evidence") or []:
            if not isinstance(evidence, dict):
                continue
            signal_gain = _number(evidence.get("late_gain_places"))
            sectional = _number(evidence.get("sectional_rank"))
            evidence_score = _number(evidence.get("score")) or 0.0
            if not ((signal_gain is not None and signal_gain > 0) or (sectional is not None and sectional <= 5)):
                continue
            positions = _direct_positions(candidate, finisher, evidence)
            if positions is None:
                continue
            candidate_pos, finisher_pos = positions
            pair_key = (int(finisher.id or 0), str(evidence.get("event_token") or evidence.get("date") or ""))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            payload = {
                "date": evidence.get("date"),
                "track": evidence.get("track"),
                "event_token": evidence.get("event_token"),
                "candidate_position": candidate_pos,
                "finisher_number": finisher.number,
                "finisher_name": finisher.horse_name,
                "finisher_position": finisher_pos,
                "finisher_run_score": round(float(evidence_score), 1),
                "finisher_late_gain_places": signal_gain,
                "finisher_sectional_rank": int(sectional) if sectional is not None else None,
            }
            if candidate_pos < finisher_pos:
                gap = max(1, finisher_pos - candidate_pos)
                run_score = 60.0 + min(18.0, max(0.0, evidence_score - 60.0) * .45) + min(8.0, gap * 2.0)
                if signal_gain is not None and signal_gain >= 3:
                    run_score += 4.0
                if sectional is not None and sectional <= 2:
                    run_score += 4.0
                payload["score"] = round(clip(run_score), 1)
                supports.append(payload)
            elif finisher_pos < candidate_pos:
                payload["score"] = round(clip(55.0 + max(0.0, evidence_score - 60.0) * .30), 1)
                counters.append(payload)

    if not supports:
        return FinisherResistanceProfile(
            score=0.0,
            status="insufficient",
            eligible=False,
            support_runs=0,
            unique_finishers=0,
            counter_runs=len(counters),
            reasons=["Aucune confrontation directe où ce cheval a contenu un finisseur objectivement démontré"],
            evidence=[],
        )

    supports.sort(key=lambda item: float(item.get("score") or 0), reverse=True)
    base = sum(float(item.get("score") or 0) for item in supports[:5]) / min(5, len(supports))
    unique_finishers = len({int(item["finisher_number"]) for item in supports})
    repeat_bonus = min(10.0, max(0, len(supports) - 1) * 3.5)
    diversity_bonus = min(12.0, max(0, unique_finishers - 1) * 6.0)
    counter_penalty = min(12.0, len(counters) * 3.0)
    score = clip(base + repeat_bonus + diversity_bonus - counter_penalty)
    confirmed = (unique_finishers >= 2 or len(supports) >= 2) and score >= 72
    probable = score >= 62
    status = "confirmed" if confirmed else "probable" if probable else "insufficient"

    reasons: list[str] = []
    if unique_finishers >= 2:
        reasons.append(f"A déjà résisté à {unique_finishers} finisseurs distincts présents aujourd'hui")
    elif len(supports) >= 2:
        reasons.append(f"Résistance répétée sur {len(supports)} confrontations directes")
    else:
        reasons.append("Une résistance directe objectivement vérifiée à un finisseur du lot")
    for item in supports[:3]:
        date_label = str(item.get("date") or "")
        track = str(item.get("track") or "").strip()
        rival = f"n°{item['finisher_number']} {item['finisher_name']}"
        detail = ""
        gain = _number(item.get("finisher_late_gain_places"))
        sectional = _number(item.get("finisher_sectional_rank"))
        if gain is not None and gain > 0:
            detail = f", malgré +{gain:g} places gagnées par ce rival dans la phase finale"
        elif sectional is not None:
            detail = f", malgré son {int(sectional)}e meilleur dernier tronçon/sectionnel"
        reasons.append(
            f"{date_label}{' à ' + track if track else ''} : {item['candidate_position']}e devant {rival} ({item['finisher_position']}e){detail}"
        )
    if counters:
        reasons.append(f"Contre-signal : {len(counters)} confrontation(s) où un finisseur du lot l'a devancé")

    return FinisherResistanceProfile(
        score=score,
        status=status,
        eligible=status in {"confirmed", "probable"},
        support_runs=len(supports),
        unique_finishers=unique_finishers,
        counter_runs=len(counters),
        reasons=reasons,
        evidence=supports,
    )


def rank_finisher_resistance_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank up to three proven resistants; no result is manufactured to fill 3 slots."""
    eligible = [item for item in candidates if item.get("eligible") is True]
    eligible.sort(
        key=lambda item: (
            float(item.get("resistance_score") or 0),
            int(item.get("unique_finishers") or 0),
            int(item.get("support_runs") or 0),
            float(item.get("placed") or 0),
            float(item.get("performance") or 0),
        ),
        reverse=True,
    )
    return eligible[:3]
