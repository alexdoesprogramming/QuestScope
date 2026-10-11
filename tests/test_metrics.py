import unittest

from questscope.metrics import cpu_percent, parse_battery, parse_cpu_stat, parse_meminfo


class MetricsTests(unittest.TestCase):
    def test_cpu_delta(self):
        self.assertIsNone(cpu_percent(None, (100, 80)))
        self.assertAlmostEqual(cpu_percent((100, 80), (200, 150)), 30.0)

    def test_cpu_stat(self):
        self.assertEqual(parse_cpu_stat("cpu  10 2 8 70 10 0 0 0\ncpu0 1 0 2 3"), (100, 80))

    def test_meminfo(self):
        result = parse_meminfo("MemTotal: 2048000 kB\nMemAvailable: 1024000 kB\n")
        self.assertEqual(result["total_mb"], 2000)
        self.assertEqual(result["used_mb"], 1000)
        self.assertAlmostEqual(result["used_percent"], 50.0)

    def test_battery_and_temperature(self):
        result = parse_battery("level: 87\ntemperature: 321\n")
        self.assertEqual(result["level"], 87)
        self.assertAlmostEqual(result["temperature_c"], 32.1)

    def test_missing_metrics(self):
        self.assertIsNone(parse_cpu_stat("not cpu stats"))
        self.assertIsNone(parse_meminfo("unavailable"))


if __name__ == "__main__":
    unittest.main()
