# Sheet-music reading went from 20% to 99.8% in one model generation

*Draft. All numbers are from 12 October 2026, one run per cell.*

I transcribe jazz solos into MuseScore with AI coding agents. Until this summer I worked by one rule: do not trust the model's eyes for pitches. An optical music recognition (OMR) program produced the draft, and the model only repaired it. In August a model reading a page on its own got 62 of 138 pitches right on a page where the OMR program got all 138.

This month I tested that rule on pages no model can have seen before. It no longer holds.

- On three freshly generated pages (522 notes), Claude Opus 5 read 20% of the notes correctly. Opus 5.5, in the same CLI, read 99.8%. GPT-5.6 Sol read 49%; GPT-6.1 Sol read all 522.
- The smallest current Claude model, Haiku 5.5, reads far better than the previous flagship.
- The best current models, with no tools at all, are more accurate than the OMR program I used to rely on.

![Notes read right by each product on two pages](img/products.png)

## What I measured

**The pages.** A script generates each page from a random seed: one melodic line in 4/4 with chord symbols, 32 bars, in the style of a jazz line (scale runs, approach notes, triplets, ties, rests). The music is in no training set and has no copyright owner. MuseScore engraves the page. A second program then reads back the MusicXML that MuseScore exports and compares it with the answer, including every accidental MuseScore chose to print, so the answer and the image cannot drift apart.

**The task.** The agent gets the page image and returns one line of text per bar: pitches, note values, ties, triplets and chord symbols. It may look at the image and do nothing else. Claude Code runs with only its file-reading tool. Codex CLI gets the image attached and a read-only sandbox. I checked the tool logs of every Claude Code and Codex run: one read of the image, or no tool use.

**The score.** A note is right when its position in the bar, its pitch and its length all match. Errors are counted as an edit distance per bar, so a wrong, missing or extra note costs one. A bar the agent skipped costs all its notes.

**The products.** A "product" is a model inside its vendor's CLI, at the reasoning effort I normally use (Claude Code: xhigh, with Haiku at the CLI default; Codex CLI: max). The results describe that pair, not the model alone.

Everything is one run per cell. Read small differences as noise.

## Results

| Product | Page A (186 notes) | Page B (137) | Page C (199) |
|---|---|---|---|
| Codex CLI · GPT-6.1 Sol | 186 | 137 | 199 |
| Claude Code · Opus 5.5 | 185 | 137 | 199 |
| Codex CLI · GPT-6 Astra | 183 | 137 | – |
| Claude Code · Sonnet 5.5 | 174 | 136 | – |
| Claude Code · Haiku 5.5 | 150 | 135 | – |
| Claude Code · Fable 5.1 | no answer in 45 min | 131 | – |
| Codex CLI · GPT-6 Luna | 94 | 120 | – |
| Codex CLI · GPT-5.6 Sol (previous generation) | 92 | 90 | 74 |
| Claude Code · Opus 5 (previous generation) | 20 | 56 | 30 |
| Grok CLI · Grok 4.7 | 8 | 37 | – |
| Antigravity · Gemini 3.8 Flash | 10 | 0 | – |
| Audiveris 5.11 (OMR, no language model) | 177 | 120 | 190 |

Page A and page C are the harder kind: no key signature, many accidentals, triplets, ledger lines. Page B has two flats in the key and simpler rhythm. A dash means I did not run that cell.

### One generation apart

![Previous and current generation on three pages](img/generations.png)

The gap shows on all three pages for both vendors. Scale alone does not explain it: Haiku 5.5 reads 81% and 99% of pages A and B, where Opus 5 reads 11% and 41%.

The previous-generation models read every chord symbol on all three pages. Text was never the problem. What changed is reading where a notehead sits on the staff.

### The errors that remain

The best models now make the kind of slip a person makes when sight-reading.

![Opus 5.5 read the circled F flat as D flat](img/misread-bar8.png)

Opus 5.5 made one error on page A: it read the circled F♭ as D♭, a third too low. D♭ is a chord tone of the E♭7 above it. F♭ is not.

![GPT-6 Astra read the three circled notes one step low](img/misread-bar27.png)

