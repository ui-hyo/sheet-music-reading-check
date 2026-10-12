# sheet-reading-check

Small tools for measuring how well an AI agent reads printed sheet music: a text format for a reading, a scorer, a seeded generator of test pages, and a runner for agent CLIs.

Status: work in progress. Results and the write-up are not here yet.

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
```

Each run happens in a fresh folder outside the repository that holds only the page image. While a batch runs, `material/` and `src/` are made unreadable. If a batch is killed hard, restore them with `chmod 775 material src`.

Requirements: Python 3.12, MuseScore 4 as `mscore4` for building pages, Audiveris for the OMR baseline, and the agent CLIs you want to measure.

## Tests

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

## License

MIT
