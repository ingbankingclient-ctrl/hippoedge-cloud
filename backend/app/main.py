from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .analysis_service import (
    CONFIRMATION,
    evaluate_locked_snapshots,
    generate_analysis,
    is_pre_race_snapshot,
    lock_latest_snapshot,
)
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .importer import ImportService
from .models import AnalysisSnapshot, Evaluation, HistoricalRaceCache, HorseHistory, Meeting, Race, Runner, RunnerScore
from .opponent_network import normalized_horse_name
from .providers import DemoProvider, PmuProvider, TurfBzhProvider
from .schemas import AnalysisOut, MeetingOut, ScoreOut
from .selection_service import choose
from .utils import sanitize_objective_payload, to_int

settings=get_settings()
HISTORY_ENRICHMENT_VERSION = "2026.09.04-v6-unlimited"
PMU_OPPONENT_ENRICHMENT_VERSION = "2026.09.03-v3-pmu"
OPPONENT_ENRICHMENT_VERSION = "2026.09.04-v4-complete-retry"


def _source_label(current: object, incoming: object) -> str | None:
    labels: list[str] = []
    for value in (current, incoming):
        for label in str(value or "").split(" + "):
            label = label.strip()
            if label and label not in labels:
                labels.append(label)
    return " + ".join(labels) or None


def provider_factory():
    if settings.provider.lower()=="pmu":
        return PmuProvider(
            settings.pmu_base_url,
            letrot_base_url=settings.letrot_base_url,
            france_galop_base_url=settings.france_galop_base_url,
            geny_base_url=settings.geny_base_url,
            geny_history_enabled=settings.geny_history_enabled,
            official_history_enabled=settings.official_history_enabled,
            history_request_interval_seconds=settings.history_request_interval_seconds,
            history_max_rows=settings.history_max_rows,
            history_cache_size=settings.history_cache_size,
            history_course_cache_size=settings.history_course_cache_size,
            history_directory_cache_size=settings.history_directory_cache_size,
        )
    if settings.provider.lower()=="turfbzh":
        return TurfBzhProvider(settings.turfbzh_base_url, settings.turfbzh_api_key)
    return DemoProvider()


def _schedule_history_enrichment(
    day: date,
    write_lock: asyncio.Lock,
    tasks: dict[date, asyncio.Task],
) -> None:
    existing = tasks.get(day)
    if existing is None or existing.done():
        tasks[day] = asyncio.create_task(_enrich_day_histories_safe(day, write_lock))


def _merge_objective_opponents(
    existing: list[dict],
    incoming: list[dict],
    own_name: str,
    own_geny_id: str | None,
) -> list[dict]:
    """Merge a full historical field while excluding the horse itself."""
    combined: dict[str, dict] = {}
    own_normalized = normalized_horse_name(own_name)
    for opponent in [*existing, *incoming]:
        if not isinstance(opponent, dict):
            continue
        label = str(
            opponent.get("horse_name") or opponent.get("nom_cheval")
            or opponent.get("name") or opponent.get("nom") or ""
        ).strip()
        opponent_id = str(opponent.get("geny_horse_id") or "").strip() or None
        if (own_geny_id and opponent_id == own_geny_id) or normalized_horse_name(label) == own_normalized:
            continue
        if not label:
            continue
        key = f"id:{opponent_id}" if opponent_id else f"name:{normalized_horse_name(label)}"
        clean = sanitize_objective_payload(opponent)
        if key not in combined:
            combined[key] = clean
        else:
            combined[key] = {
                **combined[key],
                **{field: value for field, value in clean.items() if value not in (None, "", [])},
            }
    return list(combined.values())


def _recent_lookup_failure(raw: dict) -> bool:
    if str(raw.get("geny_course_lookup_status") or "") != "unavailable":
        return False
    checked = str(raw.get("geny_course_checked_at") or "").strip()
    if not checked:
        return False
    try:
        checked_at = datetime.fromisoformat(checked)
    except ValueError:
        return False
    now = datetime.now(checked_at.tzinfo) if checked_at.tzinfo is not None else datetime.now()
    return (now - checked_at).total_seconds() < max(0, int(settings.history_course_retry_cooldown_seconds))


