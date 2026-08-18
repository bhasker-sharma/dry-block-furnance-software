"""
Entry point for the Dry Block Calibrator application.

Run with:
    python main.py

The app always connects over a real serial port (USBComm) — pick the
COM port in the Live Monitor screen. To test without the physical dry
block, run simulator.py (repo root) as a separate process against a
virtual COM port pair and connect to that port instead; see the
docstring at the top of simulator.py for setup.

Build EXE:
    pyinstaller --onefile --windowed --name "DryBlockCalibrator" main.py
"""
import os
import sys
from pathlib import Path

# ── DPI / Multi-monitor scaling ───────────────────────────────────────
# These MUST be set before importing PyQt5 or creating QApplication.
#
# Problem without these:
#   Qt reads the DPI of the PRIMARY monitor at startup. If you drag the
#   window to a second monitor with a different Windows display scale
#   (e.g. 100% vs 125% or 150%), Qt doesn't re-scale — text and widgets
#   look tiny or huge on the second screen.
#
# What each variable does:
#   QT_AUTO_SCREEN_SCALE_FACTOR=1
#       Qt re-reads the DPI of whichever monitor the window is currently on
#       and adjusts scaling automatically when you move it between screens.
#
#   QT_ENABLE_HIGHDPI_SCALING=1
#       Enables Qt 5.14+ per-monitor DPI scaling code path. Works alongside
#       AA_EnableHighDpiScaling for older Qt5 code paths.
#
# Result: the app looks identical (same physical size) on every monitor,
# whether that monitor is at 96 DPI (100%), 120 DPI (125%), or 144 DPI (150%).
os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING',   '1')

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from ui.main_window import MainWindow


def _icon_path() -> Path:
    """
    Path to the app icon (asset/logo.ico), used for the window/taskbar icon
    while running — separate from PyInstaller's --icon flag, which only
    sets the icon Explorer shows for the .exe file itself, not anything
    the running app displays.

    Bundled read-only resources like this live under sys._MEIPASS when
    frozen (PyInstaller --onefile extracts them there at startup) — this is
    the opposite of where *writable* data goes (see db/settings_store.py's
    _app_root(), which anchors to the exe's own folder instead, since that
    has to survive after the process exits and _MEIPASS doesn't).
    """
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / 'asset' / 'logo.ico'


def main() -> None:
    # These must be set before QApplication() is called.
    # AA_EnableHighDpiScaling: tells Qt to scale the UI to match screen DPI.
    # AA_UseHighDpiPixmaps:    makes icons and images sharp on HiDPI screens.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps,    True)

    # PassThrough rounding policy: fractional DPI values like 125% or 150%
    # are used as-is instead of being rounded to 100% or 200%.
    # Without this, a 125% monitor might look like 100% or 200%.
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except AttributeError:
        pass   # Qt < 5.14 — not available, skip silently

    app = QApplication(sys.argv)
    app.setApplicationName('Dry Block Calibrator')
    app.setOrganizationName('TIPL')

    icon_path = _icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
