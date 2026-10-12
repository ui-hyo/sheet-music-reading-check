"""OMR-only baseline: run Audiveris on the page images and score what it exports.

    python3 -m sheetcheck.omr --pages solo-1,lead-3 --inputs clean,lowres

No language model is involved. The MusicXML that Audiveris exports is converted
to the reading format (first part, first voice) and scored like any other
reading. Bars it could not express count as unread.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
import time

from .musicxml import read_musicxml, to_reading_text
from .run import INPUT_FILE, ROOT, report

PRODUCT = 'audiveris (OMR only)'


def transcribe(image: pathlib.Path, timeout: int) -> tuple[str, str]:
    """Return (reading text, note about what happened)."""
    prefix = shlex.split(os.environ.get('SHEETCHECK_OMR_PREFIX', ''))  # e.g. a memory-limited systemd scope
    with tempfile.TemporaryDirectory() as tmp:
        cmd = prefix + ['audiveris', '-batch', '-transcribe', '-export', '-output', tmp, '--', str(image)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return '', 'timeout'
        exports = sorted(pathlib.Path(tmp).rglob('*.mxl')) + sorted(pathlib.Path(tmp).rglob('*.musicxml'))
        if not exports:
            return '', f'no export (exit {proc.returncode})'
        try:
            return to_reading_text(read_musicxml(str(exports[0]))), f'{len(exports)} export file(s)'
        except Exception as exc:
            return '', f'export not readable: {type(exc).__name__}: {exc}'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--pages', required=True)
    ap.add_argument('--inputs', default='clean,lowres')
    ap.add_argument('--batch', default='omr-only')
    ap.add_argument('--timeout', type=int, default=1200)
    args = ap.parse_args(argv)
    version = None
    if shutil.which('audiveris'):
        out = subprocess.run(['audiveris', '-version'], capture_output=True, text=True, timeout=120)
        version = next(('Audiveris ' + line.split(':', 1)[1].strip() for line in (out.stdout + out.stderr).splitlines()
                        if line.strip().lower().startswith('- version:')), None)
    folder = ROOT / 'results' / args.batch / PRODUCT
    folder.mkdir(parents=True, exist_ok=True)
    answers = {}
    for page in args.pages.split(','):
        answers[page] = (ROOT / 'material' / page / 'answer.txt').read_text()
        for inp in args.inputs.split(','):
            started = time.time()
            text, note = transcribe(ROOT / 'material' / page / INPUT_FILE[inp], args.timeout)
            meta = dict(product=PRODUCT, page=page, input=inp, duration_s=round(time.time() - started), ok=bool(text.strip()),
                        tool_calls=None, reported_models=[], cli_version=version, note=note)
            (folder / f'{page}-{inp}.txt').write_text(text)
            (folder / f'{page}-{inp}.json').write_text(json.dumps(meta, indent=1) + '\n')
            print(f'{page} {inp}: {note} in {meta["duration_s"]}s', flush=True)
    report(ROOT / 'results' / args.batch, answers)


if __name__ == '__main__':
    main()
