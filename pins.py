"""Pinned upstream artifacts for the stcc package build.

Single source of truth for versions, download URLs and SHA256 digests.
build_package.py consumes this; update all three fields together when
bumping a component (and re-run the phase-1 validation for runtime/model bumps).
"""

PINS = {
    "parakeet_cpp": {
        "version": "0.6.1",
        "source": "https://github.com/mudler/parakeet.cpp",
        "url": "https://github.com/mudler/parakeet.cpp/releases/download/v0.6.1/parakeet-v0.6.1-bin-win-cpu-x64.zip",
        "sha256": "d74b4e857f75f91ae215c5e91ec42bf15ec84ed3a369423c134dbd6422243ed8",
        "filename": "parakeet-win-cpu-x64.zip",
        "license": "MIT",
    },
    "fluid_speech_mini": {
        "version": "q2k-q4k (2026-10)",
        "source": "https://huggingface.co/FluidVoice-Labs/fluid-speech-mini-gguf",
        "url": "https://huggingface.co/FluidVoice-Labs/fluid-speech-mini-gguf/resolve/main/fluid-speech-mini-q2k-q4k.gguf",
        "sha256": "f0796bf40274cc49d3db58563c23cd024b52ca7e2ae4749ccf27af85841726b5",
        "filename": "fluid-speech-mini-q2k-q4k.gguf",
        "license": "CC-BY-4.0",
        "credit": "Fluid Speech Mini by FluidVoice",
    },
    "silero_vad": {
        "version": "f16",
        "source": "https://github.com/snakers4/silero-vad",
        "url": "https://huggingface.co/mudler/parakeet-cpp-gguf/resolve/main/silero-vad-f16.gguf",
        "sha256": "8160489282352accc0e95925c2f6bf3d76fb8f7bccdce5c7e46808cb15e8443c",
        "filename": "silero-vad-f16.gguf",
        "license": "MIT",
    },
}
