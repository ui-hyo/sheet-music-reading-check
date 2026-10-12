import contextlib
import io
import itertools
import json
import pathlib
import tempfile
import unittest
from fractions import Fraction as F

from sheetcheck import reading as R
from sheetcheck.compare import bar_length, compare, main
from sheetcheck.musicxml import main as musicxml_main
from sheetcheck.score import score

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS = ROOT / 'results' / 'no-tools'

A = """key: -2
time: 4/4
m1 | chords: 1=Cm7 3=F7 | events: R:q G4:8 C5:8 Eb5:q {3 F5:8 G5:8 An5:8}
m2 | chords: 1=Bbmaj7 | events: A5:q. G5:8~ G5:h
m3 | chords: 1=Gm7 | events: D5:h R:q [Bb4+D5]:q
"""


def listed(*texts, **kw):
    return {item['bar']: item['reasons'] for item in compare([R.parse_text(t) for t in texts], **kw)['check']}


def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main(list(args))
    return out.getvalue()


class CompareTest(unittest.TestCase):
    def test_equal_readings_list_nothing(self):
        self.assertEqual(listed(A, A), {})

    def test_another_spelling_of_the_same_pitch_is_not_a_difference(self):
        # B is flat in the key; a reader who writes the flat again has read the same note.
        self.assertEqual(listed(A, A.replace('[Bb4+D5]', '[B4+D5]').replace('Eb5:q', 'D#5:q')), {})

    def test_wrong_pitch_is_listed_with_its_beat(self):
        self.assertEqual(listed(A, A.replace('G4:8 C5:8', 'G4:8 B4:8')), {1: ['notes differ at beat 2.5']})
        self.assertEqual(listed(A, A.replace('G5:8 An5:8}', 'G5:8 Bn5:8}')), {1: ['notes differ at beat 4.67']})

    def test_unsure_mark_is_listed_with_who_made_it(self):
        self.assertEqual(listed(A, A.replace('D5:h', 'D5:h?')), {3: ['marked unsure by b']})
        self.assertEqual(listed(A.replace('D5:h', 'D5:h?')), {3: ['marked unsure by a']})

    def test_bar_that_does_not_add_up_is_listed_even_when_the_readings_agree(self):
        five = A.replace('D5:h R:q', 'D5:h R:q R:q')
        self.assertEqual(listed(five, five), {3: ['5 quarter notes in a, b, not 4']})
        self.assertEqual(listed(five), {3: ['5 quarter notes in a, not 4']})
        self.assertEqual(listed(A, five), {3: ['notes differ at beat 4, 5', '5 quarter notes in b, not 4']})

    def test_time_signature_sets_the_bar_length(self):
        self.assertEqual((bar_length('4/4'), bar_length('3/4'), bar_length('6/8'), bar_length('C'), bar_length(None)), (F(4), F(3), F(3), None, None))
        self.assertEqual(listed(A, A, time='3/4'), {n: ['4 quarter notes in a, b, not 3'] for n in (1, 2, 3)})
        # A reading with no time line is still checked, against the time the other one gives.
        five = A.replace('time: 4/4\n', '').replace('D5:h R:q', 'D5:h R:q R:q')
        self.assertIn('5 quarter notes in b, not 4', listed(A, five)[3])

    def test_missing_unparsed_and_repeated_lines(self):
        short = '\n'.join(A.splitlines()[:-1])
        self.assertEqual(listed(A, short), {3: ['missing from b']})
        self.assertEqual(listed(A, A.replace('D5:h R:q', 'H5:h R:q')), {3: ['the line in b cannot be parsed']})
        self.assertEqual(listed(A, A + 'm3 | chords: | events: C5:w\n'), {3: ['b gives this bar more than once']})

    def test_tie_rest_and_chord_differences(self):
        self.assertEqual(listed(A, A.replace('G5:8~', 'G5:8')), {2: ['ties differ']})
        self.assertEqual(listed(A, A.replace('R:q G4:8', 'R:8 R:8 G4:8')), {1: ['rests differ']})
        self.assertEqual(listed(A, A.replace('3=F7', '4=F7')), {1: ['chord symbols differ']})
        self.assertEqual(listed(A, A.replace('1=Cm7', '1=C-7').replace('Bbmaj7', 'BbM7')), {})

    def test_reading_without_chord_symbols_is_left_out_only_when_asked(self):
        bare = '\n'.join(line.split('| chords:')[0] + '| chords: |' + line.split('|')[2] if line.startswith('m') else line for line in A.splitlines())
        # A score that lost every chord symbol on the way through MuseScore must not pass as equal.
        self.assertEqual(listed(A, bare), {n: ['chord symbols differ'] for n in (1, 2, 3)})
        result = compare([R.parse_text(A), R.parse_text(A), R.parse_text(bare)])
        self.assertEqual([item['bar'] for item in result['check']], [1, 2, 3])
        self.assertIn('leave it out with --no-chords c', result['remarks'][0])
        # An OMR export has none to begin with: the caller says so, and the other two are still compared.
        self.assertEqual(listed(A, A, bare, no_chords='c'), {})
        self.assertEqual(listed(A, A.replace('3=F7', '4=F7'), bare, no_chords='c'), {1: ['chord symbols differ']})
        with self.assertRaises(ValueError):
            listed(A, A, no_chords='c')

    def test_bar_that_no_reading_has_is_listed_when_later_bars_exist(self):
        gap = '\n'.join(line for line in A.splitlines() if not line.startswith('m2 '))
        self.assertEqual(listed(gap, gap), {2: ['in no reading']})

    def test_reading_without_any_bar_line_is_an_error_not_an_empty_list(self):
        for text in ('', 'key: 0\ntime: 4/4\nm1: C4:w\n'):
            with self.assertRaises(ValueError):
                listed(A, text)

    def test_stray_brace_makes_the_line_unusable(self):
        self.assertEqual(listed(A, A.replace('{3 F5:8', '{ F5:8')), {1: ['the line in b cannot be parsed']})

    def test_any_one_of_three_readings_that_differs_lists_the_bar(self):
        self.assertEqual(listed(A, A, A.replace('A5:q.', 'B5:q.')), {2: ['notes differ at beat 1']})

    def test_each_reading_is_resolved_with_its_own_key(self):
        # b believes in three flats and so reads the plain A in bar 2 as A flat: that must show.
        three = A.replace('key: -2', 'key: -3')
        result = compare([R.parse_text(A), R.parse_text(three)])
        self.assertEqual([item['bar'] for item in result['check']], [2])
        self.assertIn('do not agree on the key (a: -2, b: -3)', result['remarks'][0])
        self.assertEqual(listed(A, three, key=-2), {})

    def test_reading_without_a_key_does_not_borrow_one(self):
        plain = A.replace('[Bb4+D5]', '[B4+D5]')  # this B is flat only through the key
        result = compare([R.parse_text(plain), R.parse_text(plain.replace('key: -2\n', ''))])
        self.assertEqual(result['keys'], {'a': -2, 'b': 0})
        self.assertEqual(result['remarks'], ['no key given in b; taken as no sharps or flats'])
        self.assertEqual([item['bar'] for item in result['check']], [3])


