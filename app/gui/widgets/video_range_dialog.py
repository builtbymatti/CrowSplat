"""Dialog to pick an in/out range on a single video before extraction.

The preview is built from ffmpeg stills rather than a Qt media player: ffmpeg
is already a hard dependency and decodes every container in VIDEO_EXTENSIONS,
while Qt's backend silently fails on several of them (.mts, .insv, .mxf). The
cost is that scrubbing shows stills instead of playing — acceptable, since the
point is to choose two timestamps, not to watch the video.
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.core.i18n import tr
from app.core.media import (
    extract_preview_frame,
    format_timecode,
    is_preferred_video,
    parse_timecode,
    probe_video_duration,
)

# Scrubbing fires a frame extraction per position; without a delay a drag would
# queue one ffmpeg call per pixel travelled.
_SCRUB_DEBOUNCE_MS = 120
# The slider works in integer steps, so the timeline is divided into this many.
_SLIDER_STEPS = 1000

# Workers still running when their dialog closes: kept alive here so a running
# QThread is never destroyed (SIGABRT), and dropped once they finish.
_ORPHAN_WORKERS: set = set()


class _FrameWorker(QThread):
    """Run one blocking media call (ffprobe/ffmpeg) off the GUI thread.

    Emits ``done(request_id, result)``; the receiver compares the id with the
    latest one it issued and drops anything older.
    """

    done = Signal(int, object)

    def __init__(self, request_id, func, *args, parent=None):
        super().__init__(parent)
        self._request_id = request_id
        self._func = func
        self._args = args

    def run(self):
        try:
            result = self._func(*self._args)
        except Exception:  # a failing probe/extract must read as "no result"
            result = None
        self.done.emit(self._request_id, result)


class VideoRangeDialog(QDialog):
    """Pick a start and an end timestamp. Returns them through `selected_range`."""

    def __init__(self, video_path, parent=None, initial=None):
        super().__init__(parent)
        self.video_path = str(video_path)
        # Filled in by the probe worker; None means "unknown" until `_ready`.
        self.duration = None
        self._ready = False
        self._initial = initial
        self.selected_range = None
        # Set before the unreadable-duration early return below, so the mark
        # handlers never meet a half-built object.
        self.start_s = 0.0
        self.end_s = 0.0

        self._tmpdir = tempfile.TemporaryDirectory(prefix="corbeau_preview_")
        self._frame_path = Path(self._tmpdir.name) / "frame.jpg"
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setSingleShot(True)
        self._scrub_timer.timeout.connect(self._render_frame)
        self._frame_req = 0
        self._frame_worker = None
        self._closed = False

        self.setWindowTitle(tr("video_range_title", "Sélection vidéo"))
        self.setMinimumWidth(680)
        self._build_ui()

        # Nothing is usable until the duration is known.
        self._set_controls_enabled(False)
        self.preview.setText(tr("video_range_loading", "Chargement…"))
        self._probe_worker = _FrameWorker(0, probe_video_duration, self.video_path, parent=self)
        self._probe_worker.done.connect(self._on_probe_done)
        self._probe_worker.start()

    def _set_controls_enabled(self, enabled):
        for widget in (self.slider, self.btn_in, self.btn_out, self.btn_reset,
                       self.edit_in, self.edit_out,
                       self.buttons.button(QDialogButtonBox.StandardButton.Ok)):
            widget.setEnabled(enabled)

    def _on_probe_done(self, _request_id, duration):
        if self._closed:
            return
        self.duration = duration
        self._ready = True
        if self.duration is None:
            # Unreadable duration means every timestamp below is meaningless.
            self.preview.setText(tr(
                "video_range_unreadable",
                "Durée de la vidéo illisible — sélection impossible.",
            ))
            return  # controls (incl. Reset) stay disabled

        self._set_controls_enabled(True)
        initial = self._initial
        start, end = 0.0, self.duration
        if initial:
            start = max(0.0, float(initial.get("start", 0.0)))
            end = min(self.duration, float(initial.get("end", self.duration)))
            if end <= start:
                start, end = 0.0, self.duration
        self.start_s, self.end_s = start, end

        if not is_preferred_video(self.video_path):
            # Every supported container can be trimmed; the broadcast and
            # action-camera ones just seek less precisely, so a mark can land a
            # keyframe away from what the preview showed.
            self.lbl_hint.setText(tr(
                "video_range_container_hint",
                "Format non idéal pour la découpe : le positionnement peut manquer "
                "de précision. Convertissez en MP4 ou MOV pour un repérage exact.",
            ))
            self.lbl_hint.setVisible(True)

        self._sync_labels()
        self._render_frame()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(320)
        self.preview.setStyleSheet("background: #1b1d24; border-radius: 4px;")
        layout.addWidget(self.preview)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, _SLIDER_STEPS)
        self.slider.valueChanged.connect(self._on_scrub)
        layout.addWidget(self.slider)

        self.lbl_position = QLabel()
        self.lbl_position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_position)

        marks = QHBoxLayout()
        self.btn_in = QPushButton(tr("video_range_set_in", "Point d'entrée"))
        self.btn_in.clicked.connect(self._set_in)
        # Typed entry next to each button: reading a timecode off another tool
        # and copying it in is faster and more precise than dragging a slider.
        self.edit_in = QLineEdit()
        self.edit_in.setMaximumWidth(110)
        self.edit_in.setPlaceholderText("00:00.0")
        self.edit_in.editingFinished.connect(self._apply_typed_in)

        self.btn_out = QPushButton(tr("video_range_set_out", "Point de sortie"))
        self.btn_out.clicked.connect(self._set_out)
        self.edit_out = QLineEdit()
        self.edit_out.setMaximumWidth(110)
        self.edit_out.setPlaceholderText("00:00.0")
        self.edit_out.editingFinished.connect(self._apply_typed_out)

        self.btn_reset = QPushButton(tr("video_range_reset", "Toute la vidéo"))
        self.btn_reset.clicked.connect(self._reset)

        for widget in (self.btn_in, self.edit_in, self.btn_out, self.edit_out, self.btn_reset):
            marks.addWidget(widget)
        layout.addLayout(marks)

        self.lbl_hint = QLabel()
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #c8a45c;")
        self.lbl_hint.setVisible(False)
        layout.addWidget(self.lbl_hint)

        self.lbl_range = QLabel()
        self.lbl_range.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_range.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.lbl_range)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            tr("video_range_validate", "Valider")
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("btn_cancel", "Annuler")
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    # ── Position ────────────────────────────────────────────────────────────
    @property
    def position(self) -> float:
        if self.duration is None:
            return 0.0
        return self.slider.value() / _SLIDER_STEPS * self.duration

    def _on_scrub(self, _value=None):
        self._sync_labels()
        self._scrub_timer.start(_SCRUB_DEBOUNCE_MS)

    def _render_frame(self):
        """Request a still for the current position (asynchronous)."""
        if self.duration is None or self._closed:
            return
        self._frame_req += 1
        if self._frame_worker is not None:
            return  # the running one hands over to the latest request when done
        self._start_frame_worker()

    def _start_frame_worker(self):
        self.preview.setText(tr("video_range_loading", "Chargement…"))
        worker = _FrameWorker(self._frame_req, extract_preview_frame,
                              self.video_path, self.position, self._frame_path, parent=self)
        worker.done.connect(self._on_frame_done)
        self._frame_worker = worker
        worker.start()

    def _on_frame_done(self, request_id, ok):
        worker, self._frame_worker = self._frame_worker, None
        if worker is not None:
            worker.wait()
        if self._closed:
            return
        if request_id != self._frame_req:
            # Stale: the slider moved on while this one was running.
            if self._frame_worker is None:
                self._start_frame_worker()
            return
        if not ok:
            self.preview.setText(tr("video_range_no_frame", "Aperçu indisponible"))
            return
        pix = QPixmap(str(self._frame_path))
        if pix.isNull():
            self.preview.setText(tr("video_range_no_frame", "Aperçu indisponible"))
            return
        self.preview.setPixmap(pix.scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def done(self, result):
        """Stop pending work and remove the preview directory on any close."""
        self._closed = True
        self._scrub_timer.stop()
        running = [w for w in (getattr(self, "_probe_worker", None), self._frame_worker)
                   if w is not None and w.isRunning()]
        if running:
            # Never destroy a running QThread: detach it and clean up after it.
            for w in running:
                w.setParent(None)
                _ORPHAN_WORKERS.add(w)
                w.finished.connect(lambda w=w: _ORPHAN_WORKERS.discard(w))
                w.finished.connect(self._tmpdir.cleanup)  # idempotent
        else:
            self._tmpdir.cleanup()
        super().done(result)

    # ── Marks ───────────────────────────────────────────────────────────────
    def _set_in(self):
        self.start_s = self.position
        # Keeping start < end matters: the extraction turns them into a
        # duration, and a negative one makes ffmpeg produce nothing at all.
        if self.end_s <= self.start_s:
            self.end_s = self.duration
        self._sync_labels()

    def _set_out(self):
        self.end_s = self.position
        if self.end_s <= self.start_s:
            self.start_s = 0.0
        self._sync_labels()

    def _reset(self):
        self.start_s, self.end_s = 0.0, self.duration
        self._sync_labels()

    def _apply_typed_in(self):
        """Read the typed in point; on nonsense, put the current value back."""
        value = parse_timecode(self.edit_in.text())
        if value is None or self.duration is None or value >= self.end_s:
            self._sync_labels()
            return
        self.start_s = min(max(0.0, value), self.duration)
        self._sync_labels()

    def _apply_typed_out(self):
        value = parse_timecode(self.edit_out.text())
        if value is None or self.duration is None or value <= self.start_s:
            self._sync_labels()
            return
        self.end_s = min(value, self.duration)
        self._sync_labels()

    def _sync_labels(self):
        if self.duration is None:
            return
        self.lbl_position.setText(
            f"{format_timecode(self.position)} / {format_timecode(self.duration)}"
        )
        span = max(0.0, self.end_s - self.start_s)
        self.lbl_range.setText(tr("video_range_summary").format(
            format_timecode(self.start_s), format_timecode(self.end_s), format_timecode(span)
        ))
        # Refreshed without signals: setText would otherwise re-enter the
        # editingFinished handler that may have just called us.
        for field, value in ((self.edit_in, self.start_s), (self.edit_out, self.end_s)):
            field.blockSignals(True)
            field.setText(format_timecode(value))
            field.blockSignals(False)

    # ── Result ──────────────────────────────────────────────────────────────
    def _accept(self):
        if self.duration is None:
            self.reject()
            return
        # A full-span selection is reported as None so callers, the saved
        # configuration and the ffmpeg command all stay free of a no-op trim.
        if self.start_s <= 0.0 and self.end_s >= self.duration:
            self.selected_range = None
        else:
            self.selected_range = {"start": round(self.start_s, 3),
                                   "end": round(self.end_s, 3)}
        self.accept()
