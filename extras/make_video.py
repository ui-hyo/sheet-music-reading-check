"""A video of the score with the current bar marked, playing with a sound track (step 7 of docs/workflow.md).

    python3 extras/make_video.py pages/ map.json overlay.mp3 follow.mp4 --tempo 190

`pages/` holds what MuseScore exports for one score at one resolution: the page images and the
positions of its bars and notes. From a score built with `--layout video` (16:9 pages):

    mscore4 -o pages/score.mscz tune.musicxml
    for x in png mpos spos; do mscore4 -r 152.4 -o pages/score.$x pages/score.mscz; done

-r must be the same for all three, or the positions will not fit the images (152.4 gives 1920 x 1080).
--tempo is the tempo written in the score: MuseScore gives its positions in the time of its own playback,
and map.json (from extras/align_audio.py) says where each of those beats lies in the sound track.

The bar under the cursor is tinted, and a vertical line moves from note to note.
Needs numpy and pillow, and ffmpeg on the path. A starting point, like the rest of extras/.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

EL = re.compile(r'<element id="(\d+)" x="([\d.\-e]+)" y="([\d.\-e]+)" sx="([\d.\-e]+)" sy="([\d.\-e]+)" page="(\d+)"')
EV = re.compile(r'<event elid="(\d+)" position="([\d.]+)"')
TINT = np.array([255, 236, 160], dtype=np.float32)  # warm yellow


def positions(path: Path):
    """Boxes (x, y, width, height, page) in pixels by element, and (element, milliseconds) in playing order."""
    text = path.read_text()
    els = {int(i): (float(x) / 12, float(y) / 12, float(sx) / 12, float(sy) / 12, int(p)) for i, x, y, sx, sy, p in EL.findall(text)}
    evs = [(int(i), float(ms)) for i, ms in EV.findall(text)]
    return els, evs


def main(argv=None):
    ap = argparse.ArgumentParser(description='A video of the score with the current bar marked, playing with a sound track.')
    ap.add_argument('folder', type=Path, help='score-*.png, score.mpos and score.spos from MuseScore')
    ap.add_argument('map')
    ap.add_argument('sound')
    ap.add_argument('out')
    ap.add_argument('--tempo', type=float, required=True, help='the tempo written in the score')
    ap.add_argument('--fps', type=int, default=15)
    ap.add_argument('--seconds', type=float, help='stop after this many seconds (for a trial)')
    ap.add_argument('--pad', help='pixels tinted above and below the bar box, e.g. 70,18; without it 1.1 times the height of the box')
    args = ap.parse_args(argv)
    grid = np.array(json.loads(Path(args.map).read_text())['beat_seconds'])
    beats = np.arange(len(grid), dtype=float)
    pages = sorted(args.folder.glob('score-*.png'), key=lambda p: int(re.search(r'-(\d+)\.png$', p.name).group(1)))
    base = []
    for p in pages:
        im = Image.open(p).convert('RGBA')
        bg = Image.new('RGBA', im.size, 'white')
        bg.alpha_composite(im)
        base.append(np.asarray(bg.convert('RGB')))
    H, W = base[0].shape[:2]
    m_el, m_ev = positions(args.folder / 'score.mpos')
    s_el, s_ev = positions(args.folder / 'score.spos')
    ms_per_beat = 60000.0 / args.tempo
    # bar boxes by the beat at which each bar starts in the score's own time
    bar_start = np.array([ms / ms_per_beat for _, ms in m_ev])
    bar_box = [m_el[i] for i, _ in m_ev]
    seg_beat = np.array([ms / ms_per_beat for _, ms in s_ev])
    seg_box = [s_el[i] for i, _ in s_ev]
    # to the end of the sound file, so that the last note rings out
    sound_len = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', args.sound], capture_output=True, text=True).stdout.strip() or 0)
    duration = max(float(grid[-1]) + 2.0, sound_len)
    if args.seconds:
        duration = min(duration, args.seconds)
    n_frames = int(duration * args.fps)
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(args.fps), '-i', '-',
           '-i', args.sound, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27', '-pix_fmt', 'yuv420p', '-g', str(args.fps * 4),
           '-c:a', 'aac', '-b:a', '128k', '-t', f'{duration:.2f}', '-movflags', '+faststart', args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    last_key, frame = None, None
    for k in range(n_frames):
        t = k / args.fps
        b = float(np.interp(t, grid, beats, left=-1.0, right=beats[-1]))
        if b < 0:
            key = ('idle', 0)
        else:
            bi = int(np.searchsorted(bar_start, b + 1e-6, side='right') - 1)
            si = int(np.searchsorted(seg_beat, b + 1e-6, side='right') - 1)
            x, y, sx, sy, page = bar_box[max(bi, 0)]
            cx = seg_box[max(si, 0)][0]
            if si + 1 < len(seg_box) and seg_box[si + 1][4] == seg_box[si][4] and abs(seg_box[si + 1][1] - seg_box[si][1]) < 1 and seg_beat[si + 1] > seg_beat[si]:
                frac = (b - seg_beat[si]) / (seg_beat[si + 1] - seg_beat[si])
                cx = cx + min(1.0, max(0.0, frac)) * (seg_box[si + 1][0] - cx)
            elif si >= 0:
                frac = (b - seg_beat[si]) / max(1e-6, (bar_start[bi + 1] if bi + 1 < len(bar_start) else seg_beat[si] + 4) - seg_beat[si])
                cx = cx + min(1.0, max(0.0, frac)) * (x + sx - cx)
            key = (page, bi, int(cx))
        if key != last_key:
            if key[0] == 'idle':
                frame = base[0].copy()
            else:
                frame = base[page].copy()
                x0, x1 = int(x), int(x + sx)
                above, below = (float(v) for v in args.pad.split(',')) if args.pad else (sy * 1.1, sy * 1.1)
                y0, y1 = max(0, int(y - above)), min(H, int(y + sy + below))
                region = frame[y0:y1, x0:x1].astype(np.float32)
                frame[y0:y1, x0:x1] = (region * (TINT / 255.0)).astype(np.uint8)
                c = int(np.clip(cx, 1, W - 3))
                frame[y0:y1, c:c + 3] = (220, 40, 40)
            last_key = key
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    print('wrote', args.out, f'{n_frames} frames, {duration:.1f} s, pages {len(base)}')


if __name__ == '__main__':
    main()
