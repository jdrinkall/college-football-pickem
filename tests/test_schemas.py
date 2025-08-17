import unittest
import app.schemas

class TestSchemas(unittest.TestCase):
    def test_module_import(self):
        self.assertIsNotNone(app.schemas)

if __name__ == "__main__":
    unittest.main()