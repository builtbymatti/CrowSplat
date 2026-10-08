from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.core.i18n import add_language_observer, tr


class ModelCard(QFrame):
    """One row of the Upscale model gallery: name, description, size, action.

    The panel's dropdown only tells installed models from missing ones; the
    gallery is where a model is described, weighed, fetched or removed. The card
    owns no worker: it emits, the panel downloads and calls ``refresh``.
    """

    download_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, model, models_dir: Path):
        super().__init__()
        self.model = model
        self.models_dir = models_dir
        self._action_handler = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build()
        add_language_observer(self.refresh)

    def _set_action_handler(self, handler):
        """(Re)connect the action button, disconnecting only the previous
        handler — a bare disconnect() raises a RuntimeWarning under PySide6."""
        if self._action_handler is not None:
            self.btn_action.clicked.disconnect(self._action_handler)
        self._action_handler = handler
        self.btn_action.clicked.connect(handler)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        info = QVBoxLayout()
        self.lbl_name = QLabel(f"<b>{self.model.label}</b>")
        self.lbl_desc = QLabel(self.model.description)
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color: #888; font-size: 11px;")
        info.addWidget(self.lbl_name)
        info.addWidget(self.lbl_desc)
        layout.addLayout(info, stretch=1)

        badge = QLabel(f"x{self.model.scale}")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(32)
        badge.setStyleSheet(
            "background: #2a82da; color: white; border-radius: 4px; "
            "font-size: 11px; font-weight: bold; padding: 2px 4px;"
        )
        layout.addWidget(badge)

        self.lbl_status = QLabel()
        self.lbl_status.setFixedWidth(120)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_status)

        self.btn_action = QPushButton()
        self.btn_action.setFixedWidth(90)
        layout.addWidget(self.btn_action)

        self.refresh()

    def refresh(self):
        """Re-read the model's state on disk and rebuild the row's right side."""
        if self.model.is_downloaded(self.models_dir):
            size = self.model.size_on_disk_mb(self.models_dir)
            self.lbl_status.setText(f"✅ {size} MB")
            self.lbl_status.setStyleSheet("color: #44aa44; font-size: 11px;")
            self.btn_action.setText(tr("up_delete", "Supprimer"))
            self.btn_action.setStyleSheet("color: #cc4444;")
            self._set_action_handler(lambda: self.delete_requested.emit(self.model.id))
            self.btn_action.setEnabled(True)
        elif self.model.bundled and not self.model.url_bin:
            # Shipped inside the upscayl-bin archive: nothing to fetch, nothing
            # to delete, and no files of our own to measure.
            self.lbl_status.setText(tr("up_bundled", "Inclus"))
            self.lbl_status.setStyleSheet("color: #888; font-size: 11px;")
            self.btn_action.setText("—")
            self.btn_action.setEnabled(False)
        else:
            self.lbl_status.setText(tr("up_not_installed", "Non installé"))
            self.lbl_status.setStyleSheet("color: #888; font-size: 11px;")
            self.btn_action.setText(tr("up_download", "Télécharger"))
            self.btn_action.setStyleSheet("")
            self._set_action_handler(lambda: self.download_requested.emit(self.model.id))
            self.btn_action.setEnabled(True)

    def set_downloading(self, active: bool):
        self.btn_action.setEnabled(not active)
        if active:
            self.lbl_status.setText(tr("up_downloading", "Téléchargement…"))
            self.lbl_status.setStyleSheet("color: #2a82da; font-size: 11px;")
