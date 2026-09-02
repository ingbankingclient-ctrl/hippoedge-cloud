from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from .base import ProviderError


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalized_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _first_number(value: str) -> int | None:
    match = re.search(r"\d+", value.replace("\u202f", " "))
    return int(match.group()) if match else None


def _distance_number(value: str) -> int | None:
    match = re.search(r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+", value)
    return int(re.sub(r"\s+", "", match.group())) if match else None


@dataclass
class _Cell:
    text_parts: list[str] = field(default_factory=list)
    class_parts: dict[str, list[str]] = field(default_factory=dict)
    links: list[tuple[str, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return _clean(" ".join(self.text_parts))

    def class_text(self, name: str) -> str:
        return _clean(" ".join(self.class_parts.get(name, [])))

    def link(self, pattern: re.Pattern[str]) -> tuple[str, str] | None:
        return next(((href, label) for href, label in self.links if pattern.search(href)), None)


@dataclass
class _Table:
    headings: list[str] = field(default_factory=list)
    rows: list[list[_Cell]] = field(default_factory=list)


class _TableHTMLParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[_Table] = []
        self.table: _Table | None = None
        self.row: list[_Cell] | None = None
        self.cell: _Cell | None = None
        self.cell_kind: str | None = None
        self.stack: list[tuple[str, set[str]]] = []
        self.anchor_href: str | None = None
        self.anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, classes))
        if tag == "br" and self.cell:
            self.cell.text_parts.append(" ")
        elif tag == "table":
            self.table = _Table()
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.table is not None:
            self.cell = _Cell()
            self.cell_kind = tag
        elif tag == "a" and self.cell is not None:
            self.anchor_href = attributes.get("href")
            self.anchor_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.cell is None or not data.strip():
            return
        self.cell.text_parts.append(data)
        for _, classes in self.stack:
            for class_name in classes:
                self.cell.class_parts.setdefault(class_name, []).append(data)
        if self.anchor_href is not None:
            self.anchor_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.cell is not None and self.anchor_href:
            self.cell.links.append((self.anchor_href, _clean(" ".join(self.anchor_parts))))
            self.anchor_href = None
            self.anchor_parts = []
        elif tag in {"td", "th"} and self.cell is not None and self.table is not None:
            if self.cell_kind == "th":
                self.table.headings.append(self.cell.text)
            elif self.row is not None:
                self.row.append(self.cell)
            self.cell = None
            self.cell_kind = None
        elif tag == "tr" and self.table is not None:
            if self.row:
                self.table.rows.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


class _LinkHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.links.append((self.href, _clean(" ".join(self.parts))))
            self.href = None
            self.parts = []


class LeTrotHistoryParser:
    """Parses objective fields from LeTROT's public horse pages.

    Columns containing trainer opinions and probable odds are deliberately never
    read. The returned structure is already compatible with HippoEdge's importer.
    """

    PROFILE_RE = re.compile(
        r"^(?:https?://(?:www\.)?letrot\.com)?/stats/chevaux/[^/]+/[^/]+/courses/?(?:[?#].*)?$",
        re.IGNORECASE,
    )

    @classmethod
    def find_profile_path(cls, html: str, horse_name: str) -> str | None:
        parser = _LinkHTMLParser()
        parser.feed(html)
        wanted = _normalized_name(horse_name)
        candidates: list[tuple[str, str]] = []
        for href, text in parser.links:
            if not cls.PROFILE_RE.match(href):
                continue
            label = _normalized_name(text)
            candidates.append((label, href))
        for label, href in candidates:
            if label == wanted:
                return href
        # A unique but differently named result is still unsafe: an exact
        # identity match is required before attaching a history.
        return None

    @staticmethod
    def _performance_table(html: str) -> _Table | None:
        parser = _TableHTMLParser()
        parser.feed(html)
        for table in parser.tables:
            headings = _clean(" ".join(table.headings)).lower()
            if "red. km" in headings and "distance" in headings and "hippodrome" in headings:
                return table
        return None

    @staticmethod
    def _rank_and_field(cell: _Cell) -> tuple[int | None, bool, int | None]:
        rank_text = (cell.class_text("text-lg") or cell.text).upper()
        field_size = _first_number(cell.class_text("cel-info"))
        disqualified = rank_text.startswith(("DA", "DM", "DI", "DQ"))
        rank = _first_number(rank_text)
        if disqualified or rank == 0:
            rank = None
        return rank, disqualified, field_size

    @staticmethod
    def _discipline(speciality: str) -> str:
        code = speciality.strip().upper()
        if code == "M":
            return "Trot monté"
        return "Trot attelé"

    @staticmethod
    def _class_name(category: str) -> str | None:
        code = category.strip().upper()
        if re.fullmatch(r"[A-H]", code):
            return f"Course {code}"
        return category or None

    @classmethod
    def parse_performances(cls, html: str, max_rows: int = 50) -> list[dict[str, Any]]:
        table = cls._performance_table(html)
        if table is None:
            return []
        rows: list[dict[str, Any]] = []
        for cells in table.rows:
            if len(cells) < 14:
                continue
            date_text = cells[0].text
            try:
                race_date = datetime.strptime(date_text, "%d/%m/%y").date().isoformat()
            except ValueError:
                continue

            rank, disqualified, field_size = cls._rank_and_field(cells[1])
            distance_text = cells[3].text
            distance = _first_number(distance_text)
            recoil = re.search(r"\+\s*(\d+)\s*m", distance_text, re.IGNORECASE)

            track_anchor = cells[7].link(re.compile(r"/hippodromes/"))
            race_anchor = cells[7].link(re.compile(r"/courses/"))
            track = track_anchor[1] if track_anchor else None
            race_name = race_anchor[1] if race_anchor else None
            race_code = race_anchor[0] if race_anchor else None

            start_bits: list[str] = []
            start_text = cells[8].text
            if start_text and start_text not in {"-", "--"}:
                start_bits.append(start_text)
            if recoil:
                start_bits.append(f"Recul {recoil.group(1)} m")

            # Indexes 6 and 15 are "Avis Entr." and "Rap. prob.". They are
            # intentionally absent here and therefore cannot reach the scoring.
            history = {
                "date": race_date,
                "hippodrome": track,
                "code_course": race_code,
                "nom_course": race_name,
                "discipline": cls._discipline(cells[11].text),
                "distance": distance,
                "position": rank,
                "disqualifie": disqualified,
                "reduction_km": cells[2].text or None,
                "classe": cls._class_name(cells[10].text),
                "depart": " · ".join(start_bits) or None,
                "corde": cells[9].text or None,
                "nb_partants": field_size,
                "source": "LeTROT",
            }
            rows.append({key: value for key, value in history.items() if value not in (None, "")})
            if len(rows) >= max_rows:
                break
        return rows


class GenyHistoryParser(HTMLParser):
    """Extracts objective career lines from a public Geny horse page.

    Geny pages also expose odds, editorial classifications and predictions.  The
    parser deliberately addresses only the visual columns that contain facts and
    never reads the odds/Quinte/editorial columns.
    """

    FIELD_CLASSES = {
        "w-[94px]": "hippodrome",
        "w-[49px]": "discipline",
        "w-[39px]": "distance",
        "w-[72px]": "terrain",
        "w-[36px]": "classe",
        "w-[112px]": "jockey",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str]]] = []
        self.current: dict[str, list[str]] | None = None
        self.rows: list[dict[str, Any]] = []
        self.in_h1 = False
        self.heading_parts: list[str] = []
        self.profile_name: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        self.stack.append((tag, classes))
        if tag == "h1":
            self.in_h1 = True
            self.heading_parts = []
        if tag == "nav" and attributes.get("role") == "navigation":
            self.current = {}

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.in_h1 and data.strip():
            self.heading_parts.append(data)
        if self.current is None or not data.strip():
            return
        class_chain = set().union(*(classes for _, classes in self.stack))
        key: str | None = None
        if "bg-green-700" in class_chain:
            key = "date"
        elif "bg-green-500" in class_chain:
            key = "rang"
        else:
            for class_name, field_name in self.FIELD_CLASSES.items():
                if class_name in class_chain:
                    key = field_name
                    break
        if key:
            self.current.setdefault(key, []).append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.in_h1:
            heading = _clean(" ".join(self.heading_parts))
            self.profile_name = re.sub(r"^\d+\s*[.]\s*", "", heading) or None
            self.in_h1 = False
        if tag == "nav" and self.current is not None:
            row = {key: _clean(" ".join(parts)) for key, parts in self.current.items()}
            if re.fullmatch(r"\d{2}/\d{2}/\d{2}", row.get("date", "")):
                self.rows.append(row)
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    @classmethod
    def parse(cls, html: str, horse_name: str, max_rows: int = 50) -> tuple[str | None, list[dict[str, Any]]]:
        parser = cls()
        parser.feed(html)
        if not parser.profile_name:
            return None, []
        if _normalized_name(parser.profile_name) != _normalized_name(horse_name):
            return parser.profile_name, []
        history: list[dict[str, Any]] = []
        for raw in parser.rows:
            try:
                race_date = datetime.strptime(raw["date"], "%d/%m/%y").date().isoformat()
            except (KeyError, ValueError):
                continue
            rank_text = raw.get("rang", "").upper()
            disqualified = rank_text.startswith(("DA", "DM", "DI", "DQ"))
            rank = _first_number(rank_text)
            if disqualified or rank == 0:
                rank = None
            row = {
                "date": race_date,
                "hippodrome": raw.get("hippodrome") or None,
                "discipline": raw.get("discipline") or None,
                "distance": _distance_number(raw.get("distance", "")),
                "terrain": raw.get("terrain") or None,
                "classe": raw.get("classe") or None,
                "position": rank,
                "disqualifie": disqualified,
                "jockey_driver": raw.get("jockey") or None,
                "source": "Geny",
            }
            history.append({key: value for key, value in row.items() if value not in (None, "")})
            if len(history) >= max_rows:
                break
        return parser.profile_name, history


