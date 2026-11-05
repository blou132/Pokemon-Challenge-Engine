"""Discover the user's permanent library independently of an installation/build."""

from copy import deepcopy
from pathlib import Path
import re

from app.services.auto_setup_service import AutoSetupService
from app.services.discovery_safety import file_signature


class LibrarySetupService(AutoSetupService):
    def __init__(self, base_dir, config, library, catalog, *, source_directories=()):
        super().__init__(base_dir, config)
        self.library = library
        self.catalog = catalog
        self.source_directories = tuple(Path(path) for path in source_directories)
        self._library_report = None
        self._library_signature = None
        self._bootstrap_done = False

    @staticmethod
    def _bind_master(profile, path, emulator):
        profile.update(rom_path=str(path), emulator_kind='melonds', emulator_path=str(emulator or ''),
                       ini_path='', save_path='', save_state_directory='', save_state_stem='',
                       apply_settings=False, lua_connection='manual')

    def _signature(self, entries):
        paths = [self.library.manifest_path, *(self.library.master_path(entry) for entry in entries)]
        if self._library_report:
            paths += [Path(item['path']) for item in self._library_report['emulators']]
        values = []
        for path in paths:
            try:
                values.append((str(path), file_signature(path)))
            except OSError:
                values.append((str(path), None))
        return tuple(values)

    def automatic_setup(self, force=False, game_id=None):
        from app.services.melonds_runtime import find_installation
        with self._lock:
            entries = self.library.list_entries()
            # Initial personal preparation only. Updates use the already imported
            # masters, even if the original folder or old installation disappears.
            if not self._bootstrap_done:
                if not entries:
                    for folder in self.source_directories:
                        if folder.is_dir():
                            self.library.import_directory(folder)
                            break
                    entries = self.library.list_entries()
                self._bootstrap_done = True
            if not entries:
                from app.core.game_detector import GEN4_GAME_IDS
                if game_id in GEN4_GAME_IDS:
                    raise ValueError('Importez ce jeu dans Paramètres → Bibliothèque de jeux avant de créer une aventure.')
                return super().automatic_setup(force=force, game_id=game_id)
            # Preferences are small and can change independently of the master
            # inventory. Re-read them even on a library cache hit, and preserve
            # the existing refusal of corrupt configuration instead of silently
            # replacing the user's choices with defaults.
            _, preferences = self._preferences()
            profiles = preferences['launch_profiles']
            signature = self._signature(entries)
            if not force and self._library_report is not None and signature == self._library_signature:
                report = deepcopy(self._library_report)
                for entry in entries:
                    if report['library_integrity'][entry.game_id]['valid']:
                        self._bind_master(profiles[entry.game_id], self.library.master_path(entry),
                                          report['game_states'][entry.game_id]['emulator_path'])
                report['launch_profiles'] = profiles
                return report | {'cached': True}
            verified = {result.entry.game_id: result for result in self.library.verify()}
            emulator = find_installation(self.base_dir)
            report = {'library': True, 'library_root': str(self.library.root), 'game_states': {},
                      'games': [], 'emulators': [], 'installations': [], 'warnings': [], 'details': [],
                      'ready': False, 'prepared_games': [], 'cached': False, 'setup_complete': True,
                      'launch_profiles': profiles, 'library_integrity': {
                          key: {'sha256': result.entry.sha256, 'valid': result.valid, 'error': result.error}
                          for key, result in verified.items()}}
            if emulator:
                report['emulators'] = [{'path': str(emulator), 'emulator_kind': 'melonds'}]
            for game in self.catalog.games.values():
                if not game.supports_melonds:
                    continue
                state = {'status': 'not_found', 'message': 'Importez votre jeu dans Paramètres → Bibliothèque de jeux.',
                         'emulator_path': str(emulator or ''), 'candidate_id': '', 'save_path': ''}
                report['game_states'][game.id] = state
                result = verified.get(game.id)
                if result is None:
                    continue
                entry = result.entry
                path = self.library.master_path(entry)
                report['games'].append({'game_id': entry.game_id, 'game_code': entry.game_code,
                    'region': entry.region, 'revision': entry.revision, 'source_path': str(path),
                    'archive_member': None, 'source_kind': 'nds', 'id': entry.sha256,
                    'supported': result.valid, 'requires_choice': False, 'saves': []})
                state['candidate_id'] = entry.sha256
                if not result.valid:
                    state.update(status='needs_attention', message=result.error)
                    report['warnings'].append(result.error)
                    continue
                profile = profiles[game.id]
                self._bind_master(profile, path, emulator)
                state.update(status='ready' if emulator else 'needs_attention',
                    message=game.compatibility_summary if emulator else 'ROM vérifiée ; composant melonDS PCE indisponible.')
                report['ready'] |= bool(emulator)
            self._library_report = deepcopy(report)
            self._library_signature = self._signature(entries)
            return report


def source_reference(library, game_id):
    """Small manifest read for UI selection; hashing occurs in the preparation worker."""
    entry = next((entry for entry in library.list_entries() if entry.game_id == game_id), None)
    if entry is None:
        return None
    return {'root': str(library.root), 'game_id': entry.game_id, 'sha256': entry.sha256,
            'game_code': entry.game_code, 'region': entry.region, 'revision': entry.revision,
            'path': str(library.master_path(entry))}


def verify_library_source(run, source):
    """Refuse changed, missing or rebound masters before creating any derived ROM."""
    reference = (run.launch_profile or {}).get('_library_source')
    if reference is None:
        return None
    from app.services.rom_library_service import RomLibraryService
    if not isinstance(reference, dict) or set(reference) != {
            'root', 'game_id', 'sha256', 'game_code', 'region', 'revision', 'path'}:
        raise ValueError('Référence de bibliothèque invalide ; préparation refusée.')
    if any(not isinstance(reference[key], str) or not reference[key] or '\0' in reference[key]
           for key in ('root', 'game_id', 'sha256', 'game_code', 'region', 'path')) or \
            not Path(reference['root']).is_absolute() or not Path(reference['path']).is_absolute() or \
            not re.fullmatch(r'[0-9a-f]{64}', reference['sha256']) or \
            type(reference['revision']) is not int or not 0 <= reference['revision'] <= 255:
        raise ValueError('Référence de bibliothèque invalide ; préparation refusée.')
    library = RomLibraryService(Path(reference['root']))
    current = source_reference(library, run.game_id)
    if current != reference or Path(source) != Path(reference['path']):
        raise ValueError('La référence de la ROM maîtresse a changé ; préparation refusée.')
    if library.resolve(run.game_id) != Path(source):
        raise ValueError('La ROM maîtresse est absente ; préparation refusée.')
    return reference['sha256']
