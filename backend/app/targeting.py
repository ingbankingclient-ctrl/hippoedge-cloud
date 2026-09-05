from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import re
import unicodedata
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import HorseHistory, Meeting, Race, Runner, RunnerScore


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _same_class(left: str | None, right: str | None) -> bool:
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _history_race_name(history: HorseHistory) -> str:
    raw = history.raw if isinstance(history.raw, dict) else {}
    for key in ("nom_course", "race_name", "prix", "race", "course_name", "nomPrix", "nomEpreuve"):
        value = raw.get(key)
        if value:
            return str(value)
    return str(history.race_code or "")


def _horse_key(runner: Runner) -> str:
    if runner.horse_external_id:
        return f"id:{str(runner.horse_external_id).strip()}"
    return f"name:{_norm(runner.horse_name)}"


def _future_engagements_for_runners(db: Session, race: Race, runners: list[Runner]) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    end_date = race.meeting.race_date + timedelta(days=max(1, int(settings.future_engagement_days)))
    ids = sorted({str(r.horse_external_id).strip() for r in runners if r.horse_external_id})
    names = sorted({r.horse_name for r in runners if not r.horse_external_id and r.horse_name})
    if not ids and not names:
        return {}
    identity_clauses = []
    if ids:
        identity_clauses.append(Runner.horse_external_id.in_(ids))
    if names:
        identity_clauses.append(Runner.horse_name.in_(names))
    rows = db.execute(
        select(Runner, Race, Meeting)
        .join(Race, Runner.race_id == Race.id)
        .join(Meeting, Race.meeting_id == Meeting.id)
        .where(
            or_(*identity_clauses),
            Meeting.race_date <= end_date,
            Race.scheduled_at > race.scheduled_at,
            Runner.scratched.is_(False),
        )
        .order_by(Race.scheduled_at, Race.id)
    ).all()
    result: dict[str, list[dict[str, Any]]] = {}
    for future_runner, future_race, meeting in rows:
        key = _horse_key(future_runner)
        bucket = result.setdefault(key, [])
        if len(bucket) >= 4:
            continue
        days_after = (meeting.race_date - race.meeting.race_date).days
        bucket.append({
            "date": meeting.race_date.isoformat(),
            "days_after": days_after,
            "meeting": meeting.code,
            "track": meeting.track,
            "race_code": future_race.code,
            "race_name": future_race.name,
            "scheduled_at": future_race.scheduled_at.isoformat(),
            "distance_m": future_race.distance_m,
            "discipline": future_race.discipline,
            "class_name": future_race.class_name,
            "status": future_race.status,
        })
    return result


def _future_engagements_for_runner(db: Session, race: Race, runner: Runner) -> list[dict[str, Any]]:
    settings = get_settings()
    end_date = race.meeting.race_date + timedelta(days=max(1, int(settings.future_engagement_days)))
    conditions = [Meeting.race_date <= end_date, Race.scheduled_at > race.scheduled_at, Runner.scratched.is_(False)]
    if runner.horse_external_id:
        identity = Runner.horse_external_id == runner.horse_external_id
    else:
        identity = Runner.horse_name == runner.horse_name
    rows = db.execute(
        select(Runner, Race, Meeting)
        .join(Race, Runner.race_id == Race.id)
        .join(Meeting, Race.meeting_id == Meeting.id)
        .where(and_(identity, *conditions))
        .order_by(Race.scheduled_at, Race.id)
        .limit(4)
    ).all()
    items: list[dict[str, Any]] = []
    for _future_runner, future_race, meeting in rows:
        days_after = (meeting.race_date - race.meeting.race_date).days
        items.append({
            "date": meeting.race_date.isoformat(),
            "days_after": days_after,
            "meeting": meeting.code,
            "track": meeting.track,
            "race_code": future_race.code,
            "race_name": future_race.name,
            "scheduled_at": future_race.scheduled_at.isoformat(),
            "distance_m": future_race.distance_m,
            "discipline": future_race.discipline,
            "class_name": future_race.class_name,
            "status": future_race.status,
        })
    return items


def _format_future(item: dict[str, Any]) -> str:
    day = int(item.get("days_after") or 0)
    j = f"J+{day}"
    course = str(item.get("race_code") or "course")
    track = str(item.get("track") or "hippodrome non renseigné")
    distance = f" {int(item['distance_m'])} m" if item.get("distance_m") else ""
    return f"{j} · {track} {course}{distance}"


