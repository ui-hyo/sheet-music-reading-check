# sheet-music-reading-check

Small tools for measuring how well an AI agent reads printed sheet music: a text format for a reading, a scorer, a seeded generator of test pages, and a runner for agent CLIs. There is also a command that compares two readings of a page and lists the bars a person should check.

The write-up with figures: <https://ui-hyo.github.io/sheet-music-reading-check/> (source in [docs/index.md](docs/index.md)).

Short version: on three generated pages (522 notes), read with no tools, Claude Opus 5 scored 20% and Opus 5.5 scored 99.8%; GPT-5.6 Sol scored 49% and GPT-6.1 Sol scored 100%. One run per cell, so treat small differences as noise. The score is the number of notes in the answer minus the note errors.

## What is measured

A test page is one staff in 4/4 with chord symbols, 32 bars. An agent gets the page image and returns a reading in the format described in [FORMAT.md](FORMAT.md). The scorer compares it with the answer note by note.

- A note is right when its position in the bar, its pitch and its length all match.
- Errors are counted as an edit distance per bar: a wrong, missing or extra note costs one. A bar the agent skipped or wrote in a form that cannot be parsed costs all of its notes.
- Chord symbols, ties, the key signature and the agent's own "unsure" marks are reported separately.

A "product" is a model inside its vendor's CLI (for example Claude Code with a given model). Results describe that pair, not the model on its own.

## Test pages

Pages are generated from a seed by `sheetcheck.generate`, so they are in no training set and have no copyright owner. Each page is engraved with MuseScore and then checked: the MusicXML that MuseScore exports from the engraved score is read back by an independent reader and compared with the answer, including every accidental MuseScore printed.

Each page has two images: `clean.png` (300 dpi) and `lowres.jpg` (620 pixels wide, like a screen capture of a PDF).

```sh
uv venv && uv pip install pillow
PYTHONPATH=src .venv/bin/python -m sheetcheck.material --style solo --seed 1 --out material/solo-1
```

## Running

```sh
PYTHONPATH=src python3 -m sheetcheck.run --batch no-tools --pages solo-1,lead-3 --inputs clean,lowres --products all
PYTHONPATH=src python3 -m sheetcheck.omr --pages solo-1,lead-3        # OMR only, no language model
PYTHONPATH=src python3 -m sheetcheck.score material/solo-1/answer.txt some-reading.txt
PYTHONPATH=src python3 -m sheetcheck.run --batch no-tools --report-only           # score every stored reading again
.venv/bin/python docs/make_figures.py                                          # needs matplotlib
```

Each run happens in a fresh folder outside the repository that holds only the page image. While a batch runs, the repository folder is made unreadable (answers, generator, git history, earlier results), and each finished run folder is closed as well. If a batch is killed hard, restore access with `chmod 775 .` in the repository and `chmod -R u+rwx` on the run folder.

Where the CLI writes an event log, each run is checked against the rules of its condition (`rule_check`: `pass`, `violation`, or `unverified` when the CLI gives no log).

## Using it for transcription

```sh
PYTHONPATH=src python3 -m sheetcheck.compare reading-a.txt reading-b.txt     # list the bars to check
PYTHONPATH=src python3 -m sheetcheck.musicxml score.musicxml > score.txt     # MusicXML (OMR or MuseScore export) as a reading
```

`compare` lists a bar when the readings disagree on it, when a reader marked it with `?`, when it does not add up to the time signature, or when a reading has no usable line for it. The procedure around it is in [docs/workflow.md](docs/workflow.md). It has been run on the stored readings here and used once on a real transcription, which that page describes.

[`extras/`](extras/README.md) holds four scripts for the steps after the comparison: a builder that writes MusicXML from a reading, and three that set the transcription against a recording (beat alignment, an overlay mix, a video in which the score follows the sound). They come from that one transcription and are starting points to change for another tune.

## Requirements

Python 3.12, MuseScore 4 as `mscore4` for building pages, Audiveris for the OMR baseline, and the agent CLIs you want to measure. The scripts in `extras/` that work with a recording also need numpy, scipy, librosa, soundfile and ffmpeg.

## Tests

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

The tests of the listening scripts in `extras/` make their own recording; they are skipped where librosa is not installed.

## License

MIT
