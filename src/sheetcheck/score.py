"""Score a reading against the answer for the same page.

Counting rules:
- A "note" is a sounding event: a note, a chord, or a grace note. Its identity
  is (onset in the bar, pitches, duration). Rests are not notes, but a misread
  rest shifts the onsets after it, so it still costs.
- Note errors are the edit distance between the answer's notes and the
  reading's notes, bar by bar. A substituted note costs 1, a dropped note 1, an
  added note 1. The denominator is the number of notes in the answer.
- A bar that is missing from the reading, or whose line cannot be parsed, costs
  every note it contains. A bar the reading adds costs every note it contains.
- Both sides are resolved with the answer's key signature. Whether the reader
  named the key correctly is reported separately.
- A chord symbol is right when both its beat and its name match.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys

from . import reading as R


def note_items(bar: R.Bar) -> list[tuple]:
    return [(e.onset, tuple(sorted(p.midi for p in e.pitches)), e.dur) for e in bar.events if e.kind != 'rest']


def all_items(bar: R.Bar) -> list[tuple]:
    return [(e.onset, e.kind, tuple(sorted(p.midi for p in e.pitches)), e.dur, e.tie) for e in bar.events]


def rhythm_items(bar: R.Bar) -> list[tuple]:
    return [(e.onset, e.kind, e.dur) for e in bar.events]


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def norm_chord(sym: str) -> str:
    s = sym.strip().replace('♭', 'b').replace('♯', '#').replace('(', '').replace(')', '').replace(' ', '')
    s = s.replace('△', 'maj').replace('Δ', 'maj').replace('ø7', 'm7b5').replace('ø', 'm7b5').replace('°', 'dim')
    m = re.match(r'^([A-G][b#]?)(.*?)(?:/([A-G][b#]?))?$', s)
    if not m:
        return s
    root, q, bass = m.group(1), m.group(2), m.group(3)
    q = re.sub(r'^(Maj|MAJ|maj|Ma|MA|ma|M)(?=\d|$)', 'maj', q)
    q = re.sub(r'^(min|MIN|mi|-)', 'm', q)
    q = re.sub(r'^o(?=7|$)', 'dim', q)
    if q == 'maj':
        q = ''
    return root + q + ('/' + bass if bass else '')


def chord_syms(bar: R.Bar) -> list[str]:
    return [norm_chord(s) for _, s in bar.chords]


def chord_items(bar: R.Bar) -> list[tuple]:
    """(beat, normalised symbol); a beat that is not a number can never match."""
    out = []
    for beat, sym in bar.chords:
        try:
            out.append((float(beat), norm_chord(sym)))
        except ValueError:
            out.append((beat, norm_chord(sym)))
    return out


def _matched(a: list, b: list) -> int:
    return sum(blk.size for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())


def score(answer: R.Reading, got: R.Reading, fifths: int) -> dict:
    R.resolve(answer, fifths)
    R.resolve(got, fifths)
    s = dict.fromkeys(['bars_exact', 'bars_notes_exact', 'bars_rhythm_exact', 'bars_chords_exact', 'notes_total', 'note_errors',
                       'ties_total', 'ties_found', 'chords_total', 'chords_matched', 'chord_names_matched', 'uncertain_events'], 0)
    wrong, flagged, missing = [], [], []
    a_pitch, g_pitch = [], []
    for n in sorted(answer.bars):
        a = answer.bars[n]
        an = note_items(a)
        s['notes_total'] += len(an)
        a_pitch += [p for _, ps, _ in an for p in ps]
        a_ties = {e.onset for e in a.events if e.tie}
        s['ties_total'] += len(a_ties)
        s['chords_total'] += len(a.chords)
        g = got.bars.get(n)
        if g is None:
            missing.append(n)
            wrong.append(n)
            s['note_errors'] += len(an)
            continue
        gn = note_items(g)
        g_pitch += [p for _, ps, _ in gn for p in ps]
        s['note_errors'] += edit_distance(an, gn)
        s['bars_exact'] += all_items(a) == all_items(g)
        s['bars_notes_exact'] += an == gn
        s['bars_rhythm_exact'] += rhythm_items(a) == rhythm_items(g)
        s['bars_chords_exact'] += chord_items(a) == chord_items(g)
        s['ties_found'] += len(a_ties & {e.onset for e in g.events if e.tie})
        s['chords_matched'] += _matched(chord_items(a), chord_items(g))  # right symbol on the right beat
        s['chord_names_matched'] += _matched(chord_syms(a), chord_syms(g))  # right symbol, any beat
        unc = sum(e.unc for e in g.events)
        s['uncertain_events'] += unc
        if an != gn:
            wrong.append(n)
        if unc:
            flagged.append(n)
    extra = sorted(set(got.bars) - set(answer.bars))
    s['note_errors'] += sum(len(note_items(got.bars[n])) for n in extra)
    s.update(
        bars_total=len(answer.bars),
        pitches_total=len(a_pitch),
        pitches_matched=_matched(a_pitch, g_pitch),
        errors_per_100_notes=round(100 * s['note_errors'] / s['notes_total'], 2) if s['notes_total'] else None,
        key_given=got.key,
        key_ok=None if got.key is None else got.key == fifths,
        missing_bars=missing,
        extra_bars=extra,
        unparsed_lines=len(got.unparsed),
        wrong_bars=wrong,
        flagged_bars=flagged,
        wrong_and_flagged=len(set(wrong) & set(flagged)),
    )
    return s


def summary_line(name: str, s: dict) -> str:
    return (f"{name:<28} notes {s['notes_total'] - s['note_errors']:>3}/{s['notes_total']} right, {s['note_errors']:>3} errors"
            f" ({s['errors_per_100_notes']}/100) | bars {s['bars_notes_exact']:>2}/{s['bars_total']} | chords {s['chords_matched']}/{s['chords_total']}"
            f" | ties {s['ties_found']}/{s['ties_total']} | flagged {len(s['flagged_bars'])} bars, {s['wrong_and_flagged']} of {len(s['wrong_bars'])} wrong bars flagged"
            f" | missing {len(s['missing_bars'])} unparsed {s['unparsed_lines']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('answer')
    ap.add_argument('readings', nargs='+')
    ap.add_argument('--json', action='store_true', help='print one JSON object per reading')
    args = ap.parse_args(argv)
    key = R.parse_file(args.answer).key
    if key is None:
        sys.exit('answer file has no key: line')
    for path in args.readings:
        s = score(R.parse_file(args.answer), R.parse_file(path), key)
        if args.json:
            print(json.dumps({'reading': path, **s}, default=str))
        else:
            print(summary_line(path.rsplit('/', 1)[-1], s))


if __name__ == '__main__':
    main()
