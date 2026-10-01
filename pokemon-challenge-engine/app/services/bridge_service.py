"""Consomme des fichiers locaux atomiques ; aucun accès aux ROM ni sauvegardes."""

from collections.abc import Callable
from dataclasses import replace
import math
import os
from pathlib import Path
import re
from time import monotonic
from uuid import uuid4

from app.bridge.protocol import GAME_IDS, MAX_MESSAGE_BYTES, BridgeMessage, ProtocolError, parse_message
from app.bridge.state import BridgeState

_SNAPSHOT_NAME = re.compile(r"snapshot-([0-9]{1,64})\.json\Z")
_OBSERVATION_NAME = re.compile(r"observation-([0-9]{10})\.json\Z")
_MAX_DIRECTORY_ENTRIES = 512


class BridgeService:
    """Une session isolée par démarrage ; appeler poll depuis le worker d'interface."""

    def __init__(self, root: Path, timeout_seconds: float = 3.0, clock: Callable[[], float] = monotonic) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("Le délai de déconnexion doit être un nombre positif.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Le délai de déconnexion doit être un nombre positif et fini.")
        self.root = Path(root)
        self.timeout_seconds = float(timeout_seconds)
        self._clock = clock
        self._state = BridgeState()
        self._session_dir: Path | None = None
        self._session_id: str | None = None
        self._started_at: float | None = None
        self._expected_code: str | None = None
        self._expected_revision: int | None = None

    @property
    def state(self) -> BridgeState:
        return self._state

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def start(self, game_id: str, rom_code: str | None = None, rom_revision: int | None = None) -> BridgeState:
        if not isinstance(game_id, str) or game_id not in GAME_IDS:
            raise ValueError("La passerelle accepte Pokémon Noir, Blanc, Noir 2 et Blanc 2.")
        if rom_code is not None and (not isinstance(rom_code, str) or re.fullmatch(r"[A-Z0-9]{4}", rom_code) is None):
            raise ValueError("Le code de ROM attendu est invalide.")
        if rom_revision is not None and (type(rom_revision) is not int or not 0 <= rom_revision <= 255):
            raise ValueError("La révision de ROM attendue est invalide.")
        self.stop()
        self._expected_code = rom_code
        self._expected_revision = rom_revision
        self._session_id = uuid4().hex
        self._session_dir = self.root / self._session_id
        try:
            self._session_dir.mkdir(parents=True, exist_ok=False)
        except OSError:
            self._session_dir = None
            self._session_id = None
            self._state = BridgeState(status="error", expected_game=game_id,
                                      last_error="Impossible de créer le dossier local de la passerelle.")
            return self._state
        self._started_at = self._clock()
        self._state = BridgeState(status="waiting", expected_game=game_id)
        return self._state

    def stop(self) -> BridgeState:
        if self._session_dir is not None:
            try:
                (self._session_dir / "stop").touch(exist_ok=True)
            except OSError:
                # L'arrêt local reste possible si le dossier a été déplacé ou verrouillé.
                pass
        self._session_dir = None
        self._session_id = None
        self._started_at = None
        self._expected_code = None
        self._expected_revision = None
        self._state = BridgeState()
        return self._state

    def _latest_snapshot(self) -> tuple[int, Path] | None:
        if self._session_dir is None:
            return None
        latest: tuple[int, Path] | None = None
        with os.scandir(self._session_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_DIRECTORY_ENTRIES:
                    raise ProtocolError("Trop de fichiers dans la session locale ; redémarrez la passerelle.")
                match = _SNAPSHOT_NAME.fullmatch(entry.name)
                if match is None or not entry.is_file(follow_symlinks=False):
                    continue
                sequence = int(match[1])
                if latest is None or sequence > latest[0]:
                    latest = sequence, Path(entry.path)
        return latest

    def _validate_session(self, message: BridgeMessage) -> None:
        if message.session_id != self._session_id:
            raise ProtocolError("Message ignoré : il appartient à une autre session.")
        if message.game_id is not None and message.game_id != self._state.expected_game:
            raise ProtocolError("Message ignoré : le jeu reçu ne correspond pas au jeu sélectionné.")
        if self._expected_code is not None and message.game_code is not None and message.game_code != self._expected_code:
            raise ProtocolError("Message ignoré : le code de ROM ne correspond pas à la ROM configurée.")
        if (self._expected_revision is not None and message.rom_revision is not None
                and message.rom_revision != self._expected_revision):
            raise ProtocolError("Message ignoré : la révision de ROM ne correspond pas à la ROM configurée.")

    def _accept(self, message: BridgeMessage, now: float) -> None:
        status = "receiving" if message.party_size is not None else "connected"
        error = message.error
        if message.event == "bridge_error":
            status = "error"
            error = error or "Le script Lua a signalé une erreur."
        elif message.event == "emulator_closing":
            status = "disconnected"
            error = error or "Le script Lua ou l'émulateur a été fermé."
        self._state = BridgeState(
            status=status, expected_game=self._state.expected_game, game_id=message.game_id,
            game_code=message.game_code, game_region=message.game_region, rom_revision=message.rom_revision,
            script_version=message.script_version, memory_profile=message.memory_profile, capabilities=message.capabilities,
            party_size=message.party_size if status in {"connected", "receiving"} else None,
            party=message.party if status in {"connected", "receiving"} else None,
            received_count=self._state.received_count + 1, last_received_at=now,
            last_timestamp=message.timestamp, last_event=message.event, last_error=error, sequence=message.sequence,
            protocol_version=message.protocol_version, session_id=message.session_id,
            observation=message.observation if status in {"connected", "receiving"} else None,
        )

    def _read_observations(self) -> tuple[dict, ...]:
        """Journal durable : une observation peut survivre à plusieurs snapshots."""
        if self._session_dir is None or not (self._state.connected or self._state.last_event == "emulator_closing"):
            return ()
        pending = []
        with os.scandir(self._session_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_DIRECTORY_ENTRIES:
                    raise ProtocolError("Trop de fichiers dans la session locale ; redémarrez la passerelle.")
                match = _OBSERVATION_NAME.fullmatch(entry.name)
                if match and entry.is_file(follow_symlinks=False):
                    pending.append((int(match[1]), Path(entry.path)))
        if len(pending) > 256:
            raise ProtocolError("Journal d'observations plein ; suivi suspendu sans supprimer les événements.")
        observations = []
        for sequence, path in sorted(pending):
            # Le snapshot confirme la publication complète de cette observation.
            if sequence > self._state.sequence:
                continue
            with path.open("rb") as handle:
                message = parse_message(handle.read(MAX_MESSAGE_BYTES + 1))
            self._validate_session(message)
            if message.sequence != sequence or message.protocol_version != 2 or message.observation is None:
                raise ProtocolError("Entrée du journal d'observations invalide.")
            if (message.game_id, message.game_code, message.game_region, message.rom_revision) != (
                self._state.game_id, self._state.game_code, self._state.game_region, self._state.rom_revision
            ):
                raise ProtocolError("L'identité du jeu a changé dans le journal ; nouvelle connexion requise.")
            observations.append({"id": f"{message.session_id}:{sequence}", "session_id": message.session_id,
                                 "sequence": sequence, "timestamp": message.timestamp,
                                 "observation": message.observation})
        return tuple(observations)

    def acknowledge_observations(self, state: BridgeState) -> None:
        """Appelé après persistance réussie (ou consultation sans profil actif)."""
        if (self._session_dir is None or state.session_id != self._session_id
                or not (state.connected or state.last_event == "emulator_closing") or state.protocol_version < 2):
            return
        for item in state.observations:
            # Le nom provient exclusivement du numéro validé, jamais d'un chemin reçu.
            path = self._session_dir / f"observation-{item['sequence']:010d}.json"
            path.unlink(missing_ok=True)
        temporary = self._session_dir / "ack.txt.tmp"
        temporary.write_text(str(state.sequence), encoding="ascii")
        temporary.replace(self._session_dir / "ack.txt")

    def poll(self) -> BridgeState:
        """Lit uniquement le dernier instantané complet, sans rafraîchir les doublons."""
        if self._session_dir is None:
            return self._state
        now = self._clock()
        try:
            latest = self._latest_snapshot()
            if latest is not None and latest[0] > self._state.sequence:
                with latest[1].open("rb") as handle:
                    payload = handle.read(MAX_MESSAGE_BYTES + 1)
                message = parse_message(payload)
                if message.sequence != latest[0]:
                    raise ProtocolError("Le numéro de séquence du fichier et du message diffèrent.")
                self._validate_session(message)
                if message.sequence > self._state.sequence:
                    self._accept(message, now)
            self._state = replace(self._state, observations=self._read_observations())
        except FileNotFoundError:
            # Le producteur peut retirer l'ancien instantané pendant cette lecture.
            pass
        except (OSError, ProtocolError) as exc:
            detail = str(exc) if isinstance(exc, ProtocolError) else "Impossible de lire le dossier local de la passerelle."
            self._state = replace(self._state, status="error", party_size=None, party=None,
                                  observation=None, observations=(), last_error=detail)
        last_activity = self._state.last_received_at
        if last_activity is None:
            last_activity = self._started_at
        if last_activity is not None and now - last_activity >= self.timeout_seconds:
            self._state = replace(
                self._state, status="disconnected", party_size=None, party=None, observation=None, observations=(),
                last_error="Aucun message Lua récent : connexion perdue ou script arrêté.",
            )
        return self._state
