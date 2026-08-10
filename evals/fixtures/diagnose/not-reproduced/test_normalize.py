import unittest

from normalize import normalize


class NormalizeTests(unittest.TestCase):
    def test_collapses_repeated_whitespace(self) -> None:
        self.assertEqual(normalize("  alpha   beta  "), "alpha beta")


if __name__ == "__main__":
    unittest.main()
