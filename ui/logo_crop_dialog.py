"""In-app logo cropping dialog.

Lets the user pick any image and crop it into a shape whose width lands
in the range the report layout wants (LOGO_MIN_WIDTH-LOGO_MAX_WIDTH),
with height fixed at LOGO_HEIGHT, instead of rejecting anything that
isn't already that exact size. Height is fixed (not user-adjustable) so
the logo always prints at the same compact height in the certificate
header, regardless of how wide the user makes it.

The crop frame is fixed (like a profile-picture cropper) — the zoom
slider scales the image underneath it and dragging pans it, rather than
resizing a box over a static image. The Width spin box reshapes that
frame's aspect ratio live (and sets the final saved pixel width); the
result is always scaled to exactly width x LOGO_HEIGHT, regardless of
the source image's own resolution.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QRectF, QPointF, QSize
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QWidget,
    QDialogButtonBox, QSpinBox,
)

_CANVAS_MAX = QSize(640, 480)
_MAX_ZOOM_MULT = 3.0  # how far past the "fills the frame" scale you can zoom in


class _CropCanvas(QWidget):
    """A constant-size widget (always _CANVAS_MAX — never resizes, so
    reshaping the crop doesn't reflow the surrounding dialog) containing
    a crop frame: an inner rectangle, centered, sized to the target
    aspect ratio. The image is drawn at some zoom scale and pan offset
    relative to that frame; dragging pans it, set_zoom() scales it,
    set_target_size() reshapes the frame itself while preserving pan/zoom
    as best it can. Whatever's visible inside the frame IS the crop —
    `cropped_source_rect()` just inverts the current scale/offset back
    into the original image's coordinates."""

    def __init__(self, image: QImage, target_w: int, target_h: int, parent=None):
        super().__init__(parent)
        self.source = image
        self._pixmap = QPixmap.fromImage(image)
        self._zoom_fraction = 0.0
        self._frame_size = QSize(0, 0)
        self._frame_origin = QPointF(0, 0)
        self._scale = 1.0
        self._offset = QPointF(0, 0)

        self._drag_start_mouse: QPointF | None = None
        self._drag_start_offset: QPointF | None = None
        self.setCursor(Qt.OpenHandCursor)
        self.setFixedSize(_CANVAS_MAX)

        self.set_target_size(target_w, target_h)

    # -- shape ------------------------------------------------------------
    def set_target_size(self, target_w: int, target_h: int) -> None:
        """Reshape the crop frame to this aspect ratio, keeping whatever
        the frame is currently centered on (in image coordinates) and the
        current zoom fraction. The widget's own size never changes."""
        img_w, img_h = self.source.width(), self.source.height()

        if self._frame_size.width() == 0:
            center_img = QPointF(img_w / 2, img_h / 2)
        else:
            old_fw, old_fh = self._frame_size.width(), self._frame_size.height()
            center_img = QPointF(
                (old_fw / 2 - self._offset.x()) / self._scale,
                (old_fh / 2 - self._offset.y()) / self._scale,
            )

        aspect = target_w / target_h
        frame_w = min(_CANVAS_MAX.width(), _CANVAS_MAX.height() * aspect)
        frame_h = frame_w / aspect
        self._frame_size = QSize(round(frame_w), round(frame_h))
        self._frame_origin = QPointF(
            (_CANVAS_MAX.width() - self._frame_size.width()) / 2,
            (_CANVAS_MAX.height() - self._frame_size.height()) / 2,
        )

        # "Cover" scale — the smallest zoom at which the image still fully
        # covers the frame on both axes (no empty gaps at the edges).
        self._base_scale = max(self._frame_size.width() / img_w, self._frame_size.height() / img_h)
        self._scale = self._base_scale * (1 + (_MAX_ZOOM_MULT - 1) * self._zoom_fraction)

        fw, fh = self._frame_size.width(), self._frame_size.height()
        self._offset = QPointF(
            fw / 2 - center_img.x() * self._scale,
            fh / 2 - center_img.y() * self._scale,
        )
        self._clamp_offset()
        self.update()

    # -- zoom -----------------------------------------------------------
    def set_zoom(self, fraction: float) -> None:
        """fraction 0.0 = image just fills the frame, 1.0 = zoomed in to
        _MAX_ZOOM_MULT times that. Zooms toward whatever's currently at
        the frame's center."""
        old_scale = self._scale
        fw, fh = self._frame_size.width(), self._frame_size.height()
        center_img = QPointF(
            (fw / 2 - self._offset.x()) / old_scale,
            (fh / 2 - self._offset.y()) / old_scale,
        )

        self._zoom_fraction = fraction
        self._scale = self._base_scale * (1 + (_MAX_ZOOM_MULT - 1) * fraction)
        self._offset = QPointF(
            fw / 2 - center_img.x() * self._scale,
            fh / 2 - center_img.y() * self._scale,
        )
        self._clamp_offset()
        self.update()

    # -- mouse (pan) --------------------------------------------------------
    def mousePressEvent(self, ev) -> None:
        self._drag_start_mouse = ev.pos()
        self._drag_start_offset = QPointF(self._offset)
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_start_mouse is not None:
            # Deltas are translation-invariant, so this works the same
            # whether or not the frame is centered in a larger widget.
            delta = ev.pos() - self._drag_start_mouse
            self._offset = self._drag_start_offset + QPointF(delta.x(), delta.y())
            self._clamp_offset()
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        self._drag_start_mouse = None
        self.setCursor(Qt.OpenHandCursor)

    def _clamp_offset(self) -> None:
        fw, fh = self._frame_size.width(), self._frame_size.height()
        img_w = self.source.width() * self._scale
        img_h = self.source.height() * self._scale
        # Image must always fully cover the frame: left/top edge at or
        # before 0, right/bottom edge at or after the frame's far edge
        # (both in frame-local coordinates).
        x = min(0.0, max(fw - img_w, self._offset.x()))
        y = min(0.0, max(fh - img_h, self._offset.y()))
        self._offset = QPointF(x, y)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#1a2332'))

        fx, fy = self._frame_origin.x(), self._frame_origin.y()
        frame_rect = QRectF(fx, fy, self._frame_size.width(), self._frame_size.height())

        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.save()
        p.setClipRect(frame_rect)
        target = QRectF(
            fx + self._offset.x(), fy + self._offset.y(),
            self.source.width() * self._scale, self.source.height() * self._scale,
        )
        p.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))
        p.restore()

        pen = QPen(QColor('#38bdf8'))
        pen.setWidth(3)
        p.setPen(pen)
        p.drawRect(frame_rect.adjusted(1, 1, -1, -1))
        p.end()

    # -- result -------------------------------------------------------------
    def cropped_source_rect(self) -> tuple[int, int, int, int]:
        """The frame is the crop, so invert the current scale/pan back
        into source-image coordinates."""
        fw, fh = self._frame_size.width(), self._frame_size.height()
        x = (0 - self._offset.x()) / self._scale
        y = (0 - self._offset.y()) / self._scale
        w = fw / self._scale
        h = fh / self._scale
        # Clamp against float rounding at the image's own edges.
        x = min(max(x, 0), self.source.width() - w)
        y = min(max(y, 0), self.source.height() - h)
        return round(x), round(y), round(w), round(h)


