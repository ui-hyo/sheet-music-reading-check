import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

from sheetcheck import reading as R
from sheetcheck.generate import answer_text, make_page
from sheetcheck.material import verify
from sheetcheck.musicxml import read_musicxml, to_reading_text, write_musicxml
from sheetcheck.score import all_items, norm_chord, score


def read_back(page):
    """Write a page as MusicXML and read it with the independent reader."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'page.musicxml'
        path.write_text(write_musicxml(page), encoding='utf-8')
        return read_musicxml(str(path))


class GeneratorTest(unittest.TestCase):
    def test_same_seed_gives_the_same_page(self):
        self.assertEqual(answer_text(make_page('solo', 7)), answer_text(make_page('solo', 7)))
        self.assertNotEqual(answer_text(make_page('solo', 7)), answer_text(make_page('solo', 8)))

    def test_answer_resolves_to_the_generated_pitches_and_fills_every_bar(self):
        for style in ('solo', 'lead'):
            for seed in range(1, 13):
                page = make_page(style, seed)
                r = R.resolve(R.parse_text(answer_text(page)), page.fifths)
                self.assertEqual((len(r.bars), r.unparsed, r.key), (32, [], page.fifths))
                for bar in page.bars:
                    got = r.bars[bar.number]
                    self.assertEqual(got.length(), F(4), (style, seed, bar.number))
                    self.assertEqual([n.midi for n in bar.notes if n.kind != 'rest'], [p.midi for e in got.events for p in e.pitches])

    def test_written_musicxml_reads_back_as_the_answer(self):
        for style, seed in (('solo', 1), ('lead', 3), ('solo', 5)):
            page = make_page(style, seed)
            back = read_back(page)
            ans = R.resolve(R.parse_text(answer_text(page)), page.fifths)
            got = R.resolve(R.parse_text(to_reading_text(back)), page.fifths)
            self.assertEqual(back['fifths'], page.fifths)
            for n, a in ans.bars.items():
                self.assertEqual(all_items(a), all_items(got.bars[n]), (style, seed, n))
                self.assertEqual([norm_chord(s) for _, s in a.chords], [norm_chord(s) for _, s in got.bars[n].chords])
            printed = [x for b in back['bars'] for e in b['events'] for x in e['printed']]
            self.assertEqual(printed, [p.acc for b in ans.bars.values() for e in b.events for p in e.pitches])
            self.assertEqual(score(ans, got, page.fifths)['note_errors'], 0)


class VerifyTest(unittest.TestCase):
    """material.verify must notice when the engraved score and the answer disagree."""

    def problems(self, page, change_xml=None, change_answer=None):
        xml, answer = write_musicxml(page), answer_text(page)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'page.musicxml'
            path.write_text(change_xml(xml) if change_xml else xml, encoding='utf-8')
            return verify(change_answer(answer) if change_answer else answer, str(path))

    def test_agreeing_score_has_no_problems(self):
        self.assertEqual(self.problems(make_page('solo', 1)), [])
        self.assertEqual(self.problems(make_page('lead', 3)), [])

    def test_changed_duration_in_the_score_is_found(self):
        for style, seed, old, new in (('solo', 1, '<duration>6</duration>', '<duration>12</duration>'),
                                      ('lead', 3, '<duration>12</duration>', '<duration>24</duration>')):
            found = self.problems(make_page(style, seed), change_xml=lambda x: x.replace(old, new, 1))
            self.assertTrue(found, (style, seed))

    def test_changed_note_value_in_the_score_is_found(self):
        found = self.problems(make_page('lead', 3), change_xml=lambda x: x.replace('<type>quarter</type>', '<type>half</type>', 1))
        self.assertTrue(found)

    def test_chord_symbol_on_another_beat_is_found(self):
        page = make_page('solo', 1)
        self.assertTrue(self.problems(page, change_answer=lambda a: a.replace(' 3=', ' 4=', 1)))


class ReaderTest(unittest.TestCase):
    def test_six_in_the_time_of_four_is_read_as_triplets(self):
        # Audiveris exports runs of triplet eighths as 6:4; the timing equals 3:2 and must not cost the bar.
        page = make_page('solo', 1)
        back = read_back(page)
        changed = 0
        for bar in back['bars']:
            for ev in bar['events']:
                if ev['tmod'] == (3, 2):
                    ev['tmod'] = (6, 4)
                    changed += 1
        self.assertGreater(changed, 0)
        got = R.parse_text(to_reading_text(back))
        self.assertEqual(got.unparsed, [])
        self.assertEqual(score(R.parse_text(answer_text(page)), got, page.fifths)['note_errors'], 0)

    def test_other_tuplets_are_still_outside_the_format(self):
        page = make_page('solo', 1)
        back = read_back(page)
        ev = next(e for b in back['bars'] for e in b['events'] if e['tmod'])
        ev['tmod'] = (5, 4)
        self.assertEqual(len(R.parse_text(to_reading_text(back)).unparsed), 1)

    def test_bar_outside_the_format_becomes_an_unread_bar(self):
        page = make_page('lead', 3)
        back = read_back(page)
        back['bars'][4]['events'][0]['type'] = '64th'
        got = R.parse_text(to_reading_text(back))
        self.assertEqual((len(got.bars), len(got.unparsed)), (31, 1))
        s = score(R.parse_text(answer_text(page)), got, page.fifths)
        self.assertEqual(s['missing_bars'], [5])


if __name__ == '__main__':
    unittest.main()
