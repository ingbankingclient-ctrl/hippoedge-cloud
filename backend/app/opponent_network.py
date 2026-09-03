from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
import re
import unicodedata
from typing import Any

from .models import HorseHistory, Race, Runner
from .utils import clip


def normalized_horse_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("\u202f", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number > 0 else None


def _known_non_place(status: str | None, disqualified: bool) -> bool:
    if disqualified:
        return True
    text = str(status or "").upper()
    return any(token in text for token in ("NON_PLACE", "NON PLACE", "DISQUAL", "DISTANC", "ARRET", "TOMBE"))


@dataclass
class _Observation:
    name: str
    label: str
    position: int | None = None
    disqualified: bool = False
    status: str | None = None

    @property
    def result_known(self) -> bool:
        return self.position is not None or _known_non_place(self.status, self.disqualified)


@dataclass
class _Event:
    key: tuple[str, str, str, int | None]
    race_date: date
    track: str | None
    race_name: str | None
    distance_m: int | None
    allocation_eur: float | None
    class_name: str | None
    field_size: int | None
    observations: dict[str, _Observation] = field(default_factory=dict)

    @property
    def level(self) -> float:
        if self.allocation_eur and self.allocation_eur > 0:
            return self.allocation_eur
        text = str(self.class_name or "").upper()
        groups = {"GROUPE 1": 120000, "GROUPE I": 120000, "GROUPE 2": 85000, "GROUPE II": 85000,
                  "GROUPE 3": 60000, "GROUPE III": 60000, "LISTED": 45000}
        for label, level in groups.items():
            if label in text:
                return float(level)
        match = re.search(r"(?:COURSE|CLASSE)\s*([A-H1-4])", text)
        if match:
            return float({"A": 50000, "B": 42000, "C": 35000, "D": 29000, "E": 24000,
                          "F": 19000, "G": 15000, "H": 12000, "1": 42000, "2": 30000,
                          "3": 22000, "4": 16000}.get(match.group(1), 20000))
        return 20000.0


@dataclass(frozen=True)
class _Duel:
    winner: str
    loser: str
    event_key: tuple[str, str, str, int | None]
    race_date: date
    level: float
    weight: float


@dataclass
class OpponentNetworkCard:
    score: float
    eligible: bool
    paragraph: str
    history_rows: int
    linked_races: int
    coverage_percent: int
    direct_rivals: int
    direct_comparisons: int
    direct_wins: int
    confirmed_lines: int
    higher_or_equal_confirmations: int
    indirect_chains: int
    second_degree_chains: int
    third_degree_chains: int
    previous_meetings_today: int
    today_opponent_bridges: int
    bridge_supports: int
    bridge_counter_signals: int
    today_bridge_examples: list[str]
    chain_examples: list[str]
    examples: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "eligible": self.eligible,
            "paragraph": self.paragraph,
            "history_rows": self.history_rows,
            "linked_races": self.linked_races,
            "coverage_percent": self.coverage_percent,
            "direct_rivals": self.direct_rivals,
            "direct_comparisons": self.direct_comparisons,
            "direct_wins": self.direct_wins,
            "confirmed_lines": self.confirmed_lines,
            "higher_or_equal_confirmations": self.higher_or_equal_confirmations,
            "indirect_chains": self.indirect_chains,
            "second_degree_chains": self.second_degree_chains,
            "third_degree_chains": self.third_degree_chains,
            "previous_meetings_today": self.previous_meetings_today,
            "today_opponent_bridges": self.today_opponent_bridges,
            "bridge_supports": self.bridge_supports,
            "bridge_counter_signals": self.bridge_counter_signals,
            "today_bridge_examples": self.today_bridge_examples,
            "chain_examples": self.chain_examples,
            "examples": self.examples,
            "independent": True,
            "affects_main_scores": False,
            "max_depth": 3,
        }


