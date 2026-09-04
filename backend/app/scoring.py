from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Iterable
import math
import re

from .models import HorseHistory, Race, Runner
from .opponent_network import build_opponent_network
from .utils import clip, mean


@dataclass
class ScoreCard:
    performance: float
    placed: float
    hidden_potential: float
    robustness: float
    uncertainty: float
    line_strength: float
    reasons: list[str]
    breakdown: dict


POSITION_POINTS = {1: 100, 2: 91, 3: 84, 4: 77, 5: 70, 6: 62, 7: 55, 8: 48, 9: 42, 10: 36}
_MUSIC_TOKEN_RE = re.compile(r"(?<!\d)(DAI|DA|DM|DQ|DISQ|DIST|NP|\d{1,2})(?!\d)", re.IGNORECASE)


def _music_observations(value: str | None) -> list[tuple[float, bool]]:
    """Read the official music string as a factual fallback only.

    PMU uses forms such as ``1p2p`` (galop), ``2a1aDa`` (trot) and sometimes
    ``0``/``NP`` markers.  The parser intentionally extracts only result
    markers; it never interprets a provider opinion or a market indicator.
    """
    if not value:
        return []
    observations: list[tuple[float, bool]] = []
    for token in _MUSIC_TOKEN_RE.findall(str(value).upper()):
        if token.isdigit():
            position = int(token)
            if position == 0:
                observations.append((32.0, False))
            else:
                observations.append((float(POSITION_POINTS.get(position, max(18, 36 - (position - 10) * 2))), False))
        else:
            observations.append((16.0, True))
    return observations


def _observations(history: list[HorseHistory], recent_form: str | None = None) -> list[tuple[float, bool]]:
    if history:
        recent = sorted(history, key=lambda h: h.race_date, reverse=True)[:10]
        return [(_position_score(h), bool(h.disqualified)) for h in recent]
    return _music_observations(recent_form)[:10]


def _sample_count(history: list[HorseHistory], recent_form: str | None = None) -> int:
    return len(history) if history else len(_music_observations(recent_form))


def _position_score(h: HorseHistory) -> float:
    if h.disqualified:
        return 16.0
    if h.position is None:
        return 35.0
    return float(POSITION_POINTS.get(h.position, max(18, 36 - (h.position - 10) * 2)))


def _recency_weights(n: int) -> list[float]:
    base = [1.00, .88, .77, .67, .58, .50, .43, .37, .32, .28]
    return base[:n] + [0.24] * max(0, n-len(base))


def weighted_form(history: list[HorseHistory], recent_form: str | None = None) -> float:
    observations = _observations(history, recent_form)
    if not observations:
        return 50.0
    weights = _recency_weights(len(observations))
    vals = [score for score, _ in observations]
    return sum(v*w for v, w in zip(vals, weights)) / sum(weights)


def consistency_score(history: list[HorseHistory], recent_form: str | None = None) -> float:
    observations = _observations(history, recent_form)
    completed = [score for score, disqualified in observations if not disqualified]
    if not observations:
        return 45.0
    dq_rate = sum(1 for _, disqualified in observations if disqualified) / len(observations)
    top5_rate = sum(1 for score in completed if score >= POSITION_POINTS[5]) / max(1, len(completed))
    top3_rate = sum(1 for score in completed if score >= POSITION_POINTS[3]) / max(1, len(completed))
    return clip(42 + top5_rate*30 + top3_rate*20 - dq_rate*36)


