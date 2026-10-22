"""Base classes for engine dependency management."""
import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.atomic_io import read_json_dict
from app.core.system import resolve_project_root


class EngineDependency:
    """Represents an external engine (Colmap, Glomap, Brush, etc.)"""
    auto_update_default = False  # Subclasses can override to enable auto-update by default
    ask_before_update = False    # If True, prompt user at startup before updating

    def on_startup_ready(self):
        """Called at startup when the engine is installed and up to date."""
        pass

    def __init__(self, name, repo_url=None, bin_name=None, pinned_ref=None):
        self.name = name
        self.repo_url = repo_url
        self.bin_name = bin_name
        # Tag or commit SHA this dependency is built from. None means "track the
        # default branch", which for a repo we compile and then execute means
        # running whatever upstream pushed since. Subclasses that build code
        # should always set it.
        self.pinned_ref = pinned_ref
        self.root = self.resolve_project_root()
        self.engines_dir = self.root / "engines"
        self.version_file = self.engines_dir / f"{name}.version"
        self.target_dir = self.engines_dir / name
        self.bin_path = self.engines_dir / (bin_name if bin_name else name)

    def resolve_project_root(self) -> Path:
        return resolve_project_root()

    def is_enabled_in_config(self, config: dict) -> bool:
        """SOLID-OCP: lets the engine decide whether it is active"""
        return config.get(f"{self.name}_enabled", True)

    def is_installed(self) -> bool:
        return self.bin_path.exists()

    def get_local_version(self) -> str:
        if self.version_file.exists():
            return self.version_file.read_text().strip()
        return ""

    def save_local_version(self, version: str):
        self.engines_dir.mkdir(parents=True, exist_ok=True)
        self.version_file.write_text(version)

    def get_remote_version(self) -> str:
        if not self.repo_url:
            return ""
        try:
            output = subprocess.check_output(
                ["git", "ls-remote", self.repo_url, "HEAD"], text=True, timeout=10
            ).strip()
            return output.split()[0] if output else ""
        except Exception as e:
            print(f"Warning: Failed to get remote version for {self.repo_url}: {e}")
            return ""

    def update_git(self):
        """Clone or update the repository, checking out `pinned_ref` when set.

        Without a pin this did `clone` then `pull` on the default branch, so the
        code that gets compiled and executed on the user's machine was whatever
        upstream had pushed that day. A moved tag is still trusted, but the
        version is at least declared, reviewable and reproducible.
        """
        if not self.repo_url:
            return
        self.engines_dir.mkdir(parents=True, exist_ok=True)

        if not self.target_dir.exists():
            print(f"Cloning {self.name}...")
            subprocess.check_call(["git", "clone", self.repo_url, str(self.target_dir)])
        else:
            print(f"Updating {self.name}...")
            subprocess.check_call(["git", "-C", str(self.target_dir), "fetch", "--tags", "--force"])

        if not self.pinned_ref:
            if self.target_dir.exists():
                subprocess.check_call(["git", "-C", str(self.target_dir), "pull"])
            return

        print(f"Checking out {self.name} at {self.pinned_ref}...")
        subprocess.check_call(
            ["git", "-C", str(self.target_dir), "checkout", "--force", self.pinned_ref]
        )

    def install(self) -> bool:
        """Install or update the engine; subclasses must override.

        Contract: return True on success, False on failure. Some legacy
        overrides still return None, so callers keep re-checking
        ``is_installed()`` afterwards. Not a strict ``abstractmethod``: the base
        class is instantiated directly for its shared helpers (version file,
        git handling), which an ABC would forbid.
        """
        raise NotImplementedError(f"{type(self).__name__}.install() is not implemented")

    def uninstall(self):
        """Standard uninstallation: remove target_dir and version file"""
        if self.target_dir.exists():
            print(f"Removing {self.target_dir}...")
            shutil.rmtree(str(self.target_dir))
        if self.version_file.exists():
            self.version_file.unlink()
        print(f"{self.name} uninstalled.")
        return True


