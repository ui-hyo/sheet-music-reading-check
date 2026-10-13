import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from sheetcheck import reading as R
from sheetcheck.compare import compare
from sheetcheck.musicxml import read_musicxml, to_reading_text

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'extras'))
import build_musicxml as B  # noqa: E402

# Chords of three and four notes, a tied chord, a grace note, triplets with a rest and with a chord, a section label.
CHORDS = """key: -3
time: 4/4
m1 | chords: 1=Cm7 3=F7 | events: R:8 [Eb4+G4+Bb4]:8 R:q [Eb4+A4+C5]:q. [D4+A4+C5]:8~ # section=Head
m2 | chords: 1=Bbmaj7 2.5=G7b9 | events: [D4+A4+C5]:q R:8 g(F#5) G5:8 {3 R:8 B4:8 D5:8} {3 [Ab4+Bn4+F5]:q G5:8}
m3 | chords: 1=Cm6 | events: [Eb4+G4+An4+D5]:h R:h
m4 | chords: 1=Ab/Bb | events: Bb4:q. C5:8~ C5:h
"""
LONG_REST = """key: 0
time: 4/4
m1 | chords: 1=C | events: C5:w
m2 | chords: | events: R:w # multirest=8 # section=Bass Solo
m3 | chords: 1=G7 | events: B4:h D5:h
"""


def back(xml: str) -> str:
    with tempfile.TemporaryDirectory() as work:
        path = pathlib.Path(work) / 'built.musicxml'
        path.write_text(xml, encoding='utf-8')
        return to_reading_text(read_musicxml(str(path)))


def listed(a: str, b: str):
    return [(item['bar'], item['reasons']) for item in compare([R.parse_text(a), R.parse_text(b)])['check']]


