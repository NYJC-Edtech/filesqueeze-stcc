# stcc implementation plan (working notes)

Package = `stcc.py` CLI + pinned runtime/model artifacts, released as one zip.
FileSqueeze integration consumes the CLI only. Policy lives in FileSqueeze;
mechanics live here.

## Frozen contract

```
python stcc.py transcribe [--ffmpeg P] [--output-dir D] [--name N]
                          [--formats srt,txt,json] [--threads N] [--timeout S]
                          [--min-conf F] [--min-ram-gb F] VIDEO [VIDEO...]
python stcc.py info
python stcc.py --version
```

- VAD chunking ALWAYS on (phase-1: memory otherwise scales ~4.4 MB/audio-s;
  63 min ≈ 25 GB. With VAD: flat ~1.3 GB).
- Model/VAD/runtime resolved relative to stcc.py's own dir (bin/, models/).
- Exit codes: 0 ok | 1 other | 2 usage | 3 low RAM | 4 no audio stream
  | 5 component missing | 6 runtime failure | 7 timeout.
- Windows: CREATE_NO_WINDOW on all subprocesses (FileSqueeze runs headless).
- UTF-8 explicit writes; stdout reconfigured.

## Phase 2 checklist

- [x] Phase-1 spike (GO): findings.md
- [x] SHA256 pins: parakeet d74b4e85…, model f0796bf4…, silero 81604892…
- [x] stcc.py (3.9+ floor, stdlib only)
- [x] unittest suite — 28 tests green (cue heuristics, golden SRT, time fmt,
      info, extract args, pipeline w/ stub runtime, exit codes)
- [x] build_package.py → dist/stcc-0.1.0-win-x64-cpu.zip (sha256 e1190f16…)
- [x] E2E on this machine: info ok; 4-min video → 58 cues/489 words in 16.5s;
      SRT validated (well-formed, monotonic, indexed)
- [x] CI (ubuntu+windows × 3.9/3.13) + release workflow (tag v* → zip)
- [ ] GATE (user): E2E on a real .exe-blocked machine (whitelisted dir)

## Phase 3 (filesqueeze) — not started

deps_setup Dependency entry (zip URL+checksum, unpack to whitelisted binaries
dir); `[transcription]` config (enabled=false, stcc_path, threads); invoke via
[sys.executable, stcc.py, ...]; warn-and-continue on failure; output naming via
--output-dir/--name aligned with compressed_ convention; doctor surfaces
`stcc.py info`; stub-stcc tests.

## Deferred

CUDA/Vulkan variants, diarization (`parakeet-cli scene`), multilingual model,
VTT format, upstream --srt tracking.