class CommandTest(unittest.TestCase):
    def test_text_and_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = pathlib.Path(tmp, 'a.txt'), pathlib.Path(tmp, 'b.txt')
            a.write_text(A)
            b.write_text('Here is my reading.\n```\n' + A.replace('G4:8 C5:8', 'G4:8 B4:8') + '```\n')
            text = cli(str(a), str(b))
            self.assertIn('key -2, time 4/4, 3 bars (m1 to m3)', text)
            self.assertIn('1 bar to check: 1\n\nm1: notes differ at beat 2.5\n  a  m1 | chords: 1=Cm7 3=F7 | events: R:q G4:8 C5:8', text)
            self.assertIn('0 bars to check\n', cli(str(a), str(a)))
            got = json.loads(cli(str(a), str(b), '--json'))
            self.assertEqual((got['readings'], got['bars'], got['check'][0]['bar']), ({'a': str(a), 'b': str(b)}, 3, 1))
            self.assertEqual(sorted(got['check'][0]['lines']), ['a', 'b'])
            empty = pathlib.Path(tmp, 'empty.txt')
            empty.write_text('I could not read the page.\n')
            with self.assertRaises(SystemExit) as stop, contextlib.redirect_stderr(io.StringIO()) as err:
                main([str(a), str(empty)])
            self.assertEqual(stop.exception.code, 2)
            self.assertIn('no bar lines in reading b', err.getvalue())

    def test_musicxml_command_prints_a_reading_that_agrees_with_the_answer(self):
        page = ROOT / 'material' / 'lead-3'
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            musicxml_main([str(page / 'roundtrip.musicxml')])
        self.assertEqual(listed((page / 'answer.txt').read_text(), out.getvalue()), {})