def target_profile(
    db: Session,
    race: Race,
    runner: Runner,
    score: RunnerScore,
    future_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Independent 'course ciblée / engagements' reading.

    This never infers private stable intent.  It only exposes objective scheduling
    coherence: return to a proven track/distance/class, exact named-race repeats
    when published, continuity of distance, equipment change, and already-known
    later engagements.  It has zero weight in every main score.
    """
    history = sorted(runner.history, key=lambda row: row.race_date, reverse=True)
    current_track = _norm(race.meeting.track if race.meeting else "")
    current_name = _norm(race.name)
    current_dist = int(race.distance_m or runner.distance_m or 0)

    exact_named: list[HorseHistory] = []
    same_track_distance: list[HorseHistory] = []
    same_track_distance_class: list[HorseHistory] = []
    positive_track_distance: list[HorseHistory] = []
    recent_distance_matches = 0
    for index, row in enumerate(history):
        row_track = _norm(row.track)
        row_name = _norm(_history_race_name(row))
        close_distance = bool(current_dist and row.distance_m and abs(int(row.distance_m) - current_dist) <= 100)
        same_track = bool(current_track and row_track == current_track)
        if current_name and row_name and (current_name == row_name or (len(current_name) >= 8 and current_name in row_name) or (len(row_name) >= 8 and row_name in current_name)):
            exact_named.append(row)
        if same_track and close_distance:
            same_track_distance.append(row)
            if row.position is not None and 1 <= int(row.position) <= 3 and not row.disqualified:
                positive_track_distance.append(row)
            if _same_class(row.class_name, race.class_name):
                same_track_distance_class.append(row)
        if index < 4 and close_distance:
            recent_distance_matches += 1

    latest = history[0] if history else None
    equipment_change = bool(
        latest and runner.equipment and latest.equipment
        and _norm(runner.equipment) != _norm(latest.equipment)
    )
    future = future_override if future_override is not None else _future_engagements_for_runner(db, race, runner)

    # This score orders only this independent block. It NEVER enters Performance,
    # Placé, hidden potential, robustness, uncertainty or the final verdict.
    block_score = 42.0
    if exact_named:
        block_score += 24
    if same_track_distance_class:
        block_score += 14
    if positive_track_distance:
        block_score += 14
    elif same_track_distance:
        block_score += 7
    if recent_distance_matches >= 2:
        block_score += 6
    if future:
        block_score += 3
    block_score = min(100.0, block_score)

    reasons: list[str] = []
    if exact_named:
        best = next((row for row in exact_named if row.position and row.position <= 3 and not row.disqualified), exact_named[0])
        pos = f"{best.position}e" if best.position else "déjà courue"
        reasons.append(f"Retour sur une épreuve portant le même intitulé, {pos} lors de la référence retrouvée")
    if positive_track_distance:
        best = min(positive_track_distance, key=lambda row: int(row.position or 99))
        reasons.append(
            f"Référence déjà positive sur {race.meeting.track} autour de {current_dist} m ({int(best.position)}e)"
        )
    elif same_track_distance:
        reasons.append(f"Retour sur {race.meeting.track} autour de {current_dist} m déjà expérimenté")
    if same_track_distance_class:
        reasons.append("Même combinaison hippodrome/distance avec catégorie comparable déjà rencontrée")
    if recent_distance_matches >= 2:
        reasons.append(f"Programme récent cohérent : {recent_distance_matches} des 4 dernières sorties sont dans la même zone de distance")
    if equipment_change:
        reasons.append(f"Changement d'équipement constaté aujourd'hui ({latest.equipment} → {runner.equipment})")
    if future:
        reasons.append("Prochain(s) engagement(s) déjà publié(s) : " + "; ".join(_format_future(item) for item in future[:2]))
    if not reasons:
        reasons.append("Aucun indice objectif suffisamment précis pour qualifier cette course de rendez-vous ciblé")

    if exact_named and positive_track_distance:
        status = "signal_fort"
        label = "FORT SIGNAL DE RENDEZ-VOUS"
    elif positive_track_distance or same_track_distance_class or recent_distance_matches >= 2:
        status = "coherent"
        label = "ENGAGEMENT TRÈS COHÉRENT"
    elif future or same_track_distance:
        status = "informatif"
        label = "SIGNAL INFORMATIF"
    else:
        status = "non_determine"
        label = "NON DÉTERMINÉ"

    if status == "non_determine":
        argument = (
            "Aucune preuve objective ne permet d'affirmer que cette course est spécialement visée. "
            "HippoEdge refuse d'inventer une intention d'entourage."
        )
    else:
        argument = ". ".join(reasons[:5]).rstrip(".") + ". "
        argument += "Ce bloc décrit la cohérence du programme, pas une intention privée de l'entourage."

    return {
        "number": runner.number,
        "horse_name": runner.horse_name,
        "score": round(block_score, 1),
        "status": status,
        "label": label,
        "argument": argument,
        "reasons": reasons,
        "same_named_race_count": len(exact_named),
        "same_track_distance_count": len(same_track_distance),
        "same_track_distance_class_count": len(same_track_distance_class),
        "positive_track_distance_count": len(positive_track_distance),
        "recent_distance_matches": recent_distance_matches,
        "equipment_change": equipment_change,
        "future_engagements": future,
        "independent": True,
        "affects_scores": False,
        "performance": round(float(score.performance), 1),
        "placed": round(float(score.placed), 1),
    }


def rank_target_profiles(db: Session, race: Race, scored_runners: list[tuple[Runner, RunnerScore]]) -> list[dict[str, Any]]:
    runners = [runner for runner, _score in scored_runners]
    future_by_horse = _future_engagements_for_runners(db, race, runners)
    profiles = [
        target_profile(db, race, runner, score, future_by_horse.get(_horse_key(runner), []))
        for runner, score in scored_runners
    ]
    # Publish useful signals first, but keep non-determined horses available in the
    # detailed per-runner table if a client wants to inspect them.
    useful = [item for item in profiles if item["status"] != "non_determine"]
    useful.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            int(item.get("positive_track_distance_count") or 0),
            int(item.get("same_track_distance_class_count") or 0),
            float(item.get("performance") or 0),
        ),
        reverse=True,
    )
    return useful
