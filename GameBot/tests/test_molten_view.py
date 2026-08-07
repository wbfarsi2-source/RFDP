from games.kintara.molten.view import format_snapshot


def test_molten_view_is_concise() -> None:
    text = format_snapshot(
        {
            "accurate": True,
            "top3": [
                {"server": "Server 15", "count": 12},
                {"server": "Server 7", "count": 2},
                {"server": "Server 4", "count": 1},
            ],
            "monitored": 25,
            "live": 20,
            "total_players": 31,
            "updated_at": "2026-08-04T18:48:00Z",
        },
        "en",
    )
    assert "Server 15" in text
    assert "monitored" not in text.lower()
    assert "updated" not in text.lower()
    assert "2026" not in text


def test_molten_requires_accurate_snapshot() -> None:
    text = format_snapshot({"accurate": False, "top3": []}, "en")
    assert "not reliable" in text.lower()
