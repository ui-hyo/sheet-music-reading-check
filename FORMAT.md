# Reading format

A reading is plain text: two header lines, then one line per bar.

```
key: -2
time: 4/4
m1 | chords: 1=Cm7 3=F7 | events: R:q G4:8 C5:8 Eb5:q {3 F5:8 G5:8 An5:8}
m2 | chords: 1=Bbmaj7 | events: A5:q. G5:8~ G5:h
```

- `key:` is the key signature as a number: sharps are positive, flats negative, `0` for none. Two flats is `-2`.
- `time:` is the time signature as printed.
- Bar numbers: the small number at the start of each system is that system's first bar. Count bars left to right.
- Pitches are the written pitches exactly as they sit on the treble staff. `C5` is the third-space C, `F5` the top line, `G4` the second line, `A5` the first ledger line above the staff, `C4` the first ledger line below it. Use the letter, then the accidental printed on that notehead, then the octave number: `C5`, `Eb5`, `F#5`, `Bn4` (a printed natural sign), `Bb4`.
- Write an accidental only when a sign is printed directly before that notehead. Do not add the sharps or flats of the key signature to the note names, and do not repeat an accidental that was printed earlier in the bar. Both are applied later by a program.
- Durations: `w` whole, `h` half, `q` quarter, `8` eighth, `16`, `32`. A dot adds `.` (`q.`, `8.`). Rests are `R:q`, `R:8`, and so on; a whole-bar rest is `R:w`.
- An event is `<pitch>:<duration>`. A tie that starts on this note: append `~` (`Eb5:q~`). A grace note: `g(Bb5)` placed before its main note. Notes sounding together: `[C5+E5]:q`. Ignore accents, staccato dots and slurs.
- Triplets: wrap the members, `{3 G4:8 C5:8 D5:8}`. A quarter-note triplet is `{3 C5:q D5:q E5:q}`. Rests and mixed values are allowed inside (`{3 R:8 C5:8 D5:8}`, `{3 A5:q C6:8}`).
- Chord symbols: give the beat (1 to 4) where the symbol sits and the symbol as printed, for example `1=Cm7 3=G7(b9)`. A bar with no chord symbol has an empty `chords:` field.
- If you are unsure of a pitch or rhythm, still give your best reading and put `?` right after the event (`F#5:q?`).
- Each bar must add up to the time signature. If your reading does not, re-check it. If it still does not, keep your reading and end the line with ` # len=<your sum>`.

Chord-symbol spellings that mean the same chord are scored as equal (`C-7`, `Cm7`, `Cmin7`; `G7(b9)`, `G7b9`). Enharmonic spellings of a note are scored as equal too, but remember that an accidental you write carries to later notes on the same line or space in that bar.
