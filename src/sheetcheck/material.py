"""Build one test page: generate, engrave with MuseScore, and check the result.

    python -m sheetcheck.material --style solo --seed 1 --out material/solo-1

The check reads back the MusicXML that MuseScore exports from the engraved
score and compares it, bar by bar, with the answer: every note, rest, tie and
chord symbol, and every accidental MuseScore decided to print.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

from PIL import Image

from . import reading as R
from .generate import answer_text, make_page
from .musicxml import read_musicxml, to_reading_text, write_musicxml
from .score import all_items, norm_chord

MSCORE = 'mscore4'
LOWRES_WIDTH = 620


def _mscore(*args: str) -> None:
    subprocess.run([MSCORE, *args], check=True, capture_output=True, timeout=300)


def verify(answer: str, roundtrip_path: str) -> list[str]:
    """Differences between the answer and what MuseScore engraved; empty when they agree."""
    ans = R.parse_text(answer)
    fifths = ans.key
    R.resolve(ans, fifths)
    back = read_musicxml(roundtrip_path)
    got = R.resolve(R.parse_text(to_reading_text(back, fifths)), fifths)
    problems = []
    if back['fifths'] != fifths:
        problems.append(f"key signature {back['fifths']} != {fifths}")
    if sorted(got.bars) != sorted(ans.bars) or got.unparsed:
        problems.append(f'bars differ: {len(got.bars)} read back, {len(got.unparsed)} unreadable')
    printed = {b['number']: [a for e in b['events'] for a in e['printed']] for b in back['bars']}
    for n, a in ans.bars.items():
        g = got.bars.get(n)
        if g is None:
            continue
        if all_items(a) != all_items(g):
            problems.append(f'bar {n}: notes differ')
        if [p.acc for e in a.events for p in e.pitches] != printed[n]:
            problems.append(f'bar {n}: printed accidentals differ')
        if [norm_chord(s) for _, s in a.chords] != [norm_chord(s) for _, s in g.chords]:
            problems.append(f'bar {n}: chord symbols differ: {[s for _, s in g.chords]}')
    return problems


def build(style: str, seed: int, out: pathlib.Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    page = make_page(style, seed)
    answer = answer_text(page)
    (out / 'answer.txt').write_text(answer, encoding='utf-8')
    (out / 'page.musicxml').write_text(write_musicxml(page), encoding='utf-8')
    for old in out.glob('render-*.png'):
        old.unlink()
    _mscore('-o', str(out / 'page.mscz'), str(out / 'page.musicxml'))
    _mscore('-o', str(out / 'page.pdf'), str(out / 'page.mscz'))
    _mscore('-o', str(out / 'render.png'), '-r', '300', str(out / 'page.mscz'))
    _mscore('-o', str(out / 'roundtrip.musicxml'), str(out / 'page.mscz'))
    renders = sorted(out.glob('render-*.png'))
    if len(renders) != 1:
        raise RuntimeError(f'expected one page, MuseScore made {len(renders)}')
    img = Image.open(renders[0]).convert('RGBA')
    flat = Image.new('RGB', img.size, 'white')
    flat.paste(img, mask=img.getchannel('A'))  # MuseScore exports a transparent background
    flat.save(out / 'clean.png')
    renders[0].unlink()
    small = flat.resize((LOWRES_WIDTH, round(flat.height * LOWRES_WIDTH / flat.width)), Image.LANCZOS)
    small.save(out / 'lowres.jpg', quality=80)
    problems = verify(answer, str(out / 'roundtrip.musicxml'))
    notes = sum(1 for b in R.parse_text(answer).bars.values() for e in b.events if e.kind != 'rest')
    meta = {
        'style': style, 'seed': seed, 'key_fifths': page.fifths, 'bars': len(page.bars), 'notes': notes,
        'clean_size': flat.size, 'lowres_size': small.size, 'verified': not problems,
        'musescore': subprocess.run([MSCORE, '--version'], capture_output=True, text=True).stdout.strip(),
        'sha256': {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in ('answer.txt', 'page.musicxml', 'clean.png', 'lowres.jpg')},
    }
    (out / 'meta.json').write_text(json.dumps(meta, indent=1) + '\n', encoding='utf-8')
    return {'meta': meta, 'problems': problems}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--style', choices=['solo', 'lead'], required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--out', type=pathlib.Path, required=True)
    args = ap.parse_args(argv)
    result = build(args.style, args.seed, args.out)
    m = result['meta']
    print(f"{args.out}: key {m['key_fifths']}, {m['bars']} bars, {m['notes']} notes, clean {m['clean_size']}, lowres {m['lowres_size']}")
    for p in result['problems']:
        print('  PROBLEM', p)
    sys.exit(1 if result['problems'] else 0)


if __name__ == '__main__':
    main()