def _event_key(history: HorseHistory) -> tuple[str, str, str, int | None]:
    raw = history.raw if isinstance(history.raw, dict) else {}
    geny_course_id = str(raw.get("geny_course_id") or "").strip()
    race_name = (
        f"GENY {geny_course_id}"
        if geny_course_id.isdigit()
        else history.race_code or raw.get("nom_course") or raw.get("race_name") or raw.get("prix") or ""
    )
    return (
        history.race_date.isoformat(),
        normalized_horse_name(history.track),
        normalized_horse_name(str(race_name)),
        history.distance_m,
    )


def _merge_observation(event: _Event, observation: _Observation) -> None:
    if not observation.name:
        return
    existing = event.observations.get(observation.name)
    if existing is None:
        event.observations[observation.name] = observation
        return
    if existing.position is None and observation.position is not None:
        existing.position = observation.position
    existing.disqualified = existing.disqualified or observation.disqualified
    if not existing.status and observation.status:
        existing.status = observation.status
    if len(observation.label) > len(existing.label):
        existing.label = observation.label


def _build_events(runners: list[Runner]) -> tuple[dict[tuple[str, str, str, int | None], _Event], dict[int, str]]:
    events: dict[tuple[str, str, str, int | None], _Event] = {}
    current_names = {runner.id: normalized_horse_name(runner.horse_name) for runner in runners}
    for runner in runners:
        own_name = current_names[runner.id]
        for history in runner.history:
            if not history.opponents:
                continue
            raw = history.raw if isinstance(history.raw, dict) else {}
            key = _event_key(history)
            event = events.get(key)
            if event is None:
                event = _Event(
                    key=key,
                    race_date=history.race_date,
                    track=history.track,
                    race_name=history.race_code or raw.get("nom_course") or raw.get("race_name"),
                    distance_m=history.distance_m,
                    allocation_eur=_number(raw.get("allocation_eur") or raw.get("allocation")),
                    class_name=history.class_name,
                    field_size=history.field_size,
                )
                events[key] = event
            _merge_observation(event, _Observation(
                name=own_name,
                label=runner.horse_name,
                position=history.position,
                disqualified=bool(history.disqualified),
                status=str(raw.get("result_status") or raw.get("status_arrivee") or "") or None,
            ))
            for opponent in history.opponents:
                if not isinstance(opponent, dict):
                    continue
                label = str(
                    opponent.get("horse_name") or opponent.get("nom_cheval")
                    or opponent.get("name") or opponent.get("nom") or ""
                ).strip()
                name = normalized_horse_name(label)
                if not name or name == own_name:
                    continue
                _merge_observation(event, _Observation(
                    name=name,
                    label=label,
                    position=_integer(opponent.get("position") or opponent.get("place") or opponent.get("rank")),
                    disqualified=bool(opponent.get("disqualified") or opponent.get("disqualifie")),
                    status=str(opponent.get("result_status") or opponent.get("status_arrivee") or opponent.get("status") or "") or None,
                ))
    return events, current_names


def _pair_result(left: _Observation, right: _Observation) -> int:
    """Return 1 when left beat right, -1 when it lost, and 0 if unknown."""
    if not left.result_known or not right.result_known:
        return 0
    if left.position is not None and right.position is not None:
        return 1 if left.position < right.position else -1 if left.position > right.position else 0
    if left.position is not None and right.position is None:
        return 1
    if left.position is None and right.position is not None:
        return -1
    return 0


def _duels(events: dict[tuple[str, str, str, int | None], _Event], today: date) -> list[_Duel]:
    duels: list[_Duel] = []
    for event in events.values():
        observations = list(event.observations.values())
        age_days = max(0, (today - event.race_date).days)
        recency = 0.45 + 0.55 * math.exp(-age_days / 730)
        level_weight = max(0.75, min(1.30, 0.75 + math.log10(max(10000, event.level) / 10000) * 0.35))
        weight = recency * level_weight
        for index, left in enumerate(observations):
            for right in observations[index + 1:]:
                result = _pair_result(left, right)
                if result > 0:
                    duels.append(_Duel(left.name, right.name, event.key, event.race_date, event.level, weight))
                elif result < 0:
                    duels.append(_Duel(right.name, left.name, event.key, event.race_date, event.level, weight))
    return duels


