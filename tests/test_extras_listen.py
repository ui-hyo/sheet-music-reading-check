"""The listening tools of extras/, tried on a recording that is made here: the notes of a generated page
played as plain tones along a beat grid whose tempo drifts, with the chord tones underneath and a little
noise. The grid is known, so what align_audio finds can be measured. No real recording is in the repository.

These tests need numpy, scipy, librosa and soundfile, and ffmpeg; without them they are skipped.
"""
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'extras'))
NEEDED = ('numpy', 'scipy', 'librosa', 'soundfile')
READY = all(importlib.util.find_spec(m) for m in NEEDED) and bool(shutil.which('ffmpeg'))
PAGE = (ROOT / 'material' / 'solo-1' / 'answer.txt').read_text()


def with_long_rest(text: str, after: int, bars: int) -> str:
    """The page with a rest of `bars` bars put in after bar `after`."""
    head = [ln for ln in text.splitlines() if not ln.startswith('m')]
    body = [ln for ln in text.splitlines() if ln.startswith('m')]
    later = [re.sub(r'^m(\d+)', lambda m: f'm{int(m.group(1)) + 1}', ln) for ln in body[after:]]
    return '\n'.join(head + body[:after] + [f'm{after + 1} | chords: | events: R:w # multirest={bars}'] + later) + '\n'


def recording(text: str, folder: pathlib.Path, swing: float, period: int):
    """Write the made-up recording of a reading and return its path and the time of every beat in it."""
    import numpy as np
    import soundfile as sf
    import align_audio as A
    import make_overlay as O
    ev, _ = A.score_events(text)
    beat = np.arange(int(ev['beats']) + 1)
    bpm = 126 * (1 + swing * np.sin(2 * np.pi * beat / period))
    truth = 1.5 + np.concatenate([[0], np.cumsum(60 / bpm[:-1])])
    n = int((truth[-1] + 3) * O.SR)
    band = np.zeros(n, dtype=np.float32)
    for c in ev['chords']:
        t0, t1 = np.interp([c['at'], c['at'] + c['d']], beat, truth)
        for m in c['v']:
            w = 0.25 * O.tone(m, t1 - t0)
            i = int(t0 * O.SR)
            w = w[:n - i]
            band[i:i + len(w)] += w
    y = O.render(O.sounding_notes(text), truth, n) + 0.22 * band + 0.002 * np.random.default_rng(1).standard_normal(n).astype(np.float32)
    path = folder / 'recording.wav'
    sf.write(path, y, O.SR)
    return path, truth


