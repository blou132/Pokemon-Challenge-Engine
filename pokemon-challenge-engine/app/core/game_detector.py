"""Inspection en lecture seule d'une ROM Nintendo DS choisie par l'utilisateur."""

from pathlib import Path

# Les trois premiers caractères du code jeu sont indépendants de la région.
# Référence des codes : https://github.com/FlagBrew/PKSM/wiki/FAQs
# Structure de l'en-tête : https://github.com/WerWolv/ImHex-Patterns/blob/master/patterns/nds.hexpat
GAME_CODE_PREFIXES = {"IRB": "black", "IRA": "white", "IRE": "black2", "IRD": "white2"}


class GameDetector:
    """Une indication issue de l'en-tête, jamais une preuve d'intégrité de la ROM."""

    @staticmethod
    def detect(rom_path: Path | str) -> str | None:
        path = Path(rom_path).expanduser()
        if not path.is_file():
            raise ValueError("Le fichier ROM sélectionné n'existe pas.")
        if path.suffix.lower() != ".nds":
            raise ValueError("Sélectionnez une ROM Nintendo DS au format .nds.")
        try:
            with path.open("rb") as rom:
                header = rom.read(16)
        except OSError as error:
            raise ValueError("Impossible de lire l'en-tête de cette ROM.") from error
        if len(header) < 16:
            raise ValueError("Ce fichier est trop court pour être une ROM Nintendo DS.")
        try:
            code = header[12:16].decode("ascii")
        except UnicodeDecodeError:
            return None
        return GAME_CODE_PREFIXES.get(code[:3])


def detect_game(rom_path: Path | str) -> str | None:
    return GameDetector.detect(rom_path)
