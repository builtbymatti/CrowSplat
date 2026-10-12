import logging
import types
import typing
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

_MISSING = object()


def _coerce_scalar(value, target):
    """Coerce ``value`` to ``target`` (bool/int/float/str); _MISSING if impossible."""
    if target is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        return _MISSING
    if target is int:
        if isinstance(value, bool):
            return _MISSING
        if isinstance(value, int):
            return value
        try:
            number = float(value) if isinstance(value, (float, str)) else None
        except ValueError:
            return _MISSING
        if number is not None and number == number and number not in (float("inf"), float("-inf")) \
                and number.is_integer():
            return int(number)
        return _MISSING
    if target is float:
        if isinstance(value, bool):
            return _MISSING
        if isinstance(value, (int, float, str)):
            try:
                number = float(value)
            except ValueError:
                return _MISSING
            return number if number == number and number not in (float("inf"), float("-inf")) else _MISSING
        return _MISSING
    if target is str:
        return value if isinstance(value, str) else _MISSING
    return value


def coerce_known_fields(cls, data: dict) -> dict:
    """Keep only the keys of dataclass ``cls`` and coerce them to the declared
    scalar types; values that cannot be coerced are dropped (field default
    applies) and logged. Protects against hand-edited configs/presets.
    """
    hints = typing.get_type_hints(cls)
    out = {}
    for name, value in data.items():
        hint = hints.get(name)
        if hint is None:
            continue
        args = typing.get_args(hint) if isinstance(hint, types.UnionType) or typing.get_origin(hint) is typing.Union else (hint,)
        allows_none = type(None) in args
        if value is None:
            if allows_none:
                out[name] = None
            continue
        scalars = [a for a in args if a in (bool, int, float, str)]
        if not scalars:
            out[name] = value
            continue
        for target in scalars:
            coerced = _coerce_scalar(value, target)
            if coerced is not _MISSING:
                out[name] = coerced
                break
        else:
            logger.warning("Ignoring invalid value %r for %s.%s", value, cls.__name__, name)
    return out

FEATURE_TYPES = ['SIFT', 'ALIKED_N16ROT', 'ALIKED_N32']
MATCHING_TYPES = ['SIFT_BRUTEFORCE', 'ALIKED_BRUTEFORCE', 'SIFT_LIGHTGLUE', 'ALIKED_LIGHTGLUE']

FEATURE_TO_DEFAULT_MATCHING = {
    'SIFT': 'SIFT_BRUTEFORCE',
    'ALIKED_N16ROT': 'ALIKED_LIGHTGLUE',
    'ALIKED_N32': 'ALIKED_LIGHTGLUE',
}

COMPATIBLE_MATCHING = {
    'SIFT': ['SIFT_BRUTEFORCE', 'SIFT_LIGHTGLUE'],
    'ALIKED_N16ROT': ['ALIKED_BRUTEFORCE', 'ALIKED_LIGHTGLUE'],
    'ALIKED_N32': ['ALIKED_BRUTEFORCE', 'ALIKED_LIGHTGLUE'],
}

def blur_factor_from_strength(strength: str) -> float:
    """Convert a textual strength (light/medium/strong) into a COLMAP blur factor."""
    return {"light": 0.5, "medium": 0.7, "strong": 0.9}.get(strength, 0.7)


@dataclass
class ColmapParams:
    """Data structure for the COLMAP parameters"""
    camera_model: str = 'SIMPLE_RADIAL'
    single_camera: bool = True
    max_image_size: int = 3200
    max_num_features: int = 8192
    feature_type: str = 'SIFT'
    matching_type: str = 'SIFT_BRUTEFORCE'
    # Full DSP-SIFT: affine_shape + domain_size_pooling maximise the matches
    # (COLMAP FAQ recommendation). Forces CPU computation — slower but more robust.
    estimate_affine_shape: bool = True
    domain_size_pooling: bool = True
    max_ratio: float = 0.8
    max_distance: float = 0.7
    cross_check: bool = True
    guided_matching: bool = False
    ba_refine_focal_length: bool = True
    ba_refine_principal_point: bool = False
    ba_refine_extra_params: bool = True
    min_num_matches: int = 15
    matcher_type: str = 'exhaustive' # exhaustive, sequential, vocab_tree
    sequential_overlap: int = 30
    undistort_images: bool = False
    # Blur filtering: discard frames whose sharpness (variance of Laplacian) falls
    # below blur_factor x the median sharpness. 0 (or filter_blurry=False) disables.
    filter_blurry: bool = False
    blur_factor: float = 0.7
    thermal_throttling: bool = False
    # View graph calibration estimates focal lengths from two-view geometries.
    # Recommended before global_mapper, especially for AI-generated content.
    use_view_graph_calibration: bool = True
    # Ignore watermarks typically found in AI-generated video frames.
    ignore_watermarks: bool = True
    # Source images outside JPEG/PNG (HEIC, TIFF, BMP, WebP…) are converted on
    # ingest so every downstream tool can read them: "png" (lossless, default),
    # "jpeg" (quality 95) or "off" to copy them untouched.
    image_convert_format: str = 'png'
    # In/out range picked in the Source panel, in seconds. None means the whole
    # video. Only meaningful for a single-video source.
    video_trim_start: float | None = None
    video_trim_end: float | None = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        # Drop unknown keys (old json) and ill-typed values (hand-edited json)
        if not isinstance(data, dict):
            return cls()
        return cls(**coerce_known_fields(cls, data))
