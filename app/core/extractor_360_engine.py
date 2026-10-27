import logging
import os
import sys
from pathlib import Path

from .base_engine import BaseEngine
from .i18n import tr
from .system import compute_env, resolve_data_root

logger = logging.getLogger(__name__)


def get_venv_360_python():
    """Path to the Python executable of the dedicated ``.venv_360`` environment."""
    root = resolve_data_root()
    if sys.platform == "win32":
        return root / ".venv_360" / "Scripts" / "python.exe"
    return root / ".venv_360" / "bin" / "python"


# Plain "--flag value" parameters: params key -> CLI flag.
_VALUE_FLAGS = (
    ("interval", "--interval"),
    ("format", "--format"),
    ("resolution", "--resolution"),
    ("camera_count", "--camera-count"),
    ("quality", "--quality"),
    ("layout", "--layout"),
)


class Extractor360Engine(BaseEngine):
    """Runs the 360Extractor CLI from its dedicated venv.

    Installation and removal are handled by ``Extractor360EngineDep`` (see
    ``app.scripts.installers.extractor_360``), not by the runtime engine.
    """

    def __init__(self, logger_callback=None):
        super().__init__("360Extractor", logger_callback)
        self.root_dir = Path(resolve_data_root())
        self.engines_dir = self.root_dir / "engines"
        self.extractor_dir = self.engines_dir / "extractor_360"
        self.venv_python = Path(get_venv_360_python())
        self.script_path = self.extractor_dir / "src" / "main.py"

    def is_installed(self):
        """Checks if venv and script exist"""
        return self.venv_python.exists() and self.script_path.exists()

    def _build_cmd(self, safe_in, safe_out, params):
        """Assemble the CLI argv, mapping ``params`` onto the extractor's flags."""
        cmd = [
            self.venv_python,
            self.script_path,
            "--input", str(safe_in),
            "--output", str(safe_out),
        ]

        for key, flag in _VALUE_FLAGS:
            if key in params:
                cmd.extend([flag, str(params[key])])

        # AI options
        if params.get("ai_mask", False):
            cmd.append("--ai-mask")

        if params.get("ai_skip", False):
            cmd.append("--ai-skip")

        if params.get("adaptive", False):
            cmd.append("--adaptive")
            if "motion_threshold" in params:
                cmd.extend(["--motion-threshold", str(params["motion_threshold"])])
        return cmd

    def run_extraction(self, input_path, output_dir, params, progress_callback=None, log_callback=None, status_callback=None, check_cancel_callback=None):
        """
        Runs the extraction CLI.
        params: dict of arguments mirroring CLI args
        """
        if status_callback:
            status_callback(tr("status_extracting_360", "Extracting 360 images..."))
        if not self.is_installed():
            if log_callback:
                log_callback(tr("x360_log_not_installed", "Error: 360Extractor not installed."))
            return False

        safe_in = self.validate_path(input_path)
        safe_out = self.validate_path(output_dir)
        if safe_in is None:
            if log_callback:
                log_callback(tr("log_invalid_input_path", "SECURITY: Invalid input path: {name}").format(
                    name=os.path.basename(str(input_path))))
                logger.debug("Invalid input path: %s", input_path)
            return False
        if safe_out is None:
            if log_callback:
                log_callback(tr("log_invalid_output_dir", "SECURITY: Invalid output directory: {name}").format(
                    name=os.path.basename(str(output_dir))))
                logger.debug("Invalid output directory: %s", output_dir)
            return False

        cmd = self._build_cmd(safe_in, safe_out, params)

        if log_callback:
            # Use map(str, ...) to handle Path objects in the list
            log_callback(f"Command: {' '.join(map(str, cmd))}")

        # Run process
        # We use Popen to capture stdout/stderr for progress
        env = compute_env()
        # Isolate from the main app's PYTHONPATH to avoid package conflicts
        env.pop("PYTHONPATH", None)

        # Ensure all arguments are strings for subprocess
        cmd_str = [str(arg) for arg in cmd]

        # Use BaseEngine's Template Method for process execution
        def line_handler(line: str):
            if log_callback:
                log_callback(line)
            if "%" in line and progress_callback:
                try:
                    if "[" in line and "%]" in line:
                        part = line.split("[")[1].split("%]")[0]
                        progress_callback(int(part.strip()))
                except (ValueError, IndexError):
                    pass

        if status_callback:
            status_callback(tr("status_extracting_360", "Extracting 360 images..."))

        returncode = self._execute_command(cmd_str, env=env, cwd=str(self.extractor_dir), line_callback=line_handler)

        if check_cancel_callback and check_cancel_callback():
            if log_callback:
                log_callback(tr("x360_log_stopped", "Process stopped by user."))
            return False

        if status_callback and returncode == 0:
            status_callback(tr("status_ready", "Ready"))
        return returncode == 0
