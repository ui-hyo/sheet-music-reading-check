"""Parse the one-line-per-bar reading format and resolve it to absolute events.

The format is described in FORMAT.md. A reading records what is printed: an
accidental is written only where a sign is printed on that notehead. `resolve`
turns that into sounding pitches by applying the key signature, accidentals
carried within the bar, and ties across barlines.
"""
from __future__ import annotations

import dataclasses
import re
from fractions import Fraction as F

STEP_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
SHARP_ORDER = 'FCGDAEB'
FLAT_ORDER = 'BEADGCF'
ACC = {'': None, '#': 1, 'b': -1, 'n': 0, '##': 2, 'x': 2, 'bb': -2}
DUR = {'w': F(4), 'h': F(2), 'q': F(1), '8': F(1, 2), '16': F(1, 4), '32': F(1, 8)}
# n notes in the time of TUPLET_NORMAL[n]
TUPLET_NORMAL = {3: 2, 5: 4, 6: 4, 7: 4}

PITCH_RE = re.compile(r'^([A-G])(##|bb|#|b|n|x)?(-?\d)$')
BAR_RE = re.compile(r'^m(\d+)\s*\|\s*chords:(.*?)\|\s*events:(.*)$')


class ReadingError(ValueError):
    pass


@dataclasses.dataclass
class Pitch:
    step: str
    octave: int
    acc: int | None  # printed accidental, None when no sign is printed
    alter: int | None = None  # filled by resolve()

    @property
    def midi(self) -> int:
        return 12 * (self.octave + 1) + STEP_PC[self.step] + self.alter


@dataclasses.dataclass
class Event:
    kind: str  # 'note' | 'rest' | 'grace'
    dur: F  # quarter notes; 0 for a grace note
    pitches: list[Pitch]
    tie: bool = False
    unc: bool = False
    onset: F | None = None  # filled by parse_bar()


@dataclasses.dataclass
class Bar:
    number: int
    chords: list[tuple[str, str]]  # (beat text, symbol as written)
    events: list[Event]
    comment: str = ''

    def length(self) -> F:
        return sum((e.dur for e in self.events), F(0))


@dataclasses.dataclass
class Reading:
    key: int | None
    time: str | None
    bars: dict[int, Bar]
    unparsed: list[str]


def key_alters(fifths: int) -> dict[str, int]:
    alters = dict.fromkeys(STEP_PC, 0)
    for s in SHARP_ORDER[:max(fifths, 0)]:
        alters[s] = 1
    for s in FLAT_ORDER[:max(-fifths, 0)]:
        alters[s] = -1
    return alters


def parse_pitch(tok: str) -> Pitch:
    m = PITCH_RE.match(tok)
    if not m:
        raise ReadingError(f'bad pitch {tok!r}')
    return Pitch(m.group(1), int(m.group(3)), ACC[m.group(2) or ''])


def parse_dur(tok: str) -> F:
    dots = len(tok) - len(tok.rstrip('.'))
    base = tok.rstrip('.')
    if base not in DUR or dots > 2:
        raise ReadingError(f'bad duration {tok!r}')
    d = DUR[base]
    return d * (F(2) - F(1, 2 ** dots))


def _tokens(text: str) -> list[str]:
    return re.findall(r'\{\d*|\}\??|[^\s{}]+', text)


