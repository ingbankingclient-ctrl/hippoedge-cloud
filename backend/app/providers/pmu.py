from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from .base import ProviderError, RacingProvider
from .official_history import OfficialHistoryClient


def _text(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("libelleCourt") or value.get("libelleLong") or value.get("libelle") or value.get("code")
    return value


def _root_payload(payload: dict[str, Any]) -> dict[str, Any]:
    root: Any = payload.get("programme") or payload.get("data") or payload
    if isinstance(root, dict) and isinstance(root.get("programme"), dict):
        root = root["programme"]
    return root if isinstance(root, dict) else {}


def _iso_time(day: date, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # PMU currently sends epoch milliseconds for heureDepart.
        return datetime.fromtimestamp(value / 1000).astimezone().isoformat()
    text = str(value)
    return text if "T" in text else f"{day.isoformat()}T{text}"


class PmuProvider(RacingProvider):
    """Read-only adapter for PMU's public TurfInfo feed.

    It intentionally maps objective race facts only. Odds, popularity and every
    editorial/prediction field are discarded before HippoEdge sees the payload.
    """

    name = "pmu"

    def __init__(
        self,
        base_url: str,
        letrot_base_url: str = "https://www.letrot.com",
        france_galop_base_url: str = "https://www.france-galop.com",
        geny_base_url: str = "https://www.geny.com",
        geny_history_enabled: bool = True,
        official_history_enabled: bool = True,
        history_request_interval_seconds: float = 0.35,
        history_max_rows: int = 50,
    ):
        self.base_url = base_url.rstrip("/")
        self.history_client = OfficialHistoryClient(
            letrot_base_url=letrot_base_url,
            france_galop_base_url=france_galop_base_url,
            geny_base_url=geny_base_url,
            geny_enabled=geny_history_enabled,
            enabled=official_history_enabled,
            request_interval_seconds=history_request_interval_seconds,
            max_rows=history_max_rows,
        )

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "HippoEdge/1.0 (personal read-only client)"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(f"{self.base_url}/{path.lstrip('/')}", params=params or {}, headers=headers)
        if response.status_code >= 400:
            raise ProviderError(f"PMU {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("Le flux PMU n'a pas renvoyé de JSON valide") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Format de réponse PMU inattendu")
        return payload

    @staticmethod
    def normalize_program(payload: dict[str, Any], day: date) -> dict[str, Any]:
        root = _root_payload(payload)
        meetings = []
        for meeting in root.get("reunions", []) or []:
            rnum = meeting.get("numOfficiel") or meeting.get("numReunion")
            rcode = f"R{rnum}" if rnum is not None else str(meeting.get("code") or "R?")
            hippodrome = meeting.get("hippodrome") or {}
            track = _text(hippodrome) or meeting.get("libelleCourt") or "Inconnu"
            races = []
            for race in meeting.get("courses", []) or []:
                cnum = race.get("numOrdre") or race.get("numCourse")
                code = f"{rcode}C{cnum}" if cnum is not None else str(race.get("code") or "")
                races.append({
                    "code_course": code,
                    "prix": race.get("libelle") or race.get("libelleCourt") or code,
                    "heure_depart": _iso_time(day, race.get("heureDepart") or race.get("heure")),
                    "discipline": _text(race.get("discipline")),
                    "distance": race.get("distance"),
                    "allocation": race.get("montantPrix") or race.get("montantTotalOffert"),
                    "terrain": _text(race.get("etatPiste")),
                    "surface": _text(race.get("typePiste")),
                    "categorie": _text(race.get("categorieParticularite")) or _text(race.get("categorieStatut")),
                    "depart": _text(race.get("typeDepart")) or _text(race.get("modeDepart")),
                    "source_ref": f"pmu:{day.isoformat()}:{code}",
                })
            meetings.append({
                "code": rcode,
                "hippodrome": track,
                "pays": _text(meeting.get("pays")),
                "courses": races,
            })
        return {"data": {"reunions": meetings}}

    @staticmethod
    def normalize_runners(payload: dict[str, Any]) -> dict[str, Any]:
        root = _root_payload(payload)
        raw = root.get("participants") or root.get("partants") or []
        runners = []
        for p in raw:
            driver = p.get("driver") or p.get("jockey") or {}
            trainer = p.get("entraineur") or {}
            gains = p.get("gainsParticipant") or {}
            status = str(p.get("statut") or "").upper()
            runners.append({
                "num": p.get("numPmu") or p.get("numero") or p.get("num"),
                "name": p.get("nom") or p.get("nomCheval"),
                "idcheval": p.get("idCheval") or p.get("idParticipant") or p.get("nom"),
                "age": p.get("age"),
                "sexe": _text(p.get("sexe")),
                "poids": p.get("handicapPoids") or p.get("poidsConditionMonte"),
                "corde": p.get("placeCorde"),
                "valeur": p.get("handicapValeur"),
                "gains": gains.get("gainsCarriere") if isinstance(gains, dict) else gains,
                "record": p.get("record") or p.get("recordAbsolu"),
                "ferrure": _text(p.get("deferre")) or _text(p.get("ferrure")),
                "equipement": _text(p.get("oeilleres")),
                "position_depart": p.get("placeCorde") or p.get("positionDepart"),
                "distance": p.get("handicapDistance") or p.get("distance"),
                "jockey_driver": _text(driver),
                "entraineur": _text(trainer),
                "musique": p.get("musique"),
                "np": status in {"NON_PARTANT", "NON PARTANT", "NP"},
            })
        return {"data": {"partants": runners}}

    async def get_program(self, day: date) -> dict[str, Any]:
        raw = await self._get(f"programme/{day.strftime('%d%m%Y')}", {"meteo": "true", "specialisation": "INTERNET"})
        return self.normalize_program(raw, day)

    async def get_race(self, day: date, code: str, track: str | None = None) -> dict[str, Any]:
        try:
            reunion, course = code.upper().split("C", 1)
            rnum = reunion.removeprefix("R")
        except ValueError as exc:
            raise ProviderError(f"Code course PMU invalide: {code}") from exc
        raw = await self._get(
            f"programme/{day.strftime('%d%m%Y')}/R{rnum}/C{course}/participants",
            {"specialisation": "INTERNET"},
        )
        return self.normalize_runners(raw)

    async def get_horse_history(
        self, horse_id: str, discipline: str | None = None, horse_name: str | None = None
    ) -> dict[str, Any]:
        # PMU supplies the runner identity; the governing body's official source
        # supplies objective historical performances when public access permits it.
        return await self.history_client.get_history(horse_name or horse_id, discipline, horse_id=horse_id)

    @staticmethod
    def normalize_results(payload: dict[str, Any]) -> dict[str, Any]:
        root = _root_payload(payload)
        results = []
        for meeting in root.get("reunions", []) or []:
            rnum = meeting.get("numOfficiel") or meeting.get("numReunion")
            if rnum is None:
                continue
            track = _text(meeting.get("hippodrome")) or ""
            for race in meeting.get("courses", []) or []:
                cnum = race.get("numOrdre") or race.get("numCourse")
                if cnum is None:
                    continue
                definitive = (
                    race.get("arriveeDefinitive")
                    or race.get("ordreArriveeDefinitive")
                    or race.get("arriveeOfficielle")
                )

                def as_entries(value: Any) -> list[Any]:
                    if isinstance(value, list):
                        return value
                    if isinstance(value, dict):
                        nested = (
                            value.get("ordre") or value.get("order") or value.get("arrivee")
                            or value.get("participants") or value.get("classement")
                        )
                        if isinstance(nested, list):
                            return nested
                        if any(k in value for k in ("numPmu", "numeroPmu", "numero", "num", "number")):
                            return [value]
                    return []

                definitive_order = as_entries(definitive)
                arrival = (
                    race.get("ordreArrivee") or race.get("arrivee") or race.get("resultat")
                    or definitive_order
                )
                if isinstance(arrival, dict):
                    arrival = (
                        arrival.get("ordre")
                        or arrival.get("order")
                        or arrival.get("arrivee")
                        or arrival.get("participants")
                        or arrival.get("classement")
                        or [arrival]
                    )
                arrival = as_entries(arrival)
                raw_status = str(
                    _text(race.get("statut"))
                    or _text(race.get("etatCourse"))
                    or _text(race.get("status"))
                    or ""
                ).upper()
                provisional = "PROVISOIRE" in raw_status or "PROVISION" in raw_status
                official = (
                    (bool(definitive) and not provisional)
                    or "DEFINIT" in raw_status
                    or "OFFICIEL" in raw_status
                )
                has_result_status = any(token in raw_status for token in ("ARRIV", "PROVISION", "OFFICIEL", "DEFINIT"))
                if arrival or has_result_status:
                    non_finishers = (
                        race.get("nonClassement") or race.get("nonClasses")
                        or race.get("nonFinishers") or race.get("non_finis") or []
                    )
                    results.append({
                        "code_course": f"R{rnum}C{cnum}",
                        "hippodrome": track,
                        "arrivee": arrival,
                        "non_finishers": non_finishers,
                        "result_status": "official" if official else "provisional",
                        "source_status": raw_status or None,
                    })
        return {"data": {"results": results}}

    async def get_results(self, day: date) -> dict[str, Any]:
        raw = await self._get(f"programme/{day.strftime('%d%m%Y')}", {"specialisation": "INTERNET"})
        return self.normalize_results(raw)
