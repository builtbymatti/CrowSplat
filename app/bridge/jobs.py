"""Qt-free jobs the CrowSplat app runs, one per process.

Each job takes a plain dict (the JSON the app sends) and a ``Channel`` for
events, drives the existing engines in ``app/core`` and reports through the
channel. Nothing here re-implements an engine: the logic below is the glue
that used to live in the QThread workers (``app/gui/workers.py``) and the CLI
(``app/cli/commands.py``), without Qt and without ``print``/``sys.exit``.

A scene is a folder ``<library>/<name>/`` holding the COLMAP project, the
``checkpoints/`` Brush writes, the cleaned and exported splats, and a
``scene.json`` manifest the app's library reads.
"""

import json
import shutil
import threading
import time
from pathlib import Path

from app.core.brush_presets import BRUSH_DEFAULTS, BRUSH_PRESETS
from app.core.media import IMAGE_EXTENSIONS
from app.core.params import ColmapParams
from app.core.system import get_brush_build_mode
from app.gui.chaining_logic import find_checkpoint_plys, resolve_checkpoints_dir
from app.gui.panels.reconstruction_logic import detect_source_kind


class Cancelled(Exception):
    pass


class JobContext:
    """Cancellation shared by the job and the SIGTERM handler."""

    def __init__(self, channel):
        self.channel = channel
        self.cancelled = threading.Event()
        self.engine = None  # engine running now, stopped on cancel

    def cancel(self):
        if self.cancelled.is_set():
            return
        self.cancelled.set()
        engine = self.engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled()


# ── Quality presets ────────────────────────────────────────────────────────────
# One choice for the user instead of forty knobs. Each maps to a COLMAP image
# size and a Brush preset; "advanced" in the job can still override any field.
QUALITY = {
    "draft":    {"brush": "fast",  "max_image_size": 1600, "undistort": False},
    "standard": {"brush": "std",   "max_image_size": 3200, "undistort": False},
    "fine":     {"brush": "dense", "max_image_size": 3200, "undistort": True},
}


def _write_manifest(scene_dir: Path, **fields) -> dict:
    path = scene_dir / "scene.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
    data.update(fields)
    data["updated"] = time.time()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(path)
    return data