def parse_events(text: str) -> list[Event]:
    events: list[Event] = []
    scale = F(1)
    group_start = None
    pending_grace: list[Event] = []
    for tok in _tokens(text):
        if tok.startswith('{'):
            if group_start is not None:
                raise ReadingError('nested tuplet')
            if tok == '{':
                raise ReadingError('tuplet without a number')
            n = int(tok[1:])
            if n not in TUPLET_NORMAL:
                raise ReadingError(f'unsupported tuplet {n}')
            scale = F(TUPLET_NORMAL[n], n)
            group_start = len(events)
            continue
        if tok.startswith('}'):
            if group_start is None:
                raise ReadingError('unmatched }')
            if tok.endswith('?'):
                for e in events[group_start:]:
                    e.unc = True
            scale, group_start = F(1), None
            continue
        tok, marks = re.match(r'^(.*?)([~?]*)$', tok).groups()
        unc, tie = '?' in marks, '~' in marks
        m = re.match(r'^g\((.+)\)$', tok)
        if m:
            pending_grace.append(Event('grace', F(0), [parse_pitch(m.group(1))], unc=unc))
            continue
        head, sep, dur = tok.rpartition(':')
        if not sep:
            raise ReadingError(f'bad event {tok!r}')
        d = parse_dur(dur) * scale
        if head == 'R':
            if tie:
                raise ReadingError('tie on a rest')
            ev = Event('rest', d, [], unc=unc)
        elif head.startswith('[') and head.endswith(']'):
            ev = Event('note', d, [parse_pitch(p) for p in head[1:-1].split('+')], tie, unc)
        else:
            ev = Event('note', d, [parse_pitch(head)], tie, unc)
        events.extend(pending_grace)
        pending_grace = []
        events.append(ev)
    if group_start is not None:
        raise ReadingError('unclosed tuplet')
    if pending_grace:
        raise ReadingError('grace note without a main note')
    onset = F(0)
    for e in events:
        e.onset = onset
        onset += e.dur
    return events


def parse_chords(text: str) -> list[tuple[str, str]]:
    out = []
    for tok in text.split():
        beat, sep, sym = tok.partition('=')
        if not sep or not sym:
            raise ReadingError(f'bad chord {tok!r}')
        out.append((beat, sym))
    return out


def parse_bar(line: str) -> Bar | None:
    """Return a Bar, or None when the line is not a bar line at all."""
    # A comment starts at a free-standing '#'; sharps are always attached to a letter.
    body, *rest = re.split(r'\s#(?:\s|$)', line, maxsplit=1)
    m = BAR_RE.match(body.strip())
    if not m:
        return None
    return Bar(int(m.group(1)), parse_chords(m.group(2)), parse_events(m.group(3)), rest[0].strip() if rest else '')


def parse_text(text: str) -> Reading:
    key = time = None
    bars: dict[int, Bar] = {}
    unparsed: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip('`')
        if not line:
            continue
        low = line.lower()
        if low.startswith('key:'):
            m = re.search(r'-?\d+', line)
            key = int(m.group()) if m else None
            continue
        if low.startswith('time:'):
            time = line.split(':', 1)[1].strip()
            continue
        if not re.match(r'^m\d+\s*\|', line):
            continue  # prose around the reading is ignored, not counted
        try:
            bar = parse_bar(line)
        except ReadingError:
            bar = None
        if bar is None or bar.number in bars:
            unparsed.append(line)
        else:
            bars[bar.number] = bar
    return Reading(key, time, bars, unparsed)


def parse_file(path: str) -> Reading:
    with open(path, encoding='utf-8') as fh:
        return parse_text(fh.read())


def resolve(reading: Reading, fifths: int) -> Reading:
    """Fill Pitch.alter for every pitch, in bar order.

    Rules: a printed accidental sets the alteration for that step and octave
    until the end of the bar. A note that continues a tie from the previous bar
    keeps the tied pitch without setting that state. Otherwise the key
    signature applies.
    """
    key = key_alters(fifths)
    tied_in: dict[tuple[str, int], int] = {}
    prev = None
    for n in sorted(reading.bars):
        if prev is not None and n != prev + 1:
            tied_in = {}
        prev = n
        carried: dict[tuple[str, int], int] = {}
        bar = reading.bars[n]
        first_sounding = next((e for e in bar.events if e.kind == 'note' and e.onset == 0), None)
        for ev in bar.events:
            for p in ev.pitches:
                k = (p.step, p.octave)
                if p.acc is not None:
                    p.alter = p.acc
                    carried[k] = p.acc
                elif ev is first_sounding and k in tied_in and k not in carried:
                    p.alter = tied_in[k]
                else:
                    p.alter = carried.get(k, key[p.step])
        last = bar.events[-1] if bar.events else None
        tied_in = {(p.step, p.octave): p.alter for p in last.pitches} if last is not None and last.kind == 'note' and last.tie else {}
    return reading
