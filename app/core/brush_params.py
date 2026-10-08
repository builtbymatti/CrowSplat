"""Structured surface of the Brush parameters, on top of the engine allowlist.

Goal: give the UI (Entraînement step, Brush module) and preset saving structured
fields (Max Splats, Densification group, Checkpoints group) rather than a
free-text ``custom_args`` string.

**Security contract unchanged**: this module only produces the *flat dict* that
``BrushEngine.build_command()`` already consumes. It touches neither
``ALLOWED_FLAGS`` nor ``build_command``: for the same values, the generated
tokens stay strictly identical to the existing ones. The one flag not handled
natively by ``build_command`` (``--eval-every``) is folded into
``custom_args``, where the allowlist filters it as it does today.

``save_iterations`` and ``refine_pose`` used to live here too; Brush v0.3.0
has no such flags, so they were dropped (audit D14). ``from_dict()`` still
ignores them in old presets.
"""

from dataclasses import asdict, dataclass, fields

# Flags promoted to structured fields but NOT handled natively by build_command:
# we fold them into custom_args (the engine allowlist filters them). Fixed order
# for deterministic token output. The release (v0.3.0) and a source build (git
# main) accept different options, so the mode-specific tuples are only folded
# for the matching ``build_mode`` (cf. BrushEngine.RELEASE_ONLY_FLAGS /
# SOURCE_ONLY_FLAGS). Bare boolean flags come last so they never swallow a value.
_COMMON_ARG_FLAGS = (
    ("eval_every", "--eval-every"),
)
_RELEASE_ARG_FLAGS = (
    ("lr_scale_end", "--lr-scale-end"),
    ("opac_loss_weight", "--opac-loss-weight"),
    ("scale_loss_weight", "--scale-loss-weight"),
    ("aux_loss_time", "--aux-loss-time"),
)
_SOURCE_ARG_FLAGS = (
    ("growth_start_iter", "--growth-start-iter"),
    ("split_at_screen_size", "--split-at-screen-size"),
    ("alpha_mode", "--alpha-mode"),
    ("units_per_meter", "--units-per-meter"),
    ("opac_decay", "--opac-decay"),
    ("min_scale_factor", "--min-scale-factor"),
    ("background_noise_strength", "--background-noise-strength"),
    ("lod_levels", "--lod-levels"),
    ("lod_refine_steps", "--lod-refine-steps"),
    ("lod_decimation_keep", "--lod-decimation-keep"),
    ("lod_image_scale", "--lod-image-scale"),
)
_SOURCE_BOOL_FLAGS = (
    ("invert_masks", "--invert-masks"),
)


@dataclass
class BrushParams:
    """Structured Brush training parameters.

    ``None`` values mean "unset" → the matching flag is omitted, exactly like a
    flat dict without the key.
    """

    # ── Essentials ────────────────────────────────────────────────────────────
    total_steps: int | None = None
    sh_degree: int | None = None
    max_splats: int | None = None
    device: str | None = None

    # ── Advanced ──────────────────────────────────────────────────────────────
    max_resolution: int | None = None
    with_viewer: bool = False
    build_mode: str | None = None
    custom_args: str = ""

    # ── Densification (already handled natively by build_command) ─────────────
    start_iter: int | None = None
    refine_every: int | None = None
    growth_grad_threshold: float | None = None
    growth_select_fraction: float | None = None
    growth_stop_iter: int | None = None

    # ── Checkpoints ───────────────────────────────────────────────────────────
    # checkpoint_interval defaults to 7000: reproduces build_command's default
    # (which always emits --export-every 7000 unless set to 0).
    checkpoint_interval: int = 7000
    eval_every: int | None = None  # folded into custom_args; None/0 = never

    # ── Release-only options (Brush v0.3.0) — None = Brush default ──────────
    lr_scale_end: float | None = None
    opac_loss_weight: float | None = None
    scale_loss_weight: float | None = None
    aux_loss_time: float | None = None

    # ── Source-only options (git main, snapshot 2026-10-08) — None = default ─
    growth_start_iter: int | None = None
    split_at_screen_size: float | None = None
    alpha_mode: str | None = None  # "masked" | "transparent"
    invert_masks: bool | None = None
    units_per_meter: float | None = None
    opac_decay: float | None = None
    min_scale_factor: float | None = None
    background_noise_strength: float | None = None
    lod_levels: int | None = None
    lod_refine_steps: int | None = None
    lod_decimation_keep: int | None = None
    lod_image_scale: int | None = None

    # ── Mode ──────────────────────────────────────────────────────────────────
    refine_mode: bool = False  # True = resume an existing training run

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BrushParams":
        """Build from a dict, ignoring unknown keys (old presets / configs saved
        by an earlier version).
        """
        if not isinstance(data, dict):
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def to_engine_params(self) -> dict:
        """Produce the flat dict consumed by ``BrushEngine.build_command()``.

        Fields not handled natively are appended to ``custom_args`` (filtered by
        the allowlist on the engine side). No flag outside the allowlist is
        introduced.
        """
        native_keys = (
            "total_steps", "sh_degree", "max_splats", "device",
            "max_resolution", "with_viewer", "build_mode",
            "start_iter", "refine_every", "growth_grad_threshold",
            "growth_select_fraction", "growth_stop_iter", "checkpoint_interval",
            "refine_mode",
        )
        params = {k: getattr(self, k) for k in native_keys if getattr(self, k) is not None}

        extra_tokens: list[str] = []
        for attr, flag in _COMMON_ARG_FLAGS:
            value = getattr(self, attr)
            if value:  # None, 0 and "" all mean "unset"
                extra_tokens.extend([flag, str(value)])

        # Mode-specific options: only the ones the chosen build accepts. With
        # no build_mode (hand-built params) fold everything and let the engine
        # allowlist sort it out.
        value_flags: tuple[tuple[str, str], ...] = ()
        bool_flags: tuple[tuple[str, str], ...] = ()
        if self.build_mode != "source":
            value_flags += _RELEASE_ARG_FLAGS
        if self.build_mode != "release":
            value_flags += _SOURCE_ARG_FLAGS
            bool_flags += _SOURCE_BOOL_FLAGS
        for attr, flag in value_flags:
            value = getattr(self, attr)
            if value is not None and value != "":  # 0 is a real value here
                extra_tokens.extend([flag, str(value)])
        for attr, flag in bool_flags:
            if getattr(self, attr):
                extra_tokens.append(flag)

        custom = self.custom_args.strip()
        if extra_tokens:
            custom = (custom + " " + " ".join(extra_tokens)).strip() if custom else " ".join(extra_tokens)
        if custom:
            params["custom_args"] = custom
        return params
