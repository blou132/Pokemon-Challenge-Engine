"""Adaptateur Qt de la passerelle : lectures et préparation dans un worker dédié."""

from dataclasses import replace
import logging
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Signal, Slot

from app.bridge.state import BridgeState
from app.services.bridge_service import BridgeService
from app.services.emulator_service import EmulatorService
from app.services.tracking_service import TrackingService, TrackingState

LOGGER = logging.getLogger(__name__)


class _BridgeWorker(QObject):
    state_changed = Signal(object)
    state_for_request = Signal(int, object)
    tracking_changed = Signal(object)
    prepared = Signal(str)
    prepared_for_request = Signal(int, str)
    preparation_failed = Signal(int, str)
    failed = Signal(str)
    failure_for_request = Signal(int, str)

    def __init__(self, bridge: BridgeService, base_dir: Path) -> None:
        super().__init__()
        self.bridge = bridge
        self.base_dir = base_dir
        self.emulator: EmulatorService | None = None
        self._timer: QTimer | None = None
        self._last_state = BridgeState()
        self.tracking: TrackingService | None = None
        self._tracking_state = TrackingState()
        self._request_id = 0

    def _tracking(self) -> TrackingService:
        if self.tracking is None:
            self.tracking = TrackingService(self.base_dir)
        return self.tracking

    def _publish_tracking(self, state: TrackingState) -> None:
        if state != self._tracking_state:
            self._tracking_state = state
            self.tracking_changed.emit(state)

    @Slot(object)
    def select_profile(self, profile_id: str | None) -> None:
        try:
            self._publish_tracking(self._tracking().select_profile(profile_id))
        except (OSError, ValueError) as exc:
            self._publish_tracking(TrackingState(status="error", message=str(exc)))

    def _publish(self, state: BridgeState) -> None:
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)
            self.state_for_request.emit(self._request_id, state)
            try:
                tracking = self._tracking().consume(state)
                self._publish_tracking(tracking)
                if tracking.status != "error":
                    self.bridge.acknowledge_observations(state)
            except (OSError, ValueError) as exc:
                LOGGER.exception("Suivi Nuzlocke suspendu ; observations conservées.")
                self._publish_tracking(replace(self._tracking_state, status="error", message=str(exc)))

    @Slot(str, str, int)
    def start(self, game_id: str, rom_path: str, request_id: int = 0) -> None:
        if self._timer is not None:
            self._timer.stop()
        if self.bridge.session_id is not None:
            self._publish(self.bridge.poll())
        self.bridge.stop()
        self._last_state = BridgeState()
        self._request_id = request_id
        try:
            if self.emulator is None:
                self.emulator = EmulatorService(self.base_dir, self.bridge)
            script = self.emulator.prepare(game_id, rom_path)
            if self.bridge.state.status == "error":
                raise ValueError(self.bridge.state.last_error or "Préparation de la passerelle impossible.")
        except Exception as exc:
            # Une erreur d'I/O reste visible dans l'interface et ne tue pas le worker.
            LOGGER.exception("Préparation de la passerelle impossible.")
            self.bridge.stop()
            message = str(exc) or "Préparation de la passerelle impossible."
            self._publish(BridgeState(status="error", expected_game=game_id, last_error=message))
            self.failed.emit(message)
            self.failure_for_request.emit(request_id, message)
            self.preparation_failed.emit(request_id, message)
            return
        if self._timer is None:
            # Le timer est créé ici, après moveToThread, dans son thread propriétaire.
            self._timer = QTimer(self)
            self._timer.setInterval(200)
            self._timer.timeout.connect(self.poll)
        self.prepared.emit(str(script))
        self.prepared_for_request.emit(request_id, str(script))
        self._publish(self.bridge.state)
        self._timer.start()

    @Slot()
    def poll(self) -> None:
        try:
            self._publish(self.bridge.poll())
        except Exception as exc:
            LOGGER.exception("Lecture de la passerelle impossible.")
            if self._timer is not None:
                self._timer.stop()
            message = str(exc) or "Lecture de la passerelle impossible."
            self._publish(replace(self.bridge.state, status="error", party_size=None, party=None, last_error=message))
            self.failed.emit(message)
            self.failure_for_request.emit(self._request_id, message)

    @Slot()
    @Slot(int)
    def stop(self, request_id=None) -> None:
        if self._timer is not None:
            self._timer.stop()
        if self.bridge.session_id is not None:
            self._publish(self.bridge.poll())
        if request_id is not None:
            self._request_id = request_id
        self.bridge.stop()
        self._publish(self.bridge.state)