class LogoCropDialog(QDialog):
    """Pick a region of `image_path` and return it as an image whose
    width is in [min_w, max_w] px (chosen via a spin box) and whose
    height is fixed at `height` px. Call exec_(); if it returns
    QDialog.Accepted, read the result via cropped_image()."""

    def __init__(self, image_path: str, min_w: int, max_w: int,
                 height: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Crop Logo')
        self._height = height
        self._canvas: _CropCanvas | None = None

        image = QImage(image_path)
        layout = QVBoxLayout(self)

        if image.isNull():
            layout.addWidget(QLabel('Could not read that image file.'))
            buttons = QDialogButtonBox(QDialogButtonBox.Ok)
            buttons.accepted.connect(self.reject)
            layout.addWidget(buttons)
            return

        hint = QLabel(
            'Drag the image to reposition it, use Zoom to scale it.\n'
            f'Width sets the shape; height is fixed at {height} px.'
        )
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet('color:#4a5568;font-size:11px;')
        layout.addWidget(hint)

        self._width_box = QSpinBox()
        self._width_box.setRange(min_w, max_w)
        self._width_box.setValue(max_w)
        self._width_box.setSuffix(' px')

        self._canvas = _CropCanvas(image, self._width_box.value(), self._height)
        canvas_row = QHBoxLayout()
        canvas_row.addStretch()
        canvas_row.addWidget(self._canvas)
        canvas_row.addStretch()
        layout.addLayout(canvas_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel('Width'))
        size_row.addWidget(self._width_box)
        size_row.addStretch()
        layout.addLayout(size_row)

        self._width_box.valueChanged.connect(self._on_size_changed)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel('Zoom'))
        zoom = QSlider(Qt.Horizontal)
        zoom.setRange(0, 100)
        zoom.setValue(0)
        zoom.valueChanged.connect(lambda v: self._canvas.set_zoom(v / 100))
        zoom_row.addWidget(zoom)
        layout.addLayout(zoom_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_size_changed(self) -> None:
        self._canvas.set_target_size(self._width_box.value(), self._height)

    def cropped_image(self) -> QImage:
        """Valid only after the dialog was accepted with a readable image."""
        x, y, w, h = self._canvas.cropped_source_rect()
        cropped = self._canvas.source.copy(x, y, w, h)
        return cropped.scaled(
            self._width_box.value(), self._height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
