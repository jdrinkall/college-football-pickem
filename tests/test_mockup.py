import unittest
from unittest.mock import MagicMock, patch
from app.services import upsert_records, refresh_season

class TestServices(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.season = 2024

    def test_upsert_records_inserts_records_correctly(self):
        cfbd_records = [{
            "team": "Georgia",
            "conference": "SEC",
            "division": "East",
            "wins": 14,
            "losses": 1,
            "ties": 0,
            "totalGames": 15
        }]
        written = upsert_records(self.session, self.season, cfbd_records)
        self.assertEqual(written, 1)
        self.session.add.assert_called()
        self.session.commit.assert_called()

    def test_upsert_records_skips_missing_team(self):
        cfbd_records = [{
            "conference": "SEC",
            "division": "East",
            "wins": 14,
            "losses": 1,
            "ties": 0,
            "totalGames": 15
        }]
        written = upsert_records(self.session, self.season, cfbd_records)
        self.assertEqual(written, 0)
        self.session.commit.assert_called()

    @patch("app.services.fetch_team_records", return_value=[{
        "team": "Georgia",
        "conference": "SEC",
        "division": "East",
        "wins": 14,
        "losses": 1,
        "ties": 0,
        "totalGames": 15
    }])
    def test_refresh_season_calls_fetch_and_upsert(self, mock_fetch):
        with patch("app.services.upsert_records", return_value=1) as mock_upsert:
            import asyncio
            result = asyncio.run(refresh_season(self.season))
            self.assertEqual(result, 1)
            mock_fetch.assert_called_with(self.season)
            mock_upsert.assert_called()

if __name__ == "__main__":
    unittest.main()