"""List the bars a person should check, from readings of the same page.

    python3 -m sheetcheck.compare opus.txt sol.txt [omr.txt ...]

A bar is listed when
- the readings disagree on its notes, ties, rests or chord symbols,
- a reader marked something in it as unsure (`?`),
- it does not add up to the time signature in one of the readings,
- it is missing from a reading, or its line cannot be parsed.

Readings are compared the way the scorer compares a reading with an answer, so
two spellings of the same pitch are not a difference. Agreement is not proof:
two readers can share an error, and a bar that every reading leaves out at the
end of the page cannot be listed. The list says where to look first.
"""
from __future__ import annotations

import argparse
import json
import re
import string
from fractions import Fraction as F

from . import reading as R
from .score import chord_items, note_items


def bar_length(time: str | None) -> F | None:
    """Quarter notes in one bar, or None when the time signature is not written as n/d."""
    m = re.match(r'^(\d+)\s*/\s*(\d+)$', (time or '').strip())
    return F(4 * int(m.group(1)), int(m.group(2))) if m and int(m.group(2)) else None


def bar_lines(text: str) -> dict[int, list[str]]:
    """The lines of a reading as written, by bar number."""
    out: dict[int, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip().strip('`')
        m = re.match(r'^m(\d+)\s*\|', line)
        if m:
            out.setdefault(int(m.group(1)), []).append(line)
    return out


def _num(x) -> str:
    return f'{float(x):.3g}'


def _shown(per_reading: dict) -> str:
    values = set(per_reading.values())
    return str(values.pop()) if len(values) == 1 else ', '.join(f'{l}: {v}' for l, v in per_reading.items())


def _differ(seqs: list) -> bool:
    return any(s != seqs[0] for s in seqs[1:])


def _each(labels: str, stated: dict, given, what: str, option: str, remarks: list[str]) -> dict:
    """The value to use for each reading: the one given by the caller, else the one it states, else None."""
    if given is not None:
        return dict.fromkeys(labels, given)
    if len(set(stated.values())) > 1:
        remarks.append(f"the readings do not agree on the {what} ({', '.join(f'{l}: {v}' for l, v in stated.items())}); "
                       f'each is taken with its own. Settle it first, then run again with {option}')
    return {l: stated.get(l) for l in labels}


def compare(readings: list[R.Reading], key: int | None = None, time: str | None = None, no_chords: str = '') -> dict:
    """Readings are named a, b, c ... in the order given.

    Without `key`, each reading is resolved with the key it states, and with no
    sharps or flats when it states none. A reading never borrows another one's
    key: that could make two different readings of a note look the same.

    Every reading takes part in the chord comparison unless its letter is in
    `no_chords`. Leaving one out is the caller's decision, never a guess: a
    reading that lost all its chord symbols must show up as a difference.
    """
    labels = string.ascii_lowercase[:len(readings)]
    remarks: list[str] = []
    for l, r in zip(labels, readings):
        if not r.bars and not r.unparsed:
            raise ValueError(f'no bar lines in reading {l} (a bar line starts with m<number> |)')
    if set(no_chords) - set(labels):
        raise ValueError(f"no reading named {', '.join(sorted(set(no_chords) - set(labels)))}")
    keys = _each(labels, {l: r.key for l, r in zip(labels, readings) if r.key is not None}, key, 'key', '--key', remarks)
    if None in keys.values():
        remarks.append(f"no key given in {', '.join(l for l in labels if keys[l] is None)}; taken as no sharps or flats")
        keys = {l: k or 0 for l, k in keys.items()}
    times = _each(labels, {l: r.time for l, r in zip(labels, readings) if r.time}, time, 'time signature', '--time', remarks)
    if len(set(filter(None, times.values()))) == 1:  # a reading without a time line is checked against the one the others give
        times = dict.fromkeys(labels, next(filter(None, times.values())))
    lengths = {l: bar_length(t) for l, t in times.items()}
    if None in lengths.values():
        remarks.append(f"no time signature of the form n/d for {', '.join(l for l in labels if lengths[l] is None)}; bar lengths were not checked there")
    with_chords = [l for l in labels if l not in no_chords]
    bare = [l for l, r in zip(labels, readings) if l in with_chords and not any(b.chords for b in r.bars.values())]
    if bare and len(bare) < len(with_chords):
        remarks.append(f"no chord symbols at all in {', '.join(bare)}; if that is expected, as in an OMR export, leave it out with --no-chords {','.join(bare)}")
    for l, r in zip(labels, readings):
        R.resolve(r, keys[l])
    unusable = [{int(re.match(r'm(\d+)', line).group(1)) for line in r.unparsed} for r in readings]
    numbers = sorted(set().union(*(r.bars for r in readings), *unusable))
    check = []
    for n in range(numbers[0], numbers[-1] + 1):
        if n not in numbers:
            check.append({'bar': n, 'reasons': ['in no reading']})
            continue
        reasons = []
        for l, r, bad in zip(labels, readings, unusable):
            if n in bad:
                reasons.append(f'{l} gives this bar more than once' if n in r.bars else f'the line in {l} cannot be parsed')
            elif n not in r.bars:
                reasons.append(f'missing from {l}')
        have = [(l, r.bars[n]) for l, r in zip(labels, readings) if n in r.bars]
        notes = [note_items(b) for _, b in have]
        if _differ(notes):
            shared = set(notes[0]).intersection(*notes[1:])
            beats = sorted({item[0] + 1 for items in notes for item in items if item not in shared})
            reasons.append('notes differ' + (' at beat ' + ', '.join(map(_num, beats)) if beats else ''))
        else:
            if _differ([[(e.onset, e.tie) for e in b.events if e.kind != 'rest'] for _, b in have]):
                reasons.append('ties differ')
            if _differ([[(e.onset, e.dur) for e in b.events if e.kind == 'rest'] for _, b in have]):
                reasons.append('rests differ')
        if _differ([chord_items(b) for l, b in have if l in with_chords]):
            reasons.append('chord symbols differ')
        off: dict[tuple[F, F], list[str]] = {}
        for l, b in have:
            if lengths[l] is not None and b.length() != lengths[l]:
                off.setdefault((b.length(), lengths[l]), []).append(l)
        reasons += [f"{_num(got)} quarter notes in {', '.join(ls)}, not {_num(want)}" for (got, want), ls in off.items()]
        unsure = [l for l, b in have if any(e.unc for e in b.events)]
        if unsure:
            reasons.append('marked unsure by ' + ', '.join(unsure))
        if reasons:
            check.append({'bar': n, 'reasons': reasons})
    return {'keys': keys, 'times': times, 'remarks': remarks, 'bars': len(numbers), 'first': numbers[0], 'last': numbers[-1], 'check': check}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('readings', nargs='+', help='two or more readings of the same page; one alone is checked for bar lengths and unsure marks')
    ap.add_argument('--key', type=int, help='key signature to resolve every reading with (default: each reading with the key it states)')
    ap.add_argument('--time', help='time signature to check bar lengths against, such as 4/4 (default: the one the readings give)')
    ap.add_argument('--no-chords', default='', metavar='LETTERS',
                    help='readings to leave out of the chord comparison, by letter in the order given (c, or b,c), for an OMR export without chord symbols')
    ap.add_argument('--json', action='store_true', help='print one JSON object')
    args = ap.parse_args(argv)
    if len(args.readings) > len(string.ascii_lowercase):
        ap.error('too many readings')
    texts = []
    for path in args.readings:
        with open(path, encoding='utf-8') as fh:
            texts.append(fh.read())
    names = dict(zip(string.ascii_lowercase, args.readings))
    try:
        result = compare([R.parse_text(t) for t in texts], args.key, args.time, args.no_chords.replace(',', '').replace(' ', ''))
    except ValueError as exc:
        ap.error(f"{exc}; readings: {', '.join(f'{l} = {path}' for l, path in names.items())}")
    lines = dict(zip(names, map(bar_lines, texts)))
    for item in result['check']:
        item['lines'] = {l: lines[l][item['bar']] for l in names if item['bar'] in lines[l]}
    if args.json:
        print(json.dumps({'readings': names, **result}))
        return
    for l, path in names.items():
        print(f'{l}  {path}')
    print(f"key {_shown(result['keys'])}, time {_shown(result['times'])}, {result['bars']} bars (m{result['first']} to m{result['last']})")
    for remark in result['remarks']:
        print('note: ' + remark)
    bars = [item['bar'] for item in result['check']]
    print(f"\n{len(bars)} bar{'' if len(bars) == 1 else 's'} to check" + (': ' + ', '.join(map(str, bars)) if bars else ''))
    for item in result['check']:
        print(f"\nm{item['bar']}: {'; '.join(item['reasons'])}")
        for l, written in item['lines'].items():
            for line in written:
                print(f'  {l}  {line}')


if __name__ == '__main__':
    main()