def _event_finish(event: _Event, name: str) -> tuple[bool, bool]:
    observation = event.observations.get(name)
    if observation is None or observation.position is None:
        return False, False
    return observation.position == 1, observation.position <= 3


def _elo_scores(events: dict[tuple[str, str, str, int | None], _Event], duels: list[_Duel]) -> dict[str, float]:
    nodes = {name for event in events.values() for name in event.observations}
    ratings = {name: 1500.0 for name in nodes}
    for duel in sorted(duels, key=lambda item: (item.race_date, item.event_key)):
        winner_rating = ratings[duel.winner]
        loser_rating = ratings[duel.loser]
        expected = 1 / (1 + 10 ** ((loser_rating - winner_rating) / 400))
        change = 10.0 * duel.weight * (1 - expected)
        ratings[duel.winner] += change
        ratings[duel.loser] -= change
    return ratings


def build_opponent_network(race: Race, runners: list[Runner]) -> dict[int, OpponentNetworkCard]:
    """Build a field-only, independent graph of verified past opponents.

    The graph never reads odds, tips or provider rankings.  It uses named race
    participants and objective finishing positions only.  A result is propagated
    at most three edges (A→B→C→D). Every extra edge is attenuated and the
    entire graph remains separate from the horse's main performance scores.
    """
    active = [runner for runner in runners if not runner.scratched]
    events, current_names = _build_events(active)
    today = race.meeting.race_date if race.meeting else race.scheduled_at.date()
    duels = _duels(events, today)
    ratings = _elo_scores(events, duels)
    current_set = set(current_names.values())
    current_labels = {
        current_names[runner.id]: f"n°{runner.number} {runner.horse_name}"
        for runner in active
    }
    by_winner: dict[str, list[_Duel]] = {}
    by_loser: dict[str, list[_Duel]] = {}
    for duel in duels:
        by_winner.setdefault(duel.winner, []).append(duel)
        by_loser.setdefault(duel.loser, []).append(duel)

    event_by_key = events
    output: dict[int, OpponentNetworkCard] = {}
    for runner in active:
        name = current_names[runner.id]
        wins = by_winner.get(name, [])
        losses = by_loser.get(name, [])
        comparisons = len(wins) + len(losses)
        linked_keys = {duel.event_key for duel in [*wins, *losses]}
        linked_races = len(linked_keys)
        history_rows = len(runner.history)
        coverage = round(linked_races / history_rows * 100) if history_rows else 0
        coverage = max(0, min(100, coverage))
        rivals = {duel.loser for duel in wins} | {duel.winner for duel in losses}

        weighted_total = sum(duel.weight for duel in wins) + sum(duel.weight for duel in losses)
        direct_balance = (
            (sum(duel.weight for duel in wins) - sum(duel.weight for duel in losses)) / weighted_total
            if weighted_total else 0.0
        )
        direct_component = 50 + direct_balance * 34

        confirmations: list[tuple[float, _Duel, _Event, bool, bool]] = []
        chains: set[tuple[str, str, tuple[str, str, str, int | None]]] = set()
        third_degree_chains: set[
            tuple[
                str,
                str,
                str,
                tuple[str, str, str, int | None],
                tuple[str, str, str, int | None],
            ]
        ] = set()
        for win in wins:
            later_events = [
                event for event in events.values()
                if event.race_date > win.race_date and win.loser in event.observations
            ]
            for later in later_events:
                later_win, later_place = _event_finish(later, win.loser)
                if not (later_win or later_place):
                    continue
                same_or_higher = later.level >= win.level * 0.90
                signal = 1.0 if later_win and same_or_higher else 0.82 if later_place and same_or_higher else 0.72 if later_win else 0.55
                confirmations.append((signal, win, later, later_win, same_or_higher))
            for second in by_winner.get(win.loser, []):
                if second.race_date <= win.race_date or second.loser == name:
                    continue
                later_proof = any(
                    event.race_date > second.race_date
                    and second.loser in event.observations
                    and any(_event_finish(event, second.loser))
                    for event in events.values()
                )
                if later_proof or second.level >= win.level * 0.90:
                    chains.add((win.loser, second.loser, second.event_key))
                    for third in by_winner.get(second.loser, []):
                        if (
                            third.race_date <= second.race_date
                            or third.loser in {name, win.loser}
                        ):
                            continue
                        terminal_proof = any(
                            event.race_date > third.race_date
                            and third.loser in event.observations
                            and any(_event_finish(event, third.loser))
                            for event in events.values()
                        )
                        if terminal_proof or third.level >= second.level * 0.90:
                            third_degree_chains.add((
                                win.loser,
                                second.loser,
                                third.loser,
                                second.event_key,
                                third.event_key,
                            ))

        unique_confirmations: dict[tuple[str, tuple[str, str, str, int | None]], tuple[float, _Duel, _Event, bool, bool]] = {}
        for item in confirmations:
            key = (item[1].loser, item[2].key)
            if key not in unique_confirmations or item[0] > unique_confirmations[key][0]:
                unique_confirmations[key] = item
        confirmation_rows = list(unique_confirmations.values())
        confirmed_lines = len(confirmation_rows)
        higher_confirmations = sum(1 for item in confirmation_rows if item[4])
        confirmation_component = 50 + (sum(item[0] for item in confirmation_rows) / max(1, len(wins))) * 34
        confirmation_component = clip(confirmation_component)
        # A third-degree relation is useful context but receives less than half
        # the contribution of a second-degree relation. It can never alter the
        # main Performance/Placé scores because this component lives only here.
        indirect_component = 50 + min(30, len(chains) * 4.5 + len(third_degree_chains) * 2.0)

        current_duels = [duel for duel in [*wins, *losses] if (duel.loser if duel.winner == name else duel.winner) in current_set]
        current_wins = sum(1 for duel in current_duels if duel.winner == name)
        current_losses = len(current_duels) - current_wins
        head_component = 50 + ((current_wins - current_losses) / len(current_duels) * 25 if current_duels else 0)

        # Bridge a horse beaten by this runner to every current-day rival that
        # horse subsequently met.  Both directions are retained: B beating a
        # current rival supports A>B>C, while the current rival beating B is a
        # shared-line counter-signal that must also be shown to the reader.
        today_bridges: dict[
            tuple[str, str, tuple[str, str, str, int | None]],
            tuple[_Duel, _Duel, str, str],
        ] = {}
        for original in wins:
            beaten_name = original.loser
            for later_duel in [*by_winner.get(beaten_name, []), *by_loser.get(beaten_name, [])]:
                if later_duel.race_date <= original.race_date or later_duel.event_key == original.event_key:
                    continue
                if later_duel.winner == beaten_name:
                    current_rival = later_duel.loser
                    direction = "support"
                else:
                    current_rival = later_duel.winner
                    direction = "counter"
                if current_rival not in current_set or current_rival == name:
                    continue
                bridge_key = (beaten_name, current_rival, later_duel.event_key)
                existing_bridge = today_bridges.get(bridge_key)
                if existing_bridge is None or original.race_date > existing_bridge[0].race_date:
                    today_bridges[bridge_key] = (original, later_duel, current_rival, direction)

        bridge_rows = list(today_bridges.values())
        bridge_supports = sum(1 for row in bridge_rows if row[3] == "support")
        bridge_counters = len(bridge_rows) - bridge_supports
        bridge_examples: list[str] = []
        for original, later_duel, current_rival, direction in sorted(
            bridge_rows,
            key=lambda row: (row[1].race_date, row[0].race_date),
            reverse=True,
        ):
            original_event = event_by_key[original.event_key]
            later_event = event_by_key[later_duel.event_key]
            beaten_observation = original_event.observations.get(original.loser)
            beaten_label = beaten_observation.label if beaten_observation else original.loser.title()
            rival_label = current_labels.get(current_rival, current_rival.title())
            level_text = (
                "dans un lot au moins équivalent"
                if later_event.level >= original_event.level * 0.90
                else "dans un lot moins relevé"
            )
            if direction == "support":
                sentence = (
                    f"{beaten_label}, battu le {original.race_date.strftime('%d/%m/%Y')}, a ensuite devancé "
                    f"{rival_label} le {later_duel.race_date.strftime('%d/%m/%Y')} {level_text}"
                )
            else:
                sentence = (
                    f"{rival_label} a ensuite devancé {beaten_label}, que ce cheval avait battu le "
                    f"{original.race_date.strftime('%d/%m/%Y')}, lors de leur rencontre du "
                    f"{later_duel.race_date.strftime('%d/%m/%Y')} {level_text}"
                )
            bridge_examples.append(sentence)
            if len(bridge_examples) >= 3:
                break

        chain_examples: list[str] = []
        for first_name, second_name, third_name, second_key, third_key in sorted(
            third_degree_chains,
            key=lambda item: (event_by_key[item[4]].race_date, event_by_key[item[3]].race_date),
            reverse=True,
        ):
            second_event = event_by_key[second_key]
            third_event = event_by_key[third_key]
            first_label = second_event.observations.get(first_name)
            second_label = second_event.observations.get(second_name)
            third_label = third_event.observations.get(third_name)
            chain_examples.append(
                f"{runner.horse_name} avait devancé {first_label.label if first_label else first_name.title()} ; "
                f"ce dernier a ensuite devancé {second_label.label if second_label else second_name.title()} "
                f"le {second_event.race_date.strftime('%d/%m/%Y')}, puis "
                f"{second_label.label if second_label else second_name.title()} a devancé "
                f"{third_label.label if third_label else third_name.title()} "
                f"le {third_event.race_date.strftime('%d/%m/%Y')}"
            )
            if len(chain_examples) >= 3:
                break

        rating_values = [ratings.get(current_name, 1500.0) for current_name in current_set]
        field_rating = sum(rating_values) / len(rating_values) if rating_values else 1500.0
        elo_component = clip(50 + (ratings.get(name, 1500.0) - field_rating) / 5.5)
        raw_score = (
            direct_component * 0.33
            + confirmation_component * 0.34
            + indirect_component * 0.13
            + head_component * 0.08
            + elo_component * 0.12
        )
        evidence_factor = min(1.0, linked_races / 6) * min(1.0, comparisons / 14)
        score = round(50 + (raw_score - 50) * evidence_factor, 1)
        eligible = linked_races >= 2 and comparisons >= 4 and len(rivals) >= 3

        examples: list[str] = []
        for _signal, original, later, later_win, same_or_higher in sorted(
            confirmation_rows, key=lambda item: (item[0], item[2].race_date), reverse=True
        ):
            opponent = event_by_key[original.event_key].observations.get(original.loser)
            opponent_label = opponent.label if opponent else original.loser.title()
            result = "a ensuite gagné" if later_win else "s’est ensuite placé"
            level = "dans un lot au moins équivalent" if same_or_higher else "dans un autre lot"
            examples.append(f"{opponent_label}, battu le {original.race_date.strftime('%d/%m/%Y')}, {result} {level}")
            if len(examples) >= 3:
                break

        if not eligible:
            paragraph = (
                f"Le réseau a relié {linked_races} course{'s' if linked_races != 1 else ''} sur {history_rows} "
                f"et {len(rivals)} adversaire{'s' if len(rivals) != 1 else ''}. Ce volume ne permet pas encore "
                "un classement sérieux dans ce bloc : le cheval reste non classé ici, même si ses autres notes existent."
            )
        else:
            line_text = (
                f" {confirmed_lines} ligne{'s ont' if confirmed_lines != 1 else ' a'} été confirmée{'s' if confirmed_lines != 1 else ''} "
                f"par une victoire ou une place ultérieure, dont {higher_confirmations} dans un niveau au moins équivalent."
                if confirmed_lines else
                " Aucun adversaire battu n’a encore fourni de confirmation positive visible dans les courses reliées."
            )
            if chains or third_degree_chains:
                chain_text = (
                    f" {len(chains)} chaîne{'s' if len(chains) != 1 else ''} A→B→C et "
                    f"{len(third_degree_chains)} chaîne{'s' if len(third_degree_chains) != 1 else ''} "
                    "A→B→C→D ont été retrouvées avec une influence décroissante à chaque liaison."
                )
            else:
                chain_text = " Aucune chaîne fiable A→B→C ou A→B→C→D n’est encore mesurable."
            example_text = f" Exemple fort : {examples[0]}." if examples else ""
            direct_today_count = len({
                (duel.loser if duel.winner == name else duel.winner)
                for duel in current_duels
            })
            direct_today_text = (
                f" Il a déjà affronté directement {direct_today_count} partant"
                f"{'s' if direct_today_count != 1 else ''} de la course du jour."
                if direct_today_count else
                " Il n’a pas encore de confrontation directe retrouvée avec un partant du jour."
            )
            if bridge_rows:
                bridge_text = (
                    f" Le réseau retrouve aussi {len(bridge_rows)} passerelle"
                    f"{'s' if len(bridge_rows) != 1 else ''} entre un cheval qu’il avait battu et un adversaire du jour : "
                    f"{bridge_supports} prolonge{'nt' if bridge_supports != 1 else ''} positivement sa ligne et "
                    f"{bridge_counters} montre{'nt' if bridge_counters != 1 else ''} que l’adversaire du jour a également pris le dessus. "
                    f"{bridge_examples[0]}."
                )
            else:
                bridge_text = (
                    " Aucun cheval qu’il avait battu n’a ensuite été retrouvé face à un adversaire du jour "
                    "dans les courses actuellement reliées."
                )
            paragraph = (
                f"{runner.horse_name} est comparé sur {linked_races} course{'s' if linked_races != 1 else ''} reliée{'s' if linked_races != 1 else ''} "
                f"parmi {history_rows} performances connues, face à {len(rivals)} adversaire{'s' if len(rivals) != 1 else ''}. "
                f"Il remporte {len(wins)} des {comparisons} comparaisons directes exploitables."
                f"{line_text}{chain_text}{direct_today_text}{bridge_text}{example_text} Son indice indépendant des lignes vaut {score:.0f}/100 ; "
                "il ne modifie ni le Top Performance, ni le Top Placé, ni les sélections du jour."
            )

        output[runner.id] = OpponentNetworkCard(
            score=score,
            eligible=eligible,
            paragraph=paragraph,
            history_rows=history_rows,
            linked_races=linked_races,
            coverage_percent=coverage,
            direct_rivals=len(rivals),
            direct_comparisons=comparisons,
            direct_wins=len(wins),
            confirmed_lines=confirmed_lines,
            higher_or_equal_confirmations=higher_confirmations,
            indirect_chains=len(chains) + len(third_degree_chains),
            second_degree_chains=len(chains),
            third_degree_chains=len(third_degree_chains),
            previous_meetings_today=len({
                (duel.loser if duel.winner == name else duel.winner)
                for duel in current_duels
            }),
            today_opponent_bridges=len(bridge_rows),
            bridge_supports=bridge_supports,
            bridge_counter_signals=bridge_counters,
            today_bridge_examples=bridge_examples,
            chain_examples=chain_examples,
            examples=examples,
        )
    return output
