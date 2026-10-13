# extras: from a reading to a score, and to the recording

Four scripts for steps 6 and 7 of [the workflow](../docs/workflow.md). They come from the one real transcription described there, with the parts that belonged to that tune taken out.

They are starting points, not finished tools. The comparison in `src/` was measured on stored readings; these were used on one transcription (the alignment on two solos before it as well). Expect to change them for your tune.

| script | what it does | needs |
|---|---|---|
| `build_musicxml.py` | writes MusicXML from a reading, for MuseScore to open | Python only |
| `align_audio.py` | finds where each beat of the reading sits in a recording | numpy, scipy, librosa, soundfile, ffmpeg |
| `make_overlay.py` | mixes the reading, played as a plain tone, onto the recording | numpy, soundfile, ffmpeg |
| `make_video.py` | a video of the score with the current bar marked, playing with a sound track | numpy, pillow, ffmpeg, MuseScore 4 for the pages |

## From a reading to a score

```sh
PYTHONPATH=src python3 extras/build_musicxml.py final.txt tune.musicxml --title 'A tune' --tempo 190
mscore4 -o tune.mscz tune.musicxml
```

For guitar notation, which sounds an octave below what is written, add `--octave-down --part-name Guitar --midi-program 27`.

The builder writes one part on one staff: notes, rests, chords, grace notes, triplets, ties and chord symbols. It leaves the accidentals to MuseScore. It does not write slurs or other markings, a tablature staff, a second voice or a change of time signature.

A reading may carry two notes after ` # ` that the format in [FORMAT.md](../FORMAT.md) does not have. `# multirest=8` makes the bar a rest of eight bars, and `# section=Head` puts a boxed label above the bar. A long rest becomes that many real bars, so the bar numbers of the score run ahead of those of the reading; `--map bars.json` records which is which.

Then check what came out, as step 6 says: export MusicXML from the MuseScore file again and compare it with the reading. If the reading has a long rest, compare the text that `--expanded written-out.txt` writes instead, in which the rest is written out and the bars are numbered as in the score. MuseScore spells some chord symbols in its own way on export (`G7alt` comes back as `G7b5#5b9#9`), and those bars will be listed.

## Against the recording

```sh
PYTHONPATH=src python3 extras/align_audio.py final.txt recording.mp3 map.json --tempo 190
PYTHONPATH=src python3 extras/make_overlay.py final.txt recording.mp3 map.json overlay.mp3
```

`overlay.mp3` is the recording with the transcription sounding on top. For guitar notation give `make_overlay.py` `--octave -1`, so that the tone sounds where the guitar does. The alignment compares pitch classes only and needs no such option.

`align_audio.py` assumes 4/4, a tempo that drifts but does not jump, a form that repeats every `--chorus` bars (32 unless you say otherwise), chord symbols in the reading, and a first bar that begins near the start of the recording (`--start-within` says where to look, it is not a limit). It prints, for each part of the score, how often the written pitches are found in the recording at the place it chose and at places half a beat, one beat and four beats away. The first number should stand well above the others. It is a calculation and it can be wrong: listen to the overlay before you trust the map.

For a video in which the score follows the sound:

```sh
PYTHONPATH=src python3 extras/build_musicxml.py final.txt video.musicxml --tempo 190 --layout video
mkdir pages && mscore4 -o pages/score.mscz video.musicxml
for x in png mpos spos; do mscore4 -r 152.4 -o pages/score.$x pages/score.mscz; done
python3 extras/make_video.py pages map.json overlay.mp3 follow.mp4 --tempo 190
```

`--tempo` must be the tempo written in the score, and `-r` the same for all three exports.

## Tests

`tests/test_extras_build.py` builds MusicXML from the generated pages and from a reading with chords, reads it back, and takes it through MuseScore where MuseScore is installed. `tests/test_extras_listen.py` makes its own recording (the notes of a generated page as plain tones, on a beat grid whose tempo drifts) and measures how far the beats that `align_audio.py` finds are from that grid; it is skipped where librosa is not installed. That recording holds exactly the written notes and chords and nothing else, which is far easier than a band. There is no real recording in this repository, so nothing here shows how the alignment does on one.