def progression_score(history: list[HorseHistory], recent_form: str | None = None) -> float:
    observations = _observations(history, recent_form)[:5]
    if len(observations) < 2:
        return 50.0
    vals = [score for score, _ in reversed(observations)]  # old -> recent
    diffs = [b-a for a,b in zip(vals, vals[1:])]
    avg = mean(diffs) or 0
    # A spectacular-looking change over only two or three starts is evidence,
    # but not yet a repeatable trend.  The previous formula could turn 0p -> 6p
    # into 98.6/100 because it treated one isolated step as a mature curve.
    # Shrink the signal by the number of observed transitions and require a
    # genuinely good latest performance before calling a positive move strong.
    transition_weight = min(1.0, len(diffs) / 4)
    latest_quality = vals[-1]
    quality_weight = 1.0
    if avg > 0:
        quality_weight = 0.35 + 0.65 * clip((latest_quality - 45) / 45, 0, 1)
    value = 50 + avg * 1.8 * transition_weight * quality_weight
    # Symmetric confidence bands preserve the possibility of a talented,
    # lightly-raced improver without presenting a one-race move as certainty.
    if len(observations) == 2:
        value = clip(value, 32, 68)
    elif len(observations) == 3:
        value = clip(value, 24, 78)
    elif len(observations) == 4:
        value = clip(value, 16, 88)
    return clip(value)


