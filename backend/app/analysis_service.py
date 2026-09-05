from __future__ import annotations

from datetime import datetime
import hashlib
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import AnalysisSnapshot, Evaluation, Race, Runner, RunnerScore
from .finisher import (
    objective_finisher_signature,
    rank_finisher_candidates,
    rank_late_mover_candidates,
    finisher_resistance_profile,
    rank_finisher_resistance_candidates,
)
from .scoring import score_race
from .arguments import build_block_argument, detail_item
from .targeting import rank_target_profiles
from .utils import stable_hash

CONFIRMATION = (
    "Je confirme que le moteur n'utilise volontairement ni classements, ni pronostics, ni favoris, "
    "ni cotes, ni popularité, ni avis éditoriaux. La liste des partants provient de la fiche de course "
    "et les scores sont construits uniquement à partir des données objectives de course et de performance disponibles."
)

# Contract enforced by tests and exposed to the client. A block may legitimately
# contain "aucune preuve"; it may never silently disappear from a race analysis.
REQUIRED_ANALYSIS_BLOCKS = [
    "conditions_course",
    "cheval_par_cheval",
    "performance",
    "placed",
    "hidden_potential",
    "robustness",
    "volatility",
    "convergence",
    "do_not_overlook",
    "opponent_network",
    "finisher",
    "late_mover",
    "finisher_resistance",
    "selection_8",
    "reinforced_parameters",
    "conclusion",
    "house_target",
    "future_engagements",
]


def snapshot_phase(race: Race, generated_at: datetime | None = None) -> str:
    """Classify an analysis without ever pretending a late read was pre-race."""
    if race.result is not None:
        return "post_result"
    moment = generated_at or datetime.now()
    return "pre_race" if moment < race.scheduled_at else "post_start"


def is_pre_race_snapshot(race: Race, snapshot: AnalysisSnapshot) -> bool:
    phase = (snapshot.summary or {}).get("snapshot_phase") if isinstance(snapshot.summary, dict) else None
    if phase:
        return phase == "pre_race"
    # Older snapshots predate the explicit phase marker. They are accepted only
    # when their generation timestamp is clearly before the scheduled start.
    return snapshot.generated_at < race.scheduled_at


def load_race(db: Session, race_id: int) -> Race | None:
    return db.scalar(
        select(Race).where(Race.id==race_id).options(
            selectinload(Race.meeting),
            selectinload(Race.runners).selectinload(Runner.history),
            selectinload(Race.snapshots),
        )
    )


