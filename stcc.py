#!/usr/bin/env python3
"""stcc - speech-to-closed-captions.

Turns a video file into SRT and/or plain-text captions using the bundled
Fluid Speech Mini GGUF model, run through the parakeet.cpp runtime with
Silero VAD chunking (always on: unbounded memory growth without it).

Standalone and stdlib-only (Python 3.9+). Meant to be invoked by FileSqueeze
or directly:

    python stcc.py transcribe --ffmpeg C:\\path\\ffmpeg.exe --output-dir out lecture.mp4
    python stcc.py info

Components (bin/parakeet-cli.exe, models/*.gguf) are resolved relative to
this script's directory, i.e. the released package layout.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_HOME = Path(__file__).resolve().parent

MODEL_RELPATH = Path("models") / "fluid-speech-mini-q2k-q4k.gguf"
VAD_RELPATH = Path("models") / "silero-vad-f16.gguf"
BIN_RELPATH = Path("bin") / ("parakeet-cli.exe" if os.name == "nt" else "parakeet-cli")

# exit codes (FileSqueeze maps any nonzero to warn-and-continue)
EXIT_OK = 0
EXIT_OTHER = 1
EXIT_USAGE = 2
EXIT_LOW_RAM = 3
EXIT_NO_AUDIO = 4
EXIT_MISSING = 5
EXIT_TRANSCRIBE = 6
EXIT_TIMEOUT = 7

# silence console flashes when the parent is a GUI process (pythonw)
_SUBPROCESS_KW: Dict[str, Any] = {}
if os.name == "nt":
    _SUBPROCESS_KW["creationflags"] = 0x08000000  # CREATE_NO_WINDOW


class StccError(Exception):
    def __init__(self, message: str, exit_code: int = EXIT_OTHER):
        super().__init__(message)
        self.exit_code = exit_code


def _read_version() -> str:
    try:
        return (_HOME / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0.dev"

VERSION = _read_version()

# cue-grouping heuristics (tuned against phase-1 JSON: ~124 wpm teacher speech)
GAP_BREAK_SEC = 0.9       # silence gap between words that ends a cue
MAX_CUE_SEC = 5.0         # hard duration cap
MAX_CUE_CHARS = 84        # 2 lines x 42
MIN_WORDS_SENTENCE = 4    # don't split on "."/"!" after 1-2 words
LINE_WIDTH = 42


# ---------------------------------------------------------------- components

def component_paths() -> Dict[str, Path]:
    paths = {
        "runtime": _HOME / BIN_RELPATH,
        "model": _HOME / MODEL_RELPATH,
        "vad": _HOME / VAD_RELPATH,
    }
    missing = [name for name, p in paths.items() if not p.exists()]
    if missing:
        raise StccError(
            "package component(s) missing: %s (looked under %s)" % (", ".join(missing), _HOME),
            EXIT_MISSING,
        )
    return paths


def read_manifest() -> Dict[str, Any]:
    try:
        return json.loads((_HOME / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------ system probing

def ram_gb() -> Dict[str, Optional[float]]:
    """Total/available RAM in GiB; values are None when unknowable."""
    if os.name == "nt":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return {"total": m.ullTotalPhys / 2**30, "available": m.ullAvailPhys / 2**30}
        return {"total": None, "available": None}
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, val = line.partition(":")
            info[key.strip()] = float(val.strip().split()[0]) / 2**20
        return {"total": info.get("MemTotal"), "available": info.get("MemAvailable")}
    except OSError:
        return {"total": None, "available": None}


def cpu_model() -> str:
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return str(name).strip()
        except OSError:
            return ""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return ""


def gpu_name() -> str:
    """Best-effort GPU description; never raises."""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name"],
                capture_output=True, text=True, timeout=10, **_SUBPROCESS_KW,
            )
            return (r.stdout or "").strip() if r.returncode == 0 else ""
        r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10, **_SUBPROCESS_KW)
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                if "VGA" in line or "3D controller" in line:
                    return line.partition(":")[2].strip()
        return ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ------------------------------------------------------------- cue building

def format_ts(seconds: float, ms_sep: str = ",") -> str:
    """Cue timestamp HH:MM:SS<ms_sep>mmm (negative inputs clamped to 0).

    Default separator ',' is SRT; WebVTT uses '.'.
    """
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    mnt, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, mnt, s, ms_sep, ms)


def group_cues(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group per-word timings into subtitle cues.

    Breaks on: inter-word silence > GAP_BREAK_SEC, cue longer than
    MAX_CUE_SEC, text wider than MAX_CUE_CHARS, or sentence-ending
    punctuation once the cue carries a full clause.
    """
    cues: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []

    def cur_text(extra: str = "") -> str:
        parts = [w.get("w", "") for w in cur]
        if extra:
            parts.append(extra)
        return " ".join(p for p in parts if p)

    def flush() -> None:
        nonlocal cur
        if not cur:
            return
        text = cur_text().strip()
        if text:
            start = float(cur[0].get("start", 0.0))
            end = max(float(cur[-1].get("end", start)), start + 0.001)
            cues.append({"start": start, "end": end, "text": text})
        cur = []

    for w in words:
        if not isinstance(w, dict) or "w" not in w:
            continue
        if cur:
            gap = float(w.get("start", 0.0)) - float(cur[-1].get("end", 0.0))
            projected = cur_text(w.get("w", ""))
            duration = float(w.get("end", 0.0)) - float(cur[0].get("start", 0.0))
            if gap > GAP_BREAK_SEC or duration > MAX_CUE_SEC or len(projected) > MAX_CUE_CHARS:
                flush()
        cur.append(w)
        if len(cur) >= MIN_WORDS_SENTENCE and re.search(r"[.!?][\"')\]]?$", w.get("w", "").rstrip()):
            flush()
    flush()
    return cues


