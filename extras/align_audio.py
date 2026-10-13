"""Find where each beat of a reading sits in a recording (step 7 of docs/workflow.md).

    PYTHONPATH=src python3 extras/align_audio.py final.txt recording.mp3 map.json --tempo 190 [--octave -1]

Writes map.json with `beat_seconds`: the time in the recording of every quarter-note beat of the
score, counted from the first bar. extras/make_overlay.py and extras/make_video.py read it.

Needs numpy, scipy, librosa and soundfile, and ffmpeg on the path.

This comes from the one real transcription described in docs/workflow.md and from two solo
transcriptions before it: three jazz recordings in all. Take it as a starting point and change it for
your tune. What it assumes:
- 4/4, one tempo that drifts but does not jump, and a form that repeats every --chorus bars;
- the recording starts within --start-within seconds of the first bar of the reading;
- chord symbols in the reading (they give the harmony the notes alone do not).

The method: chroma features of the recording, a subsequence DTW against the written notes and chords
chorus by chorus, smoothing, a small nudge of every bar towards the written pitches, and a repair of
stretches that slipped by a beat or two. A long rest (` # multirest=N`) splits the score into parts.
The part after a rest has little to hold on to, so it is followed window by window instead; the beats
of the rest are spread evenly, and the number of bars that fit the gap is reported as a check on N.

Nothing here listens. The map is a calculation: check it by ear with the overlay before trusting it.
`pitch_agreement_by_shift_in_beats` in the output helps: the value for a shift of 0 should stand well
above the values for a shift of half a beat, one beat and four beats.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

from sheetcheck import reading as R

SR, HOP_COARSE, HOP = 22050, 2048, 256
FRAMES = 8  # score frames per beat
BAR = 4     # beats in a bar
PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def load(path: Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as work:
        wav = Path(work) / 'a.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), '-ac', '1', '-ar', str(SR), str(wav)], check=True)
        y, _ = sf.read(wav)
    return y


def chord_pcs(sym: str) -> list[int]:
    """Pitch classes of a chord symbol, roughly: enough for chroma, not a voicing."""
    s = sym.replace('♭', 'b').replace('♯', '#').replace('(', '').replace(')', '')
    m = re.match(r'^([A-G])(b|#)?(.*?)(?:/([A-G])(b|#)?)?$', s)
    alt = {'b': -1, '#': 1, None: 0}
    root = PC[m.group(1)] + alt[m.group(2)]
    q = m.group(3)
    if q.startswith('m7b5') or q.startswith('ø'):
        iv = [0, 3, 6, 10]
    elif q.startswith('maj') or q.startswith('M7'):
        iv = [0, 4, 7, 11]
    elif q.startswith('dim'):
        iv = [0, 3, 6, 9]
    elif q.startswith('m') or q.startswith('-'):
        iv = [0, 3, 7] + ([9] if '6' in q else [10] if re.search(r'7|9|11|13', q) else [])
    elif re.match(r'^(7|9|11|13)', q) or 'alt' in q:
        iv = [0, 4, 7, 10]
    elif q.startswith('6'):
        iv = [0, 4, 7, 9]
    else:
        iv = [0, 4, 7]
    if 'alt' in q:
        iv = [0, 4, 10, 1, 3, 8]
    for mark, add, drop in (('b5', 6, 7), ('#5', 8, 7), ('b9', 1, None), ('#9', 3, None), ('#11', 6, None), ('b13', 8, None)):
        if mark in q and not q.startswith('m7b5'):
            iv = [x for x in iv if x != drop] + [add]
    pcs = [(root + x) % 12 for x in iv]
    if m.group(4):
        pcs.append((PC[m.group(4)] + alt[m.group(5)]) % 12)
    return sorted(set(pcs))


def score_events(text: str, octave: int = 0, last_reading_bar: int | None = None) -> tuple[dict, list[dict]]:
    """Notes and chords on the beat axis of the score, and the long rests found on the way.

    `octave` moves the written pitches to where they sound (-1 for guitar notation).
    """
    reading = R.parse_text(text)
    if reading.key is None or (reading.time or '4/4') != '4/4':
        raise ValueError('the reading needs a `key:` line and 4/4 time')
    R.resolve(reading, reading.key)
    notes, chords, rests = [], [], []
    beat = 0.0
    open_chord = None
    for n in sorted(reading.bars):
        if last_reading_bar and n > last_reading_bar:
            break
        bar = reading.bars[n]
        multi = re.search(r'multirest=(\d+)', bar.comment)
        if multi:
            if open_chord:
                open_chord['d'] = beat - open_chord['at']
                open_chord = None
            rests.append({'from_beat': beat, 'bars': int(multi.group(1))})
            beat += BAR * int(multi.group(1))
            continue
        for b, sym in sorted(((float(b) - 1, s) for b, s in bar.chords)):
            if open_chord:
                open_chord['d'] = beat + b - open_chord['at']
            open_chord = {'at': beat + b, 'd': float(BAR), 'v': [48 + pc for pc in chord_pcs(sym)]}
            chords.append(open_chord)
        for e in bar.events:
            if e.kind != 'note':
                continue
            notes.append({'at': beat + float(e.onset), 'd': float(e.dur), 'm': sorted(p.midi + 12 * octave for p in e.pitches)})
        beat += BAR
    if open_chord:
        open_chord['d'] = beat - open_chord['at']
    return {'beats': beat, 'notes': notes, 'chords': [c for c in chords if c['d'] > 0]}, rests


def part(ev: dict, b0: float, b1: float) -> dict:
    cut = lambda items: [dict(x, at=x['at'] - b0, d=min(x['d'], b1 - x['at'])) for x in items if b0 <= x['at'] < b1]  # noqa: E731
    return {'beats': b1 - b0, 'notes': cut(ev['notes']), 'chords': cut(ev['chords'])}


def score_chroma(ev: dict) -> np.ndarray:
    n = int(round(ev['beats'] * FRAMES))
    sc = np.zeros((12, n))
    for c in ev['chords']:
        for m in c['v']:
            sc[m % 12, int(c['at'] * FRAMES):int((c['at'] + c['d']) * FRAMES)] += 1.0
    for x in ev['notes']:
        a = int(max(0.0, x['at']) * FRAMES)
        for m in x['m']:
            sc[m % 12, a:max(a + 1, int((x['at'] + x['d']) * FRAMES))] += 2.0
    return sc


def unit(m: np.ndarray) -> np.ndarray:
    return m / (np.linalg.norm(m, axis=0, keepdims=True) + 1e-9)


def dtw_map(sc: np.ndarray, ch: np.ndarray, fps: float, tempo: float, steps: np.ndarray):
    """Subsequence DTW of score frames (resampled to `tempo`) against chroma frames; beat -> time samples."""
    spb = 60 / tempo
    m = max(2, int(sc.shape[1] / FRAMES * spb * fps))
    idx = np.minimum((np.arange(m) / fps / spb * FRAMES).astype(int), sc.shape[1] - 1)
    cost = 1 - unit(sc[:, idx]).T @ unit(ch)
    D, wp = librosa.sequence.dtw(C=cost, subseq=True, step_sizes_sigma=steps,
                                 weights_add=np.zeros(len(steps)), weights_mul=np.ones(len(steps)))
    wp = wp[::-1]
    b = np.array([idx[i] / FRAMES for i, _ in wp])
    t = np.array([j / fps for _, j in wp])
    ub, first = np.unique(b, return_index=True)
    return ub, t[first], float(D[-1].min() / m)


def time_at(b, grid):
    k = np.clip(np.floor(b).astype(int), 0, len(grid) - 2)
    return grid[k] + (b - k) * (grid[k + 1] - grid[k])


def pitch_hits(grid, sel, fine, fps, shift=0.0, shortest=0.24):
    """Share of the notes whose lowest pitch class is among the three strongest of the recording while the note lasts."""
    hits = n = 0
    K = len(grid)
    for x in sel:
        b = x['at'] + shift
        if x['d'] < shortest or b < 0 or b >= K - 1:
            continue
        a = int(time_at(b, grid) * fps)
        e = max(a + 1, int(time_at(min(b + x['d'], K - 1.001), grid) * fps))
        if e >= fine.shape[1]:
            continue
        n += 1
        hits += (x['m'][0] % 12) in np.argsort(fine[:, a:e].mean(axis=1))[-3:]
    return hits / max(1, n), n


def fix_slips(grid, notes, fine, fps):
    """Move stretches of the grid that sit a beat or two off: two-bar windows whose pitches fit much better when shifted."""
    K = len(grid)
    centres, found = [], []
    for w in range(0, K // BAR - 1):
        sel = [x for x in notes if w * BAR <= x['at'] < (w + 2) * BAR]
        base, n = pitch_hits(grid, sel, fine, fps)
        best, gain = 0.0, 0.0
        for s in (-2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2):
            h, _ = pitch_hits(grid, sel, fine, fps, s)
            if h - base > gain:
                best, gain = s, h - base
        centres.append(w * BAR + BAR)
        found.append((best, gain, base + gain, n))
    strong = [b if n >= 8 and g >= 0.25 and top >= 0.65 else 0.0 for b, g, top, n in found]
    # A weaker window pointing the same way as a strong neighbour counts too, so a real slip
    # spanning two windows survives the median filter while a lone odd window does not.
    shifts = [s if s else next((found[i][0] for j in (i - 1, i + 1) if 0 <= j < len(strong) and strong[j]
                                and strong[j] == found[i][0] and found[i][1] >= 0.15 and found[i][3] >= 8), 0.0)
              for i, s in enumerate(strong)]
    if not shifts:
        return grid
    shifts = median_filter(np.array(shifts), size=3, mode='nearest')
    corr = np.interp(np.arange(K), centres, shifts)
    fixed = np.array([time_at(min(max(b + corr[b], 0), K - 1.001), grid) for b in range(K)])
    return np.maximum.accumulate(fixed)


def checks_of(grid, notes, fine, fps) -> dict:
    long_notes = [x for x in notes if x['d'] >= 0.45]
    return {str(s): round(pitch_hits(grid, long_notes, fine, fps, s, shortest=0.45)[0], 3) for s in (0, 0.5, 1, 4)}


def align_part(ev, feats, bpm, start_window, chorus=32, span=16, nudge=0.25):
    """Beat times of one part of the score. `start_window` (seconds) is where its first beat may lie."""
    coarse, fps_c, fine, fps, onset = feats
    sc = score_chroma(ev)
    wide = np.array([[1, 1], [1, 2], [2, 1]])
    tight = np.array([[1, 1], [2, 3], [3, 2]])
    first = sc[:, :min(sc.shape[1], chorus * BAR * FRAMES)]
    w0 = max(0, int(start_window[0] * fps_c))
    w1 = min(coarse.shape[1], int((start_window[1] + first.shape[1] / FRAMES * 60 / bpm * 1.6) * fps_c))
    ub, ut, _ = dtw_map(first, coarse[:, w0:w1], fps_c, bpm, wide)
    start = float(np.interp(0, ub, ut)) + w0 / fps_c
    beats_total = int(ev['beats'])
    samples_b, samples_t = [], []
    at = start
    edges = list(range(0, beats_total, chorus * BAR)) + [beats_total]
    if len(edges) > 2 and edges[-1] - edges[-2] < 8 * BAR:
        del edges[-2]
    for c0, c1 in zip(edges, edges[1:]):
        seg = sc[:, c0 * FRAMES:c1 * FRAMES]
        expect = (c1 - c0) * 60 / bpm
        f0 = max(0, int((at - 2.0) * fps_c))
        f1 = min(coarse.shape[1], int((at + expect * 1.5 + 2.0) * fps_c))
        try:
            ub, ut, _ = dtw_map(seg, coarse[:, f0:f1], fps_c, bpm, tight)
        except Exception as exc:
            # Not enough recording left for this stretch at any allowed tempo (the end of the track): carry on at the tempo so far.
            print(f'  beats {c0}-{c1}: no path in {f0 / fps_c:.1f}-{f1 / fps_c:.1f} s ({type(exc).__name__}); extended at {bpm:.1f} bpm', flush=True)
            ub, ut = np.array([0.0, float(c1 - c0)]), np.array([0.0, (c1 - c0) * 60 / bpm]) + at - f0 / fps_c
        ut = ut + f0 / fps_c
        print(f'  beats {c0}-{c1}: {ut[0]:.1f}-{ut[-1]:.1f} s', flush=True)
        samples_b.extend(ub + c0)
        samples_t.extend(ut)
        at = float(np.interp(c1 - c0, ub, ut, right=ut[-1]))
    order = np.argsort(samples_b)
    sb, st = np.array(samples_b)[order], np.maximum.accumulate(np.array(samples_t)[order])
    K = beats_total + 1
    raw = np.interp(np.arange(K, dtype=float), sb, st)
    smooth = np.empty(K)
    for k in range(K):
        lo, hi = max(0, k - span), min(K, k + span + 1)
        a, b = np.polyfit(np.arange(lo, hi), raw[lo:hi], 1)
        smooth[k] = a * k + b
    played = [x for x in ev['notes'] if x['at'] >= 0]

    def agreement(grid, sel, delta):
        total = 0.0
        for x in sel:
            t = time_at(x['at'], grid) + delta
            t2 = time_at(min(x['at'] + x['d'], len(grid) - 1.001), grid) + delta
            a, b = int(t * fps), max(int(t * fps) + 1, int(t2 * fps))
            if a < 0 or b >= fine.shape[1]:
                continue
            v = fine[:, a:b].mean(axis=1)
            total += v[x['m'][0] % 12] / (v.sum() + 1e-9) + 0.15 * onset[max(0, a - 1):a + 2].max() / onset.max()
        return total
    deltas = []
    for bar in range(K // BAR):
        sel = [x for x in played if bar * BAR - BAR <= x['at'] < bar * BAR + 2 * BAR]
        if len(sel) < 3:
            deltas.append(np.nan)
            continue
        limit = min(nudge, 0.35 * 60 / bpm)
        cands = np.arange(-limit, limit + 1e-9, 0.005)
        deltas.append(cands[int(np.argmax([agreement(smooth, sel, d) for d in cands]))])
    deltas = np.array(deltas)
    good = ~np.isnan(deltas)
    if good.any():
        deltas = median_filter(np.interp(np.arange(len(deltas)), np.flatnonzero(good), deltas[good]), size=3, mode='nearest')
        grid = smooth + np.interp(np.arange(K) / BAR, np.arange(len(deltas)) + 0.5, deltas)
    else:
        grid = smooth
    grid = np.maximum.accumulate(grid)
    grid = fix_slips(grid, played, fine, fps)
    return grid, checks_of(grid, played, fine, fps)


def track_part(ev, feats, t_guess, spb, first_range=5.0, bars_per_window=8):
    """Beat times of a part that follows a long rest, where chroma DTW has too little to hold on to.

    The part is followed window by window (8 bars). In each window that has notes, the start offset and the
    tempo that put the written pitch classes and onsets best on the recording are searched: widely for the
    first window (the tempo may have drifted during the rest), narrowly afterwards. Windows without notes
    run on at the tempo so far.
    """
    coarse, fps_c, fine, fps, onset = feats
    K = int(ev['beats']) + 1
    notes = sorted((x for x in ev['notes'] if x['d'] >= 0.2), key=lambda x: x['at'])
    omax = float(onset.max())

    def score(sel, t0, w0, step):
        total, n = 0.0, 0
        for x in sel:
            t = t0 + (x['at'] - w0) * step
            a = int(t * fps)
            b = max(a + 1, int((t + x['d'] * step) * fps))
            if a < 1 or b >= fine.shape[1]:
                continue
            v = fine[:, a:b].mean(axis=1)
            pc = x['m'][0] % 12
            total += float(pc in np.argsort(v)[-3:]) + 0.5 * v[pc] / (v.sum() + 1e-9) + 0.1 * onset[a - 1:a + 2].max() / omax
            n += 1
        return total / max(1, n)
    anchors, t_pred, step, log = [], t_guess, spb, []
    win = bars_per_window * BAR
    for w0 in range(0, K - 1, win):
        w1 = min(K - 1, w0 + win)
        sel = [x for x in notes if w0 <= x['at'] < w1]
        if len(sel) >= 6:
            first = not log
            rng = first_range if first else 0.5
            factors = (0.94, 0.96, 0.98, 1.0, 1.02, 1.04, 1.06) if first else (0.97, 0.985, 1.0, 1.015, 1.03)
            if w1 >= K - 1:
                factors += (0.75, 0.8, 0.85, 0.9)   # the ending slows down
            best = max(((score(sel, t_pred + d, w0, step * f), d, f) for f in factors for d in np.arange(-rng, rng + 1e-9, 0.01)), key=lambda r: r[0])
            sc, d, f = best
            other = max(score(sel, t_pred + d + k * step * f, w0, step * f) for k in (-4, -2, -1, 1, 2, 4))
            log.append({'beats': [w0, w1], 'notes': len(sel), 'offset_s': round(float(d), 2), 'tempo': round(60 / (step * f), 1),
                        'agreement': round(sc, 3), 'best_when_shifted_by_beats': round(other, 3)})
            t_pred += d
            step = float(np.clip(step * f, spb * 0.9, spb * 1.1)) if w1 < K - 1 else step * f
        anchors.append((w0, t_pred))
        t_pred += (w1 - w0) * step
    anchors.append((K - 1, t_pred))
    grid = np.maximum.accumulate(np.interp(np.arange(K, dtype=float), [a for a, _ in anchors], [t for _, t in anchors]))
    return grid, checks_of(grid, ev['notes'], fine, fps), log


def align(text: str, audio: Path, tempo: float, *, octave: int = 0, chorus: int = 32, start_within: float = 20.0,
          last_reading_bar: int | None = None, cache: Path | None = None) -> dict:
    """The audio map of a reading. `cache` keeps the features of the recording, which take the longest to compute."""
    ev, rests = score_events(text, octave, last_reading_bar)
    if cache and cache.exists():
        z = np.load(cache)
        coarse, fine, onset, tracked = z['coarse'], z['fine'], z['onset'], float(z['tracked'])
    else:
        y = load(audio)
        coarse = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP_COARSE)
        fine = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=HOP)
        onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
        tracked = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=SR, hop_length=512)[0])[0])
        if cache:
            np.savez(cache, coarse=coarse, fine=fine, onset=onset, tracked=tracked)
    fps = SR / HOP
    feats = (coarse, SR / HOP_COARSE, fine, fps, onset)
    # The beat tracker may lock on to half or double the tempo; take the reading of it nearest to the given tempo.
    bpm = min((tracked * f for f in (0.5, 1, 2)), key=lambda t: abs(np.log(t / tempo))) if tracked > 0 else tempo
    # Parts between the long rests. Rests that follow each other make one gap.
    cuts = []
    for r in rests:
        if cuts and cuts[-1][1] == r['from_beat']:
            cuts[-1][1] = r['from_beat'] + BAR * r['bars']
        else:
            cuts.append([r['from_beat'], r['from_beat'] + BAR * r['bars']])
    spans, b = [], 0.0
    for c0, c1 in cuts:
        spans.append((b, c0))
        b = c1
    spans.append((b, ev['beats']))
    grid = np.full(int(ev['beats']) + 1, np.nan)
    report, t_end, previous = [], 0.0, None
    for i, (b0, b1) in enumerate(spans):
        if b1 - b0 < BAR:
            continue
        this = part(ev, b0, b1)
        windows = None
        if previous is None:
            print(f'part {i}: beats {b0:.0f}-{b1:.0f}, chroma DTW', flush=True)
            g, checks = align_part(this, feats, bpm, (0.0, start_within), chorus=chorus)
            # A stretch with little to hold on to (sparse comping) can come out squeezed. Where a chorus runs more
            # than 8 % off the tempo of the others, that stretch and what follows are followed window by window instead.
            edges = list(range(0, len(g) - 1, chorus * BAR)) + [len(g) - 1]
            tempos = [60 * (c1 - c0) / (g[c1] - g[c0]) for c0, c1 in zip(edges, edges[1:])]
            med = float(np.median(tempos))
            odd = next((c0 for (c0, c1), t in zip(zip(edges, edges[1:]), tempos) if abs(t / med - 1) > 0.08), None)
            if odd:
                step = float(np.median(np.diff(g[max(0, odd - 2 * chorus * BAR):odd + 1])))
                print(f'  beats {odd}-{len(g) - 1} came out at an odd tempo; followed window by window from {g[odd]:.1f} s at {60 / step:.1f} bpm', flush=True)
                tail, _, windows = track_part(part(ev, b0 + odd, b1), feats, float(g[odd]), step, first_range=1.0)
                g = np.concatenate([g[:odd], tail])
                checks = checks_of(g, this['notes'], fine, fps)
        else:
            gap_beats = b0 - previous
            e = int(previous)
            step = float(np.median(np.diff(grid[max(0, e - 2 * chorus * BAR):e + 1])))
            guess = t_end + gap_beats * step
            print(f'part {i}: beats {b0:.0f}-{b1:.0f}, followed window by window from about {guess:.1f} s at {60 / step:.1f} bpm', flush=True)
            g, checks, windows = track_part(this, feats, guess, step, first_range=6.0)
        for w in windows or []:
            print('  ', w, flush=True)
        grid[int(b0):int(b1) + 1] = g
        gap = None
        if previous is not None:
            local = 60 / np.median(np.diff(g[:64]))
            gap = {'seconds': round(float(g[0] - t_end), 2), 'bars_written': (b0 - previous) / BAR,
                   'bars_that_fit_at_local_tempo': round(float((g[0] - t_end) / (60 * BAR / ((local + report[-1]['tempo_end']) / 2))), 2)}
        report.append({'beats': [b0, b1], 'start_s': round(float(g[0]), 2), 'end_s': round(float(g[-1]), 2), 'tempo_start': round(float(60 / np.median(np.diff(g[:64]))), 1),
                       'tempo_end': round(float(60 / np.median(np.diff(g[-64:]))), 1), 'pitch_agreement_by_shift_in_beats': checks, 'gap_before': gap, 'windows': windows})
        t_end, previous = float(g[-1]), b1
    known = ~np.isnan(grid)
    grid = np.interp(np.arange(len(grid)), np.flatnonzero(known), grid[known])
    return {'audio': audio.name, 'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(), 'tracked_tempo': round(tracked, 1), 'tempo_used': round(float(bpm), 1),
            'parts': report, 'beat_seconds': [round(float(t), 3) for t in grid],
            'method': 'chroma subsequence DTW per chorus, smoothed, bar nudges, slip repair; parts after a long rest followed window by window'}


def main(argv=None):
    ap = argparse.ArgumentParser(description='Find where each beat of a reading sits in a recording.')
    ap.add_argument('reading')
    ap.add_argument('audio', type=Path)
    ap.add_argument('out')
    ap.add_argument('--tempo', type=float, required=True, help='the tempo of the score, as a first guess')
    ap.add_argument('--octave', type=int, default=0, help='octaves from the written to the sounding pitch (-1 for guitar notation)')
    ap.add_argument('--chorus', type=int, default=32, help='bars of the form that repeats')
    ap.add_argument('--start-within', type=float, default=20.0, help='seconds of the recording in which the first bar begins')
    ap.add_argument('--bars', type=int, help='use only the first N bars of the reading (for a trial)')
    args = ap.parse_args(argv)
    out = align(Path(args.reading).read_text(encoding='utf-8'), args.audio, args.tempo, octave=args.octave, chorus=args.chorus,
                start_within=args.start_within, last_reading_bar=args.bars, cache=Path(args.out).with_suffix('.features.npz'))
    Path(args.out).write_text(json.dumps(out, indent=1) + '\n')
    print(json.dumps({k: v for k, v in out.items() if k != 'beat_seconds'}, indent=1))


if __name__ == '__main__':
    main()
