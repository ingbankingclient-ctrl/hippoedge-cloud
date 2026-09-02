import asyncio

from app.providers.official_history import GenyHistoryParser, LeTrotHistoryParser, OfficialHistoryClient, _merge_histories
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


def test_geny_without_profile_identity_is_rejected():
    _, history = GenyHistoryParser.parse(GENY_HTML.replace("<h1>1. Something Coming</h1>", ""), "Something Coming")
    assert history == []


def test_histories_are_deduplicated_and_official_fields_stay_primary():
    primary = [{"date": "2026-08-10", "hippodrome": "Kempton Park", "distance": 1600, "position": 5, "source": "LeTROT"}]
    complement = [{"date": "2026-08-10", "hippodrome": "Kempton Park", "distance": 1600, "position": 6, "terrain": "PSF", "source": "Geny"}]
    merged = _merge_histories(primary, complement, 50)
    assert len(merged) == 1
    assert merged[0]["position"] == 5
    assert merged[0]["terrain"] == "PSF"
    assert merged[0]["source"] == "LeTROT + Geny"


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