def _make_thumbnail(images_dir: Path, scene_dir: Path):
    """Middle frame of the capture, 640 px wide: the library card's picture."""
    try:
        from PIL import Image

        frames = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not frames:
            return None
        with Image.open(frames[len(frames) // 2]) as im:
            im.thumbnail((640, 640))
            out = scene_dir / "thumb.jpg"
            im.convert("RGB").save(out, quality=86)
            return out
    except Exception:
        return None


def _watch_checkpoints(folder: Path, ctx: JobContext, stop: threading.Event):
    """Announce each checkpoint Brush exports, so the app can preview it live."""
    seen = set(find_checkpoint_plys(folder))
    while not stop.wait(3.0):
        for ply in find_checkpoint_plys(folder):
            if ply not in seen:
                seen.add(ply)
                ctx.channel.artifact("checkpoint", ply)


def _archive_existing_checkpoints(folder: Path, ch) -> None:
    """Brush resumes from existing checkpoints; a fresh run starts clean."""
    existing = find_checkpoint_plys(folder)
    if not existing:
        return
    backup = folder / f"checkpoints_backup_{int(time.time())}"
    backup.mkdir()
    for ply in existing:
        shutil.move(str(ply), backup / ply.name)
    ch.log(f"Previous checkpoints moved to {backup.name}")


def _latest(plys):
    return max(plys, key=lambda p: p.stat().st_mtime) if plys else None


# ── Steps ──────────────────────────────────────────────────────────────────────

def _step_360(ctx, source: Path, scene_dir: Path, opts: dict) -> Path:
    from app.core.extractor_360_engine import Extractor360Engine

    ch = ctx.channel
    engine = Extractor360Engine(logger_callback=ch.log)
    if not engine.is_installed():
        raise RuntimeError("The 360° extractor is not installed. Install it in Settings → Engines.")
    out = scene_dir / "views_360"
    params = {"interval": opts.get("interval", 1.0), "format": "jpg",
              "resolution": opts.get("resolution", 1920), "camera_count": opts.get("cameras", 4),
              "quality": 92, "ai_mask": bool(opts.get("mask_operator", False))}
    ctx.engine = engine
    ok = engine.run_extraction(str(source), str(out), params, progress_callback=ch.progress,
                               log_callback=ch.log, status_callback=ch.status,
                               check_cancel_callback=ctx.cancelled.is_set)
    ctx.check()
    if not ok:
        raise RuntimeError("360° extraction failed (see log).")
    return out


def _step_reconstruct(ctx, source: Path, kind: str, scene_dir: Path, job: dict) -> Path:
    from app.core.engine import ColmapCallbacks, ColmapEngine

    ch = ctx.channel
    quality = QUALITY.get(job.get("quality", "standard"), QUALITY["standard"])
    params = ColmapParams()
    params.max_image_size = quality["max_image_size"]
    params.undistort_images = quality["undistort"]
    # Video frames come in order: sequential matching is faster and closes
    # loops; loose photos need every pair compared.
    params.matcher_type = job.get("matcher") or ("sequential" if kind == "video" else "exhaustive")
    trim = job.get("trim")
    if trim:
        params.video_trim_start, params.video_trim_end = trim
    for key, value in (job.get("advanced", {}).get("colmap") or {}).items():
        if hasattr(params, key):
            setattr(params, key, value)

    engine = ColmapEngine(
        params, str(source), str(scene_dir.parent), kind, int(job.get("fps", 3)), scene_dir.name,
        ColmapCallbacks(logger=ch.log, progress=ch.progress, status=ch.status,
                        check_cancel=ctx.cancelled.is_set),
    )
    if job.get("upscale"):
        engine.upscale_config = {"active": True, **job["upscale"]}
    ctx.engine = engine
    ok, message = engine.run()
    ctx.check()
    if not ok:
        raise RuntimeError(message or "Reconstruction failed.")
    return scene_dir


def _step_train(ctx, scene_dir: Path, job: dict) -> Path:
    from app.core.brush_engine import BrushEngine

    ch = ctx.channel
    quality = QUALITY.get(job.get("quality", "standard"), QUALITY["standard"])
    params = dict(BRUSH_DEFAULTS)
    params.update(BRUSH_PRESETS[quality["brush"]])
    params.update(job.get("advanced", {}).get("brush") or {})
    params["build_mode"] = get_brush_build_mode()
    # Five checkpoints over the run: enough to watch the splat take shape.
    params["checkpoint_interval"] = max(1000, int(params["total_steps"]) // 5)
    params["with_viewer"] = False

    checkpoints = resolve_checkpoints_dir({"output_path": str(scene_dir.parent),
                                           "project_name": scene_dir.name, "checkpoint_dest": ""})
    checkpoints.mkdir(parents=True, exist_ok=True)
    _archive_existing_checkpoints(checkpoints, ch)

    engine = BrushEngine(logger_callback=ch.log,
                         progress_callback=lambda pct, eta: (ch.progress(min(99.9, pct)), ch.eta(eta)),
                         status_callback=ch.status)
    ctx.engine = engine
    stop = threading.Event()
    threading.Thread(target=_watch_checkpoints, args=(checkpoints, ctx, stop), daemon=True).start()
    try:
        code = engine.train(str(scene_dir), str(checkpoints), params)
    finally:
        stop.set()
    ctx.check()
    if code != 0:
        raise RuntimeError(f"Brush stopped with code {code} (see log).")
    final = _latest(find_checkpoint_plys(checkpoints))
    if final is None:
        raise RuntimeError("Training finished but produced no splat.")
    ch.progress(100)
    return final


def _step_clean(ctx, ply: Path, strength: str) -> Path:
    from app.core.ply_cleaner import CleaningCancelled, clean_ply

    ch = ctx.channel
    out = ply.parent.parent / "splat_clean.ply" if ply.parent.name == "checkpoints" else \
        ply.with_name(f"{ply.stem}_clean.ply")
    ch.status(f"Removing floaters ({strength})")
    try:
        stats = clean_ply(str(ply), str(out), strength=strength, log=ch.log,
                          cancel_check=ctx.cancelled.is_set)
    except CleaningCancelled:
        raise Cancelled() from None
    ch.log(f"Kept {stats.get('kept', '?')} of {stats.get('total', '?')} splats")
    ch.progress(100)
    return out


def _export(ctx, ply: Path, fmt: str, dest_dir: Path, stem: str | None = None) -> Path:
    """SOG/SPZ/GLB through PlayCanvas splat-transform, else the PLY exporter."""
    from app.core.export_engine import ExportEngine
    from app.core.splat_transform_engine import SplatTransformEngine

    ch = ctx.channel
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{stem or ply.stem.replace('_clean', '')}.{fmt}"
    transform = SplatTransformEngine(logger_callback=ch.log)
    if fmt in ("sog", "spz", "glb", "ply") and transform.is_available():
        ctx.engine = transform
        if transform.transform(str(ply), str(target), {}) == 0:
            return target
    exporter = ExportEngine(logger_callback=ch.log)
    missing = exporter.missing_dependency(fmt)
    if missing:
        raise RuntimeError(f"{fmt.upper()} export needs {missing}.")
    if not exporter.export(str(ply), str(dest_dir), fmt):
        raise RuntimeError(f"{fmt.upper()} export failed.")
    return target


# ── Jobs ───────────────────────────────────────────────────────────────────────

def job_scene(ctx: JobContext, job: dict) -> dict:
    """Capture → splat: [360 split] → reconstruct → train → [clean] → [export]."""
    ch = ctx.channel
    source = Path(job["input"]).expanduser()
    scene_dir = Path(job["library"]).expanduser() / job["name"]
    scene_dir.mkdir(parents=True, exist_ok=True)

    is_360 = job.get("source") == "360"
    kind = "video" if is_360 else detect_source_kind(source)
    if kind not in ("video", "images"):
        raise RuntimeError("Pick one video or a folder of photos (this one is empty or mixed).")

    steps = (["split360"] if is_360 else []) + ["reconstruct", "train"]
    if job.get("clean"):
        steps.append("clean")
    exports = [f for f in job.get("export") or [] if f]
    if exports:
        steps.append("export")
    labels = {"split360": "Splitting 360° video", "reconstruct": "Reconstructing cameras",
              "train": "Training splat", "clean": "Cleaning", "export": "Exporting"}

    _write_manifest(scene_dir, name=job["name"], source=str(source), kind=kind,
                    quality=job.get("quality", "standard"), status="running",
                    created=time.time(), steps=steps, outputs={})

    def begin(step):
        ch.begin(step, labels[step], steps.index(step), len(steps), steps)
        _write_manifest(scene_dir, status="running", step=step)

    try:
        images_source, images_kind = source, kind
        if is_360:
            begin("split360")
            images_source, images_kind = _step_360(ctx, source, scene_dir, job.get("options_360") or {}), "images"

        begin("reconstruct")
        _step_reconstruct(ctx, images_source, images_kind, scene_dir, job)
        thumb = _make_thumbnail(scene_dir / "images", scene_dir)
        if thumb:
            ch.artifact("thumbnail", thumb)
            _write_manifest(scene_dir, thumbnail=thumb.name)

        begin("train")
        splat = _step_train(ctx, scene_dir, job)
        outputs = {"trained": str(splat)}
        ch.artifact("splat", splat)

        if job.get("clean"):
            begin("clean")
            splat = _step_clean(ctx, splat, job["clean"])
            outputs["clean"] = str(splat)
            ch.artifact("splat", splat)

        if exports:
            begin("export")
            for i, fmt in enumerate(exports):
                ch.status(f"Writing {fmt.upper()}")
                target = _export(ctx, splat, fmt, scene_dir / "exports", stem=scene_dir.name)
                outputs[fmt] = str(target)
                ch.artifact("export", target)
                ch.progress(100 * (i + 1) / len(exports))

        _write_manifest(scene_dir, status="ready", step=None, outputs=outputs, splat=str(splat))
        return {"scene": str(scene_dir), "splat": str(splat), "outputs": outputs}
    except Cancelled:
        _write_manifest(scene_dir, status="cancelled", step=None)
        raise
    except Exception as e:
        # An engine tripping over the closed pipe after a cancel is still a cancel.
        if ctx.cancelled.is_set():
            _write_manifest(scene_dir, status="cancelled", step=None)
            raise Cancelled() from e
        _write_manifest(scene_dir, status="failed", step=None, error=str(e))
        raise


def job_sharp(ctx: JobContext, job: dict) -> dict:
    """One photo (or a video, frame by frame) → splat with Apple ML Sharp."""
    from app.core.sharp_engine import SharpEngine

    ch = ctx.channel
    engine = SharpEngine(logger_callback=ch.log)
    if not engine.is_installed():
        raise RuntimeError("Sharp is not installed. Install it in Settings → Engines.")
    source = Path(job["input"]).expanduser()
    out = Path(job["output"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    ctx.engine = engine
    ch.begin("sharp", "Predicting 3D", 0, 1)
    if detect_source_kind(source) == "video":
        count = engine.process_video_frames(str(source), str(out), {"skip_frames": int(job.get("skip", 1))},
                                            log_callback=ch.log, progress_callback=ch.progress,
                                            cancel_check=ctx.cancelled.is_set)
        ctx.check()
        if not count:
            raise RuntimeError("Sharp produced no frames.")
    else:
        if engine.predict(str(source), str(out), {}) != 0:
            ctx.check()
            raise RuntimeError("Sharp failed (see log).")
    plys = sorted(out.rglob("*.ply"), key=lambda p: p.stat().st_mtime)
    for ply in plys[-1:]:
        ch.artifact("splat", ply)
    ch.progress(100)
    return {"output": str(out), "splats": [str(p) for p in plys]}


def job_clean(ctx: JobContext, job: dict) -> dict:
    ch = ctx.channel
    ch.begin("clean", "Cleaning", 0, 1)
    out = _step_clean(ctx, Path(job["input"]).expanduser(), job.get("strength", "medium"))
    ch.artifact("splat", out)
    return {"output": str(out)}


def job_convert(ctx: JobContext, job: dict) -> dict:
    ch = ctx.channel
    ply = Path(job["input"]).expanduser()
    formats = job.get("formats") or ["sog"]
    ch.begin("export", "Converting", 0, 1)
    outputs = {}
    for i, fmt in enumerate(formats):
        ch.status(f"Writing {fmt.upper()}")
        target = _export(ctx, ply, fmt, Path(job.get("output") or ply.parent).expanduser())
        outputs[fmt] = str(target)
        ch.artifact("export", target)
        ch.progress(100 * (i + 1) / len(formats))
    return {"outputs": outputs}


def job_upscale(ctx: JobContext, job: dict) -> dict:
    from app.core.upscale_engine import run_upscale_job

    ch = ctx.channel
    ch.begin("upscale", "Upscaling", 0, 1)
    out = Path(job["output"]).expanduser()
    ok, message = run_upscale_job(str(Path(job["input"]).expanduser()), str(out),
                                  {"model_id": job.get("model", "realesrgan-x4plus"),
                                   "scale": int(job.get("scale", 4)), "format": "png"},
                                  ch.log, ctx.cancelled.is_set)
    ctx.check()
    if not ok:
        raise RuntimeError(message or "Upscale failed.")
    ch.progress(100)
    return {"output": str(out)}


def job_split360(ctx: JobContext, job: dict) -> dict:
    ch = ctx.channel
    ch.begin("split360", "Splitting 360° video", 0, 1)
    out = Path(job["output"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    views = _step_360(ctx, Path(job["input"]).expanduser(), out, job)
    return {"output": str(views)}


def job_fourdgs(ctx: JobContext, job: dict) -> dict:
    from app.core.four_dgs_engine import FourDGSEngine

    ch = ctx.channel
    engine = FourDGSEngine(logger_callback=ch.log)
    ctx.engine = engine
    ch.begin("fourdgs", "Preparing 4D dataset", 0, 1)
    ok = engine.process_dataset(str(Path(job["input"]).expanduser()),
                                str(Path(job["output"]).expanduser()), fps=int(job.get("fps", 5)))
    ctx.check()
    if not ok:
        raise RuntimeError("4D dataset preparation failed (see log).")
    ch.progress(100)
    return {"output": job["output"]}


JOBS = {
    "scene": job_scene,
    "sharp": job_sharp,
    "clean": job_clean,
    "convert": job_convert,
    "upscale": job_upscale,
    "split360": job_split360,
    "fourdgs": job_fourdgs,
}
