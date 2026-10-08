"""Training panel (PIPELINE step) — equivalent of the Brush tab.

Center: manual/standalone mode (dataset/export/PLY), Visualize after toggle
(bound to run_state), Preset (dropdown, built-in + custom presets via
``merge_presets``), "Save preset" button, essential fields (Steps, SH
Degree, Max Splats, Device), Advanced toggle (Max resolution, Extra args,
Viewer, Build mode — auto-detected from the installed binary, cf.
``get_brush_build_mode``), collapsible Densification and Checkpoints
sections, New/Refine mode. Built on ``BrushParams`` (Batch 1):
``get_params()`` returns a BrushParams, ``to_engine_params()`` produces the
engine string (tokens unchanged, allowlist on the BrushEngine side). Right
bar: empty (content merged into the center, cf. ``app.gui.panels``
docstring).

Batch 3c: UI + BrushParams + presets. The actual run (BrushWorker) goes
through StudioWindow's orchestrated dispatch.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.cli.commands import BRUSH_PRESETS
from app.core.brush_engine import BrushEngine
from app.core.brush_params import BrushParams
from app.core.brush_presets import (
    delete_user_preset,
    is_deletable,
    merge_presets,
    save_user_preset,
)
from app.core.i18n import add_language_observer, tr
from app.core.system import available_devices, get_brush_build_mode
from app.gui.run_state_binding import bind_flag_checkbox
from app.gui.widgets.cancel_button import CancelButton
from app.gui.widgets.dialog_utils import get_existing_directory

# (build_mode value, i18n key, default label) — moved here from SettingsWindow:
# this is a Brush-specific setting, not a global one. Initial value is
# auto-detected from the installed binary (cf. get_brush_build_mode); the
# dropdown lets an informed user override it if needed (e.g. after manually
# swapping binaries).
_BUILD_MODES = (("release", "settings_build_release", "Binaire release"),
                ("source", "settings_build_source", "Compilé source"))


class EntrainementPanel:
    """Plain panel exposing ``center`` and ``right`` (Qt widgets)."""

    def __init__(self, run_state, standalone=False):
        self.run_state = run_state
        self.standalone = standalone
        self._bindings = []
        self.center = self._build_center()
        self.right = self._build_right()
        self._reload_presets()
        add_language_observer(self.retranslate_ui)
        self.retranslate_ui()

    # ── Center (manual mode + tracking + preset → essential → advanced) ────────
    def _build_center(self):
        """Assemble the centre column from its sections.

        Was one ~190-line body (audit M11). Each section still runs in the
        same order on the same layout, so the widget tree is unchanged.
        """
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)

        self._build_manual_group(layout)
        self._build_preset_row(layout)
        self._build_essentials(layout)
        self._build_advanced(layout)
        self._build_densification(layout)
        self._build_checkpoints(layout)
        self._build_release_options(layout)
        self._build_source_options(layout)
        self._sync_build_mode_groups()

        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Local Launch button: standalone mode only (the OUTILS "Brush"
        # module), where the user fills the input/output fields by hand.
        #
        # Deliberately absent from the PIPELINE Training tab. It existed there
        # briefly and was removed on request: that tab has no manual paths, so
        # the button had to infer them, and an early version inferred them
        # wrongly and moved a user's project folder through the checkpoint
        # archiving logic. Training inside the chain is started by the single
        # Launch button in Source, or automatically after Reconstruction when
        # "Lancer Brush" is ticked (StudioWindow._on_reconstruction_standalone_finished).
        if self.standalone:
            self.btn_run = QPushButton()
            self.btn_run.setStyleSheet("font-weight: bold;")
            outer.addWidget(self.btn_run)

            self.btn_cancel = CancelButton()
            outer.addWidget(self.btn_cancel)
        return w

    def _build_manual_group(self, layout):
        """Manual/standalone paths (dataset, export, PLY name) and the Visualize toggle."""
        self.manual_group = QGroupBox()
        mg = QVBoxLayout(self.manual_group)
        self.lbl_dataset = QLabel()
        mg.addWidget(self.lbl_dataset)
        ds_row = QHBoxLayout()
        self.input_path = QLineEdit()
        ds_row.addWidget(self.input_path)
        self.btn_browse_dataset = QPushButton("📁")
        self.btn_browse_dataset.clicked.connect(self._browse_dataset)
        ds_row.addWidget(self.btn_browse_dataset)
        mg.addLayout(ds_row)
        self.lbl_export = QLabel()
        mg.addWidget(self.lbl_export)
        ex_row = QHBoxLayout()
        self.output_path = QLineEdit()
        ex_row.addWidget(self.output_path)
        self.btn_browse_export = QPushButton("📁")
        self.btn_browse_export.clicked.connect(self._browse_export)
        ex_row.addWidget(self.btn_browse_export)
        mg.addLayout(ex_row)
        self.lbl_ply = QLabel()
        mg.addWidget(self.lbl_ply)
        self.ply_name_edit = QLineEdit()
        self.ply_name_edit.setPlaceholderText("output.ply")
        mg.addWidget(self.ply_name_edit)
        layout.addWidget(self.manual_group)

        self.chk_visualiser = QCheckBox()
        self._bind(self.chk_visualiser, "visualiser_apres")
        layout.addWidget(self.chk_visualiser)

    def _build_preset_row(self, layout):
        """Preset dropdown with save/delete buttons."""
        # ── Migrated from _build_right: preset → essential → advanced ──────────
        # Preset + save
        preset_row = QHBoxLayout()
        self.lbl_preset = QLabel()
        self.combo_preset = QComboBox()
        self.combo_preset.currentIndexChanged.connect(self._apply_selected_preset)
        preset_row.addWidget(self.lbl_preset)
        preset_row.addWidget(self.combo_preset, 1)
        self.btn_save_preset = QPushButton("💾")
        self.btn_save_preset.clicked.connect(self._save_current_as_preset)
        preset_row.addWidget(self.btn_save_preset)
        self.btn_delete_preset = QPushButton("🗑")
        self.btn_delete_preset.clicked.connect(self._delete_selected_preset)
        preset_row.addWidget(self.btn_delete_preset)
        layout.addLayout(preset_row)
        self._sync_delete_preset_enabled()

    def _build_essentials(self, layout):
        """Essential fields: steps, SH degree, max splats, device."""
        # Essentials
        essential = QFormLayout()
        essential.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # avoid horizontal overflow (long labels)
        self.spin_total_steps = QSpinBox()
        self.spin_total_steps.setRange(1, 1_000_000)
        self.spin_total_steps.setValue(30000)
        self.lbl_steps = QLabel()
        essential.addRow(self.lbl_steps, self.spin_total_steps)
        self.sh_spin = QSpinBox()
        self.sh_spin.setRange(0, 4)
        self.sh_spin.setValue(3)
        self.lbl_sh = QLabel()
        essential.addRow(self.lbl_sh, self.sh_spin)
        self.spin_max_splats = QSpinBox()
        self.spin_max_splats.setRange(1000, 100_000_000)
        self.spin_max_splats.setValue(10_000_000)
        self.lbl_max_splats = QLabel()
        essential.addRow(self.lbl_max_splats, self.spin_max_splats)
        self.device_combo = QComboBox()
        # "auto" first and selected by default: matches the CLI default
        # (cf. cli/parser.py --device) and lets BrushEngine pick the right
        # device itself (get_device()) instead of forcing "mps", which would
        # be wrong on non-Apple-Silicon machines (cf. audit D10). Only devices
        # this machine can have are listed (no CUDA on a Mac).
        self.device_combo.addItems(["auto", *available_devices()])
        self.lbl_device = QLabel()
        essential.addRow(self.lbl_device, self.device_combo)
        layout.addLayout(essential)

    def _build_advanced(self, layout):
        """Advanced toggle and its hidden form (resolution, extra args, viewer, build mode)."""
        # Advanced (persisted later — Batch 6)
        self.btn_advanced = QPushButton()
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.toggled.connect(self._on_advanced_toggled)
        layout.addWidget(self.btn_advanced)
        self.advanced_group = QWidget()
        ag = QFormLayout(self.advanced_group)
        ag.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # avoid horizontal overflow (long labels)
        self.max_resolution_spin = QSpinBox()
        self.max_resolution_spin.setRange(0, 8192)
        self.lbl_res = QLabel()
        ag.addRow(self.lbl_res, self.max_resolution_spin)
        self.custom_args_edit = QLineEdit()
        self.lbl_args = QLabel()
        ag.addRow(self.lbl_args, self.custom_args_edit)
        self.check_viewer = QCheckBox()
        # Checked by default: without it the Brush viewer window never opens
        # during training, and the option is easy to miss (tucked under
        # "Advanced").
        self.check_viewer.setChecked(True)
        ag.addRow(self.check_viewer)
        # Build mode: which CLI flag spelling BrushEngine must use depends on
        # whether the installed binary is a tagged release or a source build
        # (cf. build_command in brush_engine.py) — auto-detected here from the
        # installed binary so training works out of the box; only override if
        # you know you've manually swapped binaries.
        self.combo_build_mode = QComboBox()
        for value, key, default in _BUILD_MODES:
            self.combo_build_mode.addItem(tr(key, default), value)
        idx = self.combo_build_mode.findData(get_brush_build_mode())
        if idx >= 0:
            self.combo_build_mode.setCurrentIndex(idx)
        # The release and a source build accept different extra options; the
        # tooltip on the extra-args field lists the ones the chosen mode takes.
        self.combo_build_mode.currentIndexChanged.connect(self._sync_args_tooltip)
        self.lbl_build_mode = QLabel()
        ag.addRow(self.lbl_build_mode, self.combo_build_mode)
        self.advanced_group.setVisible(False)
        layout.addWidget(self.advanced_group)

    def _build_densification(self, layout):
        """Densification accordion."""
        # Densification (collapsible)
        self.densif_group = QGroupBox()
        self.densif_group.setCheckable(True)
        self.densif_group.setChecked(False)
        dg = QFormLayout(self.densif_group)
        dg.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # avoid horizontal overflow (long labels)
        self.spin_start_iter = QSpinBox()
        self.spin_start_iter.setRange(0, 1_000_000)
        self.lbl_start_iter = QLabel()
        dg.addRow(self.lbl_start_iter, self.spin_start_iter)
        self.spin_refine = QSpinBox()
        self.spin_refine.setRange(1, 100_000)
        self.spin_refine.setValue(200)
        self.lbl_refine = QLabel()
        dg.addRow(self.lbl_refine, self.spin_refine)
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.0, 1.0)
        self.spin_threshold.setDecimals(5)
        self.spin_threshold.setSingleStep(0.0005)
        self.spin_threshold.setValue(0.003)
        self.lbl_threshold = QLabel()
        dg.addRow(self.lbl_threshold, self.spin_threshold)
        self.spin_fraction = QDoubleSpinBox()
        self.spin_fraction.setRange(0.0, 1.0)
        self.spin_fraction.setSingleStep(0.1)
        self.spin_fraction.setValue(0.2)
        self.lbl_fraction = QLabel()
        dg.addRow(self.lbl_fraction, self.spin_fraction)
        self.spin_growth_stop = QSpinBox()
        self.spin_growth_stop.setRange(0, 1_000_000)
        self.spin_growth_stop.setValue(15000)
        self.lbl_growth_stop = QLabel()
        dg.addRow(self.lbl_growth_stop, self.spin_growth_stop)
        layout.addWidget(self.densif_group)

    def _build_checkpoints(self, layout):
        """Checkpoints accordion (interval, New/Refine mode)."""
        # Checkpoints (collapsible)
        self.ckpt_group = QGroupBox()
        self.ckpt_group.setCheckable(True)
        self.ckpt_group.setChecked(False)
        cg = QFormLayout(self.ckpt_group)
        cg.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # avoid horizontal overflow (long labels, combo_mode issue)
        self.spin_checkpoint_interval = QSpinBox()
        self.spin_checkpoint_interval.setRange(0, 1_000_000)
        self.spin_checkpoint_interval.setValue(7000)
        self.lbl_ckpt_interval = QLabel()
        cg.addRow(self.lbl_ckpt_interval, self.spin_checkpoint_interval)
        # Eval cadence (audit D14): 0 means "never", the Brush default. Folded
        # into custom_args by BrushParams, so the engine tokens stay allowlisted.
        self.spin_eval_every = QSpinBox()
        self.spin_eval_every.setRange(0, 1_000_000)
        self.spin_eval_every.setValue(0)
        self.lbl_eval_every = QLabel()
        cg.addRow(self.lbl_eval_every, self.spin_eval_every)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("", "new")
        self.combo_mode.addItem("", "refine")
        self.lbl_mode = QLabel()
        cg.addRow(self.lbl_mode, self.combo_mode)
        layout.addWidget(self.ckpt_group)

    # The release (v0.3.0) and a source build (git main) do not take the same
    # options. Each gets its own collapsible group, shown only for the build
    # mode selected under "Advanced"; an unchecked group sends nothing, so
    # Brush keeps its own defaults (the values pre-filled below are those
    # defaults, read from `brush --help` / the clap structs on 2026-10-08).
    def _build_release_options(self, layout):
        """Options that only the pinned release accepts."""
        self.release_group = QGroupBox()
        self.release_group.setCheckable(True)
        self.release_group.setChecked(False)
        rg = QFormLayout(self.release_group)
        rg.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.spin_lr_scale_end = QDoubleSpinBox()
        self.spin_lr_scale_end.setRange(0.0, 1.0)
        self.spin_lr_scale_end.setDecimals(5)
        self.spin_lr_scale_end.setSingleStep(0.001)
        self.spin_lr_scale_end.setValue(0.006)
        self.lbl_lr_scale_end = QLabel()
        rg.addRow(self.lbl_lr_scale_end, self.spin_lr_scale_end)
        # Loss weights are tiny (1e-9): a spinbox cannot show them, so free
        # text with the Brush default as placeholder; empty = default.
        self.edit_opac_loss_weight = QLineEdit()
        self.edit_opac_loss_weight.setPlaceholderText("1e-9")
        self.lbl_opac_loss_weight = QLabel()
        rg.addRow(self.lbl_opac_loss_weight, self.edit_opac_loss_weight)
        self.edit_scale_loss_weight = QLineEdit()
        self.edit_scale_loss_weight.setPlaceholderText("1e-8")
        self.lbl_scale_loss_weight = QLabel()
        rg.addRow(self.lbl_scale_loss_weight, self.edit_scale_loss_weight)
        self.spin_aux_loss_time = QDoubleSpinBox()
        self.spin_aux_loss_time.setRange(0.0, 1.0)
        self.spin_aux_loss_time.setDecimals(2)
        self.spin_aux_loss_time.setSingleStep(0.05)
        self.spin_aux_loss_time.setValue(0.9)
        self.lbl_aux_loss_time = QLabel()
        rg.addRow(self.lbl_aux_loss_time, self.spin_aux_loss_time)
        layout.addWidget(self.release_group)

    def _build_source_options(self, layout):
        """Options that only a source build (git main) accepts."""
        self.source_group = QGroupBox()
        self.source_group.setCheckable(True)
        self.source_group.setChecked(False)
        sg = QFormLayout(self.source_group)
        sg.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.spin_growth_start_iter = QSpinBox()
        self.spin_growth_start_iter.setRange(0, 1_000_000)
        self.lbl_growth_start_iter = QLabel()
        sg.addRow(self.lbl_growth_start_iter, self.spin_growth_start_iter)
        self.spin_split_at_screen_size = QDoubleSpinBox()
        self.spin_split_at_screen_size.setRange(0.0, 1.0)
        self.spin_split_at_screen_size.setDecimals(2)
        self.spin_split_at_screen_size.setSingleStep(0.05)
        self.spin_split_at_screen_size.setValue(0.5)
        self.lbl_split_at_screen_size = QLabel()
        sg.addRow(self.lbl_split_at_screen_size, self.spin_split_at_screen_size)
        self.combo_alpha_mode = QComboBox()
        self.combo_alpha_mode.addItem("", None)  # Brush decides
        self.combo_alpha_mode.addItem("masked", "masked")
        self.combo_alpha_mode.addItem("transparent", "transparent")
        self.lbl_alpha_mode = QLabel()
        sg.addRow(self.lbl_alpha_mode, self.combo_alpha_mode)
        self.check_invert_masks = QCheckBox()
        sg.addRow(self.check_invert_masks)
        self.spin_units_per_meter = QDoubleSpinBox()
        self.spin_units_per_meter.setRange(0.0001, 100_000.0)
        self.spin_units_per_meter.setDecimals(4)
        self.spin_units_per_meter.setValue(1.0)
        self.lbl_units_per_meter = QLabel()
        sg.addRow(self.lbl_units_per_meter, self.spin_units_per_meter)
        self.spin_opac_decay = QDoubleSpinBox()
        self.spin_opac_decay.setRange(0.0, 1.0)
        self.spin_opac_decay.setDecimals(4)
        self.spin_opac_decay.setSingleStep(0.001)
        self.spin_opac_decay.setValue(0.004)
        self.lbl_opac_decay = QLabel()
        sg.addRow(self.lbl_opac_decay, self.spin_opac_decay)
        self.spin_min_scale_factor = QDoubleSpinBox()
        self.spin_min_scale_factor.setRange(0.0, 10.0)
        self.spin_min_scale_factor.setDecimals(3)
        self.spin_min_scale_factor.setSingleStep(0.05)
        self.spin_min_scale_factor.setValue(0.1)
        self.lbl_min_scale_factor = QLabel()
        sg.addRow(self.lbl_min_scale_factor, self.spin_min_scale_factor)
        self.spin_bg_noise = QDoubleSpinBox()
        self.spin_bg_noise.setRange(0.0, 1.0)
        self.spin_bg_noise.setDecimals(2)
        self.spin_bg_noise.setSingleStep(0.05)
        self.spin_bg_noise.setValue(0.1)
        self.lbl_bg_noise = QLabel()
        sg.addRow(self.lbl_bg_noise, self.spin_bg_noise)
        self.spin_lod_levels = QSpinBox()
        self.spin_lod_levels.setRange(0, 10)
        self.lbl_lod_levels = QLabel()
        sg.addRow(self.lbl_lod_levels, self.spin_lod_levels)
        self.spin_lod_refine_steps = QSpinBox()
        self.spin_lod_refine_steps.setRange(0, 1_000_000)
        self.spin_lod_refine_steps.setValue(5000)
        self.lbl_lod_refine_steps = QLabel()
        sg.addRow(self.lbl_lod_refine_steps, self.spin_lod_refine_steps)
        self.spin_lod_decimation_keep = QSpinBox()
        self.spin_lod_decimation_keep.setRange(1, 100)
        self.spin_lod_decimation_keep.setValue(50)
        self.lbl_lod_decimation_keep = QLabel()
        sg.addRow(self.lbl_lod_decimation_keep, self.spin_lod_decimation_keep)
        self.spin_lod_image_scale = QSpinBox()
        self.spin_lod_image_scale.setRange(1, 100)
        self.spin_lod_image_scale.setValue(50)
        self.lbl_lod_image_scale = QLabel()
        sg.addRow(self.lbl_lod_image_scale, self.spin_lod_image_scale)
        layout.addWidget(self.source_group)
        self.combo_build_mode.currentIndexChanged.connect(self._sync_build_mode_groups)

    def _sync_build_mode_groups(self, *_):
        """Show the option group of the selected build mode, hide the other."""
        release = self.combo_build_mode.currentData() == "release"
        self.release_group.setVisible(release)
        self.source_group.setVisible(not release)

    def _build_right(self):
        return QWidget()

    def _bind(self, checkbox, flag):
        self._bindings.append(bind_flag_checkbox(checkbox, self.run_state, flag))

    # ── Presets ─────────────────────────────────────────────────────────────────
    def _reload_presets(self):
        """Reload the dropdown: "default" + built-in + custom."""
        self.combo_preset.blockSignals(True)
        self.combo_preset.clear()
        self.combo_preset.addItem(tr("brush_preset_default", "Défaut"), None)
        for name in merge_presets(BRUSH_PRESETS):
            self.combo_preset.addItem(name, name)
        self.combo_preset.blockSignals(False)
        self._sync_delete_preset_enabled()

    def _sync_delete_preset_enabled(self):
        """The 🗑 button is only active on a *user* preset.

        "Default" (data None) and the built-in presets (``BRUSH_PRESETS``,
        shipped with the app) are not deletable: only names present in
        ``load_user_presets()`` are. A user preset that shadows a built-in
        preset of the same name stays deletable — the built-in one then
        reappears, which is ``merge_presets``'s expected behavior."""
        self.btn_delete_preset.setEnabled(is_deletable(self.combo_preset.currentData()))

    def _delete_selected_preset(self):
        name = self.combo_preset.currentData()
        if not is_deletable(name):
            return
        confirm = QMessageBox.question(
            self.center,
            tr("brush_delete_preset", "Supprimer le preset"),
            # No default passed to tr(): when the key exists, LanguageManager.tr()
            # consumes any extra argument as the argument to .format(), which
            # would inject the default text into the {0}. The key is defined
            # in all 9 locales; the fallback (raw key name) is a defensive
            # guard, never actually reached in practice.
            tr("brush_delete_preset_confirm").format(name),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        delete_user_preset(name)
        self._reload_presets()
        self.combo_preset.setCurrentIndex(0)

    def _apply_selected_preset(self, _index):
        name = self.combo_preset.currentData()
        self._sync_delete_preset_enabled()
        if not name:
            return
        preset = merge_presets(BRUSH_PRESETS).get(name)
        if preset:
            self.set_params(BrushParams.from_dict({**self.get_params().to_dict(), **preset}))
            # Built-in presets carry no ply_name (training params only); only
            # apply it when a user preset actually saved one (audit D7).
            if "ply_name" in preset:
                self.ply_name_edit.setText(preset.get("ply_name") or "")

    def _save_current_as_preset(self):
        name, ok = QInputDialog.getText(self.center, tr("brush_save_preset", "Enregistrer le preset"),
                                        tr("brush_preset_name", "Nom du preset"))
        if ok and name.strip():
            data = self.get_params().to_dict()
            data["ply_name"] = self.ply_name_edit.text().strip()
            save_user_preset(name.strip(), data)
            self._reload_presets()

    # ── Handlers ────────────────────────────────────────────────────────────────
    def _on_advanced_toggled(self, checked):
        self.advanced_group.setVisible(checked)

    def _sync_args_tooltip(self, *_):
        """Tooltip of the extra-args field: the flags the current build mode accepts."""
        mode = self.combo_build_mode.currentData()
        flags = sorted(BrushEngine.allowed_flags(mode))
        # Four flags per line keeps the tooltip readable.
        rows = [", ".join(flags[i:i + 4]) for i in range(0, len(flags), 4)]
        # No default passed to tr(): with the key present, extra arguments feed
        # .format() (cf. _delete_selected_preset). Key exists in all 9 locales.
        self.custom_args_edit.setToolTip(
            tr("brush_args_tooltip").format(self.combo_build_mode.currentText(), "\n".join(rows))
        )

    def _browse_dataset(self):
        path = get_existing_directory(self.center, tr("brush_lbl_input", "Dossier dataset"))
        if path:
            self.input_path.setText(path)

    def _browse_export(self):
        path = get_existing_directory(self.center, tr("brush_lbl_output", "Dossier export"))
        if path:
            self.output_path.setText(path)

    # ── Params ────────────────────────────────────────────────────────────────────
    def get_params(self):
        # Densification/Checkpoints are checkable QGroupBox: Qt only greys out
        # their children when unchecked, it does not exclude them from
        # get_params(). Gate explicitly on isChecked() (audit D16/L3-06) so an
        # unchecked section sends nothing (start_iter/refine_every/... are
        # Optional and simply omitted by to_engine_params()) or, for
        # checkpoint_interval (not Optional in BrushParams), the engine's own
        # default (build_command falls back to 7000 when the key is absent —
        # cf. brush_engine.py) so both paths agree.
        densif_on = self.densif_group.isChecked()
        ckpt_on = self.ckpt_group.isChecked()
        return BrushParams(
            total_steps=self.spin_total_steps.value(),
            sh_degree=self.sh_spin.value(),
            max_splats=self.spin_max_splats.value(),
            device=self.device_combo.currentText(),
            max_resolution=self.max_resolution_spin.value() or None,
            with_viewer=self.check_viewer.isChecked(),
            custom_args=self.custom_args_edit.text(),
            start_iter=(self.spin_start_iter.value() or None) if densif_on else None,
            refine_every=self.spin_refine.value() if densif_on else None,
            growth_grad_threshold=self.spin_threshold.value() if densif_on else None,
            growth_select_fraction=self.spin_fraction.value() if densif_on else None,
            growth_stop_iter=(self.spin_growth_stop.value() or None) if densif_on else None,
            checkpoint_interval=self.spin_checkpoint_interval.value() if ckpt_on else 7000,
            eval_every=(self.spin_eval_every.value() or None) if ckpt_on else None,
            build_mode=self.combo_build_mode.currentData(),
            refine_mode=self.combo_mode.currentData() == "refine",
            **self._mode_specific_params(),
        )

    @staticmethod
    def _float_or_none(text):
        try:
            return float(text.strip()) if text.strip() else None
        except ValueError:
            return None

    def _mode_specific_params(self):
        """Fields of the release/source groups: set only when the group is
        checked *and* matches the selected build mode, None otherwise."""
        mode = self.combo_build_mode.currentData()
        out = {}
        if mode == "release" and self.release_group.isChecked():
            out.update(
                lr_scale_end=self.spin_lr_scale_end.value(),
                opac_loss_weight=self._float_or_none(self.edit_opac_loss_weight.text()),
                scale_loss_weight=self._float_or_none(self.edit_scale_loss_weight.text()),
                aux_loss_time=self.spin_aux_loss_time.value(),
            )
        elif mode != "release" and self.source_group.isChecked():
            out.update(
                growth_start_iter=self.spin_growth_start_iter.value(),
                split_at_screen_size=self.spin_split_at_screen_size.value(),
                alpha_mode=self.combo_alpha_mode.currentData(),
                invert_masks=self.check_invert_masks.isChecked(),
                units_per_meter=self.spin_units_per_meter.value(),
                opac_decay=self.spin_opac_decay.value(),
                min_scale_factor=self.spin_min_scale_factor.value(),
                background_noise_strength=self.spin_bg_noise.value(),
                lod_levels=self.spin_lod_levels.value(),
                lod_refine_steps=self.spin_lod_refine_steps.value(),
                lod_decimation_keep=self.spin_lod_decimation_keep.value(),
                lod_image_scale=self.spin_lod_image_scale.value(),
            )
        return out

    def set_params(self, params: BrushParams):
        if params.total_steps is not None:
            self.spin_total_steps.setValue(params.total_steps)
        if params.sh_degree is not None:
            self.sh_spin.setValue(params.sh_degree)
        if params.max_splats is not None:
            self.spin_max_splats.setValue(params.max_splats)
        if params.device:
            self.device_combo.setCurrentText(params.device)
        if params.max_resolution is not None:
            self.max_resolution_spin.setValue(params.max_resolution)
        self.check_viewer.setChecked(params.with_viewer)
        self.custom_args_edit.setText(params.custom_args or "")
        if params.start_iter is not None:
            self.spin_start_iter.setValue(params.start_iter)
        if params.refine_every is not None:
            self.spin_refine.setValue(params.refine_every)
        if params.growth_grad_threshold is not None:
            self.spin_threshold.setValue(params.growth_grad_threshold)
        if params.growth_select_fraction is not None:
            self.spin_fraction.setValue(params.growth_select_fraction)
        if params.growth_stop_iter is not None:
            self.spin_growth_stop.setValue(params.growth_stop_iter)
        if params.checkpoint_interval is not None:
            self.spin_checkpoint_interval.setValue(params.checkpoint_interval)
        # Older presets stored eval_every as a string; int() keeps them working.
        self.spin_eval_every.setValue(int(params.eval_every or 0))
        if params.build_mode:
            idx = self.combo_build_mode.findData(params.build_mode)
            if idx >= 0:
                self.combo_build_mode.setCurrentIndex(idx)
        # Restore the New/Refine mode (audit D17): previously never round-tripped.
        idx = self.combo_mode.findData("refine" if params.refine_mode else "new")
        if idx >= 0:
            self.combo_mode.setCurrentIndex(idx)
        self._set_mode_specific_params(params)

    def _set_mode_specific_params(self, params: BrushParams):
        """Restore the release/source groups; a group whose values are present
        is ticked so a loaded preset actually sends them."""
        release_fields = (
            ("lr_scale_end", self.spin_lr_scale_end.setValue),
            ("opac_loss_weight", lambda v: self.edit_opac_loss_weight.setText(repr(v))),
            ("scale_loss_weight", lambda v: self.edit_scale_loss_weight.setText(repr(v))),
            ("aux_loss_time", self.spin_aux_loss_time.setValue),
        )
        source_fields = (
            ("growth_start_iter", self.spin_growth_start_iter.setValue),
            ("split_at_screen_size", self.spin_split_at_screen_size.setValue),
            ("alpha_mode", lambda v: self.combo_alpha_mode.setCurrentIndex(
                max(0, self.combo_alpha_mode.findData(v)))),
            ("invert_masks", lambda v: self.check_invert_masks.setChecked(bool(v))),
            ("units_per_meter", self.spin_units_per_meter.setValue),
            ("opac_decay", self.spin_opac_decay.setValue),
            ("min_scale_factor", self.spin_min_scale_factor.setValue),
            ("background_noise_strength", self.spin_bg_noise.setValue),
            ("lod_levels", self.spin_lod_levels.setValue),
            ("lod_refine_steps", self.spin_lod_refine_steps.setValue),
            ("lod_decimation_keep", self.spin_lod_decimation_keep.setValue),
            ("lod_image_scale", self.spin_lod_image_scale.setValue),
        )
        for group, fields in ((self.release_group, release_fields), (self.source_group, source_fields)):
            present = False
            for name, setter in fields:
                value = getattr(params, name)
                if value is not None:
                    setter(value)
                    present = True
            if present:
                group.setChecked(True)

    def get_state(self):
        # ply_name_edit has no matching BrushParams field (engine-agnostic,
        # cosmetic-only): carried as an extra dict key alongside the
        # BrushParams fields. BrushParams.from_dict() ignores unknown keys, so
        # round-tripping through set_state() stays safe (audit D7).
        state = self.get_params().to_dict()
        state["ply_name"] = self.ply_name_edit.text().strip()
        return state

    def set_state(self, state):
        if state:
            self.set_params(BrushParams.from_dict(state))
            self.ply_name_edit.setText(state.get("ply_name") or "")

    # ── i18n ────────────────────────────────────────────────────────────────────
    def retranslate_ui(self):
        # Item 0 ("Défaut", data=None) only — preset names (index 1+) are
        # literal, user-chosen strings, never translated.
        self.combo_preset.setItemText(0, tr("brush_preset_default", "Défaut"))
        self.manual_group.setTitle(tr("brush_group_paths", "Mode manuel / indépendant"))
        self.lbl_dataset.setText(tr("brush_lbl_input", "Dossier dataset (sparse + images)"))
        self.lbl_export.setText(tr("brush_lbl_output", "Dossier export"))
        self.lbl_ply.setText(tr("brush_lbl_ply", "Nom du fichier PLY (optionnel)"))
        self.chk_visualiser.setText(tr("chain_view_after", "Lancer dans SuperSplat"))
        if self.standalone:
            self.btn_run.setText(tr("btn_run", "Lancer"))
        self.lbl_preset.setText(tr("brush_lbl_preset", "Preset"))
        self.btn_save_preset.setToolTip(tr("brush_save_preset", "Enregistrer la config comme preset"))
        self.btn_delete_preset.setToolTip(tr("brush_delete_preset", "Supprimer le preset"))
        self.lbl_steps.setText(tr("brush_lbl_steps", "Steps total"))
        self.lbl_sh.setText(tr("brush_sh_degree", "SH Degree"))
        self.lbl_max_splats.setText(tr("brush_max_splats", "Max Splats"))
        self.lbl_device.setText(tr("brush_device", "Device"))
        self.btn_advanced.setText(tr("toggle_advanced", "Avancé"))
        self.lbl_res.setText(tr("brush_lbl_res", "Résolution max"))
        self.lbl_args.setText(tr("brush_args", "Arguments supplémentaires"))
        self.check_viewer.setText(tr("brush_viewer", "Activer le visualiseur pendant l'entraînement"))
        self.lbl_build_mode.setText(tr("settings_build_mode", "Mode de build Brush"))
        for i, (_value, key, default) in enumerate(_BUILD_MODES):
            self.combo_build_mode.setItemText(i, tr(key, default))
        self._sync_args_tooltip()
        self.densif_group.setTitle(tr("brush_group_densif", "Densification"))
        self.lbl_start_iter.setText(tr("brush_start_iter", "Start iter"))
        self.lbl_refine.setText(tr("brush_refine_every", "Refine every"))
        self.lbl_threshold.setText(tr("brush_growth_threshold", "Growth grad threshold"))
        self.lbl_fraction.setText(tr("brush_growth_fraction", "Growth select fraction"))
        self.lbl_growth_stop.setText(tr("brush_growth_stop", "Growth stop iter"))
        self.ckpt_group.setTitle(tr("brush_group_ckpt", "Checkpoints"))
        self.lbl_ckpt_interval.setText(tr("brush_ckpt_interval", "Checkpoint interval"))
        self.lbl_eval_every.setText(tr("brush_eval_every", "Éval. toutes les N étapes (0 = jamais)"))
        self.release_group.setTitle(tr("brush_group_release", "Options release (0.3.0)"))
        self.lbl_lr_scale_end.setText(tr("brush_lr_scale_end", "LR échelle (fin)"))
        self.lbl_opac_loss_weight.setText(tr("brush_opac_loss_weight", "Poids perte opacité"))
        self.lbl_scale_loss_weight.setText(tr("brush_scale_loss_weight", "Poids perte échelle"))
        self.lbl_aux_loss_time.setText(tr("brush_aux_loss_time", "Durée pertes aux. (0–1)"))
        self.source_group.setTitle(tr("brush_group_source", "Options build git"))
        self.lbl_growth_start_iter.setText(tr("brush_growth_start_iter", "Growth start iter"))
        self.lbl_split_at_screen_size.setText(tr("brush_split_at_screen_size", "Split à la taille écran (0 = off)"))
        self.lbl_alpha_mode.setText(tr("brush_alpha_mode", "Mode alpha"))
        self.combo_alpha_mode.setItemText(0, tr("brush_alpha_auto", "Auto"))
        self.check_invert_masks.setText(tr("brush_invert_masks", "Inverser les masques"))
        self.lbl_units_per_meter.setText(tr("brush_units_per_meter", "Unités par mètre"))
        self.lbl_opac_decay.setText(tr("brush_opac_decay", "Décroissance opacité"))
        self.lbl_min_scale_factor.setText(tr("brush_min_scale_factor", "Filtre 3D min (Mip-Splatting)"))
        self.lbl_bg_noise.setText(tr("brush_bg_noise", "Bruit du fond"))
        self.lbl_lod_levels.setText(tr("brush_lod_levels", "Niveaux LOD (0 = off)"))
        self.lbl_lod_refine_steps.setText(tr("brush_lod_refine_steps", "Étapes par niveau LOD"))
        self.lbl_lod_decimation_keep.setText(tr("brush_lod_decimation_keep", "LOD : % de splats gardés"))
        self.lbl_lod_image_scale.setText(tr("brush_lod_image_scale", "LOD : % d'échelle image"))
        self.lbl_mode.setText(tr("brush_lbl_mode", "Mode"))
        self.combo_mode.setItemText(0, tr("brush_mode_new", "Nouveau"))
        self.combo_mode.setItemText(1, tr("brush_mode_refine", "Refine"))
