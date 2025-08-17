import unittest
import app.main

class TestMain(unittest.TestCase):
    def test_module_import(self):
        self.assertIsNotNone(app.main)

if __name__ == "__main__":
    unittest.main()