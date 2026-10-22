#!/usr/bin/env python3
"""Prepare per-game Xcode projects from a developer's local TOML configuration.

Requires Python 3.11+ and the same environment as build_ipa_from_nsp.py.
Terminal: python3 scripts/prepare_games.py --config /external/games/games.local.toml prepare engage
Spyder: set CONFIG_FILE, ACTION and SELECTED_GAMES below, then press F5.
Game files, keys, generated projects and build products stay on the games drive.
"""
import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib

# ---- Settings (command-line arguments override these) ----
CONFIG_FILE = ''                       # empty = NXNATIVE_CONFIG environment, else games.local.toml in this repository
ACTION = 'list'                        # list, check, or prepare
SELECTED_GAMES = []                     # aliases from [games.<alias>]; empty checks all, but prepare requires a selection
ALL_GAMES = False                       # explicitly prepare every configured game

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FIELDS = {'keys', 'workspace', 'team_id'}
GAME_FIELDS = {'path', 'keys', 'bundle_id', 'team_id', 'package', 'app_name'}


@dataclass(frozen=True)
class Game:
    alias: str
    path: Path
    keys: Path
    workspace: Path
    bundle_id: str = ''
    team_id: str = ''
    package: str = ''
    app_name: str = ''

    def command(self):
        command = [sys.executable, str(REPO / 'scripts/build_ipa_from_nsp.py'),
                   str(self.path), '-k', str(self.keys), '--prepare-xcode',
                   '--keep-extracted', '--xcode-workspace', str(self.workspace)]
        for option, value in (('--bundle-id', self.bundle_id), ('--team-id', self.team_id),
                              ('--package', self.package), ('--app-name', self.app_name)):
            if value:
                command.extend([option, value])
        return command


def table(value, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a TOML table')
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f'{label}: unknown fields: {", ".join(sorted(unknown))}')
    for key, item in value.items():
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f'{label}.{key} must be a nonempty string; omit optional fields to use their defaults')
    return value


def resolve_path(value, base):
    expanded = os.path.expanduser(os.path.expandvars(value))
    if re.search(r'\$(?:[A-Za-z_]\w*|\{[^}]+\})', expanded):
        raise ValueError(f'unset environment variable in path: {value}')
    path = Path(expanded)
    return (path if path.is_absolute() else base / path).resolve()


def load_config(path):
    with path.open('rb') as source:
        config = tomllib.load(source)
    if set(config) - {'version', 'defaults', 'games'}:
        raise ValueError('config only accepts version, defaults and games')
    if type(config.get('version')) is not int or config['version'] != 1:
        raise ValueError('config must contain version = 1')
    defaults = table(config.get('defaults', {}), DEFAULT_FIELDS, 'defaults')
    entries = config.get('games')
    if not isinstance(entries, dict) or not entries:
        raise ValueError('add at least one [games.<alias>] table')
    workspace = resolve_path(defaults.get('workspace', 'NxNative.xcworkspace'), path.parent)
    if workspace.suffix != '.xcworkspace':
        raise ValueError('defaults.workspace must end in .xcworkspace')
    games, folders, bundle_ids = {}, {}, {}
    for alias, entry in entries.items():
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', alias):
            raise ValueError(f'invalid game alias: {alias}; use letters, numbers, underscores or hyphens')
        entry = table(entry, GAME_FIELDS, f'games.{alias}')
        values = defaults | entry
        for required in ('path', 'keys'):
            if required not in values:
                raise ValueError(f'games.{alias}: missing {required} (keys can also be set in defaults)')
        folder = resolve_path(values['path'], path.parent)
        keys = resolve_path(values['keys'], path.parent)
        bundle_id = values.get('bundle_id', '')
        if bundle_id and not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', bundle_id):
            raise ValueError(f'games.{alias}: invalid bundle_id: {bundle_id}')
        team_id = values.get('team_id', '')
        if team_id and not re.fullmatch(r'[A-Z0-9]{10}', team_id):
            raise ValueError(f'games.{alias}: team_id must be the 10-character Apple team ID')
        package = values.get('package', '')
        if package and not re.fullmatch(r'v[0-9]+', package):
            raise ValueError(f'games.{alias}: package must be a container version such as v327680')
        if folder in folders:
            raise ValueError(f'games.{alias} and games.{folders[folder]} use the same game folder')
        if bundle_id and bundle_id.lower() in bundle_ids:
            raise ValueError(f'games.{alias} and games.{bundle_ids[bundle_id.lower()]} use the same bundle ID')
        folders[folder] = alias
        if bundle_id:
            bundle_ids[bundle_id.lower()] = alias
        games[alias] = Game(alias, folder, keys, workspace, bundle_id, team_id,
                            package, values.get('app_name', ''))
    return games


