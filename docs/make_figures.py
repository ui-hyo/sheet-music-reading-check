"""Draw the figures for docs/article.md from the stored scores.

    .venv/bin/python docs/make_figures.py        (needs matplotlib and pillow)
"""
import json
import pathlib

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'img'
NAME = {
    'codex-cli+gpt-6.1-sol': 'Codex CLI · GPT-6.1 Sol', 'claude-code+opus-5.5': 'Claude Code · Opus 5.5',
    'codex-cli+gpt-6-astra': 'Codex CLI · GPT-6 Astra', 'claude-code+sonnet-5.5': 'Claude Code · Sonnet 5.5',
    'claude-code+haiku-5.5': 'Claude Code · Haiku 5.5', 'claude-code+fable-5.1': 'Claude Code · Fable 5.1',
    'codex-cli+gpt-6-luna': 'Codex CLI · GPT-6 Luna', 'codex-cli+gpt-5.6-sol': 'Codex CLI · GPT-5.6 Sol (previous)',
    'claude-code+opus-5': 'Claude Code · Opus 5 (previous)', 'grok-cli+grok-4.7': 'Grok CLI · Grok 4.7',
    'antigravity+gemini-3.8-flash': 'Antigravity · Gemini 3.8 Flash', 'audiveris (OMR only)': 'Audiveris 5.11 (OMR, no LLM)',
}
PREVIOUS = {'codex-cli+gpt-5.6-sol', 'claude-code+opus-5'}
BLUE, GREY, ORANGE, LIGHT = '#2b6cb0', '#8a8f98', '#c05621', '#a9c7e8'

rows = json.loads((ROOT / 'results/no-tools/scores.json').read_text()) + json.loads((ROOT / 'results/omr-only/scores.json').read_text())
cell = {(r['product'], r['page'], r['input']): r for r in rows}


def pct(product, page, inp='clean'):
    """Share of notes read right, or None when the run gave no answer or was not made."""
    r = cell.get((product, page, inp))
    if r is None or not r['ok']:
        return None
    return 100 * max(0, r['notes_total'] - r['note_errors']) / r['notes_total']


def colour(product):
    return ORANGE if product.startswith('audiveris') else GREY if product in PREVIOUS else BLUE


def label_bars(ax, bars, values, missing='no answer'):
    for bar, v in zip(bars, values):
        ax.text((v or 0) + 1, bar.get_y() + bar.get_height() / 2, missing if v is None else f'{v:.0f}%', va='center', fontsize=8)


def products_figure():
    order = sorted(NAME, key=lambda p: (pct(p, 'solo-1') or -1, pct(p, 'lead-3') or -1))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, page, title in zip(axes, ('solo-1', 'lead-3'), ('Harder page: 186 notes, many accidentals, triplets, ledger lines', 'Easier page: 137 notes, two flats in the key')):
        vals = [pct(p, page) for p in order]
        bars = ax.barh([NAME[p] for p in order], [v or 0 for v in vals], color=[colour(p) for p in order])
        label_bars(ax, bars, vals, missing='no answer in 45 min')
        ax.set_xlim(0, 112); ax.set_xlabel('score (% of the notes on the page)'); ax.set_title(title, fontsize=9)
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('Reading one printed page with no tools, one run each', fontsize=11)
    fig.tight_layout(); fig.savefig(OUT / 'products.png', dpi=160); plt.close(fig)


def generations_figure():
    pages = [('solo-1', 'page A'), ('lead-3', 'page B'), ('solo-2', 'page C')]
    pairs = [('Claude Code', 'claude-code+opus-5', 'Opus 5', 'claude-code+opus-5.5', 'Opus 5.5'),
             ('Codex CLI', 'codex-cli+gpt-5.6-sol', 'GPT-5.6 Sol', 'codex-cli+gpt-6.1-sol', 'GPT-6.1 Sol')]
    fig, axes = plt.subplots(1, 2, figsize=(9, 4.0), sharey=True)
    for ax, (cli, old, old_name, new, new_name) in zip(axes, pairs):
        x = range(len(pages))
        a = ax.bar([i - 0.2 for i in x], [pct(old, p) for p, _ in pages], 0.4, color=GREY, label=old_name)
        b = ax.bar([i + 0.2 for i in x], [pct(new, p) for p, _ in pages], 0.4, color=BLUE, label=new_name)
        for bar in list(a) + list(b):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5, f'{bar.get_height():.0f}%', ha='center', fontsize=8)
        ax.set_xticks(list(x)); ax.set_xticklabels([n for _, n in pages]); ax.set_ylim(0, 112)
        ax.set_title(cli, fontsize=10)
        ax.legend(frameon=False, fontsize=9, loc='upper center', bbox_to_anchor=(0.5, -0.1), ncol=2)
        ax.spines[['top', 'right']].set_visible(False)
    axes[0].set_ylabel('score (% of the notes on the page)')
    fig.suptitle('One model generation apart, same pages, same CLI', fontsize=11)
    fig.tight_layout(); fig.savefig(OUT / 'generations.png', dpi=160); plt.close(fig)


def paired_figure(filename, title, products, left, right, left_label, right_label, missing):
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(products) + 2.1))
    y = range(len(products))
    lv, rv = [pct(p, *left) for p in products], [pct(p, *right) for p in products]
    a = ax.barh([i + 0.2 for i in y], [v or 0 for v in lv], 0.4, color=BLUE, label=left_label)
    b = ax.barh([i - 0.2 for i in y], [v or 0 for v in rv], 0.4, color=LIGHT, label=right_label)
    label_bars(ax, a, lv); label_bars(ax, b, rv, missing=missing)
    ax.set_yticks(list(y)); ax.set_yticklabels([NAME[p] for p in products]); ax.invert_yaxis()
    ax.set_xlim(0, 118); ax.set_xlabel('score (% of the notes on the page)'); ax.set_title(title, fontsize=10)
    ax.legend(frameon=False, fontsize=9, loc='upper center', bbox_to_anchor=(0.5, -0.22), ncol=2); ax.spines[['top', 'right']].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / filename, dpi=160); plt.close(fig)


def excerpt(filename, page, box, marks):
    """Crop a region of a page image and ring the notes that were misread."""
    im = Image.open(ROOT / 'material' / page / 'clean.png').convert('RGB')
    d = ImageDraw.Draw(im)
    for x, y in marks:
        d.ellipse((x - 36, y - 36, x + 36, y + 36), outline=(200, 40, 40), width=6)
    im.crop(box).save(OUT / filename)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    products_figure()
    generations_figure()
    paired_figure('lowres.png', 'Same page as a 300 dpi image and as a 620-pixel-wide capture',
                  ['claude-code+opus-5.5', 'claude-code+sonnet-5.5', 'claude-code+haiku-5.5', 'codex-cli+gpt-6-luna', 'audiveris (OMR only)'],
                  ('solo-1', 'clean'), ('solo-1', 'lowres'), '300 dpi', '620 px wide', 'no output')
    paired_figure('font.png', 'Same notes in the default font and in a handwritten-style font',
                  ['codex-cli+gpt-6.1-sol', 'claude-code+opus-5.5', 'audiveris (OMR only)'],
                  ('solo-1', 'clean'), ('solo-1-hand', 'clean'), 'default engraving', 'handwritten-style font (MuseJazz)', 'no output')
    excerpt('misread-bar8.png', 'solo-1', (1330, 730, 2400, 1010), [(2059, 876)])
    excerpt('misread-bar27.png', 'solo-1', (1230, 2640, 2400, 2900), [(1492, 2812), (1596, 2803), (1752, 2811)])
    print(sorted(p.name for p in OUT.iterdir()))
