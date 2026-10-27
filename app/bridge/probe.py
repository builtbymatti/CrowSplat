"""What this Mac has: hardware, the Homebrew tools and every engine.

Feeds the app's onboarding and settings. Each engine reports whether it is
installed, its version, whether the core flow needs it, and whether the app
can install it on its own (``installable``) or the user must act (Homebrew).
"""

import platform
import shutil
import subprocess

from app.core.system import (
    get_brush_build_mode,
    get_memory_info,
    is_apple_silicon,
    resolve_binary,
    resolve_data_root,
)

# Display order, role in the product, and what each engine is for.
# "core" engines are needed to turn a capture into a splat at all.
ENGINES = [
    ("colmap", "core", "Camera poses from your photos or video"),
    ("brush", "core", "Trains the Gaussian splat on the GPU"),
    ("splat-transform", "export", "Converts splats to SOG, SPZ and GLB"),
    ("sharp", "optional", "Turns a single photo into 3D (Apple ML Sharp)"),
    ("upscayl", "optional", "Upscales low-resolution input images"),
    ("extractor_360", "optional", "Splits 360° video into camera views"),
    ("four_dgs", "optional", "Prepares 4D (moving scene) datasets"),
]


def _version(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0][:80]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def _dependencies():
    from app.scripts.installers.brush import BrushEngineDep
    from app.scripts.installers.extractor_360 import Extractor360EngineDep
    from app.scripts.installers.four_dgs import FourDGSEngineDep
    from app.scripts.installers.mapping import ColmapBrewDep
    from app.scripts.installers.sharp import SharpEngineDep
    from app.scripts.installers.splat_transform import SplatTransformEngineDep
    from app.scripts.installers.upscayl import UpscaylEngineDep

    deps = [ColmapBrewDep(), BrushEngineDep(), SplatTransformEngineDep(), SharpEngineDep(),
            UpscaylEngineDep(), Extractor360EngineDep(), FourDGSEngineDep()]
    return {d.name: d for d in deps}


def probe() -> dict:
    deps = _dependencies()
    engines = []
    for name, role, purpose in ENGINES:
        dep = deps.get(name)
        installed = False
        version = ""
        if dep is not None:
            try:
                installed = bool(dep.is_installed())
                version = dep.get_local_version() if installed else ""
            except Exception:  # an installer probing a broken folder must not sink the probe
                installed = False
        if name == "colmap":
            path = resolve_binary("colmap")
            installed = path is not None
            version = _version([path, "-h"]).replace("COLMAP ", "").split(" ")[0] if path else ""
        engines.append({
            "id": name, "role": role, "purpose": purpose,
            "installed": installed, "version": version or "",
            # COLMAP comes from Homebrew; everything else the core can fetch.
            "installable": name != "colmap" or shutil.which("brew") is not None,
            "via": "homebrew" if name == "colmap" else "download",
        })

    memory = get_memory_info()
    brush_mode = ""
    try:
        brush_mode = get_brush_build_mode()
    except Exception:
        pass
    return {
        "machine": {
            "apple_silicon": is_apple_silicon(),
            "chip": _version(["sysctl", "-n", "machdep.cpu.brand_string"]),
            "macos": platform.mac_ver()[0],
            "memory_gb": round(memory.get("total", 0) / 1024**3, 1) if memory.get("total") else None,
        },
        "tools": {
            "homebrew": shutil.which("brew"),
            "ffmpeg": resolve_binary("ffmpeg"),
            "node": shutil.which("node"),
        },
        "engines": engines,
        "brush_build": brush_mode,
        "data_root": str(resolve_data_root()),
    }


def install(name: str, channel) -> bool:
    """Install one engine, streaming the installer's output as log lines."""
    if name == "colmap":
        brew = shutil.which("brew")
        if not brew:
            channel.log("Homebrew is required for COLMAP: https://brew.sh", level="error")
            return False
        missing = [p for p in ("colmap", "ffmpeg") if resolve_binary(p) is None]
        if not missing:
            return True
        channel.status(f"brew install {' '.join(missing)}")
        proc = subprocess.Popen([brew, "install", *missing], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            channel.status(line.strip()[:120])
            channel.log(line.rstrip())
        return proc.wait() == 0 and resolve_binary("colmap") is not None

    dep = _dependencies().get(name)
    if dep is None:
        channel.log(f"Unknown engine: {name}", level="error")
        return False
    if dep.is_installed():
        return True
    channel.status(f"Installing {name}")
    try:
        dep.install()
    except Exception as e:  # installers raise anything from git to pip
        channel.log(f"{name}: {e}", level="error")
        return False
    return bool(dep.is_installed())
