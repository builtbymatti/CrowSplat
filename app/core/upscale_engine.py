"""
upscale_engine.py — Thin wrapper around the upscayl-bin CLI.

No Python venv required. upscayl-bin is a standalone NCNN-based binary.
"""
import shutil
import tempfile
from pathlib import Path

from app.upscayl_models import get_model

from .base_engine import BaseEngine
from .i18n import tr
from .media import IMAGE_EXTENSIONS, convert_image


class UpscaleEngine(BaseEngine):

    def __init__(self, logger_callback=None):
        super().__init__("Upscale", logger_callback)

    def _binary(self) -> Path | None:
        from app.upscayl_manager import find_binary
        return find_binary()

    # ----------------------------------------------------------------- public

    def is_installed(self) -> bool:
        return self._binary() is not None

    def load_model(self, model_id="realesrgan-x4plus", scale=4,
                   output_format="png", tile=0, tta=False,
                   compression=0) -> dict | None:
        """Returns a params dict used by upscale_image/upscale_folder.

        The model_id is passed through unchanged; *scale* reaches upscayl-bin
        as -s and is what governs the output size.

        If *tile* is 0 (auto-detect), the tile size is adapted to available
        system memory to avoid swapping on low-RAM Apple Silicon systems:
          - < 8 GB total  → tile=256 (conservative)
          - 8-16 GB total  → tile=512 (balanced)
          - ≥ 16 GB total  → tile=1024 (large but still tiled)
        Memory pressure > 80% reduces tile by one step.

        tile=0 (no tiling at all) is never used here: on unified-memory Apple
        Silicon, processing a large image in one pass can exceed the GPU's
        working set and crash upscayl-bin with SIGBUS, even when system RAM
        looks abundant.
        """
        if not self.is_installed():
            self.log(tr("up_err_no_binary", "upscayl-bin not found."))
            return None
        # The model name is passed through untouched. There used to be a
        # substitution here that rewrote "x4" into the requested scale, so
        # "realesrgan-x4plus" at scale 2 became "realesrgan-2plus" — a model that
        # does not exist, and upscayl_manager then refused with "Modèle
        # introuvable". ncnn models have a fixed native scale; the requested
        # scale goes to upscayl-bin via -s, which resamples on its own.

        # --- Adaptive tile size based on available RAM ---
        if tile == 0:
            from .system import get_memory_info
            mem = get_memory_info()
            total_gb = mem.get("total", 0) / (1024 ** 3)
            pressure = mem.get("percent", 0.0)

            if total_gb < 8:
                tile = 256
            elif total_gb < 16:
                tile = 512
            else:
                tile = 1024  # plenty of RAM, but still tiled to protect GPU memory

            # Under high memory pressure, reduce tile to avoid swap
            if pressure > 80:
                tile = max(128, tile // 2)
                self.log(tr(
                    "up_log_memory_pressure",
                    "⚠️ Memory under pressure ({pressure}%) - tile reduced to {tile}px to avoid swapping.",
                ).format(pressure=pressure, tile=tile))

            self.log(tr(
                "up_log_adaptive_tile",
                "🧠 {gb:.0f} GB RAM - adaptive tile: {tile}px (memory pressure: {pressure}%)",
            ).format(gb=total_gb, tile=tile, pressure=pressure))

        return {
            "model_id": model_id, "scale": scale,
            "output_format": output_format, "tile": tile,
            "tta": tta, "compression": compression,
        }

    def upscale_image(self, input_path, output_path, upsampler) -> bool:
        """
        upsampler — dict returned by load_model().
        upscayl-bin works on folders; we use a temp dir for single-image calls.
        """
        if not upsampler:
            return False
        safe_in = self.validate_path(input_path)
        if safe_in is None:
            self.log(tr("log_invalid_input_path", "SECURITY: Invalid input path: {name}").format(name=input_path))
            return False
        safe_out = self.validate_path(output_path)
        if safe_out is None:
            self.log(tr("log_invalid_output_path", "SECURITY: Invalid output path: {name}").format(name=output_path))
            return False
        with tempfile.TemporaryDirectory() as tmp_in:
            shutil.copy2(safe_in, Path(tmp_in) / safe_in.name)
            safe_out.parent.mkdir(parents=True, exist_ok=True)
            success, _ = self.upscale_folder(
                input_dir=tmp_in,
                output_dir=str(safe_out.parent),
                **upsampler,
            )
            return success

    def upscale_folder(self, input_dir, output_dir,
                       model_id="realesrgan-x4plus", scale=4,
                       output_format="png", tile=0, tta=False,
                       compression=0, custom_scale=None,
                       cancel_check=None) -> tuple:
        if not model_id:
            return False, tr("up_err_no_model", "No model selected.")
        # Validate paths
        safe_in = self.validate_path(input_dir)
        safe_out = self.validate_path(output_dir)
        if safe_in is None:
            self.log(tr("log_invalid_input_dir", "SECURITY: Invalid input directory: {name}").format(name=input_dir))
            return False, tr("up_err_input_path", "Input path not allowed.")
        if safe_out is None:
            self.log(tr("log_invalid_output_dir", "SECURITY: Invalid output directory: {name}").format(name=output_dir))
            return False, tr("up_err_output_path", "Output path not allowed.")
        from app.upscayl_manager import run_upscayl
        params = {
            "model_id":    model_id,
            "scale":       custom_scale or scale,
            "format":      output_format,
            "tile":        tile,
            "tta":         tta,
            "compression": compression,
        }
        result = [False]
        run_upscayl(input_dir, str(safe_out), params,  # pass original input_dir to run_upscayl (validated)
                    log_callback=self.log,
                    done_callback=lambda ok: result.__setitem__(0, ok),
                    cancel_check=cancel_check)
        if result[0]:
            return True, tr("up_msg_complete", "Upscale complete.")
        return False, tr("up_err_failed", "Upscale failed.")


def run_upscale_job(input_path, output_dir, params, log_callback, cancel_check):
    """Run an upscayl-bin upscale and return ``(success, message)``.

    Extracted from :class:`LocalUpscaleWorker`'s body to be shared with
    :class:`UpscaleImagesWorker` (OPTIONS "Upscale" step): both need exactly
    the same invocation (x1 mode = upscale then resize back to original size,
    folder or single file), only their destination differs.
    """
    import tempfile as _tempfile

    from app.upscayl_manager import find_binary, resize_to_original, run_upscayl

    model_id = params.get("model_id", "")
    if not model_id:
        return False, tr("up_err_no_model", "No model selected.")
    if not find_binary():
        return False, tr("up_err_no_binary", "upscayl-bin not found.")

    fmt = params.get("format", "png")
    req_scale = params.get("scale", 4)
    src = Path(input_path)

    x1_mode = (req_scale == 1)
    if x1_mode:
        m = get_model(model_id)
        actual_scale = m.scale if m else 4
    else:
        actual_scale = req_scale

    upscayl_params = {
        "model_id":    model_id,
        "scale":       actual_scale,
        "format":      fmt,
        "tile":        params.get("tile", 0),
        "tta":         params.get("tta", False),
        "compression": params.get("compression", 0),
    }

    # Stage every source image under a name that already carries the model
    # and scale used (<stem>_<model_id>_x<scale>.<fmt>) *before* upscayl-bin
    # ever runs. This guarantees the output file can never collide with —
    # and so never silently overwrite — an existing file, including the
    # original itself when input and output folders happen to be the same.
    suffix = f"_{model_id}_x{req_scale}"
    # Recursive on purpose: the chain's previous step may nest its images
    # (360Extractor writes <images_360>/equi_processed/), and Reconstruction
    # itself collects the source folder recursively.
    sources = (
        sorted(f for f in src.rglob("*") if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS)
        if src.is_dir()
        else [src]
    )

    staged_names = _staged_names(sources, suffix, fmt, root=src if src.is_dir() else None)

    with _tempfile.TemporaryDirectory(prefix="upscayl_in_") as tmp_in:
        tmp_in_path = Path(tmp_in)
        orig_sizes = {}
        for f in sources:
            staged_name = staged_names[f]
            _copy_as_supported_image(f, tmp_in_path / staged_name)
            if x1_mode:
                from PIL import Image as _PIL
                # Read back the staged copy: the original may be a format
                # Pillow cannot open (HEIC), the staged one never is.
                with _PIL.open(tmp_in_path / staged_name) as im:
                    orig_sizes[staged_name] = im.size

        success = [False]
        run_upscayl(tmp_in, output_dir, upscayl_params,
                    log_callback=log_callback,
                    done_callback=lambda ok: success.__setitem__(0, ok),
                    cancel_check=cancel_check)
        if success[0] and x1_mode:
            resize_to_original(output_dir, orig_sizes)

    return success[0], (output_dir if success[0] else tr("up_err_failed", "Upscale failed."))


def _staged_names(sources, suffix, fmt, root=None):
    """Map each source to its staged file name (``<stem><suffix>.<fmt>``).

    Sources sharing a stem (``a.jpg`` and ``a.png``, or ``x/a.jpg`` and
    ``y/a.jpg`` when *root* is scanned recursively) would get the same name
    and silently overwrite each other, so those alone also carry their
    sub-folder (relative to *root*) and original extension
    (``a_y_jpg<suffix>.<fmt>``). Other names are unchanged.
    """
    counts = {}
    for f in sources:
        counts[f.stem.lower()] = counts.get(f.stem.lower(), 0) + 1
    names = {}
    for f in sources:
        tag = ""
        if counts[f.stem.lower()] > 1:
            parts = []
            if root is not None:
                try:
                    parts = list(f.parent.relative_to(root).parts)
                except ValueError:
                    parts = []
            parts.append(f.suffix.lower().lstrip("."))
            tag = "_" + "_".join(parts)
        names[f] = f"{f.stem}{tag}{suffix}.{fmt}"
    return names


def _copy_as_supported_image(src: Path, dest: Path) -> None:
    """Copies *src* to *dest*, re-encoding it as 8-bit RGB/RGBA first.

    upscayl-bin's image loader rejects some real-world scans (CMYK, 16-bit,
    palette/indexed color, interlaced PNG…) with a generic "channels: 0"
    error. Re-saving through Pillow normalizes the pixel format before the
    binary ever sees the file. Falls back to a raw copy if Pillow can't open
    it (e.g. an already-unsupported format), so the original error surfaces.
    """
    from PIL import Image as _PIL
    try:
        with _PIL.open(src) as im:
            has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            im.convert("RGBA" if has_alpha else "RGB").save(dest)
    except Exception:
        # HEIC and friends: Pillow has no decoder here, macOS sips does.
        fmt = "jpeg" if dest.suffix.lower() in (".jpg", ".jpeg") else "png"
        if convert_image(src, dest, fmt):
            return
        import shutil as _shutil
        _shutil.copy2(src, dest)
