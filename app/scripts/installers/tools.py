"""Utility functions for dependency management — installers, checkers, helpers."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.atomic_io import read_json_dict
from app.core.system import resolve_project_root
from app.scripts.checksum_verifier import load_expected_checksums, verify_download_strict

# ─────────────────────────────────────────────────────────────────────────────
# Config and requirements helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_config():
    """Loads config.json from the project root (not the CWD)."""
    return read_json_dict(resolve_project_root() / "config.json")


def relax_requirements(src, dst):
    """Refactor utils: Relax strict torch deps"""
    with open(src) as f_in, open(dst, 'w') as f_out:
        for line in f_in:
            if line.strip().startswith('torch==') or line.strip().startswith('torchvision=='):
                line = line.replace('==', '>=')
            f_out.write(line)


# ─────────────────────────────────────────────────────────────────────────────
# Checkers
# ─────────────────────────────────────────────────────────────────────────────

def check_cargo():
    return shutil.which("cargo") is not None


def check_brew():
    return shutil.which("brew") is not None


def check_node():
    return shutil.which("node") is not None and shutil.which("npm") is not None


def check_cmake_ninja():
    return shutil.which("cmake") is not None and shutil.which("ninja") is not None


def check_xcode_tools():
    """Checks if Xcode Command Line Tools are installed (macOS only)"""
    if sys.platform != "darwin":
        return True
    try:
        # xcode-select -p prints the path if installed, or exits with error
        subprocess.check_call(["xcode-select", "-p"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Installers helpers
# ─────────────────────────────────────────────────────────────────────────────

def install_node_js():
    print("Installing Node.js via Homebrew...")
    try:
        subprocess.check_call(["brew", "install", "node"])
        return True
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Error installing Node.js: {e}")
        return False


def install_rust_toolchain():
    print("Installing Rust (cargo)...")
    import tempfile
    import urllib.request
    fd, tmp_name = tempfile.mkstemp(suffix=".sh")
    os.close(fd)
    rustup_path = Path(tmp_name)
    try:
        req = urllib.request.Request("https://sh.rustup.rs")
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 - literal https URL (sh.rustup.rs)
            rustup_path.write_bytes(resp.read())

        checksums = load_expected_checksums()
        checksum_key = "darwin_rustup" if sys.platform == "darwin" else "linux_rustup"
        # Fail-closed: an unknown or mismatching hash aborts the install rather
        # than executing an unverified shell script.
        if not verify_download_strict(rustup_path, checksums.get(checksum_key, "")):
            print(
                f"❌ rustup installer SHA256 mismatch or missing reference hash "
                f"(checksum key: {checksum_key}) — installation refusée."
            )
            return False

        rustup_path.chmod(0o755)
        subprocess.check_call([str(rustup_path), "-y"])

        # Add to current path for this session
        cargo_bin = Path.home() / ".cargo" / "bin"
        if cargo_bin.exists():
            os.environ["PATH"] = str(cargo_bin) + os.pathsep + os.environ["PATH"]
            print("Rust installed and added to PATH.")
            return True
        print("Error installing Rust: ~/.cargo/bin not found after rustup finished.")
    except Exception as e:
        print(f"Error installing Rust: {e}")
    finally:
        rustup_path.unlink(missing_ok=True)
    return False


def install_system_dependencies(check_only=False, startup=False):
    print("--- System Dependency Check (Homebrew) ---")
    missing = []
    for cmd in ["colmap", "ffmpeg", "cmake"]:
        if shutil.which(cmd) is None:
            missing.append(cmd)

    if sys.platform == "darwin":
        try:
             # Check for libomp and freeimage
             if subprocess.run(["brew", "list", "libomp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
                 missing.append("libomp")
             if subprocess.run(["brew", "list", "freeimage"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
                 missing.append("freeimage")
        except (subprocess.CalledProcessError, OSError):
            print("⚠️ Could not check brew packages (libomp/freeimage).")

    if not missing:
        print("✅ System dependencies present.")
        return True

    print(f"Missing: {', '.join(missing)}")
    if check_only:
        print("ℹ️ Audit mode: automatic installation skipped.")
        return False

    if shutil.which("brew") is None:
        print("ERROR: Homebrew required.")
        return False

    if startup:
        # Same y/n question as for missing engines; no answer means no.
        try:
            answer = input(f"\n>>> Install {', '.join(missing)} via Homebrew now? (y/n): ").strip().lower()
        except EOFError:
            return False
        if answer not in ("o", "y", "oui", "yes"):
            return False

    print("Installing via Homebrew...")
    try:
        if "colmap" in missing:
            subprocess.check_call(["brew", "install", "colmap"])
        if "ffmpeg" in missing:
            subprocess.check_call(["brew", "install", "ffmpeg"])
        if "cmake" in missing:
            subprocess.check_call(["brew", "install", "cmake"])
        if "libomp" in missing:
            subprocess.check_call(["brew", "install", "libomp"])
        if "freeimage" in missing:
            subprocess.check_call(["brew", "install", "freeimage"])
        return True
    except subprocess.CalledProcessError as e:
        print(f"System installation failed: {e}")
        return False