class BridgeController(QObject):
    """Expose seulement des signaux à l'UI, sans I/O sur le thread graphique."""

    state_changed = Signal(object)
    tracking_changed = Signal(object)
    prepared = Signal(str)
    prepared_for_request = Signal(int, str)
    preparation_failed = Signal(int, str)
    failed = Signal(str)
    _start_requested = Signal(str, str, int)
    _stop_requested = Signal(int)
    _profile_requested = Signal(object)

    def __init__(self, base_dir: Path, parent: QObject | None = None, *, bridge: BridgeService | None = None) -> None:
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.bridge = bridge if bridge is not None else BridgeService(self.base_dir / "runtime" / "bridge")
        self.state = BridgeState()
        self.tracking_state = TrackingState()
        self._thread: QThread | None = None
        self._worker: _BridgeWorker | None = None
        self._closed = False
        self.request_id = 0

    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        thread.setObjectName("DeSmuME bridge reader")
        worker = _BridgeWorker(self.bridge, self.base_dir)
        worker.moveToThread(thread)
        self._start_requested.connect(worker.start)
        self._stop_requested.connect(worker.stop)
        self._profile_requested.connect(worker.select_profile)
        worker.state_for_request.connect(self._receive_scoped_state)
        worker.tracking_changed.connect(self._receive_tracking)
        worker.prepared_for_request.connect(self._receive_scoped_prepared)
        worker.preparation_failed.connect(self._receive_preparation_failure)
        worker.failure_for_request.connect(self._receive_scoped_failure)
        thread.finished.connect(worker.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot(object)
    def _receive_tracking(self, state: TrackingState) -> None:
        if not self._closed:
            self.tracking_state = state
            self.tracking_changed.emit(state)

    @Slot(object)
    def select_profile(self, profile_id: str | None) -> None:
        if not self._closed:
            self._ensure_worker()
            self._profile_requested.emit(profile_id)

    @Slot(object)
    def _receive_state(self, state: BridgeState) -> None:
        if not self._closed:
            self.state = state
            self.state_changed.emit(state)

    @Slot(int, object)
    def _receive_scoped_state(self, request_id, state):
        if request_id == self.request_id:
            self._receive_state(state)

    @Slot(int, str)
    def _receive_scoped_prepared(self, request_id, path):
        if not self._closed and request_id == self.request_id:
            self._receive_prepared(path)
            self.prepared_for_request.emit(request_id, path)

    @Slot(int, str)
    def _receive_preparation_failure(self, request_id, message):
        if not self._closed and request_id == self.request_id:
            self.preparation_failed.emit(request_id, message)

    @Slot(str)
    def _receive_prepared(self, path: str) -> None:
        if not self._closed:
            self.prepared.emit(path)

    @Slot(str)
    def _receive_failure(self, message: str) -> None:
        if not self._closed:
            self.failed.emit(message)

    @Slot(int, str)
    def _receive_scoped_failure(self, request_id, message):
        if request_id == self.request_id:
            self._receive_failure(message)

    @Slot(str, str)
    def start(self, game_id: str, rom_path: str = "") -> int | None:
        if self._closed:
            return
        self._ensure_worker()
        self.request_id += 1
        self._start_requested.emit(game_id, rom_path, self.request_id)
        return self.request_id

    @Slot()
    def stop(self) -> None:
        self.request_id += 1  # Invalidate every pending preparation immediately.
        if self._thread is not None and not self._closed:
            self._stop_requested.emit(self.request_id)

    @Slot()
    def shutdown(self) -> None:
        """Arrête le timer dans le worker, puis attend sa fin avant de fermer Qt."""
        if self._closed:
            return
        self._closed = True
        thread, worker = self._thread, self._worker
        if thread is not None and worker is not None:
            if thread.isRunning():
                QMetaObject.invokeMethod(worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
                thread.quit()
                thread.wait()
            thread.deleteLater()
        self._thread = None
        self._worker = None
        self.state = BridgeState()
        self.state_changed.emit(self.state)
