import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stcc  # noqa: E402

CANNED = {
    "text": "Hello world. Second sentence here.",
    "frame_sec": 0.08,
    "words": [
        {"w": "Hello", "start": 0.0, "end": 0.5, "conf": 0.9},
        {"w": "world.", "start": 0.6, "end": 1.0, "conf": 0.9},
        {"w": "Second", "start": 1.1, "end": 1.4, "conf": 0.9},
        {"w": "sentence", "start": 1.5, "end": 1.8, "conf": 0.9},
        {"w": "here.", "start": 1.9, "end": 2.2, "conf": 0.9},
    ],
    "tokens": [],
}


def make_opts(argv):
    return stcc.build_parser().parse_args(argv)


class TranscribePipelineTest(unittest.TestCase):
    def test_writes_srt_and_txt_with_stub_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "lecture.mp4"
            video.write_bytes(b"fake")
            outdir = tmp_path / "out"
            opts = make_opts([
                "transcribe", str(video), "--output-dir", str(outdir),
                "--formats", "srt,txt", "--min-ram-gb", "0",
            ])
            with mock.patch.object(stcc, "extract_audio"), \
                 mock.patch.object(stcc, "run_parakeet", return_value=CANNED), \
                 mock.patch.object(stcc, "component_paths", return_value={}):
                summary = stcc.transcribe_one(video, opts)

            srt = (outdir / "lecture.srt").read_text(encoding="utf-8")
            txt = (outdir / "lecture.txt").read_text(encoding="utf-8")
            # 5 words, single sentence-break at "here." -> one cue
            self.assertIn("00:00:00,000 --> 00:00:02,200", srt)
            self.assertIn("Hello world. Second sentence here.", srt)
            self.assertEqual(txt.splitlines()[0], "Hello world. Second sentence here.")
            self.assertIn("1 cues / 5 words", summary)

    def test_min_conf_filters_words_before_grouping(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "lecture.mp4"
            video.write_bytes(b"fake")
            opts = make_opts([
                "transcribe", str(video), "--output-dir", str(tmp_path),
                "--formats", "txt", "--min-conf", "0.8", "--min-ram-gb", "0",
            ])
            filtered = [w for w in CANNED["words"] if w["conf"] >= 0.8]
            with mock.patch.object(stcc, "extract_audio"), \
                 mock.patch.object(stcc, "run_parakeet", return_value=dict(CANNED, words=filtered)), \
                 mock.patch.object(stcc, "component_paths", return_value={}):
                summary = stcc.transcribe_one(video, opts)
            self.assertIn("%d words" % len(filtered), summary)

    def test_min_ram_guard_blocks_before_any_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "lecture.mp4"
            video.write_bytes(b"fake")
            opts = make_opts([
                "transcribe", str(video), "--min-ram-gb", "99999",
            ])
            with mock.patch.object(stcc, "ram_gb", return_value={"total": 16.0, "available": 1.0}):
                with self.assertRaises(stcc.StccError) as ctx:
                    stcc.transcribe_one(video, opts)
            self.assertEqual(ctx.exception.exit_code, stcc.EXIT_LOW_RAM)


class ExtractArgsTest(unittest.TestCase):
    def test_extraction_is_16k_mono_pcm(self):
        args = stcc._extract_args(Path("in.mp4"), Path("out.wav"))
        joined = " ".join(args)
        self.assertIn("-vn", joined)
        self.assertEqual(args[args.index("-ar") + 1], "16000")
        self.assertEqual(args[args.index("-ac") + 1], "1")
        self.assertIn("pcm_s16le", joined)
        self.assertTrue(args[-1].endswith("out.wav"))


class MainTest(unittest.TestCase):
    def test_version_flag(self):
        with self.assertRaises(SystemExit) as ctx:
            stcc.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_missing_ffmpeg_reports_exit_5(self):
        with mock.patch.object(stcc.shutil, "which", return_value=None):
            code = stcc.main(["transcribe", "whatever.mp4"])
        self.assertEqual(code, stcc.EXIT_MISSING)


if __name__ == "__main__":
    unittest.main()
