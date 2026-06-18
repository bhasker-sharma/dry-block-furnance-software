from enum import Enum, auto
from datetime import datetime
from typing import Callable

from models.calibration_point import CalibrationPoint
from models.calibration_session import CalibrationSession
from comm.base_comm import BaseComm


class Phase(Enum):
    """States a calibration run moves through, in order."""
    STABILIZING = auto()   # waiting for fluctuation to settle, or for max time
    SAVING      = auto()   # point just captured — brief UI flash
    COMPLETED   = auto()   # all setpoints done


class CalibrationEngine:
    """
    State machine for one calibration run.

    The UI creates one engine, then calls tick() every second with the
    latest temperature readings. The engine updates its phase and calls
    the registered callbacks so the UI can refresh itself.

    Capture is fully automatic — there is no operator Pass/Fail step.
    A point is recorded the moment either condition is met:
      - the dry block's fluctuation over the last `volatility_window_minutes`
        is within `volatility_limit` (it has stabilized), or
      - `max_stabilization_seconds` has elapsed since the setpoint was sent
        (recorded as-is even if it never settled).

    Why a separate engine and not logic in the UI?
    - The UI should only handle drawing. Business logic (when to stabilize,
      when to capture, error calculation) belongs in a class that can be
      tested without a screen. This pattern is called MVC — the engine is
      the controller.
    """

    def __init__(
        self,
        session: CalibrationSession,
        comm: BaseComm,
        max_stabilization_seconds: int,
        volatility_window_minutes: float,
        volatility_limit: float,
        on_phase_change:  Callable[[Phase], None],
        on_tick:          Callable[[int], None],                 # remaining seconds
        on_point_ready:   Callable[[CalibrationPoint], None],    # called right after capture
        on_complete:      Callable[[], None],
    ):
        self._session = session
        self._comm    = comm
        self._max_seconds       = max_stabilization_seconds
        self._volatility_window = volatility_window_minutes
        self._volatility_limit  = volatility_limit

        self._idx     = 0          # which setpoint we're on
        self._phase   = Phase.STABILIZING
        self._elapsed = 0

        # callbacks — the engine never touches UI widgets directly
        self._on_phase_change = on_phase_change
        self._on_tick         = on_tick
        self._on_point_ready  = on_point_ready
        self._on_complete     = on_complete

        # send the first setpoint immediately
        self._comm.send_setpoint(self._current_target())

    # ------------------------------------------------------------------
    # Called every second by a QTimer in the UI
    # ------------------------------------------------------------------
    def tick(self, dry_block: float, master: float, uut: float) -> None:
        if self._phase != Phase.STABILIZING:
            return

        self._elapsed += 1
        self._on_tick(self.remaining_seconds)

        fluctuation = self._comm.read_volatility(self._volatility_window)
        stabilized  = fluctuation is not None and fluctuation <= self._volatility_limit
        timed_out   = self._elapsed >= self._max_seconds

        if stabilized or timed_out:
            self._capture(dry_block, master, uut)

    # ------------------------------------------------------------------
    # Internal — record the current reading, then advance or finish
    # ------------------------------------------------------------------
    def _capture(self, dry_block: float, master: float, uut: float) -> None:
        point = CalibrationPoint(
            setpoint=self._current_target(),
            dry_block_temp=dry_block,
            master_rtd=master,
            uut=uut,
            timestamp=datetime.now(),
        )
        self._session.points.append(point)
        self._set_phase(Phase.SAVING)
        self._on_point_ready(point)

        if self._idx + 1 < len(self._session.setpoints):
            self._idx += 1
            self._comm.send_setpoint(self._current_target())
            self._elapsed = 0
            self._set_phase(Phase.STABILIZING)
        else:
            self._set_phase(Phase.COMPLETED)
            self._on_complete()

    # ------------------------------------------------------------------
    # Read-only properties the UI can query
    # ------------------------------------------------------------------
    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def current_index(self) -> int:
        return self._idx

    @property
    def remaining_seconds(self) -> int:
        return max(0, self._max_seconds - self._elapsed)

    @property
    def session(self) -> CalibrationSession:
        return self._session

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _current_target(self) -> float:
        return self._session.setpoints[self._idx]

    def _set_phase(self, new_phase: Phase) -> None:
        self._phase = new_phase
        self._on_phase_change(new_phase)