GPT-6 Astra read these three notes one step low. Neither model marked these notes as uncertain, although the task asks for a `?` on anything it is unsure of.

### Low resolution still needs help

![The same page at 300 dpi and at 620 pixels wide](img/lowres.png)

I shrank page A to 620 pixels wide, about what a screen capture of a PDF gives you. Opus 5.5 fell to 77%, and the OMR program produced no output. The agents were not allowed to zoom here. In real work I let them crop and enlarge each system first.

### A handwritten-style font

![Default font and handwritten-style font](img/font.png)

To see whether the models had only learned one engraving style, I re-engraved pages A and B with MuseScore's MuseJazz style, which imitates handwriting. The notes are identical. GPT-6.1 Sol still read every note on both pages. Opus 5.5 dropped from 185 to 168 on page A and from 137 to 136 on page B. The OMR program fell apart completely.

This is a font, not handwriting. I did not test real handwritten scores.

## Why did it jump?

I don't know. Here is what the numbers allow.

- **It is not scale.** The smallest model of the current Claude family beats the largest of the previous one.
- **Two vendors moved in the same generation.** The Gemini and Grok models I tested did not, but I tested Gemini 3.8 Flash and Grok 4.7 through their CLIs, not every model those vendors have.
- **It is not one font.** GPT-6.1 Sol reads a handwritten-style font as well as the default one.
- **It is recent.** A [blog post from May](https://www.artfish.ai/p/can-ai-read-music-part-2) found that Opus 4.7, GPT 5.4 and Gemini 3.0 Pro could not reliably name a single note. A [paper from July](https://arxiv.org/abs/2607.05769) found Gemini 3.1 Pro far behind a dedicated OMR model.

My guess is that music notation, or something close to it, became part of training or evaluation between these generations. Pages like mine are cheap to make in any quantity from symbolic music, which is all my generator does. A general gain in fine-grained vision would look the same from outside, though, and I found no release note that mentions either. If you know what changed, I would like to hear it.

## What this changed in how I work

Before: OMR draft, then the model repairs it bar by bar, then automatic checks.

Now, for a clean print:

1. Two models from different vendors read the page independently.
2. A program compares the two readings bar by bar.
3. I look only at the bars where they differ.

On page A, Opus 5.5 and Astra differ in three bars: 8, 27 and 28. Those are exactly the bars one of them got wrong. A model's own `?` marks are not enough for this. On these pages Opus 5.5, Astra and Haiku 5.5 left their wrong notes unmarked, and Sonnet 5.5 marked two of its four wrong bars on page A.

The automatic checks stay: every bar must add up to the time signature, and the MusicXML must survive a round trip through MuseScore. OMR is still useful on a clean print as a cheap third reading.

For a low-resolution source, the first step is unchanged: crop each system and enlarge it before anyone reads it.

## Limits

- **Small.** Three pages in the default font, two in the handwritten-style font and one low-resolution page, each read once. There are no error bars, so small differences mean nothing.
- **One kind of music.** A single line with chord symbols in 4/4, generated and cleanly engraved. No piano music, no real handwriting, no scans of old editions.
- **Model plus CLI.** Each CLI handles images in its own way, and I used each vendor's usual effort setting. Gemini and Grok ran through wrapper scripts that give no tool log, so for those two I cannot show that the look-only rule was followed.

## Reproduce

```sh
git clone <this repository> && cd sheet-music-reading-check
uv venv && uv pip install pillow
PYTHONPATH=src .venv/bin/python -m sheetcheck.material --style solo --seed 4 --out material/solo-4   # a page nobody has seen
PYTHONPATH=src python3 -m sheetcheck.run --batch no-tools --pages solo-4 --inputs clean --products claude-code+opus-5.5
PYTHONPATH=src python3 -m sheetcheck.score material/solo-4/answer.txt results/no-tools/claude-code+opus-5.5/solo-4-clean.txt
```

Pages A, B and C are `material/solo-1`, `material/lead-3` and `material/solo-2`. Every reading and its score is under `results/`, and `results/no-tools/NOTES.json` lists what was not measured. The format is described in [FORMAT.md](../FORMAT.md).