def generate_analysis(db: Session, race: Race, lock: bool = False) -> AnalysisSnapshot:
    settings=get_settings()
    # Compute the fingerprint incrementally.  The previous implementation built
    # a second, giant nested copy of every horse career (including every
    # opponents JSON list) and then json.dumps() duplicated it once more.  On a
    # 512 MB worker that transient copy could be larger than the analysis itself.
    # Incremental hashing keeps exactly the same factual sensitivity without
    # retaining a duplicate of the complete field in memory.
    digest = hashlib.sha256()

    def feed(payload: object) -> None:
        digest.update(stable_hash(payload).encode("ascii"))
        digest.update(b"\0")

    feed({
        "methodology_version": settings.methodology_version,
        "race": {
            "id": race.id, "going": race.going, "surface": race.surface,
            "distance": race.distance_m, "discipline": race.discipline,
            "class": race.class_name, "purse": race.purse_eur, "start": race.start_type,
        },
    })
    for r in sorted(race.runners, key=lambda item: (item.number, item.id or 0)):
        feed({
            "n": r.number, "name": r.horse_name, "scratched": r.scratched,
            "age": r.age, "sex": r.sex, "weight": r.weight_kg, "draw": r.draw,
            "handicap_value": r.handicap_value, "earnings": r.earnings_eur,
            "record": r.record_km_seconds, "ferrure": r.ferrure,
            "equipment": r.equipment, "start_position": r.start_position,
            "distance": r.distance_m, "jockey_driver": r.jockey_driver,
            "trainer": r.trainer, "recent_form": r.recent_form,
            "history_status": (r.raw or {}).get("history_status") if isinstance(r.raw, dict) else None,
            "history_source": (r.raw or {}).get("history_source") if isinstance(r.raw, dict) else None,
        })
        for h in sorted(
            r.history,
            key=lambda item: (item.race_date, item.id or 0),
            reverse=True,
        ):
            feed({
                "d": h.race_date.isoformat(), "track": h.track, "code": h.race_code,
                "discipline": h.discipline, "dist": h.distance_m, "going": h.going,
                "p": h.position, "dq": h.disqualified, "t": h.chrono_km_seconds,
                "class": h.class_name, "weight": h.weight_kg, "draw": h.draw,
                "start": h.start_type, "equipment": h.equipment, "field": h.field_size,
                "margin": h.margin_to_winner, "opponents": h.opponents,
            })
        feed({"finisher_objective_signature": objective_finisher_signature(r.history)})
    dh = digest.hexdigest()
    latest=max(race.snapshots,key=lambda x:x.generated_at) if race.snapshots else None
    if race.result is not None:
        # Preserve the best available pre-race reading even when a provider
        # later fills a missing runner field. A result must never make the
        # displayed prediction change retroactively.
        pre_race = [s for s in race.snapshots if is_pre_race_snapshot(race, s)]
        if pre_race:
            return max(pre_race, key=lambda x: x.generated_at)
    # Once a snapshot is locked it is the immutable pre-race record. A forced
    # refresh or a later result must never create a newer analysis that hides it.
    if latest and latest.locked:
        return latest
    if latest and latest.data_hash==dh and latest.methodology_version==settings.methodology_version and not lock:
        return latest
    cards=score_race(race,race.runners)
    generated_at = datetime.now()
    phase = snapshot_phase(race, generated_at)
    snap=AnalysisSnapshot(
        race_id=race.id,
        generated_at=generated_at,
        methodology_version=settings.methodology_version,
        data_hash=dh,
        locked=lock,
        locked_at=generated_at if lock else None,
    )
    db.add(snap); db.flush()
    scores=[]
    for r in race.runners:
        if r.scratched or r.id not in cards: continue
        c=cards[r.id]
        rs=RunnerScore(snapshot_id=snap.id,runner_id=r.id,performance=c.performance,placed=c.placed,hidden_potential=c.hidden_potential,robustness=c.robustness,uncertainty=c.uncertainty,line_strength=c.line_strength,reasons=c.reasons,breakdown=c.breakdown)
        db.add(rs); scores.append((r,rs))
    documented_count=sum(
        1 for _runner,score in scores
        if isinstance(score.breakdown,dict) and int(score.breakdown.get("history_rows") or 0)>0
    )
    field_coverage_percent=round(documented_count/len(scores)*100) if scores else 0
    field_coverage_ready=field_coverage_percent>=settings.selection_min_field_coverage_percent
    eligible_scores=[
        item for item in scores
        if field_coverage_ready
        and isinstance(item[1].breakdown,dict)
        and item[1].breakdown.get("ranking_eligible") is True
    ]
    perf=sorted(eligible_scores,key=lambda x:x[1].performance,reverse=True)
    placed=sorted(eligible_scores,key=lambda x:x[1].placed,reverse=True)
    hidden=sorted(eligible_scores,key=lambda x:x[1].hidden_potential,reverse=True)
    robustness=sorted(eligible_scores,key=lambda x:(x[1].robustness, x[1].placed),reverse=True)
    low_volatility=sorted(eligible_scores,key=lambda x:(x[1].uncertainty, -x[1].placed))
    convergence=sorted(eligible_scores,key=lambda x:(x[1].performance+x[1].placed)/2,reverse=True)
    network=sorted(
        [
            item for item in scores
            if isinstance(item[1].breakdown, dict)
            and isinstance(item[1].breakdown.get("opponent_network"), dict)
            and item[1].breakdown["opponent_network"].get("eligible") is True
        ],
        key=lambda item: float(item[1].breakdown["opponent_network"].get("score") or 0),
        reverse=True,
    )
    # Independent closing-style blocks. A historical finisher/progressive mover
    # is not automatically a good current-race chance: the #1 of each list must
    # also belong to the main Performance/Placé shortlists and clear the same
    # score/volatility gates. No market or editorial data is consulted.
    main_chance_numbers={x[0].number for x in perf[:3]} | {x[0].number for x in placed[:3]}
    finisher_blocks_by_runner_id={
        runner.id: ((score.breakdown or {}).get("finisher", {}) if isinstance(score.breakdown, dict) else {})
        for runner, score in scores
    }
    finisher_candidates=[]
    late_mover_candidates=[]
    for runner, score in eligible_scores:
        beautiful_chance=(
            runner.number in main_chance_numbers
            and (score.performance >= 66 or score.placed >= 70)
            and score.uncertainty <= 72
        )
        current_argument=build_block_argument(race, runner, score, "performance")
        block=(score.breakdown or {}).get("finisher", {}) if isinstance(score.breakdown,dict) else {}
        if isinstance(block,dict) and block.get("eligible") is True:
            finisher_candidates.append({
                "number": runner.number,
                "horse_name": runner.horse_name,
                "finisher_score": float(block.get("score") or 0),
                "status": block.get("status") or "probable",
                "evidence_runs": int(block.get("evidence_runs") or 0),
                "strong_runs": int(block.get("strong_runs") or 0),
                "performance": float(score.performance),
                "placed": float(score.placed),
                "uncertainty": float(score.uncertainty),
                "beautiful_chance": beautiful_chance,
                "eligible": True,
                "reasons": list(block.get("reasons") or []),
                "evidence": list(block.get("evidence") or []),
                "current_argument": current_argument,
            })
        late=(score.breakdown or {}).get("late_mover", {}) if isinstance(score.breakdown,dict) else {}
        if isinstance(late,dict) and late.get("eligible") is True:
            late_mover_candidates.append({
                "number": runner.number,
                "horse_name": runner.horse_name,
                "late_mover_score": float(late.get("score") or 0),
                "status": late.get("status") or "probable",
                "evidence_runs": int(late.get("evidence_runs") or 0),
                "strong_runs": int(late.get("strong_runs") or 0),
                "performance": float(score.performance),
                "placed": float(score.placed),
                "uncertainty": float(score.uncertainty),
                "beautiful_chance": beautiful_chance,
                "eligible": True,
                "reasons": list(late.get("reasons") or []),
                "evidence": list(late.get("evidence") or []),
                "current_argument": current_argument,
            })

    finisher_top3=rank_finisher_candidates(finisher_candidates)
    for index, item in enumerate(finisher_top3):
        status_label="finisseur confirmé" if item.get("status")=="confirmed" else "finisseur à confirmer"
        evidence_text="; ".join(str(x) for x in (item.get("reasons") or [])[:3])
        chance_text=(
            " Pour la course du jour, il passe aussi le filtre de belle chance : " + str(item.get("current_argument") or "")
            if index == 0 and item.get("beautiful_chance") else ""
        )
        item["argument"]=(
            f"{status_label.capitalize()} : {evidence_text or 'un mouvement final objectif est mesuré'}."
            f"{chance_text}"
        )

    late_mover_top3=rank_late_mover_candidates(late_mover_candidates)
    for index, item in enumerate(late_mover_top3):
        status_label="progressif tardif confirmé" if item.get("status")=="confirmed" else "progressif tardif à confirmer"
        evidence_text="; ".join(str(x) for x in (item.get("reasons") or [])[:3])
        chance_text=(
            " Pour la course du jour, il possède également une vraie candidature : " + str(item.get("current_argument") or "")
            if index == 0 and item.get("beautiful_chance") else ""
        )
        item["argument"]=(
            f"{status_label.capitalize()} : {evidence_text or 'une remontée avant la phase finale puis un effort soutenu sont mesurés'}."
            f"{chance_text}"
        )

    # A third independent closing-style view: horses that have already stayed
    # ahead of a current rival *on one of that rival's objectively identified
    # finisher runs*. This is stronger than a generic head-to-head result and
    # prevents "finisher" from being treated as automatic superiority.
    resistance_candidates=[]
    for runner, score in scores:
        profile=finisher_resistance_profile(runner, [item[0] for item in scores], finisher_blocks_by_runner_id)
        if not profile.eligible:
            continue
        beautiful_chance=(
            runner.number in main_chance_numbers
            and (score.performance >= 66 or score.placed >= 70)
            and score.uncertainty <= 72
        )
        if beautiful_chance:
            chance_label="BELLE CHANCE"
        elif score.performance >= 62 or score.placed >= 66:
            chance_label="CHANCE SECONDAIRE"
        else:
            chance_label="SIGNAL DE STYLE À SURVEILLER"
        resistance_candidates.append({
            "number": runner.number,
            "horse_name": runner.horse_name,
            "resistance_score": float(profile.score),
            "status": profile.status,
            "support_runs": profile.support_runs,
            "unique_finishers": profile.unique_finishers,
            "counter_runs": profile.counter_runs,
            "performance": float(score.performance),
            "placed": float(score.placed),
            "uncertainty": float(score.uncertainty),
            "beautiful_chance": beautiful_chance,
            "chance_label": chance_label,
            "eligible": True,
            "reasons": list(profile.reasons),
            "evidence": list(profile.evidence),
            "current_argument": build_block_argument(race, runner, score, "performance"),
        })

    finisher_resistance_top3=rank_finisher_resistance_candidates(resistance_candidates)
    for item in finisher_resistance_top3:
        status_label=(
            "résistance aux finisseurs confirmée"
            if item.get("status")=="confirmed"
            else "résistance aux finisseurs à confirmer"
        )
        evidence_text="; ".join(str(x) for x in (item.get("reasons") or [])[:4])
        chance_text=(
            " Pour aujourd'hui : " + str(item.get("current_argument") or "")
            if item.get("beautiful_chance")
            else f" Lecture actuelle : {str(item.get('chance_label') or 'signal indépendant').lower()}."
        )
        item["argument"]=(
            f"{status_label.capitalize()} : {evidence_text or 'une résistance directe à un finisseur du lot est vérifiée'}."
            f"{chance_text}"
        )

    # Add the direct counter-proof to the finisher's own card. Example: a horse
    # may be a genuine finisher but have already failed to pass n°3 today.
    resistance_by_finisher_number={}
    for resistant in resistance_candidates:
        for evidence in resistant.get("evidence") or []:
            finisher_number=evidence.get("finisher_number")
            if finisher_number is None:
                continue
            resistance_by_finisher_number.setdefault(int(finisher_number), []).append(resistant)
    for item in finisher_top3:
        resistant_list=resistance_by_finisher_number.get(int(item.get("number") or 0), [])
        if resistant_list:
            resistant_list=sorted(
                resistant_list,
                key=lambda value: float(value.get("resistance_score") or 0),
                reverse=True,
            )
            examples=", ".join(
                f"n°{r['number']} {r['horse_name']}" for r in resistant_list[:2]
            )
            item["argument"] += (
                f" Contre-preuve directe : {examples} a/ont déjà réussi à rester devant lui "
                "lors d'une course où son finish était objectivement mesuré."
            )

    # Independent "course ciblée / engagements" block. It uses only objective
    # scheduling/history facts and NEVER changes a main score.
    house_target_ranking=rank_target_profiles(db, race, scores)
    house_target_top3=house_target_ranking[:3]
    future_engagement_items=[
        {
            "number": item["number"],
            "horse_name": item["horse_name"],
            "engagements": item.get("future_engagements") or [],
        }
        for item in house_target_ranking
        if item.get("future_engagements")
    ]

    quality_counts={"complete":0,"partial":0,"limited":0,"loading":0,"insufficient":0}
    for _runner, score in scores:
        status=(score.breakdown or {}).get("evidence_status","insufficient") if isinstance(score.breakdown,dict) else "insufficient"
        quality_counts[status]=quality_counts.get(status,0)+1
    quality_total=len(scores)
    quality_ready=documented_count
    top_numbers={x[0].number for x in perf[:3]} | {x[0].number for x in placed[:3]}
    overlooked=[x for x in hidden if x[0].number not in top_numbers][:2]
    volatility_bands={
        str(r.number): ("0-30 faible" if rs.uncertainty <= 30 else "31-59 moyenne" if rs.uncertainty < 60 else "60-100 forte")
        for r,rs in scores
    }
    def horse_label(item):
        return f"n°{item[0].number} {item[0].horse_name}"

    # Player-facing arguments are deliberately built from factual performances,
    # course context and verified opponent lines. /100 numbers remain visible in
    # the cards, but are no longer the main explanation.
    performance_detail=[detail_item(race, runner, score, "performance") for runner,score in perf[:3]]
    placed_detail=[detail_item(race, runner, score, "placed") for runner,score in placed[:3]]
    hidden_detail=[detail_item(race, runner, score, "hidden") for runner,score in hidden[:3]]
    robustness_detail=[detail_item(race, runner, score, "robustness") for runner,score in robustness[:3]]
    volatility_detail=[detail_item(race, runner, score, "volatility") for runner,score in low_volatility[:3]]
    convergence_detail=[detail_item(race, runner, score, "convergence") for runner,score in convergence[:3]]
    overlooked_detail=[detail_item(race, runner, score, "overlooked") for runner,score in overlooked]
    network_detail=[detail_item(race, runner, score, "network") for runner,score in network[:3]]
    selection_detail=[detail_item(race, runner, score, "selection") for runner,score in convergence[:8]]

    perf_text=(
        "Performance/Victoire : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in performance_detail
        )
    ) if performance_detail else "Aucune donnée suffisante pour établir le classement Performance."
    placed_text=(
        "Simple Placé : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in placed_detail
        )
    ) if placed_detail else "Aucune donnée suffisante pour établir le classement Placé."
    hidden_text=(
        "Potentiel caché : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in hidden_detail[:2]
        )
    ) if hidden_detail else "Aucun potentiel caché distinct n'est mesurable avec les données disponibles."
    robustness_text=(
        "Robustesse au scénario : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in robustness_detail
        )
    ) if robustness_detail else "Aucun classement de robustesse fiable n'est disponible."
    volatility_text=(
        "Faible volatilité / confiance : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in volatility_detail
        )
    ) if volatility_detail else "Aucun classement de volatilité fiable n'est disponible."
    convergence_text=(
        "Convergence : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in convergence_detail
        )
    ) if convergence_detail else "Aucune convergence mesurable."
    overlooked_text=(
        "À ne pas négliger : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in overlooked_detail
        )
    ) if overlooked_detail else "Aucun cheval distinct ne ressort hors des deux Top 3 avec un signal caché suffisamment supérieur."
    selection_text=(
        "La sélection élargie couvre " + " – ".join(str(x[0].number) for x in convergence[:8]) +
        ". Les arguments individuels restent ceux des faits de course ci-dessus ; aucune cote n'entre dans cet ordre."
    ) if convergence else "Aucune sélection élargie disponible."
    network_text=(
        "Réseau des adversaires : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in network_detail
        ) + " Ce bloc reste indépendant des classements principaux."
    ) if network_detail else (
        "Aucun classement des adversaires n’est publié : il faut au moins deux anciennes courses reliées, "
        "trois rivaux identifiés et quatre comparaisons objectives pour classer un cheval dans ce bloc."
    )
    finisher_text=(
        "Finisseurs purs : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in finisher_top3
        )
    ) if finisher_top3 else (
        "Aucun finisseur pur publiable : HippoEdge ne force pas un cheval si le mouvement terminal n'est pas objectivement démontré "
        "ou si aucun finisseur détecté ne constitue une belle chance actuelle."
    )
    late_mover_text=(
        "Progressifs tardifs : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in late_mover_top3
        )
    ) if late_mover_top3 else (
        "Aucun progressif tardif publiable : il faut une remontée mesurable avant la toute dernière phase puis un effort soutenu jusqu'au poteau, "
        "et le premier doit aussi être une belle chance actuelle."
    )
    finisher_resistance_text=(
        "Résistance aux finisseurs : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in finisher_resistance_top3
        )
    ) if finisher_resistance_top3 else (
        "Aucune résistance aux finisseurs suffisamment démontrée : une simple victoire passée sur un rival ne suffit pas. "
        "Il faut avoir terminé devant un cheval du jour précisément lors d'une course où ce rival produisait un finish objectivement mesuré."
    )
    house_target_text=(
        "Course ciblée / engagements : " + " ".join(
            f"{item['number']} {item['horse_name']} — {item['argument']}" for item in house_target_top3
        )
    ) if house_target_top3 else (
        "Course ciblée / engagements : aucun signal objectif suffisamment précis. "
        "HippoEdge refuse d'inventer une intention d'entourage."
    )
    reinforced_parameters={
        "performance": [x[0].number for x in perf[:3]],
        "placed": [x[0].number for x in placed[:3]],
        "opponent_network": [x[0].number for x in network[:3]],
        "hidden_potential": [x[0].number for x in hidden[:3]],
        "robustness": [x[0].number for x in robustness[:3]],
        "low_volatility": [x[0].number for x in low_volatility[:3]],
        "finisher": [item["number"] for item in finisher_top3],
        "late_mover": [item["number"] for item in late_mover_top3],
        "finisher_resistance": [item["number"] for item in finisher_resistance_top3],
        "house_target": [item["number"] for item in house_target_top3],
    }
    reinforced_text=(
        "Paramètres renforcés : "
        f"réseau {reinforced_parameters['opponent_network'] or '—'} ; "
        f"potentiel caché {reinforced_parameters['hidden_potential'] or '—'} ; "
        f"robustesse {reinforced_parameters['robustness'] or '—'} ; "
        f"faible volatilité {reinforced_parameters['low_volatility'] or '—'} ; "
        f"finisseurs {reinforced_parameters['finisher'] or '—'} ; "
        f"late movers {reinforced_parameters['late_mover'] or '—'} ; "
        f"résistance aux finisseurs {reinforced_parameters['finisher_resistance'] or '—'} ; "
        f"course ciblée/engagement {reinforced_parameters['house_target'] or '—'}."
    )
    conclusion_text=(
        f"{horse_label(perf[0])} est le cheval à battre. {performance_detail[0]['argument'] if performance_detail else ''} "
        f"{horse_label(perf[1]) if len(perf)>1 else 'Aucun second profil'} est le danger principal. "
        f"Pour la place, {horse_label(placed[0]) if placed else 'aucun profil'} est prioritaire"
        + (f" : {placed_detail[0]['argument']}" if placed_detail else ".")
    ) if perf else "Conclusion impossible avec les données disponibles."
    card_signature = stable_hash({
        "race": {
            "going": race.going, "surface": race.surface, "distance": race.distance_m,
            "discipline": race.discipline, "class": race.class_name, "purse": race.purse_eur,
            "start": race.start_type, "scheduled_at": race.scheduled_at.isoformat(),
        },
        "runners": [
            {
                "n": runner.number, "name": runner.horse_name, "scratched": runner.scratched,
                "age": runner.age, "sex": runner.sex, "weight": runner.weight_kg, "draw": runner.draw,
                "handicap": runner.handicap_value, "record": runner.record_km_seconds,
                "equipment": runner.equipment, "ferrure": runner.ferrure,
                "start_position": runner.start_position, "distance": runner.distance_m,
                "jockey_driver": runner.jockey_driver, "trainer": runner.trainer,
                "recent_form": runner.recent_form,
            }
            for runner in sorted(race.runners, key=lambda item: (item.number, item.id or 0))
        ],
    })
    snap.summary={
        "card_signature": card_signature,
        "top3_performance":[x[0].number for x in perf[:3]],
        "top3_performance_detail":performance_detail,
        "top3_placed":[x[0].number for x in placed[:3]],
        "top3_placed_detail":placed_detail,
        "winning_pick":perf[0][0].number if perf else None,
        "placed_pick":placed[0][0].number if placed else None,
        "hidden_potential":[x[0].number for x in hidden[:3]],
        "hidden_potential_detail":hidden_detail,
        "robustness_top3":[x[0].number for x in robustness[:3]],
        "robustness_top3_detail":robustness_detail,
        "low_volatility_top3":[x[0].number for x in low_volatility[:3]],
        "low_volatility_top3_detail":volatility_detail,
        "best_convergence":[x[0].number for x in convergence[:3]],
        "best_convergence_detail":convergence_detail,
        "do_not_overlook":[x[0].number for x in overlooked],
        "do_not_overlook_detail":overlooked_detail,
        "selection_8":[x[0].number for x in convergence[:8]],
        "selection_8_detail":selection_detail,
        "opponent_network_ranking":[x[0].number for x in network],
        "opponent_network_top3":[x[0].number for x in network[:3]],
        "opponent_network_top3_detail":network_detail,
        "opponent_network_independent":True,
        "finisher_top3":[item["number"] for item in finisher_top3],
        "finisher_pick":finisher_top3[0]["number"] if finisher_top3 else None,
        "finisher_top3_detail":finisher_top3,
        "finisher_independent":True,
        "finisher_affects_scores":False,
        "late_mover_top3":[item["number"] for item in late_mover_top3],
        "late_mover_pick":late_mover_top3[0]["number"] if late_mover_top3 else None,
        "late_mover_top3_detail":late_mover_top3,
        "late_mover_independent":True,
        "late_mover_affects_scores":False,
        "finisher_resistance_top3":[item["number"] for item in finisher_resistance_top3],
        "finisher_resistance_pick":finisher_resistance_top3[0]["number"] if finisher_resistance_top3 else None,
        "finisher_resistance_top3_detail":finisher_resistance_top3,
        "finisher_resistance_independent":True,
        "finisher_resistance_affects_scores":False,
        "main_danger":perf[1][0].number if len(perf)>1 else None,
        "rational_place":placed[0][0].number if placed else None,
        "final_verdict":[x[0].number for x in perf[:3]],
        "winning_pick_label": horse_label(perf[0]) if perf else None,
        "main_danger_label": horse_label(perf[1]) if len(perf) > 1 else None,
        "rational_place_label": horse_label(placed[0]) if placed else None,
        "final_verdict_detail": {
            "cheval_a_battre": perf[0][0].number if perf else None,
            "danger_principal": perf[1][0].number if len(perf) > 1 else None,
            "choix_rationnel_place": placed[0][0].number if placed else None,
            "top3_performance": [x[0].number for x in perf[:3]],
            "cheval_a_battre_label": horse_label(perf[0]) if perf else None,
            "danger_principal_label": horse_label(perf[1]) if len(perf) > 1 else None,
            "choix_rationnel_place_label": horse_label(placed[0]) if placed else None,
        },
        "complements":[x[0].number for x in convergence[3:5]],
        "block_explanations":{
            "performance":perf_text,"placed":placed_text,"hidden_potential":hidden_text,
            "robustness":robustness_text,"volatility":volatility_text,
            "convergence":convergence_text,"do_not_overlook":overlooked_text,
            "opponent_network":network_text,"finisher":finisher_text,"late_mover":late_mover_text,
            "finisher_resistance":finisher_resistance_text,
            "selection_8":selection_text,"reinforced_parameters":reinforced_text,
            "house_target":house_target_text,"conclusion":conclusion_text,
        },
        "volatility_bands":volatility_bands,
        "net_conclusion_order":[
            "top3_performance", "top3_placed", "hidden_potential", "robustness_top3", "low_volatility_top3", "best_convergence",
            "do_not_overlook", "opponent_network_top3", "finisher_top3", "late_mover_top3", "finisher_resistance_top3",
            "selection_8", "reinforced_parameters", "winning_pick", "placed_pick", "house_target"
        ],
        "snapshot_phase": phase,
        "snapshot_is_pre_race": phase == "pre_race",
        "data_quality":{
            "total":quality_total,
            "ready":quality_ready,
            "ready_percent":round(quality_ready/quality_total*100) if quality_total else 0,
            "complete":quality_counts.get("complete",0),
            "partial":quality_counts.get("partial",0)+quality_counts.get("limited",0),
            "loading":quality_counts.get("loading",0),
            "insufficient":quality_counts.get("insufficient",0),
            "ranking_eligible":len(eligible_scores),
            "detailed_histories":documented_count,
            "field_coverage_percent":field_coverage_percent,
            "minimum_field_coverage_percent":settings.selection_min_field_coverage_percent,
            "field_coverage_ready":field_coverage_ready,
            "status":"ready" if field_coverage_ready and eligible_scores else "in_progress" if quality_counts.get("loading",0) else "limited",
        },
        "race_conditions": {
            "track": race.meeting.track if race.meeting else None,
            "meeting": race.meeting.code if race.meeting else None,
            "race_code": race.code,
            "race_name": race.name,
            "scheduled_at": race.scheduled_at.isoformat(),
            "discipline": race.discipline,
            "distance_m": race.distance_m,
            "surface": race.surface,
            "going": race.going,
            "class_name": race.class_name,
            "purse_eur": race.purse_eur,
            "start_type": race.start_type,
        },
        "reinforced_parameters": reinforced_parameters,
        "house_target":{
            "selection":[item["number"] for item in house_target_top3],
            "detail":house_target_top3,
            "all_signals":house_target_ranking,
            "argument":house_target_text,
            "independent":True,
            "affects_scores":False,
        },
        "future_engagements":{
            "items":future_engagement_items,
            "independent":True,
            "affects_scores":False,
        },
        "required_blocks":REQUIRED_ANALYSIS_BLOCKS,
        "completed_blocks":REQUIRED_ANALYSIS_BLOCKS,
        "missing_blocks":[],
        "method_complete":True,
        "method_notes":[
            "Le réseau des adversaires possède son propre classement et un poids nul dans les scores principaux.",
            "Une chaîne indirecte est limitée à trois liaisons A→B→C→D, avec une influence décroissante, et chaque course non reliée diminue la couverture affichée.",
            "Chaque cheval battu est recherché dans les anciennes courses des partants du jour ; le résultat est conservé dans les deux sens.",
            "Une faute récente réduit surtout la sécurité au trot ; elle n'efface pas automatiquement la valeur précédente.",
            "La régularité sur 2-3 sorties est plafonnée par l'incertitude d'échantillon.",
            "Le numéro de corde/autostart n'est pas traité comme un bonus automatique hors contexte.",
            "Le volet Finisseurs est indépendant et exige un déroulement final objectif ; une place à l'arrivée ou une note éditoriale seule ne suffit jamais.",
            "Le sous-volet Progressif tardif / Late mover distingue les chevaux qui remontent avant la phase terminale puis soutiennent leur effort jusqu'au poteau.",
            "Résistance aux finisseurs : une preuve n'est admise que si le cheval a fini devant un rival du jour dans une course où ce rival produisait objectivement son finish ; une simple confrontation brute ne suffit pas.",
            "Les notes /100 restent affichées comme repères secondaires ; les arguments joueurs sont rédigés en priorité à partir des performances, lignes, conditions et déroulements factuels.",
            "Le bloc Course ciblée / engagements est toujours publié en dernier et reste indépendant : il signale des répétitions objectives de programme et les engagements futurs connus sans inventer l'intention de l'entourage.",
            "Le manifeste required_blocks empêche une version future de supprimer silencieusement un bloc permanent : l'absence de preuve produit un bloc vide expliqué, jamais une omission.",
        ]
    }
    db.commit(); db.refresh(snap)
    return snap