def wrap_two_lines(text: str, width: int = LINE_WIDTH) -> str:
    """Balance caption text onto at most two lines."""
    if len(text) <= width:
        return text
    lines: List[str] = []
    for word in text.split():
        if not lines:
            lines.append(word)
            continue
        candidate = lines[-1] + " " + word
        if len(candidate) > width and len(lines) < 2:
            lines.append(word)
        else:
            lines[-1] = candidate
    return "\n".join(lines)


def render_srt(cues: List[Dict[str, Any]]) -> str:
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(
            "%d\n%s --> %s\n%s"
            % (i, format_ts(cue["start"]), format_ts(cue["end"]), wrap_two_lines(cue["text"]))
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def render_vtt(cues: List[Dict[str, Any]]) -> str:
    """WebVTT rendering of the same cue data as render_srt.

    Differences per spec: mandatory WEBVTT header and '.' as the
    millisecond separator. Numeric cue ids are valid VTT identifiers;
    line wrapping matches SRT exactly.
    """
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(
            "%d\n%s --> %s\n%s"
            % (i, format_ts(cue["start"], "."), format_ts(cue["end"], "."), wrap_two_lines(cue["text"]))
        )
    return "WEBVTT\n\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


def _write_text(path: Path, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


# ------------------------------------------------------------------ pipeline

def _extract_args(video: Path, wav: Path) -> List[str]:
    return [
        "-v", "error", "-y", "-i", str(video), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
    ]


def extract_audio(video: Path, wav: Path, ffmpeg: Path) -> None:
    """Extract 16 kHz mono WAV; raises EXIT_NO_AUDIO for silent videos."""
    probe = ffmpeg.with_name("ffprobe" + ffmpeg.suffix)
    if probe.exists():
        r = subprocess.run(
            [str(probe), "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, **_SUBPROCESS_KW,
        )
        if r.returncode == 0 and not (r.stdout or "").strip():
            raise StccError("no audio stream in %s" % video.name, EXIT_NO_AUDIO)
    r = subprocess.run(
        [str(ffmpeg)] + _extract_args(video, wav),
        capture_output=True, text=True, **_SUBPROCESS_KW,
    )
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if "does not contain any stream" in err:
            raise StccError("no audio stream in %s" % video.name, EXIT_NO_AUDIO)
        raise StccError("ffmpeg failed (%d): %s" % (r.returncode, err[-400:]), EXIT_TRANSCRIBE)
    if not wav.exists() or wav.stat().st_size <= 44:
        raise StccError("no audio produced from %s" % video.name, EXIT_NO_AUDIO)


def run_parakeet(comp: Dict[str, Path], wav: Path, threads: int,
                 min_conf: Optional[float], timeout: Optional[float]) -> Dict[str, Any]:
    cmd = [
        str(comp["runtime"]), "transcribe",
        "--model", str(comp["model"]), "--input", str(wav),
        "--threads", str(threads),
        "--vad", "--vad-model", str(comp["vad"]),
        "--json",
    ]
    if min_conf is not None:
        cmd += ["--min-local-conf", str(min_conf)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_SUBPROCESS_KW)
    except subprocess.TimeoutExpired:
        raise StccError("parakeet-cli timed out after %ss" % timeout, EXIT_TIMEOUT)
    if r.returncode != 0:
        raise StccError(
            "parakeet-cli failed (%d): %s" % (r.returncode, (r.stderr or "").strip()[-400:]),
            EXIT_TRANSCRIBE,
        )
    try:
        return json.loads(r.stdout)
    except ValueError as exc:
        raise StccError("unparseable runtime output: %s" % exc, EXIT_TRANSCRIBE)


def transcribe_one(video: Path, opts: argparse.Namespace) -> str:
    started = time.monotonic()
    ffmpeg_raw = opts.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg_raw:
        raise StccError("ffmpeg not found on PATH; pass --ffmpeg", EXIT_MISSING)
    ffmpeg = Path(ffmpeg_raw)
    if not video.exists():
        raise StccError("input not found: %s" % video, EXIT_USAGE)
    if opts.min_ram_gb > 0:
        mem = ram_gb()
        avail = mem.get("available")
        if avail is not None and avail < opts.min_ram_gb:
            raise StccError(
                "only %.1f GB RAM available, %s needs ~%.1f GB free (use --min-ram-gb 0 to override)"
                % (avail, video.name, opts.min_ram_gb),
                EXIT_LOW_RAM,
            )

    comp = component_paths()
    outdir = Path(opts.output_dir) if opts.output_dir else video.parent
    outdir.mkdir(parents=True, exist_ok=True)
    name = opts.name or video.stem
    formats = {f.strip().lower() for f in (opts.formats or "").split(",") if f.strip()}
    if not formats:
        raise StccError("no output formats selected (--formats)", EXIT_USAGE)

    with tempfile.TemporaryDirectory(prefix="stcc-") as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio(video, wav, ffmpeg)
        data = run_parakeet(comp, wav, opts.threads, opts.min_conf, opts.timeout or None)

    words = [w for w in (data.get("words") or []) if isinstance(w, dict)]
    cues = group_cues(words)
    written: List[str] = []
    if "srt" in formats:
        _write_text(outdir / ("%s.srt" % name), render_srt(cues))
        written.append(name + ".srt")
    if "vtt" in formats:
        _write_text(outdir / ("%s.vtt" % name), render_vtt(cues))
        written.append(name + ".vtt")
    if "txt" in formats:
        _write_text(outdir / ("%s.txt" % name), "\n".join(c["text"] for c in cues) + "\n")
        written.append(name + ".txt")
    if "json" in formats:
        _write_text(outdir / ("%s.json" % name), json.dumps(data, ensure_ascii=False))
        written.append(name + ".json")

    elapsed = time.monotonic() - started
    return "%s: wrote %s (%d cues / %d words) in %.1fs" % (
        video.name, ", ".join(written), len(cues), len(words), elapsed,
    )


# --------------------------------------------------------------------- info

def gather_info() -> Dict[str, Any]:
    mem = ram_gb()
    manifest = read_manifest()
    components = {}
    for key, label in (("parakeet_cpp", "runtime"), ("fluid_speech_mini", "model"), ("silero_vad", "vad")):
        entry = dict((manifest.get("components") or {}).get(key) or {})
        entry["present"] = {
            "runtime": _HOME / BIN_RELPATH,
            "model": _HOME / MODEL_RELPATH,
            "vad": _HOME / VAD_RELPATH,
        }[label].exists()
        components[key] = entry
    return {
        "version": VERSION,
        "python": platform.python_version(),
        "system": "%s %s" % (platform.system(), platform.release()),
        "cpu": cpu_model() or "unknown",
        "logical_cores": os.cpu_count(),
        "ram_total_gb": mem.get("total"),
        "ram_available_gb": mem.get("available"),
        "gpu": gpu_name() or "unknown",
        "components": components,
    }


def cmd_info(_opts: argparse.Namespace) -> int:
    info = gather_info()
    print("stcc %s" % info["version"])
    print("python %s on %s" % (info["python"], info["system"]))
    print("cpu: %s (%s logical cores)" % (info["cpu"], info["logical_cores"]))
    if info["ram_total_gb"] is not None:
        print("ram: %.1f GiB total, %.1f GiB available" % (info["ram_total_gb"], info["ram_available_gb"] or 0))
    else:
        print("ram: unknown")
    print("gpu: %s" % info["gpu"])
    all_present = True
    for key, entry in info["components"].items():
        state = "ok" if entry["present"] else "MISSING"
        all_present = all_present and entry["present"]
        print("component %s: %s (%s) %s" % (key, entry.get("version", "?"), entry.get("license", "?"), state))
    return EXIT_OK if all_present else EXIT_MISSING


# --------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stcc", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version="stcc " + VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribe", help="video in, SRT/txt captions out")
    t.add_argument("video", nargs="+", help="video file(s) to transcribe")
    t.add_argument("--ffmpeg", help="ffmpeg path (default: search PATH)")
    t.add_argument("--output-dir", help="where captions go (default: beside each video)")
    t.add_argument("--name", help="output basename override (default: video stem)")
    t.add_argument("--formats", default="srt,txt", help="comma list of srt,vtt,txt,json")
    t.add_argument("--threads", type=int, default=None, help="runtime threads (default: min(8, cores))")
    t.add_argument("--timeout", type=float, default=0, help="kill runtime after S seconds (default: never)")
    t.add_argument("--min-conf", type=float, default=None, help="drop words below this confidence (runtime --min-local-conf)")
    t.add_argument("--min-ram-gb", type=float, default=2.0, help="refuse if less free RAM (0 disables guard)")

    sub.add_parser("info", help="report machine capabilities and package components")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except AttributeError:
            pass

    opts = build_parser().parse_args(argv)

    if opts.cmd == "info":
        return cmd_info(opts)

    if opts.threads is None:
        opts.threads = min(8, os.cpu_count() or 4)

    failures = 0
    for raw in opts.video:
        try:
            print(transcribe_one(Path(raw), opts))
        except StccError as exc:
            print("stcc: error: %s" % exc, file=sys.stderr)
            failures = max(failures, exc.exit_code)
    return failures


if __name__ == "__main__":
    sys.exit(main())
