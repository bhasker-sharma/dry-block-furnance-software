"""
Reusable widgets shared across multiple screens.
Keeping them here avoids copy-paste and means a style fix applies everywhere.
"""
from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
import math


# ── Readout card ──────────────────────────────────────────────────────────────
class ReadoutWidget(QWidget):
    """
    Displays one temperature sensor value.
    Used on the Live Monitor and Execution screens.

    Why a custom widget instead of plain QLabel?
    We need a "card" layout with three zones: name/tag, big number, footer.
    Grouping that into one class lets us write Readout("Dry Block") and reuse it.
    """

    def __init__(self, name: str, tag: str, tag_color: str = '#3d7fff', parent=None):
        super().__init__(parent)
        self.setObjectName('readout')
        self.setMinimumSize(170, 130)

        self._name_label = QLabel(name)
        self._name_label.setObjectName('readout_name')

        self._tag_label = QLabel(tag)
        self._tag_label.setStyleSheet(
            f'background:{tag_color};color:#fff;border-radius:8px;'
            f'padding:2px 8px;font-size:11px;font-weight:600;'
        )
        self._tag_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        self._value_label = QLabel('––.–')
        self._value_label.setObjectName('readout_value')
        self._value_label.setProperty('idle', True)

        self._unit_label = QLabel('°C')
        self._unit_label.setObjectName('readout_unit')
        self._unit_label.setAlignment(Qt.AlignBottom)

        self._foot_label = QLabel('no signal')
        self._foot_label.setStyleSheet('font-size:11px;color:#a0aec0;')

        # top row: name + tag
        top = QHBoxLayout()
        top.addWidget(self._name_label)
        top.addStretch()
        top.addWidget(self._tag_label)

        # value row: big number + unit
        val_row = QHBoxLayout()
        val_row.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        val_row.addWidget(self._value_label)
        val_row.addWidget(self._unit_label)
        val_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.addLayout(top)
        layout.addLayout(val_row)
        layout.addWidget(self._foot_label)

    def set_value(self, value: float | None) -> None:
        """Call this every time a new temperature arrives."""
        if value is None:
            self._value_label.setText('––.–')
            self._value_label.setProperty('idle', True)
            self._foot_label.setText('no signal')
        else:
            self._value_label.setText(f'{value:.1f}')
            self._value_label.setProperty('idle', False)
            self._foot_label.setText('live · 1.0 s')
        # QSS property changes require a style refresh
        self._value_label.style().unpolish(self._value_label)
        self._value_label.style().polish(self._value_label)


# ── Timer ring ────────────────────────────────────────────────────────────────
class TimerRingWidget(QWidget):
    """
    Circular progress timer — same visual as the JSX TimerRing component.

    Why custom painting?
    Qt has QProgressBar but it's horizontal. A circular arc requires
    QPainter (Qt's drawing API). We draw the grey background arc, then
    the accent arc whose length represents remaining/total.
    """

    def __init__(self, total: int = 600, parent=None):
        super().__init__(parent)
        self._total    = total
        self._remaining = total
        self.setFixedSize(160, 160)

    def set_remaining(self, seconds: int) -> None:
        self._remaining = max(0, seconds)
        self.update()   # triggers paintEvent

    def set_total(self, total: int) -> None:
        self._total = max(1, total)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        margin = 16
        rect_size = min(w, h) - 2 * margin

        # centre the drawing rectangle
        x = (w - rect_size) / 2
        y = (h - rect_size) / 2

        # background arc (grey)
        pen = QPen(QColor('#e2e7ee'), 10, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(int(x), int(y), rect_size, rect_size, 0, 360 * 16)

        # foreground arc (accent colour)
        if self._total > 0:
            fraction = self._remaining / self._total
            span = int(fraction * 360 * 16)
            pen.setColor(QColor('#3d7fff'))
            painter.setPen(pen)
            # Qt arcs start at 3 o'clock; we want 12 o'clock = 90°
            painter.drawArc(int(x), int(y), rect_size, rect_size,
                            90 * 16, span)

        # time text in centre
        mm = self._remaining // 60
        ss = self._remaining  % 60
        painter.setPen(QColor('#1a2332'))
        font = QFont('Courier New', 18, QFont.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, w, h, Qt.AlignCenter, f'{mm:02d}:{ss:02d}')

        painter.end()


# ── Log console ───────────────────────────────────────────────────────────────
class ConsoleWidget(QFrame):
    """
    Scrollable log panel — shows time-stamped status messages.
    Uses a plain QLabel whose text grows; wrapped in a scroll area elsewhere.
    """
    MAX_LINES = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('console')
        self._lines: list[str] = []

        self._label = QLabel('awaiting connection…')
        self._label.setObjectName('console')
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._label.setTextFormat(Qt.RichText)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self._label)

    def append(self, kind: str, message: str) -> None:
        from datetime import datetime
        t = datetime.now().strftime('%H:%M:%S')
        colours = {'ok': '#22c55e', 'err': '#ef4444',
                   'warn': '#f59e0b', 'info': '#a0aec0'}
        colour = colours.get(kind, '#a0aec0')
        line = (
            f'<span style="color:#607080">{t}</span>&nbsp;&nbsp;'
            f'<span style="color:{colour}">{message}</span>'
        )
        self._lines.append(line)
        if len(self._lines) > self.MAX_LINES:
            self._lines.pop(0)
        self._label.setText('<br/>'.join(self._lines))


# ── Utility: styled button factory ───────────────────────────────────────────
def make_button(text: str, role: str = '', icon_char: str = '') -> 'QPushButton':
    """
    Create a QPushButton with the given QSS role property.
    role can be: 'primary', 'danger', 'success', 'ghost', ''
    """
    from PyQt5.QtWidgets import QPushButton
    btn = QPushButton(f'{icon_char}  {text}' if icon_char else text)
    if role:
        btn.setProperty('role', role)
    return btn