async def _enrich_geny_course_details(
    day: date,
    write_lock: asyncio.Lock,
    provider: object,
    *,
    race_id: int | None = None,
    request: Request | None = None,
) -> bool:
    """Attach exact historical-race participants in bounded parallel batches.

    The source remains request-throttled by OfficialHistoryClient.  Here we only
    stop wasting time by waiting for one remote response before starting the
    next request, and we persist one whole batch in one transaction.  Complete
    histories and A→B→C→D semantics are unchanged.
    """
    detail_method = getattr(provider, "get_historical_course", None)
    if not callable(detail_method):
        return False

    db = SessionLocal()
    try:
        history_query = (
            select(HorseHistory.id, HorseHistory.race_date, HorseHistory.raw)
            .join(Runner)
            .join(Race)
            .join(Meeting)
        )
        history_query = (
            history_query.where(Race.id == race_id)
            if race_id is not None
            else history_query.where(Meeting.race_date == day)
        )
        history_rows = db.execute(history_query).all()
        grouped: dict[str, list[int]] = {}
        dates: dict[str, date] = {}
        for history_id, history_date, history_raw in history_rows:
            raw = history_raw if isinstance(history_raw, dict) else {}
            course_id = str(raw.get("geny_course_id") or "").strip()
            if not course_id.isdigit():
                continue
            status = str(raw.get("geny_course_lookup_status") or "")
            if status == "ok" or status in {"no_participants", "identity_mismatch"}:
                continue
            if _recent_lookup_failure(raw):
                continue
            grouped.setdefault(course_id, []).append(history_id)
            dates[course_id] = max(dates.get(course_id, history_date), history_date)
    finally:
        db.close()

    ordered_ids = sorted(grouped, key=lambda item: dates[item], reverse=True)
    batch_size = max(1, min(int(settings.history_course_batch_size), 500))
    selected_ids = ordered_ids[:batch_size]
    pending_after_batch = len(ordered_ids) > len(selected_ids)
    if not selected_ids:
        return False

    # Persistent exact-race cache shared by every current runner/day. A Geny
    # course fetched once should never need to be downloaded again merely
    # because another horse or another page references the same course.
    db = SessionLocal()
    try:
        cached_rows = db.scalars(
            select(HistoricalRaceCache).where(HistoricalRaceCache.course_id.in_(selected_ids))
        ).all()
        cached_payloads = {
            row.course_id: {
                "data": {"course_id": row.course_id, "participants": row.participants or []},
                "meta": {"status": row.status, "source": row.source or "persistent-cache"},
            }
            for row in cached_rows
            if row.status in {"ok", "no_participants"}
        }
    finally:
        db.close()
    remote_ids = [course_id for course_id in selected_ids if course_id not in cached_payloads]

    concurrency = max(1, min(int(settings.history_course_fetch_concurrency), 16))
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(course_id: str) -> tuple[str, dict | None, Exception | None]:
        try:
            async with semaphore:
                payload = await detail_method(course_id)
            return course_id, payload if isinstance(payload, dict) else {}, None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return course_id, None, exc

    # Fetch concurrently, but keep checking the client connection. If the user
    # leaves the race/Selections page, cancel outstanding remote requests rather
    # than continuing a hidden background analysis.
    tasks = {asyncio.create_task(fetch_one(course_id)) for course_id in remote_ids}
    results: list[tuple[str, dict | None, Exception | None]] = [
        (course_id, payload, None) for course_id, payload in cached_payloads.items()
    ]
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                results.append(await task)
            if request is not None and await _client_disconnected(request):
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                raise asyncio.CancelledError()
    except BaseException:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        raise

    async with write_lock:
        db = SessionLocal()
        try:
            target_ids = [history_id for course_id in selected_ids for history_id in grouped[course_id]]
            histories = db.scalars(
                select(HorseHistory)
                .where(HorseHistory.id.in_(target_ids))
                .options(selectinload(HorseHistory.runner))
            ).all()
            by_id = {history.id: history for history in histories}

            for course_id, payload, exc in results:
                if exc is not None:
                    for history_id in grouped[course_id]:
                        history = by_id.get(history_id)
                        if history is None:
                            continue
                        raw = history.raw if isinstance(history.raw, dict) else {}
                        attempts = int(raw.get("geny_course_lookup_attempts") or 0) + 1
                        history.raw = {
                            **raw,
                            "geny_course_lookup_status": "unavailable",
                            "geny_course_lookup_attempts": attempts,
                            "geny_course_lookup_warning": str(exc),
                            "geny_course_checked_at": datetime.now().isoformat(),
                        }
                    continue

                payload = payload or {}
                participants = payload.get("data", {}).get("participants", [])
                if not isinstance(participants, list):
                    participants = []
                meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
                source_status = str(meta.get("status") or "")
                source_name = str(meta.get("source") or "").strip() or None
                if source_name != "persistent-cache" and source_status in {"ok", "no_participants"}:
                    cache_status = "no_participants" if (not participants or source_status == "no_participants") else "ok"
                    cached = db.get(HistoricalRaceCache, course_id)
                    if cached is None:
                        cached = HistoricalRaceCache(course_id=course_id)
                        db.add(cached)
                    cached.status = cache_status
                    cached.participants = sanitize_objective_payload(participants)
                    cached.source = source_name
                    cached.warning = None
                    cached.checked_at = datetime.now()

                for history_id in grouped[course_id]:
                    history = by_id.get(history_id)
                    if history is None:
                        continue
                    raw = history.raw if isinstance(history.raw, dict) else {}
                    attempts = int(raw.get("geny_course_lookup_attempts") or 0) + 1
                    own_id = str(raw.get("geny_horse_id") or "").strip() or None
                    own_name = history.runner.horse_name
                    if own_id:
                        own = next(
                            (
                                item for item in participants
                                if isinstance(item, dict)
                                and str(item.get("geny_horse_id") or "").strip() == own_id
                            ),
                            None,
                        )
                    else:
                        own = next(
                            (
                                item for item in participants
                                if isinstance(item, dict)
                                and normalized_horse_name(str(item.get("horse_name") or ""))
                                == normalized_horse_name(own_name)
                            ),
                            None,
                        )

                    if not participants or source_status == "no_participants":
                        lookup_status = "no_participants"
                    elif own is None:
                        lookup_status = "identity_mismatch"
                    else:
                        lookup_status = "ok"
                        history.opponents = _merge_objective_opponents(
                            history.opponents or [], participants, own_name, own_id
                        )
                        if history.position is None and not history.disqualified:
                            own_position = to_int(own.get("position"))
                            if own_position and own_position > 0:
                                history.position = own_position
                        history.disqualified = bool(history.disqualified or own.get("disqualified"))
                        if own.get("result_status") and not raw.get("result_status"):
                            raw = {**raw, "result_status": own.get("result_status")}

                    history.raw = {
                        **raw,
                        "geny_course_lookup_status": lookup_status,
                        "geny_course_lookup_attempts": attempts,
                        "geny_course_participants": len(participants),
                        "geny_course_checked_at": datetime.now().isoformat(),
                        "geny_course_lookup_warning": None,
                    }
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # Do not re-load all 633 careers and regenerate every race after every
    # 120-course batch. That O(day × batches) work was a major bottleneck.
    # history-status reads HorseHistory.raw directly, so progress still updates
    # immediately. Finalise runners/snapshots once, after the last batch.
    if pending_after_batch:
        return True

    async with write_lock:
        db = SessionLocal()
        try:
            if race_id is not None:
                runner_ids = db.scalars(
                    select(Runner.id).where(Runner.race_id == race_id)
                ).all()
                race_ids = [race_id]
            else:
                runner_ids = db.scalars(
                    select(Runner.id).join(Race).join(Meeting).where(Meeting.race_date == day)
                ).all()
                race_ids = db.scalars(
                    select(Race.id).join(Meeting).where(Meeting.race_date == day)
                ).all()
        finally:
            db.close()

        for runner_id in runner_ids:
            db = SessionLocal()
            try:
                runner = db.scalar(
                    select(Runner).where(Runner.id == runner_id).options(selectinload(Runner.history))
                )
                if runner is None:
                    continue
                geny_rows = [
                    row for row in runner.history
                    if isinstance(row.raw, dict) and str(row.raw.get("geny_course_id") or "").isdigit()
                ]
                linked = sum(1 for row in geny_rows if (row.raw or {}).get("geny_course_lookup_status") == "ok")
                terminal = sum(
                    1 for row in geny_rows
                    if (row.raw or {}).get("geny_course_lookup_status") in {"no_participants", "identity_mismatch"}
                )
                pending = max(0, len(geny_rows) - linked - terminal)
                opponent_rows = sum(1 for row in runner.history if row.opponents)
                raw = runner.raw if isinstance(runner.raw, dict) else {}
                updated = {
                    **raw,
                    "geny_course_rows_total": len(geny_rows),
                    "geny_course_rows_linked": linked,
                    "geny_course_rows_pending": pending,
                    "opponent_network_rows": opponent_rows,
                    "opponent_network_status": (
                        "loading" if pending
                        else "complete" if geny_rows and linked == len(geny_rows)
                        else "partial" if opponent_rows
                        else "insufficient"
                    ),
                }
                if pending == 0:
                    updated["opponent_enrichment_version"] = OPPONENT_ENRICHMENT_VERSION
                else:
                    updated.pop("opponent_enrichment_version", None)
                runner.raw = updated
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        for race_id in race_ids:
            db = SessionLocal()
            try:
                race = db.scalar(
                    select(Race)
                    .where(Race.id == race_id)
                    .options(
                        selectinload(Race.meeting),
                        selectinload(Race.runners).selectinload(Runner.history),
                        selectinload(Race.snapshots),
                        selectinload(Race.result),
                    )
                )
                if race is not None and race.result is None:
                    generate_analysis(db, race)
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
    return False


