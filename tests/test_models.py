import unittest
from app.models import TeamRecord

class TestModels(unittest.TestCase):
    def test_team_record_creation(self):
        rec = TeamRecord(
            season=2024,
            team="Georgia",
            conference="SEC",
            division="East",
            wins=14,
            losses=1,
            ties=0,
            total_games=15
        )
        self.assertEqual(rec.team, "Georgia")

if __name__ == "__main__":
    unittest.main()