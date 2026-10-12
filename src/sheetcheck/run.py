"""Run the reading task on agent CLIs, one isolated folder per run.

    python3 -m sheetcheck.run --batch no-tools --pages solo-1,lead-3 --inputs clean,lowres --products all

Each run gets a fresh folder outside this repository that holds only the page
image. While a batch runs, the answers and the generator (`material/`, `src/`)
are made unreadable, so an agent that wanders cannot find them. Every run keeps
the CLI's event log where the CLI provides one, so tool use can be audited.

A "product" here is a model inside its vendor's CLI. Results are about that
pair, not about the model alone.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

from . import reading as R
from .score import score, summary_line

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = pathlib.Path(os.environ.get('SHEETCHECK_RUN_DIR', '~/.cache/sheet-reading-check')).expanduser()
INPUT_FILE = {'clean': 'clean.png', 'lowres': 'lowres.jpg'}

# name -> vendor CLI, model as that CLI names it, reasoning effort (None = CLI default).
PRODUCTS = {
    'claude-code+haiku-5.5': dict(vendor='claude', model='claude-haiku-5-5', effort=None),
    'claude-code+sonnet-5.5': dict(vendor='claude', model='claude-sonnet-5-5', effort='xhigh'),
    'claude-code+opus-5.5': dict(vendor='claude', model='claude-opus-5-5', effort='xhigh'),
    'claude-code+opus-5': dict(vendor='claude', model='claude-opus-5', effort='xhigh'),
    'claude-code+fable-5.1': dict(vendor='claude', model='claude-fable-5-1', effort='xhigh'),
    'codex-cli+gpt-6-luna': dict(vendor='codex', model='gpt-6-luna', effort='max'),
    'codex-cli+gpt-5.6-sol': dict(vendor='codex', model='gpt-5.6-sol', effort='max'),
    'codex-cli+gpt-6.1-sol': dict(vendor='codex', model='gpt-6.1-sol', effort='max'),
    'codex-cli+gpt-6-astra': dict(vendor='codex', model='gpt-6-astra', effort='max'),
    # These two go through a local wrapper script: WRAPPER PROMPT_FILE OUTPUT_FILE [...].
    'antigravity+gemini-3.8-flash': dict(vendor='gemini', model='Gemini 3.8 Flash (High)', effort=None),
    'grok-cli+grok-4.7': dict(vendor='grok', model='grok-4.7', effort='xhigh'),
}
WRAPPER_ENV = {'gemini': 'SHEETCHECK_GEMINI_WRAPPER', 'grok': 'SHEETCHECK_GROK_WRAPPER'}
VERSION_CMD = {'claude': ['claude', '--version'], 'codex': ['codex', '--version'], 'gemini': ['agy', '--version'], 'grok': ['grok', '--version']}

RULES = ('Do not run any code or shell command, do not crop, zoom or re-render the image, do not open any other file or directory, '
         'do not search, and do not call any other AI or agent. If something is hard to read, give your best reading and mark it '
         'as described below. Do not stop or ask a question.')
PROMPT = """This is a measurement of how accurately you can read printed sheet music from an image, using nothing but looking at it.

{how}
{rules}

The page is one staff of music in treble clef with chord symbols above it: 32 bars in 8 systems of 4 bars each. Transcribe all 32 bars in the format below.