@unittest.skipUnless(READY, f'needs {", ".join(NEEDED)} and ffmpeg')
class Listen(unittest.TestCase):
    def test_beats_of_a_drifting_tempo_are_found(self):
        import numpy as np
        import align_audio as A
        with tempfile.TemporaryDirectory() as work:
            wav, truth = recording(PAGE, pathlib.Path(work), swing=0.05, period=64)
            out = A.align(PAGE, wav, tempo=120.0)
        err = np.abs(np.array(out['beat_seconds']) - truth)
        self.assertEqual(len(err), 129)                       # 32 bars of four beats, and the end of the last one
        self.assertLess(np.median(err), 0.06)
        self.assertLess(err.max(), 0.25)                      # a beat lasts about 0.48 s here
        hits = out['parts'][0]['pitch_agreement_by_shift_in_beats']
        self.assertGreater(hits['0'], hits['1'] + 0.2)        # the check the script prints: right place against one beat off

    def test_part_after_a_long_rest_is_found_and_the_rest_is_measured(self):
        import numpy as np
        import align_audio as A
        text = with_long_rest(PAGE, after=16, bars=8)
        with tempfile.TemporaryDirectory() as work:
            wav, truth = recording(text, pathlib.Path(work), swing=0.04, period=80)
            out = A.align(text, wav, tempo=120.0, chorus=16)
        err = np.abs(np.array(out['beat_seconds']) - truth)
        played = np.r_[0:64, 96:161]
        self.assertLess(np.median(err[played]), 0.1)
        self.assertLess(err[played].max(), 0.45)              # still less than a beat
        gap = out['parts'][1]['gap_before']
        self.assertEqual(gap['bars_written'], 8.0)
        self.assertAlmostEqual(gap['bars_that_fit_at_local_tempo'], 8.0, delta=0.3)

    def test_overlay_strikes_each_note_at_its_beat_and_holds_tied_notes(self):
        import numpy as np
        import make_overlay as O
        text = 'key: 0\ntime: 4/4\nm1 | chords: | events: R:h A4:q~ A4:q\nm2 | chords: | events: [C4+E4]:h R:h\n'
        self.assertEqual(O.sounding_notes(text), [(2.0, 2.0, 69), (4.0, 2.0, 60), (4.0, 2.0, 64)])
        self.assertEqual(O.sounding_notes(text, octave=-1)[0], (2.0, 2.0, 57))
        grid = np.arange(9) * 0.5 + 1.0                       # beat 0 at 1.0 s, two beats a second
        track = O.render(O.sounding_notes(text), grid, 6 * O.SR)
        loud = np.flatnonzero(np.abs(track) > 0.01)
        self.assertAlmostEqual(loud[0] / O.SR, 2.0, delta=0.01)   # the first note is at beat 2
        self.assertEqual(float(np.abs(track[:int(1.99 * O.SR)]).max()), 0.0)

    def test_overlay_command_keeps_the_length_of_the_recording(self):
        import soundfile as sf
        import align_audio as A
        import make_overlay as O
        with tempfile.TemporaryDirectory() as work:
            work = pathlib.Path(work)
            wav, truth = recording(PAGE, work, swing=0.0, period=64)
            (work / 'page.txt').write_text(PAGE)
            (work / 'map.json').write_text(json.dumps({'beat_seconds': [float(t) for t in truth]}))
            O.main([str(work / 'page.txt'), str(wav), str(work / 'map.json'), str(work / 'overlay.wav')])
            self.assertEqual(sf.info(work / 'overlay.wav').frames, sf.info(wav).frames)
            self.assertEqual(A.SR, 22050)

    @unittest.skipUnless(shutil.which('mscore4') and importlib.util.find_spec('PIL'), 'needs MuseScore 4 and pillow')
    def test_video_of_the_score_following_the_sound(self):
        import build_musicxml as B
        import make_video as V
        with tempfile.TemporaryDirectory() as work:
            work = pathlib.Path(work)
            wav, truth = recording(PAGE, work, swing=0.0, period=64)
            (work / 'map.json').write_text(json.dumps({'beat_seconds': [float(t) for t in truth]}))
            pages = work / 'pages'
            pages.mkdir()
            (work / 'tune.musicxml').write_text(B.build(PAGE, tempo=126, layout='video')[0], encoding='utf-8')
            subprocess.run(['mscore4', '-o', str(pages / 'score.mscz'), str(work / 'tune.musicxml')], check=True, capture_output=True, timeout=180)
            for ext in ('png', 'mpos', 'spos'):
                subprocess.run(['mscore4', '-r', '152.4', '-o', str(pages / f'score.{ext}'), str(pages / 'score.mscz')], check=True, capture_output=True, timeout=180)
            bars, _ = V.positions(pages / 'score.mpos')
            self.assertEqual(len(bars), 32)
            V.main([str(pages), str(work / 'map.json'), str(wav), str(work / 'follow.mp4'), '--tempo', '126', '--seconds', '3'])
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height', '-of', 'json', str(work / 'follow.mp4')],
                                   capture_output=True, text=True, check=True)
            streams = json.loads(probe.stdout)['streams']
            self.assertEqual(sorted(s['codec_type'] for s in streams), ['audio', 'video'])
            self.assertEqual([(s['width'], s['height']) for s in streams if s['codec_type'] == 'video'], [(1920, 1080)])


if __name__ == '__main__':
    unittest.main()