def aptitude_score(race: Race, history: list[HorseHistory]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not history:
        return 50.0, reasons
    track_name = (race.meeting.track if race.meeting else "") or ""
    race_surface = (race.surface or "").lower()
    scores = []
    for h in history:
        s = _position_score(h)
        weight = 0.0
        if race.distance_m and h.distance_m:
            d = abs(race.distance_m - h.distance_m)
            if d <= 150: weight += 1.8
            elif d <= 400: weight += 1.0
        if h.track and track_name and h.track.lower() == track_name.lower():
            weight += 2.0
        if race.going and h.going and (
            race.going.lower() in h.going.lower() or h.going.lower() in race.going.lower()
        ):
            weight += 1.1
        history_surface = ""
        if isinstance(h.raw, dict):
            history_surface = str(h.raw.get("surface") or h.raw.get("piste") or h.raw.get("terrain") or "").lower()
        if race_surface and history_surface and (
            race_surface in history_surface or history_surface in race_surface
        ):
            weight += 0.9
        if race.discipline and h.discipline and _discipline_family(race.discipline) == _discipline_family(h.discipline):
            weight += 1.2
        if weight:
            scores.append((s, weight))
    if not scores:
        return 50.0, reasons
    total = sum(s*w for s,w in scores)/sum(w for _,w in scores)
    if track_name and any((h.track or '').lower() == track_name.lower() and not h.disqualified and (h.position or 99) <= 3 for h in history):
        reasons.append("Référence placée sur l'hippodrome")
    if race.distance_m and any(h.distance_m and abs(h.distance_m-race.distance_m)<=150 and not h.disqualified and (h.position or 99)<=3 for h in history):
        reasons.append("Référence placée sur une distance très proche")
    if race_surface and any(
        isinstance(h.raw, dict)
        and race_surface in str(h.raw.get("surface") or h.raw.get("piste") or h.raw.get("terrain") or "").lower()
        and not h.disqualified
        and (h.position or 99) <= 3
        for h in history
    ):
        reasons.append("Référence placée sur une surface comparable")
    return clip(total), reasons


def _discipline_family(d: str | None) -> str:
    x = (d or '').lower()
    if any(k in x for k in ('mont', 'mounted', 'saddle')): return 'trot_monte'
    if any(k in x for k in ('attel', 'trot', 'harness', 'standardbred', 'pace')): return 'trot_attele'
    if any(k in x for k in ('haie', 'hurdle', 'steeple', 'obstacle', 'cross', 'jump', 'chase')): return 'obstacle'
    return 'galop'


def speed_score(
    race: Race,
    runner: Runner,
    history: list[HorseHistory],
    field_histories: Iterable[list[HorseHistory]],
    field_records: Iterable[float | None] = (),
) -> float:
    if _discipline_family(race.discipline) not in ('trot_attele','trot_monte'):
        # Gallop timing data are provider-dependent. Use margins if available, otherwise neutral.
        margins = [h.margin_to_winner for h in history[:8] if h.margin_to_winner is not None and not h.disqualified]
        if not margins:
            return 52.0
        m = mean(margins) or 0
        return clip(82 - m*6, 25, 95)

    own = [h.chrono_km_seconds for h in history[:10] if h.chrono_km_seconds and not h.disqualified]
    if runner.record_km_seconds:
        own.append(runner.record_km_seconds)
    all_times = [h.chrono_km_seconds for hs in field_histories for h in hs[:10] if h.chrono_km_seconds and not h.disqualified]
    all_times.extend(float(v) for v in field_records if v is not None)
    if not own or not all_times:
        return 50.0
    own_best = min(own)
    med = median(all_times)
    # 1 second/km around the field median is meaningful at trot.
    return clip(68 + (med-own_best)*9, 25, 97)


def dq_risk(history: list[HorseHistory], recent_form: str | None = None) -> float:
    observations = _observations(history, recent_form)[:8]
    if not observations:
        return 35.0
    rate = sum(1 for _, disqualified in observations if disqualified)/len(observations)
    last = observations[0][1]
    return clip(rate*85 + (12 if last else 0), 0, 95)


def sample_uncertainty(history: list[HorseHistory], runner: Runner, recent_form: str | None = None) -> float:
    n = _sample_count(history, recent_form)
    score = 65 if n <= 2 else 52 if n <= 4 else 36 if n <= 7 else 22
    score += dq_risk(history, recent_form)*0.25
    if not history and recent_form:
        # Music is objective, but it does not provide all contextual fields of
        # a detailed historical line (lot, track, distance and conditions).
        score += 8
    if history:
        days = (date.today() - max(h.race_date for h in history)).days
        if days > 240: score += 22
        elif days > 120: score += 12
    if runner.age and runner.age <= 3 and n <= 4:
        score += 10
    return clip(score)


def scenario_robustness(
    race: Race, runner: Runner, history: list[HorseHistory], recent_form: str | None = None
) -> float:
    cons = consistency_score(history, recent_form)
    risk = dq_risk(history, recent_form)
    n = _sample_count(history, recent_form)
    experience = clip(35 + min(n, 15)*4)
    start = 50.0
    fam = _discipline_family(race.discipline)
    if fam == 'trot_attele' and race.start_type and 'auto' in race.start_type.lower():
        # Good number is only a meaningful bonus when there's actual autostart experience.
        auto_hist = [h for h in history if h.start_type and 'auto' in h.start_type.lower()]
        if runner.start_position and auto_hist:
            if 2 <= runner.start_position <= 5: start = 72
            elif runner.start_position in (1,6): start = 62
            else: start = 48
        elif runner.start_position:
            start = 54
    elif fam == 'galop' and runner.draw:
        # Avoid blind draw dogma; keep effect modest without contextual bias data.
        start = 58 if runner.draw <= 5 else 52
    return clip(cons*0.43 + (100-risk)*0.27 + experience*0.20 + start*0.10)


def class_score(race: Race, history: list[HorseHistory]) -> float:
    def rank(s: str | None) -> int:
        x = (s or '').lower()
        if 'groupe 1' in x or 'group 1' in x: return 100
        if 'groupe 2' in x or 'group 2' in x: return 95
        if 'groupe 3' in x or 'group 3' in x: return 90
        if 'listed' in x: return 86
        if 'course a' in x or 'classe 1' in x: return 82
        if 'course b' in x or 'classe 2' in x: return 76
        if 'course c' in x: return 70
        if 'course d' in x or 'classe 3' in x: return 64
        if 'course e' in x: return 58
        if 'course f' in x: return 52
        if 'handicap' in x: return 62
        return 55
    target = rank(race.class_name)
    vals = []
    for h in history[:10]:
        hclass = rank(h.class_name)
        pos = _position_score(h)
        vals.append(50 + (hclass-target)*0.65 + (pos-50)*0.35)
    return clip(mean(vals) if vals else 50)


def weight_and_draw_score(race: Race, runner: Runner, field: list[Runner]) -> float:
    fam = _discipline_family(race.discipline)
    score = 50.0
    weights = [r.weight_kg for r in field if r.weight_kg is not None and not r.scratched]
    if runner.weight_kg is not None and weights:
        lo, hi = min(weights), max(weights)
        if hi > lo:
            score += ((hi-runner.weight_kg)/(hi-lo)-0.5)*24
    if fam == 'galop' and runner.draw is not None:
        # Small contribution only; actual draw bias should be learned from same-day/historical context.
        n = max(1, len(field))
        if runner.draw <= max(3, n//3): score += 5
        elif runner.draw >= max(8, int(n*.8)): score -= 3
    if fam == 'trot_attele' and race.start_type and 'auto' in race.start_type.lower() and runner.start_position:
        if 2 <= runner.start_position <= 5: score += 8
        elif runner.start_position >= 8: score -= 5
    return clip(score)


def objective_value_score(race: Race, runner: Runner, field: list[Runner]) -> float:
    """Compare objective value indicators with this race's field.

    Handicap value is meaningful primarily in the galop.  Career earnings are
    retained as a secondary level signal for all disciplines, using a logarithm
    so one exceptional purse cannot overwhelm form and performance.
    """
    values: list[float] = []
    fam = _discipline_family(race.discipline)
    if fam == "galop":
        handicap_values = [r.handicap_value for r in field if r.handicap_value is not None and not r.scratched]
        if runner.handicap_value is not None and len(handicap_values) >= 2:
            lo, hi = min(handicap_values), max(handicap_values)
            if hi > lo:
                values.append(35 + 65 * (runner.handicap_value - lo) / (hi - lo))
    earnings = [r.earnings_eur for r in field if r.earnings_eur is not None and r.earnings_eur >= 0 and not r.scratched]
    if runner.earnings_eur is not None and len(earnings) >= 2:
        logged = [math.log1p(max(0.0, x)) for x in earnings]
        lo, hi = min(logged), max(logged)
        if hi > lo:
            current = math.log1p(max(0.0, runner.earnings_eur))
            values.append(35 + 65 * (current - lo) / (hi - lo))
    return clip(mean(values) if values else 50.0)


def hidden_potential_score(
    race: Race,
    runner: Runner,
    history: list[HorseHistory],
    field: list[Runner],
    recent_form: str | None = None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    if not history:
        base = 52.0
    else:
        recent = sorted(history, key=lambda h: h.race_date, reverse=True)
        recent3 = recent[:3]
        older = recent[3:10]
        recent_avg = mean([_position_score(h) for h in recent3]) or 50
        old_best = max([_position_score(h) for h in older], default=recent_avg)
        masked = max(0, old_best - recent_avg)
        base = 50 + masked*0.65
        if masked >= 18:
            reasons.append("Ancienne valeur nettement supérieure à la forme récente")
        # DQ masks performance, but is not a performance failure.
        if recent3 and recent3[0].disqualified and any(not h.disqualified and _position_score(h)>=82 for h in recent[1:5]):
            base += 10
            reasons.append("Faute récente après une performance propre de haut niveau")
    wd = weight_and_draw_score(race, runner, field)
    if wd >= 62:
        base += (wd-50)*0.45
        reasons.append("Configuration poids/position favorable")
    prog = progression_score(history, recent_form)
    if prog >= 63:
        base += 7
        reasons.append("Courbe de progression récente")
    # Young/low-sample profiles have potential but also uncertainty. Don't turn it into a certainty.
    if runner.age and runner.age <= 4 and 2 <= len(history) <= 5:
        base += 4
        reasons.append("Faible historique : marge de progression encore ouverte")
    return clip(base), reasons


def line_strength_score(history: list[HorseHistory]) -> float:
    # Only objective opponent outcomes are accepted here. Provider editorial 'lines' are never used.
    vals = []
    for h in history[:8]:
        if not h.opponents:
            continue
        confirmed = 0
        total = 0
        for o in h.opponents:
            if not isinstance(o, dict):
                continue
            total += 1
            try:
                later_wins = int(o.get('later_wins') or 0)
            except (TypeError, ValueError):
                later_wins = 0
            try:
                later_places = int(o.get('later_places') or 0)
            except (TypeError, ValueError):
                later_places = 0
            confirmed += min(2, later_wins*2 + later_places)
        if total:
            vals.append(50 + min(35, confirmed/total*10))
    return clip(mean(vals) if vals else 50)


def equipment_signal(runner: Runner, history: list[HorseHistory]) -> tuple[float, list[str]]:
    reasons = []
    current = (runner.ferrure or runner.equipment or '').strip().lower()
    if not current or not history:
        return 50, reasons
    same = [h for h in history if (h.equipment or '').strip().lower() == current]
    if not same:
        return 50, reasons
    score = mean([_position_score(h) for h in same]) or 50
    if score >= 75:
        reasons.append("Configuration du jour déjà associée à de bonnes performances")
    return clip(score), reasons


def _history_breakdown(history: list[HorseHistory]) -> list[dict]:
    """Expose only objective historical facts to the mobile detail view."""
    return [
        {
            "date": h.race_date.isoformat(),
            "track": h.track,
            "discipline": h.discipline,
            "distance_m": h.distance_m,
            "going": h.going,
            "position": h.position,
            "disqualified": bool(h.disqualified),
            "chrono_km_seconds": h.chrono_km_seconds,
            "class_name": h.class_name,
            "weight_kg": h.weight_kg,
            "draw": h.draw,
            "start_type": h.start_type,
            "equipment": h.equipment,
            "field_size": h.field_size,
            "margin_to_winner": h.margin_to_winner,
            "opponents_seen": len(h.opponents or []),
        }
        for h in history[:50]
    ]


def _score_level(value: float, positive: str, neutral: str, negative: str) -> str:
    if value >= 72:
        return positive
    if value >= 52:
        return neutral
    return negative


_PLAIN_LABELS = {
    "COURSE_A_CONDITIONS": "course à conditions",
    "COURSE_A_RECLAMER": "course à réclamer",
    "HANDICAP_DIVISE": "handicap divisé",
    "FEMELLES": "femelle",
    "FEMELLE": "femelle",
    "F": "femelle",
    "MALES": "mâle",
    "MALE": "mâle",
    "M": "mâle",
    "HONGRES": "hongre",
    "HONGRE": "hongre",
    "H": "hongre",
    "SANS_OEILLERES": "sans œillères",
    "AVEC_OEILLERES": "avec œillères",
    "OEILLERES_AUSTRALIENNES": "œillères australiennes",
    "HERBE": "herbe",
    "GAZON": "gazon",
    "SABLE_FIBRE": "piste en sable fibré",
    "PISTE_EN_SABLE_FIBRE": "piste en sable fibré",
    "AUTOSTART": "autostart",
    "VOLTÉ": "départ volté",
    "VOLTE": "départ volté",
}


def _plain(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).strip()
    key = text.upper().replace(" ", "_")
    if key in _PLAIN_LABELS:
        return _PLAIN_LABELS[key]
    # Keep compact racing codes such as D4, F4 or DA readable and uppercase.
    if re.fullmatch(r"[A-Z]{1,3}\d{1,2}", text):
        return text
    if "_" in text or text.isupper():
        return text.replace("_", " ").strip().lower()
    return text


def _evidence_status(history: list[HorseHistory], runner: Runner) -> tuple[str, str, int]:
    music_rows = len(_music_observations(runner.recent_form))
    raw = runner.raw if isinstance(runner.raw, dict) else {}
    source_status = str(raw.get("history_status") or "")
    if len(history) >= 5:
        return "complete", "Analyse étayée", min(95, 55 + len(history) * 5)
    if history:
        return "partial", "Analyse partielle", min(75, 45 + len(history) * 7)
    # Music is useful as a temporary factual signal, but it is not a detailed
    # history: it contains neither the level of the race nor the opponents.
    # It must therefore never make a dossier selection-ready by itself.
    if music_rows:
        return "limited", "Musique seule — historique détaillé absent", 0
    if source_status in {"pending", "loading", ""}:
        return "loading", "Historique en cours", 0
    if source_status == "unavailable":
        return "insufficient", "Historique indisponible", 0
    return "insufficient", "Données insuffisantes", 0


def analysis_paragraph(
    race: Race,
    runner: Runner,
    history: list[HorseHistory],
    performance: float,
    placed: float,
    hidden: float,
    robust: float,
    uncertainty: float,
    reasons: list[str],
    ranking_eligible: bool,
) -> str:
    """Produce a client-facing factual reading in plain French."""
    identity = f"Le n°{runner.number} {runner.horse_name}"
    music_observations = _music_observations(runner.recent_form)
    evidence_status, _evidence_label, _confidence = _evidence_status(history, runner)
    raw_status = str((runner.raw or {}).get("history_status") or "") if isinstance(runner.raw, dict) else ""

    profile_bits: list[str] = []
    if runner.sex:
        profile_bits.append(_plain(runner.sex))
    if runner.age is not None:
        profile_bits.append(f"de {runner.age} ans")
    profile = f" est {' '.join(profile_bits)}." if profile_bits else "."

    race_bits: list[str] = []
    if race.distance_m:
        race_bits.append(f"{race.distance_m} m")
    if race.surface:
        race_bits.append(f"sur {_plain(race.surface)}")
    if race.going:
        race_bits.append(f"terrain {_plain(race.going)}")
    if runner.weight_kg is not None:
        race_bits.append(f"avec {runner.weight_kg:g} kg")
    if runner.draw is not None:
        race_bits.append(f"corde {runner.draw}")
    elif runner.start_position is not None:
        race_bits.append(f"position de départ {runner.start_position}")
    if race.start_type:
        race_bits.append(_plain(race.start_type))
    race_sentence = f" Il dispute cette course sur {', '.join(race_bits)}." if race_bits else ""

    if history:
        recent = sorted(history, key=lambda h: h.race_date, reverse=True)[:5]
        marks = []
        for h in recent:
            result = "disqualifié" if h.disqualified else (
                ("1er" if h.position == 1 else f"{h.position}e") if h.position else "non classé"
            )
            context_bits = []
            if h.track:
                context_bits.append(str(h.track))
            if h.distance_m:
                context_bits.append(f"{h.distance_m} m")
            if h.going:
                context_bits.append(_plain(str(h.going)))
            if h.chrono_km_seconds:
                context_bits.append(f"{h.chrono_km_seconds:.1f} s/km")
            if h.class_name:
                context_bits.append(_plain(str(h.class_name)))
            context = f" ({', '.join(context_bits)})" if context_bits else ""
            marks.append(f"{result}{context}")
        evidence = (
            f" {len(history)} performances sont documentées. Les plus récentes donnent : "
            + " ; ".join(marks)
            + "."
        )
    elif runner.recent_form:
        evidence = (
            f" Sa musique officielle est « {runner.recent_form} » ({len(music_observations)} résultats lisibles). "
            "Les détails de chaque course ne sont pas encore tous disponibles : la lecture reste provisoire."
        )
    elif raw_status == "unavailable":
        evidence = (
            "Le contrôle de l’historique détaillé n’a pas abouti avec les sources disponibles. "
            "Cette absence est signalée clairement et ne peut pas être transformée en avantage."
        )
    elif evidence_status == "loading":
        evidence = (
            " Son historique détaillé est en cours de récupération. "
            "Aucune conclusion sérieuse n’est publiée avant la fin de ce contrôle."
        )
    else:
        evidence = (
            " Aucune performance passée suffisamment précise n’est disponible dans les sources contrôlées. "
            "Les seules conditions du jour ne permettent pas de mesurer sa valeur."
        )

    detail_bits: list[str] = []
    if race.class_name:
        detail_bits.append(_plain(race.class_name))
    if runner.handicap_value is not None:
        detail_bits.append(f"valeur handicap {runner.handicap_value:g}")
    if runner.ferrure:
        detail_bits.append(f"ferrure {_plain(runner.ferrure)}")
    if runner.equipment:
        detail_bits.append(_plain(runner.equipment))
    if runner.record_km_seconds:
        detail_bits.append(f"record {runner.record_km_seconds:.1f} s/km")
    if runner.jockey_driver:
        detail_bits.append(f"piloté par {runner.jockey_driver}")
    if runner.trainer:
        detail_bits.append(f"entraîné par {runner.trainer}")
    details = f" Repères du jour : {', '.join(detail_bits)}." if detail_bits else ""

    if not ranking_eligible:
        return (
            f"{identity}{profile}{race_sentence}{evidence}{details} "
            "Conclusion : les preuves sont insuffisantes pour lui attribuer un rang fiable. "
            "Ce cheval est écarté des choix principaux tant que son historique n’est pas confirmé."
        )

    reading = _score_level(
        performance,
        "Son niveau objectif le place parmi les candidatures fortes pour la victoire.",
        "Son potentiel de performance est intermédiaire et demande confirmation face à ce lot.",
        "Ses preuves actuelles sont insuffisantes pour en faire une priorité de victoire.",
    )
    safety = _score_level(
        placed,
        "Son profil placé est solide",
        "Sa sécurité pour une place est moyenne",
        "Son profil placé est fragile",
    )
    volatility = "faible" if uncertainty <= 30 else "moyenne" if uncertainty < 60 else "élevée"
    signals = (" Points déterminants : " + "; ".join(reasons[:3]) + ".") if reasons else ""
    hidden_text = (
        f" Un potentiel moins visible est détecté ({hidden:.0f}/100), mais il doit être confirmé."
        if hidden >= 62
        else " Aucun potentiel caché suffisamment fort ne ressort actuellement."
    )
    return (
        f"{identity}{profile}{race_sentence}{evidence}{details} {reading.rstrip('.')}. "
        f"{safety} (Performance {performance:.0f}/100, Placé {placed:.0f}/100). "
        f"Sa résistance aux différents scénarios est de {robust:.0f}/100 et l’incertitude est {volatility} "
        f"({uncertainty:.0f}/100 : plus ce chiffre est haut, moins la prévision est sûre)."
        f"{hidden_text}{signals}"
    )


def score_race(race: Race, runners: list[Runner]) -> dict[int, ScoreCard]:
    active = [r for r in runners if not r.scratched]
    field_histories = [sorted(r.history, key=lambda h: h.race_date, reverse=True) for r in active]
    field_records = [r.record_km_seconds for r in active]
    network_cards = build_opponent_network(race, active)
    output: dict[int, ScoreCard] = {}

    for runner in active:
        hist = sorted(runner.history, key=lambda h: h.race_date, reverse=True)
        form = weighted_form(hist, runner.recent_form)
        cons = consistency_score(hist, runner.recent_form)
        prog = progression_score(hist, runner.recent_form)
        aptitude, apt_reasons = aptitude_score(race, hist)
        speed = speed_score(race, runner, hist, field_histories, field_records)
        cls = class_score(race, hist)
        wd = weight_and_draw_score(race, runner, active)
        hidden, hidden_reasons = hidden_potential_score(race, runner, hist, active, runner.recent_form)
        robust = scenario_robustness(race, runner, hist, runner.recent_form)
        uncertainty = sample_uncertainty(hist, runner, runner.recent_form)
        network = network_cards[runner.id]
        line = network.score
        equip, eq_reasons = equipment_signal(runner, hist)
        value_signal = objective_value_score(race, runner, active)
        risk = dq_risk(hist, runner.recent_form)
        sample_n = _sample_count(hist, runner.recent_form)
        evidence_status, evidence_label, data_confidence = _evidence_status(hist, runner)
        strongest_proof = max(form, cls, aptitude)
        # Public rankings require actual detailed performances. The compact
        # official music remains visible but cannot manufacture a Horse of the
        # day before the source cascade has completed.
        detailed_n = len(hist)
        # A public rank needs several detailed lines. A genuinely exceptional
        # lightly-raced horse may enter with two lines, but never from music
        # alone or from one isolated result.
        ranking_eligible = detailed_n >= 3 or (detailed_n >= 2 and strongest_proof >= 82)

        fam = _discipline_family(race.discipline)
        # Core philosophy: own performance evidence dominates indirect lines.
        # The opponent network is published in its own block and deliberately
        # has zero weight here, so readers can compare the two conclusions.
        if fam in ('trot_attele','trot_monte'):
            performance = (
                form*.215 + speed*.20 + aptitude*.13 + cls*.12 + prog*.10 +
                hidden*.09 + cons*.06 + wd*.04 + equip*.025 + value_signal*.02
            )
        else:
            performance = (
                form*.245 + aptitude*.16 + cls*.13 + prog*.11 + hidden*.10 +
                cons*.09 + wd*.07 + speed*.04 + equip*.015 + value_signal*.04
            )
        # Placed score: consistency + technical cleanliness matter more, but never from 2-3 runs alone.
        sample_factor = min(1.0, len(hist)/7) if hist else 0.55
        effective_cons = 50 + (cons-50)*sample_factor
        placed = performance*.47 + effective_cons*.18 + robust*.18 + aptitude*.09 + (100-risk)*.08

        reasons = []
        if form >= 75: reasons.append("Forme récente solide")
        if cons >= 78: reasons.append("Régularité de fond")
        if prog >= 64: reasons.append("Progression récente mesurable")
        if speed >= 78: reasons.append("Capacité chronométrique supérieure au lot")
        if cls >= 72: reasons.append("A déjà tenu un niveau de course comparable ou supérieur")
        if value_signal >= 76: reasons.append("Valeur objective supérieure dans ce lot")
        if not hist and runner.recent_form:
            reasons.append("Musique officielle utilisée en attendant l’historique détaillé")
        reasons.extend(apt_reasons + hidden_reasons + eq_reasons)
        if fam.startswith('trot') and risk >= 42:
            reasons.append("Risque de faute à intégrer dans la sécurité")
        if uncertainty >= 60:
            reasons.append("Profil volatil / peu documenté")
        if robust >= 82:
            reasons.append("Robuste à plusieurs scénarios de course")

        if sample_n == 0:
            # Race conditions alone must never manufacture a ranking.  Keep a
            # neutral placeholder internally and expose the dossier as
            # ineligible until an objective performance is available.
            performance = 50.0
            placed = 50.0
            hidden = 50.0
            robust = 50.0
            uncertainty = 95.0
            ranking_eligible = False
            reasons = [
                "Historique en cours de récupération"
                if evidence_status == "loading"
                else "Aucune performance suffisamment documentée"
            ]

        performance=round(clip(performance), 1)
        placed=round(clip(placed), 1)
        hidden=round(hidden, 1)
        robust=round(robust, 1)
        uncertainty=round(uncertainty, 1)
        paragraph=analysis_paragraph(
            race,
            runner,
            hist,
            performance,
            placed,
            hidden,
            robust,
            uncertainty,
            reasons,
            ranking_eligible,
        )

        output[runner.id] = ScoreCard(
            performance=performance,
            placed=placed,
            hidden_potential=round(hidden, 1),
            robustness=robust,
            uncertainty=uncertainty,
            line_strength=round(line, 1),
            reasons=reasons[:8],
            breakdown={
                "form": round(form,1), "consistency": round(cons,1), "progression": round(prog,1),
                "aptitude": round(aptitude,1), "speed": round(speed,1), "class": round(cls,1),
                "weight_draw_start": round(wd,1), "objective_value": round(value_signal,1), "equipment": round(equip,1), "dq_risk": round(risk,1),
                "sample_size": sample_n, "history_rows": len(hist),
                "official_music_rows": len(_music_observations(runner.recent_form)), "principle": "opponent_network_is_independent",
                "evidence_status": evidence_status, "evidence_label": evidence_label,
                "data_confidence": data_confidence, "ranking_eligible": ranking_eligible,
                "history_status": (runner.raw or {}).get("history_status") if isinstance(runner.raw, dict) else None,
                "history_source": (runner.raw or {}).get("history_source") if isinstance(runner.raw, dict) else None,
                "history": _history_breakdown(hist),
                "opponent_network": network.as_dict(),
                "analysis_text": paragraph,
            },
        )
    return output
