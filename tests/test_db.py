import unittest
import app.db

class TestDB(unittest.TestCase):
    def test_engine_exists(self):
        self.assertIsNotNone(app.db.engine)

    def test_session_local(self):
        with app.db.SessionLocal() as session:
            self.assertIsNotNone(session)

if __name__ == "__main__":
    unittest.main()