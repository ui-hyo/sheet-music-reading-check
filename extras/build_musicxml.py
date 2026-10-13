"""Write MusicXML from a reading, for MuseScore to open (step 6 of docs/workflow.md).

    PYTHONPATH=src python3 extras/build_musicxml.py final.txt tune.musicxml --title 'A tune' --tempo 120

This is the builder of the one real transcription described in docs/workflow.md, with the parts that
belonged to that tune taken out. Take it as a starting point and change it for your tune.

What it writes: one part on one staff in treble clef, with notes, rests, chords, grace notes, triplets,
ties and chord symbols. A tie is written note by note: of a tied chord, only the pitches that are there
again in the next event are tied. Accidentals are left to MuseScore, which prints what the key and the
bar call for. A chord symbol is moved to the nearest half beat.

Two notes a reading may carry after ` # ` are used as well:
  # multirest=8        the bar is a rest of 8 bars; it becomes 8 real bars, so later bar numbers shift
  # section=Head       a boxed label above the bar
--map writes which bar of the score each bar of the reading became.

Not here: slurs and other markings, a tablature staff, more than one voice, time signature changes.
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from fractions import Fraction as F
from pathlib import Path

from sheetcheck import reading as R

DIV = 24  # divisions per quarter: eighth triplets 8, sixteenths 6, sixteenth triplets 4, thirty-seconds 3
TYPE = {'w': 'whole', 'h': 'half', 'q': 'quarter', '8': 'eighth', '16': '16th', '32': '32nd'}
DOCTYPE = '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">'

# printed quality -> (MusicXML kind, text shown after the root)
QUALITY = [
    (r'mmaj7', 'major-minor', 'm(maj7)'), (r'maj7|M7|Δ7?', 'major-seventh', 'maj7'), (r'maj9', 'major-ninth', 'maj9'),
    (r'm7b5|ø7?', 'half-diminished', 'm7b5'), (r'm13', 'minor-13th', 'm13'), (r'm11', 'minor-11th', 'm11'), (r'm9', 'minor-ninth', 'm9'),
    (r'm7|min7|-7', 'minor-seventh', 'm7'), (r'm6|min6|-6', 'minor-sixth', 'm6'), (r'm|min|-', 'minor', 'm'),
    (r'dim7|o7|°7', 'diminished-seventh', 'dim7'), (r'dim|o|°', 'diminished', 'dim'), (r'aug|\+', 'augmented', 'aug'),
    (r'13', 'dominant-13th', '13'), (r'11', 'dominant-11th', '11'), (r'9', 'dominant-ninth', '9'), (r'7', 'dominant', '7'),
    (r'69|6/9', 'major-sixth', '69'), (r'6', 'major-sixth', '6'), (r'', 'major', ''),
]
ALT = {'b': -1, '#': 1, '': 0}
# Page set-ups: 'a4' leaves the layout to MuseScore; 'video' gives 16:9 pages with larger notes for extras/make_video.py.
LAYOUTS = {'a4': None, 'video': {'mm': 9.2, 'page_w_mm': 320.0, 'page_h_mm': 180.0, 'margin_mm': 9.0}}


def sub(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, tag, {k.replace('_', '-'): str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = str(text)
    return e


def parse_symbol(sym: str) -> dict:
    s = sym.replace('♭', 'b').replace('♯', '#').replace('(', '').replace(')', '').replace('mMaj7', 'mmaj7')
    m = re.match(r'^([A-G])(b|#)?(.*?)(?:/([A-G])(b|#)?)?$', s)
    if not m:
        raise ValueError(f'chord symbol {sym!r}')
    root, ralt, rest, bass, balt = m.groups()
    for pattern, kind, text in QUALITY:
        q = re.match(rf'^(?:{pattern})(?=$|[b#]\d|alt|sus|add)', rest)
        if q:
            tail = rest[q.end():]
            break
    else:
        raise ValueError(f'chord quality in {sym!r}')
    degrees = [(9, 0, 'add')] if text == '69' else []   # MuseScore knows the 6/9 chord as a sixth chord with an added ninth
    while tail:
        d = re.match(r'^(b|#)(5|9|11|13)', tail)
        if d:
            degrees.append((int(d.group(2)), ALT[d.group(1)], 'alter' if d.group(2) == '5' else 'add'))
            text += d.group(0)
            tail = tail[d.end():]
            continue
        w = re.match(r'^(alt|sus4|sus2|sus|add9)', tail)
        if not w:
            raise ValueError(f'chord tail {tail!r} in {sym!r}')
        # MuseScore keeps a name it does not know only when the kind is "other" (with "dominant" it shows a plain 7).
        kind, degrees = 'other', []
        text += w.group(0)
        tail = tail[w.end():]
    return {'root': (root, ALT[ralt or '']), 'kind': kind, 'text': text, 'degrees': degrees, 'bass': (bass, ALT[balt or '']) if bass else None}


def harmony(parent, sym: str, offset_div: int):
    h = parse_symbol(sym)
    he = sub(parent, 'harmony', print_frame='no')
    r = sub(he, 'root')
    sub(r, 'root-step', h['root'][0])
    if h['root'][1]:
        sub(r, 'root-alter', h['root'][1])
    ke = sub(he, 'kind', h['kind'])
    if h['text']:
        ke.set('text', h['text'])  # an empty text on a major triad makes MuseScore drop the kind
    if h['bass']:
        b = sub(he, 'bass')
        sub(b, 'bass-step', h['bass'][0])
        if h['bass'][1]:
            sub(b, 'bass-alter', h['bass'][1])
    for v, a, t in h['degrees']:
        d = sub(he, 'degree')
        sub(d, 'degree-value', v)
        sub(d, 'degree-alter', a)
        sub(d, 'degree-type', t)
    if offset_div:
        sub(he, 'offset', offset_div)


def structure(events_text: str) -> list[dict]:
    """The events of a bar with what MusicXML needs and reading.parse_events drops: note value, dots, tuplet grouping."""
    out, group, pending = [], None, 0
    for tok in R._tokens(events_text):
        if tok.startswith('{'):
            n = int(tok[1:])
            group = {'ratio': (n, R.TUPLET_NORMAL[n]), 'first': True}
            continue
        if tok.startswith('}'):
            out[-1]['tuplet_stop'] = True
            group = None
            continue
        tok = re.match(r'^(.*?)([~?]*)$', tok).group(1)
        if re.match(r'^g\((.+)\)$', tok):
            pending += 1
            continue
        dur = tok.rpartition(':')[2]
        out.append({'base': dur.rstrip('.'), 'dots': len(dur) - len(dur.rstrip('.')), 'tuplet': group['ratio'] if group else None,
                    'tuplet_start': bool(group and group['first']), 'tuplet_stop': False, 'graces': pending})
        if group:
            group['first'] = False
        pending = 0
    return out


def note_el(m, ev: R.Event, st: dict | None, p: R.Pitch | None, *, chord=False, grace=False, tie_stop=False, tie_start=False):
    n = sub(m, 'note')
    if grace:
        sub(n, 'grace')
    if chord:
        sub(n, 'chord')
    if p is None:
        sub(n, 'rest')
    else:
        pe = sub(n, 'pitch')
        sub(pe, 'step', p.step)
        if p.alter:
            sub(pe, 'alter', p.alter)
        sub(pe, 'octave', p.octave)
    if not grace:
        sub(n, 'duration', int(ev.dur * DIV))
        if tie_stop:
            sub(n, 'tie', type='stop')
        if tie_start:
            sub(n, 'tie', type='start')
    sub(n, 'voice', 1)
    sub(n, 'type', 'eighth' if grace else TYPE[st['base']])
    if grace:
        return
    for _ in range(st['dots']):
        sub(n, 'dot')
    if st['tuplet']:
        tm = sub(n, 'time-modification')
        sub(tm, 'actual-notes', st['tuplet'][0])
        sub(tm, 'normal-notes', st['tuplet'][1])
    nots = [('tied', {'type': 'stop'})] * tie_stop + [('tied', {'type': 'start'})] * tie_start
    if st['tuplet_start'] and not chord:
        nots.append(('tuplet', {'type': 'start', 'bracket': 'yes'}))
    if st['tuplet_stop'] and not chord:
        nots.append(('tuplet', {'type': 'stop'}))
    if nots:
        ne = sub(n, 'notations')
        for tag, at in nots:
            sub(ne, tag, **at)


def rest_bar(m, quarters: F):
    rn = sub(m, 'note')
    sub(rn, 'rest', measure='yes')
    sub(rn, 'duration', int(quarters * DIV))
    sub(rn, 'voice', 1)


def notes_of(comment: str) -> dict:
    """What a line carries after ` # `: multirest=<bars>, section=<label>. A label may hold spaces."""
    out = {}
    m = re.search(r'multirest=(\d+)', comment)
    if m:
        out['multirest'] = m.group(1)
    m = re.search(r'section=(.+?)(?=\s+#|\s+\w+=|$)', comment)
    if m:
        out['section'] = m.group(1).strip().replace(' | ', ' / ')
    return out


def page_setup(root, name: str):
    lay = LAYOUTS[name]
    if not lay:
        return
    tenths = lambda mm: round(mm / lay['mm'] * 40, 2)  # noqa: E731
    dfl = sub(root, 'defaults')
    sc = sub(dfl, 'scaling')
    sub(sc, 'millimeters', lay['mm'])
    sub(sc, 'tenths', 40)
    pg = sub(dfl, 'page-layout')
    sub(pg, 'page-height', tenths(lay['page_h_mm']))
    sub(pg, 'page-width', tenths(lay['page_w_mm']))
    pm = sub(pg, 'page-margins', type='both')
    for side in ('left-margin', 'right-margin', 'top-margin', 'bottom-margin'):
        sub(pm, side, tenths(lay['margin_mm']))


def build(text: str, *, title: str = '', composer: str = '', subtitle: str = '', tempo: int | None = None, part_name: str = '',
          octave_down: bool = False, midi_program: int | None = None, layout: str = 'a4') -> tuple[str, list[dict]]:
    """MusicXML for a reading, and for each bar of the reading the bars of the score it became.

    `octave_down` declares that the part sounds an octave below what is written, as guitar notation does.
    """
    reading = R.parse_text(text)
    if reading.unparsed:
        raise ValueError(f'lines that do not parse: {reading.unparsed[:3]}')
    if reading.key is None:
        raise ValueError('the reading has no `key:` line')
    beats, beat_type = (int(x) for x in (reading.time or '4/4').split('/'))
    bar_len = F(beats * 4, beat_type)
    R.resolve(reading, reading.key)
    nums = sorted(reading.bars)
    if nums != list(range(nums[0], nums[0] + len(nums))):
        raise ValueError('the bar numbers of the reading have a gap')
    raw = {int(m.group(1)): m.group(3) for m in (R.BAR_RE.match(re.split(r'\s#(?:\s|$)', line.strip().strip('`'), maxsplit=1)[0].strip())
                                                   for line in text.splitlines()) if m}
    root = ET.Element('score-partwise', version='4.0')
    if title:
        sub(sub(root, 'work'), 'work-title', title)
        sub(root, 'movement-title', title)
    ident = sub(root, 'identification')
    if composer:
        sub(ident, 'creator', composer, type='composer')
    if subtitle:
        sub(ident, 'creator', subtitle, type='lyricist')   # MuseScore shows this line at the left under the title
    sub(sub(ident, 'encoding'), 'software', 'sheet-music-reading-check extras/build_musicxml.py')
    page_setup(root, layout)
    sp = sub(sub(root, 'part-list'), 'score-part', id='P1')
    name = sub(sp, 'part-name', part_name or 'Melody')
    if not part_name:
        name.set('print-object', 'no')
    if midi_program:
        sub(sub(sp, 'score-instrument', id='P1-I1'), 'instrument-name', part_name or 'Melody')
        mi = sub(sp, 'midi-instrument', id='P1-I1')
        sub(mi, 'midi-channel', 1)
        sub(mi, 'midi-program', midi_program)
    part = sub(root, 'part', id='P1')
    # A `~` ties an event to the next one, note by note: only a pitch that is there again is tied.
    flat = [e for n in nums for e in (reading.bars[n].events if 'multirest' not in reading.bars[n].comment else [None])]
    carries = {}
    for e, nxt in zip(flat, flat[1:] + [None]):
        if e is not None and e.kind == 'note' and e.tie and nxt is not None and nxt.kind == 'note':
            carries[id(e)] = {p.midi for p in e.pitches} & {p.midi for p in nxt.pitches}
    real, mapping, tie_open = 0, [], set()
    for n in nums:
        bar = reading.bars[n]
        info = notes_of(bar.comment)
        rest_bars = int(info.get('multirest', 0))
        mapping.append({'reading_bar': n, 'first_real_bar': real + 1, 'real_bars': max(1, rest_bars)})
        if not rest_bars and bar.length() != bar_len:
            raise ValueError(f'm{n} adds up to {bar.length()} quarter notes, not {bar_len}')
        for k in range(max(1, rest_bars)):
            real += 1
            m = sub(part, 'measure', number=real)
            if real == 1:
                a = sub(m, 'attributes')
                sub(a, 'divisions', DIV)
                sub(sub(a, 'key'), 'fifths', reading.key)
                t = sub(a, 'time')
                sub(t, 'beats', beats)
                sub(t, 'beat-type', beat_type)
                c = sub(a, 'clef')
                sub(c, 'sign', 'G')
                sub(c, 'line', 2)
                if octave_down:
                    tr = sub(a, 'transpose')
                    sub(tr, 'diatonic', 0)
                    sub(tr, 'chromatic', 0)
                    sub(tr, 'octave-change', -1)
                if rest_bars:
                    sub(sub(a, 'measure-style'), 'multiple-rest', rest_bars)
                if tempo:
                    d = sub(m, 'direction', placement='above')
                    met = sub(sub(d, 'direction-type'), 'metronome')
                    sub(met, 'beat-unit', 'quarter')
                    sub(met, 'per-minute', tempo)
                    sub(d, 'sound', tempo=tempo)
            elif rest_bars and k == 0:
                sub(sub(sub(m, 'attributes'), 'measure-style'), 'multiple-rest', rest_bars)
            if 'section' in info and k == 0:
                d = sub(m, 'direction', placement='above')
                sub(sub(d, 'direction-type'), 'rehearsal', info['section'])
            if rest_bars:
                rest_bar(m, bar_len)
        if rest_bars:
            tie_open = set()
            continue
        chords = sorted(((F(round(float(beat) * 2), 2) - 1, sym) for beat, sym in bar.chords), key=lambda c: c[0])  # to the nearest half beat
        events = list(bar.events)
        whole_rest = len(events) == 1 and events[0].kind == 'rest' and events[0].dur == bar_len
        i = 0
        for st in structure(raw[n]):
            graces, i = events[i:i + st['graces']], i + st['graces']
            ev = events[i]
            i += 1
            while chords and chords[0][0] < ev.onset + ev.dur:
                at, sym = chords.pop(0)
                harmony(m, sym, int((at - ev.onset) * DIV))
            for g in graces:
                note_el(m, g, None, g.pitches[0], grace=True)
            if ev.kind == 'rest':
                if whole_rest:
                    rest_bar(m, bar_len)
                else:
                    note_el(m, ev, st, None)
                tie_open = set()
            else:
                for j, p in enumerate(sorted(ev.pitches, key=lambda p: p.midi)):
                    note_el(m, ev, st, p, chord=j > 0, tie_stop=p.midi in tie_open, tie_start=p.midi in carries.get(id(ev), ()))
                tie_open = set(carries.get(id(ev), ()))
        if i != len(events) or chords:
            raise ValueError(f'm{n}: left over {events[i:]} {chords}')
        if n == nums[-1]:
            sub(sub(m, 'barline', location='right'), 'bar-style', 'light-heavy')
    ET.indent(root, space='  ')
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{DOCTYPE}\n' + ET.tostring(root, encoding='unicode') + '\n', mapping


def main(argv=None):
    ap = argparse.ArgumentParser(description='Write MusicXML from a reading.')
    ap.add_argument('reading')
    ap.add_argument('out')
    ap.add_argument('--title', default='')
    ap.add_argument('--composer', default='')
    ap.add_argument('--subtitle', default='', help='a line at the left under the title')
    ap.add_argument('--tempo', type=int, help='quarter notes per minute, printed and played')
    ap.add_argument('--part-name', default='', help='printed at the first system; without it the staff has no name')
    ap.add_argument('--octave-down', action='store_true', help='the part sounds an octave below what is written (guitar notation)')
    ap.add_argument('--midi-program', type=int, help='General MIDI program for playback, 1 to 128 (27 is a jazz guitar)')
    ap.add_argument('--layout', choices=sorted(LAYOUTS), default='a4')
    ap.add_argument('--map', help='write here which bars of the score each bar of the reading became')
    args = ap.parse_args(argv)
    xml, mapping = build(Path(args.reading).read_text(encoding='utf-8'), title=args.title, composer=args.composer, subtitle=args.subtitle,
                         tempo=args.tempo, part_name=args.part_name, octave_down=args.octave_down, midi_program=args.midi_program, layout=args.layout)
    Path(args.out).write_text(xml, encoding='utf-8')
    real = mapping[-1]['first_real_bar'] + mapping[-1]['real_bars'] - 1
    if args.map:
        Path(args.map).write_text(json.dumps({'real_bars': real, 'bars': mapping}, indent=1) + '\n')
    print('wrote', args.out, len(mapping), 'bars in the reading,', real, 'bars in the score')


if __name__ == '__main__':
    main()
