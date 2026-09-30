"""Diagnostic manuel du transport Lua réel, sans dépendance à l'interface Qt."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
import math
from pathlib import Path
import time

from app.bridge.state import BridgeState
from app.services.bridge_service import BridgeService

PROJECT_DIR = Path(__file__).resolve().parents[1]
_STATUS_LABELS = {
    "stopped": "Arrêté", "waiting": "En attente", "connected": "Connecté",
    "receiving": "Données reçues", "disconnected": "Déconnecté", "error": "Erreur",
}


def _duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("La durée doit être un nombre de secondes positif.") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise argparse.ArgumentTypeError("La durée doit être positive et finie.")
    return duration


def _prepare(base_dir: Path, bridge: BridgeService, game: str, rom_path: str) -> Path:
    # L'import tardif permet de consulter --help sans préparer de session.
    from app.services.emulator_service import EmulatorService

    return EmulatorService(base_dir, bridge).prepare(game, rom_path=rom_path)


def _display(payload: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, allow_nan=False), flush=True)
        return
    if payload["event"] == "prepared":
        print(f"Script Lua à charger dans DeSmuME : {payload['lua_path']}", flush=True)
        print(f"Session : {payload['session_id']} — durée : {payload['duration_seconds']:g} s", flush=True)
        print("Ouvrez la ROM puis chargez ce script dans la console Lua de DeSmuME.", flush=True)
    elif payload["event"] == "state":
        state = payload["state"]
        identity = " / ".join(str(state[key]) if state[key] is not None else "inconnu"
                              for key in ("game_id", "game_code", "game_region", "rom_revision"))
        profile = state["memory_profile"] or "non disponible"
        party = "non disponible" if state["party_size"] is None else str(state["party_size"])
        print(
            f"{_STATUS_LABELS[state['status']]} | messages : {state['received_count']} | "
            f"heartbeat : {payload['heartbeat_messages']} | fréquence reçue : {payload['reception_hz']:.2f}/s | "
            f"jeu/code/région/révision : {identity} | profil : {profile} | équipe : {party}", flush=True,
        )
        if state["last_error"]:
            print(f"Détail : {state['last_error']}", flush=True)
    elif payload["event"] == "summary":
        print(payload["message"], flush=True)
        print("Ce résultat mesure la connexion ; il ne valide pas les adresses mémoire du jeu.", flush=True)
    elif payload["event"] == "error":
        print(f"Diagnostic impossible : {payload['message']}", flush=True)


def _frequency(first_received: float | None, last_received: float | None, messages: int) -> float:
    if first_received is None or last_received is None or last_received <= first_received or messages < 2:
        return 0.0
    return round((messages - 1) / (last_received - first_received), 3)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vérifier le transport fichier entre DeSmuME/Lua et Python.")
    parser.add_argument("--game", choices=("black", "black2"), required=True, help="Jeu attendu : black (Noir) ou black2 (Noir 2).")
    parser.add_argument("--rom", default="", help="ROM locale à identifier en lecture seule ; son lancement reste manuel.")
    parser.add_argument("--duration", type=_duration, default=60.0, help="Durée de surveillance en secondes (défaut : 60).")
    parser.add_argument("--base-dir", type=Path, default=PROJECT_DIR, help="Dossier des fichiers locaux (défaut : dossier du projet).")
    parser.add_argument("--json", action="store_true", help="Émettre des événements JSONL pour conserver le diagnostic.")
    args = parser.parse_args(argv)
    base_dir = args.base_dir.expanduser().resolve()
    bridge = BridgeService(base_dir / "runtime" / "bridge")
    started_at = time.monotonic()
    heartbeat_messages = 0
    last_sequence = 0
    first_received: float | None = None
    last_emitted: BridgeState | None = None
    try:
        lua_path = _prepare(base_dir, bridge, args.game, args.rom)
        if bridge.state.status != "waiting" or bridge.session_id is None:
            raise ValueError(bridge.state.last_error or "La session de diagnostic n'a pas démarré.")
        _display({"event": "prepared", "lua_path": str(lua_path.resolve()), "session_id": bridge.session_id,
                  "duration_seconds": args.duration}, args.json)
        started_at = time.monotonic()
        deadline = started_at + args.duration
        while True:
            state = bridge.poll()
            if state.sequence > last_sequence:
                last_sequence = state.sequence
                if first_received is None:
                    first_received = state.last_received_at
                if state.last_event == "heartbeat" and "heartbeat" in state.capabilities:
                    heartbeat_messages += 1
            rate = _frequency(first_received, state.last_received_at, state.received_count)
            if state != last_emitted:
                _display({"event": "state", "state": asdict(state), "heartbeat_messages": heartbeat_messages,
                          "reception_hz": rate}, args.json)
                last_emitted = state
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.2, remaining))
        # Un fichier isolé ou une connexion déjà perdue ne suffit pas au succès.
        success = heartbeat_messages > 0 and state.received_count >= 2 and state.connected
        if success:
            result = "heartbeat_received"
            message = f"Connexion observée : {state.received_count} messages, dont {heartbeat_messages} heartbeat accepté(s)."
        elif heartbeat_messages == 0:
            result = "no_heartbeat"
            message = "Échec : aucun heartbeat Lua accepté pendant la surveillance."
        elif not state.connected:
            result = "disconnected"
            message = "Échec : le script Lua a émis, mais la connexion est interrompue en fin de surveillance."
        else:
            result = "insufficient_messages"
            message = "Échec : un seul message a été reçu ; une activité suivie n'a pas été vérifiée."
        _display({"event": "summary", "success": success, "result": result, "message": message,
                  "duration_seconds": round(time.monotonic() - started_at, 3), "received_messages": state.received_count,
                  "heartbeat_messages": heartbeat_messages, "reception_hz": rate, "state": asdict(state)}, args.json)
        return 0 if success else 1
    except KeyboardInterrupt:
        _display({"event": "error", "message": "Diagnostic interrompu par l'utilisateur."}, args.json)
        return 130
    except (OSError, ValueError) as exc:
        _display({"event": "error", "message": str(exc)}, args.json)
        return 2
    finally:
        bridge.stop()


if __name__ == "__main__":
    raise SystemExit(main())
