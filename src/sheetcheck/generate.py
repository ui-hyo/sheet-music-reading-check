"""Seeded generator for test pages: one melodic line in 4/4 with chord symbols.

The music is made by rules and a random seed, so it is in no training set, has
no copyright owner, and anyone can make a fresh page with a new seed. It aims
to look like a jazz lead line (scale runs, approach notes, triplets, ties,
rests), not to sound good.
"""
from __future__ import annotations

import dataclasses
import random
from fractions import Fraction as F

from .reading import key_alters

LETTERS = 'CDEFGAB'
NAT_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
ACC_TEXT = {-2: 'bb', -1: 'b', 0: 'n', 1: '#', 2: '##'}
MODES = {
    'maj7': [0, 2, 4, 5, 7, 9, 11], '6': [0, 2, 4, 5, 7, 9, 11], 'm7': [0, 2, 3, 5, 7, 9, 10],
    '7': [0, 2, 4, 5, 7, 9, 10], 'm7b5': [0, 1, 3, 5, 6, 8, 10], '7b9': [0, 1, 4, 5, 7, 8, 10],
}
CHORD_TEXT = {'maj7': 'maj7', '6': '6', 'm7': 'm7', '7': '7', 'm7b5': 'm7(b5)', '7b9': '7(b9)'}
MAJOR, MINOR = MODES['maj7'], [0, 2, 3, 5, 7, 8, 10]
MAJOR_TONICS = [('C', 0), ('F', 0), ('B', -1), ('E', -1), ('A', -1), ('D', -1), ('G', 0), ('D', 0), ('A', 0)]
MINOR_TONICS = [('C', 0), ('G', 0), ('D', 0), ('A', 0), ('E', 0), ('F', 0), ('B', 0)]
KEY_TONIC = {0: ('C', 0), 1: ('G', 0), 2: ('D', 0), 3: ('A', 0), -1: ('F', 0), -2: ('B', -1), -3: ('E', -1), -4: ('A', -1)}
# Four-bar units as (scale degree, quality) per chord, one or two chords per bar.
MAJOR_UNITS = [
    [[(1, 'm7')], [(4, '7')], [(0, 'maj7')], [(0, '6')]],
    [[(1, 'm7'), (4, '7')], [(0, 'maj7')], [(5, 'm7')], [(1, 'm7'), (4, '7')]],
    [[(0, 'maj7')], [(5, 'm7')], [(1, 'm7')], [(4, '7')]],
    [[(0, 'maj7'), (5, '7b9')], [(1, 'm7')], [(4, '7')], [(0, '6')]],
]
MINOR_UNITS = [
    [[(1, 'm7b5')], [(4, '7b9')], [(0, 'm7')], [(0, 'm7')]],
    [[(1, 'm7b5'), (4, '7b9')], [(0, 'm7')], [(3, 'm7')], [(4, '7b9')]],
    [[(0, 'm7')], [(1, 'm7b5'), (4, '7b9')], [(0, 'm7')], [(5, 'maj7')]],
]
# Half-bar rhythm cells. 'r' = rest, 't' = member of a triplet.
SOLO_CELLS = [
    (6, ['8', '8', '8', '8']), (3, ['q', '8', '8']), (3, ['8', '8', 'q']), (2, ['q', 'q']), (2, ['q.', '8']),
    (2, ['8', 'q', '8']), (3, ['r8', '8', '8', '8']), (2, ['rq', '8', '8']), (1, ['rq', 'q']), (1.5, ['r8', '8', 'q']),
    (2, ['t8', 't8', 't8', 'q']), (2, ['q', 't8', 't8', 't8']), (2, ['t8', 't8', 't8', '8', '8']), (1, ['tq', 'tq', 'tq']),
    (1, ['16', '16', '16', '16', 'q']), (1, ['8', '16', '16', '8', '8']), (1, ['h']), (0.7, ['rh']),
]
LEAD_CELLS = [
    (5, ['q', 'q']), (4, ['h']), (3, ['q.', '8']), (3, ['q', '8', '8']), (2, ['8', '8', 'q']), (2, ['rq', 'q']),
    (1, ['8', 'q', '8']), (0.7, ['tq', 'tq', 'tq']), (1, ['rh']), (1, ['8', '8', '8', '8']), (1, ['r8', '8', 'q']),
]
TOKEN = {  # token -> (written type, dots, length in quarters, is triplet member)
    '16': ('16', 0, F(1, 4), False), '8': ('8', 0, F(1, 2), False), 'q': ('q', 0, F(1), False), 'q.': ('q', 1, F(3, 2), False),
    'h': ('h', 0, F(2), False), 'h.': ('h', 1, F(3), False), 'w': ('w', 0, F(4), False),
    't8': ('8', 0, F(1, 3), True), 'tq': ('q', 0, F(2, 3), True),
}
STYLES = {
    'solo': dict(cells=SOLO_CELLS, lo=60, hi=88, p_chrom=0.22, p_tie=0.12, p_grace=0.04, p_leap=0.15, keyed=False),
    'lead': dict(cells=LEAD_CELLS, lo=60, hi=81, p_chrom=0.06, p_tie=0.10, p_grace=0.0, p_leap=0.20, keyed=True),
}