class PipEngine(EngineDependency):
    """Engine installed via pip in a dedicated venv"""
    def __init__(self, name, repo_url, venv_name, pinned_ref=None):
        super().__init__(name, repo_url, pinned_ref=pinned_ref)
        self.venv_dir = self.root / venv_name
        self.python_bin = self.venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
        self.bin_path = self.python_bin # For pip engines, the python bin is the marker

    def is_installed(self) -> bool:
        return self.python_bin.exists()

    def create_venv(self, python_cmd=sys.executable):
        if self.venv_dir.exists() and not self.python_bin.exists():
            print(f"Broken venv detected at {self.venv_dir} (symlink or binary missing). Removing...")
            shutil.rmtree(str(self.venv_dir))

        if not self.venv_dir.exists():
            print(f"Creating venv: {self.venv_dir}")
            subprocess.check_call([python_cmd, "-m", "venv", str(self.venv_dir)])

        # Ensure pip is present (sometimes venv is created --without-pip on some systems)
        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.check_call([str(self.python_bin), "-m", "ensurepip", "--upgrade"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Upgrade pip
        try:
            subprocess.check_call(
                [str(self.python_bin), "-m", "pip", "install", "--upgrade", "pip", "--no-input"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"Warning: Failed to upgrade pip in {self.venv_dir}: {e}")

    def pip_install(self, args, cwd=None):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.check_call(
            [str(self.python_bin), "-m", "pip", "install"] + args + ["--no-input", "--progress-bar", "off"],
            env=env, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def uninstall(self):
        """Remove venv and target_dir"""
        if self.venv_dir.exists():
            print(f"Removing venv {self.venv_dir}...")
            shutil.rmtree(str(self.venv_dir))
        return super().uninstall()


class DependencyManager:
    def __init__(self, engines_dir: Path):
        self.engines_dir = engines_dir
        self.engines: dict[str, EngineDependency] = {}

    def register(self, engine: EngineDependency):
        self.engines[engine.name] = engine

    def get_config(self) -> dict:
        return read_json_dict(self.engines_dir.parent / "config.json")

    @staticmethod
    def _confirm_install(name: str) -> bool:
        """Asks before installing a missing engine at startup (L6-02).
        No answer (closed stdin) means no."""
        try:
            answer = input(f"\n>>> {name.capitalize()} is missing. Install now? (y/n): ").strip().lower()
        except EOFError:
            return False
        return answer in ("o", "y", "oui", "yes")

    @staticmethod
    def _run_install(engine: EngineDependency, fail_msg: str, ok_msg: str | None = None) -> bool:
        """Runs engine.install() and reports the outcome.

        install() reports most failures through a return value, not an exception
        (cf. BrushInstaller._install_from_release, which prints its error and
        returns False), so success is re-checked with is_installed() whenever
        ok_msg is given. Without ok_msg, only exceptions are reported.
        """
        try:
            engine.install()
        except Exception as e:
            print(f"{fail_msg}: {e}")
            return False
        if ok_msg is None:
            return True
        if engine.is_installed():
            print(ok_msg)
            return True
        print(f"{fail_msg}.")
        return False

    def _handle_missing(self, name: str, engine: EngineDependency, enabled: bool, check_only: bool, startup: bool) -> bool:
        """Installs (or skips) an engine that is not installed.
        Returns True if the engine is still missing and must be reported."""
        label = name.capitalize()
        if check_only:
            pass  # Just report status below
        elif startup and not self._confirm_install(name):
            # A disabled engine is offered too (it only gets installed on a
            # "y"); installing never touches its enabled flag in config.json.
            print(f"  ⏭️  {label}: installation skipped.")
            return False
        elif startup:
            print(f">>> Installing {label} on startup...")
            if self._run_install(engine, f"❌ Auto-install failed for {name}", f"✅ {label} installed automatically."):
                engine.on_startup_ready()
        else:
            print(f">>> Auto-installing missing engine [{name}]...")
            self._run_install(engine, f"❌ Auto-install failed for {name}")

        if engine.is_installed():
            return False
        if startup or check_only:
            print(f"  ❌ {label}: Missing")
        return True

    def _handle_update(
        self, name: str, engine: EngineDependency, config: dict, local: str, remote: str, check_only: bool, startup: bool
    ) -> None:
        """Handles an installed engine whose remote version differs from the local one."""
        label = name.capitalize()
        cfg_section = config.get("config", {})
        auto_update = (
            config.get(f"{name}_auto_update", engine.auto_update_default)
            or cfg_section.get(f"{name}_auto_update", engine.auto_update_default)
        )

        if startup and auto_update and not engine.ask_before_update:
            print(f">>> Auto-updating {label}...")
            self._run_install(engine, f"❌ Auto-update failed for {name}", f"✅ {label} updated.")
        elif startup:
            # Without auto-update, startup reports the new version and lets the user
            # decide; it used to fall through to the install-mode branch and update silently.
            print(f"\n>>> Mise à jour disponible pour {label} ({local} → {remote})")
            try:
                answer = input("    Mettre à jour maintenant ? (o/n) : ").strip().lower()
            except EOFError:
                answer = "n"
            if answer in ("o", "y", "oui", "yes"):
                print(f">>> Mise à jour de {label}...")
                self._run_install(engine, f"❌ Échec de la mise à jour de {name}", f"✅ {label} mis à jour.")
            else:
                print(f"    Mise à jour de {label} ignorée.")
        elif check_only:
            print(f"  ⚠️  {label}: Update available ({local} -> {remote})")
        else:
            print(f">>> Auto-updating {name} ({local} -> {remote})...")
            self._run_install(engine, f"❌ Auto-update failed for {name}")

    def main_install(self, check_only=False, startup=False):
        from app.scripts.installers.tools import install_system_dependencies

        print("--- System Dependency Check ---")
        install_system_dependencies(check_only=check_only, startup=startup)

        config = self.get_config()
        missing_engines_startup = False

        for name, engine in self.engines.items():
            # OCP: the engine decides whether it is active
            enabled = engine.is_enabled_in_config(config)

            # During --check or --startup, we audit everything. During install, we respect enablement.
            if not enabled and not (check_only or startup):
                continue

            remote = engine.get_remote_version()
            local = engine.get_local_version()
            # Normalize local version for comparison (strip build-mode suffixes like -source)
            local_clean = local.replace("-source", "") if local else local

            if not engine.is_installed():
                if self._handle_missing(name, engine, enabled, check_only, startup):
                    missing_engines_startup = True
            elif remote and local and remote != local_clean:
                self._handle_update(name, engine, config, local_clean, remote, check_only, startup)
            else:
                if startup:
                    engine.on_startup_ready()
                if check_only:
                    print(f"  ✅ {name.capitalize()}: Ready")

        if missing_engines_startup:
            print("\nℹ️  Note: some engines are still missing (see ❌ above).")
