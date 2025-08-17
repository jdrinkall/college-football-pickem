import unittest
import app.cfbd_client

class TestCFBDClient(unittest.TestCase):
    def test_module_import(self):
        self.assertIsNotNone(app.cfbd_client)

if __name__ == "__main__":
    unittest.main()