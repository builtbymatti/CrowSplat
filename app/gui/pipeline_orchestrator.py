"""Qt-free orchestration of the Studio pipeline chain.

``StudioWindow`` used to hold, next to its widgets, the whole chaining logic:
which step runs next, how each step's worker is built from the panels, how
the PLY of the previous step is looked up and pre-filled into the next panel.
That logic lives here, behind a small ``PipelineHost`` surface, so the window
is left with the Qt wiring (threads, dialogs, rail, buttons).

Nothing in this module imports PySide6. The worker classes (which are
``QThread`` subclasses) are injected as the ``workers`` namespace, and the
window is reached only through ``PipelineHost``.

Adding a step means writing one handler and registering it with
``@pipeline_step("name")`` (or one row in ``_WORKER_STEPS`` when the step is
just "build a worker, start it"); ``run_step`` never changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.core.base_engine import validate_path_standalone
from app.core.i18n import tr
from app.core.run_state import StepStatus
from app.gui.chaining_logic import (
    is_chain_owned,
    keeps_only_latest_checkpoint,
    resolve_checkpoints_dir,
    resolve_export_dir,
    resolve_export_format,
)
from app.gui.panels.reconstruction_logic import (
    RESUME_COLMAP_PROJECT,
    RESUME_EXTERNAL_IMAGES,
    apply_source_settings,
    classify_resume_folder,
    describe_unusable_source,
    detect_source_kind,
)


class PipelineHost(Protocol):
    """What the orchestrator needs from the window that drives it."""

    panels: dict
    run_state: Any
    rail: Any
    logs_window: Any

    def _fail_pipeline_step(self, step: str, message: str) -> None: ...

    def _start_pipeline_worker(self, step: str, worker: Any) -> None: ...

    def _finish_pipeline_chain(self, success: bool, message: str) -> None: ...


@dataclass
class PipelineContext:
    """Mutable state shared by the steps of one chain run."""

    plan: list = field(default_factory=list)
    plan_index: int = 0
    mode: str = "gsplat"
    # Current image folder of the chain: every pre-step that produces a new
    # folder (Extraction 360, then Upscale) overwrites it, and the next step
    # reads it instead of the raw Source path.
    images_dir: str | None = None
    pending_upscale_params: dict | None = None
    # Output fields the chain filled in itself (Nettoyage, Export), so a later
    # run may replace them while a value typed by the user is kept.
    chain_prefilled: dict = field(default_factory=dict)
    # Set when an OUTILS tool started the chain (where it wrote its PLY, and
    # the name to show when that PLY is missing).
    tool_ply_root: Any = None
    tool_producer_label: str | None = None


# ── Step registry ─────────────────────────────────────────────────────────────
StepHandler = Callable[["PipelineOrchestrator", int], None]
_STEP_HANDLERS: dict[str, StepHandler] = {}


def pipeline_step(name: str) -> Callable[[StepHandler], StepHandler]:
    """Register ``handler(orchestrator, index)`` as the runner of step ``name``."""

    def register(handler: StepHandler) -> StepHandler:
        _STEP_HANDLERS[name] = handler
        return handler

    return register


# Steps that only build a worker and start it: name -> (builder method,
# prefill method or None, whether a missing worker is a "missing producer"
# failure). Methods are resolved by name when the step runs.
_WORKER_STEPS = {
    "extraction360": ("build_extraction360_worker", None, False),
    "reconstruction": ("build_reconstruction_worker", None, False),
    "entrainement": ("build_brush_worker", None, False),
    "nettoyage": ("build_cleaner_worker", "prefill_cleaner_from_brush", True),
    "export": ("build_export_worker", "prefill_export_from_previous", True),
}


def _register_worker_step(name, builder, prefill, missing_is_failure):
    def handler(orch, _index):
        if prefill:
            getattr(orch, prefill)()
        worker = getattr(orch, builder)()
        if worker is not None:
            orch.host._start_pipeline_worker(name, worker)
        elif missing_is_failure:
            orch.host._fail_pipeline_step(name, orch.missing_producer_message())

    pipeline_step(name)(handler)


for _name, _spec in _WORKER_STEPS.items():
    _register_worker_step(_name, *_spec)


# ── Pure parameter helpers (tool launchers) ───────────────────────────────────
def decimate_needs_ply(src_params: dict) -> bool:
    """True when a decimation is asked for an output that is not ``.ply``.

    Safety net: the panel resets decimate to 100 when the format is not ply,
    but a loaded config could still set both (L3-11).
    """
    return src_params["decimate"] < 100 and src_params["format"] != "ply"


def build_splat_transform_params(src_params: dict) -> dict:
    """SplatTransform CLI flags out of the SplatTransform panel's parameters."""
    flags = {
        "filter_nan": ("--filter-nan", True),
        "filter_floaters": ("--filter-floaters", True),
        "morton": ("--morton-order", True),
        "harmonics": ("--filter-harmonics", "0"),
    }
    st_params: dict = {"--overwrite": True}
    for key, (flag, value) in flags.items():
        if src_params[key]:
            st_params[flag] = value
    if src_params["decimate"] < 100:
        st_params["--decimate"] = f"{src_params['decimate']:.0f}%"
    return st_params


