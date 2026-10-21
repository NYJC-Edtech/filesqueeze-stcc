# Phase 1 findings — Fluid Speech Mini as FileSqueeze video transcription step

Date: 2026-10-21. Machine: ICT dept workstation, 20 threads, 15.7 GB RAM, Windows, prod FileSqueeze 0.9.7 running.

## Verdict: GO

All three kill-switch questions passed:

1. **Accuracy** is good on real classroom audio (Singaporean-accented, unscripted teacher speech).
2. **Throughput** is far beyond requirement (6.5–13.8× real-time on CPU).
3. **Memory on long files** is bounded **when run with Silero VAD chunking** — which must therefore be the integration's only supported mode.

## Setup validated

- Runtime: [mudler/parakeet.cpp](https://github.com/mudler/parakeet.cpp) release **v0.6.1** win-x64 CPU zip (1.8 MB download, no build). Verified identical to commit `5c9b0fb`, the exact commit the model card was validated against — upstream release binaries usable as-is.
- Model: `fluid-speech-mini-q2k-q4k.gguf`, 347 MB, loads via stock `parakeet-cli info` (arch `tdt` confirmed).
- VAD: `silero-vad-f16.gguf`, 1.3 MB.
- Audio prep: `ffmpeg -vn -ac 1 -ar 16000` from the source mp4s.

## Measurements

| Sample | Audio | Threads | Mode | Wall | RTFx | Peak working set |
|---|---|---|---|---|---|---|
| Arenes tutorial 1 (first 4 min) | 240 s | 4 | none | 35.9 s | 6.69 | 3 638 MB |
| Arenes tutorial 1 (json run) | 240 s | 4 | none | 37.2 s | 6.46 | 3 638 MB |
| H1 EOY P2 Review (22 min) | 1 317 s | 4 | none | 126.6 s | 10.4 | 8 154 MB |
| H1 EOY P2 Review (22 min) | 1 317 s | 8 | none | 95.4 s | 13.81 | 8 558 MB |
| Arenes tutorial 2 (63 min) | 3 788 s | 4 | **VAD** | 322.0 s | 11.76 | **1 295 MB** |

### Memory scaling (no VAD) is the critical finding

Non-VAD peak working set grows with audio length: 240 s → 3.6 GB, 1 317 s → 8.2 GB (≈ 2.5 GB base + ~4.4 MB per audio-second). Extrapolated, a 63-minute file would need ~19–25 GB — over this machine's 15.7 GB. The model card's "~485 MB" figure only holds for ~15-second clips.

With `--vad --vad-model silero-vad-f16.gguf`, the 63-minute file peaked at **1.3 GB flat**. Conclusion: FileSqueeze must **always** run transcription with VAD chunking, regardless of clip length.

### Threading

8 threads beat 4 by ~33% (RTFx 13.8 vs 10.4) on this machine. Default 4 is a safe floor for slower colleague machines; expose threads as a config key.

## Transcript quality (qualitative)

*Arenes tutorial 1* (chemistry, benzene history):
> "…bring you through the story of uh benzene, okay, the whole key core concept of benzene is the idea of refineries. Okay, so uh, imagine about so few hundred years ago when technology makes you very primitive, right? … They figure out that the uh molecular formula is E take take six, six times, six carbon atom, six hydrogen atom. … is this dream of the snake biting its own tail?"

Lesson structure, Singlish-adjacent speech patterns ("Make sense so far", "right?"), and the Kekulé narrative all come through. Errors are the expected kind: formulas spoken aloud ("C six H six" → "E take take six"), occasional phrase garbles ("refineries" — likely "resonance"/"delocalisation").

*H1 EOY P2 Review*: clean — "…paper 2, question 3, A, part 3, on the definition of lattice energy…"

*Arenes tutorial 2* (63 min, VAD): coherent throughout; accuracy visibly drops in the tail where students talk over each other ("…I've seen it on Freddy Light. Yeah. Yeah…") — overlapping speech is the known weak spot. Acceptable: captions degrade where the audio itself is messy.

**User spot-check requested:** verify `arenes1` excerpt above against the actual lesson before sign-off.

## JSON output shape (feeds the SRT writer)

```json
{"text": "...", "frame_sec": 0.08,
 "words":  [{"w": "All", "start": 1.84, "end": 2.16, "conf": 0.652}, ...],
 "tokens": [{"id": 6222, "t": 1.84, "conf": 0.652}, ...]}
```

Per-word start/end/confidence — SRT cue generation (group words into ~3–5 s cues, break on gaps) is straightforward. Confidence also enables flagging low-confidence cues. 496 words for 4 min ≈ 124 wpm, sensible.

## Not tested / open items

- **No-VAD long-file probe deliberately skipped**: would push the prod machine into swap; the two-point scaling curve is sufficient.
- **Non-English content**: model is English-only. The "MT Exam Briefing" sample (likely Mother Tongue content) was not run — expect gibberish; transcription must stay opt-in per file/config.
- **Accuracy assessment is a read of the transcripts, not a human check against audio.**
- Slower colleague machines untested (huge headroom makes this low-risk).

## Implications for the speech-pack bundle (phase 2)

Bundle = `parakeet-cli.exe` (from 1.8 MB zip) + model (347 MB) + silero VAD (1.3 MB) ≈ 349 MB, CPU-only. Pin v0.6.1 or the exact release whose binaries match the model's validated commit.
