"""Profile-bound observation consumer; call from the bridge worker, never Qt slots."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.core.catalog import Catalog
from app.core.nuzlocke_tracker import NuzlockeTracker
from app.core.profile_manager import ProfileManager
from app.events.game_event import GameObservation
from app.models.profile import Profile


@dataclass(frozen=True)
class TrackingState:
    profile_id: str | None = None
    profile_name: str | None = None
    status: str = "disabled"
    message: str = "Aucun profil actif : diagnostic uniquement."
    current_map_id: int | None = None
    current_zone_id: str | None = None
    zone_name: str | None = None
    zone_used: bool | None = None
    zone_status: str | None = None
    encounter: dict | None = None
    history: tuple[dict, ...] = ()
    revision: int = 0

    @property
    def enabled(self) -> bool:
        return self.status == "tracking"


class _TrackingBlocked(ValueError):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


class TrackingService:
    def __init__(self, base_dir: Path):
        self.manager = ProfileManager(Path(base_dir) / "profiles")
        self.games = Catalog.load(Path(__file__).resolve().parents[2] / "data").games
        self.tracker = NuzlockeTracker()
        self.state = TrackingState()
        self._profile: Profile | None = None
        self._last_sample: tuple | None = None

    def _publish(self, state: TrackingState) -> TrackingState:
        candidate = replace(state, revision=self.state.revision)
        if candidate != self.state:
            self.state = replace(candidate, revision=self.state.revision + 1)
        return self.state

    def _view(self, status: str, message: str, observation: GameObservation | None = None) -> TrackingState:
        profile = self._profile
        tracking = profile.progress["nuzlocke"] if profile else {}
        zone_id = observation.capture_zone_id if observation else tracking.get("current_zone_id")
        map_id = observation.map_id if observation else tracking.get("current_map_id")
        zone = tracking.get("zones", {}).get(zone_id, {})
        return self._publish(TrackingState(
            profile_id=profile.id if profile else self.state.profile_id,
            profile_name=profile.name if profile else None, status=status, message=message,
            current_map_id=map_id, current_zone_id=zone_id,
            zone_name=(observation.zone_name if observation else None) or zone.get("name"),
            zone_used=zone.get("used"), zone_status=zone.get("status"),
            encounter=deepcopy(zone.get("first_encounter") or zone.get("last_ignored")),
            history=tuple(deepcopy(profile.history[-100:])) if profile else ()))

    def select_profile(self, profile_id: str | None) -> TrackingState:
        self._profile = None
        self._last_sample = None
        self._publish(TrackingState(profile_id=profile_id))
        if profile_id is None:
            return self._view("disabled", "Aucun profil actif : diagnostic uniquement.")
        try:
            profile = self.manager.load(profile_id)
            if self.manager.warnings:
                raise ValueError("Progression ou historique absent ou corrompu ; suivi automatique suspendu.")
            self._profile = profile
        except (ValueError, OSError) as exc:
            return self._view("error", str(exc))
        if "nuzlocke" not in profile.challenge.active_rules:
            return self._view("disabled", "La règle Nuzlocke n'est pas active dans ce profil.")
        return self._view("waiting", "Profil chargé ; en attente de l'identité du jeu.")

    def _check_identity(self, profile: Profile, state: Any) -> None:
        if "nuzlocke" not in profile.challenge.active_rules:
            raise _TrackingBlocked("disabled", "La règle Nuzlocke n'est pas active dans ce profil.")
        game = self.games.get(profile.challenge.game_id)
        if game is None or game.game_code is None:
            raise _TrackingBlocked("mismatch", "Le jeu du profil n'a pas de profil mémoire pris en charge.")
        for field, expected in (("game_id", game.id), ("game_code", game.game_code),
                                ("game_region", game.region), ("rom_revision", game.revision)):
            actual = getattr(state, field, None)
            if actual is None:
                raise _TrackingBlocked("waiting", "Identité du jeu incomplète ; aucune progression enregistrée.")
            if expected is not None and actual != expected:
                raise _TrackingBlocked("mismatch", f"Jeu et profil incompatibles ({field} : {actual}, attendu : {expected}).")

    def consume(self, state: Any) -> TrackingState:
        entries = getattr(state, "observations", ()) or ()
        raw = getattr(state, "observation", None)
        try:
            current = GameObservation.from_dict(raw) if raw is not None else None
        except ValueError as exc:
            return self._view("error", str(exc))
        if self._profile is None:
            if self.state.profile_id is not None:
                return self._view("error", self.state.message, current)
            return self._view("disabled", "Aucun profil actif : diagnostic uniquement.", current)
        try:
            self._check_identity(self._profile, state)
        except _TrackingBlocked as exc:
            return self._view(exc.status, str(exc), current)
        closing = getattr(state, "last_event", None) == "emulator_closing" and bool(entries)
        if not getattr(state, "connected", False) and not closing:
            return self._view("waiting", "Passerelle déconnectée ; progression conservée.")
        if not entries and current is not None:
            sample = (getattr(state, "session_id", None), current)
            if sample != self._last_sample:
                entries = ({"session_id": getattr(state, "session_id", None),
                            "sequence": getattr(state, "sequence", 0),
                            "timestamp": getattr(state, "last_timestamp", None), "observation": raw},)
        try:
            parsed = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Journal d'observations invalide.")
                observation = GameObservation.from_dict(entry["observation"])
                source = entry["session_id"]
                sequence = entry["sequence"]
                timestamp = entry.get("timestamp")
                if not isinstance(source, str) or not source or type(sequence) is not int or sequence < 1:
                    raise ValueError("Identité du journal d'observations invalide.")
                if timestamp is not None and (type(timestamp) is not int or timestamp < 0):
                    raise ValueError("Date du journal d'observations invalide.")
                parsed.append((observation, source, sequence, timestamp))
            if parsed:
                def apply(profile: Profile) -> None:
                    self._check_identity(profile, state)
                    for observation, source, sequence, timestamp in parsed:
                        self.tracker.consume(profile, observation, session_id=source,
                                             sequence=sequence, timestamp=timestamp)
                self._profile = self.manager.update(self._profile.id, apply)
                if current is None:
                    current = parsed[-1][0]
            if current is not None:
                self._last_sample = (getattr(state, "session_id", None), current)
        except _TrackingBlocked as exc:
            return self._view(exc.status, str(exc), current)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return self._view("error", f"Suivi non enregistré : {exc}", current)
        if closing:
            return self._view("waiting", "Émulateur fermé ; dernières observations enregistrées.", current)
        if current is None or current.battle_active is None:
            return self._view("waiting", "Rencontres automatiques indisponibles : lectures de combat non documentées.", current)
        if current.capture_zone_id is None:
            return self._view("waiting", "Zone de capture non documentée ; aucune tentative consommée.", current)
        return self._view("tracking", "Suivi Nuzlocke actif, en lecture seule.", current)