{format}
Reply with only the two header lines and the 32 bar lines, with no commentary before or after them.
"""
HOW_FILE = 'Open the image file {name} in the current directory with one file-read call. That is the only file you may open.'
HOW_ATTACHED = 'The page image is attached to this message. Look at the attached image only.'


def build_prompt(vendor: str, image_name: str, format_text: str) -> str:
    how = HOW_ATTACHED if vendor == 'codex' else HOW_FILE.format(name=image_name)
    body = format_text.split('\n', 1)[1].strip() + '\n'  # drop the title line
    return PROMPT.format(how=how, rules=RULES, format=body)


def _clean_env() -> dict:
    """Drop variables this process may have inherited from a parent agent session."""
    drop = ('CLAUDECODE', 'CLAUDE_CODE_', 'CLAUDE_EFFORT', 'CLAUDE_PID', 'CLAUDE_SESSION', 'CLOSE_OUT_', 'AGENT_CALL_')
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


def _run(cmd: list[str], cwd: pathlib.Path, stdin: str | None, timeout: int, env: dict) -> tuple[int | None, str, str]:
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, start_new_session=True,
                            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
        return None, out, err


def _jsonl(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _claude(job, d, prompt, timeout, env):
    p = PRODUCTS[job['product']]
    cmd = ['claude', '-p', '--model', p['model'], '--output-format', 'stream-json', '--verbose', '--tools', 'Read',
           '--allowedTools', 'Read', '--no-session-persistence']
    if p['effort']:
        cmd += ['--effort', p['effort']]
    code, out, err = _run(cmd, d, prompt, timeout, env)
    (d / 'events.jsonl').write_text(out)
    events = _jsonl(out)
    result = next((e for e in reversed(events) if e.get('type') == 'result'), {})
    tools = [(b.get('name'), os.path.basename(str((b.get('input') or {}).get('file_path', ''))))
             for e in events if e.get('type') == 'assistant' for b in (e.get('message') or {}).get('content') or []
             if isinstance(b, dict) and b.get('type') == 'tool_use']
    ok = code == 0 and not result.get('is_error')
    return dict(reading=result.get('result') or '', ok=ok, tool_calls=[list(t) for t in tools],
                reported_models=sorted(result.get('modelUsage') or {}), stderr=err)


def _codex(job, d, prompt, timeout, env):
    p = PRODUCTS[job['product']]
    last = d / 'last.txt'
    cmd = ['codex', 'exec', '-m', p['model'], '-c', f'model_reasoning_effort="{p["effort"]}"', '-s', 'read-only', '--skip-git-repo-check',
           '-C', str(d), '--json', '-i', str(d / job['image_name']), '-o', str(last), '-']
    code, out, err = _run(cmd, d, prompt, timeout, env)
    (d / 'events.jsonl').write_text(out)
    items = {}
    for e in _jsonl(out):
        item = e.get('item') or {}
        if item.get('type') not in (None, 'agent_message', 'reasoning'):
            items[item.get('id', len(items))] = [item.get('type'), str(item.get('command') or item.get('tool') or '')[:80]]
    return dict(reading=last.read_text() if last.exists() else '', ok=code == 0, tool_calls=list(items.values()), reported_models=[], stderr=err)


def _wrapper(job, d, prompt, timeout, env):
    vendor = PRODUCTS[job['product']]['vendor']
    wrapper = os.environ.get(WRAPPER_ENV[vendor])
    if not wrapper:
        return dict(reading='', ok=False, tool_calls=None, reported_models=[], stderr=f'{WRAPPER_ENV[vendor]} is not set')
    out_file = d / 'answer.md'
    cmd = [wrapper, str(d / 'prompt.txt'), str(out_file)] + (['policy:primary'] if vendor == 'grok' else [])
    env = dict(env, ANTIGRAVITY_WORKDIR=str(d))
    code, out, err = _run(cmd, d, None, timeout, env)
    return dict(reading=out_file.read_text() if out_file.exists() else '', ok=code == 0, tool_calls=None, reported_models=[], stderr=err)


ADAPTER = {'claude': _claude, 'codex': _codex, 'gemini': _wrapper, 'grok': _wrapper}


def run_job(job: dict, batch_dir: pathlib.Path, timeout: int, versions: dict) -> dict:
    p = PRODUCTS[job['product']]
    d = batch_dir / job['id']
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / job['image_name']).write_bytes(job['image'])
    (d / 'prompt.txt').write_text(job['prompt'])
    started = time.time()
    try:
        r = ADAPTER[p['vendor']](job, d, job['prompt'], timeout, _clean_env())
    except Exception as exc:  # a broken adapter must not stop the other lanes
        r = dict(reading='', ok=False, tool_calls=None, reported_models=[], stderr=f'{type(exc).__name__}: {exc}')
    meta = {
        'product': job['product'], 'vendor_cli': p['vendor'], 'cli_version': versions.get(p['vendor']), 'requested_model': p['model'],
        'requested_effort': p['effort'], 'reported_models': r['reported_models'], 'condition': job['condition'], 'page': job['page'],
        'input': job['input'], 'duration_s': round(time.time() - started), 'ok': bool(r['ok'] and r['reading'].strip()),
        'tool_calls': r['tool_calls'], 'reading_sha256': hashlib.sha256(r['reading'].encode()).hexdigest(),
    }
    (d / 'reading.txt').write_text(r['reading'])
    (d / 'stderr.log').write_text(r['stderr'][-20000:])
    (d / 'meta.json').write_text(json.dumps(meta, indent=1) + '\n')
    print(f"[{time.strftime('%H:%M:%S')}] {job['id']}: {'ok' if meta['ok'] else 'FAILED'} in {meta['duration_s']}s", flush=True)
    return dict(job=job, reading=r['reading'], meta=meta)


class Hidden:
    """Make paths unreadable for the duration of a batch."""

    def __init__(self, paths, enabled=True):
        self.paths, self.modes = [p for p in paths if enabled], {}

    def __enter__(self):
        for p in self.paths:
            self.modes[p] = p.stat().st_mode & 0o7777
            p.chmod(0)
        return self

    def __exit__(self, *exc):
        for p, mode in self.modes.items():
            p.chmod(mode)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--batch', required=True)
    ap.add_argument('--pages', required=True, help='comma-separated folder names under material/')
    ap.add_argument('--inputs', default='clean,lowres')
    ap.add_argument('--products', default='all')
    ap.add_argument('--timeout', type=int, default=2700)
    ap.add_argument('--no-hide', action='store_true', help='leave material/ and src/ readable (for debugging)')
    ap.add_argument('--redo', action='store_true', help='run again even when a successful result exists')
    args = ap.parse_args(argv)
    products = list(PRODUCTS) if args.products == 'all' else args.products.split(',')
    unknown = [p for p in products if p not in PRODUCTS]
    if unknown:
        sys.exit(f'unknown products: {unknown}')
    format_text = (ROOT / 'FORMAT.md').read_text()
    out_dir = ROOT / 'results' / args.batch
    answers, jobs = {}, []
    for page in args.pages.split(','):
        answers[page] = (ROOT / 'material' / page / 'answer.txt').read_text()
        for inp in args.inputs.split(','):
            image = (ROOT / 'material' / page / INPUT_FILE[inp]).read_bytes()
            image_name = 'page' + pathlib.Path(INPUT_FILE[inp]).suffix
            for product in products:
                done = out_dir / product / f'{page}-{inp}.json'
                if done.exists() and json.loads(done.read_text()).get('ok') and not args.redo:
                    continue
                vendor = PRODUCTS[product]['vendor']
                jobs.append(dict(id=f'{product}__{page}__{inp}', product=product, page=page, input=inp, condition=args.batch,
                                 image=image, image_name=image_name, prompt=build_prompt(vendor, image_name, format_text)))
    versions = {}
    for vendor in {PRODUCTS[j['product']]['vendor'] for j in jobs}:
        try:
            versions[vendor] = subprocess.run(VERSION_CMD[vendor], capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
        except Exception:
            versions[vendor] = None
    batch_dir = CACHE / args.batch
    batch_dir.mkdir(parents=True, exist_ok=True)
    lanes: dict[str, list[dict]] = {}
    for j in jobs:
        lanes.setdefault(PRODUCTS[j['product']]['vendor'], []).append(j)
    print(f'{len(jobs)} runs in {len(lanes)} lanes; run folders under {batch_dir}', flush=True)

    def lane(items):
        return [run_job(j, batch_dir, args.timeout, versions) for j in items]

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    results = []
    with Hidden([ROOT / 'material', ROOT / 'src'], enabled=not args.no_hide):
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(lanes))) as pool:
            for fut in [pool.submit(lane, items) for items in lanes.values()]:
                results += fut.result()
    for r in results:
        j, folder = r['job'], out_dir / r['job']['product']
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{j['page']}-{j['input']}.txt").write_text(r['reading'])
        (folder / f"{j['page']}-{j['input']}.json").write_text(json.dumps(r['meta'], indent=1) + '\n')
    report(out_dir, answers)


def report(out_dir: pathlib.Path, answers: dict[str, str]) -> None:
    """Score every reading in a batch folder and write scores.json."""
    rows = []
    for meta_path in sorted(out_dir.glob('*/*.json')):
        meta = json.loads(meta_path.read_text())
        if meta['page'] not in answers:
            continue
        answer = R.parse_text(answers[meta['page']])
        s = score(answer, R.parse_text(meta_path.with_suffix('.txt').read_text()), answer.key)
        rows.append({**{k: meta[k] for k in ('product', 'page', 'input', 'duration_s', 'ok', 'tool_calls', 'reported_models', 'cli_version')}, **s})
        print(summary_line(f"{meta['product']} {meta['page']} {meta['input']}", s))
    (out_dir / 'scores.json').write_text(json.dumps(rows, indent=1, default=str) + '\n')


if __name__ == '__main__':
    main()
