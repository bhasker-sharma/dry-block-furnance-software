"""
Application-wide QSS (Qt Style Sheet).
QSS is Qt's equivalent of CSS — same idea, different property names.
Defining it here means every screen gets consistent colours/fonts
without repeating styles everywhere.
"""

APP_QSS = """
/* ── Global ──────────────────────────────────────────────────────── */
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
    color: #1a2332;
    background: transparent;
}

/* ── Main window background ──────────────────────────────────────── */
QMainWindow, #centralWidget {
    background: #f0f4fa;
}

/* ── Sidebar ─────────────────────────────────────────────────────── */
#sidebar {
    background: #1a2332;
    min-width: 200px;
    max-width: 200px;
}
#sidebar QLabel {
    color: #a0aec0;
}
#sidebar QPushButton {
    color: #a0aec0;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: left;
    font-size: 13px;
}
#sidebar QPushButton:hover {
    background: #243044;
    color: #ffffff;
}
#sidebar QPushButton[active="true"] {
    background: #3d7fff;
    color: #ffffff;
}
#brand_label {
    color: #ffffff;
    font-size: 15px;
    font-weight: 700;
    padding: 20px 16px 4px 16px;
}
#brand_sub {
    color: #607080;
    font-size: 11px;
    padding: 0 16px 16px 16px;
}

/* ── Content area ────────────────────────────────────────────────── */
#contentStack {
    background: #f0f4fa;
}

/* ── Cards / QGroupBox ───────────────────────────────────────────── */
#card {
    background: #ffffff;
    border: 1px solid #d1d9e6;
    border-radius: 10px;
}

/*
  QGroupBox needs TWO rules to look right:
  1. margin-top: reserves space ABOVE the top border for the title text.
     (padding-top would push ALL content down — causes the large-gap bug.)
  2. ::title positions the text label inside that reserved margin area.
     background: white punches a hole through the border line under the text.
*/
QGroupBox {
    margin-top: 20px;
    padding: 2px 6px 6px 6px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 12px;
    color: #1a2332;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0px 5px;
    background: #ffffff;
}
QGroupBox#card {
    background: #ffffff;
}

/* ── Top bar inside screens ──────────────────────────────────────── */
#topbar {
    background: #ffffff;
    border-bottom: 1px solid #d1d9e6;
    padding: 12px 20px;
}
#topbar QLabel#screen_title {
    font-size: 18px;
    font-weight: 700;
    color: #1a2332;
}
#topbar QLabel#screen_sub {
    font-size: 12px;
    color: #6b7a90;
}

/* ── Temperature readout cards ───────────────────────────────────── */
#readout {
    background: #ffffff;
    border: 1px solid #d1d9e6;
    border-radius: 10px;
    padding: 16px;
}
#readout_value {
    font-family: "Courier New", monospace;
    font-size: 38px;
    font-weight: 700;
    color: #1a2332;
}
#readout_value[idle="true"] {
    color: #a0aec0;
}
#readout_unit {
    font-size: 16px;
    color: #6b7a90;
}
#readout_name {
    font-size: 12px;
    font-weight: 600;
    color: #6b7a90;
}

/* ── Buttons ─────────────────────────────────────────────────────── */
QPushButton {
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    border: 1px solid #d1d9e6;
    background: #ffffff;
    color: #1a2332;
}
QPushButton:hover    { background: #f0f4fa; }
QPushButton:pressed  { background: #e2e7ee; }
QPushButton:disabled { color: #a0aec0; background: #f7f9fc; }

QPushButton[role="primary"] {
    background: #3d7fff;
    color: #ffffff;
    border: none;
}
QPushButton[role="primary"]:hover   { background: #3370ee; }
QPushButton[role="primary"]:pressed { background: #2860de; }

QPushButton[role="danger"] {
    background: #ef4444;
    color: #ffffff;
    border: none;
}
QPushButton[role="danger"]:hover { background: #dc2626; }

QPushButton[role="success"] {
    background: #22c55e;
    color: #ffffff;
    border: none;
}
QPushButton[role="success"]:hover { background: #16a34a; }

QPushButton[role="ghost"] {
    background: transparent;
    border: 1px solid #d1d9e6;
    color: #6b7a90;
}
QPushButton[role="ghost"]:hover { background: #f0f4fa; color: #1a2332; }

/* ── Form inputs ─────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    border: 1px solid #d1d9e6;
    border-radius: 6px;
    padding: 6px 10px;
    background: #ffffff;
    color: #1a2332;
    font-size: 13px;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #3d7fff;
    outline: none;
}
QLineEdit:disabled, QComboBox:disabled {
    background: #f7f9fc;
    color: #a0aec0;
}

/* ── Tables ──────────────────────────────────────────────────────── */
QTableWidget {
    border: none;
    gridline-color: #e2e7ee;
    background: #ffffff;
    alternate-background-color: #f7f9fc;
}
QTableWidget::item { padding: 6px 10px; }
QTableWidget::item:selected { background: #ebf2ff; color: #1a2332; }
QHeaderView::section {
    background: #f0f4fa;
    border: none;
    border-bottom: 1px solid #d1d9e6;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
    color: #6b7a90;
}

/* ── Status console (log area) ───────────────────────────────────── */
#console {
    background: #0f1623;
    border-radius: 8px;
    padding: 10px;
    font-family: "Courier New", monospace;
    font-size: 12px;
    color: #a0aec0;
}

/* ── Connection status chip ──────────────────────────────────────── */
#conn_chip {
    border-radius: 20px;
    padding: 6px 14px;
}
#conn_chip[state="on"]  { background: #1a3a2a; }
#conn_chip[state="off"] { background: #2a1a1a; }

/*
  Pop-up dialogs (QMessageBox, QInputDialog, and plain QDialog windows
  like Manufacturer Settings) don't inherit the #f0f4fa app background —
  on a dark Windows theme they fall back to a dark system background,
  and the QWidget rule above forces dark text on top of it, making it
  unreadable. Force a light background here so the dark text stays legible.
*/
QDialog, QMessageBox {
    background: #ffffff;
    color: #1a2332;
}
QMessageBox QLabel, QInputDialog QLabel, QDialog QLabel {
    color: #1a2332;
    background: transparent;
}
"""
