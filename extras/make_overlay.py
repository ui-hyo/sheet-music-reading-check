"""Mix a reading, played as a plain tone, onto the recording it was transcribed from (step 7 of docs/workflow.md).

    PYTHONPATH=src python3 extras/make_overlay.py final.txt recording.mp3 map.json overlay.mp3 [--octave -1] [--gain 0.45]

Every written note sounds at the time map.json (from extras/align_audio.py) gives its beat. Tied
notes are held, not struck again. The recording keeps its level; --gain sets the added tone.
A wrong note then sounds against the recording, and a note that is right doubles it.

Needs numpy and soundfile, and ffmpeg on the path. The output is written as its extension says
(.wav directly, anything else through ffmpeg). A starting point, like the rest of extras/: 4/4 only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from sheetcheck import reading as R

SR = 44100
BAR = 4  # beats in a bar


def sounding_notes(text: str, octave: int = 0, last_bar: int | None = None) -> list[tuple[float, float, int]]:
    """(start beat, length in beats, sounding MIDI pitch) with ties joined."""
    reading = R.parse_text(text)
    if reading.key is None or (reading.time or '4/4') != '4/4':
        raise ValueError('the reading needs a `key:` line and 4/4 time')
    R.resolve(reading, reading.key)
    out, held, beat = [], {}, 0.0   # held: pitch -> index in out
    for n in sorted(reading.bars):
        if last_bar and n > last_bar:
            break
        bar = reading.bars[n]
        multi = re.search(r'multirest=(\d+)', bar.comment)
        if multi:
            held, beat = {}, beat + BAR * int(multi.group(1))
            continue
        for e in bar.events:
            if e.kind == 'rest':
                held = {}
                continue
            at, dur = beat + float(e.onset), float(e.dur) if e.kind == 'note' else 0.12
            now = {}
            for p in e.pitches:
                m = p.midi + 12 * octave
                if m in held and e.kind == 'note':
                    s, d, _ = out[held[m]]
                    out[held[m]] = (s, at + dur - s, m)
                    idx = held[m]
                else:
                    out.append((at, dur, m))
                    idx = len(out) - 1
                if e.kind == 'note' and e.tie:
                    now[m] = idx
            if e.kind == 'note':
                held = now
        beat += BAR
    return out


def tone(midi: int, seconds: float) -> np.ndarray:
    n = int((seconds + 0.25) * SR)
    t = np.arange(n) / SR
    f = 440.0 * 2 ** ((midi - 69) / 12)
    wave = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.1)) if f * k < SR / 2)
    env = np.exp(-t * 2.2) * np.minimum(1.0, t / 0.004)
    release = np.clip((seconds + 0.25 - t) / 0.25, 0, 1)
    return (wave * env * release).astype(np.float32)


def render(notes: list[tuple[float, float, int]], grid: np.ndarray, samples: int) -> np.ndarray:
    """The notes as one mono track of `samples` samples, each at the time the grid gives its beat."""
    at = lambda b: float(np.interp(b, np.arange(len(grid)), grid))  # noqa: E731
    add = np.zeros(samples, dtype=np.float32)
    together = {}
    for b, d, m in notes:
        together[round(b, 3)] = together.get(round(b, 3), 0) + 1
    for b, d, m in notes:
        t0, t1 = at(b), at(min(b + d, len(grid) - 1))
        w = tone(m, max(0.08, t1 - t0)) / np.sqrt(together[round(b, 3)])   # a four-note chord is not four times as loud
        i = int(t0 * SR)
        if i < 0:               # the map puts this beat before the recording begins
            w, i = w[-i:], 0
        if i >= len(add):
            continue
        w = w[:len(add) - i]
        add[i:i + len(w)] += w
    return add * 0.22  # one note of the plain tone at about the level of a solo instrument in a small group


def main(argv=None):
    ap = argparse.ArgumentParser(description='Mix a reading, played as a plain tone, onto the recording.')
    ap.add_argument('reading')
    ap.add_argument('audio')
    ap.add_argument('map')
    ap.add_argument('out')
    ap.add_argument('--octave', type=int, default=0, help='octaves from the written to the sounding pitch (-1 for guitar notation)')
    ap.add_argument('--gain', type=float, default=0.45, help='level of the added tone; 0.45 sits about level with the recording')
    ap.add_argument('--bars', type=int, help='use only the first N bars of the reading')
    ap.add_argument('--only-tone', action='store_true', help='write the added tone alone, without the recording')
    args = ap.parse_args(argv)
    grid = np.array(json.loads(Path(args.map).read_text())['beat_seconds'])
    with tempfile.TemporaryDirectory() as work:
        wav = Path(work) / 'a.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', args.audio, '-ac', '2', '-ar', str(SR), str(wav)], check=True)
        rec, _ = sf.read(wav, dtype='float32')
        add = render(sounding_notes(Path(args.reading).read_text(encoding='utf-8'), args.octave, args.bars), grid, len(rec))
        mix = (0 if args.only_tone else rec) + (args.gain / 0.45) * add[:, None]
        peak = float(np.abs(mix).max())
        if peak > 0.98:
            mix = mix * (0.98 / peak)
        if args.out.endswith('.wav'):
            sf.write(args.out, mix, SR)
        else:
            out_wav = Path(work) / 'mix.wav'
            sf.write(out_wav, mix, SR)
            codec = ['-codec:a', 'libmp3lame', '-q:a', '3'] if args.out.endswith('.mp3') else []
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out_wav), *codec, args.out], check=True)
    print('wrote', args.out, f'peak before limiting {peak:.2f}')


if __name__ == '__main__':
    main()