def select_games(games, aliases, all_games, action):
    if all_games and aliases:
        raise ValueError('use game aliases or --all, not both')
    if not aliases and not all_games and action == 'prepare':
        raise ValueError('prepare requires a game alias or --all')
    unknown = set(aliases) - games.keys()
    if unknown:
        raise ValueError(f'unknown games: {", ".join(sorted(unknown))}; available: {", ".join(games)}')
    return [games[a] for a in dict.fromkeys(aliases)] if aliases else list(games.values())


def check_paths(games):
    errors = []
    for game in games:
        if not game.path.is_dir():
            errors.append(f'{game.alias}: game folder not found: {game.path}')
        elif not any(p.is_file() and p.suffix.lower() in ('.nsp', '.xci') for p in game.path.iterdir()):
            errors.append(f'{game.alias}: no NSP or XCI files directly inside {game.path}')
        if not game.keys.is_file():
            errors.append(f'{game.alias}: key file not found: {game.keys}')
    if errors:
        raise ValueError('\n'.join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=CONFIG_FILE or os.environ.get('NXNATIVE_CONFIG') or str(REPO / 'games.local.toml'),
                        help='local TOML file (default: CONFIG_FILE setting, NXNATIVE_CONFIG, or repository games.local.toml)')
    parser.add_argument('action', nargs='?', choices=('list', 'check', 'prepare'), default=ACTION)
    parser.add_argument('games', nargs='*', help='game aliases from the configuration')
    parser.add_argument('--all', action='store_true', default=ALL_GAMES, help='select every configured game; required for batch preparation')
    args = parser.parse_args(argv)
    try:
        config = Path(os.path.expandvars(os.path.expanduser(args.config))).resolve()
        if not config.is_file():
            raise ValueError(f'config not found: {config}\nCopy games.example.toml to your games drive, edit its paths, then pass --config <file>.')
        games = select_games(load_config(config), args.games or SELECTED_GAMES, args.all, args.action)
        for game in games:
            print(f'{game.alias}: {game.path}', flush=True)
            print(f'  bundle ID: {game.bundle_id or "saved Xcode ID, else org.nxnative.<title ID>"}', flush=True)
        if args.action == 'list':
            return 0
        # Validate every selection before starting any extraction or generation.
        check_paths(games)
        if args.action == 'check':
            for game in games:
                print(shlex.join(game.command()), flush=True)
            print('Configuration and input paths checked. Game contents and profile compatibility are checked during preparation.')
            return 0
        for index, game in enumerate(games, 1):
            print(f'Preparing {game.alias} ({index}/{len(games)})', flush=True)
            result = subprocess.run(game.command(), cwd=REPO)
            if result.returncode:
                print(f'[RED] {game.alias}: preparation failed; remaining games were not started', file=sys.stderr)
                return 130 if result.returncode in (-2, 130) else 1
        print(f'Open in Xcode: {games[0].workspace}')
        print('Choose the game scheme, your signing team and a connected iPhone or iPad, then Run.')
        return 0
    except (OSError, ValueError) as error:
        print(f'[RED] {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    # Spyder's F5 uses the settings above; its configured command-line arguments also work.
    code = main()
    if not hasattr(sys, 'ps1') and 'IPython' not in sys.modules:
        sys.exit(code)
