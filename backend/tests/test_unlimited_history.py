from app.providers.official_history import OfficialHistoryClient, _merge_histories


def test_zero_history_limit_means_no_local_truncation():
    rows = [
        {
            "date": f"2026-01-{(index % 28) + 1:02d}",
            "hippodrome": f"Track {index}",
            "distance": 2000,
            "geny_course_id": str(index + 1),
        }
        for index in range(700)
    ]
    client = OfficialHistoryClient(max_rows=0)
    assert client.max_rows is None
    assert len(_merge_histories([], rows, client.max_rows)) == 700


def test_explicit_positive_history_limit_still_works_for_debug_or_custom_deploys():
    rows = [
        {
            "date": f"2026-01-{(index % 28) + 1:02d}",
            "hippodrome": f"Track {index}",
            "distance": 2000,
            "geny_course_id": str(index + 1),
        }
        for index in range(20)
    ]
    assert len(_merge_histories([], rows, 7)) == 7
