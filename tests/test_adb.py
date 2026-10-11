import unittest
from unittest.mock import patch

from questscope.adb import AdbClient, AdbError


class AdbClientTests(unittest.TestCase):
    def test_devices_parses_ready_and_unauthorized(self):
        client = AdbClient(executable="adb")
        output = (
            "List of devices attached\n"
            "quest123 device product:hollywood model:Quest_2\n"
            "quest456 unauthorized usb:1-2\n"
            "\n"
        )
        with patch.object(client, "run", return_value=output):
            devices = client.devices()
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].serial, "quest123")
        self.assertTrue(devices[0].ready)
        self.assertFalse(devices[1].ready)
        self.assertEqual(devices[1].state, "unauthorized")

    def test_missing_adb_has_actionable_error(self):
        client = AdbClient(executable=None)
        with patch("questscope.adb.shutil.which", return_value=None):
            client = AdbClient()
        with self.assertRaisesRegex(AdbError, "Install Android Platform Tools"):
            client.run(["devices"])

    def test_invalid_serial_rejected(self):
        client = AdbClient(executable="adb")
        with self.assertRaises(ValueError):
            client.shell("bad serial", "getprop")


if __name__ == "__main__":
    unittest.main()
