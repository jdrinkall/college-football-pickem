import unittest
import app.selected_teams

class TestSelectedTeams(unittest.TestCase):
    def test_selected_teams_is_list(self):
        self.assertIsInstance(app.selected_teams.SELECTED_TEAMS, dict)

if __name__ == "__main__":
    unittest.main()