async def _enrich_day_histories(
    day: date,
    write_lock: asyncio.Lock,
    provider: object | None = None,
) -> None:
    """Fetch slow horse histories without blocking programme/result reads.

    Every horse is committed as soon as its profile has been checked.  Exact
    historical-race linking is intentionally orchestrated by the wrapper task
    instead of being chained behind this sweep.  That keeps the opponent
    network moving even when a handful of horse-profile lookups are slow.
    """
    provider = provider or provider_factory()
    importer = ImportService(provider)
    db = SessionLocal()
    try:
        races = db.scalars(
            select(Race)
            .join(Meeting)
            .where(Meeting.race_date == day)
            .options(selectinload(Race.runners))
        ).all()
        race_jobs = [
            (race.id, race.code, race.scheduled_at)
            for race in races
            if any(
                (runner.raw or {}).get("pmu_opponent_enrichment_version") != PMU_OPPONENT_ENRICHMENT_VERSION
                for runner in race.runners
                if isinstance(runner.raw, dict)
            )
        ]
        rows = db.scalars(
            select(Runner)
            .join(Race)
            .join(Meeting)
            .where(Meeting.race_date == day)
            .options(selectinload(Runner.race))
        ).all()
        jobs = []
        for runner in rows:
            raw = runner.raw if isinstance(runner.raw, dict) else {}
            status = str(raw.get("history_status") or "pending")
            already_checked = raw.get("history_enrichment_version") == HISTORY_ENRICHMENT_VERSION
            transient = status in {"pending", "loading", "unavailable"}
            if not already_checked or transient:
                jobs.append((
                    runner.id,
                    runner.race_id,
                    runner.horse_external_id,
                    runner.horse_name,
                    runner.race.discipline,
                    runner.race.scheduled_at,
                ))
    finally:
        db.close()

    now = datetime.now()
    race_jobs.sort(
        key=lambda item: (
            0 if item[2] >= now else 1,
            item[2].timestamp() if item[2] >= now else -item[2].timestamp(),
        )
    )
    jobs.sort(
        key=lambda item: (
            0 if item[5] >= now else 1,
            item[5].timestamp() if item[5] >= now else -item[5].timestamp(),
        )
    )

    # PMU exposes one factual detailed-performance payload per race.  Reading it
    # once is enough to attach the visible past opponents to every runner and is
    # therefore much cheaper than requesting those rivals one by one.
    detail_method = getattr(provider, "get_detailed_performances", None)
    if callable(detail_method):
        for race_id, race_code, _scheduled_at in race_jobs:
            try:
                detail_payload = await detail_method(day, race_code)
                detail_rows = (
                    detail_payload.get("data", {}).get("runners", [])
                    if isinstance(detail_payload, dict) else []
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print("opponent network warning", day, race_code, exc)
                continue

            async with write_lock:
                db = SessionLocal()
                try:
                    race = db.scalar(
                        select(Race)
                        .where(Race.id == race_id)
                        .options(
                            selectinload(Race.runners).selectinload(Runner.history),
                            selectinload(Race.meeting),
                            selectinload(Race.snapshots),
                            selectinload(Race.result),
                        )
                    )
                    if race is None:
                        continue
                    by_number = {runner.number: runner for runner in race.runners}
                    for detail in detail_rows if isinstance(detail_rows, list) else []:
                        if not isinstance(detail, dict):
                            continue
                        runner = by_number.get(to_int(detail.get("number")))
                        if runner is None:
                            continue
                        detail_name = normalized_horse_name(str(detail.get("horse_name") or ""))
                        if detail_name and detail_name != normalized_horse_name(runner.horse_name):
                            continue
                        total = importer._replace_history(
                            db,
                            runner,
                            {"data": {"historique": detail.get("historique") or []}},
                        )
                        linked_rows = sum(1 for row in runner.history if row.opponents)
                        runner.raw = {
                            **(runner.raw or {}),
                            "history_source": _source_label(
                                (runner.raw or {}).get("history_source"),
                                "PMU performances détaillées" if total else None,
                            ),
                            "history_status": "ok" if total else (runner.raw or {}).get("history_status", "pending"),
                            "history_rows": total,
                            "opponent_network_status": "partial" if linked_rows else "insufficient",
                            "opponent_network_rows": linked_rows,
                            "pmu_opponent_enrichment_version": PMU_OPPONENT_ENRICHMENT_VERSION,
                        }
                    # Mark runners absent from the payload as checked too.  A
                    # debutant must stay visibly unranked instead of causing an
                    # endless loop of identical requests.
                    for runner in race.runners:
                        if (runner.raw or {}).get("pmu_opponent_enrichment_version") != PMU_OPPONENT_ENRICHMENT_VERSION:
                            runner.raw = {
                                **(runner.raw or {}),
                                "opponent_network_status": "insufficient",
                                "opponent_network_rows": 0,
                                "pmu_opponent_enrichment_version": PMU_OPPONENT_ENRICHMENT_VERSION,
                            }
                    db.commit()
                    if race.result is None:
                        generate_analysis(db, race)
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()

    for runner_id, race_id, horse_id, horse_name, discipline, _scheduled_at in jobs:
        # Persist a checkpoint before the network request. If a free cloud
        # instance sleeps here, the next startup sees "loading" and resumes.
        async with write_lock:
            db = SessionLocal()
            try:
                runner = db.get(Runner, runner_id)
                if runner is not None:
                    raw = runner.raw if isinstance(runner.raw, dict) else {}
                    runner.raw = {
                        **raw,
                        "history_status": "loading",
                        "history_attempts": int(raw.get("history_attempts") or 0) + 1,
                        "history_started_at": datetime.now().isoformat(),
                    }
                    db.commit()
            finally:
                db.close()

        try:
            payload = await provider.get_horse_history(
                horse_id or horse_name,
                discipline,
                horse_name=horse_name,
                race_date=day,
            )
            payload = payload if isinstance(payload, dict) else {}
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # One blocked or unavailable public profile must not cancel the
            # other horses' enrichment.
            print("history warning", day, horse_name, exc)
            async with write_lock:
                db = SessionLocal()
                try:
                    runner = db.scalar(
                        select(Runner).where(Runner.id == runner_id).options(selectinload(Runner.history))
                    )
                    if runner is not None:
                        has_history = bool(runner.history)
                        runner.raw = {
                            **(runner.raw or {}),
                            # Keep persisted factual rows usable without
                            # pretending that this refresh completed.
                            "history_status": "partial" if has_history else "unavailable",
                            "history_warning": str(exc),
                            "history_last_error": str(exc),
                            "history_rows": len(runner.history),
                            "history_checked_at": datetime.now().isoformat(),
                            "history_enrichment_version": HISTORY_ENRICHMENT_VERSION,
                        }
                        db.commit()
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()
            continue

        imported = 0
        async with write_lock:
            db = SessionLocal()
            try:
                runner = db.scalar(
                    select(Runner)
                    .where(Runner.id == runner_id)
                    .options(selectinload(Runner.history))
                )
                if runner is not None:
                    imported = importer._replace_history(db, runner, payload)
                    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
                    runner.raw = {
                        **(runner.raw or {}),
                        "history_source": _source_label((runner.raw or {}).get("history_source"), meta.get("source")),
                        "history_status": "ok" if imported else (meta.get("status") or "history_incomplete"),
                        "history_rows": imported,
                        "history_checked_at": datetime.now().isoformat(),
                        "history_last_error": None,
                        "history_enrichment_version": HISTORY_ENRICHMENT_VERSION,
                    }
                    db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        # Release the full provider payload before loading the complete field
        # for scoring. Persisted rows are now the source of truth.
        payload = None
        if imported:
            async with write_lock:
                db = SessionLocal()
                try:
                    race = db.scalar(
                        select(Race)
                        .where(Race.id == race_id)
                        .options(
                            selectinload(Race.runners).selectinload(Runner.history),
                            selectinload(Race.meeting),
                            selectinload(Race.snapshots),
                            selectinload(Race.result),
                        )
                    )
                    if race is not None and race.result is None:
                        generate_analysis(db, race)
                except Exception:
                    db.rollback()
                    raise
                finally:
                    db.close()

    return None


async def _client_disconnected(request: Request | None) -> bool:
    if request is None:
        return False
    try:
        return bool(await request.is_disconnected())
    except Exception:
        return False


async def _close_provider(provider: object) -> None:
    closer = getattr(provider, "aclose", None)
    if callable(closer):
        try:
            await closer()
        except Exception:
            pass


async def _enrich_race_histories_on_demand(
    race_id: int,
    write_lock: asyncio.Lock,
    provider: object,
    request: Request | None = None,
) -> date:
    """Prepare complete factual history only for the race the user opened.

    Programme reads stay light.  A clicked race refreshes its own runners,
    persists every published career row, then links exact historical fields for
    those runners only.  Persisted facts are reused on later opens; analysis is
    recalculated without re-downloading data that is already complete.
    """
    importer = ImportService(provider)
    db = SessionLocal()
    try:
        race = db.scalar(
            select(Race)
            .where(Race.id == race_id)
            .options(selectinload(Race.meeting), selectinload(Race.runners))
        )
        if race is None:
            raise HTTPException(404, "Course introuvable")
        day = race.meeting.race_date
        race_code = race.code
        discipline = race.discipline
        runner_meta = [
            (
                runner.id,
                runner.horse_external_id,
                runner.horse_name,
                runner.raw if isinstance(runner.raw, dict) else {},
            )
            for runner in race.runners
            if not runner.scratched
        ]
    finally:
        db.close()

    if await _client_disconnected(request):
        raise asyncio.CancelledError()

    # One PMU detailed-performance call can already attach factual historical
    # rivals to several runners.  Do it only when this race has not been checked
    # with the current enrichment version.
    needs_pmu_detail = any(
        raw.get("pmu_opponent_enrichment_version") != PMU_OPPONENT_ENRICHMENT_VERSION
        for _runner_id, _horse_id, _horse_name, raw in runner_meta
    )
    detail_method = getattr(provider, "get_detailed_performances", None)
    if needs_pmu_detail and callable(detail_method):
        try:
            detail_payload = await detail_method(day, race_code)
            detail_rows = (
                detail_payload.get("data", {}).get("runners", [])
                if isinstance(detail_payload, dict) else []
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("opponent network warning", day, race_code, exc)
            detail_rows = []

        if await _client_disconnected(request):
            raise asyncio.CancelledError()

        async with write_lock:
            db = SessionLocal()
            try:
                race = db.scalar(
                    select(Race)
                    .where(Race.id == race_id)
                    .options(selectinload(Race.runners).selectinload(Runner.history))
                )
                if race is not None:
                    by_number = {runner.number: runner for runner in race.runners}
                    for detail in detail_rows if isinstance(detail_rows, list) else []:
                        if not isinstance(detail, dict):
                            continue
                        runner = by_number.get(to_int(detail.get("number")))
                        if runner is None:
                            continue
                        detail_name = normalized_horse_name(str(detail.get("horse_name") or ""))
                        if detail_name and detail_name != normalized_horse_name(runner.horse_name):
                            continue
                        total = importer._replace_history(
                            db,
                            runner,
                            {"data": {"historique": detail.get("historique") or []}},
                        )
                        linked_rows = sum(1 for row in runner.history if row.opponents)
                        runner.raw = {
                            **(runner.raw or {}),
                            "history_source": _source_label(
                                (runner.raw or {}).get("history_source"),
                                "PMU performances détaillées" if total else None,
                            ),
                            "history_status": "ok" if total else (runner.raw or {}).get("history_status", "pending"),
                            "history_rows": total,
                            "opponent_network_status": "partial" if linked_rows else "insufficient",
                            "opponent_network_rows": linked_rows,
                            "pmu_opponent_enrichment_version": PMU_OPPONENT_ENRICHMENT_VERSION,
                        }
                    for runner in race.runners:
                        if (runner.raw or {}).get("pmu_opponent_enrichment_version") != PMU_OPPONENT_ENRICHMENT_VERSION:
                            runner.raw = {
                                **(runner.raw or {}),
                                "opponent_network_status": (runner.raw or {}).get("opponent_network_status", "insufficient"),
                                "opponent_network_rows": int((runner.raw or {}).get("opponent_network_rows") or 0),
                                "pmu_opponent_enrichment_version": PMU_OPPONENT_ENRICHMENT_VERSION,
                            }
                    db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    # Re-read runner metadata because the PMU detailed payload may already have
    # populated useful history rows.
    db = SessionLocal()
    try:
        race = db.scalar(
            select(Race)
            .where(Race.id == race_id)
            .options(selectinload(Race.runners))
        )
        if race is None:
            raise HTTPException(404, "Course introuvable")
        jobs: list[tuple[int, str | None, str, str | None]] = []
        for runner in race.runners:
            if runner.scratched:
                continue
            raw = runner.raw if isinstance(runner.raw, dict) else {}
            status = str(raw.get("history_status") or "pending")
            already_checked = raw.get("history_enrichment_version") == HISTORY_ENRICHMENT_VERSION
            transient = status in {"pending", "loading", "unavailable"}
            if not already_checked or transient:
                jobs.append((runner.id, runner.horse_external_id, runner.horse_name, discipline))
    finally:
        db.close()

    if jobs:
        async with write_lock:
            db = SessionLocal()
            try:
                ids = [item[0] for item in jobs]
                runners = db.scalars(select(Runner).where(Runner.id.in_(ids))).all()
                by_id = {runner.id: runner for runner in runners}
                for runner_id, _horse_id, _horse_name, _discipline in jobs:
                    runner = by_id.get(runner_id)
                    if runner is None:
                        continue
                    raw = runner.raw if isinstance(runner.raw, dict) else {}
                    runner.raw = {
                        **raw,
                        "history_status": "loading",
                        "history_attempts": int(raw.get("history_attempts") or 0) + 1,
                        "history_started_at": datetime.now().isoformat(),
                    }
                db.commit()
            finally:
                db.close()

        concurrency = max(1, min(int(settings.history_profile_fetch_concurrency), 8))
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_profile(job: tuple[int, str | None, str, str | None]):
            runner_id, horse_id, horse_name, runner_discipline = job
            if await _client_disconnected(request):
                raise asyncio.CancelledError()
            try:
                async with semaphore:
                    payload = await provider.get_horse_history(
                        horse_id or horse_name,
                        runner_discipline,
                        horse_name=horse_name,
                        race_date=day,
                    )
                return runner_id, payload if isinstance(payload, dict) else {}, None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return runner_id, None, exc

        results = await asyncio.gather(*(fetch_profile(job) for job in jobs))

        if await _client_disconnected(request):
            raise asyncio.CancelledError()

        async with write_lock:
            db = SessionLocal()
            try:
                ids = [item[0] for item in jobs]
                runners = db.scalars(
                    select(Runner).where(Runner.id.in_(ids)).options(selectinload(Runner.history))
                ).all()
                by_id = {runner.id: runner for runner in runners}
                for runner_id, payload, exc in results:
                    runner = by_id.get(runner_id)
                    if runner is None:
                        continue
                    if exc is not None:
                        has_history = bool(runner.history)
                        runner.raw = {
                            **(runner.raw or {}),
                            "history_status": "partial" if has_history else "unavailable",
                            "history_warning": str(exc),
                            "history_last_error": str(exc),
                            "history_rows": len(runner.history),
                            "history_checked_at": datetime.now().isoformat(),
                            "history_enrichment_version": HISTORY_ENRICHMENT_VERSION,
                        }
                        continue
                    payload = payload or {}
                    imported = importer._replace_history(db, runner, payload)
                    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
                    runner.raw = {
                        **(runner.raw or {}),
                        "history_source": _source_label((runner.raw or {}).get("history_source"), meta.get("source")),
                        "history_status": "ok" if imported else (meta.get("status") or "history_incomplete"),
                        "history_rows": imported,
                        "history_checked_at": datetime.now().isoformat(),
                        "history_last_error": None,
                        "history_enrichment_version": HISTORY_ENRICHMENT_VERSION,
                    }
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

    # Link exact historical fields for this race only.  Each pass is bounded in
    # RAM; persisted linked courses are skipped on later opens.
    while True:
        if await _client_disconnected(request):
            raise asyncio.CancelledError()
        remaining = bool(
            await _enrich_geny_course_details(
                day,
                write_lock,
                provider,
                race_id=race_id,
                request=request,
            )
        )
        if not remaining:
            break
        await asyncio.sleep(0)

    return day


async def _prepare_race_analysis(
    race_id: int,
    write_lock: asyncio.Lock,
    provider: object,
    request: Request | None = None,
) -> AnalysisOut:
    await _enrich_race_histories_on_demand(race_id, write_lock, provider, request)
    if await _client_disconnected(request):
        raise asyncio.CancelledError()
    async with write_lock:
        db = SessionLocal()
        try:
            race = db.scalar(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.meeting),
                    selectinload(Race.runners).selectinload(Runner.history),
                    selectinload(Race.snapshots),
                    selectinload(Race.result),
                )
            )
            if race is None:
                raise HTTPException(404, "Course introuvable")
            current = [s for s in race.snapshots if s.methodology_version == settings.methodology_version]
            locked_current = max((s for s in current if s.locked), key=lambda x: x.generated_at, default=None)
            if locked_current is not None:
                snap = locked_current
            elif race.result is not None:
                latest = max(current, key=lambda x: x.generated_at) if current else None
                snap = latest or generate_analysis(db, race)
            else:
                snap = generate_analysis(db, race)
            scores = db.scalars(
                select(RunnerScore)
                .where(RunnerScore.snapshot_id == snap.id)
                .options(selectinload(RunnerScore.runner))
            ).all()
            return AnalysisOut(
                snapshot_id=snap.id,
                race_id=race.id,
                generated_at=snap.generated_at,
                methodology_version=snap.methodology_version,
                locked=snap.locked,
                confirmation=CONFIRMATION,
                summary=snap.summary,
                result=race.result,
                scores=[
                    ScoreOut(
                        number=score.runner.number,
                        horse_name=score.runner.horse_name,
                        performance=score.performance,
                        placed=score.placed,
                        hidden_potential=score.hidden_potential,
                        robustness=score.robustness,
                        uncertainty=score.uncertainty,
                        line_strength=score.line_strength,
                        reasons=score.reasons,
                        breakdown=score.breakdown,
                    )
                    for score in sorted(scores, key=lambda item: item.performance, reverse=True)
                ],
            )
        finally:
            db.close()