@dataclasses.dataclass
class Note:
    kind: str  # 'note' | 'rest' | 'grace'
    type: str  # written value: w h q 8 16
    dots: int
    dur: F  # sounding length in quarters, 0 for a grace note
    triplet: bool = False
    step: str = ''
    alter: int = 0
    octave: int = 0
    tie: bool = False  # a tie starts on this note
    printed: int | None = None  # accidental shown on the page, None for no sign

    @property
    def midi(self) -> int:
        return 12 * (self.octave + 1) + NAT_PC[self.step] + self.alter


@dataclasses.dataclass
class Chord:
    step: str
    alter: int
    quality: str

    @property
    def symbol(self) -> str:
        return self.step + {0: '', 1: '#', -1: 'b'}[self.alter] + CHORD_TEXT[self.quality]


@dataclasses.dataclass
class Bar:
    number: int
    chords: list[tuple[int, Chord]]  # (beat 1 or 3, chord)
    notes: list[Note]


@dataclasses.dataclass
class Page:
    title: str
    style: str
    seed: int
    fifths: int
    bars: list[Bar]


def spelled_scale(step: str, alter: int, intervals: list[int]):
    """Seven (letter, alter) pairs, or None when a double accidental would be needed."""
    root_pc, i0, out = NAT_PC[step] + alter, LETTERS.index(step), []
    for i, iv in enumerate(intervals):
        letter = LETTERS[(i0 + i) % 7]
        a = (root_pc + iv - NAT_PC[letter] + 6) % 12 - 6
        if abs(a) > 1:
            return None
        out.append((letter, a))
    return out


def pool(chord: Chord, lo: int, hi: int) -> list[tuple[int, str, int, int, bool]]:
    """Scale notes in range as (midi, step, alter, octave, is chord tone), low to high."""
    out = []
    for octave in range(2, 8):
        for degree, (step, alter) in enumerate(spelled_scale(chord.step, chord.alter, MODES[chord.quality])):
            midi = 12 * (octave + 1) + NAT_PC[step] + alter
            if lo <= midi <= hi:
                out.append((midi, step, alter, octave, degree in (0, 2, 4, 6)))
    return sorted(out)


def progression(rng: random.Random, bars: int, fifths: int | None) -> list[list[Chord]]:
    out: list[list[Chord]] = []
    while len(out) < bars:
        if fifths is None:
            minor = rng.random() < 0.4
            tonic = rng.choice(MINOR_TONICS if minor else MAJOR_TONICS)
        else:  # stay near the key: tonic, relative minor, subdominant, dominant
            home = spelled_scale(*KEY_TONIC[fifths], MAJOR)
            degree, minor = rng.choices([(0, False), (5, True), (3, False), (4, False)], [5, 3, 1, 1])[0]
            tonic = home[degree]
        scale = spelled_scale(*tonic, MINOR if minor else MAJOR)
        if scale is None:
            continue
        unit = [[Chord(*scale[d], q) for d, q in bar] for bar in rng.choice(MINOR_UNITS if minor else MAJOR_UNITS)]
        if any(spelled_scale(c.step, c.alter, MODES[c.quality]) is None for bar in unit for c in bar):
            continue
        out.extend(unit)
    return out[:bars]


