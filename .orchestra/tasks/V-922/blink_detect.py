"""Blink = a block that changes and returns to its previous look within <= 6 frames.
Reports blocks (16x16 at 480x270) whose content at k-1 and k+n agree, but differ at frames in between."""
import subprocess, sys
import numpy as np
W, H, B = 480, 270, 15
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", sys.argv[1], "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                     capture_output=True, check=True).stdout
f = np.frombuffer(raw, np.uint8).reshape(-1, H, W).astype(np.float32)
blk = f.reshape(len(f), H // B, B, W // B, B).mean(axis=(2, 4))   # block means
hits = []
for k in range(1, len(blk) - 7):
    for n in range(1, 7):
        before, after = blk[k - 1], blk[k + n]
        mid = blk[k:k + n]
        dev = np.abs(mid - before).max(axis=0)          # how far the in-between frames go
        back = np.abs(after - before)                   # returned to the same look
        m = (dev > 12) & (back < 2)
        if m.any():
            ys, xs = np.nonzero(m)
            hits.append((k, n, len(ys), float(dev[m].max()), int(ys.min() * B), int(xs.min() * B), int(ys.max() * B), int(xs.max() * B)))
            break
for h in hits:
    print(f"frame {h[0]:4d} t={h[0]/30:6.2f}s  lasts {h[1]} fr  blocks {h[2]:3d}  max {h[3]:5.1f}  box y{h[4]}-{h[6]} x{h[5]}-{h[7]}")
