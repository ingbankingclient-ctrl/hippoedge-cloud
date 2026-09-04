from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Meeting, Race, Runner, HorseHistory, RaceResult, Evaluation
from .providers.base import RacingProvider
from .utils import parse_iso_or_local, parse_record_to_seconds, sanitize_objective_payload, to_float, to_int



def _first(d: dict, keys: Iterable[str], default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "oui", "y", "np", "non_partant", "non partant"}:
        return True
    if text in {"false", "0", "no", "non", "n", "partant"}:
        return False
    return default


def _form_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        value = _first(value, ("libelleCourt", "libelle", "value", "form"), "")
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    text = str(value).strip()
    return text or None


def _normalize_discipline(value: str | None) -> str:
    x = (value or "").strip().lower()
    if any(token in x for token in ("mont", "mounted", "saddle")):
        return "Trot monté"
    if any(token in x for token in ("attel", "trot", "harness", "standardbred", "pace", "pac(e)")):
        return "Trot attelé"
    if any(token in x for token in ("haie", "hurdle")):
        return "Haies"
    if any(token in x for token in ("steeple", "jump", "chase")):
        return "Steeple-chase"
    if "cross" in x: return "Cross"
    if any(token in x for token in ("plat", "galop", "flat", "thoroughbred")):
        return "Plat"
    return value or "Inconnue"


