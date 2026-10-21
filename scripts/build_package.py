#!/usr/bin/env python3
"""Assemble the stcc release package from pinned upstream artifacts.

Verifies SHA256 of each pinned artifact (downloading into artifacts/ only
when absent or mismatched), lays out dist/stcc/, writes MANIFEST.json and
LICENSES/, and zips to dist/stcc-<version>-win-x64-cpu.zip.

Usage: python scripts/build_package.py [--artifacts DIR] [--dist DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pins import PINS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PARAKEET_UNPACK_SUBDIR = "parakeet-v0.6.1-bin-win-cpu-x64"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_artifact(pin_key: str, artifacts: Path) -> Path:
    """Download the pinned artifact if absent/mismatched; verify checksum."""
    pin = PINS[pin_key]
    target = artifacts / pin["filename"]
    if target.exists() and sha256_of(target) == pin["sha256"]:
        print("ok (cached)  %s" % pin["filename"])
        return target
    if target.exists():
        print("checksum mismatch, re-downloading %s" % pin["filename"])
        target.unlink()
    print("downloading  %s" % pin["url"])
    last_error: Exception = RuntimeError("unreachable")
    for attempt in (1, 2, 3):
        try:
            with urllib.request.urlopen(pin["url"], timeout=300) as resp, open(target, "wb") as fh:
                shutil.copyfileobj(resp, fh, 1 << 20)
            break
        except Exception as exc:  # noqa: BLE001 - retry any network failure
            last_error = exc
            print("  attempt %d failed: %s" % (attempt, exc))
    else:
        raise SystemExit("download failed for %s: %s" % (pin["filename"], last_error))
    actual = sha256_of(target)
    if actual != pin["sha256"]:
        target.unlink()
        raise SystemExit(
            "sha256 mismatch for %s: expected %s, got %s (pins.py needs an update?)"
            % (pin["filename"], pin["sha256"], actual)
        )
    print("ok           %s" % pin["filename"])
    return target


def unpack_parakeet(zip_path: Path, artifacts: Path) -> Path:
    unpacked = artifacts / "parakeet-cli"
    exe = unpacked / PARAKEET_UNPACK_SUBDIR / "parakeet-cli.exe"
    if not exe.exists():
        print("unpacking parakeet runtime")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(unpacked)
    if not exe.exists():
        raise SystemExit("parakeet-cli.exe not found after unpack")
    return exe


def write_notice(dest: Path) -> None:
    dest.write_text(
        "stcc - speech-to-closed-captions\n"
        "================================\n\n"
        "This package bundles third-party components:\n\n"
        "1. parakeet.cpp runtime (bin/parakeet-cli.exe) - MIT License.\n"
        "   https://github.com/mudler/parakeet.cpp\n"
        "   Full text: LICENSES/parakeet.cpp-LICENSE\n\n"
        "2. Fluid Speech Mini GGUF model (models/fluid-speech-mini-q2k-q4k.gguf)\n"
        "   Copyright FluidVoice, licensed CC BY 4.0.\n"
        "   https://huggingface.co/FluidVoice-Labs/fluid-speech-mini-gguf\n"
        "   Required attribution when using this package:\n"
        '   "Fluid Speech Mini by FluidVoice"\n\n'
        "3. Silero VAD (models/silero-vad-f16.gguf) - MIT License.\n"
        "   https://github.com/snakers4/silero-vad\n\n"
        "Model weights are redistributed unmodified; checksums are recorded in\n"
        "MANIFEST.json. stcc itself is MIT licensed (see repository).\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts", default=str(REPO / "artifacts"))
    parser.add_argument("--dist", default=str(REPO / "dist"))
    args = parser.parse_args()
    artifacts = Path(args.artifacts)
    dist = Path(args.dist)
    artifacts.mkdir(parents=True, exist_ok=True)

    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    model_name = PINS["fluid_speech_mini"]["filename"]
    vad_name = PINS["silero_vad"]["filename"]

    # 1. artifacts: download-if-needed + verify all pins
    parakeet_zip = ensure_artifact("parakeet_cpp", artifacts)
    ensure_artifact("fluid_speech_mini", artifacts)
    ensure_artifact("silero_vad", artifacts)

    # 2. lay out dist/stcc
    pkg = dist / "stcc"
    if pkg.exists():
        shutil.rmtree(pkg)
    (pkg / "bin").mkdir(parents=True)
    (pkg / "models").mkdir()
    licenses = pkg / "LICENSES"
    licenses.mkdir()

    shutil.copyfile(REPO / "stcc.py", pkg / "stcc.py")
    shutil.copyfile(REPO / "VERSION", pkg / "VERSION")
    readme = REPO / "README.md"
    if readme.exists():
        shutil.copyfile(readme, pkg / "README.md")
    shutil.copyfile(unpack_parakeet(parakeet_zip, artifacts), pkg / "bin" / "parakeet-cli.exe")
    parakeet_license = (
        artifacts / "parakeet-cli" / PARAKEET_UNPACK_SUBDIR / "LICENSE"
    )
    shutil.copyfile(parakeet_license, licenses / "parakeet.cpp-LICENSE")
    shutil.copyfile(artifacts / model_name, pkg / "models" / model_name)
    shutil.copyfile(artifacts / vad_name, pkg / "models" / vad_name)
    write_notice(licenses / "NOTICE-stcc.txt")

    # 3. manifest
    manifest = {
        "name": "stcc",
        "version": version,
        "target": "win-x64-cpu",
        "components": {
            key: {
                "version": pin["version"],
                "source": pin["source"],
                "sha256": pin["sha256"],
                "license": pin["license"],
                **({"credit": pin["credit"]} if "credit" in pin else {}),
            }
            for key, pin in PINS.items()
        },
    }
    (pkg / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    # 4. zip
    zip_base = dist / ("stcc-%s-win-x64-cpu" % version)
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=str(dist), base_dir="stcc")
    print("\nbuilt %s" % archive)
    print("sha256 %s" % sha256_of(Path(archive)))
    for name in sorted(str(p.relative_to(pkg)) for p in pkg.rglob("*") if p.is_file()):
        print("  %s" % name)


if __name__ == "__main__":
    main()
