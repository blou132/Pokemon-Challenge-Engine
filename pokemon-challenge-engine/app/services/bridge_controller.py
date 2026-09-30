"""Adaptateur Qt de la passerelle : lectures et préparation dans un worker dédié."""

from dataclasses import replace
import logging
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Signal, Slot

from app.bridge.state import BridgeState
from app.services.bridge_service import BridgeService
from app.services.emulator_service import EmulatorService

LOGGER = logging.getLogger(__name__)


class _BridgeWorker(QObject):
    state_changed = Signal(object)
    prepared = Signal(str)
    failed = Signal(str)

    def __init__(self, bridge: BridgeService, base_dir: Path) -> None:
        super().__init__()
        self.bridge = bridge
        self.base_dir = base_dir
        self.emulator: EmulatorService | None = None
        self._timer: QTimer | None = None
        self._last_state = BridgeState()

    def _publish(self, state: BridgeState) -> None:
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state)

    @Slot(str, str)
    def start(self, game_id: str, rom_path: str) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.bridge.stop()
        self._last_state = BridgeState()
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
            return
        if self._timer is None:
            # Le timer est créé ici, après moveToThread, dans son thread propriétaire.
            self._timer = QTimer(self)
            self._timer.setInterval(200)
            self._timer.timeout.connect(self.poll)
        self.prepared.emit(str(script))
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

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.bridge.stop()
        self._publish(self.bridge.state)


class BridgeController(QObject):
    """Expose seulement des signaux à l'UI, sans I/O sur le thread graphique."""

    state_changed = Signal(object)
    prepared = Signal(str)
    failed = Signal(str)
    _start_requested = Signal(str, str)
    _stop_requested = Signal()

    def __init__(self, base_dir: Path, parent: QObject | None = None, *, bridge: BridgeService | None = None) -> None:
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self.bridge = bridge if bridge is not None else BridgeService(self.base_dir / "runtime" / "bridge")
        self.state = BridgeState()
        self._thread: QThread | None = None
        self._worker: _BridgeWorker | None = None
        self._closed = False

    def _ensure_worker(self) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        thread.setObjectName("DeSmuME bridge reader")
        worker = _BridgeWorker(self.bridge, self.base_dir)
        worker.moveToThread(thread)
        self._start_requested.connect(worker.start)
        self._stop_requested.connect(worker.stop)
        worker.state_changed.connect(self._receive_state)
        worker.prepared.connect(self._receive_prepared)
        worker.failed.connect(self._receive_failure)
        thread.finished.connect(worker.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot(object)
    def _receive_state(self, state: BridgeState) -> None:
        if not self._closed:
            self.state = state
            self.state_changed.emit(state)

    @Slot(str)
    def _receive_prepared(self, path: str) -> None:
        if not self._closed:
            self.prepared.emit(path)

    @Slot(str)
    def _receive_failure(self, message: str) -> None:
        if not self._closed:
            self.failed.emit(message)

    @Slot(str, str)
    def start(self, game_id: str, rom_path: str = "") -> None:
        if self._closed:
            return
        self._ensure_worker()
        self._start_requested.emit(game_id, rom_path)

    @Slot()
    def stop(self) -> None:
        if self._thread is not None and not self._closed:
            self._stop_requested.emit()

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
