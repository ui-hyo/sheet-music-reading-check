import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

from sheetcheck import reading as R
from sheetcheck.generate import answer_text, make_page
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


class ReaderTest(unittest.TestCase):
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
