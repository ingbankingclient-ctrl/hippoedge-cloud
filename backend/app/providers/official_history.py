from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from .base import ProviderError
from ..utils import sanitize_objective_payload, to_float, to_int


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
    MODERN_FIELD_CLASSES = {
        "w-[108px]": "hippodrome",
        "w-[115px]": "jockey",
        "w-[51px]": "context",
        "w-[48px]": "handicap_value",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str]]] = []
        self.current: dict[str, list[str]] | None = None
        self.current_mode: str | None = None
        self.rows: list[dict[str, Any]] = []
        self.in_h1 = False
        self.heading_parts: list[str] = []
        self.profile_name: str | None = None

    @staticmethod
    def find_profile_path(html: str, horse_name: str) -> str | None:
        """Resolve an exact horse from Geny's daily public directory.

        The current directory embeds its horse identities in the
        server-rendered Next.js payload rather than ordinary links.  Matching
        the normalized full name prevents a similarly named horse from ever
        being attached to the wrong runner.
        """
        wanted = _normalized_name(horse_name)
        parser = _LinkHTMLParser()
        parser.feed(html)
        for href, label in parser.links:
            if href.startswith("/cheval/") and _normalized_name(label) == wanted:
                return href
        pattern = re.compile(
            r'\\"cheval\\":\{\\"id\\":(\d+),\\"nom\\":\\"([^"\\]+)\\"'
            r'[^{}]{0,350}?\\"slug\\":\\"([^"\\]+)\\"'
        )
        for horse_id, label, slug in pattern.findall(html):
            if _normalized_name(label) == wanted:
                return f"/cheval/{horse_id}-{slug}"
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        self.stack.append((tag, classes))
        if tag == "h1":
            self.in_h1 = True
            self.heading_parts = []
        if tag == "nav" and attributes.get("role") == "navigation" and self.current is None:
            self.current = {}
            self.current_mode = "legacy"
        elif tag == "button" and attributes.get("aria-haspopup") == "dialog" and self.current is None:
            # Geny's 2026 mobile/server-rendered career cards are buttons, not
            # navigation rows.  Their factual fields still have stable layout
            # classes, so they can be read without touching odds or editorial
            # content.
            self.current = {}
            self.current_mode = "modern"
        if self.current is not None and self.current_mode == "modern":
            equipment = attributes.get("aria-label")
            if equipment and equipment.lower() not in {"ouvrir", "fermer"}:
                self.current.setdefault("equipment", []).append(equipment)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.in_h1 and data.strip():
            self.heading_parts.append(data)
        if self.current is None or not data.strip():
            return
        class_chain = set().union(*(classes for _, classes in self.stack))
        if self.current_mode == "modern":
            self.current.setdefault("tokens", []).append(data)
            key: str | None = None
            if "bg-green-700" in class_chain:
                key = "header"
            elif "bg-green-500" in class_chain:
                key = "rang"
            else:
                for class_name, field_name in self.MODERN_FIELD_CLASSES.items():
                    if class_name in class_chain:
                        key = field_name
                        break
            if key:
                self.current.setdefault(key, []).append(data)
            return
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

    def _finish_current(self) -> None:
        if self.current is None:
            return
        if self.current_mode == "modern":
            values = {
                key: [_clean(item) for item in parts if _clean(item)]
                for key, parts in self.current.items()
            }
            header = values.get("header", [])
            contexts = values.get("context", [])
            tokens = values.get("tokens", [])
            row: dict[str, str] = {}
            if header:
                row["date"] = header[0]
            if len(header) > 1:
                row["discipline"] = header[1]
            for field_name in ("hippodrome", "jockey", "rang", "handicap_value"):
                parts = values.get(field_name, [])
                if parts:
                    row[field_name] = _clean(" ".join(parts))
            if contexts:
                row["classe"] = contexts[0]
            if len(contexts) > 1:
                row["distance"] = contexts[1]
            # Between the track and category, the modern card prints direction
            # followed by surface/going.  Only the latter is useful here.
            track = row.get("hippodrome")
            category = row.get("classe")
            if track in tokens and category in tokens:
                start = tokens.index(track) + 1
                end = tokens.index(category, start)
                between = [item for item in tokens[start:end] if item not in {"-", "--"}]
                if between:
                    row["terrain"] = between[-1]
            equipment = values.get("equipment", [])
            if equipment:
                row["equipment"] = " · ".join(dict.fromkeys(equipment))
        else:
            row = {key: _clean(" ".join(parts)) for key, parts in self.current.items()}
        if re.fullmatch(r"\d{2}/\d{2}(?:/\d{2,4}|\s+\d{4})", row.get("date", "")):
            self.rows.append(row)
        self.current = None
        self.current_mode = None

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.in_h1:
            heading = _clean(" ".join(self.heading_parts))
            self.profile_name = re.sub(r"^\d+\s*[.]\s*", "", heading) or None
            self.in_h1 = False
        if (
            (tag == "nav" and self.current_mode == "legacy")
            or (tag == "button" and self.current_mode == "modern")
        ):
            self._finish_current()
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
            race_date = None
            for date_format in ("%d/%m/%y", "%d/%m/%Y", "%d/%m %Y"):
                try:
                    race_date = datetime.strptime(raw["date"], date_format).date().isoformat()
                    break
                except (KeyError, ValueError):
                    pass
            if race_date is None:
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
                "equipement": raw.get("equipment") or None,
                "source": "Geny",
            }
            history.append({key: value for key, value in row.items() if value not in (None, "")})
            if len(history) >= max_rows:
                break
        return parser.profile_name, history


