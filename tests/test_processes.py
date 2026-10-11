import unittest
from questscope.processes import parse_process_list

class ProcessParserTests(unittest.TestCase):
    def test_toybox_ps_columns(self):
        rows = parse_process_list(
            "USER PID PPID VSZ RSS WCHAN ADDR S NAME\n"
            "root 1 0 1234 500 0 0 S init\n"
            "u0_a123 2500 900 4567 1000 0 0 R com.example.game\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["pid"], "1")
        self.assertEqual(rows[0]["name"], "init")
        self.assertEqual(rows[1]["user"], "u0_a123")
        self.assertEqual(rows[1]["state"], "R")
        self.assertEqual(rows[1]["name"], "com.example.game")

    def test_empty_or_unknown_format(self):
        self.assertEqual(parse_process_list(""), [])
        self.assertEqual(parse_process_list("no useful columns\n1 2 3"), [])

if __name__ == "__main__":
    unittest.main()
