"""Configuration and batch dispatch checks; never extracts, signs or installs a game."""
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import prepare_games as launcher


class PrepareGamesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = self.root / 'games.local.toml'
        (self.root / 'keys').mkdir()
        (self.root / 'keys/prod.keys').touch()
        for name in ('one', 'two'):
            (self.root / name).mkdir()
            (self.root / name / 'base.nsp').touch()
        self.text = '''version = 1
[defaults]
keys = "keys/prod.keys"
workspace = "Games.xcworkspace"
[games.one]
path = "one"
bundle_id = "com.example.one"
[games.two]
path = "two"
bundle_id = "com.example.two"
'''
        self.config.write_text(self.text)

    def run_cli(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return launcher.main(['--config', str(self.config), *args])

    def test_relative_paths_and_environment_expansion(self):
        self.config.write_text(self.text.replace('keys/prod.keys', '${NX_TEST_KEYS}/prod.keys'))
        with patch.dict(os.environ, NX_TEST_KEYS=str(self.root / 'keys')):
            game = launcher.load_config(self.config)['one']
        self.assertEqual(game.keys, self.root / 'keys/prod.keys')
        self.assertEqual(game.path, self.root / 'one')
        self.assertEqual(game.workspace, self.root / 'Games.xcworkspace')

    def test_override_and_paths_are_literal_subprocess_arguments(self):
        folder = self.root / "Game ' with $ and `ticks`"
        folder.mkdir()
        self.config.write_text(self.text.replace('path = "one"', f'path = "{folder.name}"\nkeys = "custom.keys"\nteam_id = "ABCDEFGHIJ"'))
        game = launcher.load_config(self.config)['one']
        command = game.command()
        self.assertIn(str(folder), command)
        self.assertEqual(command[command.index('-k') + 1], str(self.root / 'custom.keys'))
        self.assertEqual(command[command.index('--team-id') + 1], 'ABCDEFGHIJ')
        self.assertEqual(command[0], sys.executable)

    def test_invalid_config_rejected(self):
        for text in (self.text.replace('version = 1', 'version = 2'),
                     self.text.replace('com.example.two', 'COM.EXAMPLE.ONE'),
                     self.text.replace('path = "two"', 'path = "one"'),
                     self.text.replace('path = "one"', 'paths = "one"'),
                     self.text.replace('keys/prod.keys', '${NX_TEST_MISSING}/prod.keys'),
                     self.text.replace('com.example.one', 'not a bundle identifier')):
            with self.subTest(text=text):
                self.config.write_text(text)
                with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
                    launcher.load_config(self.config)

    def test_explicit_selection_required_and_unknown_alias_rejected(self):
        with patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(self.run_cli('prepare'), 1)
            self.assertEqual(self.run_cli('prepare', 'missing'), 1)
            self.assertEqual(self.run_cli('prepare', 'one', '--all'), 1)
            run.assert_not_called()

    def test_batch_validates_all_paths_before_starting(self):
        (self.root / 'two/base.nsp').unlink()
        with patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(self.run_cli('prepare', '--all'), 1)
            run.assert_not_called()

    def test_check_and_list_do_not_prepare(self):
        with patch.object(launcher.subprocess, 'run') as run:
            self.assertEqual(self.run_cli('check'), 0)
            (self.root / 'keys/prod.keys').unlink()
            self.assertEqual(self.run_cli('list'), 0)
            self.assertEqual(self.run_cli('check', 'one'), 1)
            run.assert_not_called()

    def test_prepare_one_and_batch_stop_on_failure(self):
        with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(self.run_cli('prepare', 'two'), 0)
            self.assertEqual(run.call_count, 1)
            self.assertIn(str(self.root / 'two'), run.call_args.args[0])
            self.assertNotIn('shell', run.call_args.kwargs)
        with patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)) as run:
            self.assertEqual(self.run_cli('prepare', '--all'), 1)
            self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
