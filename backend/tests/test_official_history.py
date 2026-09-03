import asyncio

from app.providers.base import ProviderError
from app.providers.official_history import GenyApiParser, GenyHistoryParser, LeTrotHistoryParser, OfficialHistoryClient, _merge_histories
from app.utils import sanitize_objective_payload


SEARCH_HTML = """
<main>
  <a href="/stats/chevaux/kitena/ZmJbYgMIAQsc/courses">KITENA</a>
  <a href="/stats/chevaux/kitena-bis/another-id/courses">KITENA BIS</a>
</main>
"""


PERFORMANCE_HTML = """
<table>
  <thead><tr>
    <th>Date</th><th>Rg Nb part.</th><th>Red. Km</th><th>Distance</th><th>Fer</th>
    <th>Driver Entraîneur</th><th>Avis Entr.</th><th>Hippodrome Prix</th>
    <th>Départ N° Pos</th><th>Corde</th><th>Cat. course</th><th>Spéc.</th>
    <th>Alloc.</th><th>Gains</th><th>Track.</th><th>Rap. prob.</th>
  </tr></thead>
  <tbody><tr>
    <td><a href="/courses/2025-12-18/5307/1">18/12/25</a></td>
    <td><span class="text-lg">4</span><div class="cel-info"><span>18</span></div></td>
    <td>1'14\"4</td><td>2900 <span class="cel-info">+25m</span></td><td>D4</td>
    <td>DRIVER TEST ENTRAINEUR TEST</td><td>Très confiant</td>
    <td><a href="/hippodromes/meslay-du-maine/5307">MESLAY-DU-MAINE</a>
        <a href="/courses/2025-12-18/5307/1">PRIX DU TRAINEAU</a></td>
    <td>V 3</td><td>D</td><td>F</td><td>M</td><td>20 000</td><td>1 600</td><td>-</td><td>12</td>
  </tr></tbody>
</table>
"""


GENY_HTML = """
<h1>1. Something Coming</h1>
<nav role="navigation">
  <div class="bg-green-700"><span>10/08/26</span></div>
  <span class="w-[94px]">Kempton Park</span>
  <span class="w-[49px]">Plat</span>
  <span class="w-[39px]">1 600</span>
  <span class="w-[72px]">PSF</span>
  <span class="w-[36px]">Hand.</span>
  <span class="w-[112px]">D. Probert</span>
  <span class="w-[27px]">38,1</span>
  <div class="bg-green-500"><span>6</span><span>e</span></div>
</nav>
"""


GENY_MODERN_HTML = """
<h1>14. Native de Bozouls</h1>
<button aria-haspopup="dialog">
  <div class="bg-green-700"><span>24/08/26</span><span>Plat</span></div>
  <span class="w-[108px]">Deauville</span>
  <span>PSF</span><span>Bon</span>
  <span class="w-[51px]">Course A</span><span class="w-[51px]">2 000 m</span>
  <span class="w-[115px]">A. Werle</span>
  <div class="bg-green-500"><span>3</span><span>e</span></div>
  <span class="w-[48px]">55</span>
  <svg aria-label="Sans œillères"></svg>
  <span class="market-column">12,5</span>
</button>
"""


GENY_DIRECTORY_HTML = r'''<script>\"cheval\":{\"id\":2896392,\"nom\":\"Native de Bozouls\",\"slug\":\"native-de-bozouls\"}</script>'''


GENY_API_HORSE = {
    "cheval": {"id": 2709650, "nom": "Jabalpur", "discipline": "TROT"},
    "pronostic": {"selection": [6]},
    "performances": [
        {
            "id": 21574129,
            "rang": 6,
            "etatParticipation": "PARTANT",
            "cheval": {"id": 2709650, "nom": "Jabalpur"},
            "course": {
                "id": 1671089,
                "nomPrix": "Prix d'Europe",
                "dateHeureCourse": "2026-07-25T16:24:00",
                "classe": "GROUPE_II",
                "specialite": "ATTELE",
                "nombrePartants": 12,
                "distance": 2875,
                "typeEtatTerrain": "BON",
                "surface": "DUR",
                "corde": "G",
                "conditionDeLaCourse": "Pour 4 à 11 ans.",
                "etatCourse": "ARRIVEE_DEFINITIVE_EN_ATTENTE_VALIDATION",
                "allocations": {"total": 150000, "devise": "EUR"},
            },
            "reunion": {
                "dateReunion": "2026-07-25",
                "nomReunion": "Enghien",
                "hippodrome": {"nom": "Enghien", "nationalite": "FRANCE"},
            },
            "jockey": {"nom": "Raffin", "initialePrenom": "E."},
            "entraineur": {"nom": "Chavatte", "initialePrenom": "A."},
            "deferre": "DD",
            "redKm": "1'11''9",
            "cote": 14.0,
            "rapportPlace": 3.4,
            "noteFinDeCourse": "Commentaire éditorial interdit.",
        },
        {
            "id": 21500000,
            "rang": 1,
            "cheval": {"id": 2709650, "nom": "Jabalpur"},
            "course": {
                "id": 1669000,
                "nomPrix": "Prix précédent",
                "dateHeureCourse": "2026-06-10T14:00:00",
                "specialite": "ATTELE",
                "nombrePartants": 10,
                "distance": 2700,
                "etatCourse": "ARRIVEE_DEFINITIVE",
            },
            "reunion": {"nomReunion": "Vincennes"},
        },
    ],
}


