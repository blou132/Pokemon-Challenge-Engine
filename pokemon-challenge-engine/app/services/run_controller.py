"""Qt boundary for run tracking: one worker owns mutations and durable writes."""

from copy import deepcopy
from uuid import uuid4
from PySide6.QtCore import QMetaObject, QObject, QThread, QTimer, Qt, Signal, Slot

from app.core.run_manager import RunManager
from app.events.game_event import GameObservation
from app.services.run_tracking_service import RunTrackingService


class _RunWorker(QObject):
    changed = Signal(object, dict)
    activation_ready = Signal(str, object)
    activated = Signal(str, object)
    activation_failed = Signal(str, str)
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
        self.activation_token = None

    def publish(self):
        if self.tracker is not None and self.activation_token is None:
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

    @Slot(str, str)
    def activate(self, run_id, token):
        try:
            if self.tracker is None:
                self.tracker = RunTrackingService(RunManager(self.root))
                self.timer = QTimer(self)
                self.timer.setInterval(1000)
                self.timer.timeout.connect(self.tick)
                self.timer.start()
            current = self.tracker.active_run
            if self.running and current is not None and current.run_id != run_id:
                raise ValueError("Terminez la session DeSmuME suivie avant de changer de partie.")
            self.activation_token = token
            run = self.tracker.prepare_activation(run_id)
            self.last_sample = None
            self.activation_ready.emit(token, run)
        except (OSError, ValueError) as exc:
            if self.tracker is not None:
                self.tracker.cancel_activation()
            self.activation_token = None
            self.error = str(exc)
            self.activation_failed.emit(token, self.error)

    @Slot(str, str)
    def commit_activation(self, run_id, token):
        if token != self.activation_token:
            return
        try:
            run = self.tracker.commit_activation(run_id)
            self.activation_token = None
            self.error = ""
            self.activated.emit(token, run)
        except (OSError, ValueError) as exc:
            self.tracker.cancel_activation()
            self.activation_token = None
            self.error = str(exc)
            self.activation_failed.emit(token, self.error)
        self.publish()

    @Slot(str)
    def cancel_activation(self, token):
        if token == self.activation_token:
            if self.tracker is not None:
                self.tracker.cancel_activation()
            self.activation_token = None

    @Slot(bool, object)
    def process_context(self, running, game_id):
        self.running, self.game_id = running, game_id
        self.tick()

    @Slot(object)
    def consume(self, state):
        if self.tracker is None or self.activation_token is not None:
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
            if self.activation_token is not None:
                raise ValueError("Attendez la confirmation de la partie demandée avant cette action.")
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
    _activate = Signal(str, str)
    _commit_activation = Signal(str, str)
    _cancel_activation = Signal(str)
    _consume = Signal(object)
    _process = Signal(bool, object)
    _action = Signal(str, str, object)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self.active_run = None
        self.state = {}
        self.requested_run_id = None
        self.activation_pending = False
        self._activation_token = None
        self._thread = self._worker = None

    def _ensure_worker(self):
        if self._thread is not None:
            return
        self._thread = QThread(self)
        self._thread.setObjectName("PCE persistent runs")
        self._worker = _RunWorker(self.root)
        self._worker.moveToThread(self._thread)
        self._activate.connect(self._worker.activate)
        self._commit_activation.connect(self._worker.commit_activation)
        self._cancel_activation.connect(self._worker.cancel_activation)
        self._consume.connect(self._worker.consume)
        self._process.connect(self._worker.process_context)
        self._action.connect(self._worker.action)
        self._worker.changed.connect(self._receive)
        self._worker.activation_ready.connect(self._acknowledge_activation)
        self._worker.activated.connect(self._receive_activation)
        self._worker.activation_failed.connect(self._activation_failed)
        self._worker.failed.connect(self.failed)
        self._worker.action_succeeded.connect(self.action_succeeded)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.start()

    @Slot(object, dict)
    def _receive(self, run, state):
        if self.activation_pending or (run is not None and self.requested_run_id is not None
                                      and run.run_id != self.requested_run_id):
            return
        self.active_run, self.state = run, state
        self.changed.emit(run, state)

    @Slot(str, object)
    def _acknowledge_activation(self, token, run):
        if token != self._activation_token or run.run_id != self.requested_run_id:
            self._cancel_activation.emit(token)
            return
        self._commit_activation.emit(run.run_id, token)

    @Slot(str, object)
    def _receive_activation(self, token, run):
        if token != self._activation_token or run.run_id != self.requested_run_id:
            return
        self.activation_pending = False
        self.active_run = run
        self.activated.emit(run)

    @Slot(str, str)
    def _activation_failed(self, token, message):
        if token == self._activation_token:
            self.activation_pending = False
            self.state = self.state | {"error": message}
            self.failed.emit(message)

    def expect_run(self, run_id):
        """Record the UI request before asynchronous environment preparation begins."""
        from app.models.run import validate_run_id
        validate_run_id(run_id)
        if self._activation_token is not None and self._worker is not None:
            self._cancel_activation.emit(self._activation_token)
        self.requested_run_id = run_id
        self._activation_token = uuid4().hex
        self.activation_pending = False

    def activate(self, run_id):
        self.expect_run(run_id)
        self._ensure_worker()
        self.activation_pending = True
        self._activate.emit(run_id, self._activation_token)

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
