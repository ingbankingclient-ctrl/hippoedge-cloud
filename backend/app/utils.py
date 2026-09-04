from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo


FORBIDDEN_MARKET_OR_OPINION_KEYS = {
    "cote", "cotes", "odds", "favori", "favorite", "popularite", "popularité",
    "note_ia", "note ia", "cote_bzh", "value_bet", "value-bet", "pronostic",
    "pronostics", "prediction", "predictions", "prediction_externe",
    "selection", "sélection", "selections", "sélections", "avis", "conseil", "advice", "tips", "tip",
    "elo_cheval", "classement_externe", "classement_editorial", "classement_presse", "classement_probable", "rank_prediction",
    "opposant", "outsider", "interdit", "rapport", "rapports", "quinte",
    "synthese_presse", "synthèse_presse", "presse", "rating_externe", "rating", "rpr",
    "topspeed", "editorial_rating", "editorial", "avis_geny", "note_fin_de_course",
    "probability", "probabilities", "probable_odds", "forecast", "recommendation",
    "pick", "valuebet", "bet", "bets",
}


def sanitize_objective_payload(value: Any) -> Any:
    """Recursively removes market, popularity and editorial/prediction fields.

    This is deliberately conservative. It is the hard firewall that preserves the
    user's independence requirement even when a provider response mixes raw facts
    with odds or editorial rankings. The generic key ``classement`` is retained
    because it can denote an official arrival; explicit external/editorial
    variants remain blocked.
    """
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            raw_key = str(k).strip().lower()
            folded = "".join(
                char for char in unicodedata.normalize("NFKD", raw_key)
                if not unicodedata.combining(char)
            )
            normalized = re.sub(r"[^a-z0-9]+", " ", folded).strip()
            compact = re.sub(r"[^a-z0-9]+", "", folded)
            forbidden = {
                "".join(
                    char for char in unicodedata.normalize("NFKD", str(item).lower())
                    if not unicodedata.combining(char)
                )
                for item in FORBIDDEN_MARKET_OR_OPINION_KEYS
            }
            if normalized in forbidden or compact in {
                re.sub(r"[^a-z0-9]+", "", str(item).lower())
                for item in forbidden
            }:
                continue
            # Prefix/substring variants are deliberately blocked as well. A
            # provider may call the same editorial field ``selection_8``,
            # ``predictionsExternes`` or ``favoriteRank``.
            if any(token in compact for token in (
                "pronostic", "prediction", "cote", "cotebzh", "odds", "rapport",
                "popularit", "favori", "valuebet", "editorial", "presse", "synthesepresse",
                "selection", "recommendation", "probability", "probable", "forecast", "tipster",
                "market", "opinion",
            )):
                continue
            if any(token in normalized for token in (
                "avis entraineur", "avis entraîneur", "avis geny", "trainer opinion",
                "rapport probable", "probable odds", "synthese presse", "synthèse presse",
                "note fin de course", "editorial rating", "market rank", "external score",
            )):
                continue
            out[k] = sanitize_objective_payload(v)
        return out
    if isinstance(value, list):
        return [sanitize_objective_payload(x) for x in value]
    return value


def parse_record_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if 50 <= v <= 150:
            return v
    s = str(value).strip().lower().replace('"', "").replace("’", "'")
    # 1'13"5 / 1:13.5 / 73.5
    m = re.search(r"(?:(\d+)\s*[':])?\s*(\d{1,2})(?:[\.,](\d))?", s)
    if not m:
        return None
    minutes = int(m.group(1) or 0)
    seconds = int(m.group(2))
    tenth = int(m.group(3) or 0)
    total = minutes * 60 + seconds + tenth / 10
    return total if 50 <= total <= 150 else None


def to_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            number = float(value)
            return number if math.isfinite(number) else None
        text = str(value).strip().replace("\u00a0", " ").replace("\u202f", " ")
        text = re.sub(r"\s+", "", text)
        # French feeds commonly use a comma as decimal separator and may add
        # a currency/unit suffix. Preserve the sign and the first numeric
        # token, while rejecting NaN/Infinity instead of leaking them into a
        # score or a database JSON document.
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
        if not match:
            return None
        number = float(match.group())
        return number if math.isfinite(number) else None
    except Exception:
        return None


def to_int(value: Any) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None


def clip(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    if not math.isfinite(float(v)):
        return (lo + hi) / 2
    return max(lo, min(hi, v))


def mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return sum(vals) / len(vals) if vals else None


def stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_iso_or_local(date_str: str, time_str: str | None) -> datetime:
    t = (time_str or "12:00").strip().replace("h", ":")
    # Providers may already have normalized the value to a complete ISO
    # timestamp. Do not prepend the date a second time.
    if "T" in t or re.match(r"^\d{4}-\d{2}-\d{2}\s", t):
        candidate = t.replace(" ", "T", 1)
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is not None:
            # Database timestamps are deliberately naive and interpreted in
            # the application's French racing timezone. Convert an explicit
            # provider offset before dropping tzinfo; otherwise a UTC ``Z``
            # timestamp could move the automatic lock by two hours.
            try:
                local = parsed.astimezone(ZoneInfo("Europe/Paris"))
            except Exception:
                # Windows installations may not ship the IANA tzdata bundle.
                # The host timezone is the safe fallback for a local PMU run;
                # importantly, the offset is still applied rather than
                # silently treating an explicit UTC value as local time.
                local = parsed.astimezone()
            return local.replace(tzinfo=None)
        return parsed
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return datetime.fromisoformat(f"{t}T12:00:00")
    if len(t) == 5 and ":" in t:
        return datetime.fromisoformat(f"{date_str}T{t}:00")
    if len(t) == 8:
        return datetime.fromisoformat(f"{date_str}T{t}")
    return datetime.fromisoformat(f"{date_str}T12:00:00")