GENY_API_PARTICIPANTS = [
    {
        "cheval": {"id": 2709650, "nom": "Jabalpur"},
        "numero": 6,
        "rang": 6,
        "jockey": {"nom": "Raffin", "initialePrenom": "E."},
        "cotePmu": 14,
        "noteFinDeCourse": "Interdit",
    },
    {
        "cheval": {"id": 2656445, "nom": "Cobra Killer Gar"},
        "numero": 4,
        "rang": 0,
        "incident": "DISQUALIFIE_ALLURES_IRREGULIERES",
        "coteGeny": 13.8,
        "noteFinDeCourse": "Interdit",
    },
    {
        "cheval": {"id": 2800000, "nom": "Kanto Avis"},
        "numero": 2,
        "rang": 1,
        "redKm": "1'11''2",
    },
]


def test_letrot_search_uses_exact_horse_name():
    assert LeTrotHistoryParser.find_profile_path(SEARCH_HTML, "Kitena") == "/stats/chevaux/kitena/ZmJbYgMIAQsc/courses"
    assert LeTrotHistoryParser.find_profile_path(SEARCH_HTML, "Une Autre Jument") is None


def test_letrot_parser_keeps_facts_and_drops_opinion_and_odds():
    history = LeTrotHistoryParser.parse_performances(PERFORMANCE_HTML)
    assert len(history) == 1
    row = history[0]
    assert row["date"] == "2025-12-18"
    assert row["position"] == 4
    assert row["nb_partants"] == 18
    assert row["distance"] == 2900
    assert row["discipline"] == "Trot monté"
    assert row["classe"] == "Course F"
    assert row["depart"] == "V 3 · Recul 25 m"
    assert row["source"] == "LeTROT"
    flat = str(row).lower()
    assert "confiant" not in flat
    assert "rap" not in row
    assert "odds" not in row


def test_france_galop_boundary_is_explicit_when_geny_cannot_be_matched():
    client = OfficialHistoryClient(request_interval_seconds=0, geny_enabled=False)
    payload = asyncio.run(client.get_history("CHEVAL TEST", "Plat"))
    assert payload["data"]["historique"] == []
    assert payload["meta"]["status"] == "history_incomplete"
    attempts = payload["meta"]["sources_attempted"]
    assert attempts[0]["source"] == "France Galop"
    assert attempts[0]["status"] == "official_login_required"


def test_letrot_403_is_attempted_once_then_the_safe_fallback_continues():
    class RefusedClient(OfficialHistoryClient):
        def __init__(self):
            super().__init__(request_interval_seconds=0, geny_enabled=False)
            self.http_calls = 0

        async def _get_html(self, url: str) -> str:
            self.http_calls += 1
            raise ProviderError(f"Source historique 403: {url}")

    client = RefusedClient()
    first = asyncio.run(client.get_history("ALPHA", "Trot attelé"))
    second = asyncio.run(client.get_history("BETA", "Trot attelé"))

    assert client.http_calls == 1
    assert first["meta"]["sources_attempted"][0]["status"] == "unavailable"
    assert second["meta"]["sources_attempted"][0]["status"] == "temporarily_blocked"
    assert second["meta"]["sources_attempted"][1]["source"] == "Geny"


def test_geny_parser_keeps_foreign_facts_and_drops_market_column():
    profile_name, history = GenyHistoryParser.parse(GENY_HTML, "Something Coming")
    assert profile_name == "Something Coming"
    assert history == [{
        "date": "2026-08-10",
        "hippodrome": "Kempton Park",
        "discipline": "Plat",
        "distance": 1600,
        "terrain": "PSF",
        "classe": "Hand.",
        "position": 6,
        "disqualifie": False,
        "jockey_driver": "D. Probert",
        "source": "Geny",
    }]
    assert "38,1" not in str(history)


def test_geny_identity_mismatch_never_attaches_another_horse():
    profile_name, history = GenyHistoryParser.parse(GENY_HTML, "Another Horse")
    assert profile_name == "Something Coming"
    assert history == []


def test_geny_modern_cards_keep_objective_fields_and_ignore_market_columns():
    profile_name, history = GenyHistoryParser.parse(GENY_MODERN_HTML, "Native de Bozouls")
    assert profile_name == "Native de Bozouls"
    assert history[0]["date"] == "2026-08-24"
    assert history[0]["position"] == 3
    assert history[0]["distance"] == 2000
    assert history[0]["terrain"] == "Bon"
    assert history[0]["equipement"] == "Sans œillères"
    assert "12,5" not in str(history)


