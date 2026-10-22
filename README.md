# filesqueeze-stcc (stcc)

**stcc — speech-to-closed-captions**: a standalone package that turns a video
file into SRT and plain-text captions using the Fluid Speech Mini GGUF model
via the parakeet.cpp runtime, with Silero VAD chunking (always on — without it
memory grows with audio length and long lessons exhaust RAM).

Built for FileSqueeze video transcription but deliberately standalone: any
system with Python 3.9+ (stdlib only, nothing to pip install) and a writable
output directory can use it.

## Package contents

Each release zip (`stcc-<version>-win-x64-cpu.zip`) contains:

```
stcc/
├── stcc.py                  # the CLI (the only entry point)
├── VERSION / MANIFEST.json  # version + pinned component checksums
├── bin/parakeet-cli.exe     # parakeet.cpp v0.6.1 runtime (win-x64, CPU)
├── models/fluid-speech-mini-q2k-q4k.gguf   # FluidVoice, CC BY 4.0
├── models/silero-vad-f16.gguf              # Silero VAD, MIT
└── LICENSES/                # bundled-component licenses + attribution
```

All component paths resolve relative to `stcc.py` itself — point FileSqueeze
at one path and everything else follows. Components must live in a directory
where exe execution is permitted (FileSqueeze's whitelisted binaries dir).

## Usage

```sh
# transcribe (writes <stem>.srt and <stem>.txt next to the video by default)
python stcc.py transcribe --ffmpeg C:\path\ffmpeg.exe --output-dir out lecture.mp4

# more options
python stcc.py transcribe --formats srt,vtt,txt,json --threads 8 --name mycaptions video.mp4

# machine + package report (for support / doctor integration)
python stcc.py info
python stcc.py --version
```

Key behaviors:

- **VAD chunking is always on.** Phase-1 measurement: peak RAM stays ~1.3 GB
  on a 63-minute video (vs ~25 GB projected without VAD).
- **Thread default** is `min(8, logical cores)`; override with `--threads`.
- **RAM guard**: refuses to start when less than `--min-ram-gb` (default 2.0)
  is available; `--min-ram-gb 0` disables.
- Output filenames default to the video stem; override with `--name`.
- On Windows all subprocesses run with `CREATE_NO_WINDOW` (safe under pythonw).

### Exit codes

| code | meaning |
|---|---|
| 0 | success |
| 1 | other error |
| 2 | usage / input not found |
| 3 | insufficient RAM (guard) |
| 4 | video has no audio stream |
| 5 | package component or ffmpeg missing |
| 6 | extraction/transcription runtime failure |
| 7 | runtime timeout (`--timeout`) |

Callers (FileSqueeze) treat any nonzero exit as warn-and-continue: the
compression already succeeded; captions are a bonus.

## Development

```sh
python -m unittest discover -s tests -v   # model-free unit tests
python scripts/build_package.py           # assemble dist/stcc-<v>-win-x64-cpu.zip
```

Pinned artifacts (URL + SHA256) live in `pins.py`; the build script verifies
checksums and re-downloads on mismatch. CI runs the unit suite on Linux and
Windows (Python 3.9 + 3.13); pushing a `v*` tag builds and publishes a release.

Findings from the phase-1 validation spike: `findings.md`.

## Licenses

- stcc scripts: MIT (FileSqueeze project)
- parakeet.cpp runtime: MIT — see `LICENSES/parakeet.cpp-LICENSE`
- Fluid Speech Mini model: CC BY 4.0 — attribution required:
  **"Fluid Speech Mini by FluidVoice"**
- Silero VAD: MIT
