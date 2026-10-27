#!/usr/bin/env python3
"""Pull CrowSplat's third-party assets from pinned npm releases.

    python3 macos/scripts/sync_assets.py            # icons + fonts (committed)
    python3 macos/scripts/sync_assets.py --viewer   # also the 3D viewer (build-time)

Icons:  Gravity UI icons (MIT), turned into template image sets so they take
        the text colour. Only the icons listed in ICONS are copied, under the
        app's own names, so the code never depends on the upstream names.
Fonts:  Geist and Geist Mono (SIL OFL 1.1), static weights.
Viewer: @playcanvas/supersplat-viewer (MIT) standalone bundle, hosted by
        Resources/Viewer/crow-viewer.html.
"""

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "CrowSplat" / "Resources"
ASSETS = RES / "Assets.xcassets"

GRAVITY = "@gravity-ui/icons@2.23.0"
GEIST = "geist@1.8.2"
VIEWER = "@playcanvas/supersplat-viewer@1.41.0"

# app name -> Gravity UI file
ICONS = {
    "add": "plus", "video": "video", "photo": "picture", "folder": "folder-open",
    "scene": "cube", "play": "play", "stop": "stop", "trash": "trash-bin",
    "external": "arrow-up-right-from-square", "export": "arrow-up-right", "settings": "gear",
    "search": "magnifier", "check": "check", "clock": "clock", "cpu": "cpu", "layers": "layers",
    "close": "xmark", "chevron.down": "chevron-down", "chevron.right": "chevron-right",
    "chevron.left": "chevron-left", "reset": "arrow-rotate-left", "eye": "eye", "more": "ellipsis",
    "install": "arrow-down-to-line", "clean": "broom-motion", "convert": "arrows-rotate-right",
    "upscale": "arrows-expand", "panorama": "globe", "film": "filmstrip", "log": "terminal",
    "warning": "triangle-exclamation", "done": "circle-check", "failed": "circle-xmark",
    "copy": "copy", "disk": "hard-drive", "sliders": "sliders", "camera": "camera",
    "trim": "scissors", "sharp": "aperture", "sphere": "sphere", "cubes": "cubes-3",
}

FONTS = ["Geist-Regular", "Geist-Medium", "Geist-SemiBold", "Geist-Bold",
         "GeistMono-Regular", "GeistMono-Medium"]


def npm_unpack(spec: str, into: Path) -> Path:
    tgz = subprocess.run(["npm", "pack", spec, "--silent"], cwd=into, check=True,
                         capture_output=True, text=True).stdout.strip().splitlines()[-1]
    out = into / tgz.removesuffix(".tgz")
    with tarfile.open(into / tgz) as tar:
        tar.extractall(out, filter="data")
    return out / "package"


def sync_icons(pkg: Path) -> None:
    target = ASSETS / "Icons"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    (target / "Contents.json").write_text(json.dumps(
        {"info": {"author": "xcode", "version": 1}, "properties": {"provides-namespace": True}}, indent=2))
    for name, src in ICONS.items():
        svg = (pkg / "svgs" / f"{src}.svg").read_text()
        # Asset catalogs ignore currentColor; template rendering recolours black.
        svg = svg.replace("currentColor", "#000")
        iset = target / f"{name}.imageset"
        iset.mkdir()
        (iset / f"{name}.svg").write_text(svg)
        (iset / "Contents.json").write_text(json.dumps({
            "images": [{"filename": f"{name}.svg", "idiom": "universal"}],
            "info": {"author": "xcode", "version": 1},
            "properties": {"preserves-vector-representation": True,
                           "template-rendering-intent": "template"},
        }, indent=2))
    shutil.copy(pkg / "LICENSE", RES / "Licenses" / "gravity-ui-icons.LICENSE")
    print(f"icons: {len(ICONS)}")


def sync_fonts(pkg: Path) -> None:
    target = RES / "Fonts"
    target.mkdir(parents=True, exist_ok=True)
    for name in FONTS:
        family = "geist-mono" if name.startswith("GeistMono") else "geist-sans"
        shutil.copy(pkg / "dist" / "fonts" / family / f"{name}.ttf", target / f"{name}.ttf")
    lic = next(p for p in pkg.rglob("*") if re.search(r"(OFL|LICENSE)", p.name) and p.is_file())
    shutil.copy(lic, RES / "Licenses" / "geist.OFL.txt")
    print(f"fonts: {len(FONTS)}")


def sync_viewer(pkg: Path) -> None:
    target = RES / "Viewer"
    for f in ("index.js", "index.css", "gsaf-decoder.wasm"):
        shutil.copy(pkg / "public" / f, target / f)
    shutil.copy(pkg / "LICENSE", RES / "Licenses" / "supersplat-viewer.LICENSE")
    print("viewer: ok")


def main() -> None:
    (RES / "Licenses").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        sync_icons(npm_unpack(GRAVITY, tmp))
        sync_fonts(npm_unpack(GEIST, tmp))
        if "--viewer" in sys.argv:
            sync_viewer(npm_unpack(VIEWER, tmp))


if __name__ == "__main__":
    main()
