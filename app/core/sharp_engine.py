import functools
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .base_engine import BaseEngine
from .i18n import tr
from .media import conversion_suffix, convert_image, needs_image_conversion, without_hwaccel
from .system import compute_env, resolve_binary, resolve_project_root, use_videotoolbox


@functools.cache
def _venv_supports_mps(python: str) -> bool | None:
    """Ask the Sharp venv's PyTorch whether the Metal (MPS) backend works.

    Cached per interpreter: importing torch takes a few seconds. Returns
    None when the probe could not run, so the caller keeps the requested
    device rather than downgrading on a mere probe failure.
    """
    try:
        result = subprocess.run(
            [python, "-c",
             "import sys, torch; sys.exit(0 if torch.backends.mps.is_available() else 3)"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 3:
        return False
    return None

# Sharp runs inference one image at a time, and slowly: the reference figure
# comes from tests/integration/test_e2e_sharp.py on Apple Silicon. Used only to
# warn the user up front — a 300-frame video is roughly a twelve-hour run.
SECONDS_PER_FRAME_ESTIMATE = 142.0

# Above this estimate, ask before starting rather than committing the machine.
LONG_RUN_CONFIRM_SECONDS = 30 * 60


def _format_duration(seconds: float) -> str:
    """Render a duration as `Xh YYmin` or `Ymin`, for log lines."""
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


class SharpEngine(BaseEngine):
    """Execution engine for Apple ML Sharp."""

    def __init__(self, logger_callback=None):
        super().__init__("Sharp", logger_callback)
        self.process = None

    def _get_sharp_cmd(self):
        """Return the argv able to run Sharp, or None when it is not installed.

        There used to be a final `[sys.executable, "-m", "sharp.cli"]` fallback.
        That is the *main* venv's Python (3.13), while Sharp requires 3.11 in
        .venv_sharp, so it could only ever raise a bare ModuleNotFoundError in
        the middle of a run. Returning None lets the caller say "Sharp is not
        installed" instead.
        """
        # 1. Dedicated .venv_sharp environment
        root_dir = resolve_project_root()
        sharp_venv_bin = root_dir / ".venv_sharp" / "bin"

        sharp_bin = sharp_venv_bin / "sharp"
        if sharp_bin.exists() and os.access(sharp_bin, os.X_OK):
            return [str(sharp_bin)]

        # The venv's own interpreter can run the module even without the wrapper.
        sharp_python = sharp_venv_bin / "python3"
        if sharp_python.exists() and os.access(sharp_python, os.X_OK):
            return [str(sharp_python), "-m", "sharp.cli"]

        # 2. A 'sharp' wrapper next to the running interpreter (main venv)
        venv_bin = Path(sys.executable).parent
        sharp_bin = venv_bin / "sharp"
        if sharp_bin.exists() and os.access(sharp_bin, os.X_OK):
            return [str(sharp_bin)]

        # 3. Anything named 'sharp' on PATH
        found = shutil.which("sharp")
        if found:
            return [found]

        return None

    def _mps_usable(self) -> bool:
        """False only when the Sharp venv's PyTorch positively lacks MPS."""
        python = resolve_project_root() / ".venv_sharp" / "bin" / "python3"
        if not (python.exists() and os.access(python, os.X_OK)):
            return True  # nothing to probe; let Sharp report its own error
        return _venv_supports_mps(str(python)) is not False

    def is_installed(self):
        """Report whether Sharp can actually be launched.

        Defined as "`_get_sharp_cmd()` found a runnable command" so the two can
        no longer disagree. The previous version accepted a `.venv_sharp/bin/sharp`
        that existed without being executable, and accepted an importable `sharp`
        module in the main venv that `_get_sharp_cmd` would never have used.
        """
        return self._get_sharp_cmd() is not None

    def predict(self, input_path, output_path, params=None):
        """
        Run the Sharp prediction.
        params: dict of prediction parameters
        """
        params = params or {}
        cmd = self._get_sharp_cmd()
        if cmd is None:
            self.log(tr("sharp_log_not_installed", "Sharp is not installed (.venv_sharp not found)."))
            return -1

        cmd.extend(["predict"])
        # Validate and resolve paths
        safe_input = self.validate_path(input_path)
        safe_output = self.validate_path(output_path)
        if safe_input is None:
            self.log(tr("log_invalid_input_path", "SECURITY: Invalid input path: {name}").format(
                name=os.path.basename(str(input_path))))
            return -1
        if safe_output is None:
            self.log(tr("log_invalid_output_path", "SECURITY: Invalid output path: {name}").format(
                name=os.path.basename(str(output_path))))
            return -1

        # Sharp reads through Pillow, which has no HEIF decoder: convert the
        # iPhone-style formats into a throwaway PNG instead of failing.
        staging = None
        if safe_input.is_file() and needs_image_conversion(safe_input):
            staging = Path(tempfile.mkdtemp(prefix="sharp_in_"))
            converted = staging / (safe_input.stem + conversion_suffix("png"))
            if convert_image(safe_input, converted, "png"):
                self.log(tr(
                    "sharp_log_converted_png",
                    "🔄 {name} converted to PNG - format not readable by Sharp. The original is not modified.",
                ).format(name=safe_input.name))
                safe_input = converted
            else:
                shutil.rmtree(staging, ignore_errors=True)
                staging = None
                self.log(tr("sharp_log_convert_failed", "⚠️ Conversion impossible: {name}").format(name=safe_input.name))

        cmd.extend(["-i", str(safe_input)])
        cmd.extend(["-o", str(safe_output)])

        checkpoint = params.get("checkpoint")
        if checkpoint:
            safe_ckpt = self.validate_path(checkpoint)
            if safe_ckpt:
                cmd.extend(["-c", str(safe_ckpt)])
            else:
                self.log(tr("log_invalid_checkpoint_path", "SECURITY: Invalid checkpoint path: {name}").format(
                    name=os.path.basename(str(checkpoint))))

        device = params.get("device", self.device)
        if device == "mps" and not self._mps_usable():
            self.log(tr(
                "sharp_log_mps_unusable",
                "⚠️ The Apple GPU (MPS) cannot be used by the PyTorch in .venv_sharp - "
                "computing on the CPU (cpu), which is slower.",
            ))
            device = "cpu"
        if device and device != "default":
            cmd.extend(["--device", device])

        if params.get("verbose"):
            cmd.append("--verbose")

        env = compute_env()
        # Operations PyTorch has not ported to Metal yet run on the CPU
        # instead of aborting the whole prediction.
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

        # Ensure all args are strings for Popen
        cmd = [str(arg) for arg in cmd]

        self.log(tr("sharp_log_launch", "Launching Sharp: {cmd}").format(cmd=self._redact_cmd(cmd)))

        # GoF Template Method: delegation to the runner
        try:
            return self._execute_command(cmd, env=env)
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    def _extract_frames(self, vp, frames_dir, skip, log_callback):
        """Run ffmpeg over the video, returning its exit code.

        Retries in software when VideoToolbox refuses the stream (ProRes,
        10-bit HEVC in a .mov) rather than rejecting the container outright.
        """
        ffmpeg_bin = resolve_binary("ffmpeg") or "ffmpeg"

        ffmpeg_cmd = [ffmpeg_bin]
        if use_videotoolbox(ffmpeg_bin):
            ffmpeg_cmd.extend(["-hwaccel", "videotoolbox"])
        ffmpeg_cmd.extend([
            "-y", "-i", str(vp),
            "-vf", f"select=not(mod(n\\,{skip}))",
            # ``-fps_mode`` replaced ``-vsync`` in FFmpeg 5.1; FFmpeg 9 removed
            # the old flag entirely ("Unrecognized option 'vsync'").
            "-fps_mode", "vfr", "-q:v", "1",
            str(frames_dir / "frame_%04d.png"),
        ])

        if log_callback:
            log_callback(f"Running: {' '.join(ffmpeg_cmd)}")

        # Delegation to the runner (Template Method): the extraction stays
        # cancellable through self.stop() / self.runner.terminate().
        extraction_log = []

        def _ffmpeg_line(line_str):
            extraction_log.append(line_str)
            if log_callback:
                log_callback(line_str)

        returncode = self._execute_command(ffmpeg_cmd, line_callback=_ffmpeg_line, timeout=3600)

        if returncode != 0 and "-hwaccel" in ffmpeg_cmd and not self.stop_requested:
            if log_callback:
                log_callback(tr("log_hwdecode_retry", "Hardware decoding refused - retrying in software"))
            returncode = self._execute_command(
                without_hwaccel(ffmpeg_cmd), line_callback=_ffmpeg_line, timeout=3600
            )

        if returncode != 0 and not self.stop_requested and log_callback:
            log_callback(f"FFmpeg error (code {returncode}): {' | '.join(extraction_log[-5:])}")
        return returncode

    def _confirm_long_run(self, total_frames, log_callback, confirm_callback):
        """Ask before a long sequential run. True when processing may start.

        Sharp infers one frame at a time, so a few hundred frames is hours.
        Without a confirm_callback — every CLI caller — it proceeds.
        """
        estimated_seconds = total_frames * SECONDS_PER_FRAME_ESTIMATE
        if log_callback:
            log_callback(tr(
                "sharp_log_estimated_duration",
                "Estimated duration: {duration} ({frames} images × ~{secs:.0f} s, sequential inference).",
            ).format(duration=_format_duration(estimated_seconds), frames=total_frames,
                     secs=SECONDS_PER_FRAME_ESTIMATE))
        if confirm_callback and estimated_seconds >= LONG_RUN_CONFIRM_SECONDS:
            return bool(confirm_callback(total_frames, estimated_seconds))
        return True

    def _predict_one_frame(self, frame_path, out, params, log_callback):
        """Run Sharp on one frame and collect its PLY. True when one was saved."""
        # Only ever write to a path that does not exist yet: frame_out_dir is
        # deleted after each frame, and a name collision with a folder of the
        # user's would otherwise have it deleted along with its contents.
        frame_out_dir = out / frame_path.stem
        collision = 1
        while frame_out_dir.exists():
            frame_out_dir = out / f"{frame_path.stem}_sharp_{collision}"
            collision += 1

        saved = False
        try:
            if self.predict(str(frame_path), str(frame_out_dir), params) == 0:
                ply_files = list(frame_out_dir.rglob("*.ply"))
                if ply_files:
                    dest_ply = out / f"{frame_path.stem}.ply"
                    shutil.copy2(ply_files[0], dest_ply)
                    if log_callback:
                        log_callback(tr("sharp_log_saved", "Saved: {name}").format(name=dest_ply.name))
                    saved = True
        finally:
            if frame_out_dir.exists():
                shutil.rmtree(frame_out_dir)
        return saved

    def process_video_frames(self, video_path: str, output_dir: str,
                             params: dict | None = None,
                             log_callback: Callable | None = None,
                             status_callback: Callable | None = None,
                             progress_callback: Callable | None = None,
                             cancel_check: Callable | None = None,
                             confirm_callback: Callable | None = None) -> int:
        """Extract a video's frames, run Sharp on each, collect the PLYs.

        Orchestration only: extraction, the long-run confirmation and the
        per-frame inference each live in their own method. Every early exit
        removes the temporary frames, so an abort leaves nothing behind.

        Parameters
        ----------
        video_path: str
            Path to the input video file.
        output_dir: str
            Directory where the output PLY files are placed.
        params: dict, optional
            Sharp parameters (skip_frames, etc.).
        log_callback: callable, optional
            Called with each log message.
        status_callback: callable, optional
            Called with status updates.
        progress_callback: callable, optional
            Called with an integer percentage (0-100).
        cancel_check: callable, optional
            Called before each frame; if True, processing stops. stop() is
            honoured at the same points, whether or not this is given.
        confirm_callback: callable, optional
            Called as confirm_callback(total_frames, estimated_seconds) once the
            frame count is known, before any inference. Returning False aborts.
            Omitted, it proceeds — CLI callers are non-interactive.

        Returns
        -------
        int
            Number of successfully processed frames.
        """
        params = params or {}
        skip = max(1, int(params.get("skip_frames", 1)))

        vp = Path(video_path)
        out = Path(output_dir)

        # A unique temp dir, not a fixed "temp_frames" name: a same-named folder
        # already present in the user-chosen output dir must never be rmtree'd.
        # Only the dir actually created here is ever removed.
        out.mkdir(parents=True, exist_ok=True)
        frames_dir = Path(tempfile.mkdtemp(prefix="corbeausplat_sharp_", dir=out))

        def _abort(message=None):
            if message and log_callback:
                log_callback(message)
            shutil.rmtree(frames_dir, ignore_errors=True)
            return 0

        returncode = self._extract_frames(vp, frames_dir, skip, log_callback)
        if self.stop_requested:
            return _abort(tr("log_stopped_by_user", "--- Stopped by user ---"))
        if returncode != 0:
            return _abort()

        frames = sorted(frames_dir.glob("*.png"))
        total_frames = len(frames)
        if total_frames == 0:
            return _abort(tr("sharp_log_no_frames", "No frames extracted."))
        if log_callback:
            log_callback(tr("sharp_log_total_frames", "Total frames extracted: {n}").format(n=total_frames))

        if not self._confirm_long_run(total_frames, log_callback, confirm_callback):
            return _abort(tr("log_cancelled_before_start", "--- Cancelled before start ---"))

        success_count = 0
        # try/finally: an exception from one frame (disk full on copy2...)
        # must not strand the extracted frames in the output folder.
        try:
            for idx, frame_path in enumerate(frames):
                # stop() sets stop_requested without going through cancel_check —
                # testing only the latter left stop() unable to interrupt the loop.
                if self.stop_requested or (cancel_check and cancel_check()):
                    if log_callback:
                        log_callback(tr("log_stopped_by_user", "--- Stopped by user ---"))
                    break

                display_idx = idx + 1
                if status_callback:
                    status_callback(tr("sharp_status_frame", "Processing frame {idx}/{total}").format(
                        idx=display_idx, total=total_frames))
                if log_callback:
                    log_callback(tr("sharp_log_frame", "Processing frame {idx}/{total}: {name}").format(
                        idx=display_idx, total=total_frames, name=frame_path.name))

                if self._predict_one_frame(frame_path, out, params, log_callback):
                    success_count += 1

                if progress_callback:
                    progress_callback(int((display_idx / total_frames) * 100))
        finally:
            shutil.rmtree(frames_dir, ignore_errors=True)

        return success_count

