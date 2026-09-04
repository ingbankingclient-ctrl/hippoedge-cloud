from __future__ import annotations

from datetime import datetime
import hashlib
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import AnalysisSnapshot, Evaluation, Race, Runner, RunnerScore
from .scoring import score_race
from .utils import stable_hash

CONFIRMATION = (
    "Je confirme que le moteur n'utilise volontairement ni classements, ni pronostics, ni favoris, "
    "ni cotes, ni popularité, ni avis éditoriaux. La liste des partants provient de la fiche de course "
    "et les scores sont construits uniquement à partir des données objectives de course et de performance disponibles."
)


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
    def first_reason(item):
        return item[1].reasons[0].lower() if item[1].reasons else "son niveau objectif disponible"
    perf_text=(
        "Le modèle Performance/Victoire place " + ", ".join(
            f"{horse_label(x)} ({x[1].performance:.0f}/100, {first_reason(x)})" for x in perf[:3]
        ) + ". Ce classement recherche d’abord la capacité à produire la meilleure performance, pas seulement la régularité."
    ) if perf else "Aucune donnée suffisante pour établir le classement Performance."
    placed_text=(
        "Le modèle Simple Placé privilégie " + ", ".join(
            f"{horse_label(x)} ({x[1].placed:.0f}/100, robustesse {x[1].robustness:.0f}, volatilité {x[1].uncertainty:.0f})" for x in placed[:3]
        ) + ". Il valorise la sécurité et la répétabilité indépendamment du potentiel maximal de victoire."
    ) if placed else "Aucune donnée suffisante pour établir le classement Placé."
    hidden_text=(
        "Le potentiel caché retient " + ", ".join(
            f"{horse_label(x)} ({x[1].hidden_potential:.0f}/100)" for x in hidden[:2]
        ) + ". Leur forme visible peut sous-estimer une valeur ancienne, une progression ou une configuration du jour favorable ; la volatilité reste examinée séparément."
    ) if hidden else "Aucun potentiel caché distinct n'est mesurable avec les données disponibles."
    convergence_text=(
        "La convergence met en avant " + ", ".join(
            f"{horse_label(x)} (Performance {x[1].performance:.0f}, Placé {x[1].placed:.0f})" for x in convergence[:3]
        ) + ". Ils réunissent le mieux les deux lectures indépendantes, sans que l’une modifie l’autre."
    ) if convergence else "Aucune convergence mesurable."
    overlooked_text=(
        "À ne pas négliger : " + ", ".join(
            f"{horse_label(x)}, principalement pour {first_reason(x)}" for x in overlooked
        ) + ". Ces profils restent hors des priorités principales mais possèdent un signal interne suffisamment fort pour être signalés."
    ) if overlooked else "Aucun cheval distinct ne ressort hors des deux Top 3 avec un signal caché suffisamment supérieur."
    selection_text=(
        "La sélection élargie rassemble " + " – ".join(str(x[0].number) for x in convergence[:8]) +
        ". Elle couvre les meilleurs compromis Performance/Placé et les profils complémentaires sans intégrer la moindre cote."
    ) if convergence else "Aucune sélection élargie disponible."
    network_text=(
        "Le classement indépendant des adversaires place " + ", ".join(
            f"{horse_label(item)} ({item[1].breakdown['opponent_network']['score']:.0f}/100, "
            f"{item[1].breakdown['opponent_network']['linked_races']} courses reliées, "
            f"{item[1].breakdown['opponent_network']['confirmed_lines']} lignes confirmées, "
            f"{item[1].breakdown['opponent_network']['today_opponent_bridges']} passerelles vers le lot du jour)"
            for item in network[:3]
        ) + ". Il compare les duels passés, les résultats ultérieurs des chevaux croisés, leurs rencontres avec les partants du jour et les chaînes A→B→C→D. "
        "Ce bloc reste totalement indépendant : son ordre ne modifie aucune sélection principale."
    ) if network else (
        "Aucun classement des adversaires n’est publié : il faut au moins deux anciennes courses reliées, "
        "trois rivaux identifiés et quatre comparaisons objectives pour classer un cheval dans ce bloc."
    )
    conclusion_text=(
        f"{horse_label(perf[0])} est le cheval à battre et {horse_label(perf[1]) if len(perf)>1 else 'aucun second profil'} le danger principal dans le scénario Performance. "
        f"{horse_label(placed[0]) if placed else 'Aucun profil'} est le choix rationnel pour une place. Le verdict chiffré reste volontairement celui de la victoire ; le choix placé peut donc être différent ou absent de ce trio."
    ) if perf else "Conclusion impossible avec les données disponibles."
    snap.summary={
        "top3_performance":[x[0].number for x in perf[:3]],
        "top3_placed":[x[0].number for x in placed[:3]],
        "winning_pick":perf[0][0].number if perf else None,
        "placed_pick":placed[0][0].number if placed else None,
        "hidden_potential":[x[0].number for x in hidden[:2]],
        "best_convergence":[x[0].number for x in convergence[:3]],
        "do_not_overlook":[x[0].number for x in overlooked],
        "selection_8":[x[0].number for x in convergence[:8]],
        "opponent_network_ranking":[x[0].number for x in network],
        "opponent_network_top3":[x[0].number for x in network[:3]],
        "opponent_network_independent":True,
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
            "convergence":convergence_text,"do_not_overlook":overlooked_text,
            "opponent_network":network_text,"selection_8":selection_text,"conclusion":conclusion_text,
        },
        "volatility_bands":volatility_bands,
        "net_conclusion_order":[
            "top3_performance", "top3_placed", "hidden_potential", "best_convergence",
            "do_not_overlook", "opponent_network_top3", "selection_8", "winning_pick", "placed_pick"
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
        "house_target":{"selection":[],"independent":True,"affects_scores":False},
        "method_notes":[
            "Le réseau des adversaires possède son propre classement et un poids nul dans les scores principaux.",
            "Une chaîne indirecte est limitée à trois liaisons A→B→C→D, avec une influence décroissante, et chaque course non reliée diminue la couverture affichée.",
            "Chaque cheval battu est recherché dans les anciennes courses des partants du jour ; le résultat est conservé dans les deux sens.",
            "Une faute récente réduit surtout la sécurité au trot ; elle n'efface pas automatiquement la valeur précédente.",
            "La régularité sur 2-3 sorties est plafonnée par l'incertitude d'échantillon.",
            "Le numéro de corde/autostart n'est pas traité comme un bonus automatique hors contexte.",
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
