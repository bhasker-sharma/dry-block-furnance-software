from pathlib import Path

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
    QLineEdit, QGroupBox, QFormLayout, QScrollArea, QFrame,
    QMessageBox, QPushButton, QDoubleSpinBox, QDialog,
    QDialogButtonBox, QInputDialog, QSizePolicy, QFileDialog,
    QPlainTextEdit
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QValidator, QImage, QPixmap

from ui.widgets import make_button
from db.settings_store import (
    SettingsStore, STABILITY_LIMIT_MIN, STABILITY_LIMIT_MAX, clamp_stability_limit,
    REQUIRED_LOGO_SIZE,
)

MANUFACTURER_PIN = '123456'


def _is_unimodal(values: list[float]) -> bool:
    """True if values rise strictly to at most one peak and then fall
    strictly — i.e. at most one reversal from ascending to descending.

    Purely ascending (peak at the last element) and purely descending
    (peak at the first element) both qualify, since a run in only one
    direction never reverses. Walk the ascending run from the start, then
    the descending run from wherever that stopped; if that reaches the
    last element, there was only ever one reversal (the peak) — anything
    left over means a second reversal (a valley then another rise, or a
    repeated value), which isn't a valid sweep order.
    """
    n = len(values)
    if n <= 2:
        return True
    i = 0
    while i + 1 < n and values[i] < values[i + 1]:
        i += 1
    while i + 1 < n and values[i] > values[i + 1]:
        i += 1
    return i == n - 1


