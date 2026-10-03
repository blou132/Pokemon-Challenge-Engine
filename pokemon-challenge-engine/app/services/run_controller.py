"""Qt boundary for run tracking: one worker owns mutations and durable writes."""

from copy import deepcopy
from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Signal, Slot

from app.core.run_manager import RunManager
from app.events.game_event import GameObservation
from app.services.run_tracking_service import RunTrackingService


class _RunWorker(QObject):
    changed = Signal(object, dict)
    activated = Signal(object)
    failed = Signal(str)
    action_succeeded = Signal(str, str, object)

    def __init__(self, root):
        super().__init__()
        self.root = root
        self.tracker = None
        self.timer = None
        self.running = False
        self.game_id = None
        self.last_sample = None
        self.error = ""

    def publish(self):
        if self.tracker is not None:
            self.changed.emit(self.tracker.active_run, {
                "dirty": self.tracker.dirty, "last_saved_at": self.tracker.last_saved_at,
                "error": self.error or self.tracker.last_error,
            })

    def guarded(self, operation):
        try:
            operation()
            self.error = ""
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self.failed.emit(self.error)
        self.publish()

    @Slot(str)
    def activate(self, run_id):
        def operation():
            if self.tracker is None:
                self.tracker = RunTrackingService(RunManager(self.root))
                self.timer = QTimer(self)
                self.timer.setInterval(1000)
                self.timer.timeout.connect(self.tick)
                self.timer.start()
            self.tracker.activate(run_id)
            self.last_sample = None
            self.activated.emit(self.tracker.active_run)
        self.guarded(operation)

    @Slot(bool, object)
    def process_context(self, running, game_id):
        self.running, self.game_id = running, game_id
        self.tick()

    @Slot(object)
    def consume(self, state):
        if self.tracker is None:
            return
        def operation():
            marker = (state.session_id, state.sequence)
            eligible = state.connected and self.running and state.game_id == self.game_id
            if not eligible:
                self.tracker.heartbeat(emulator_running=self.running, game_id=state.game_id,
                                       connected=False)
            elif marker != self.last_sample:
                zone = None
                if state.observation is not None:
                    observation = GameObservation.from_dict(state.observation)
                    if observation.capture_zone_id is not None:
                        zone = {"id": observation.capture_zone_id, "name": observation.zone_name,
                                "map_id": observation.map_id}
                self.tracker.observe(state.party or [], zone, game_id=state.game_id,
                    game_code=state.game_code, region=state.game_region, revision=state.rom_revision,
                    emulator_running=True, connected=True, valid=state.party is not None)
                self.last_sample = marker
        self.guarded(operation)

    @Slot()
    def tick(self):
        if self.tracker is not None:
            def operation():
                self.tracker.heartbeat(emulator_running=self.running, game_id=self.game_id)
                self.tracker.flush()
            self.guarded(operation)

    @Slot(str, str, object)
    def action(self, run_id, name, payload):
        def operation():
            if name == "set_status" and (self.tracker is None or self.tracker.active_run is None or self.tracker.active_run.run_id != run_id):
                from app.services.run_tracking_service import set_inactive_run_status
                updated = set_inactive_run_status(RunManager(self.root), run_id, **payload)
                self.action_succeeded.emit(run_id, name, updated)
                return
            if self.tracker is None or self.tracker.active_run is None or self.tracker.active_run.run_id != run_id:
                raise ValueError("Reprenez cette partie avant d'y enregistrer une action.")
            allowed = {"manual_capture", "manual_death", "correct_death", "set_badges", "add_note",
                       "set_status", "record_backup", "update_launch_reference", "adjust_badges"}
            if name not in allowed or not isinstance(payload, dict):
                raise ValueError("Action de partie inconnue.")
            getattr(self.tracker, name)(**payload)
            self.action_succeeded.emit(run_id, name, self.tracker.active_run)
        self.guarded(operation)

    @Slot()
    def close(self):
        if self.timer is not None:
            self.timer.stop()
        if self.tracker is not None:
            self.guarded(self.tracker.close)


class RunController(QObject):
    changed = Signal(object, dict)
    activated = Signal(object)
    failed = Signal(str)
    action_succeeded = Signal(str, str, object)
    _activate = Signal(str)
    _consume = Signal(object)
    _process = Signal(bool, object)
    _action = Signal(str, str, object)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self.active_run = None
        self.state = {}
        self._thread = self._worker = None

    def _ensure_worker(self):
        if self._thread is not None:
            return
        self._thread = QThread(self)
        self._thread.setObjectName("PCE persistent runs")
        self._worker = _RunWorker(self.root)
        self._worker.moveToThread(self._thread)
        self._activate.connect(self._worker.activate)
        self._consume.connect(self._worker.consume)
        self._process.connect(self._worker.process_context)
        self._action.connect(self._worker.action)
        self._worker.changed.connect(self._receive)
        self._worker.activated.connect(self._receive_activation)
        self._worker.failed.connect(self.failed)
        self._worker.action_succeeded.connect(self.action_succeeded)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    @Slot(object, dict)
    def _receive(self, run, state):
        self.active_run, self.state = run, state
        self.changed.emit(run, state)

    @Slot(object)
    def _receive_activation(self, run):
        self.active_run = run
        self.activated.emit(run)

    def activate(self, run_id):
        self._ensure_worker()
        self._activate.emit(run_id)

    def consume(self, state):
        if self._worker is not None:
            self._consume.emit(deepcopy(state))

    def process_context(self, running, game_id):
        if self._worker is not None:
            self._process.emit(running, game_id)

    def action(self, run_id, name, payload):
        self._ensure_worker()
        self._action.emit(run_id, name, deepcopy(payload))

    def shutdown(self):
        if self._thread is not None:
            QMetaObject.invokeMethod(self._worker, "close", Qt.ConnectionType.BlockingQueuedConnection)
            error = self._worker.error or (self._worker.tracker.last_error if self._worker.tracker else "")
            if error:
                # Keep the worker alive so the user can retry a failed final save.
                self.failed.emit(error)
                return False
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread = self._worker = None
        return True
