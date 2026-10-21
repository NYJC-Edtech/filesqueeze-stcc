import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stcc import group_cues  # noqa: E402


def w(text, start, end):
    return {"w": text, "start": start, "end": end, "conf": 0.9}


class GroupCuesTest(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(group_cues([]), [])

    def test_single_cue_joined_with_spaces(self):
        cues = group_cues([w("Hello", 0.0, 0.5), w("world.", 0.6, 1.0)])
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "Hello world.")
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertEqual(cues[0]["end"], 1.0)

    def test_silence_gap_breaks_cue(self):
        cues = group_cues([w("Before the break.", 0.0, 1.0), w("After it.", 3.5, 4.5)])
        self.assertEqual([c["text"] for c in cues], ["Before the break.", "After it."])
        self.assertEqual(cues[1]["start"], 3.5)

    def test_duration_cap_breaks_cue(self):
        # 12 words x ~0.5s each = 6s total; cap is 5s so at least two cues
        words = [w("word%d" % i, i * 0.5, i * 0.5 + 0.45) for i in range(12)]
        cues = group_cues(words)
        self.assertGreater(len(cues), 1)
        for cue in cues:
            self.assertLessEqual(cue["end"] - cue["start"], 5.0 + 0.001)

    def test_char_cap_breaks_cue(self):
        long_word = "x" * 40
        words = [w(long_word, 0.0, 0.4), w(long_word, 0.5, 0.9), w(long_word, 1.0, 1.4)]
        cues = group_cues(words)  # three 40-char words exceed 84-char cap
        self.assertEqual(len(cues), 2)

    def test_sentence_punctuation_breaks_after_full_clause(self):
        words = [
            w("This", 0.0, 0.2), w("is", 0.3, 0.4), w("one", 0.5, 0.6),
            w("sentence.", 0.7, 0.9), w("Next", 1.0, 1.2), w("one.", 1.3, 1.5),
        ]
        cues = group_cues(words)
        self.assertEqual([c["text"] for c in cues], ["This is one sentence.", "Next one."])

    def test_short_punctuation_does_not_break(self):
        words = [w("Yes.", 0.0, 0.2), w("Right?", 0.3, 0.5), w("Ok.", 0.6, 0.8)]
        cues = group_cues(words)
        self.assertEqual(len(cues), 1)

    def test_end_is_at_least_start(self):
        cues = group_cues([w("Hi", 5.0, 5.0)])
        self.assertGreaterEqual(cues[0]["end"], cues[0]["start"] + 0.001)

    def test_non_dict_junk_skipped(self):
        cues = group_cues(["junk", None, w("Fine.", 0.0, 0.5)])
        self.assertEqual(len(cues), 1)


if __name__ == "__main__":
    unittest.main()
