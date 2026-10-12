import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from sheetcheck.run import PRODUCTS, Hidden, build_prompt, rule_check


class RuleCheckTest(unittest.TestCase):
    def test_claude_may_only_read_the_page_image(self):
        self.assertEqual(rule_check('claude', [['Read', 'page.png']], 'page.png'), 'pass')
        self.assertEqual(rule_check('claude', [['Read', 'page.png'], ['Read', 'page.png']], 'page.png'), 'pass')
        self.assertEqual(rule_check('claude', [['Read', 'outside the run folder: answer.txt']], 'page.png'), 'violation')
        self.assertEqual(rule_check('claude', [['Read', 'page.png'], ['Bash', '']], 'page.png'), 'violation')
        self.assertEqual(rule_check('claude', [['Read', 'reading.txt']], 'page.png'), 'violation')

    def test_codex_may_not_use_any_tool(self):
        self.assertEqual(rule_check('codex', [], 'page.png'), 'pass')
        self.assertEqual(rule_check('codex', [['command_execution', 'ls']], 'page.png'), 'violation')

    def test_no_event_log_means_unverified_not_pass(self):
        self.assertEqual(rule_check('gemini', None, 'page.png'), 'unverified')
        self.assertEqual(rule_check('grok', None, 'page.png'), 'unverified')


class HiddenTest(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, 'root can read anything')
    def test_git_history_and_files_are_out_of_reach_while_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, done = Path(tmp) / 'repo', Path(tmp) / 'run-1'
            (repo / 'material').mkdir(parents=True)
            done.mkdir()
            (repo / 'material' / 'answer.txt').write_text('m1 | chords: | events: C5:w\n')
            (done / 'reading.txt').write_text('another reading\n')
            git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com', '-C', str(repo)]
            subprocess.run(git + ['init', '-q'], check=True)
            subprocess.run(git + ['add', '-A'], check=True)
            subprocess.run(git + ['commit', '-q', '-m', 'x'], check=True)
            show = ['git', '--git-dir', str(repo / '.git'), 'show', 'HEAD:material/answer.txt']
            self.assertEqual(subprocess.run(show, capture_output=True).returncode, 0)
            with Hidden([repo]) as hidden:
                hidden.add(done)
                self.assertNotEqual(subprocess.run(show, capture_output=True).returncode, 0)
                for path in (repo / 'material' / 'answer.txt', done / 'reading.txt'):
                    with self.assertRaises(PermissionError):
                        path.read_text()
            self.assertEqual(subprocess.run(show, capture_output=True).returncode, 0)
            self.assertEqual((done / 'reading.txt').read_text(), 'another reading\n')

    def test_disabled_hiding_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with Hidden([Path(tmp)], enabled=False) as hidden:
                hidden.add(Path(tmp))
                self.assertTrue(os.listdir(tmp) == [])


class PromptTest(unittest.TestCase):
    def test_prompt_names_the_file_or_the_attachment_and_carries_the_format(self):
        fmt = '# Reading format\n\nbody line\n'
        self.assertIn('Open the image file page.jpg', build_prompt('claude', 'page.jpg', fmt))
        self.assertIn('attached to this message', build_prompt('codex', 'page.png', fmt))
        self.assertIn('body line', build_prompt('grok', 'page.png', fmt))
        self.assertNotIn('# Reading format', build_prompt('grok', 'page.png', fmt))

    def test_every_product_has_a_known_vendor(self):
        self.assertTrue(all(p['vendor'] in ('claude', 'codex', 'gemini', 'grok') for p in PRODUCTS.values()))


if __name__ == '__main__':
    unittest.main()