def test_geny_daily_directory_resolves_exact_name_and_id():
    assert GenyHistoryParser.find_profile_path(GENY_DIRECTORY_HTML, "NATIVE DE BOZOULS") == "/cheval/2896392-native-de-bozouls"


def test_geny_without_profile_identity_is_rejected():
    _, history = GenyHistoryParser.parse(GENY_HTML.replace("<h1>1. Something Coming</h1>", ""), "Something Coming")
    assert history == []


def test_geny_public_api_reads_the_full_career_array_and_only_objective_fields():
    profile_name, profile_id, history = GenyApiParser.parse_horse(GENY_API_HORSE, "JABALPUR", 500)
    assert profile_name == "Jabalpur"
    assert profile_id == "2709650"
    assert len(history) == 2
    assert history[0]["geny_course_id"] == "1671089"
    assert history[0]["nom_course"] == "Prix d'Europe"
    assert history[0]["allocation_eur"] == 150000
    assert history[0]["nb_partants"] == 12
    assert history[0]["jockey_driver"] == "E. Raffin"
    assert history[0]["entraineur"] == "A. Chavatte"
    assert history[0]["equipement"] == "Ferrure DD"
    flat = str(history).lower()
    assert "cote" not in flat
    assert "rapport" not in flat
    assert "commentaire éditorial" not in flat
    assert "pronostic" not in flat


def test_geny_public_api_rejects_an_identity_mismatch():
    profile_name, profile_id, history = GenyApiParser.parse_horse(GENY_API_HORSE, "AUTRE CHEVAL", 500)
    assert profile_name == "Jabalpur"
    assert profile_id == "2709650"
    assert history == []


def test_geny_course_api_reads_every_runner_and_drops_market_and_editorial_data():
    participants = GenyApiParser.parse_course_participants(GENY_API_PARTICIPANTS)
    assert len(participants) == 3
    assert participants[0]["horse_name"] == "Jabalpur"
    assert participants[1]["horse_name"] == "Cobra Killer Gar"
    assert participants[1]["disqualified"] is True
    assert participants[1].get("position") is None
    assert participants[2]["position"] == 1
    flat = str(participants).lower()
    assert "cote" not in flat
    assert "interdit" not in flat


def test_geny_course_api_is_cached_once_for_a_shared_historical_race():
    class PublicApiClient(OfficialHistoryClient):
        def __init__(self):
            super().__init__(request_interval_seconds=0)
            self.calls = 0

        async def _get_json(self, url, params=None):
            self.calls += 1
            return GENY_API_PARTICIPANTS

    client = PublicApiClient()
    first = asyncio.run(client.get_course_participants("1671089"))
    second = asyncio.run(client.get_course_participants("1671089"))
    assert first == second
    assert client.calls == 1
    assert first["meta"]["participants"] == 3


def test_histories_are_deduplicated_and_official_fields_stay_primary():
    primary = [{"date": "2026-08-10", "hippodrome": "Kempton Park", "distance": 1600, "position": 5, "source": "LeTROT"}]
    complement = [{"date": "2026-08-10", "hippodrome": "Kempton Park", "distance": 1600, "position": 6, "terrain": "PSF", "source": "Geny"}]
    merged = _merge_histories(primary, complement, 50)
    assert len(merged) == 1
    assert merged[0]["position"] == 5
    assert merged[0]["terrain"] == "PSF"
    assert merged[0]["source"] == "LeTROT + Geny"


def test_distinct_geny_races_with_same_date_track_and_distance_are_preserved():
    rows = [
        {
            "date": "2026-08-10", "hippodrome": "Vincennes", "distance": 2700,
            "geny_course_id": "101", "position": 1, "source": "Geny carrière complète",
        },
        {
            "date": "2026-08-10", "hippodrome": "Vincennes", "distance": 2700,
            "geny_course_id": "102", "position": 4, "source": "Geny carrière complète",
        },
    ]
    merged = _merge_histories([], rows, 500)
    assert len(merged) == 2
    assert {row["geny_course_id"] for row in merged} == {"101", "102"}


def test_official_dq_marker_is_not_replaced_by_complement_rank():
    primary = [{"date": "2026-08-10", "hippodrome": "Vincennes", "distance": 2700, "disqualifie": True, "source": "LeTROT"}]
    complement = [{"date": "2026-08-10", "hippodrome": "Vincennes", "distance": 2700, "position": 4, "terrain": "Bon", "source": "Geny"}]
    merged = _merge_histories(primary, complement, 50)
    assert merged[0].get("position") is None
    assert merged[0]["disqualifie"] is True
    assert merged[0]["terrain"] == "Bon"


def test_firewall_removes_provider_opinion_and_probable_odds_aliases():
    clean = sanitize_objective_payload({
        "date": "2026-09-02",
        "avis_entraineur": "confiant",
        "rapport_probable": 12,
        "trainer_opinion": "positive",
        "synthese_presse": {"selection": [1, 2, 3]},
        "rpr": 98,
    })
    assert clean == {"date": "2026-09-02"}