class _UnboundedSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox with its own permissive validator.

    Qt's default QDoubleSpinBox validator can refuse to let you type past
    a certain number of digits when the minimum is negative (observed:
    stuck at 999, couldn't reach 1000) — explicit setDecimals() didn't fix
    it, so rather than keep guessing at the exact internal heuristic, this
    overrides validate() to accept any string that parses as a number,
    leaving out-of-range correction to Qt's normal fixup()-on-focus-lost
    behavior (unchanged, still clamps to min/max once you tab away).

    While editing, Qt keeps the suffix (' °C') inside the text handed to
    validate() — e.g. typing into an empty box produces "9 °C", "99 °C",
    "999 °C", etc, not bare digits. The first version of this override ran
    float() on that raw string, which always raised (suffix isn't
    numeric), so every keystroke came back Invalid and fixup() reverted
    the field to its last committed value the moment focus left it —
    multi-digit entry (e.g. 600, 9999) looked like it silently "didn't
    take". Strip prefix/suffix before parsing, same as Qt's own default
    validator does internally, so typed numbers are actually accepted."""

    def validate(self, text: str, pos: int):
        stripped = text
        prefix, suffix = self.prefix(), self.suffix()
        if prefix and stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
        if suffix and stripped.endswith(suffix):
            stripped = stripped[:len(stripped) - len(suffix)]
        stripped = stripped.strip()

        if stripped in ('', '-'):
            return (QValidator.Intermediate, text, pos)
        try:
            float(stripped)
        except ValueError:
            return (QValidator.Invalid, text, pos)
        return (QValidator.Acceptable, text, pos)


class SettingsScreen(QWidget):
    save_requested = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = SettingsStore()
        self._comm = None   # set via set_comm() once MainWindow creates the comm object
        self._cmc_rows: list[tuple] = []
        self._sp_widgets: list[QDoubleSpinBox] = []
        self._sp_rows: list[tuple] = []
        self._u_logo_path: str | None = None
        self._build_ui()
        self._load_into_ui()

    def set_comm(self, comm) -> None:
        self._comm = comm

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top bar ───────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setObjectName('topbar')
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 12, 20, 12)
        vt = QVBoxLayout()
        title = QLabel('Communication & Settings')
        title.setObjectName('screen_title')
        sub = QLabel('Serial port, CMC, setpoints and Master RTD')
        sub.setObjectName('screen_sub')
        vt.addWidget(title)
        vt.addWidget(sub)
        tb.addLayout(vt)
        tb.addStretch()
        save_btn = make_button('✓  Save', 'primary')
        save_btn.clicked.connect(self._on_save)
        tb.addWidget(save_btn)
        root.addWidget(topbar)

        # ── scrollable content ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(20, 16, 20, 16)
        cv.setSpacing(16)
        cv.setAlignment(Qt.AlignTop)

        # Range spinboxes are state only here — no card on this screen.
        # They're edited inside the PIN-gated Manufacturer Settings dialog
        # (_show_manufacturer_dialog) but read from here by CMC/setpoint
        # row creation and by Save validation, so they must exist before
        # any of that runs.
        self._init_range_state()

        # A single shared grid instead of 3 independent QHBoxLayouts — with
        # separate row layouts, each row's left/right split is computed
        # from only that row's two widgets, so the column boundary can
        # land at a different x position per row (most visible once the
        # window is narrow enough that some content can't shrink further),
        # which looked like misaligned columns. One QGridLayout computes
        # both column widths once for the whole grid, so every row shares
        # the exact same boundary at any window size.
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._build_serial_card(),       0, 0)
        grid.addWidget(self._build_user_profile_card(), 0, 1)
        grid.addWidget(self._build_setpoints_card(),    1, 0)
        grid.addWidget(self._build_master_card(),       1, 1)
        grid.addWidget(self._build_cmc_card(),          2, 0)
        grid.addWidget(self._build_manufacturer_card(), 2, 1)
        cv.addLayout(grid)

        scroll.setWidget(content)
        root.addWidget(scroll)

    # ------------------------------------------------------------------
    def _build_user_profile_card(self) -> QGroupBox:
        """Company identity — logo, name, address, certificate prefix.
        Stored under user_profile in settings.json for future use when
        report_gen builds the certificate header."""
        box = QGroupBox('User Settings — Company Details')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        outer = QHBoxLayout(box)
        outer.setSpacing(20)

        # -- logo column --
        logo_col = QVBoxLayout()
        req_w, req_h = REQUIRED_LOGO_SIZE

        self._logo_preview = QLabel('No logo\nuploaded')
        self._logo_preview.setFixedSize(req_w // 2, req_h // 2)
        self._logo_preview.setAlignment(Qt.AlignCenter)
        self._logo_preview.setStyleSheet(
            'border:1px dashed #d1d9e6;color:#a0aec0;font-size:10px;'
            'background:#f7f9fc;border-radius:4px;'
        )
        logo_col.addWidget(self._logo_preview, 0, Qt.AlignHCenter)

        logo_btns = QHBoxLayout()
        upload_btn = make_button('Upload Logo…', 'ghost')
        upload_btn.clicked.connect(self._on_upload_logo)
        remove_btn = make_button('Remove', 'ghost')
        remove_btn.clicked.connect(self._on_remove_logo)
        logo_btns.addWidget(upload_btn)
        logo_btns.addWidget(remove_btn)
        logo_col.addLayout(logo_btns)

        logo_note = QLabel(f'Exactly {req_w} × {req_h} px.\n')
        logo_note.setStyleSheet('font-size:10px;color:#a0aec0;')
        logo_note.setAlignment(Qt.AlignHCenter)
        logo_note.setWordWrap(True)
        logo_col.addWidget(logo_note)
        logo_col.addStretch()

        outer.addLayout(logo_col)

        # -- form column --
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self._u_company_name = QLineEdit()
        self._u_company_name.setPlaceholderText('Company name')

        self._u_company_address = QPlainTextEdit()
        self._u_company_address.setPlaceholderText('Company address')
        self._u_company_address.setFixedHeight(56)

        self._u_cert_prefix = QLineEdit()
        self._u_cert_prefix.setPlaceholderText('e.g. TIPL-CAL-')

        form.addRow('Company Name',      self._u_company_name)
        form.addRow('Company Address',   self._u_company_address)
        form.addRow('Certificate Number Prefix', self._u_cert_prefix)

        outer.addLayout(form, 1)
        return box

    def _on_upload_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, 'Choose Company Logo', str(Path.home()),
            'Images (*.png *.jpg *.jpeg *.bmp)'
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, 'Invalid Image', 'Could not read that image file.')
            return
        req_w, req_h = REQUIRED_LOGO_SIZE
        if img.width() != req_w or img.height() != req_h:
            QMessageBox.warning(
                self, 'Wrong Dimensions',
                f'Logo must be exactly {req_w} × {req_h} px.\n'
                f'Selected image is {img.width()} × {img.height()} px.'
            )
            return
        self._u_logo_path = self._store.save_logo(path)
        self._refresh_logo_preview()

    def _on_remove_logo(self) -> None:
        if self._u_logo_path is None:
            return
        self._store.remove_logo()
        self._u_logo_path = None
        self._refresh_logo_preview()

    def _refresh_logo_preview(self) -> None:
        req_w, req_h = REQUIRED_LOGO_SIZE
        if self._u_logo_path and Path(self._u_logo_path).exists():
            pix = QPixmap(self._u_logo_path)
            self._logo_preview.setPixmap(
                pix.scaled(req_w // 2, req_h // 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._logo_preview.setPixmap(QPixmap())
            self._logo_preview.setText('No logo\nuploaded')

    def _build_serial_card(self) -> QGroupBox:
        box = QGroupBox('Serial Port Configuration')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(14)

        self._iface  = QComboBox()
        self._iface.addItems(['RS-232'])
        self._iface.setEnabled(False)
        self._iface.setToolTip(
            'The 9144 has a single RS-232 (DB-9) interface — no USB. If your PC '
            'connects via a USB-to-serial adapter cable, Windows still presents '
            'it as a COM port below, so nothing else changes.'
        )

        self._port   = QComboBox()
        self._port.setEditable(True)
        self._port.addItems(['COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8'])
        self._port.setCurrentText('COM3')
        self._port.lineEdit().setPlaceholderText('COM3 or TCP:127.0.0.1:5025')

        self._baud   = QComboBox()
        self._baud.addItems(['1200','2400','4800','9600','19200','38400'])
        self._baud.setCurrentText('9600')
        self._baud.setToolTip(
            'Must match the baud rate set on the instrument itself '
            '(MENU|SYSTEM MENU|SYSTEM SETUP|COMM SETUP). Range fixed by the 9144.'
        )

        self._timeout = QLineEdit('1000')
        self._timeout.setPlaceholderText('milliseconds')

        self._retry   = QLineEdit('3')
        self._retry.setPlaceholderText('number of retries')

        form.addRow('Interface',     self._iface)
        form.addRow('COM Port',      self._port)
        form.addRow('Baud Rate',     self._baud)
        form.addRow('Timeout (ms)',  self._timeout)
        form.addRow('Retry Count',   self._retry)

        fixed = QLabel(
            'Baud rate Should match the Intrument Baud rate in use.\n'
            'Com port should be verified by the device manager - ports section'
        )
        fixed.setStyleSheet('font-size:11px;color:#a0aec0;padding:4px 0;')
        fixed.setWordWrap(True)
        form.addRow('', fixed)

        return box

    def _init_range_state(self) -> None:
        """Dry block calibrator range — state only, no card on this
        screen. Editing lives in the PIN-gated Manufacturer Settings
        dialog (_show_manufacturer_dialog) now; these spinboxes just hold
        the current value for CMC/setpoint row bounds and Save
        validation, same as before the move."""
        self._range_min = _UnboundedSpinBox()
        self._range_min.setRange(-200, 999999)
        self._range_min.setDecimals(0)
        self._range_min.setSingleStep(100)
        self._range_min.setSuffix(' °C')
        self._range_max = _UnboundedSpinBox()
        self._range_max.setRange(-200, 999999)
        self._range_max.setDecimals(0)
        self._range_max.setSingleStep(100)
        self._range_max.setSuffix(' °C')
        self._range_max.setValue(300)

        self._range_min.editingFinished.connect(self._on_range_changed)
        self._range_max.editingFinished.connect(self._on_range_changed)

    def _on_range_changed(self) -> None:
        """Re-apply the (possibly just-edited, not-yet-saved) calibrator
        range to every already-added CMC/setpoint row's spinbox.

        A row's spinbox only gets setRange() once, at the moment it's
        created — via the '+ Add …' button, using whatever the range
        fields showed *then*. If the range fields are edited afterwards,
        existing rows never hear about it and keep clamping to the old
        bounds, which made it look like you had to Save the range before
        you could add/edit a CMC point or setpoint in the new part of it.
        Refreshing every row's bounds here means the range fields alone
        are the source of truth, live — no save-first step needed."""
        rmin, rmax = self._range_min.value(), self._range_max.value()
        if rmin >= rmax:
            return
        for temp_spin, _, _ in self._cmc_rows:
            temp_spin.setRange(rmin, rmax)
        for spin in self._sp_widgets:
            spin.setRange(max(0.0, rmin), rmax)

    def _build_cmc_card(self) -> QGroupBox:
        box = QGroupBox('CMC — Calibration & Measurement Capability')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        row = QHBoxLayout()
        row.addWidget(QLabel('CMC Status'))
        self._cmc_status = QComboBox()
        self._cmc_status.addItems(['OFF', 'ON'])
        self._cmc_status.currentTextChanged.connect(self._on_cmc_toggle)
        row.addWidget(self._cmc_status)
        row.addStretch()
        v.addLayout(row)

        self._cmc_count_label = QLabel('0 CMC points')
        self._cmc_count_label.setStyleSheet('font-size:11px;color:#6b7a90;')
        v.addWidget(self._cmc_count_label)

        self._cmc_container = QVBoxLayout()
        self._cmc_container.setSpacing(5)
        v.addLayout(self._cmc_container)

        self._cmc_add_btn = make_button('+ Add CMC point', 'ghost')
        self._cmc_add_btn.clicked.connect(lambda: self._add_cmc_row(0.0, 0.0))
        v.addWidget(self._cmc_add_btn)

        note = QLabel(
            'When CMC is ON, at least one CMC point is required before setpoints can be added.'
        )
        note.setStyleSheet('font-size:11px;color:#a0aec0;margin-top:6px;')
        note.setWordWrap(True)
        v.addWidget(note)

        return box

    def _build_setpoints_card(self) -> QGroupBox:
        box = QGroupBox('Setpoints  (ascending °C)')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        v = QVBoxLayout(box)

        self._sp_count_label = QLabel('0 / 10')
        self._sp_count_label.setStyleSheet('font-size:11px;color:#6b7a90;')
        v.addWidget(self._sp_count_label)

        order_note = QLabel(
        'Setpoint Order: purely ascending, purely descending, or ascending then '
        'descending (e.g. 200, 300, 400, 700, 600, 250, 100) '
        'Reversing direction more than once is not permitted'
        )

        order_note.setStyleSheet(
            'color:#6b7a90;font-size:11px;background:#f7f9fc;'
            'border-radius:5px;padding:4px 8px;'
        )
        order_note.setWordWrap(True)
        v.addWidget(order_note)

        self._sp_container = QVBoxLayout()
        self._sp_container.setSpacing(5)
        v.addLayout(self._sp_container)

        add_row = QHBoxLayout()
        self._sp_add_btn = make_button('+ Add setpoint', 'ghost')
        self._sp_add_btn.clicked.connect(lambda: self._add_sp_row(0.0))
        add_row.addWidget(self._sp_add_btn)
        add_row.addStretch()
        sp_save_btn = make_button('Save Setpoints', 'primary')
        sp_save_btn.clicked.connect(self._on_save)
        add_row.addWidget(sp_save_btn)
        v.addLayout(add_row)

        self._sp_lock_note = QLabel('Add CMC points first — CMC is ON.')
        self._sp_lock_note.setStyleSheet('font-size:11px;color:#f59e0b;margin-top:6px;')
        self._sp_lock_note.setWordWrap(True)
        self._sp_lock_note.setVisible(False)
        v.addWidget(self._sp_lock_note)

        v.addStretch()
        return box

    def _build_master_card(self) -> QGroupBox:
        """Master RTD (Standard Reference Sensor) — lab-wide, set once here."""
        box = QGroupBox('Standard Reference Sensor')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        form = QFormLayout(box)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(12)

        self._m_type   = QLineEdit(); self._m_type.setPlaceholderText('e.g. Platinum RTD')
        self._m_make   = QLineEdit(); self._m_make.setPlaceholderText('Manufacturer name')
        self._m_model  = QLineEdit(); self._m_model.setPlaceholderText('Model number')
        self._m_serial = QLineEdit(); self._m_serial.setPlaceholderText('Serial number')
        self._m_cert   = QLineEdit(); self._m_cert.setPlaceholderText('Calibration cert no')

        form.addRow('Instrument Type', self._m_type)
        form.addRow('Make',            self._m_make)
        form.addRow('Model',           self._m_model)
        form.addRow('Serial No',       self._m_serial)
        form.addRow('Certificate No',  self._m_cert)

        return box

    def _build_manufacturer_card(self) -> QGroupBox:
        box = QGroupBox('Manufacturer Settings')
        box.setObjectName('card')
        box.setStyleSheet('QGroupBox{border:1px solid #d1d9e6;}')
        h = QHBoxLayout(box)
        h.addStretch(1)
        btn = make_button('Manufacturer Settings', 'ghost')
        btn.clicked.connect(self._open_manufacturer_settings)
        h.addWidget(btn)
        h.addStretch(1)
        return box

    # ------------------------------------------------------------------
    # CMC point rows
    # ------------------------------------------------------------------
    def _add_cmc_row(self, temperature: float, cmc: float) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)

        temp_spin = QDoubleSpinBox()
        temp_spin.setRange(self._range_min.value(), self._range_max.value())
        temp_spin.setDecimals(0)
        temp_spin.setSingleStep(100)
        temp_spin.setSuffix(' °C')
        temp_spin.setValue(temperature)

        cmc_spin = QDoubleSpinBox()
        cmc_spin.setRange(0, 100)
        cmc_spin.setDecimals(1)
        cmc_spin.setSuffix(' ±°C')
        cmc_spin.setValue(cmc)

        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(28)
        del_btn.setStyleSheet(
            'QPushButton{border:none;color:#ef4444;background:transparent;font-size:13px;}'
            'QPushButton:hover{background:#fef2f2;border-radius:4px;}'
        )

        entry = (temp_spin, cmc_spin, row)
        self._cmc_rows.append(entry)
        del_btn.clicked.connect(lambda: self._remove_cmc_row(entry))

        row.addWidget(QLabel('Temp'))
        row.addWidget(temp_spin)
        row.addWidget(QLabel('CMC'))
        row.addWidget(cmc_spin)
        row.addWidget(del_btn)
        self._cmc_container.addLayout(row)
        self._update_cmc_count()

    def _remove_cmc_row(self, entry: tuple) -> None:
        if entry in self._cmc_rows:
            self._cmc_rows.remove(entry)
            _, _, row = entry
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
            self._cmc_container.removeItem(row)
            self._update_cmc_count()

    def _update_cmc_count(self) -> None:
        self._cmc_count_label.setText(f'{len(self._cmc_rows)} CMC points')
        self._update_setpoints_lock()

    def _on_cmc_toggle(self, status: str) -> None:
        self._cmc_add_btn.setEnabled(status == 'ON')
        self._update_setpoints_lock()

    def _update_setpoints_lock(self) -> None:
        cmc_on = self._cmc_status.currentText() == 'ON'
        locked = cmc_on and len(self._cmc_rows) == 0
        self._sp_add_btn.setEnabled(not locked)
        self._sp_lock_note.setVisible(locked)

    # ------------------------------------------------------------------
    # Setpoint rows (same pattern previously on the Setup screen)
    # ------------------------------------------------------------------
    def _add_sp_row(self, value: float) -> None:
        if len(self._sp_widgets) >= 10:
            return
        row = QHBoxLayout()
        row.setSpacing(6)

        idx_lbl = QLabel(str(len(self._sp_widgets) + 1))
        idx_lbl.setFixedWidth(20)
        idx_lbl.setStyleSheet('color:#6b7a90;font-size:12px;')

        spin = QDoubleSpinBox()
        spin.setRange(max(0.0, self._range_min.value()), self._range_max.value())
        spin.setDecimals(1)
        spin.setValue(value)
        spin.setSuffix(' °C')
        spin.setSingleStep(100)  # ↑/↓ arrows step by 100; typed values are unrestricted
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(28)
        del_btn.setStyleSheet(
            'QPushButton{border:none;color:#ef4444;background:transparent;font-size:13px;}'
            'QPushButton:hover{background:#fef2f2;border-radius:4px;}'
        )

        entry = (spin, idx_lbl, del_btn, row)
        self._sp_widgets.append(spin)
        self._sp_rows.append(entry)
        del_btn.clicked.connect(lambda: self._remove_sp(entry))

        row.addWidget(idx_lbl)
        row.addWidget(spin)
        row.addWidget(del_btn)
        self._sp_container.addLayout(row)
        self._update_sp_count()

    def _remove_sp(self, entry: tuple) -> None:
        if entry not in self._sp_rows:
            return
        spin, idx_lbl, del_btn, row = entry
        self._sp_rows.remove(entry)
        self._sp_widgets.remove(spin)

        for w in (idx_lbl, spin, del_btn):
            w.setParent(None)
        self._sp_container.removeItem(row)

        self._renumber_sp_rows()
        self._update_sp_count()

    def _renumber_sp_rows(self) -> None:
        for i, (_, idx_lbl, _, _) in enumerate(self._sp_rows):
            idx_lbl.setText(str(i + 1))

    def _update_sp_count(self) -> None:
        self._sp_count_label.setText(f'{len(self._sp_widgets)} / 10')

    # ------------------------------------------------------------------
    # Manufacturer settings (PIN-gated)
    # ------------------------------------------------------------------
    def _open_manufacturer_settings(self) -> None:
        pin, ok = QInputDialog.getText(
            self, 'Manufacturer Settings', 'Enter 6-digit PIN:',
            QLineEdit.Password
        )
        if not ok:
            return
        if pin != MANUFACTURER_PIN:
            QMessageBox.warning(self, 'Incorrect PIN', 'The PIN you entered is incorrect.')
            return
        self._show_manufacturer_dialog()

    def _show_manufacturer_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle('Manufacturer Settings')
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)

        mfg = self._store.load().get('manufacturer', {})
        current_limit = clamp_stability_limit(float(mfg.get('stability_limit_c', 0.05)))

        limit_spin = QDoubleSpinBox()
        limit_spin.setRange(STABILITY_LIMIT_MIN, STABILITY_LIMIT_MAX)
        limit_spin.setDecimals(2)
        limit_spin.setSingleStep(0.01)
        limit_spin.setSuffix(' °C')
        limit_spin.setValue(current_limit)
        form.addRow('Stability Tolerance', limit_spin)

        ref_equip = QLineEdit(mfg.get('reference_equipment', ''))
        ref_equip.setPlaceholderText('Reference equipment used')
        model_no = QLineEdit(mfg.get('model_no', ''))
        model_no.setPlaceholderText('Model number')
        serial_no = QLineEdit(mfg.get('serial_no', ''))
        serial_no.setPlaceholderText('Serial number')

        form.addRow('Reference Equipment Used', ref_equip)
        form.addRow('Model No',                 model_no)
        form.addRow('Serial No',                serial_no)

        range_min_spin = _UnboundedSpinBox()
        range_min_spin.setRange(-200, 999999)
        range_min_spin.setDecimals(0)
        range_min_spin.setSingleStep(100)
        range_min_spin.setSuffix(' °C')
        range_min_spin.setValue(self._range_min.value())
        range_max_spin = _UnboundedSpinBox()
        range_max_spin.setRange(-200, 999999)
        range_max_spin.setDecimals(0)
        range_max_spin.setSingleStep(100)
        range_max_spin.setSuffix(' °C')
        range_max_spin.setValue(self._range_max.value())

        form.addRow('Dry Block Range Minimum', range_min_spin)
        form.addRow('Dry Block Range Maximum', range_max_spin)

        range_note = QLabel('Setpoints and CMC points must stay within this range.')
        range_note.setWordWrap(True)
        range_note.setStyleSheet('font-size:11px;color:#a0aec0;')
        form.addRow('', range_note)

        note = QLabel(
            'Sent to the instrument as SOUR:STAB:LIM — the band SOUR:STAB:TEST? '
            'must stay within to report stable. Per the 9144 datasheet its own '
            'stability spec is ~0.03°C at 50°C to ~0.05°C at 660°C — a tolerance '
            'tighter than that may never be satisfied.'
        )
        note.setWordWrap(True)
        note.setStyleSheet('font-size:11px;color:#a0aec0;')
        form.addRow(note)

        on_instrument = QLabel('—')
        on_instrument.setStyleSheet('color:#6b7a90;')
        form.addRow('Currently on instrument (SOUR:STAB:LIM?)', on_instrument)

        stable_now = QLabel('—')
        stable_now.setStyleSheet('color:#6b7a90;')
        form.addRow('Stable (SOUR:STAB:TEST?)', stable_now)

        status = QLabel('')
        status.setWordWrap(True)
        form.addRow(status)

        timer = QTimer(dlg)
        def _refresh():
            if self._comm is not None and getattr(self._comm, 'is_connected', False):
                readback = self._comm.get_stability_limit()
                on_instrument.setText(f'{readback:.2f} °C' if readback is not None else 'unknown')
                stable_now.setText('Yes' if self._comm.read_stable() else 'No')
            else:
                on_instrument.setText('not connected')
                stable_now.setText('not connected')
        timer.timeout.connect(_refresh)
        timer.start(1000)
        _refresh()

        def _on_save():
            if range_min_spin.value() >= range_max_spin.value():
                QMessageBox.warning(dlg, 'Invalid Range',
                                     'Calibrator minimum must be less than maximum.')
                return
            value = limit_spin.value()
            settings = self._store.load()
            settings['manufacturer'] = {
                'stability_limit_c': value,
                'reference_equipment': ref_equip.text().strip(),
                'model_no': model_no.text().strip(),
                'serial_no': serial_no.text().strip(),
            }
            settings['calibrator_range'] = {
                'min': range_min_spin.value(),
                'max': range_max_spin.value(),
            }
            self._store.save(settings)
            # Keep the main screen's range state (used by CMC/setpoint row
            # bounds and Save validation) in sync with what was just saved
            # here, and refresh any already-added rows the same way
            # _on_range_changed always has.
            self._range_min.setValue(range_min_spin.value())
            self._range_max.setValue(range_max_spin.value())
            self._on_range_changed()
            # Only stability tolerance is a live instrument setting
            # (SOUR:STAB:LIM) — reference equipment, model/serial, and the
            # calibrator range are just saved for future report
            # generation, so there's nothing to push for them. Re-push
            # stability only when it actually changed, so saving an
            # unrelated field (e.g. reference equipment) doesn't re-send
            # the same value to the instrument every time.
            if value != current_limit:
                if self._comm is not None and getattr(self._comm, 'is_connected', False):
                    ok = self._comm.set_stability_limit(value)
                    status.setText(
                        f'Saved and pushed to instrument ({value:.2f} °C).' if ok else
                        'Saved, but the instrument did not acknowledge the new value.'
                    )
                    status.setStyleSheet(f'font-size:11px;color:{"#22c55e" if ok else "#ef4444"};')
                else:
                    status.setText('Saved. Will be pushed to the instrument on next connect.')
                    status.setStyleSheet('font-size:11px;color:#6b7a90;')
            else:
                status.setText('Saved.')
                status.setStyleSheet('font-size:11px;color:#6b7a90;')

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).clicked.connect(_on_save)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        dlg.exec_()
        timer.stop()

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------
    def _load_into_ui(self) -> None:
        s = self._store.load()

        profile = s.get('user_profile', {})
        self._u_company_name.setText(profile.get('company_name', ''))
        self._u_company_address.setPlainText(profile.get('company_address', ''))
        self._u_cert_prefix.setText(profile.get('certificate_prefix', ''))
        self._u_logo_path = profile.get('logo_path')
        self._refresh_logo_preview()

        serial = s.get('serial', {})
        self._iface.setCurrentText(serial.get('iface', 'RS-232'))
        self._port.setCurrentText(serial.get('port', 'COM3'))
        self._baud.setCurrentText(str(serial.get('baud', 9600)))
        self._timeout.setText(str(serial.get('timeout_ms', 1000)))
        self._retry.setText(str(serial.get('retry', 3)))

        rng = s.get('calibrator_range', {})
        if rng.get('min') is not None:
            self._range_min.setValue(rng['min'])
        if rng.get('max') is not None:
            self._range_max.setValue(rng['max'])

        self._cmc_status.setCurrentText('ON' if s.get('cmc_enabled') else 'OFF')
        for pt in s.get('cmc_points', []):
            self._add_cmc_row(pt.get('temperature', 0.0), pt.get('cmc', 0.0))

        for sp in s.get('setpoints', []):
            self._add_sp_row(sp)

        master = s.get('master_rtd', {})
        self._m_type.setText(master.get('instrument_type', ''))
        self._m_make.setText(master.get('make', ''))
        self._m_model.setText(master.get('model', ''))
        self._m_serial.setText(master.get('serial_no', ''))
        self._m_cert.setText(master.get('cert_number', ''))

        self._cmc_add_btn.setEnabled(self._cmc_status.currentText() == 'ON')
        self._update_setpoints_lock()

    def _on_save(self) -> None:
        if self._range_min.value() >= self._range_max.value():
            QMessageBox.warning(self, 'Invalid Range', 'Calibrator minimum must be less than maximum.')
            return

        cmc_enabled = self._cmc_status.currentText() == 'ON'
        cmc_points = []
        for temp_spin, cmc_spin, _ in self._cmc_rows:
            if temp_spin.value() % 100 != 0:
                QMessageBox.warning(self, 'Invalid CMC Point',
                                     'CMC point temperatures must be multiples of 100.')
                return
            cmc_points.append({'temperature': temp_spin.value(), 'cmc': cmc_spin.value()})

        if cmc_enabled and not cmc_points:
            QMessageBox.warning(self, 'CMC Points Required',
                                 'CMC is ON — enter at least one CMC point before saving.')
            return

        setpoints = [s.value() for s in self._sp_widgets if s.value() > 0]
        rmin, rmax = self._range_min.value(), self._range_max.value()
        if any(sp < rmin or sp > rmax for sp in setpoints):
            QMessageBox.warning(self, 'Setpoint Out of Range',
                                 'All setpoints must stay within the calibrator range.')
            return
        if not _is_unimodal(setpoints):
            QMessageBox.warning(
                self, 'Invalid Setpoint Order',
                'Setpoints must rise to at most one peak and then fall — purely '
                'ascending, purely descending, or ascending then descending '
                '(e.g. 200, 300, 400, 700, 600, 250, 100) are all fine. Reversing '
                'direction more than once, or repeating a value, is not allowed.'
            )
            return

        existing = self._store.load()
        settings = {
            **existing,
            'serial': {
                'iface': self._iface.currentText(),
                'port': self._port.currentText(),
                'baud': int(self._baud.currentText()),
                'timeout_ms': int(self._timeout.text() or '1000'),
                'retry': int(self._retry.text() or '3'),
            },
            'calibrator_range': {'min': rmin, 'max': rmax},
            'cmc_enabled': cmc_enabled,
            'cmc_points': cmc_points,
            'setpoints': setpoints,
            'user_profile': {
                'company_name':       self._u_company_name.text().strip(),
                'company_address':    self._u_company_address.toPlainText().strip(),
                'certificate_prefix': self._u_cert_prefix.text().strip(),
                'logo_path':          self._u_logo_path,
            },
            'master_rtd': {
                'instrument_type': self._m_type.text().strip(),
                'make':            self._m_make.text().strip(),
                'model':           self._m_model.text().strip(),
                'serial_no':       self._m_serial.text().strip(),
                'cert_number':     self._m_cert.text().strip(),
                'tag_number':      '',
            },
        }
        self._store.save(settings)
        self.save_requested.emit(settings)
        QMessageBox.information(self, 'Saved', 'Settings saved successfully.')

    def get_port(self) -> str:
        return self._port.currentText()