def merge_sharp_params(sharp_params: dict, upscale_params: dict) -> dict:
    """Sharp panel parameters + the shared Upscale panel's settings.

    The Sharp checkbox keeps its own on/off state; only the model, scale,
    tile... come from the Upscale panel.
    """
    upscale_checked = sharp_params.get("upscale", False)
    sharp_params.update(upscale_params)
    sharp_params["upscale"] = upscale_checked
    return sharp_params


def _project_name(source_state: dict) -> str:
    return source_state["project_name"].strip() or "Untitled"


# ── Orchestrator ──────────────────────────────────────────────────────────────
class PipelineOrchestrator:
    """Runs ``ctx.plan`` step by step; the host reports each step's outcome."""

    def __init__(self, host: PipelineHost, workers: Any, ctx: PipelineContext | None = None):
        self.host = host
        self.workers = workers
        self.ctx = ctx if ctx is not None else PipelineContext()

    # -- small shared helpers --------------------------------------------------
    @property
    def panels(self) -> dict:
        return self.host.panels

    def _mark(self, step: str, status: StepStatus) -> None:
        self.host.run_state.set_status(step, status)
        self.host.rail.set_step_status(step, status)

    def _fail_no_paths(self, step: str) -> None:
        self.host._fail_pipeline_step(step, tr("err_no_paths", "Chemins manquants."))

    # -- chaining ----------------------------------------------------------------
    def run_step(self, index: int) -> None:
        """Start the ``ctx.plan[index]`` step through the step registry.

        Source has no worker of its own (it only supplies the paths consumed
        by Reconstruction): it is marked DONE immediately and the chain moves
        on. The OUTILS post-steps (Nettoyage/Export/Visualiser) only appear in
        the plan when their ``run_state`` flag is on; they are pre-filled from
        the previous step's output then chained like Reconstruction/Brush.
        """
        self.ctx.plan_index = index
        if index >= len(self.ctx.plan):
            self.host._finish_pipeline_chain(
                True, tr("run_chain_done", "Chaîne terminée avec succès.")
            )
            return
        step = self.ctx.plan[index]
        handler = _STEP_HANDLERS.get(step)
        if handler is None:
            # Defensive: ``plan_pipeline`` only produces registered keys.
            message = tr("run_chain_manual_continue").format(step)
            self.host._finish_pipeline_chain(True, message)
            return
        handler(self, index)

    def advance(self) -> None:
        """Move on to the step after the current one."""
        self.run_step(self.ctx.plan_index + 1)

    @pipeline_step("source")
    def _step_source(self, index: int) -> None:
        self._mark("source", StepStatus.DONE)
        self.run_step(index + 1)

    @pipeline_step("upscale")
    def _step_upscale(self, index: int) -> None:
        worker = self.build_upscale_worker()
        if worker is not None:
            self.host._start_pipeline_worker("upscale", worker)
        elif self.ctx.pending_upscale_params is not None:
            # Video source: the images do not exist yet, the upscale is
            # delegated to COLMAP, which runs it right after frame extraction
            # and before feature extraction (``ColmapEngine._process_input``).
            self.host.logs_window.append_log(
                tr("run_upscale_deferred",
                   "Upscale : source vidéo — les trames seront agrandies au "
                   "début de la Reconstruction, avant COLMAP.")
            )
            self._mark("upscale", StepStatus.DONE)
            self.run_step(index + 1)

    @pipeline_step("visualiser")
    def _step_visualiser(self, _index: int) -> None:
        """Visualiser step: the panel is not a Worker/QThread (persistent
        server via ``toggle_server()``), so there is no ``finished_signal``.
        The step is DONE as soon as the server starts, ERROR if it fails.

        L5-10: this step never sets an active worker — Cancel is a no-op here
        by design; ``toggle_server()`` only spawns the servers and returns.
        """
        self.prefill_visualiser_from_previous()
        panel = self.panels["visualiser"]
        self._mark("visualiser", StepStatus.RUNNING)
        if not panel.is_running():
            panel.toggle_server()
        if not panel.is_running():
            self.host._fail_pipeline_step(
                "visualiser",
                tr("err_visualiser_start", "Échec du démarrage du serveur SuperSplat."),
            )
            return
        self._mark("visualiser", StepStatus.DONE)
        self.advance()

    # -- source type -------------------------------------------------------------
    def resolve_source_type(self, step, input_path, source_state):
        """Source type (``images``/``video``) for ``step``, or None if
        undecidable — in which case the step is already marked as failed.

        Honours the user's explicit choice (Images/Vidéo) over auto-detection
        (SourcePanel.combo_source_type, "auto" by default). Shared by Upscale
        and Reconstruction, which must classify the same source the same way.
        """
        forced_type = (source_state.get("source_type") or "auto").strip()
        if forced_type in ("images", "video"):
            return self._check_forced_type(step, forced_type, input_path)
        return self._detect_type(step, input_path, source_state)

    def _check_forced_type(self, step, forced_type, input_path):
        """L5-03: a forced type is checked against the actual folder content.
        A "mixed" folder is exactly what the override exists for, so it is
        accepted either way."""
        actual_kind = detect_source_kind(input_path)
        if actual_kind in (forced_type, "mixed"):
            return forced_type
        self.host._fail_pipeline_step(
            step,
            tr(
                "err_source_type_mismatch",
                "Type de source forcé sur « {forced} » mais le contenu "
                "détecté est « {actual} » — vérifiez le champ Source ou "
                "le sélecteur de type.",
            ).format(forced=forced_type, actual=actual_kind),
        )
        return None

    def _detect_type(self, step, input_path, source_state):
        input_type = detect_source_kind(input_path)
        if input_type == "mixed":
            self.host._fail_pipeline_step(
                step,
                tr(
                    "err_source_mixed_types",
                    "Le dossier contient à la fois des images et des vidéos — "
                    "choisissez explicitement le type de source.",
                ),
            )
            return None
        if input_type == "empty":
            # "empty" covers everything detect_source_kind cannot classify
            # (camera RAW, PSD...), not only a missing path.
            self.host._fail_pipeline_step(
                step,
                describe_unusable_source(
                    input_path, convert_format=source_state.get("convert") or "png"
                ),
            )
            return None
        return input_type

    # -- worker builders (pipeline steps) --------------------------------------
    def build_extraction360_worker(self):
        """Worker of the Extraction 360 step.

        It **produces a new folder** of planar images out of an
        equirectangular source (video or photos); that folder becomes the
        chain's current image folder, which Upscale then COLMAP consume
        instead of the original source. The source type is not resolved here:
        the extractor accepts video as well as images.
        """
        source_state = self.panels["source"].get_state()
        input_path = source_state["input_path"].strip()
        output_path = source_state["output_path"].strip()
        if not input_path or not output_path:
            return self._fail_no_paths("extraction360")
        images_360 = Path(output_path) / _project_name(source_state) / "images_360"
        safe_out = validate_path_standalone(str(images_360))
        if safe_out is None:
            return self._fail_no_paths("extraction360")
        safe_out.mkdir(parents=True, exist_ok=True)
        self.ctx.images_dir = str(safe_out)
        panel = self.panels["extraction360"]
        panel.input_path.setText(input_path)
        panel.output_path.setText(str(safe_out))
        return self.workers.Extractor360Worker(input_path, str(safe_out), panel.get_params())

    def build_upscale_worker(self):
        """Worker of the Upscale step, which enlarges the images *before*
        COLMAP reads them.

        After Extraction 360 the source is the planar image folder it
        produced. Otherwise: an **image source** gets an
        ``UpscaleImagesWorker`` writing into ``<output>/<project>/images_upscaled``
        (the user's folder stays untouched); a **video source** has nothing to
        enlarge yet, so ``pending_upscale_params`` is filled for
        ``build_colmap_worker`` to hand to the engine (``upscale_config``) and
        None is returned without failing.
        """
        source_state = self.panels["source"].get_state()
        input_path = source_state["input_path"].strip()
        output_path = source_state["output_path"].strip()
        if not input_path or not output_path:
            return self._fail_no_paths("upscale")
        params = self.panels["upscale"].get_params()
        input_path = self._upscale_source(source_state, input_path, params)
        if input_path is None:
            return None
        upscaled_dir = Path(output_path) / _project_name(source_state) / "images_upscaled"
        self.ctx.images_dir = str(upscaled_dir)
        return self.workers.UpscaleImagesWorker(input_path, str(upscaled_dir), params)

    def _upscale_source(self, source_state, input_path, params):
        """Folder to enlarge, or None (step failed, or deferred for a video)."""
        if self.ctx.images_dir:
            return self.ctx.images_dir
        input_type = self.resolve_source_type("upscale", input_path, source_state)
        if input_type is None:
            return None
        if input_type == "video":
            self.ctx.pending_upscale_params = {**params, "active": True}
            return None
        return input_path

    def build_reconstruction_worker(self):
        """Reconstruction worker matching the Source panel's mode.

        The three modes share the step slot but not the engine: Gsplat runs
        COLMAP, Sharp runs Apple ML Sharp inference, 4DGS prepares a
        Nerfstudio dataset.
        """
        if self.ctx.mode == "sharp":
            return self.build_sharp_pipeline_worker()
        if self.ctx.mode == "4dgs":
            return self.build_fourdgs_pipeline_worker()
        return self.build_colmap_worker()

    def build_sharp_pipeline_worker(self):
        """``SharpWorker`` for the Sharp mode, fed by the Source paths.

        Sharp's own settings (device, checkpoint, verbose) still come from the
        OUTILS Sharp panel; only the paths are taken from Source. Video inputs
        are rejected (L3-03): the chain's Source step feeds image folders and
        Sharp's video mode has its own worker in the OUTILS panel. Output is
        nested under ``<output>/<project>`` (L5-01), like gsplat and 4DGS.
        """
        source_state = self.panels["source"].get_state()
        input_path = self.ctx.images_dir or source_state["input_path"].strip()
        output_path = source_state["output_path"].strip()
        if not input_path or not output_path:
            return self._fail_no_paths("reconstruction")
        if not self.ctx.images_dir and not self._sharp_input_ok(input_path, source_state):
            return None
        project_output = str(Path(output_path) / _project_name(source_state))
        params = self.panels["sharp"].get_params()
        params.update({"mode": "image", "input_path": input_path, "output_path": project_output})
        return self.workers.SharpWorker(input_path, project_output, params)

    def _sharp_input_ok(self, input_path, source_state) -> bool:
        """False (step already failed) when the source is unusable or a video."""
        input_type = self.resolve_source_type("reconstruction", input_path, source_state)
        if input_type is None:
            return False
        if input_type == "video":
            self.host._fail_pipeline_step(
                "reconstruction",
                tr(
                    "err_sharp_video_rejected",
                    "Le mode Sharp de la chaîne attend un dossier d'images — "
                    "utilisez le module Sharp (OUTILS) pour traiter une vidéo "
                    "directement.",
                ),
            )
            return False
        return True

    def build_fourdgs_pipeline_worker(self):
        """``FourDGSWorker`` for the 4DGS mode, fed by the Source paths.

        Source points at the multi-camera video folder; the 4DGS panel keeps
        supplying FPS and the COLMAP settings. ``upscale_params`` (L3-04) and
        ``video_trim`` (L5-04) are forwarded like the gsplat path does: for a
        video source the Upscale step defers to ``pending_upscale_params``.
        """
        source_state = self.panels["source"].get_state()
        videos_dir = source_state["input_path"].strip()
        output_path = source_state["output_path"].strip()
        if not videos_dir or not output_path:
            return self._fail_no_paths("reconstruction")
        panel_params = self.panels["4dgs"].get_params()
        colmap_params = {
            key: panel_params[key]
            for key in ("camera_model", "single_camera", "matcher_type", "sequential_overlap")
            if key in panel_params
        }
        return self.workers.FourDGSWorker(
            videos_dir, str(Path(output_path) / _project_name(source_state)),
            source_state["fps"] or panel_params["fps"],
            colmap_params=colmap_params,
            upscale_params=self.ctx.pending_upscale_params,
            video_trim=source_state.get("video_trim"),
        )

    def resolve_colmap_resume(self, output_path, project_name):
        """Classify ReconstructionPanel's "Resume COLMAP" field (D1).

        - empty field: no resume requested, returns ``None``;
        - existing CorbeauSplat project (``images/``, ``database.db`` or
          ``sparse/``): the engine works *in place* on that folder with
          ``resume_colmap=True``, so output/project are overridden to be
          exactly the resumed folder;
        - external image folder: a plain image input for a fresh project under
          the *current* Source output/project, no ``resume_colmap``;
        - anything else: fails the step and returns ``False``.

        Returns ``(input_path, input_type, output_path, project_name,
        resume_colmap)`` on a resume request, ``None`` when the field is
        empty, or ``False`` after already failing the step.
        """
        raw = self.panels["reconstruction"].resume_path.text().strip()
        if not raw:
            return None
        kind = classify_resume_folder(raw)
        resume_dir = Path(raw)
        if kind == RESUME_COLMAP_PROJECT:
            return str(resume_dir), "images", str(resume_dir.parent), resume_dir.name, True
        if kind == RESUME_EXTERNAL_IMAGES:
            return str(resume_dir), "images", output_path, project_name, False
        self.host._fail_pipeline_step(
            "reconstruction",
            tr(
                "err_colmap_resume_invalid",
                "Chemin de reprise COLMAP invalide — attendu un projet CorbeauSplat "
                "existant (images/, database.db ou sparse/) ou un dossier contenant "
                "directement des images.",
            ),
        )
        return False

    def build_colmap_worker(self):
        """``ColmapWorker`` of the Reconstruction step, from the Source paths
        (SourcePanel.get_state) and the Reconstruction COLMAP settings.

        If Upscale ran just before, the input becomes the enlarged image
        folder it produced. A "Resume COLMAP" folder (D1), when filled in,
        overrides the source/output entirely (``resolve_colmap_resume``).
        """
        source_state = self.panels["source"].get_state()
        input_path = source_state["input_path"].strip()
        output_path = source_state["output_path"].strip()
        if not input_path or not output_path:
            return self._fail_no_paths("reconstruction")
        project_name = _project_name(source_state)
        params = apply_source_settings(
            self.panels["reconstruction"].get_params(), source_state
        )
        inputs = self._colmap_inputs(source_state, input_path, output_path, project_name)
        if inputs is None:
            return None
        return self._make_colmap_worker(params, source_state["fps"], *inputs)

    def _colmap_inputs(self, source_state, input_path, output_path, project_name):
        """``(input_path, input_type, output_path, project_name, resume)`` or
        None when the step already failed."""
        resume = self.resolve_colmap_resume(output_path, project_name)
        if resume is False:
            return None
        if resume is not None:
            return resume
        if self.ctx.images_dir:
            return self.ctx.images_dir, "images", output_path, project_name, False
        input_type = self.resolve_source_type("reconstruction", input_path, source_state)
        if input_type is None:
            return None
        return input_path, input_type, output_path, project_name, False

    def _make_colmap_worker(self, params, fps, input_path, input_type, output_path,
                            project_name, resume_colmap):
        job = self.workers.ColmapJob(
            params, input_path, output_path, input_type, fps,
            project_name=project_name,
            upscale_params=self.ctx.pending_upscale_params,
        )
        worker = self.workers.ColmapWorker(job)
        if resume_colmap:
            worker.engine.resume_colmap = True
        return worker

    def build_brush_worker(self):
        """``BrushWorker`` of the Entraînement step: dataset = the project
        folder created by COLMAP (output/project), Brush settings from
        EntrainementPanel.get_params -> BrushParams.to_engine_params.
        """
        source_state = self.panels["source"].get_state()
        output_path = source_state["output_path"].strip()
        if not output_path:
            return self._fail_no_paths("entrainement")
        project_name = _project_name(source_state)
        checkpoints_dir = resolve_checkpoints_dir(source_state)
        if checkpoints_dir is None:
            self.host._fail_pipeline_step(
                "entrainement",
                tr("err_checkpoint_dest_invalid", "Destination des checkpoints invalide."),
            )
            return None
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        return self.workers.BrushWorker(
            Path(output_path) / project_name, checkpoints_dir,
            self._brush_params(), project_name=project_name,
            # A custom checkpoint destination only keeps the last checkpoint;
            # an empty field = historical behaviour, every checkpoint kept.
            keep_only_latest=keeps_only_latest_checkpoint(source_state),
        )

    def _brush_params(self) -> dict:
        panel = self.panels["entrainement"]
        params = panel.get_params().to_engine_params()
        params["refine_mode"] = panel.combo_mode.currentData() == "refine"
        ply_name = panel.ply_name_edit.text().strip()
        if ply_name:
            params["ply_name"] = ply_name
        return params

    def build_cleaner_worker(self):
        """``CleanerWorker`` from the current fields of the Nettoyage panel.
        Shared by the local button and the ``nettoyage`` chain step, which
        pre-fills the fields first (``prefill_cleaner_from_brush``)."""
        panel = self.panels["nettoyage"]
        input_path = panel.input_path.text().strip()
        output_path = panel.output_path.text().strip()
        if not input_path or not output_path:
            return None
        params = panel.get_params()
        # L2-04: the "recursive" checkbox must reach CleanerWorker, which
        # defaults to a flat (non-recursive) scan.
        return self.workers.CleanerWorker(
            input_path, output_path, params, recursive=params.get("recursive", False)
        )

    def build_export_worker(self):
        """``ExportWorker`` from the current fields of the Export panel.
        Shared by the local button and the ``export`` chain step."""
        panel = self.panels["export"]
        input_paths = [p for p in panel.input_path.text().split("|") if p.strip()]
        output_dir = panel.output_path.text().strip()
        if not input_paths or not output_dir:
            return None
        return self.workers.ExportWorker(
            input_paths, output_dir, panel.get_format(), options={"scale": panel.get_scale()}
        )

    # -- PLY lookup --------------------------------------------------------------
    @staticmethod
    def find_latest_ply(directory: Path):
        """Most recently modified ``.ply`` under ``directory`` (recursive), or
        ``None``. The final name chosen by Brush is unknown here (it depends on
        ``ply_name``/``project_name``), so the filesystem is read back once
        training is over rather than duplicating its renaming logic.
        """
        if not directory.exists():
            return None
        latest, latest_mtime = None, -1.0
        for ply_path in directory.rglob("*.ply"):
            try:
                mtime = ply_path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest, latest_mtime = ply_path, mtime
        return latest

    def latest_brush_ply(self):
        """PLY produced by the last Entraînement step, in the project's
        checkpoints folder (``build_brush_worker``)."""
        checkpoints_dir = resolve_checkpoints_dir(self.panels["source"].get_state())
        if checkpoints_dir is None:
            return None
        return self.find_latest_ply(checkpoints_dir)

    def latest_sharp_ply(self):
        """PLY produced by the last Sharp reconstruction step (L5-02): Sharp
        writes its splat directly under ``<output>/<project>`` (L5-01), with
        no separate "checkpoints" folder like Brush."""
        source_state = self.panels["source"].get_state()
        output_path = source_state["output_path"].strip()
        if not output_path:
            return None
        return self.find_latest_ply(Path(output_path) / _project_name(source_state))

    def latest_reconstruction_ply(self):
        """PLY produced by whichever reconstruction step actually ran, for the
        current pipeline mode (L5-02).

        When an OUTILS tool started the chain (L3-05/L5-08), its own output
        location wins over the Source-panel lookup: the tool pages have their
        own path fields, unrelated to the Projet panel.
        """
        if self.ctx.tool_ply_root is not None:
            root = Path(self.ctx.tool_ply_root)
            if root.is_file():
                return root if root.suffix.lower() == ".ply" else None
            return self.find_latest_ply(root)
        if self.ctx.mode == "sharp":
            return self.latest_sharp_ply()
        return self.latest_brush_ply()

    def missing_producer_message(self) -> str:
        """Message for a Nettoyage/Export step with no PLY to work on (L5-02),
        naming the step that should have produced it instead of the generic
        "Chemins manquants"."""
        if self.ctx.tool_producer_label:
            producer = self.ctx.tool_producer_label
        elif self.ctx.mode == "sharp":
            producer = "Sharp"
        elif self.ctx.mode == "gsplat" and self.host.run_state.entrainement_apres:
            producer = tr("producer_training_brush", "Entraînement (Brush)")
        else:
            return tr("err_no_paths", "Chemins manquants.")
        return tr(
            "err_no_ply_from_producer",
            "Aucun fichier .ply trouvé — l'étape « {producer} » n'a pas encore "
            "produit de résultat (ou n'est pas dans la chaîne actuelle).",
        ).format(producer=producer)

    def resolve_ply_output(self) -> str:
        """PLY path to hand to the next step: the Nettoyage output when that
        step is on, otherwise the reconstruction step's PLY."""
        if self.host.run_state.nettoyer_apres:
            cleaned = self.panels["nettoyage"].output_path.text().strip()
            if cleaned:
                return cleaned
        latest_ply = self.latest_reconstruction_ply()
        return str(latest_ply) if latest_ply is not None else ""

    # -- Pre-filling the OUTILS post-steps ----------------------------------------
    def prefill_cleaner_from_brush(self) -> None:
        """Pre-fill Nettoyage with the PLY of the previous reconstruction step."""
        latest_ply = self.latest_reconstruction_ply()
        if latest_ply is None:
            return
        panel = self.panels["nettoyage"]
        panel.input_path.setText(str(latest_ply))
        if is_chain_owned(panel.output_path.text(), self.ctx.chain_prefilled.get("nettoyage")):
            cleaned = str(latest_ply.with_name(f"clean_{latest_ply.name}"))
            panel.output_path.setText(cleaned)
            self.ctx.chain_prefilled["nettoyage"] = cleaned

    def prefill_export_from_previous(self) -> None:
        """Pre-fill Export from the previous step's output (Nettoyage when on,
        otherwise the reconstruction PLY).

        The "Export folder" and "Format" fields of the Projet panel, when
        filled in, win over what is typed into the Export panel: they are the
        *chain* settings, whereas the Export panel also serves local runs.
        """
        source_path = self.resolve_ply_output()
        if not source_path:
            return
        source_state = self.panels["source"].get_state()
        panel = self.panels["export"]
        panel.input_path.setText(source_path)
        self._prefill_export_dir(panel, source_state, source_path)
        export_format = resolve_export_format(source_state)
        if export_format:
            idx = panel.combo_format.findData(export_format)
            if idx >= 0:
                panel.combo_format.setCurrentIndex(idx)

    def _prefill_export_dir(self, panel, source_state, source_path) -> None:
        current_output = panel.output_path.text()
        if is_chain_owned(current_output, self.ctx.chain_prefilled.get("export")):
            current_output = ""
        export_dir = resolve_export_dir(source_state, source_path, current_output)
        if export_dir is not None:
            panel.output_path.setText(export_dir)
            self.ctx.chain_prefilled["export"] = export_dir

    def prefill_visualiser_from_previous(self) -> None:
        """Pre-fill Visualiser (same rule as ``prefill_export_from_previous``)."""
        source_path = self.resolve_ply_output()
        if source_path:
            self.panels["visualiser"].input_path.setText(source_path)