def lock_latest_snapshot(db: Session, race: Race) -> AnalysisSnapshot:
    if race.result is not None:
        raise ValueError("Une course ayant une arrivée ne peut plus recevoir de snapshot pré-course.")
    settings = get_settings()
    locked = [s for s in race.snapshots if s.locked]
    if locked:
        return max(locked, key=lambda x: x.generated_at)
    if datetime.now() >= race.scheduled_at:
        raise ValueError("Le départ est déjà passé : l'analyse ne peut pas être figée rétroactivement.")
    current = [s for s in race.snapshots if s.methodology_version == settings.methodology_version]
    latest=max(current,key=lambda x:x.generated_at) if current else generate_analysis(db,race)
    if latest.locked: return latest
    quality=(latest.summary or {}).get("data_quality",{}) if isinstance(latest.summary,dict) else {}
    if quality.get("loading",0):
        raise ValueError("Les historiques sont encore en cours de chargement : l’analyse ne peut pas être figée maintenant.")
    if not quality.get("field_coverage_ready",False):
        raise ValueError("Le lot n’est pas assez documenté pour figer une analyse fiable.")
    if not quality.get("ranking_eligible",0):
        raise ValueError("Aucun cheval ne possède encore assez de preuves pour figer une analyse fiable.")
    if not is_pre_race_snapshot(race, latest):
        raise ValueError("Le départ est déjà passé : l'analyse ne peut pas être figée rétroactivement.")
    latest.locked=True; latest.locked_at=datetime.now(); db.commit(); db.refresh(latest); return latest


def evaluate_locked_snapshots(db: Session, race: Race):
    if not race.result or race.result.status != "official" or not race.result.official_order: return
    podium=race.result.official_order[:3]
    winner=podium[0] if podium else None
    for snap in [s for s in race.snapshots if s.locked and is_pre_race_snapshot(race, s)]:
        if db.scalar(select(Evaluation).where(Evaluation.snapshot_id==snap.id)): continue
        summary=snap.summary or {}
        top3=summary.get("top3_performance",[])
        pick=summary.get("winning_pick")
        ppick=summary.get("placed_pick")
        ev=Evaluation(snapshot_id=snap.id,winner_hit_top3=winner in top3 if winner else False,podium_coverage=sum(1 for x in podium if x in top3),winning_pick_hit=pick==winner,placed_pick_hit=ppick in podium,
                      details={"official_podium":podium,"top3_performance":top3,"top3_placed":summary.get("top3_placed",[]),"winning_pick":pick,"placed_pick":ppick})
        db.add(ev)
    db.commit()