class BuildMusicXML(unittest.TestCase):
    def test_generated_pages_read_back_the_same(self):
        for page in ('solo-1', 'lead-3', 'solo-2'):
            text = (ROOT / 'material' / page / 'answer.txt').read_text()
            xml, mapping = B.build(text, title='A page', tempo=120)
            self.assertEqual(len(mapping), 32)
            self.assertEqual(listed(text, back(xml)), [], page)

    def test_chords_ties_graces_and_triplets_read_back_the_same(self):
        xml, _ = B.build(CHORDS)
        self.assertEqual(listed(CHORDS, back(xml)), [])
        notes = ET.fromstring(xml.split('\n', 2)[2]).find('part').findall('measure')[0].findall('note')
        # The last chord of bar 1 is tied to the same chord in bar 2: every one of its three notes starts a tie.
        self.assertEqual([len(n.findall('tie')) for n in notes[-3:]], [1, 1, 1])

    def test_only_the_pitches_that_come_again_are_tied(self):
        text = 'key: 0\ntime: 4/4\nm1 | chords: | events: [C4+E4+G4]:h~ [C4+F4+A4]:h\n'
        xml, _ = B.build(text)
        notes = ET.fromstring(xml.split('\n', 2)[2]).find('part').find('measure').findall('note')
        ties = [(n.findtext('pitch/step'), [t.get('type') for t in n.findall('tie')]) for n in notes]
        self.assertEqual(ties, [('C', ['start']), ('E', []), ('G', []), ('C', ['stop']), ('F', []), ('A', [])])

    def test_grace_note_between_two_tied_notes_does_not_break_the_tie(self):
        xml, _ = B.build('key: 0\ntime: 4/4\nm1 | chords: | events: C5:q~ g(D5) C5:q R:h\n')
        notes = ET.fromstring(xml.split('\n', 2)[2]).find('part').find('measure').findall('note')
        self.assertEqual([[t.get('type') for t in n.findall('tie')] for n in notes[:3]], [['start'], [], ['stop']])

    def test_long_rest_becomes_real_bars_and_the_map_says_which(self):
        xml, mapping = B.build(LONG_REST)
        measures = ET.fromstring(xml.split('\n', 2)[2]).find('part').findall('measure')
        self.assertEqual(len(measures), 10)
        self.assertEqual(measures[1].findtext('attributes/measure-style/multiple-rest'), '8')
        self.assertEqual(measures[1].findtext('direction/direction-type/rehearsal'), 'Bass Solo')
        self.assertEqual(mapping, [{'reading_bar': 1, 'first_real_bar': 1, 'real_bars': 1}, {'reading_bar': 2, 'first_real_bar': 2, 'real_bars': 8},
                                   {'reading_bar': 3, 'first_real_bar': 10, 'real_bars': 1}])

    def test_reading_written_out_compares_with_the_score_bar_for_bar(self):
        """With a long rest the bar numbers of the score run ahead, so the reading itself cannot be compared with it."""
        xml, _ = B.build(LONG_REST)
        self.assertNotEqual(listed(LONG_REST, back(xml)), [])
        written_out = B.expanded(LONG_REST)
        self.assertEqual(sorted(R.parse_text(written_out).bars), list(range(1, 11)))
        self.assertEqual(listed(written_out, back(xml)), [])

    def test_other_time_signature_and_guitar_octave(self):
        text = 'key: 2\ntime: 3/4\nm1 | chords: 1=D | events: F#4:q A4:q D5:q\nm2 | chords: | events: R:h.\n'
        xml, _ = B.build(text, octave_down=True, part_name='Guitar')
        attrs = ET.fromstring(xml.split('\n', 2)[2]).find('part').find('measure').find('attributes')
        self.assertEqual((attrs.findtext('time/beats'), attrs.findtext('time/beat-type'), attrs.findtext('transpose/octave-change')), ('3', '4', '-1'))

    def test_short_note_values_keep_their_exact_length(self):
        text = 'key: 0\ntime: 4/4\nm1 | chords: | events: C5:32. D5:32. E5:32 R:h R:q R:8\n'
        xml, _ = B.build(text)
        measure = ET.fromstring(xml.split('\n', 2)[2]).find('part').find('measure')
        div = int(measure.findtext('attributes/divisions'))
        self.assertEqual(sum(int(n.findtext('duration')) for n in measure.findall('note')), 4 * div)
        self.assertEqual(listed(text, back(xml)), [])

    def test_whole_bar_rest_in_three_four(self):
        xml, _ = B.build('key: 0\ntime: 3/4\nm1 | chords: | events: C5:h.\nm2 | chords: | events: R:w\n')
        rest = ET.fromstring(xml.split('\n', 2)[2]).find('part').findall('measure')[1].find('note')
        self.assertEqual((rest.find('rest').get('measure'), rest.findtext('duration')), ('yes', '72'))

    def test_bar_of_the_wrong_length_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'm1 adds up to 3'):
            B.build('key: 0\ntime: 4/4\nm1 | chords: | events: C5:h. \n')

    def test_chord_symbols(self):
        self.assertEqual(B.parse_symbol('G7alt')['kind'], 'other')
        self.assertEqual(B.parse_symbol('Cm(maj7)')['kind'], 'major-minor')
        self.assertEqual(B.parse_symbol('Bb7#11')['degrees'], [(11, 1, 'add')])
        self.assertEqual(B.parse_symbol('Ab/Bb')['bass'], ('B', -1))
        with self.assertRaises(ValueError):
            B.parse_symbol('H7')
        with self.assertRaisesRegex(ValueError, r"m2: chord quality in 'Cxyz'"):
            B.build('key: 0\ntime: 4/4\nm1 | chords: 1=C | events: C5:w\nm2 | chords: 1=Cxyz | events: C5:w\n')

    @unittest.skipUnless(shutil.which('mscore4'), 'MuseScore 4 is not installed')
    def test_round_trip_through_musescore(self):
        """Step 6 of docs/workflow.md: what MuseScore exports again is the reading that went in."""
        for text in ((ROOT / 'material' / 'solo-1' / 'answer.txt').read_text(), CHORDS):
            with tempfile.TemporaryDirectory() as work:
                work = pathlib.Path(work)
                (work / 'tune.musicxml').write_text(B.build(text, title='A page', tempo=120)[0], encoding='utf-8')
                for src, dst in (('tune.musicxml', 'tune.mscz'), ('tune.mscz', 'roundtrip.musicxml')):
                    subprocess.run(['mscore4', '-o', str(work / dst), str(work / src)], check=True, capture_output=True, timeout=180)
                self.assertEqual(listed(text, to_reading_text(read_musicxml(str(work / 'roundtrip.musicxml')))), [])


if __name__ == '__main__':
    unittest.main()