class GenyApiParser:
    """Map Geny's public factual JSON into HippoEdge history rows.

    The horse endpoint contains the complete server-side career array, whereas
    the rendered HTML can expose only a shortened visual list.  We select the
    objective fields explicitly instead of sanitising and storing the provider
    response wholesale.  Odds, betting reports, predictions and the editorial
    end-of-race note therefore have no route into the database.
    """

    DISQUALIFIED_MARKERS = ("DISQUAL", "DISTANC", "DAI", "D_A_I")
    NON_FINISH_MARKERS = ("ARRET", "TOMBE", "DEROB", "REFUS", "NON_PARTANT", "NP")

    @staticmethod
    def _person(value: Any) -> str | None:
        if not isinstance(value, dict):
            return _clean(str(value)) or None if value else None
        first = value.get("initialePrenom") or value.get("prenom") or ""
        title = value.get("titre") or ""
        last = value.get("nom") or ""
        return _clean(" ".join(str(item) for item in (title, first, last) if item)) or None

    @staticmethod
    def _label(value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            for key in ("libelle", "libelleCourt", "nom", "code", "value"):
                if value.get(key) not in (None, ""):
                    return _clean(str(value[key])) or None
            return None
        return _clean(str(value)) or None

    @classmethod
    def _result(cls, participant: dict[str, Any], course: dict[str, Any] | None = None) -> tuple[int | None, bool, str | None]:
        raw_rank = to_int(participant.get("rang"))
        position = raw_rank if raw_rank is not None and raw_rank > 0 else None
        incident = _clean(str(participant.get("incident") or ""))
        upper = incident.upper()
        disqualified = any(marker in upper for marker in cls.DISQUALIFIED_MARKERS)
        status: str | None = incident or None
        if position is None and not status:
            participation = _clean(str(participant.get("etatParticipation") or "")).upper()
            state = _clean(str((course or {}).get("etatCourse") or "")).upper()
            if any(marker in participation for marker in cls.NON_FINISH_MARKERS):
                status = participation
            elif participant.get("rang") is not None and raw_rank == 0:
                status = "NON_PLACE"
            elif state.startswith("ARRIVEE"):
                # Geny uses rank 0 for a runner that completed outside the
                # published places. It is a known non-place, not missing data.
                status = "NON_PLACE"
        if disqualified:
            position = None
        return position, disqualified, status

    @staticmethod
    def _equipment(participant: dict[str, Any]) -> str | None:
        parts: list[str] = []
        deferre = GenyApiParser._label(participant.get("deferre"))
        if deferre and deferre.upper() not in {"FF", "NON", "AUCUN"}:
            parts.append(f"Ferrure {deferre}")
        oeilleres = GenyApiParser._label(participant.get("oeilleres"))
        if oeilleres and oeilleres.upper() not in {"SANS_OEILLERES", "SANS ŒILLÈRES", "NON", "AUCUN"}:
            parts.append(f"Œillères {oeilleres.replace('_', ' ').lower()}")
        if participant.get("bonnet") is True:
            parts.append("Bonnet")
        if participant.get("attacheLangue") is True:
            parts.append("Attache-langue")
        return " · ".join(dict.fromkeys(parts)) or None

    @classmethod
    def parse_horse(
        cls,
        payload: Any,
        horse_name: str,
        max_rows: int = 500,
    ) -> tuple[str | None, str | None, list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            return None, None, []
        profile = payload.get("cheval")
        if not isinstance(profile, dict):
            return None, None, []
        profile_name = _clean(str(profile.get("nom") or "")) or None
        profile_id = str(profile.get("id")) if profile.get("id") is not None else None
        if not profile_name or _normalized_name(profile_name) != _normalized_name(horse_name):
            return profile_name, profile_id, []

        performances = payload.get("performances")
        if not isinstance(performances, list):
            return profile_name, profile_id, []
        history: list[dict[str, Any]] = []
        for performance in performances:
            if not isinstance(performance, dict):
                continue
            course = performance.get("course") if isinstance(performance.get("course"), dict) else {}
            meeting = performance.get("reunion") if isinstance(performance.get("reunion"), dict) else {}
            track_data = meeting.get("hippodrome") if isinstance(meeting.get("hippodrome"), dict) else {}
            horse = performance.get("cheval") if isinstance(performance.get("cheval"), dict) else {}
            performance_name = _clean(str(horse.get("nom") or profile_name))
            performance_id = str(horse.get("id")) if horse.get("id") is not None else profile_id
            if (
                _normalized_name(performance_name) != _normalized_name(profile_name)
                or (profile_id and performance_id and performance_id != profile_id)
            ):
                # A mixed or malformed payload can never attach another horse's
                # race to the requested identity.
                continue

            timestamp = str(course.get("dateHeureCourse") or meeting.get("dateReunion") or "")
            match = re.match(r"(\d{4}-\d{2}-\d{2})", timestamp)
            if not match:
                continue
            position, disqualified, result_status = cls._result(performance, course)
            allocations = course.get("allocations") if isinstance(course.get("allocations"), dict) else {}
            race_name = cls._label(course.get("nomPrix") or course.get("nomEpreuve"))
            track = cls._label(track_data.get("nom") or meeting.get("nomReunion") or performance.get("hippodrome"))
            start_bits: list[str] = []
            start = cls._label(course.get("depart"))
            if start:
                start_bits.append(start)
            recoil = to_int(performance.get("recul"))
            if recoil:
                start_bits.append(f"Recul {recoil} m")

            row = {
                "date": match.group(1),
                "hippodrome": track,
                "code_course": race_name,
                "nom_course": race_name,
                "discipline": cls._label(course.get("specialite") or course.get("discipline")),
                "distance": to_int(course.get("distance") or performance.get("distance")),
                "terrain": cls._label(course.get("typeEtatTerrain")),
                "surface": cls._label(course.get("surface") or course.get("revetement")),
                "position": position,
                "disqualifie": disqualified,
                "status_arrivee": result_status,
                "reduction_km": cls._label(performance.get("redKm")),
                "chrono": cls._label(performance.get("chrono")),
                "temps_total": cls._label(performance.get("tempsTotal")),
                "ecart_arrivee": cls._label(performance.get("ecartArrivee")),
                "classe": cls._label(course.get("classe") or course.get("typeCourse")),
                "depart": " · ".join(start_bits) or None,
                "corde": to_int(performance.get("positionDepart")),
                "sens_corde": cls._label(course.get("corde")),
                "poids": to_float(performance.get("poids")),
                "valeur_handicap": to_float(performance.get("valeurHandicap")),
                "equipement": cls._equipment(performance),
                "nb_partants": to_int(course.get("nombrePartants")),
                "allocation_eur": to_float(allocations.get("total")),
                "gains_course_eur": to_float(performance.get("gainsCourse")),
                "jockey_driver": cls._person(performance.get("jockey")),
                "entraineur": cls._person(performance.get("entraineur")),
                "proprietaire": cls._person(performance.get("proprietaire")),
                "pays": cls._label(track_data.get("nationalite") or track_data.get("nationaliteIso")),
                "condition_course": cls._label(course.get("conditionDeLaCourse")),
                "etat_course": cls._label(course.get("etatCourse")),
                "dimension": cls._label(course.get("dimension")),
                "geny_course_id": str(course.get("id")) if course.get("id") is not None else None,
                "geny_performance_id": str(performance.get("id")) if performance.get("id") is not None else None,
                "geny_horse_id": performance_id,
                "source": "Geny carrière complète",
            }
            # The allow-list above is the first firewall. The recursive common
            # firewall is kept as a second defence before the row leaves the
            # parser.
            clean_row = sanitize_objective_payload({
                key: value for key, value in row.items() if value not in (None, "", [])
            })
            history.append(clean_row)
            if len(history) >= max(1, max_rows):
                break
        return profile_name, profile_id, history

    @classmethod
    def parse_course_participants(cls, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            raw_participants = payload
            course: dict[str, Any] = {}
        elif isinstance(payload, dict):
            course = payload.get("course") if isinstance(payload.get("course"), dict) else payload
            raw_participants = course.get("participants") or course.get("partants") or []
        else:
            return []
        if not isinstance(raw_participants, list):
            return []
        participants: list[dict[str, Any]] = []
        for raw in raw_participants:
            if not isinstance(raw, dict):
                continue
            horse = raw.get("cheval") if isinstance(raw.get("cheval"), dict) else {}
            horse_name = _clean(str(horse.get("nom") or raw.get("nomCheval") or raw.get("nom") or ""))
            if not horse_name:
                continue
            position, disqualified, result_status = cls._result(raw, course)
            row = {
                "horse_name": horse_name,
                "geny_horse_id": str(horse.get("id")) if horse.get("id") is not None else None,
                "number": to_int(raw.get("numero")),
                "position": position,
                "disqualified": disqualified,
                "result_status": result_status,
                "chrono_km": cls._label(raw.get("redKm")),
                "chrono": cls._label(raw.get("chrono")),
                "temps_total": cls._label(raw.get("tempsTotal")),
                "ecart_arrivee": cls._label(raw.get("ecartArrivee")),
                "distance_m": to_int(raw.get("distance")),
                "weight_kg": to_float(raw.get("poids")),
                "draw": to_int(raw.get("positionDepart")),
                "equipment": cls._equipment(raw),
                "jockey_driver": cls._person(raw.get("jockey")),
                "trainer": cls._person(raw.get("entraineur")),
            }
            participants.append(sanitize_objective_payload({
                key: value for key, value in row.items() if value not in (None, "", [])
            }))
        return participants


def _merge_histories(primary: list[dict[str, Any]], complement: list[dict[str, Any]], max_rows: int) -> list[dict[str, Any]]:
    """Merge objective rows without losing provenance or creating duplicates."""

    rows: list[dict[str, Any]] = []

    def exact_id(row: dict[str, Any]) -> str | None:
        value = str(row.get("geny_course_id") or "").strip()
        return value if value.isdigit() else None

    def signature(row: dict[str, Any]) -> tuple[str, str, int | None]:
        return (
            str(row.get("date") or ""),
            _normalized_name(str(row.get("hippodrome") or "")),
            to_int(row.get("distance")),
        )

    def merge_into(existing: dict[str, Any], row: dict[str, Any]) -> None:
        for field, value in row.items():
            if field == "source":
                sources = list(dict.fromkeys(
                    str(existing.get("source", "")).split(" + ") + str(value).split(" + ")
                ))
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

    for source_row in [*primary, *complement]:
        row = dict(source_row)
        incoming_id = exact_id(row)
        existing: dict[str, Any] | None = None
        if incoming_id:
            existing = next((item for item in rows if exact_id(item) == incoming_id), None)
            if existing is None:
                # A LeTROT/PMU row has no Geny id. It may be fused only when
                # there is one unambiguous row with the same factual signature.
                candidates = [
                    item for item in rows
                    if exact_id(item) is None and signature(item) == signature(row)
                ]
                if len(candidates) == 1:
                    existing = candidates[0]
        else:
            candidates = [item for item in rows if signature(item) == signature(row)]
            if len(candidates) == 1:
                existing = candidates[0]

        if existing is None:
            rows.append(row)
        else:
            merge_into(existing, row)

    return sorted(rows, key=lambda item: str(item.get("date") or ""), reverse=True)[:max_rows]


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
        max_rows: int = 500,
    ):
        self.letrot_base_url = letrot_base_url.rstrip("/")
        self.france_galop_base_url = france_galop_base_url.rstrip("/")
        self.geny_base_url = geny_base_url.rstrip("/")
        self.geny_enabled = geny_enabled
        self.enabled = enabled
        self.request_interval_seconds = max(0.0, request_interval_seconds)
        self.max_rows = max(1, min(max_rows, 500))
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._geny_course_cache: dict[str, dict[str, Any]] = {}
        self._geny_directory_cache: dict[str, str] = {}
        self._request_lock = asyncio.Lock()
        self._last_request_at = 0.0
        self._letrot_blocked_reason: str | None = None

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

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        async with self._request_lock:
            remaining = self.request_interval_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            headers = {
                "Accept": "application/json",
                "Accept-Language": "fr-FR,fr;q=0.9",
                "User-Agent": "HippoEdge/1.0 (usage personnel; lecture seule)",
            }
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                response = await client.get(url, params=params or {}, headers=headers)
            self._last_request_at = time.monotonic()
        if response.status_code >= 400:
            raise ProviderError(f"Source historique JSON {response.status_code}: {url}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f"Source historique JSON invalide: {url}") from exc

    async def _get_letrot(self, horse_name: str) -> dict[str, Any]:
        if self._letrot_blocked_reason:
            return {
                "data": {"historique": []},
                "meta": {
                    "source": "LeTROT",
                    "status": "temporarily_blocked",
                    "message": self._letrot_blocked_reason,
                },
            }
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

    async def _get_geny(
        self,
        horse_id: str | None,
        horse_name: str,
        race_date: date | None = None,
    ) -> dict[str, Any]:
        if not self.geny_enabled:
            return {"data": {"historique": []}, "meta": {"source": "Geny", "status": "disabled"}}
        candidates: list[str] = []
        if horse_id and str(horse_id).isdigit():
            candidates.append(f"{self.geny_base_url}/cheval/{horse_id}")

        # PMU's idCheval is often a pedigree identity string, not Geny's
        # numeric identifier.  Resolve the exact name from the daily public
        # directory in that case (and as a safe fallback after a stale ID).
        directory_key = race_date.isoformat() if race_date else "today"
        directory_url = (
            f"{self.geny_base_url}/chevaux/{race_date.isoformat()}"
            if race_date
            else f"{self.geny_base_url}/cheval"
        )
        try:
            directory_html = self._geny_directory_cache.get(directory_key)
            if directory_html is None:
                directory_html = await self._get_html(directory_url)
                self._geny_directory_cache[directory_key] = directory_html
            profile_path = GenyHistoryParser.find_profile_path(directory_html, horse_name)
            if profile_path:
                resolved = urljoin(f"{self.geny_base_url}/", profile_path)
                if resolved not in candidates:
                    candidates.append(resolved)
        except ProviderError as exc:
            if not candidates:
                return {
                    "data": {"historique": []},
                    "meta": {"source": "Geny", "status": "unavailable", "message": str(exc)},
                }

        if not candidates:
            return {"data": {"historique": []}, "meta": {"source": "Geny", "status": "not_found"}}

        last_meta: dict[str, Any] = {"source": "Geny", "status": "identity_unverified"}
        for profile_url in candidates:
            horse_id_match = re.search(r"/cheval/(\d+)", profile_url)
            if horse_id_match:
                geny_horse_id = horse_id_match.group(1)
                api_url = f"{self.geny_base_url}/api/turf/cheval/{geny_horse_id}"
                try:
                    api_payload = await self._get_json(api_url, {"withPerformances": "true"})
                    profile_name, verified_id, history = GenyApiParser.parse_horse(
                        api_payload,
                        horse_name,
                        self.max_rows,
                    )
                    if not profile_name:
                        status = "identity_unverified"
                    elif _normalized_name(profile_name) != _normalized_name(horse_name):
                        status = "identity_mismatch"
                    else:
                        status = "ok" if history else "no_performance_rows"
                    last_meta = {
                        "source": "Geny carrière complète",
                        "status": status,
                        "profile_url": profile_url,
                        "api_url": api_url,
                        "profile_name": profile_name,
                        "geny_horse_id": verified_id,
                        "rows": len(history),
                        "career_scope": "complete_public_array",
                    }
                    if status in {"ok", "no_performance_rows"}:
                        return {"data": {"historique": history}, "meta": last_meta}
                except ProviderError as exc:
                    # The public JSON endpoint is the complete source. The
                    # rendered page remains a safe reduced fallback during a
                    # temporary API outage.
                    last_meta = {
                        "source": "Geny carrière complète",
                        "status": "api_unavailable",
                        "profile_url": profile_url,
                        "api_url": api_url,
                        "message": str(exc),
                    }
            try:
                profile_html = await self._get_html(profile_url)
            except ProviderError as exc:
                last_meta = {"source": "Geny", "status": "unavailable", "message": str(exc)}
                continue
            profile_name, history = GenyHistoryParser.parse(profile_html, horse_name, self.max_rows)
            if not profile_name:
                status = "identity_unverified"
            elif _normalized_name(profile_name) != _normalized_name(horse_name):
                status = "identity_mismatch"
            else:
                status = "ok" if history else "no_performance_rows"
            last_meta = {
                "source": "Geny",
                "status": status,
                "profile_url": profile_url,
                "profile_name": profile_name,
                "rows": len(history),
            }
            if status in {"ok", "no_performance_rows"}:
                return {"data": {"historique": history}, "meta": last_meta}
        return {"data": {"historique": []}, "meta": last_meta}

    async def get_course_participants(self, course_id: str | int) -> dict[str, Any]:
        """Return every factual runner/result from one exact historical race.

        A course id is taken only from a verified Geny career row.  The public
        endpoint is cached for the worker lifetime so a race shared by many
        horses is downloaded once, not once per horse.
        """
        key = str(course_id).strip()
        if not key.isdigit():
            raise ProviderError(f"Identifiant de course Geny invalide: {course_id}")
        if key in self._geny_course_cache:
            return self._geny_course_cache[key]
        if not self.enabled or not self.geny_enabled:
            return {
                "data": {"course_id": key, "participants": []},
                "meta": {"source": "Geny course détaillée", "status": "disabled"},
            }
        api_url = f"{self.geny_base_url}/api/turf/course/{key}/partants"
        raw = await self._get_json(api_url, {"withPremieresFois": "true"})
        participants = GenyApiParser.parse_course_participants(raw)
        payload = {
            "data": {"course_id": key, "participants": participants},
            "meta": {
                "source": "Geny course détaillée",
                "status": "ok" if participants else "no_participants",
                "participants": len(participants),
                "api_url": api_url,
            },
        }
        self._geny_course_cache[key] = payload
        return payload

    async def get_history(
        self,
        horse_name: str,
        discipline: str | None = None,
        horse_id: str | None = None,
        race_date: date | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"data": {"historique": []}, "meta": {"source": "official", "status": "disabled"}}
        source = "trot_cascade" if self._is_trot(discipline) else "galop_cascade"
        cache_key = (
            source,
            f"{race_date.isoformat() if race_date else ''}:{horse_id or ''}:{_normalized_name(horse_name)}",
        )
        if cache_key in self._cache:
            return self._cache[cache_key]
        attempted: list[dict[str, Any]] = []
        official_rows: list[dict[str, Any]] = []
        if self._is_trot(discipline):
            try:
                letrot = await self._get_letrot(horse_name)
            except ProviderError as exc:
                message = str(exc)
                if "403" in message:
                    # A single access refusal applies to this source for the
                    # lifetime of the worker. Repeating it for every horse only
                    # delays the card and can aggravate the block. The factual
                    # Geny fallback remains active and the limitation is kept in
                    # the audit metadata instead of being hidden.
                    self._letrot_blocked_reason = message
                letrot = {"data": {"historique": []}, "meta": {"source": "LeTROT", "status": "unavailable", "message": str(exc)}}
            attempted.append(letrot.get("meta", {}))
            official_rows = letrot.get("data", {}).get("historique", [])
        else:
            attempted.append({
                "source": "France Galop",
                "status": "official_login_required",
                "message": "Les fiches chevaux France Galop exigent actuellement une connexion officielle.",
            })

        geny = await self._get_geny(horse_id, horse_name, race_date=race_date)
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
