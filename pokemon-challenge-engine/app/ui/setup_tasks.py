"""Exécute les opérations d'installation bornées hors du thread des widgets."""

from PySide6.QtCore import QObject, QThread, Signal, Slot


class _Task(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = ""

    @Slot()
    def run(self):
        try:
            self.result = self.operation()
        except Exception as exc:
            self.error = str(exc) or "L'opération n'a pas pu être terminée."


class SetupTaskRunner(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None

    @property
    def is_busy(self):
        return self._thread is not None

    def start(self, operation):
        if self.is_busy:
            return False
        thread = _Task(operation, self)
        thread.setObjectName("PCE installation")
        thread.finished.connect(self._finished)
        self._thread = thread
        self.busy_changed.emit(True)
        thread.start()
        return True

    @Slot()
    def _finished(self):
        thread = self._thread
        result, error = thread.result, thread.error
        self._thread = None
        thread.deleteLater()
        self.busy_changed.emit(False)
        if error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)
