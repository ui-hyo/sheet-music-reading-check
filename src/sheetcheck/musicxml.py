"""Write a generated page as MusicXML, and read MusicXML back into the reading format.

The reader is written independently of the writer and of `reading.resolve`: it
takes pitches from <alter>, never from accidental rules. That lets it check the
generated pages after a round trip through MuseScore, and score the output of
an OMR program.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from fractions import Fraction as F

from .generate import ACC_TEXT, Page

DIV = 12
TYPE_NAME = {'w': 'whole', 'h': 'half', 'q': 'quarter', '8': 'eighth', '16': '16th', '32': '32nd'}
TYPE_TOKEN = {v: k for k, v in TYPE_NAME.items()}
ACC_NAME = {-2: 'flat-flat', -1: 'flat', 0: 'natural', 1: 'sharp', 2: 'double-sharp'}
ACC_VALUE = {v: k for k, v in ACC_NAME.items()}
# quality -> (MusicXML kind, text shown after the root, added degrees)
KIND = {
    'maj7': ('major-seventh', 'maj7', []), '6': ('major-sixth', '6', []), 'm7': ('minor-seventh', 'm7', []),
    '7': ('dominant', '7', []), 'm7b5': ('half-diminished', 'm7(b5)', []), '7b9': ('dominant', '7', [(9, -1, 'add')]),
}
KIND_TEXT = {'major': '', 'minor': 'm', 'dominant': '7', 'major-seventh': 'maj7', 'minor-seventh': 'm7', 'major-sixth': '6',
             'minor-sixth': 'm6', 'half-diminished': 'm7b5', 'diminished': 'dim', 'diminished-seventh': 'dim7', 'augmented': 'aug',
             'dominant-ninth': '9', 'major-ninth': 'maj9', 'minor-ninth': 'm9', 'suspended-fourth': 'sus4', 'none': ''}
ALTER_TEXT = {-1: 'b', 0: '', 1: '#'}


def _sub(parent, tag, text=None, **attrs):
    el = ET.SubElement(parent, tag, {k.replace('_', '-'): str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def write_musicxml(page: Page, bars_per_system: int = 4) -> str:
    root = ET.Element('score-partwise', version='4.0')
    _sub(root, 'movement-title', page.title)
    defaults = _sub(root, 'defaults')
    scaling = _sub(defaults, 'scaling')
    _sub(scaling, 'millimeters', 6.6)
    _sub(scaling, 'tenths', 40)
    layout = _sub(defaults, 'page-layout')
    _sub(layout, 'page-height', 1800)  # A4 at this scaling
    _sub(layout, 'page-width', 1273)
    margins = _sub(layout, 'page-margins', type='both')
    for side in ('left', 'right', 'top', 'bottom'):
        _sub(margins, f'{side}-margin', 73)
    part_list = _sub(root, 'part-list')
    _sub(_sub(part_list, 'score-part', id='P1'), 'part-name', 'Melody', print_object='no')
    part = _sub(root, 'part', id='P1')
    tie_open = False
    for bar in page.bars:
        m = _sub(part, 'measure', number=bar.number)
        if bar.number > 1 and (bar.number - 1) % bars_per_system == 0:
            _sub(m, 'print', new_system='yes')
        if bar.number == 1:
            a = _sub(m, 'attributes')
            _sub(a, 'divisions', DIV)
            _sub(_sub(a, 'key'), 'fifths', page.fifths)
            t = _sub(a, 'time')
            _sub(t, 'beats', 4)
            _sub(t, 'beat-type', 4)
            c = _sub(a, 'clef')
            _sub(c, 'sign', 'G')
            _sub(c, 'line', 2)
        chords = {F(beat - 1): chord for beat, chord in bar.chords}
        onset, in_tuplet, filled = F(0), False, F(0)
        for n in bar.notes:
            if n.kind != 'grace' and onset in chords:
                chord = chords.pop(onset)
                kind, text, degrees = KIND[chord.quality]
                h = _sub(m, 'harmony')
                r = _sub(h, 'root')
                _sub(r, 'root-step', chord.step)
                if chord.alter:
                    _sub(r, 'root-alter', chord.alter)
                _sub(h, 'kind', kind).set('text', text)
                for value, alter, typ in degrees:
                    d = _sub(h, 'degree')
                    _sub(d, 'degree-value', value)
                    _sub(d, 'degree-alter', alter)
                    _sub(d, 'degree-type', typ)
            el = _sub(m, 'note')
            if n.kind == 'grace':
                _sub(el, 'grace', slash='yes')
            if n.kind == 'rest':
                _sub(el, 'rest')
            else:
                p = _sub(el, 'pitch')
                _sub(p, 'step', n.step)
                if n.alter:
                    _sub(p, 'alter', n.alter)
                _sub(p, 'octave', n.octave)
            tie_stop = n.kind == 'note' and tie_open
            if n.kind != 'grace':
                _sub(el, 'duration', int(n.dur * DIV))
            if tie_stop:
                _sub(el, 'tie', type='stop')
            if n.tie:
                _sub(el, 'tie', type='start')
            _sub(el, 'voice', 1)
            _sub(el, 'type', TYPE_NAME[n.type])
            for _ in range(n.dots):
                _sub(el, 'dot')
            if n.kind != 'rest' and n.printed is not None:
                _sub(el, 'accidental', ACC_NAME[n.printed])
            start = stop = False
            if n.triplet:
                tm = _sub(el, 'time-modification')
                _sub(tm, 'actual-notes', 3)
                _sub(tm, 'normal-notes', 2)
                start = not in_tuplet
                filled = n.dur if start else filled + n.dur
                stop = filled in (F(1), F(2))
                in_tuplet = not stop
            if tie_stop or n.tie or start or stop:
                nt = _sub(el, 'notations')
                if tie_stop:
                    _sub(nt, 'tied', type='stop')
                if n.tie:
                    _sub(nt, 'tied', type='start')
                if start:
                    _sub(nt, 'tuplet', type='start', bracket='yes')
                if stop:
                    _sub(nt, 'tuplet', type='stop')
            if n.kind == 'note':
                tie_open = n.tie
            onset += n.dur
        if chords:
            raise ValueError(f'bar {bar.number}: no event starts where a chord symbol sits')
        if bar.number == len(page.bars):
            _sub(_sub(m, 'barline', location='right'), 'bar-style', 'light-heavy')
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def _load(path: str) -> ET.Element:
    if path.endswith('.mxl'):
        with zipfile.ZipFile(path) as z:
            container = ET.fromstring(z.read('META-INF/container.xml'))
            rootfile = next(el.get('full-path') for el in container.iter() if el.tag.endswith('rootfile'))
            return ET.parse(io.BytesIO(z.read(rootfile))).getroot()
    return ET.parse(path).getroot()


def _harmony_symbol(h: ET.Element) -> str:
    def name(prefix):
        step = h.findtext(f'{prefix}/{prefix}-step')
        if step is None:
            return None
        return step + ALTER_TEXT.get(int(float(h.findtext(f'{prefix}/{prefix}-alter') or 0)), '')
    kind = h.find('kind')
    text = kind.get('text') if kind is not None and kind.get('text') is not None else KIND_TEXT.get(kind.text if kind is not None else 'none', '')
    flat = text.replace('(', '').replace(')', '')
    for d in h.findall('degree'):
        deg = ALTER_TEXT.get(int(float(d.findtext('degree-alter') or 0)), '') + (d.findtext('degree-value') or '')
        if deg not in flat:
            text, flat = text + deg, flat + deg
    return (name('root') or '?') + text + ('/' + name('bass') if name('bass') else '')


def read_musicxml(path: str) -> dict:
    """Return {'fifths': int|None, 'bars': [{'number', 'events', 'chords'}]} for the first part and its first voice."""
    root = _load(path)
    part = root.find('part')
    if part is None:
        raise ValueError('no <part> (only score-partwise files are supported)')
    divisions, fifths, voice, bars = F(1), None, None, []
    for m in part.findall('measure'):
        pos, events, chords = F(0), [], []
        for el in m:
            if el.tag == 'attributes':
                if el.findtext('divisions'):
                    divisions = F(el.findtext('divisions'))
                if fifths is None and el.findtext('key/fifths') is not None:
                    fifths = int(el.findtext('key/fifths'))
            elif el.tag == 'backup':
                pos -= F(el.findtext('duration')) / divisions
            elif el.tag == 'forward':
                pos += F(el.findtext('duration')) / divisions
            elif el.tag == 'harmony':
                offset = F(el.findtext('offset') or 0) / divisions
                chords.append((pos + offset, _harmony_symbol(el)))
            elif el.tag == 'note':
                grace, chord = el.find('grace') is not None, el.find('chord') is not None
                dur = F(0) if grace else F(el.findtext('duration') or 0) / divisions
                v = el.findtext('voice') or '1'
                voice = voice or v
                if v == voice:
                    pitch = None
                    if el.find('pitch') is not None:
                        pitch = (el.findtext('pitch/step'), int(float(el.findtext('pitch/alter') or 0)), int(el.findtext('pitch/octave')))
                    tm = el.find('time-modification')
                    ev = {
                        'onset': pos, 'kind': 'grace' if grace else 'rest' if pitch is None else 'note', 'dur': dur,
                        'pitches': [pitch] if pitch else [], 'printed': [ACC_VALUE.get(el.findtext('accidental'))] if pitch else [],
                        'tie': any(t.get('type') == 'start' for t in el.findall('tie')),
                        'type': el.findtext('type'), 'dots': len(el.findall('dot')),
                        'tmod': (int(tm.findtext('actual-notes')), int(tm.findtext('normal-notes'))) if tm is not None else None,
                        'whole_bar': el.find('rest') is not None and el.find('rest').get('measure') == 'yes',
                    }
                    if chord and events and pitch:
                        events[-1]['pitches'].append(pitch)
                        events[-1]['printed'] += ev['printed']
                    else:
                        events.append(ev)
                if not chord and not grace:
                    pos += dur
        bars.append({'number': int(m.get('number')) if (m.get('number') or '').isdigit() else len(bars) + 1, 'events': events, 'chords': chords})
    return {'fifths': fifths, 'bars': bars}


def _event_token(ev: dict) -> str:
    if ev['kind'] != 'rest':
        names = [s + ACC_TEXT[a] + str(o) for s, a, o in ev['pitches']]
        head = names[0] if len(names) == 1 else '[' + '+'.join(names) + ']'
    if ev['kind'] == 'grace':
        return f'g({head})'
    if ev['whole_bar'] and ev['dur'] == 4:
        return 'R:w'
    if ev['type'] not in TYPE_TOKEN or ev['dots'] > 2:
        raise ValueError(f"note value {ev['type']!r} is outside the reading format")
    dur = TYPE_TOKEN[ev['type']] + '.' * ev['dots']
    return ('R' if ev['kind'] == 'rest' else head) + ':' + dur + ('~' if ev['tie'] else '')


def to_reading_text(score: dict, fifths: int | None = None) -> str:
    """Reading-format text with an explicit accidental on every note (so no rule is needed to resolve it).

    A bar this format cannot express is written as a line that will not parse,
    so that the scorer counts it as unread.
    """
    lines = [f"key: {score['fifths'] if fifths is None else fifths}", 'time: 4/4']
    for bar in score['bars']:
        chords = ' '.join(f'{float(onset + 1):g}={sym}' for onset, sym in bar['chords'])
        try:
            toks, group, filled = [], None, F(0)
            for ev in bar['events']:
                tok = _event_token(ev)
                if ev['kind'] == 'grace':
                    toks.append(tok)
                    continue
                if ev['tmod'] and group is None:
                    if ev['tmod'][0] != 3:
                        raise ValueError(f"tuplet {ev['tmod']} is outside the reading format")
                    toks.append('{3')
                    group, filled = True, F(0)
                if group and not ev['tmod']:
                    raise ValueError('tuplet does not close')
                if group:
                    filled += ev['dur']
                    done = filled in (F(1, 4), F(1, 2), F(1), F(2), F(4))
                    toks.append(tok + ('}' if done else ''))
                    group = None if done else True
                else:
                    toks.append(tok)
            if group:
                raise ValueError('tuplet does not close')
            lines.append(f"m{bar['number']} | chords: {chords} | events: {' '.join(toks)}")
        except ValueError as exc:
            lines.append(f"m{bar['number']} | unreadable: {exc}")
    return '\n'.join(lines) + '\n'
