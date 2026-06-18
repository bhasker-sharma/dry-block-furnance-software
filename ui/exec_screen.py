"""
Calibration Execution Screen.
Shows live temps, the 3-phase stepper, and the countdown timer ring.
Capture is fully automatic — no Pass/Fail, no operator confirmation.
Matches screens_b.jsx : ExecScreen component.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.widgets import ReadoutWidget, TimerRingWidget, make_button
from calibration.engine import Phase


class ExecScreen(QWidget):
    stop_requested = pyqtSignal()

    PHASES = ['Stabilizing', 'Saving', 'Completed']

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ──────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)

        vt = QVBoxLayout()
        self._title_lbl = QLabel('Calibration in Progress')
        self._title_lbl.setObjectName('screen_title')
        self._sub_lbl = QLabel('—')
        self._sub_lbl.setObjectName('screen_sub')
        vt.addWidget(self._title_lbl)
        vt.addWidget(self._sub_lbl)
        tb.addLayout(vt)
        tb.addStretch()

        self._point_pill = QLabel('Point 1 of —')
        self._point_pill.setStyleSheet(
            'background:#ebf2ff;color:#3d7fff;border-radius:10px;'
            'padding:4px 12px;font-size:12px;font-weight:600;'
        )
        tb.addWidget(self._point_pill)

        stop_btn = make_button('■  Stop', 'danger')
        stop_btn.clicked.connect(self.stop_requested)
        tb.addWidget(stop_btn)
        root.addWidget(topbar)

        # ── scrollable content ───────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(14)

        # stepper
        cv.addWidget(self._build_stepper())

        # middle row: left (target + readouts + table) + right (timer + actions)
        mid = QHBoxLayout()
        mid.setSpacing(14)
        mid.addLayout(self._build_left(), 3)
        mid.addWidget(self._build_right(), 0)
        cv.addLayout(mid)
        cv.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------
    def _build_stepper(self) -> QGroupBox:
        box = QGroupBox()
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        h = QHBoxLayout(box)
        h.setContentsMargins(24, 14, 24, 14)
        h.setSpacing(0)

        self._step_labels: list[QLabel] = []
        for i, phase in enumerate(self.PHASES):
            if i > 0:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet('color:#d1d9e6;')
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                h.addWidget(line, 1)

            col = QVBoxLayout()
            col.setAlignment(Qt.AlignHCenter)
            dot = QLabel(str(i + 1))
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet(
                'border-radius:14px;background:#e2e7ee;color:#6b7a90;font-weight:700;'
            )
            lbl = QLabel(phase)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet('font-size:11px;color:#6b7a90;margin-top:4px;')
            col.addWidget(dot, alignment=Qt.AlignHCenter)
            col.addWidget(lbl, alignment=Qt.AlignHCenter)
            h.addLayout(col)
            self._step_labels.append((dot, lbl))

        return box

    def _build_left(self) -> QVBoxLayout:
        v = QVBoxLayout()
        v.setSpacing(12)

        # target + live error
        target_card = QGroupBox()
        target_card.setObjectName('card')
        target_card.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        th = QHBoxLayout(target_card)
        th.setContentsMargins(18, 14, 18, 14)

        sp_col = QVBoxLayout()
        sp_lbl = QLabel('Active Setpoint')
        sp_lbl.setStyleSheet('font-size:11px;color:#6b7a90;font-weight:600;')
        self._sp_value = QLabel('—')
        self._sp_value.setStyleSheet(
            'font-family:"Courier New";font-size:48px;font-weight:700;color:#1a2332;'
        )
        sp_col.addWidget(sp_lbl)
        sp_col.addWidget(self._sp_value)
        th.addLayout(sp_col)
        th.addStretch()

        err_chip = QVBoxLayout()
        err_chip.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        err_lbl = QLabel('Live Error (UUT − RTD)')
        err_lbl.setStyleSheet('font-size:11px;color:#6b7a90;')
        self._err_value = QLabel('—')
        self._err_value.setStyleSheet('font-size:22px;font-weight:700;font-family:"Courier New";')
        err_chip.addWidget(err_lbl)
        err_chip.addWidget(self._err_value)
        th.addLayout(err_chip)
        v.addWidget(target_card)

        # readouts
        ro_row = QHBoxLayout()
        ro_row.setSpacing(10)
        self._ro_fur    = ReadoutWidget('Dry Block',    'Dry Block', '#6366f1')
        self._ro_master = ReadoutWidget('Standard RTD', 'Ref',       '#3d7fff')
        self._ro_uut    = ReadoutWidget('UUT',          'UUT',       '#f59e0b')
        for r in (self._ro_fur, self._ro_master, self._ro_uut):
            r.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            ro_row.addWidget(r)
        v.addLayout(ro_row)

        # saved points table
        tbl_box = QGroupBox('Saved Points')
        tbl_box.setObjectName('card')
        tbl_box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        tbl_v = QVBoxLayout(tbl_box)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ['SP °C', 'Dry Block', 'RTD', 'UUT', 'Error', 'Time']
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QTableWidget.NoSelection)
        self._table.setMinimumHeight(160)
        tbl_v.addWidget(self._table)
        v.addWidget(tbl_box)

        return v

    def _build_right(self) -> QGroupBox:
        box = QGroupBox()
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        box.setFixedWidth(220)
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 16, 14, 16)
        v.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self._timer_ring = TimerRingWidget(total=600)
        v.addWidget(self._timer_ring, alignment=Qt.AlignHCenter)

        self._phase_note = QLabel('Waiting for fluctuation to settle.')
        self._phase_note.setWordWrap(True)
        self._phase_note.setAlignment(Qt.AlignCenter)
        self._phase_note.setStyleSheet('font-size:11px;color:#6b7a90;')
        v.addWidget(self._phase_note)

        self._view_report_btn = make_button('View Report', 'primary')
        v.addWidget(self._view_report_btn)

        self._view_report_btn.setVisible(False)
        return box

    # ------------------------------------------------------------------
    # Public API called by MainWindow
    # ------------------------------------------------------------------
    def start(self, cert: str, customer: str, total_points: int, max_seconds: int) -> None:
        """Reset the screen for a new run."""
        self._sub_lbl.setText(f'{cert}  ·  {customer or "—"}')
        self._point_pill.setText(f'Point 1 of {total_points}')
        self._table.setRowCount(0)
        self._timer_ring.set_total(max_seconds)
        self._timer_ring.set_remaining(max_seconds)
        self._view_report_btn.setVisible(False)
        self.set_phase(Phase.STABILIZING)

    def update_temperatures(self, fur, master, uut) -> None:
        self._ro_fur.set_value(fur)
        self._ro_master.set_value(master)
        self._ro_uut.set_value(uut)
        if master is not None and uut is not None:
            err = uut - master
            sign = '+' if err >= 0 else ''
            self._err_value.setText(f'{sign}{err:.2f}')
            self._err_value.setStyleSheet(
                f'font-size:22px;font-weight:700;font-family:"Courier New";'
                f'color:{"#ef4444" if abs(err) > 1 else "#1a2332"};'
            )

    def set_setpoint(self, sp: float, idx: int, total: int) -> None:
        self._sp_value.setText(f'{sp:.0f} °C')
        self._point_pill.setText(f'Point {idx + 1} of {total}')

    def set_phase(self, phase: Phase) -> None:
        phase_map = {
            Phase.STABILIZING: (0, 'Monitoring fluctuation. Capture happens automatically.'),
            Phase.SAVING:      (1, 'Point captured — moving to next setpoint.'),
            Phase.COMPLETED:   (2, 'All setpoints complete. Report generated.'),
        }
        idx, note = phase_map[phase]
        self._phase_note.setText(note)

        for i, (dot, lbl) in enumerate(self._step_labels):
            if i < idx:
                dot.setStyleSheet('border-radius:14px;background:#22c55e;color:#fff;font-weight:700;')
            elif i == idx:
                dot.setStyleSheet('border-radius:14px;background:#3d7fff;color:#fff;font-weight:700;')
            else:
                dot.setStyleSheet('border-radius:14px;background:#e2e7ee;color:#6b7a90;font-weight:700;')

        self._view_report_btn.setVisible(phase == Phase.COMPLETED)

    def set_remaining(self, seconds: int) -> None:
        self._timer_ring.set_remaining(seconds)

    def add_saved_point(self, sp, fur, master, uut, time_str) -> None:
        err = uut - master
        row = self._table.rowCount()
        self._table.insertRow(row)
        cells = [
            f'{sp:.0f}', f'{fur:.1f}', f'{master:.2f}', f'{uut:.2f}',
            f'{("+" if err >= 0 else "")}{err:.2f}',
            time_str
        ]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, col, item)

    @property
    def view_report_btn(self) -> QPushButton:
        return self._view_report_btn
