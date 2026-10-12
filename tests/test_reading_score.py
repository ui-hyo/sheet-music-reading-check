import unittest
from fractions import Fraction as F

from sheetcheck import reading as R
from sheetcheck.score import edit_distance, norm_chord, score

ANSWER = """key: -3
time: 4/4
m1 | chords: 1=C-7 | events: R:q G4:8 C5:8 Eb5:q {3 F5:8 G5:8 An5:8}
m2 | chords: 1=Dm7(b5) 3=G7(b9) | events: A5:q g(Bb5) Ab5:8 G5:8 F5:q. D5:8~
m3 | chords: 1=C-7 | events: D5:h R:q [C5+E5]:q
"""


def midis(text, fifths, bar):
    r = R.resolve(R.parse_text(text), fifths)
    return [[p.midi for p in e.pitches] for e in r.bars[bar].events]


def run(got, answer=ANSWER, fifths=-3):
    return score(R.parse_text(answer), R.parse_text(got), fifths)


class ParseTest(unittest.TestCase):
    def test_durations_and_tuplets_fill_the_bar(self):
        r = R.parse_text(ANSWER)
        self.assertEqual([b.length() for b in r.bars.values()], [F(4), F(4), F(4)])
        self.assertEqual(R.parse_dur('q.'), F(3, 2))
        self.assertEqual(R.parse_dur('h..'), F(7, 2))
        self.assertEqual([e.dur for e in R.parse_events('{3 C5:q D5:q E5:q}')], [F(2, 3)] * 3)

    def test_grace_note_has_no_length_and_shares_the_next_onset(self):
        ev = R.parse_text(ANSWER).bars[2].events
        self.assertEqual((ev[1].kind, ev[1].dur, ev[1].onset), ('grace', F(0), F(1)))
        self.assertEqual(ev[2].onset, F(1))

    def test_marks_in_either_order_and_group_uncertainty(self):
        a, b = R.parse_events('C6:8~? D6:8?~')
        self.assertTrue(a.tie and a.unc and b.tie and b.unc)
        self.assertTrue(all(e.unc for e in R.parse_events('{3 R:8 C5:8 D5:8}?')))

    def test_sharp_in_a_pitch_is_not_a_comment(self):
        r = R.parse_text('m1 | chords: 1=F#m7 | events: F#5:h G5:h # len=4')
        self.assertEqual((len(r.bars[1].events), r.bars[1].comment, r.bars[1].chords), (2, 'len=4', [('1', 'F#m7')]))

    def test_bad_and_duplicate_lines_are_unparsed_and_prose_is_ignored(self):
        r = R.parse_text('Here is my reading:\nm1 | chords: | events: C5:w\nm1 | chords: | events: D5:w\nm2 | chords: | events: H5:w\n')
        self.assertEqual((sorted(r.bars), len(r.unparsed)), ([1], 2))

    def test_rejects_malformed_events(self):
        for bad in ['{3 C5:8 D5:8', 'C5:8}', 'R:q~', 'g(C5)', 'C5', '{4 C5:8}', '{3 {3 C5:8} D5:8}']:
            with self.assertRaises(R.ReadingError, msg=bad):
                R.parse_events(bad)


class ResolveTest(unittest.TestCase):
    def test_key_signature_applies_without_a_printed_sign(self):
        self.assertEqual(midis('m1 | chords: | events: B4:q E5:q A4:q D5:q', -3, 1), [[70], [75], [68], [74]])
        self.assertEqual(midis('m1 | chords: | events: F4:q C5:q G4:q B4:q', 2, 1), [[66], [73], [67], [71]])

    def test_printed_accidental_carries_in_the_bar_for_that_octave_only(self):
        got = midis('m1 | chords: | events: Bn4:q B4:q B5:q Bb4:q\nm2 | chords: | events: B4:w', -3, 1)
        self.assertEqual(got, [[71], [71], [82], [70]])
        self.assertEqual(midis('m1 | chords: | events: Bn4:w\nm2 | chords: | events: B4:w', -3, 2), [[70]])

    def test_tie_across_the_barline_keeps_the_pitch_for_the_tied_note_only(self):
        text = 'm1 | chords: | events: R:h. F#5:q~\nm2 | chords: | events: F5:q F5:q R:h'
        self.assertEqual(midis(text, 0, 2), [[78], [77], []])
        untied = 'm1 | chords: | events: R:h. F#5:q\nm2 | chords: | events: F5:q F5:q R:h'
        self.assertEqual(midis(untied, 0, 2), [[77], [77], []])