def _merge_histories(primary: list[dict[str, Any]], complement: list[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    """Merge objective rows without losing provenance or creating duplicates."""

    rows: dict[tuple[str, str, int | None], dict[str, Any]] = {}
    for source_row in [*primary, *complement]:
        row = dict(source_row)
        key = (
            str(row.get("date") or ""),
            _normalized_name(str(row.get("hippodrome") or "")),
            row.get("distance"),
        )
        if key not in rows:
            rows[key] = row
            continue
        existing = rows[key]
        for field, value in row.items():
            if field == "source":
                sources = list(dict.fromkeys(str(existing.get("source", "")).split(" + ") + str(value).split(" + ")))
                existing["source"] = " + ".join(item for item in sources if item)
            elif "LeTROT" in str(existing.get("source", "")) and field in {
                "date", "hippodrome", "distance", "position", "disqualifie",
                "discipline", "classe", "depart", "corde", "nb_partants",
            }:
                # A complementary page may fill a missing terrain or jockey,
                # but it can never replace an official trot result (including a
                # deliberate DQ/no-rank marker) with its own interpretation.
                continue
            elif existing.get(field) in (None, "", []):
                existing[field] = value
    return sorted(rows.values(), key=lambda item: str(item.get("date") or ""), reverse=True)[:max_rows]


class OfficialHistoryClient:
    """Read-only enrichment from official governing-body sources.

    LeTROT is public and can be read without credentials. France Galop currently
    protects horse profiles with its official sign-in; that boundary is reported
    explicitly rather than bypassed or replaced with an unofficial provider.
    """

    def __init__(
        self,
        letrot_base_url: str = "https://www.letrot.com",
        france_galop_base_url: str = "https://www.france-galop.com",
        geny_base_url: str = "https://www.geny.com",
        geny_enabled: bool = True,
        enabled: bool = True,
        request_interval_seconds: float = 0.35,
        max_rows: int = 50,
    ):
        self.letrot_base_url = letrot_base_url.rstrip("/")
        self.france_galop_base_url = france_galop_base_url.rstrip("/")
        self.geny_base_url = geny_base_url.rstrip("/")
        self.geny_enabled = geny_enabled
        self.enabled = enabled
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self.max_rows = max(1, min(max_rows, 100))
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0

    @staticmethod
    def _is_trot(discipline: str | None) -> bool:
        return "trot" in (discipline or "").lower() or "attel" in (discipline or "").lower() or "mont" in (discipline or "").lower()

    async def _get_html(self, url: str) -> str:
        async with self._request_lock:
            remaining = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            headers = {
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "User-Agent": "HippoEdge/1.0 (usage personnel; lecture seule)",
            }
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
            self._last_request_at = time.monotonic()
        if response.status_code >= 400:
            raise ProviderError(f"Source historique {response.status_code}: {url}")
        return response.text

    async def _get_letrot(self, horse_name: str) -> dict[str, Any]:
        search_url = f"{self.letrot_base_url}/search?keyword={quote(horse_name)}&category=chevaux"
        search_html = await self._get_html(search_url)
        profile_path = LeTrotHistoryParser.find_profile_path(search_html, horse_name)
        if not profile_path:
            return {"data": {"historique": []}, "meta": {"source": "LeTROT", "status": "not_found"}}
        profile_url = urljoin(f"{self.letrot_base_url}/", profile_path)
        profile_html = await self._get_html(profile_url)
        history = LeTrotHistoryParser.parse_performances(profile_html, self.max_rows)
        status = "ok" if history else "no_performance_table"
        return {
            "data": {"historique": history},
            "meta": {"source": "LeTROT", "status": status, "profile_url": profile_url, "rows": len(history)},
        }

    async def _get_geny(self, horse_id: str | None, horse_name: str) -> dict[str, Any]:
        if not self.geny_enabled:
            return {"data": {"historique": []}, "meta": {"source": "Geny", "status": "disabled"}}
        if not horse_id or not str(horse_id).isdigit():
            return {"data": {"historique": []}, "meta": {"source": "Geny", "status": "missing_numeric_id"}}
        profile_url = f"{self.geny_base_url}/cheval/{horse_id}"
        try:
            profile_html = await self._get_html(profile_url)
        except ProviderError as exc:
            return {
                "data": {"historique": []},
                "meta": {"source": "Geny", "status": "unavailable", "message": str(exc)},
            }
        profile_name, history = GenyHistoryParser.parse(profile_html, horse_name, self.max_rows)
        if not profile_name:
            status = "identity_unverified"
        elif _normalized_name(profile_name) != _normalized_name(horse_name):
            status = "identity_mismatch"
        else:
            status = "ok" if history else "no_performance_rows"
        return {
            "data": {"historique": history},
            "meta": {
                "source": "Geny",
                "status": status,
                "profile_url": profile_url,
                "profile_name": profile_name,
                "rows": len(history),
            },
        }

    async def get_history(
        self, horse_name: str, discipline: str | None = None, horse_id: str | None = None
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"data": {"historique": []}, "meta": {"source": "official", "status": "disabled"}}
        source = "trot_cascade" if self._is_trot(discipline) else "galop_cascade"
        cache_key = (source, f"{horse_id or ''}:{_normalized_name(horse_name)}")
        if cache_key in self._cache:
            return self._cache[cache_key]
        attempted: list[dict[str, Any]] = []
        official_rows: list[dict[str, Any]] = []
        if self._is_trot(discipline):
            try:
                letrot = await self._get_letrot(horse_name)
            except ProviderError as exc:
                letrot = {"data": {"historique": []}, "meta": {"source": "LeTROT", "status": "unavailable", "message": str(exc)}}
            attempted.append(letrot.get("meta", {}))
            official_rows = letrot.get("data", {}).get("historique", [])
        else:
            attempted.append({
                "source": "France Galop",
                "status": "official_login_required",
                "message": "Les fiches chevaux France Galop exigent actuellement une connexion officielle.",
            })

        geny = await self._get_geny(horse_id, horse_name)
        attempted.append(geny.get("meta", {}))
        geny_rows = geny.get("data", {}).get("historique", [])
        history = _merge_histories(official_rows, geny_rows, self.max_rows)
        if history:
            active_sources = list(dict.fromkeys(
                str(row.get("source")) for row in history if row.get("source")
            ))
            payload = {
                "data": {"historique": history},
                "meta": {
                    "source": " + ".join(active_sources),
                    "status": "ok",
                    "rows": len(history),
                    "sources_attempted": attempted,
                },
            }
        else:
            payload = {
                "data": {"historique": []},
                "meta": {
                    "source": "cascade",
                    "status": "history_incomplete",
                    "rows": 0,
                    "sources_attempted": attempted,
                    "message": "Aucun historique certain n'a été trouvé; HippoEdge n'attache jamais une fiche ambiguë.",
                },
            }
        self._cache[cache_key] = payload
        return payload
