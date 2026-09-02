from __future__ import annotations

from datetime import datetime
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
            selectinload(Race.snapshots).selectinload(AnalysisSnapshot.scores),
        )
    )


def generate_analysis(db: Session, race: Race, lock: bool = False) -> AnalysisSnapshot:
    settings=get_settings()
    data_fingerprint={
        "methodology_version":settings.methodology_version,
        "race": {
            "id":race.id,"going":race.going,"surface":race.surface,"distance":race.distance_m,
            "discipline":race.discipline,"class":race.class_name,"purse":race.purse_eur,
            "start":race.start_type,
        },
        "runners": [
            {
                "n":r.number,"name":r.horse_name,"scratched":r.scratched,"age":r.age,"sex":r.sex,
                "weight":r.weight_kg,"draw":r.draw,"handicap_value":r.handicap_value,
                "earnings":r.earnings_eur,"record":r.record_km_seconds,"ferrure":r.ferrure,
                "equipment":r.equipment,"start_position":r.start_position,"distance":r.distance_m,
                "jockey_driver":r.jockey_driver,"trainer":r.trainer,"recent_form":r.recent_form,
                "history":[
                    {
                        "d":h.race_date.isoformat(),"track":h.track,"code":h.race_code,
                        "discipline":h.discipline,"dist":h.distance_m,"going":h.going,
                        "p":h.position,"dq":h.disqualified,"t":h.chrono_km_seconds,
                        "class":h.class_name,"weight":h.weight_kg,"draw":h.draw,
                        "start":h.start_type,"equipment":h.equipment,"field":h.field_size,
                        "margin":h.margin_to_winner,"opponents":h.opponents,
                    }
                    for h in r.history
                ],
            }
            for r in race.runners
        ]
    }
    dh=stable_hash(data_fingerprint)
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
    perf=sorted(scores,key=lambda x:x[1].performance,reverse=True)
    placed=sorted(scores,key=lambda x:x[1].placed,reverse=True)
    hidden=sorted(scores,key=lambda x:x[1].hidden_potential,reverse=True)
    convergence=sorted(scores,key=lambda x:(x[1].performance+x[1].placed)/2,reverse=True)
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
            "selection_8":selection_text,"conclusion":conclusion_text,
        },
        "volatility_bands":volatility_bands,
        "net_conclusion_order":[
            "top3_performance", "top3_placed", "hidden_potential", "best_convergence",
            "do_not_overlook", "selection_8", "winning_pick", "placed_pick"
        ],
        "snapshot_phase": phase,
        "snapshot_is_pre_race": phase == "pre_race",
        "house_target":{"selection":[],"independent":True,"affects_scores":False},
        "method_notes":[
            "Les lignes indirectes restent un bonus de confirmation et ne dominent jamais la performance propre.",
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
