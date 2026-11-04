"""Session-bound native melonDS commands; no window messages or RAM writes."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time

from app.services.config_service import _strict_pairs
from app.services.discovery_safety import file_hash, local_path
from app.services.run_isolation_service import _regular

CAPABILITIES = frozenset({"speed", "save_state", "load_state", "input_settings", "video_settings", "screen_layout", "input_pulse"})
ERRORS = {
    "expired": "La commande a expiré sans être exécutée.",
    "cartridge_changed": "La cartouche a changé ; relancez cette partie depuis PCE.",
    "state_directory_changed": "Le dossier de save states a changé ; relancez la partie.",
    "dialog_open": "Fermez le dialogue melonDS avant de réessayer.",
    "sram_relocation_enabled": "Désactivez Relocate savefile dans melonDS avant cette opération.",
    "unsafe_state_path": "Le chemin de save state ne respecte plus l'isolation de cette partie.",
    "state_missing_or_invalid": "Ce slot est absent ou son fichier n'est pas valide.",
    "state_load_failed": "melonDS n'a pas pu charger ce save state.",
    "state_save_failed": "melonDS n'a pas pu créer le save state.",
    "input_expired": "L'entrée n'a pas terminé dans le délai ; les boutons virtuels sont relâchés.",
    "state_commit_failed": "Le save state n'a pas pu être remplacé ; le précédent est conservé.",
}


class MelonDSCommands:
    def __init__(self, environment: dict, process, rom_path: str, state_directory: str, *, clock=time.time):
        if set(environment) != {"PCE_BRIDGE_DIR", "PCE_BRIDGE_SESSION"}:
            raise ValueError("La session de commandes melonDS est absente.")
        self.directory = local_path(environment["PCE_BRIDGE_DIR"])
        self.session = environment["PCE_BRIDGE_SESSION"]
        if not self.directory.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", self.session):
            raise ValueError("La session de commandes melonDS est invalide.")
        self.process = process
        self.pid = process.pid
        self.rom_hash = file_hash(_regular(local_path(rom_path)))
        self.states = local_path(state_directory)
        self.clock = clock
        self.instance = None
        self.sequence = 0
        self.pending = None
        self.status = None

    def _read(self, name):
        path = local_path(self.directory / name)
        if not path.exists():
            return None
        # Windows may deny opening a file during the native atomic replacement.
        # Retry only this bounded read; no command is resent or re-executed.
        for attempt in range(3):
            try:
                _regular(path)
                with path.open("rb") as handle:
                    data = handle.read(8193)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.005)
        if len(data) > 8192:
            raise ValueError("Réponse melonDS trop volumineuse.")
        document = json.loads(data, object_pairs_hook=_strict_pairs)
        if not isinstance(document, dict):
            raise ValueError("Réponse melonDS invalide.")
        return document

    def _owned_process(self):
        if (self.process.pid != self.pid or self.process.poll() is not None
                or local_path(self.directory / "stop").exists()):
            raise ValueError("Cette session melonDS est terminée ; relancez la partie depuis PCE.")

    def _identity(self, document):
        if (type(document.get("version")) is not int or document["version"] != 1
                or document.get("session_id") != self.session
                or type(document.get("pid")) is not int or document["pid"] != self.pid
                or not isinstance(document.get("instance_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", document["instance_id"])):
            raise ValueError("La réponse melonDS ne correspond pas au processus de cette partie.")
        if self.instance is not None and document["instance_id"] != self.instance:
            raise ValueError("L'instance melonDS a changé ; relancez cette partie.")

    def refresh(self):
        self.status = None
        self._owned_process()
        status = self._read("melonds-controls.json")
        if status is None:
            return None
        self._identity(status)
        if type(status.get("timestamp_ms")) is not int:
            raise ValueError("Date de réponse melonDS invalide.")
        age = self.clock() * 1000 - status["timestamp_ms"]
        if (not -1000 <= age <= 3000
                or status.get("available") is not True):
            return None
        if status.get("rom_sha256") != self.rom_hash or local_path(status.get("state_directory", "")) != self.states:
            raise ValueError("La cartouche ou les save states melonDS ne correspondent pas à cette partie.")
        capabilities = status.get("capabilities")
        if (not isinstance(capabilities, list) or any(not isinstance(value, str) for value in capabilities)
                or not set(capabilities) <= CAPABILITIES):
            raise ValueError("Les commandes de cette version melonDS ne sont pas reconnues.")
        self.instance = status["instance_id"]
        self.status = status
        return status

    def request(self, command: str, parameters: dict):
        if not isinstance(command, str) or not isinstance(parameters, dict):
            raise ValueError("Paramètres de commande melonDS invalides.")
        status = self.refresh()
        if status is None or command not in status["capabilities"]:
            raise ValueError("Commandes melonDS indisponibles. Lancez la version PCE récente de cette partie.")
        if self.pending is not None:
            raise ValueError("Une commande melonDS est déjà en attente de résultat.")
        if command == "speed":
            valid = (set(parameters) == {"value"} and isinstance(parameters["value"], str)
                     and parameters["value"] in {"x1", "x2", "x4", "MAX"})
        elif command in {"save_state", "load_state"}:
            valid = set(parameters) == {"slot"} and type(parameters["slot"]) is int and 1 <= parameters["slot"] <= 8
        elif command == "screen_layout":
            valid = set(parameters) == {"value"} and type(parameters["value"]) is int and 0 <= parameters["value"] <= 3
        elif command == "input_pulse":
            valid = (set(parameters) == {"mask", "frames"} and type(parameters["mask"]) is int
                     and 1 <= parameters["mask"] <= 4095 and type(parameters["frames"]) is int
                     and 1 <= parameters["frames"] <= 60 and parameters["mask"] & 48 != 48
                     and parameters["mask"] & 192 != 192)
        else:
            valid = not parameters
        if not valid:
            raise ValueError("Paramètres de commande melonDS invalides.")
        self.sequence += 1
        request = dict(version=1, session_id=self.session, instance_id=self.instance, pid=self.pid,
                       rom_sha256=self.rom_hash, sequence=self.sequence, expires_ms=int(self.clock() * 1000) + 5000,
                       command=command, parameters=parameters)
        target = local_path(self.directory / "melonds-command.json")
        temporary = local_path(self.directory / "melonds-command.json.tmp")
        created = False
        try:
            with temporary.open("xb") as handle:
                created = True
                handle.write(json.dumps(request, separators=(",", ":")).encode())
            # The native reader may briefly hold the old command on Windows.
            # Publish this same request once; never retry an executed action.
            for attempt in range(3):
                try:
                    temporary.replace(target)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.005)
        finally:
            if created:
                temporary.unlink(missing_ok=True)
        self.pending = request
        return request

    def poll_result(self):
        if self.pending is None:
            return None
        self._owned_process()
        if self.clock() * 1000 > self.pending["expires_ms"] + 1000:
            self.pending = None
            raise ValueError("Aucun accusé melonDS reçu : résultat non confirmé. Vérifiez melonDS avant de réessayer.")
        result = self._read("melonds-command-result.json")
        if result is not None:
            self._identity(result)
            if type(result.get("sequence")) is not int:
                raise ValueError("Accusé melonDS invalide.")
            if result["sequence"] == self.pending["sequence"]:
                if (type(result.get("timestamp_ms")) is not int
                        or not self.pending["expires_ms"] - 6000 <= result["timestamp_ms"] <= self.clock() * 1000 + 1000
                        or result.get("command") != self.pending["command"] or type(result.get("ok")) is not bool
                        or (result["ok"] and result.get("error") is not None)
                        or (result["ok"] and result["command"] == "speed" and result.get("speed") != self.pending["parameters"]["value"])):
                    raise ValueError("Résultat melonDS incohérent avec la commande envoyée.")
                if result["ok"] and result["command"] == "input_pulse":
                    if type(result.get("frames")) is not int or result["frames"] != self.pending["parameters"]["frames"]:
                        raise ValueError("Le nombre de frames d'entrée exécutées n'est pas confirmé.")
                self.pending = None
                if not result["ok"]:
                    raise ValueError(ERRORS.get(result.get("error"), "melonDS a refusé la commande."))
                return result
        return None
