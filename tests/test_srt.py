import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stcc import format_ts, group_cues, render_srt, wrap_two_lines  # noqa: E402


def w(text, start, end):
    return {"w": text, "start": start, "end": end, "conf": 0.9}


class TimestampTest(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(format_ts(0.0), "00:00:00,000")

    def test_millisecond_rounding(self):
        self.assertEqual(format_ts(1.2346), "00:00:01,235")

    def test_hours(self):
        self.assertEqual(format_ts(3661.5), "01:01:01,500")

    def test_negative_clamped(self):
        self.assertEqual(format_ts(-3.2), "00:00:00,000")


class WrapTest(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(wrap_two_lines("Hello world."), "Hello world.")

    def test_long_text_becomes_two_lines(self):
        text = " ".join(["word"] * 20)  # 99 chars
        wrapped = wrap_two_lines(text)
        lines = wrapped.split("\n")
        self.assertLessEqual(len(lines), 2)
        self.assertEqual(wrapped.replace("\n", " "), text)

    def test_unsplittable_word_does_not_lose_text(self):
        huge = "y" * 100
        self.assertEqual(wrap_two_lines(huge), huge)


class RenderGoldenTest(unittest.TestCase):
    def test_golden_output(self):
        words = [
            w("All", 1.84, 2.16),
            w("right,", 2.20, 2.50),
            w("let's", 2.55, 2.80),
            w("start", 2.85, 3.10),
            w("with", 3.15, 3.35),
            w("the", 3.40, 3.50),
            w("problem.", 3.55, 4.00),
        ]
        cues = group_cues(words)
        self.assertEqual(
            render_srt(cues),
            "1\n00:00:01,840 --> 00:00:04,000\nAll right, let's start with the problem.\n",
        )

    def test_sequential_indices_and_blank_line_separators(self):
        words = [w("One.", 0.0, 0.4), w("Two.", 5.0, 5.4)]  # gap forces two cues
        out = render_srt(group_cues(words))
        self.assertEqual(
            out,
            "1\n00:00:00,000 --> 00:00:00,400\nOne.\n\n"
            "2\n00:00:05,000 --> 00:00:05,400\nTwo.\n",
        )

    def test_empty_cues_render_empty(self):
        self.assertEqual(render_srt([]), "")


if __name__ == "__main__":
    unittest.main()