def _approach(target: tuple, below: bool) -> tuple[str, int, int]:
    """Spell the semitone below or above a target note on the neighbouring letter."""
    midi, step, _, octave, _ = target
    i = LETTERS.index(step) + (-1 if below else 1)
    letter, octave = LETTERS[i % 7], octave + i // 7
    alter = midi + (-1 if below else 1) - (12 * (octave + 1) + NAT_PC[letter])
    return letter, alter, octave


class _Line:
    """Melodic state carried along the whole page."""

    def __init__(self, rng: random.Random, cfg: dict):
        self.rng, self.cfg = rng, cfg
        self.cur, self.dir, self.pending, self.prev = 72, 1, None, None

    def pitch(self, notes_pool: list, can_approach: bool) -> tuple[str, int, int]:
        rng, cfg = self.rng, self.cfg
        if self.pending is not None:
            midi, step, alter, octave, _ = self.pending
            self.pending, self.cur = None, midi
            return step, alter, octave
        near = min(range(len(notes_pool)), key=lambda i: abs(notes_pool[i][0] - self.cur))
        if can_approach and rng.random() < cfg['p_chrom']:
            tones = [n for n in notes_pool if n[4] and abs(n[0] - self.cur) <= 5]
            if tones:
                target = rng.choice(tones)
                step, alter, octave = _approach(target, below=rng.random() < 0.6)
                if abs(alter) <= 1 and cfg['lo'] <= target[0] - 1 and target[0] + 1 <= cfg['hi']:
                    self.pending = target
                    return step, alter, octave
        if rng.random() < 0.3:
            self.dir = -self.dir
        jump = rng.randint(3, 5) if rng.random() < cfg['p_leap'] else rng.choice([1, 1, 1, 2])
        i = near + self.dir * jump
        if not 0 <= i < len(notes_pool):
            self.dir = -self.dir
            i = max(0, min(len(notes_pool) - 1, near + self.dir * jump))
        if notes_pool[i][0] == self.cur and len(notes_pool) > 1:
            i = i + 1 if i + 1 < len(notes_pool) else i - 1
        midi, step, alter, octave, _ = notes_pool[i]
        self.cur = midi
        return step, alter, octave


def _bar(line: _Line, number: int, chords: list[Chord], last: bool) -> list[Note]:
    rng, cfg = line.rng, line.cfg
    if last:
        halves = [(chords[0], ['w'])]
    else:
        cells = [rng.choices([c for _, c in cfg['cells']], [w for w, _ in cfg['cells']])[0] for _ in range(2)]
        if cells == [['rh'], ['rh']]:
            cells[1] = ['h']
        halves = [(chords[i] if len(chords) == 2 else chords[0], cells[i]) for i in range(2)]
    notes: list[Note] = []
    for chord, cell in halves:
        notes_pool = pool(chord, cfg['lo'], cfg['hi'])
        for j, tok in enumerate(cell):
            typ, dots, dur, triplet = TOKEN[tok.lstrip('r')]
            if tok.startswith('r'):
                notes.append(Note('rest', typ, dots, dur, triplet))
                line.prev, line.pending = None, None
                continue
            follows = j + 1 < len(cell) and not cell[j + 1].startswith('r')
            tied = not last and line.prev is not None and line.pending is None and rng.random() < cfg['p_tie']
            if last:  # end on the root of the last chord
                root = min((n for n in notes_pool if (n[1], n[2]) == (chord.step, chord.alter)), key=lambda n: abs(n[0] - line.cur))
                step, alter, octave = root[1], root[2], root[3]
            elif tied:
                line.prev.tie = True
                step, alter, octave = line.prev.step, line.prev.alter, line.prev.octave
            else:
                want_grace = j == 0 and line.pending is None and rng.random() < cfg['p_grace']
                step, alter, octave = line.pitch(notes_pool, follows)
                at = next((i for i, n in enumerate(notes_pool) if n[1:4] == (step, alter, octave)), None)
                if want_grace and at is not None and at + 1 < len(notes_pool):
                    g = notes_pool[at + 1]  # grace note from the scale step above
                    notes.append(Note('grace', '8', 0, F(0), False, g[1], g[2], g[3]))
            note = Note('note', typ, dots, dur, triplet, step, alter, octave)
            notes.append(note)
            line.prev = note
    return notes