async def _enrich_day_histories_safe(day: date, write_lock: asyncio.Lock) -> None:
    try:
        # Reuse one provider/client for the whole background run so its bounded
        # caches remain useful without growing unbounded.
        provider = provider_factory()

        # IMPORTANT: link one exact-race batch *before* the horse-profile sweep.
        # On a warm database there can already be thousands of verified Geny
        # course ids. Previously they all waited behind the last few slow or
        # unavailable horse profiles, which made the UI sit at 0/N for a long
        # time even though enough persisted data existed to start immediately.
        # Drain every exact historical course already persisted *before* the
        # remaining slow horse-profile lookups. On a warm production database
        # this makes the visible opponent-network counter advance immediately.
        while True:
            remaining = bool(await _enrich_geny_course_details(day, write_lock, provider))
            if not remaining:
                break
            await asyncio.sleep(0)

        # Refresh each horse profile once. This may discover additional old
        # course ids, which are drained in a second pass below.
        await _enrich_day_histories(day, write_lock, provider)

        while True:
            remaining = bool(await _enrich_geny_course_details(day, write_lock, provider))
            if not remaining:
                break
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print("history enrichment warning", day, exc)


async def maintenance_loop(
    stop: asyncio.Event,
    write_lock: asyncio.Lock,
    history_tasks: dict[date, asyncio.Task],
):
    """Keep programme/results fresh without precomputing the whole day.

    Heavy careers, historical-race linking and scoring now run only when the
    user opens one race or explicitly launches the Selections page.
    """
    provider = provider_factory()
    importer = ImportService(provider)
    try:
        while not stop.is_set():
            today = date.today()
            tomorrow = today + timedelta(days=1)
            next_wake = float(settings.refresh_seconds)
            async with write_lock:
                db = SessionLocal()
                try:
                    try:
                        await importer.import_results(db, today)
                    except Exception as exc:
                        db.rollback()
                        print("results warning", today, exc)
                    for target_day in (today, tomorrow):
                        try:
                            await importer.import_day(db, target_day, enrich_history=False)
                        except Exception as exc:
                            db.rollback()
                            print("refresh warning", target_day, exc)
                    try:
                        await importer.import_results(db, today)
                    except Exception as exc:
                        db.rollback()
                        print("results warning", today, exc)

                    # Evaluate already-locked snapshots when an official result
                    # arrives. Do not create new analyses here.
                    result_race_ids = db.scalars(
                        select(Race.id)
                        .join(Meeting)
                        .where(Meeting.race_date == today, Race.result.has())
                    ).all()
                    for race_id in result_race_ids:
                        race = db.scalar(
                            select(Race)
                            .where(Race.id == race_id)
                            .options(selectinload(Race.snapshots), selectinload(Race.result))
                        )
                        if race is not None and race.result is not None and race.result.status == "official":
                            evaluate_locked_snapshots(db, race)
                        db.expunge_all()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    print("maintenance cycle warning", exc)
                    engine.dispose()
                    next_wake = min(next_wake, 10.0)
                finally:
                    db.close()
            try:
                await asyncio.wait_for(stop.wait(), timeout=next_wake)
            except asyncio.TimeoutError:
                pass
    finally:
        await _close_provider(provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never make a rolling Render deploy depend on an immediately available
    # Supabase session-pool slot. The previous instance can temporarily own
    # every slot until Render marks this one healthy and retires it. SQLite
    # still creates its local schema synchronously; PostgreSQL schema creation
    # is best-effort because the production tables already exist.
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(engine)
    else:
        try:
            Base.metadata.create_all(engine)
        except Exception as exc:
            print("startup database warning", exc)
            engine.dispose()
    stop=asyncio.Event(); write_lock=asyncio.Lock(); history_tasks: dict[date, asyncio.Task] = {}
    task=asyncio.create_task(maintenance_loop(stop,write_lock,history_tasks))
    app.state.stop=stop; app.state.task=task; app.state.db_write_lock=write_lock; app.state.history_tasks=history_tasks
    yield
    stop.set(); task.cancel()
    try: await task
    except BaseException: pass
    for history_task in history_tasks.values():
        history_task.cancel()
    if history_tasks:
        await asyncio.gather(*history_tasks.values(), return_exceptions=True)
    # Release pooled PostgreSQL connections promptly when Render retires an
    # old instance during a rolling deploy.
    engine.dispose()


app=FastAPI(title=settings.app_name,version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_list,allow_credentials=False,allow_methods=["*"],allow_headers=["*"])


@app.get("/health")
def health():
    return {
        "ok":True,
        "app":settings.app_name,
        "provider":settings.provider,
        "methodology":settings.methodology_version,
        "independence_firewall":True,
        "official_histories":{
            "letrot":"public_read_only" if settings.official_history_enabled else "disabled",
            "france_galop":"official_login_required" if settings.official_history_enabled else "disabled",
            "geny":"public_complete_career_and_race_fields" if settings.official_history_enabled and settings.geny_history_enabled else "disabled",
        },
    }


@app.post("/api/refresh")
async def refresh(request: Request, day: date = Query(default_factory=date.today)):
    """Refresh only the light official card/results.

    Complete careers and the opponent network are intentionally *not* loaded
    here. They start only from an explicit race/day analysis action.
    """
    provider = provider_factory()
    importer = ImportService(provider)
    try:
        async with request.app.state.db_write_lock:
            db = SessionLocal()
            try:
                if day <= date.today():
                    try:
                        await importer.import_results(db, day)
                    except Exception as exc:
                        db.rollback()
                        print("results warning", day, exc)
                try:
                    meetings = await importer.import_day(db, day, enrich_history=False)
                except Exception as exc:
                    db.rollback()
                    raise HTTPException(
                        status_code=502,
                        detail=f"Source de courses indisponible pour {day.isoformat()} : {exc}",
                    ) from exc
                if day <= date.today():
                    try:
                        await importer.import_results(db, day)
                    except Exception as exc:
                        db.rollback()
                        print("results warning", day, exc)
                return {"ok": True, "date": day, "meetings": len(meetings), "mode": "on_demand"}
            finally:
                db.close()
    finally:
        await _close_provider(provider)


@app.get("/api/program/{day}",response_model=list[MeetingOut])
def program(day: date, db: Session=Depends(get_db)):
    rows=db.scalars(select(Meeting).where(Meeting.race_date==day).options(
        selectinload(Meeting.races).selectinload(Race.runners),
        selectinload(Meeting.races).selectinload(Race.result),
    ).order_by(Meeting.code)).all()
    return rows


@app.get("/api/tomorrow",response_model=list[MeetingOut])
def tomorrow(db: Session=Depends(get_db)):
    day=date.today()+timedelta(days=1)
    return program(day,db)


@app.get("/api/day/{day}/selections")
def day_selections(day: date, db: Session=Depends(get_db)):
    meetings=db.scalars(
        select(Meeting).where(Meeting.race_date==day).options(
            selectinload(Meeting.races).selectinload(Race.snapshots),
        ).order_by(Meeting.code)
    ).all()
    meeting_rows=[]
    day_items=[]
    day_quality={"complete":0,"partial":0,"limited":0,"loading":0,"insufficient":0}
    day_eligible=0
    day_documented=0
    for meeting in meetings:
        items=[]
        meeting_quality={"complete":0,"partial":0,"limited":0,"loading":0,"insufficient":0}
        meeting_eligible=0
        meeting_documented=0
        for race in meeting.races:
            # A GET must stay read-only. Snapshots are produced by refresh or the
            # maintenance task under the shared SQLite write lock.
            current=[
                s for s in race.snapshots
                if s.methodology_version==settings.methodology_version and is_pre_race_snapshot(race, s)
            ]
            snap=max(current,key=lambda x:x.generated_at) if current else None
            if snap is None:
                continue
            score_rows=db.scalars(select(RunnerScore).where(RunnerScore.snapshot_id==snap.id).options(selectinload(RunnerScore.runner))).all()
            ordered=sorted(score_rows,key=lambda s:s.performance,reverse=True)
            race_documented=sum(
                1 for score in ordered
                if isinstance(score.breakdown,dict) and int(score.breakdown.get("history_rows") or 0)>0
            )
            race_total=len(ordered)
            race_coverage=round(race_documented/race_total*100) if race_total else 0
            race_ready=race_coverage>=settings.selection_min_field_coverage_percent
            meeting_documented+=race_documented
            day_documented+=race_documented
            eligible=[
                s for s in ordered
                if race_ready and isinstance(s.breakdown,dict) and s.breakdown.get("ranking_eligible") is True
            ]
            rank_by_id={s.id:rank for rank,s in enumerate(eligible,1)}
            for s in ordered:
                breakdown=s.breakdown if isinstance(s.breakdown,dict) else {}
                evidence_status=str(breakdown.get("evidence_status") or "insufficient")
                meeting_quality[evidence_status]=meeting_quality.get(evidence_status,0)+1
                day_quality[evidence_status]=day_quality.get(evidence_status,0)+1
                item={
                    "meeting_code":meeting.code,"track":meeting.track,"race_id":race.id,"race_code":race.code,"race_name":race.name,
                    "number":s.runner.number,"horse_name":s.runner.horse_name,"performance":s.performance,"placed":s.placed,
                    "hidden_potential":s.hidden_potential,"robustness":s.robustness,"uncertainty":s.uncertainty,"race_rank":rank_by_id.get(s.id,0),
                    "sample_size":breakdown.get("sample_size",0),"form":breakdown.get("form",50),
                    "consistency":breakdown.get("consistency",45),"progression":breakdown.get("progression",50),
                    "aptitude":breakdown.get("aptitude",50),"class_score":breakdown.get("class",50),
                    "dq_risk":breakdown.get("dq_risk",35),"history_rows":breakdown.get("history_rows",0),
                    "evidence_status":evidence_status,"ranking_eligible":bool(breakdown.get("ranking_eligible")) and race_ready,
                    "data_confidence":breakdown.get("data_confidence",0),
                    "race_history_coverage_percent":race_coverage,"race_history_ready":race_ready,
                }
                if item["ranking_eligible"]:
                    meeting_eligible += 1
                    day_eligible += 1
                items.append(item)
                day_items.append(item)
        if not items:
            continue
        meeting_rows.append({
            "meeting_code":meeting.code,"track":meeting.track,
            "best":choose(items,"horse"),"placed":choose(items,"placed"),"outsider":choose(items,"outsider"),
            "tocard":choose(items,"tocard"),"heart":choose(items,"heart"),
        })
        meeting_rows[-1]["ready"] = any(
            meeting_rows[-1].get(kind) is not None
            for kind in ("best", "placed", "outsider", "tocard", "heart")
        )
        meeting_total=sum(meeting_quality.values())
        meeting_ready=meeting_documented
        meeting_rows[-1]["data_quality"]={
            **meeting_quality,
            "total":meeting_total,
            "ready":meeting_ready,
            "ready_percent":round(meeting_ready/meeting_total*100) if meeting_total else 0,
            "ranking_eligible":meeting_eligible,
            "detailed_histories":meeting_documented,
            "minimum_field_coverage_percent":settings.selection_min_field_coverage_percent,
        }
    day_picks = {
        "horse":choose(day_items,"horse"),
        "placed":choose(day_items,"placed"),
        "outsider":choose(day_items,"outsider"),
        "tocard":choose(day_items,"tocard"),
        "heart":choose(day_items,"heart"),
    }
    day_total=sum(day_quality.values())
    day_ready=day_documented
    return {
        "date":day.isoformat(),"meetings":meeting_rows,
        "day":{
            **day_picks,
            "ready": any(value is not None for value in day_picks.values()),
            "data_quality":{
                **day_quality,
                "total":day_total,
                "ready":day_ready,
                "ready_percent":round(day_ready/day_total*100) if day_total else 0,
                "ranking_eligible":day_eligible,
                "detailed_histories":day_documented,
                "minimum_field_coverage_percent":settings.selection_min_field_coverage_percent,
            },
        },
        "definitions":{
            "horse":"Meilleur indice transversal après confrontation de la performance, des preuves, de la forme, de la classe, de l'aptitude, de la robustesse et de l'incertitude.",
            "placed":"Meilleur indice de sécurité après réajustement par la régularité, la robustesse, l'expérience et la confiance documentaire.",
            "outsider":"Profil analytique hors Top 3 de sa course, retenu pour son potentiel caché sans utiliser les cotes.",
            "tocard":"Profil très spéculatif à potentiel interne, avec preuves plus fragiles ou volatilité élevée, sans utiliser les cotes.",
            "heart":"Profil réunissant valeur, potentiel caché, robustesse et confiance documentaire selon la méthode interne.",
        }
    }


@app.get("/api/day/{day}/history-status")
def history_status(day: date, db: Session=Depends(get_db)):
    """Report persisted ingestion progress without treating music as history."""
    runner_rows = db.execute(
        select(Runner.id, Runner.raw)
        .join(Race)
        .join(Meeting)
        .where(Meeting.race_date == day)
    ).all()
    statuses: dict[str,int]={}
    sources: dict[str,int]={}
    history_counts: dict[int, int] = {runner_id: 0 for runner_id, _raw in runner_rows}
    detailed=selection_ready=attempts=0
    geny_course_rows=geny_course_linked=geny_course_pending=0

    # Only raw lookup metadata is needed here. Do not materialize HorseHistory
    # ORM rows (and their large opponents JSON) just to count ingestion status.
    history_result = db.execute(
        select(HorseHistory.runner_id, HorseHistory.raw)
        .join(Runner)
        .join(Race)
        .join(Meeting)
        .where(Meeting.race_date == day)
        .execution_options(yield_per=1000)
    )
    for runner_id, history_raw_value in history_result:
        history_counts[runner_id] = history_counts.get(runner_id, 0) + 1
        history_raw=history_raw_value if isinstance(history_raw_value,dict) else {}
        if str(history_raw.get("geny_course_id") or "").isdigit():
            geny_course_rows+=1
            lookup_status=str(history_raw.get("geny_course_lookup_status") or "")
            geny_course_linked+=int(lookup_status=="ok")
            terminal=(lookup_status in {"no_participants","identity_mismatch"})
            geny_course_pending+=int(lookup_status!="ok" and not terminal)

    for runner_id, runner_raw_value in runner_rows:
        raw=runner_raw_value if isinstance(runner_raw_value,dict) else {}
        status=str(raw.get("history_status") or "pending")
        statuses[status]=statuses.get(status,0)+1
        source=str(raw.get("history_source") or "non renseignée")
        sources[source]=sources.get(source,0)+1
        rows=history_counts.get(runner_id,0)
        detailed+=int(rows>0)
        selection_ready+=int(rows>=settings.selection_min_history_rows)
        attempts+=int(raw.get("history_attempts") or 0)
    total=len(runner_rows)
    return {
        "date":day.isoformat(),"total_horses":total,
        "horses_with_detailed_history":detailed,
        "horses_selection_ready":selection_ready,
        "detailed_coverage_percent":round(detailed/total*100) if total else 0,
        "selection_ready_percent":round(selection_ready/total*100) if total else 0,
        "minimum_history_rows":settings.selection_min_history_rows,
        "minimum_field_coverage_percent":settings.selection_min_field_coverage_percent,
        "historical_race_rows":geny_course_rows,
        "historical_race_rows_linked":geny_course_linked,
        "historical_race_rows_pending":geny_course_pending,
        "historical_race_link_percent":round(geny_course_linked/geny_course_rows*100) if geny_course_rows else 0,
        "statuses":statuses,"sources":sources,"attempts":attempts,
        "complete":bool(total) and detailed==total and geny_course_pending==0,
    }


@app.post("/api/races/{race_id}/analyze", response_model=AnalysisOut)
async def analyze_race_on_demand(request: Request, race_id: int):
    """Run the complete method only for the race explicitly opened by the user."""
    provider = provider_factory()
    try:
        return await _prepare_race_analysis(
            race_id,
            request.app.state.db_write_lock,
            provider,
            request,
        )
    except asyncio.CancelledError:
        # The client left the race page. No background analysis is kept alive.
        raise HTTPException(status_code=499, detail="Analyse annulée : page quittée")
    finally:
        await _close_provider(provider)


@app.post("/api/day/{day}/analyze-selections")
async def analyze_day_selections_on_demand(request: Request, day: date):
    """Analyse every race sequentially only after an explicit Selections action.

    Leaving the page aborts the client request; disconnect checkpoints stop the
    server loop before starting the next race. Persisted factual history remains
    available for later launches.
    """
    db = SessionLocal()
    try:
        race_ids = db.scalars(
            select(Race.id)
            .join(Meeting)
            .where(Meeting.race_date == day)
            .order_by(Race.scheduled_at, Race.id)
        ).all()
    finally:
        db.close()
    if not race_ids:
        raise HTTPException(404, "Aucune course chargée pour cette date")

    provider = provider_factory()
    try:
        for race_id in race_ids:
            if await _client_disconnected(request):
                raise asyncio.CancelledError()
            try:
                await _prepare_race_analysis(
                    race_id,
                    request.app.state.db_write_lock,
                    provider,
                    request,
                )
            except HTTPException as exc:
                # One unavailable race must not erase the rest of a full-day
                # selection run; hard 404s still indicate corrupted programme data.
                if exc.status_code == 404:
                    raise
                print("selection race warning", race_id, exc.detail)
            if await _client_disconnected(request):
                raise asyncio.CancelledError()

        db = SessionLocal()
        try:
            return day_selections(day, db)
        finally:
            db.close()
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Sélections annulées : page quittée")
    finally:
        await _close_provider(provider)


@app.get("/api/races/{race_id}/analysis", response_model=AnalysisOut)
async def analysis(request: Request, race_id: int, force: bool = False):
    # Backward-compatible route: older mobile bundles also receive the new
    # on-demand behavior instead of accidentally reintroducing day-wide work.
    provider = provider_factory()
    try:
        return await _prepare_race_analysis(
            race_id,
            request.app.state.db_write_lock,
            provider,
            request,
        )
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Analyse annulée : page quittée")
    finally:
        await _close_provider(provider)


@app.post("/api/races/{race_id}/lock")
async def lock(request:Request, race_id:int, db:Session=Depends(get_db)):
    async with request.app.state.db_write_lock:
        race=db.scalar(select(Race).where(Race.id==race_id).options(selectinload(Race.runners).selectinload(Runner.history),selectinload(Race.meeting),selectinload(Race.snapshots)))
        if not race: raise HTTPException(404,"Course introuvable")
        try:
            snap=lock_latest_snapshot(db,race)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok":True,"snapshot_id":snap.id,"locked_at":snap.locked_at,"message":"Analyse pré-course figée : elle ne sera pas réécrite après l'arrivée."}


@app.get("/api/stats")
def stats(db:Session=Depends(get_db)):
    evs=db.scalars(select(Evaluation)).all(); n=len(evs)
    if not n: return {"races_evaluees":0,"message":"Les statistiques apparaîtront après les premières arrivées avec snapshots verrouillés."}
    return {
        "races_evaluees":n,
        "choix_gagnant_pct":round(sum(e.winning_pick_hit for e in evs)/n*100,1),
        "choix_place_top3_pct":round(sum(e.placed_pick_hit for e in evs)/n*100,1),
        "gagnant_dans_top3_performance_pct":round(sum(e.winner_hit_top3 for e in evs)/n*100,1),
        "couverture_podium_moyenne_sur_3":round(sum(e.podium_coverage for e in evs)/n,2),
    }
