"""Pre-upscale of a Sharp input image via upscayl-bin, shared by GUI and CLI."""
import shutil
from pathlib import Path

from app.core.i18n import tr


def preupscale_image(input_path, output_dir, params, log, cancel_check=None) -> Path | None:
    """Upscale a single image before Sharp prediction.

    The image is staged in ``<output_dir>/temp_upscale/_in`` (upscayl-bin works
    on folders) and upscaled into ``<output_dir>/temp_upscale``. Returns the
    upscaled file path, or None (after logging why) when upscaling is not
    possible or fails, so the caller keeps the original image.
    """
    # Imported lazily so patches on app.upscayl_manager are honored.
    from app.upscayl_manager import find_binary, get_models_dir, run_upscayl
    from app.upscayl_models import get_downloaded_models

    if not find_binary():
        log(tr("err_upscale_missing", "Error: Upscale requested but upscayl-bin not found."))
        return None

    input_path = Path(input_path)
    if not input_path.is_file():
        log(tr("err_upscale_folder", "Folder upscale not supported in Sharp mode."))
        return None

    model_id = params.get("model_id") or ""
    if not model_id:
        downloaded = get_downloaded_models(get_models_dir())
        model_id = downloaded[0].id if downloaded else ""
    if not model_id:
        log(tr("err_upscale_no_model", "Upscale enabled but no model available - skipped."))
        return None

    fmt = params.get("format", "png")
    temp_dir = Path(output_dir) / "temp_upscale"
    tmp_in = temp_dir / "_in"
    tmp_in.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_path, tmp_in / input_path.name)

    upscale_params = {
        "model_id": model_id,
        "scale": params.get("scale", 4),
        "format": fmt,
        "tile": params.get("tile", 0),
        "tta": params.get("tta", False),
        "compression": params.get("compression", 0),
    }
    log(tr("status_upscaling", "--- Upscale Image ---"))
    result = {"ok": False}
    kwargs = {"cancel_check": cancel_check} if cancel_check else {}
    run_upscayl(
        str(tmp_in), str(temp_dir), upscale_params,
        log_callback=log,
        done_callback=lambda ok: result.__setitem__("ok", ok),
        **kwargs,
    )
    upscaled_path = temp_dir / (input_path.stem + "." + fmt)
    if result["ok"] and upscaled_path.exists():
        log(tr("status_upscale_done", "Upscale done. Launching Sharp..."))
        return upscaled_path

    log(tr("err_upscale_failed", "Upscale failed. Using original image."))
    return None
