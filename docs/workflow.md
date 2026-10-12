# Transcribing a page: two readings, then check only the listed bars

*The procedure that "What this changes in how I work" in the [write-up](index.md) points to. I have used it once on a real transcription, described under [One real use](#one-real-use). The examples and measurements outside that section use the readings stored in this repository. The commands cover what the measurement covered: one melodic line with chord symbols in 4/4.*

The aim is to stop proofreading every note. Two readers read the page independently, a program lists the bars that need a look, and a person checks those bars against the image.

## Steps

**1. Prepare the image.** A clean print rendered at 300 dpi can go to the readers as it is. A low-resolution source, such as a screen capture or a video frame, cannot: crop each system and enlarge it first. In the measurement, Opus 5.5 scored 77% on a 620-pixel copy of a page where it otherwise had one wrong note.

**2. Get two readings.** Give each reader the image and [FORMAT.md](https://github.com/ui-hyo/sheet-music-reading-check/blob/main/FORMAT.md), and nothing else: no OMR draft, and not the other reading. A second reading by the same model can repeat the first one's mistake, so the two readers are different models, from different vendors where possible. The format already asks for the two habits that matter here: write an accidental only where one is printed, and put `?` after anything you are unsure of.

**3. Compare them.**

```sh
PYTHONPATH=src python3 -m sheetcheck.compare opus.txt astra.txt
```

With the stored readings of page A by Opus 5.5 and GPT-6 Astra, this prints:

```
a  results/no-tools/claude-code+opus-5.5/solo-1-clean.txt
b  results/no-tools/codex-cli+gpt-6-astra/solo-1-clean.txt
key 0, time 4/4, 32 bars (m1 to m32)

4 bars to check: 7, 8, 27, 28

m7: marked unsure by a
  a  m7 | chords: 1=Fm7 | events: C6:8 D6:8 Eb6:8 D6:8 Fb6:q? E6:8 C6:8
  b  m7 | chords: 1=Fm7 | events: C6:8 D6:8 Eb6:8 D6:8 Fb6:q E6:8 C6:8

m8: notes differ at beat 3
  a  m8 | chords: 1=Bbm7 3=Eb7 | events: Bb5:16 Ab5:16 Db6:16 B5:16 A5:q {3 Db5:8 Eb5:8 A5:8} G5:8 A5:8
  b  m8 | chords: 1=Bbm7 3=Eb7 | events: Bb5:16 Ab5:16 Db6:16 B5:16 A5:q {3 Fb5:8 Eb5:8 A5:8} G5:8 A5:8
...
```

A bar is listed when the readings disagree on its notes, ties, rests or chord symbols, when a reader marked something in it with `?`, when it does not add up to the time signature, or when a reading has no usable line for it. Two spellings of the same pitch are not a difference. If the readers disagree on the key signature, the program says so and reads each one in its own key. Settle the key, then run again with `--key`.

Check the bar count in the header against the page. A bar that every reading leaves out at the end of the page cannot be listed.

**4. Check the listed bars.** Look at each listed bar in the image, enlarged, and correct the reading. In the example, bar 8 was Opus's error, bars 27 and 28 were Astra's, and in bar 7 both were right. The other 28 bars are left alone.

**5. Optionally add OMR as a third reading.** Audiveris exports MusicXML, and one command turns that into the same format:

```sh
audiveris -batch -transcribe -export -output omr -- page.png
PYTHONPATH=src python3 -m sheetcheck.musicxml omr/page.mxl > omr.txt     # the .mxl file Audiveris wrote under omr/
PYTHONPATH=src python3 -m sheetcheck.compare opus.txt astra.txt omr.txt --no-chords c
```

`--no-chords c` leaves the third reading out of the chord comparison, because these Audiveris exports contain no chord symbols.

It costs checking time. On pages A, B and C, adding the Audiveris reading to the pair of Opus 5.5 and GPT-6.1 Sol made the list grow from 2, 0 and 0 bars to 5, 4 and 3, and every added bar was an error of Audiveris. What it buys is a guard against two models making the same mistake: in both cases described below, Audiveris had the notes in that bar right, so a third reading would have put it on the list. This is for clean prints only. On the handwritten-style font Audiveris got no bar right, and on the low-resolution page it exported nothing.

A source that prints the same notes a second time can do this job instead. Guitar tablature did it for pitch in the [one real use](#one-real-use).

**6. Build the score and round-trip it.** An agent writes MusicXML from the corrected reading and MuseScore converts it. Then export MusicXML again from the MuseScore file and compare it with the reading:

```sh
mscore4 -o tune.mscz tune.musicxml
mscore4 -o roundtrip.musicxml tune.mscz
PYTHONPATH=src python3 -m sheetcheck.musicxml roundtrip.musicxml > roundtrip.txt
PYTHONPATH=src python3 -m sheetcheck.compare final.txt roundtrip.txt     # expect: 0 bars to check
```

This finds what was lost or changed on the way into MuseScore, chord symbols included. It cannot find a misreading, because both sides come from the same reading. This repository has no converter from a reading to MusicXML (its writer serves the generated test pages only). In my own work an agent writes that script for each tune. As a last step the agent compares each rendered system with the same system in the source.

## How much does comparing catch?

On the stored readings of the three default-font pages, I paired each current Claude model with each current Codex model: 22 pairs. In every pair, every bar that either reader had wrong was on the list. (`tests/test_compare.py` checks this.)

That is 22 pairs on three pages, not a guarantee. These stored readings also contain bars that two readers got wrong in the same way, and there the comparison shows nothing. Fable 5.1 and Opus 5 both read the F in bar 12 of page B as a D. Opus 5 and GPT-5.6 Sol both read the B in bar 27 of page A as an A, and those two are from different vendors.

A reader's own `?` marks do not replace the second reading. In the clean default-font runs, Opus 5.5 and Astra left their wrong notes unmarked (details in the [write-up](index.md)).

## One real use

After the measurement I used the procedure once on a real transcription: a jazz guitar part of 468 bars, engraved, with a tablature staff under the notation. It has single lines and chords, mostly of three or four notes, with three flats in the key signature. The source was a set of frames from a scrolling score video, so it had no pages and no bar numbers. An agent joined the frames, cut them at the barlines and laid them out again as pages of up to 32 bars. That gave 358 written bars. Two of them are long rests, and written out they make 468.

Opus 5.5 and GPT-6.1 Sol each produced one notation reading of each page. The tablature and the other markings were read in separate passes.

- **The list was long.** The comparison listed 161 of the 358 bars. In 115 the notes differed, and 42 were listed only because a reader had put a `?` in them. On the generated pages the same pair had 2, 0 and 0 bars on the list.
- **Chords were harder than single notes.** Counted against the final reading, Opus 5.5 misread 68 of 191 chords and 150 of 1,265 single notes. Sol misread 15 and 29. (The count leaves out nine bars where the two readings and the final reading do not strike the same number of notes or chords.)
- **OMR could not be the third reading.** Audiveris exported something for every page, but on the three pages that were checked its export held 8 or 9 bars where the page has 32.
- **The tablature took its place for pitch.** The same two models read the tablature separately. A script worked out the pitch of each note from its string and fret, and compared that with the notes each notation reading strikes. In 97 of the 115 bars the tablature matched exactly one of the two readings (Sol's 93 times, Opus's 4), and that reading was taken. In 15 more the two readings agreed on the rhythm, and the pitches were taken from the tablature. The last three were settled by looking at the enlarged source.
- **Two readers did share an error, and the list did not show it.** Five bars stand under an 8va line. In them both models wrote 20 notes an octave too low, in the same way. Three of the five bars were not on the list at all. The tablature showed it. Among the 191 chords counted above, both readings were wrong on 12, and their answers differed in all 12.
- **Rhythm had no third source.** This tablature prints no rhythm. The two readings disagreed about the note values in one bar and about ties in seven more. Where they agreed, nothing independent checked them.
- **The agent did the checking, not I.** The bars were settled by its scripts, and for the last three by its own look at the source. The page layout, the tablature comparison and the MusicXML builder were written for this tune and are not in this repository. From this repository the run used the format, the runner that keeps each reader to its page image, `compare`, and the round trip of step 6.
- **The round trip did not come out at zero as it stands.** The command of step 6 lists 34 of the 468 bars: 32 where the exported file spells a chord symbol in another way (`G7alt` comes back as `G7b5#5b9#9`), one where a chord symbol had been moved to the nearest half beat, and one where only some notes of a chord are tied. The agent's verifier allows for these three things and then reports no difference. A separate check found the same notes struck in every bar.

I then listened to the result against the recording, with the transcription laid over the audio and the score following along. It seemed almost perfect to me, the chords included.

## Limits

- **Used once on a real transcription.** One tune, one notation reading of each page by each model. The measurements outside "One real use" come from the generated pages.
- **One line in 4/4** is what was tested. A pickup bar, or any other bar whose length differs from the time signature in the header, is listed as a bar that does not add up. That is a prompt to look, not an error.
- **Not tested:** real handwriting, piano music, more than one voice.
- **The comparison narrows the checking.** It does not prove the unlisted bars are right.
