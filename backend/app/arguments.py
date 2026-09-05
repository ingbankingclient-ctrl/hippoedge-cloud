from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import HorseHistory, Race, Runner, RunnerScore


def _ordinal(position: int | None) -> str:
    if not position or position <= 0:
        return "non classé"
    return "1er" if position == 1 else f"{position}e"


def _plain(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("_", " ").lower() if ("_" in text or text.isupper()) else text


def _history(runner: Runner) -> list[HorseHistory]:
    return sorted(list(runner.history or []), key=lambda row: row.race_date, reverse=True)


def _race_fact(row: HorseHistory) -> str:
    bits: list[str] = []
    if row.track:
        bits.append(str(row.track))
    if row.distance_m:
        bits.append(f"{row.distance_m} m")
    if row.going:
        bits.append(_plain(row.going))
    if row.class_name:
        bits.append(_plain(row.class_name))
    result = "disqualifié" if row.disqualified else _ordinal(row.position)
    margin = ""
    if row.margin_to_winner is not None and row.margin_to_winner >= 0:
        margin = f", à {row.margin_to_winner:g} L du gagnant"
    chrono = f", {row.chrono_km_seconds:.1f} s/km" if row.chrono_km_seconds else ""
    context = " · ".join(bits)
    return f"{result}{' à ' + context if context else ''}{margin}{chrono}"


def recent_evidence(runner: Runner, limit: int = 3) -> str:
    rows = _history(runner)[:limit]
    if not rows:
        return "Son historique détaillé n'est pas encore assez documenté pour produire un argument de forme fiable."
    facts = [_race_fact(row) for row in rows]
    return "Ses dernières références documentées sont " + " ; ".join(facts) + "."


def progression_evidence(runner: Runner, limit: int = 5) -> str | None:
    rows = [row for row in _history(runner)[:limit] if row.position and not row.disqualified]
    if len(rows) < 3:
        return None
    chronological = list(reversed(rows))
    seq = [int(row.position) for row in chronological]
    improvement = seq[0] - seq[-1]
    if improvement >= 2:
        arrow = " → ".join(_ordinal(value) for value in seq)
        return f"La trajectoire récente est réellement ascendante ({arrow}), avec {improvement} place{'s' if improvement > 1 else ''} gagnée{'s' if improvement > 1 else ''} entre la première et la dernière référence de cette séquence."
    if max(seq) - min(seq) <= 2:
        arrow = " → ".join(_ordinal(value) for value in seq)
        return f"Sa musique détaillée est assez régulière ({arrow}) : il répète un niveau proche au lieu d'alterner fortement les valeurs."
    return None


def consistency_evidence(runner: Runner, limit: int = 6) -> str | None:
    rows = [row for row in _history(runner)[:limit] if row.position and not row.disqualified]
    if not rows:
        return None
    top3 = sum(1 for row in rows if int(row.position) <= 3)
    top5 = sum(1 for row in rows if int(row.position) <= 5)
    if top3 >= 2:
        return f"Sur ses {len(rows)} dernières courses exploitables, il compte {top3} arrivée{'s' if top3 > 1 else ''} dans les trois premiers, ce qui donne une base concrète pour la sécurité."
    if top5 >= 3:
        return f"Il a terminé {top5} fois dans les cinq premiers sur ses {len(rows)} dernières courses exploitables, un signal de tenue plus utile pour la place que pour une pointe de victoire isolée."
    return None


def aptitude_evidence(race: Race, runner: Runner) -> str | None:
    rows = _history(runner)
    if not rows:
        return None
    pieces: list[str] = []
    if race.distance_m:
        similar = [row for row in rows if row.distance_m and abs(int(row.distance_m) - int(race.distance_m)) <= 200]
        if similar:
            best = min((row.position for row in similar if row.position), default=None)
            pieces.append(
                f"{len(similar)} référence{'s' if len(similar) > 1 else ''} sur une distance proche de celle du jour"
                + (f", avec au mieux {_ordinal(best)}" if best else "")
            )
    if race.meeting and race.meeting.track:
        same_track = [row for row in rows if row.track and str(row.track).strip().lower() == str(race.meeting.track).strip().lower()]
        if same_track:
            best = min((row.position for row in same_track if row.position), default=None)
            pieces.append(
                f"{len(same_track)} sortie{'s' if len(same_track) > 1 else ''} déjà enregistrée{'s' if len(same_track) > 1 else ''} sur cet hippodrome"
                + (f", avec au mieux {_ordinal(best)}" if best else "")
            )
    if not pieces:
        return None
    return "Son aptitude repose sur " + " et ".join(pieces) + "."


def network_evidence(score: RunnerScore) -> str | None:
    breakdown = score.breakdown if isinstance(score.breakdown, dict) else {}
    network = breakdown.get("opponent_network") if isinstance(breakdown, dict) else None
    if not isinstance(network, dict):
        return None
    examples = network.get("today_bridge_examples") if isinstance(network.get("today_bridge_examples"), list) else []
    chains = network.get("chain_examples") if isinstance(network.get("chain_examples"), list) else []
    if chains:
        return f"Le réseau adversaires apporte une chaîne vérifiée : {chains[0]}."
    if examples:
        return f"Une ligne recroisée vers le lot du jour ressort : {examples[0]}."
    confirmations = int(network.get("confirmed_lines") or 0)
    linked = int(network.get("linked_races") or 0)
    if linked and confirmations:
        return f"Ses anciennes courses fournissent {linked} lignes reliées et {confirmations} confirmation{'s' if confirmations > 1 else ''} par les résultats ultérieurs des adversaires."
    return None


def current_context(race: Race, runner: Runner) -> str | None:
    bits: list[str] = []
    if runner.weight_kg is not None:
        bits.append(f"{runner.weight_kg:g} kg")
    if runner.draw is not None:
        bits.append(f"corde {runner.draw}")
    elif runner.start_position is not None:
        bits.append(f"position de départ {runner.start_position}")
    if runner.ferrure:
        bits.append(f"ferrure {_plain(runner.ferrure)}")
    if runner.equipment:
        bits.append(_plain(runner.equipment))
    if not bits:
        return None
    return "Les paramètres du jour à contrôler sont : " + ", ".join(bits) + "."


def risk_evidence(race: Race, runner: Runner, score: RunnerScore) -> str:
    rows = _history(runner)
    risks: list[str] = []
    if len(rows) <= 2:
        risks.append(f"seulement {len(rows)} course{'s' if len(rows) > 1 else ''} détaillée{'s' if len(rows) > 1 else ''}")
    if score.uncertainty >= 60:
        risks.append("profil encore volatil")
    if race.distance_m and rows:
        known_distances = [int(row.distance_m) for row in rows if row.distance_m]
        if known_distances and all(abs(distance - int(race.distance_m)) > 300 for distance in known_distances):
            risks.append("distance du jour sensiblement différente de ses références documentées")
    dq = sum(1 for row in rows[:6] if row.disqualified)
    if dq >= 2:
        risks.append(f"{dq} disqualifications sur les six dernières lignes contrôlées")
    if not risks:
        return "Le principal point de vigilance ne vient pas d'un manque évident de données, mais du déroulement réel de la course qui reste à subir."
    return "Point de vigilance : " + ", ".join(risks) + "."


def _join_unique(parts: Iterable[str | None], limit: int = 4) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= limit:
            break
    return " ".join(output)


def build_block_argument(race: Race, runner: Runner, score: RunnerScore, block: str) -> str:
    """Create a factual, player-facing argument. Scores stay secondary in the UI.

    No odds, tips, favourites or editorial comments are consulted here. The text
    is assembled only from persisted race/history facts and HippoEdge's own
    objective modules.
    """
    recent = recent_evidence(runner)
    progression = progression_evidence(runner)
    consistency = consistency_evidence(runner)
    aptitude = aptitude_evidence(race, runner)
    network = network_evidence(score)
    context = current_context(race, runner)
    risk = risk_evidence(race, runner, score)

    if block == "placed":
        return _join_unique([consistency, recent, aptitude, risk])
    if block == "hidden":
        hidden_reason = next(
            (reason for reason in (score.reasons or []) if any(key in reason.lower() for key in ("ancienne", "progress", "configuration", "ferrure", "équipement", "valeur"))),
            None,
        )
        translated = f"Le signal caché vient aussi de ceci : {hidden_reason.lower()}." if hidden_reason else None
        return _join_unique([progression, translated, recent, aptitude, risk])
    if block == "network":
        return _join_unique([network, recent, aptitude, risk])
    if block == "overlooked":
        return _join_unique([progression, network, recent, risk])
    if block == "convergence":
        return _join_unique([recent, consistency, aptitude, network, risk])
    if block == "selection":
        return _join_unique([recent, aptitude, network, risk])
    if block == "robustness":
        return _join_unique([consistency, aptitude, recent, context, risk])
    if block == "volatility":
        return _join_unique([risk, recent, consistency, aptitude])
    # performance / default
    return _join_unique([recent, progression, aptitude, network, context, risk])


def detail_item(race: Race, runner: Runner, score: RunnerScore, block: str) -> dict[str, Any]:
    return {
        "number": runner.number,
        "horse_name": runner.horse_name,
        "argument": build_block_argument(race, runner, score, block),
        "performance": round(float(score.performance), 1),
        "placed": round(float(score.placed), 1),
        "hidden_potential": round(float(score.hidden_potential), 1),
        "robustness": round(float(score.robustness), 1),
        "uncertainty": round(float(score.uncertainty), 1),
    }