class StoredReadingsTest(unittest.TestCase):
    """What docs/workflow.md says about the readings stored under results/."""

    def reading(self, product, page):
        path = RESULTS / product / f'{page}-clean.txt'
        return path.read_text() if path.exists() and path.read_text().strip() else None

    def audiveris(self, page):
        return (ROOT / 'results' / 'omr-only' / 'audiveris (OMR only)' / f'{page}-clean.txt').read_text()

    def wrong_bars(self, text, page):
        answer = R.parse_text((ROOT / 'material' / page / 'answer.txt').read_text())
        return set(score(answer, R.parse_text(text), answer.key)['wrong_bars'])

    def test_opus_and_astra_on_page_a(self):
        got = listed(self.reading('claude-code+opus-5.5', 'solo-1'), self.reading('codex-cli+gpt-6-astra', 'solo-1'))
        self.assertEqual(sorted(got), [7, 8, 27, 28])
        self.assertEqual(got[7], ['marked unsure by a'])
        self.assertEqual(self.wrong_bars(self.reading('claude-code+opus-5.5', 'solo-1'), 'solo-1'), {8})
        self.assertEqual(self.wrong_bars(self.reading('codex-cli+gpt-6-astra', 'solo-1'), 'solo-1'), {27, 28})

    def test_every_wrong_bar_is_listed_for_each_pair_of_a_current_claude_and_a_current_codex_reading(self):
        claude = ['claude-code+' + m for m in ('haiku-5.5', 'sonnet-5.5', 'opus-5.5', 'fable-5.1')]
        codex = ['codex-cli+' + m for m in ('gpt-6-luna', 'gpt-6-astra', 'gpt-6.1-sol')]
        pairs = 0
        for page, a, b in itertools.product(('solo-1', 'lead-3', 'solo-2'), claude, codex):
            ta, tb = self.reading(a, page), self.reading(b, page)
            if ta is None or tb is None:
                continue
            pairs += 1
            self.assertEqual((self.wrong_bars(ta, page) | self.wrong_bars(tb, page)) - set(listed(ta, tb)), set(), (page, a, b))
        self.assertEqual(pairs, 22)

    def test_audiveris_as_a_third_reading_adds_only_its_own_wrong_bars(self):
        sizes = []
        for page in ('solo-1', 'lead-3', 'solo-2'):
            pair = [self.reading('claude-code+opus-5.5', page), self.reading('codex-cli+gpt-6.1-sol', page)]
            two, three = set(listed(*pair)), set(listed(*pair, self.audiveris(page), no_chords='c'))
            sizes.append((len(two), len(three)))
            self.assertEqual(three - two, self.wrong_bars(self.audiveris(page), page) - two)
        self.assertEqual(sizes, [(2, 5), (0, 4), (0, 3)])

    def test_two_readers_can_make_the_same_mistake_and_a_third_reading_shows_it(self):
        for page, bar, a, b in [('lead-3', 12, 'claude-code+fable-5.1', 'claude-code+opus-5'), ('solo-1', 27, 'claude-code+opus-5', 'codex-cli+gpt-5.6-sol')]:
            ta, tb = self.reading(a, page), self.reading(b, page)
            self.assertIn(bar, self.wrong_bars(ta, page) & self.wrong_bars(tb, page))
            self.assertNotIn(bar, listed(ta, tb))
            self.assertEqual(listed(ta, tb, self.audiveris(page), no_chords='c')[bar][0][:12], 'notes differ')


if __name__ == '__main__':
    unittest.main()
