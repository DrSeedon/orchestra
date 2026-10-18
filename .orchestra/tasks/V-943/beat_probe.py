# /// script
# dependencies = ["librosa", "numpy", "scipy", "soundfile", "matplotlib"]
# ///
import json, sys, numpy as np, librosa, scipy.signal as sg, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
bed, timing, out = sys.argv[1:4]
y, sr = librosa.load(bed, sr=22050, mono=True)
dur = len(y) / sr
tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
tempo = float(np.atleast_1d(tempo)[0])
oenv = librosa.onset.onset_strength(y=y, sr=sr)
pulse = librosa.beat.plp(onset_envelope=oenv, sr=sr)
# <120 Hz band
b, a = sg.butter(4, 120 / (sr / 2), "low"); low = sg.filtfilt(b, a, y)
env = np.abs(sg.hilbert(low)); env = sg.filtfilt(*sg.butter(2, 8 / (sr / 2), "low"), env)
hop = 512
lowflux = np.maximum(0, np.diff(env[::hop])); lt = np.arange(len(lowflux)) * hop / sr
pk, _ = sg.find_peaks(lowflux, height=lowflux.mean() + 2 * lowflux.std(), distance=int(0.25 * sr / hop))
low_peaks = lt[pk]
res = {"track": bed.split("/")[-1], "duration_s": round(dur, 1), "librosa_tempo_bpm": round(tempo, 1), "beats": len(beats),
       "median_beat_interval_s": round(float(np.median(np.diff(beats))), 3) if len(beats) > 2 else None,
       "plp_pulse_mean": round(float(pulse.mean()), 3), "plp_pulse_peak_to_mean": round(float(pulse.max() / max(pulse.mean(), 1e-9)), 2),
       "onset_env_cv": round(float(oenv.std() / oenv.mean()), 2),
       "low_band_flux_peaks": int(len(low_peaks))}
if len(low_peaks) and len(beats):
    off = [float(low_peaks[np.argmin(abs(low_peaks - bt))] - bt) for bt in beats]
    res["beat_to_nearest_lowband_peak_s"] = {"median": round(float(np.median(off)), 3), "p10": round(float(np.percentile(off, 10)), 3),
        "p90": round(float(np.percentile(off, 90)), 3), "within_50ms_pct": round(100 * float(np.mean(np.abs(off) <= 0.05)), 1)}
t = json.load(open(timing)); pre = t["pre"]
LOOP = dur - 1.0  # mix.py loops the bed with a 1 s crossfade seam
cuts_video = np.array([s["step_start"] + pre for s in t["steps"]])
cuts = cuts_video % LOOP
bt = np.array(beats)
d = [float(bt[np.argmin(abs(bt - c))] - c) for c in cuts]
res["cut_times_video_s"] = [round(float(x),2) for x in cuts_video]; res["cut_times_in_bed_s"] = [round(float(x),2) for x in cuts]
res["cut_to_nearest_beat_s"] = [round(x, 3) for x in d]
res["cut_to_beat_abs"] = {"median": round(float(np.median(np.abs(d))), 3), "max": round(float(np.max(np.abs(d))), 3),
    "within_100ms": int(sum(abs(x) <= 0.1 for x in d)), "n_cuts": len(cuts), "half_beat_s": round(0.5 * float(np.median(np.diff(bt))), 3)}
# random-cut null: expected |distance| if cuts were unrelated to the grid
rng = np.random.default_rng(0); nul = [np.mean([abs(bt[np.argmin(abs(bt - c))] - c) for c in rng.uniform(0, LOOP, len(cuts))]) for _ in range(2000)]
res["null_mean_abs_distance_s"] = round(float(np.mean(nul)), 3); res["observed_mean_abs_s"] = round(float(np.mean(np.abs(d))), 3)
json.dump(res, open(out + ".json", "w"), indent=1)
fig, ax = plt.subplots(3, 1, figsize=(14, 8), sharex=True)
ax[0].plot(np.arange(len(low)) / sr, low, lw=.4); ax[0].set_ylabel("<120 Hz waveform")
ax[1].plot(lt, lowflux, lw=.6); ax[1].plot(low_peaks, lowflux[pk], "rv", ms=4); ax[1].set_ylabel("low-band flux")
ax[2].plot(librosa.times_like(oenv, sr=sr), oenv, lw=.6); ax[2].set_ylabel("onset strength")
for a_ in ax:
    for x in beats: a_.axvline(x, color="orange", lw=.5, alpha=.7)
    for x in cuts: a_.axvline(x, color="green", lw=1.2, ls="--")
ax[2].set_xlabel("s (orange = librosa beats, green dashed = scene cuts)")
plt.tight_layout(); plt.savefig(out + ".png", dpi=110)
print(json.dumps(res, indent=1))
