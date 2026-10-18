# /// script
# dependencies = ["librosa", "numpy", "scipy", "soundfile", "matplotlib"]
# ///
import sys, json, numpy as np, librosa, scipy.signal as sg, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
res = {}
for name, bpm in (("559994_33044-hq", 108), ("160711_33044-hq", 90)):
    y, sr = librosa.load(f"/tmp/v943/{name}.wav", sr=22050)
    reps = int(np.ceil(30 / (len(y) / sr))); y = np.tile(y, reps)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time"); tempo = float(np.atleast_1d(tempo)[0])
    b, a = sg.butter(4, 120 / (sr / 2), "low"); low = sg.filtfilt(b, a, y)
    env = np.abs(sg.hilbert(low)); env = sg.filtfilt(*sg.butter(2, 20 / (sr / 2), "low"), env)
    flux = np.maximum(0, np.diff(env[::256])); t = np.arange(len(flux)) * 256 / sr
    pk, _ = sg.find_peaks(flux, height=flux.mean() + 2 * flux.std(), distance=int(0.2 * sr / 256)); lp = t[pk]
    off = np.array([lp[np.argmin(abs(lp - bt))] - bt for bt in beats])
    # period-folded phase: where within one beat period (ground-truth BPM) do low-band onsets fall vs the librosa grid
    P = 60 / bpm
    res[name] = {"known_bpm": bpm, "librosa_bpm": round(tempo, 1), "beats": len(beats), "loop_s": round(len(y) / sr / reps, 2),
                 "low_peaks": int(len(lp)), "beat_minus_lowband_median_s": round(float(-np.median(off)), 3),
                 "beat_minus_lowband_p10_p90_s": [round(float(-np.percentile(off, 90)), 3), round(float(-np.percentile(off, 10)), 3)],
                 "within_50ms_pct": round(100 * float(np.mean(abs(off) <= .05)), 1), "beat_period_s": round(float(np.median(np.diff(beats))), 3), "true_period_s": round(P, 3)}
    fig, ax = plt.subplots(2, 1, figsize=(14, 5), sharex=True); w = (t < 12)
    ax[0].plot(np.arange(len(low)) / sr, low, lw=.4); ax[0].set_xlim(0, 12); ax[0].set_title(f"{name} <120 Hz, orange = librosa beats (known {bpm} BPM, librosa {tempo:.1f})")
    ax[1].plot(t[w], flux[w], lw=.6); ax[1].plot(lp[lp < 12], flux[pk][lp < 12], "rv", ms=4)
    for a_ in ax:
        for x in beats[beats < 12]: a_.axvline(x, color="orange", lw=.8)
    plt.tight_layout(); plt.savefig(f"/tmp/v943/loop_{name}.png", dpi=100)
json.dump(res, open("/tmp/v943/loop_probe.json", "w"), indent=1); print(json.dumps(res, indent=1))