def set_printed(page: Page) -> None:
    """Decide which accidentals appear on the page (standard engraving rules)."""
    key = key_alters(page.fifths)
    tied_in = None
    for bar in page.bars:
        carried: dict[tuple[str, int], int] = {}
        first = next((n for n in bar.notes if n.kind != 'grace'), None)
        for n in bar.notes:
            if n.kind == 'rest':
                continue
            k = (n.step, n.octave)
            if n is first and tied_in is not None:
                n.printed = None  # continuation of a tie from the previous bar
                continue
            if n.alter != carried.get(k, key[n.step]):
                n.printed = n.alter
                carried[k] = n.alter
            else:
                n.printed = None
        tied_in = bar.notes[-1] if bar.notes[-1].tie else None


def _tie_trap(prev: list[Note] | None, cur: list[Note], fifths: int) -> bool:
    """True when a tie crosses into this bar on an altered pitch that the bar then reuses.

    Engravers and notation programs differ on whether the later note needs its
    sign repeated, so the generator avoids the case.
    """
    if not prev or not prev[-1].tie:
        return False
    t = prev[-1]
    if t.alter == key_alters(fifths)[t.step]:
        return False
    return any(n.kind != 'rest' and (n.step, n.octave) == (t.step, t.octave) for n in cur[1:])


def make_page(style: str, seed: int, bars: int = 32, title: str | None = None) -> Page:
    cfg = STYLES[style]
    rng = random.Random(f'{style}:{seed}')
    fifths = rng.choice([-4, -3, -2, -1, 1, 2, 3]) if cfg['keyed'] else 0
    chords = progression(rng, bars, fifths if cfg['keyed'] else None)
    line = _Line(rng, cfg)
    out: list[Bar] = []
    for i, bar_chords in enumerate(chords):
        if i == bars - 1:
            bar_chords = bar_chords[:1]  # the last bar is one long note
        for _ in range(200):
            saved = (line.cur, line.dir, line.pending, line.prev, line.prev.tie if line.prev else None)
            notes = _bar(line, i + 1, bar_chords, last=i == bars - 1)
            if not _tie_trap(out[-1].notes if out else None, notes, fifths) and sum((n.dur for n in notes), F(0)) == 4:
                break
            line.cur, line.dir, line.pending, line.prev = saved[:4]
            if line.prev is not None:
                line.prev.tie = saved[4]
        else:
            raise RuntimeError(f'could not generate bar {i + 1}')
        beats = [1, 3] if len(bar_chords) == 2 else [1]
        out.append(Bar(i + 1, list(zip(beats, bar_chords)), notes))
    page = Page(title or f'Reading test ({style}, seed {seed})', style, seed, fifths, out)
    set_printed(page)
    return page


def _dur_token(n: Note) -> str:
    return n.type + '.' * n.dots


def _pitch_token(n: Note) -> str:
    return n.step + ('' if n.printed is None else ACC_TEXT[n.printed]) + str(n.octave)


def answer_text(page: Page) -> str:
    """The page in the reading format, with accidentals exactly where they are printed."""
    lines = [f'key: {page.fifths}', 'time: 4/4']
    for bar in page.bars:
        toks, group = [], False
        for n in bar.notes:
            if n.kind == 'grace':
                toks.append(f'g({_pitch_token(n)})')
                continue
            if n.triplet and not group:
                toks.append('{3')
                group, filled = True, F(0)
            tok = ('R' if n.kind == 'rest' else _pitch_token(n)) + ':' + _dur_token(n) + ('~' if n.tie else '')
            if group:
                filled += n.dur
                closed = filled in (F(1), F(2))
                toks.append(tok + ('}' if closed else ''))
                group = not closed
            else:
                toks.append(tok)
        chords = ' '.join(f'{beat}={c.symbol}' for beat, c in bar.chords)
        lines.append(f'm{bar.number} | chords: {chords} | events: {" ".join(toks)}')
    return '\n'.join(lines) + '\n'