def _program_meetings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    for key in ("reunions", "réunions", "meetings"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    # Some APIs flatten courses; group later.
    courses = data.get("courses") if isinstance(data, dict) else None
    if isinstance(courses, list):
        groups: dict[tuple[str,str], dict] = {}
        for c in courses:
            code = str(_first(c, ["reunion", "code_reunion", "meeting"], "R?"))
            track = str(_first(c, ["hippodrome", "track", "lieu"], "Inconnu"))
            groups.setdefault((code,track), {"code":code,"hippodrome":track,"courses":[]})["courses"].append(c)
        return list(groups.values())
    return []


def _meeting_courses(m: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("courses", "races"):
        if isinstance(m.get(key), list): return m[key]
    return []


def _runner_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    for key in ("partants", "runners", "participants"):
        if isinstance(data, dict) and isinstance(data.get(key), list): return data[key]
    return []


def _history_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for key in ("historique", "history", "courses", "performances"):
            if isinstance(data.get(key), list): return data[key]
    return []


def _parse_position(v: Any) -> tuple[int | None, bool]:
    if v is None: return None, False
    s = str(v).strip().lower()
    dq = any(x in s for x in ("dai", "da", "dm", "dq", "disq", "dist"))
    m = re.search(r"\d+", s)
    return (int(m.group()) if m else None), dq


def _result_entries(value: Any) -> list[Any]:
    """Return arrival entries from the small shape variations used by feeds."""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        for key in (
            "ordre", "order", "arrivee", "arrival", "participants", "chevaux",
            "classement", "classements", "resultats", "results",
        ):
            nested = value.get(key)
            if isinstance(nested, (list, tuple)):
                return list(nested)
        # A single ranked runner is also a valid entry.
        if any(key in value for key in ("numPmu", "numeroPmu", "numero", "num", "number")):
            return [value]
    return []


def _result_number(value: Any) -> int | None:
    if isinstance(value, dict):
        return to_int(_first(value, ("numPmu", "numeroPmu", "numero", "num", "number", "numCheval")))
    return to_int(value)


class ImportService:
    def __init__(self, provider: RacingProvider):
        self.provider = provider

    async def import_day(self, db: Session, day: date, enrich_history: bool = True) -> list[Meeting]:
        payload = sanitize_objective_payload(await self.provider.get_program(day))
        meetings: list[Meeting] = []
        for mraw in _program_meetings(payload):
            mcode = str(_first(mraw, ["code", "code_reunion", "reunion"], "R?"))
            track = str(_first(mraw, ["hippodrome", "track", "lieu", "name"], "Inconnu"))
            meeting = db.scalar(select(Meeting).where(Meeting.race_date==day, Meeting.code==mcode, Meeting.track==track))
            if not meeting:
                meeting = Meeting(race_date=day, code=mcode, track=track, country=_first(mraw,["pays","country"]), source=self.provider.name)
                db.add(meeting); db.flush()
            else:
                meeting.country = _first(mraw, ["pays", "country"], meeting.country)
                meeting.source = self.provider.name
            meetings.append(meeting)
            for craw in _meeting_courses(mraw):
                rcode = str(_first(craw,["code_course","code","rc"], ""))
                if not rcode:
                    # derive Cn from index if needed
                    rcode = f"{mcode}C{len(meeting.races)+1}"
                scheduled = parse_iso_or_local(day.isoformat(), str(_first(craw,["heure","heure_depart","time"],"12:00")))
                race = db.scalar(select(Race).where(Race.meeting_id==meeting.id, Race.code==rcode))
                if not race:
                    race = Race(meeting_id=meeting.id, code=rcode, name=str(_first(craw,["prix","name","nom"],rcode)), scheduled_at=scheduled,
                                discipline=_normalize_discipline(_first(craw,["discipline","specialite","type"])), distance_m=to_int(_first(craw,["distance","distance_m"])),
                                surface=_first(craw,["surface"]), going=_first(craw,["terrain","going"]), class_name=_first(craw,["classe","class","categorie"]),
                                purse_eur=to_int(_first(craw,["allocation","montant","purse"])), start_type=_first(craw,["depart","start_type","mode_depart"]),
                                source_ref=_first(craw,["url","source_ref"]), raw=sanitize_objective_payload(craw))
                    db.add(race); db.flush()
                else:
                    race.scheduled_at=scheduled; race.going=_first(craw,["terrain","going"],race.going); race.raw=sanitize_objective_payload(craw)
                    race.name = str(_first(craw, ["prix", "name", "nom"], race.name))
                    race.discipline = _normalize_discipline(_first(craw, ["discipline", "specialite", "type"], race.discipline))
                    race.distance_m = to_int(_first(craw, ["distance", "distance_m"], race.distance_m))
                    race.surface = _first(craw, ["surface"], race.surface)
                    race.class_name = _first(craw, ["classe", "class", "categorie"], race.class_name)
                    race.purse_eur = to_int(_first(craw, ["allocation", "montant", "purse"], race.purse_eur))
                    race.start_type = _first(craw, ["depart", "start_type", "mode_depart"], race.start_type)
                # Fetch exact runners from race endpoint rather than trusting program summaries.
                try:
                    rp = sanitize_objective_payload(await self.provider.get_race(day, rcode, track))
                except Exception as e:
                    race.raw = {**(race.raw or {}), "runner_import_warning": str(e)}
                    continue
                # Database errors must propagate to the transaction owner. Catching
                # them here would leave SQLAlchemy in PendingRollbackError state.
                await self._upsert_runners(db, race, rp, enrich_history)
        db.commit()
        return meetings

    async def _upsert_runners(self, db: Session, race: Race, payload: dict[str,Any], enrich_history: bool):
        for p in _runner_list(payload):
            num = to_int(_first(p,["num","numero","number"]))
            name = str(_first(p,["name","cheval","nom"], "")).strip()
            if not num or not name: continue
            runner = db.scalar(select(Runner).where(Runner.race_id==race.id, Runner.number==num))
            if not runner:
                runner=Runner(race_id=race.id, number=num, horse_name=name)
                db.add(runner); db.flush()
            runner.horse_name=name
            runner.horse_external_id=str(_first(p,["idcheval","horse_id","id_cheval"], runner.horse_external_id or "")) or None
            runner.age=to_int(_first(p,["age"],runner.age)); runner.sex=_first(p,["sexe","sex","sa"],runner.sex)
            runner.weight_kg=to_float(_first(p,["poids","weight","poids_kg"],runner.weight_kg)); runner.draw=to_int(_first(p,["corde","draw"],runner.draw))
            runner.handicap_value=to_float(_first(p,["valeur","handicap_value"],runner.handicap_value)); runner.earnings_eur=to_float(_first(p,["gains","earnings"],runner.earnings_eur))
            runner.record_km_seconds=parse_record_to_seconds(_first(p,["record","reduction_km","record_km"],runner.record_km_seconds)) or runner.record_km_seconds
            runner.ferrure=_first(p,["ferrure","fer"],runner.ferrure); runner.equipment=_first(p,["equipement","equipment","oeilleres"],runner.equipment)
            # The exact race endpoint is authoritative.  Clearing a missing
            # start position also removes values created by older adapters that
            # incorrectly copied the galop draw into this field.
            runner.start_position=to_int(_first(p,["position_depart","autostart","numero_autostart"]))
            runner.distance_m=to_int(_first(p,["distance","distance_m"],runner.distance_m)); runner.jockey_driver=_first(p,["jockey_driver","driver","jockey"],runner.jockey_driver)
            runner.trainer=_first(p,["entraineur","trainer"],runner.trainer); runner.recent_form=_form_text(_first(p,["musique","form"],runner.recent_form))
            runner.scratched=_to_bool(_first(p,["np","non_partant","scratched"],False))
            previous_raw = runner.raw if isinstance(runner.raw, dict) else {}
            history_meta = {
                key: value
                for key, value in previous_raw.items()
                if key.startswith("history_") or key.startswith("opponent_")
            }
            runner.raw={**sanitize_objective_payload(p), **history_meta}
            if not runner.history and runner.horse_external_id:
                # Reuse an exact PMU horse identity already persisted on a
                # previous card. This gives the new race an immediate factual
                # baseline while the source cascade refreshes it in background.
                cached=db.scalar(
                    select(Runner)
                    .where(
                        Runner.id!=runner.id,
                        Runner.horse_external_id==runner.horse_external_id,
                    )
                    .options(selectinload(Runner.history))
                    .order_by(Runner.id.desc())
                )
                if cached is not None and cached.history:
                    for old in cached.history:
                        runner.history.append(HorseHistory(
                            race_date=old.race_date,track=old.track,race_code=old.race_code,
                            discipline=old.discipline,distance_m=old.distance_m,going=old.going,
                            position=old.position,disqualified=old.disqualified,
                            chrono_km_seconds=old.chrono_km_seconds,class_name=old.class_name,
                            weight_kg=old.weight_kg,draw=old.draw,start_type=old.start_type,
                            equipment=old.equipment,field_size=old.field_size,
                            margin_to_winner=old.margin_to_winner,
                            opponents=sanitize_objective_payload(old.opponents or []),
                            raw=sanitize_objective_payload(old.raw or {}),
                        ))
                    cached_raw=cached.raw if isinstance(cached.raw,dict) else {}
                    runner.raw={
                        **runner.raw,
                        "history_source":cached_raw.get("history_source"),
                        "history_status":"pending",
                        "history_rows":len(runner.history),
                        "history_cache_reused_from":cached.id,
                    }
            if not runner.history and not runner.raw.get("history_status"):
                runner.raw={**runner.raw, "history_status":"pending", "history_rows":0}
            if enrich_history and not runner.history:
                try:
                    hp = sanitize_objective_payload(await self.provider.get_horse_history(
                        runner.horse_external_id or runner.horse_name,
                        race.discipline,
                        horse_name=runner.horse_name,
                        race_date=race.meeting.race_date if race.meeting else None,
                    ))
                    imported = self._replace_history(db, runner, hp)
                    meta = hp.get("meta", {}) if isinstance(hp, dict) else {}
                    runner.raw={**(runner.raw or {}),"history_source":meta.get("source"),"history_status":meta.get("status"),"history_rows":imported}
                except Exception as e:
                    runner.raw={
                        **(runner.raw or {}),
                        "history_status":"unavailable",
                        "history_warning":str(e),
                        "history_rows":0,
                    }
        db.flush()

    def _replace_history(self, db: Session, runner: Runner, payload: dict[str,Any]) -> int:
        """Merge historical facts from complementary objective sources.

        The method keeps its old public name for compatibility.  Replacing the
        full collection used to erase PMU opponent lists when a longer Geny or
        LeTROT profile arrived afterwards.  Rows are now merged by race identity
        and richer fields are preserved.
        """
        rows=_history_list(payload)
        if not rows: return len(runner.history)

        def fallback_key(race_date: date, track: Any, distance: Any) -> tuple[str, str, int | None]:
            return (race_date.isoformat(), str(track or "").strip().casefold(), to_int(distance))

        def geny_course_id(raw: Any) -> str | None:
            if not isinstance(raw, dict):
                return None
            value = str(raw.get("geny_course_id") or "").strip()
            return value if value.isdigit() else None

        existing_exact = {
            course_id: item
            for item in runner.history
            if (course_id := geny_course_id(item.raw)) is not None
        }
        existing_fallback: dict[tuple[str, str, int | None], list[HorseHistory]] = {}
        for item in runner.history:
            existing_fallback.setdefault(
                fallback_key(item.race_date, item.track, item.distance_m), []
            ).append(item)
        seen_exact: set[str] = set()
        seen_without_id: set[tuple[str, str, int | None]] = set()
        for h in rows:
            ds=str(_first(h,["date","date_course","race_date"],""))[:10]
            try: d=date.fromisoformat(ds)
            except Exception:
                parsed = None
                for fmt in ("%d/%m/%Y", "%d/%m/%y"):
                    try:
                        parsed = datetime.strptime(ds, fmt).date()
                        break
                    except ValueError:
                        pass
                if parsed is None: continue
                d = parsed
            pos,dq=_parse_position(_first(h,["position","rang","rank","arrivee"]))
            dq=_to_bool(_first(h,["disqualifie","disqualified"],dq), dq)
            track = _first(h,["hippodrome","track","lieu"])
            distance = to_int(_first(h,["distance","distance_m"]))
            key=fallback_key(d, track, distance)
            incoming_raw = sanitize_objective_payload(h)
            incoming_course_id = geny_course_id(incoming_raw)
            if incoming_course_id:
                if incoming_course_id in seen_exact:
                    continue
                seen_exact.add(incoming_course_id)
            else:
                if key in seen_without_id:
                    continue
                seen_without_id.add(key)

            race_code_value = _first(h,["code_course","race_code"])
            race_code = str(race_code_value)[:32] if race_code_value not in (None, "") else None
            values = {
                "track": track,
                # Production databases created by earlier versions use
                # VARCHAR(32). The complete race name remains untouched in
                # ``raw['nom_course']``; this compatibility field is bounded.
                "race_code": race_code,
                "discipline": _normalize_discipline(_first(h,["discipline","specialite"])),
                "distance_m": distance,
                "going": _first(h,["terrain","going"]),
                "position": pos,
                "chrono_km_seconds": parse_record_to_seconds(_first(h,["reduction_km","chrono_km","record"])),
                "class_name": _first(h,["classe","class","categorie"]),
                "weight_kg": to_float(_first(h,["poids","weight"])),
                "draw": to_int(_first(h,["corde","draw"])),
                "start_type": _first(h,["depart","start_type"]),
                "equipment": _first(h,["ferrure","fer","equipement","equipment"]),
                "field_size": to_int(_first(h,["nb_partants","field_size"])),
                "margin_to_winner": to_float(_first(h,["ecart_gagnant","margin_to_winner"])),
            }
            incoming_opponents = sanitize_objective_payload(_first(h,["adversaires","opponents"],[]) or [])
            item = existing_exact.get(incoming_course_id) if incoming_course_id else None
            if item is None:
                candidates = existing_fallback.get(key, [])
                if incoming_course_id:
                    candidates = [candidate for candidate in candidates if geny_course_id(candidate.raw) is None]
                if len(candidates) == 1:
                    item = candidates[0]
            if item is None:
                item=HorseHistory(
                    runner_id=runner.id,
                    race_date=d,
                    disqualified=dq,
                    opponents=incoming_opponents,
                    raw=incoming_raw,
                    **values,
                )
                runner.history.append(item)
                existing_fallback.setdefault(key, []).append(item)
                if incoming_course_id:
                    existing_exact[incoming_course_id] = item
                continue

            for field, value in values.items():
                if getattr(item, field) in (None, "") and value not in (None, ""):
                    setattr(item, field, value)
            item.disqualified = bool(item.disqualified or dq)
            if item.position is None and pos is not None and not item.disqualified:
                item.position = pos
            if incoming_opponents:
                combined: dict[str, dict[str, Any]] = {}
                for opponent in [*(item.opponents or []), *incoming_opponents]:
                    if not isinstance(opponent, dict):
                        continue
                    label = str(_first(opponent, ["horse_name","nom_cheval","name","nom"], "")).strip()
                    opponent_key = label.casefold() or str(opponent)
                    if opponent_key not in combined:
                        combined[opponent_key] = dict(opponent)
                    else:
                        combined[opponent_key] = {
                            **combined[opponent_key],
                            **{key: value for key, value in opponent.items() if value not in (None, "", [])},
                        }
                item.opponents = list(combined.values())
            item.raw = {
                **(item.raw or {}),
                **{key: value for key, value in incoming_raw.items() if value not in (None, "", [])},
            }
            if incoming_course_id:
                existing_exact[incoming_course_id] = item
        db.flush()
        return len(runner.history)

    async def import_results(self, db: Session, day: date):
        payload=sanitize_objective_payload(await self.provider.get_results(day))
        data=payload.get("data",payload)
        results=data.get("results",[]) if isinstance(data,dict) else []
        for rr in results:
            code=str(_first(rr,["code_course","code","rc"],"")); track=str(_first(rr,["hippodrome","track"],""))
            meeting_code = code.upper().split("C", 1)[0] if "C" in code.upper() else ""
            query = select(Race).join(Meeting).where(Meeting.race_date == day, Race.code == code)
            if meeting_code:
                query = query.where(Meeting.code == meeting_code)
            if track:
                query = query.where(Meeting.track.ilike(f"%{track}%"))
            race = db.scalar(query)
            # Some result feeds omit the track or spell it differently. The
            # meeting code remains a safer identity than the first same-number
            # course found on the day.
            if race is None and meeting_code:
                race = db.scalar(
                    select(Race).join(Meeting).where(
                        Meeting.race_date == day,
                        Meeting.code == meeting_code,
                        Race.code == code,
                    )
                )
            if not race: continue
            arrival=_result_entries(_first(rr,["arrivee","arrival","ordre"],[]) or [])
            order=[]
            seen_numbers: set[int] = set()
            for x in arrival:
                if isinstance(x,dict):
                    n=_result_number(x); rank=to_int(_first(x,["rank","rang","position","ordre"]));
                    if n and n not in seen_numbers and (rank or 99)>0:
                        order.append((rank or 99,n)); seen_numbers.add(n)
                else:
                    n=_result_number(x)
                    if n and n not in seen_numbers:
                        order.append((len(order)+1,n)); seen_numbers.add(n)
            order=[n for _,n in sorted(order)]
            non_finishers=[_result_number(x) for x in _result_entries(_first(rr,["non_classes","non_finishers","nonClassement"],[]) or [])]
            non_finishers=[x for x in non_finishers if x]
            result_status=str(_first(rr,["result_status","status"],"official") or "official").lower()
            result_status="provisional" if result_status in {"provisional", "provisoire", "provision", "pending"} else "official"
            result_raw={**rr,"result_status":result_status}
            # A transient feed regression must not downgrade a published
            # official arrival back to provisional (or erase its order).
            if race.result and race.result.status == "official" and result_status == "provisional":
                continue
            if race.result and race.result.status == "official" and not order:
                continue
            if result_status == "official" and not order and (not race.result or race.result.status == "provisional"):
                # Do not promote an incomplete/ambiguous payload to official.
                continue
            if not race.result:
                race.result=RaceResult(official_order=order,non_finishers=non_finishers,raw=result_raw)
            else:
                race.result.official_order=order or race.result.official_order
                race.result.non_finishers=non_finishers or race.result.non_finishers
                race.result.raw={**(race.result.raw or {}), **result_raw}
            race.status="result_provisional" if result_status=="provisional" else "finished"
        db.commit()
