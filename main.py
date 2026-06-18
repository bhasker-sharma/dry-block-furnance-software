"""
Entry point for the Dry Block Calibrator application.

Run with:
    python main.py              # simulator mode (no hardware needed)
    python main.py --real       # real USB hardware

Build EXE:
    pyinstaller --onefile --windowed --name "DryBlockCalibrator" main.py
"""
import os
import sys

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

from ui.main_window import MainWindow


def main() -> None:
    use_simulator = '--real' not in sys.argv

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

    window = MainWindow(use_simulator=use_simulator)
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