class ScoreTest(unittest.TestCase):
    def test_identical_reading_has_no_errors(self):
        s = run(ANSWER)
        self.assertEqual((s['note_errors'], s['notes_total'], s['bars_notes_exact'], s['key_ok']), (0, 14, 3, True))
        self.assertEqual((s['ties_found'], s['ties_total'], s['chords_matched'], s['chords_total']), (1, 1, 4, 4))

    def test_one_wrong_pitch_costs_one(self):
        s = run(ANSWER.replace('G4:8 C5:8', 'G4:8 D5:8'))
        self.assertEqual((s['note_errors'], s['wrong_bars'], s['pitches_matched']), (1, [1], 14))

    def test_enharmonic_spelling_is_not_an_error(self):
        self.assertEqual(run(ANSWER.replace('Eb5:q', 'D#5:q'))['note_errors'], 0)

    def test_a_written_accidental_carries_to_the_next_same_note(self):
        # G#5 then G5 means G sharp twice, so the second note is now wrong.
        self.assertEqual(run(ANSWER.replace('Ab5:8', 'G#5:8'))['note_errors'], 1)

    def test_missing_printed_accidental_is_an_error(self):
        self.assertEqual(run(ANSWER.replace('An5:8', 'A5:8'))['note_errors'], 1)

    def test_dropped_added_and_relengthened_last_note(self):
        self.assertEqual(run(ANSWER.replace(' [C5+E5]:q', ''))['note_errors'], 1)
        self.assertEqual(run(ANSWER.replace('[C5+E5]:q', '[C5+E5]:8 G5:8'))['note_errors'], 2)
        self.assertEqual(run(ANSWER.replace('[C5+E5]:q', '[C5+E5]:8'))['note_errors'], 1)
        self.assertEqual(run(ANSWER.replace('[C5+E5]:q', '[C5+E5+G5]:q'))['note_errors'], 1)

    def test_misread_rest_shifts_what_follows(self):
        s = run(ANSWER.replace('R:q G4:8', 'R:8 G4:8'))
        self.assertEqual((s['note_errors'], s['bars_rhythm_exact']), (6, 2))

    def test_grace_note_read_as_a_normal_note(self):
        self.assertGreaterEqual(run(ANSWER.replace('g(Bb5) Ab5:8', 'Bb5:8 Ab5:8'))['note_errors'], 1)

    def test_missing_unparsed_and_extra_bars_cost_all_their_notes(self):
        lines = ANSWER.splitlines(keepends=True)
        s = run(''.join(lines[:3] + lines[4:]))
        self.assertEqual((s['note_errors'], s['missing_bars']), (6, [2]))
        s = run(ANSWER.replace('A5:q g(Bb5)', 'A5:z g(Bb5)'))
        self.assertEqual((s['note_errors'], s['unparsed_lines'], s['missing_bars']), (6, 1, [2]))
        s = run(ANSWER + 'm4 | chords: | events: C5:q D5:q R:h\n')
        self.assertEqual((s['note_errors'], s['extra_bars']), (2, [4]))

    def test_missed_tie_and_flags_are_reported_separately(self):
        s = run(ANSWER.replace('D5:8~', 'D5:8?'))
        self.assertEqual((s['note_errors'], s['ties_found'], s['flagged_bars'], s['bars_exact']), (0, 0, [2], 2))
        s = run(ANSWER.replace('G4:8 C5:8', 'G4:8 D5:8?'))
        self.assertEqual((s['wrong_and_flagged'], s['uncertain_events']), (1, 1))

    def test_key_is_scored_apart_from_the_notes(self):
        s = run(ANSWER.replace('key: -3', 'key: -2'))
        self.assertEqual((s['key_ok'], s['note_errors']), (False, 0))
        self.assertIsNone(run(ANSWER.replace('key: -3\n', ''))['key_ok'])

    def test_chord_symbol_spellings(self):
        same = [('C-7', 'Cm7', 'Cmin7', 'Cmi7'), ('Dm7(b5)', 'Dmin7b5', 'Dø7', 'Dø', 'D-7(b5)'), ('G7(b9)', 'G7b9', 'G7(♭9)'),
                ('C-/Bb', 'Cm/Bb', 'Cmin/B♭'), ('CM7', 'Cmaj7', 'C△7', 'Cma7', 'CMaj7'), ('F#dim7', 'F#o7', 'F♯°7'), ('C', 'CM', 'Cmaj')]
        for group in same:
            self.assertEqual(len({norm_chord(x) for x in group}), 1, group)
        self.assertNotEqual(norm_chord('Cm7'), norm_chord('CM7'))
        self.assertNotEqual(norm_chord('C7'), norm_chord('Cmaj7'))
        self.assertEqual(run(ANSWER.replace('1=C-7 |', '1=Cmin7 |').replace('G7(b9)', 'G7'))['chords_matched'], 3)

    def test_edit_distance(self):
        self.assertEqual(edit_distance(list('kitten'), list('sitting')), 3)
        self.assertEqual(edit_distance([], [1, 2]), 2)


if __name__ == '__main__':
    unittest.main()
