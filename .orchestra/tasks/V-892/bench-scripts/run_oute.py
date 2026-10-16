import json, sys, time
from pathlib import Path
import torch, soundfile as sf
torch.set_num_threads(6)
sys.path.insert(0, str(Path(__file__).parent))
from common import texts, Log
import torchaudio
def _sf_load(path, *a, **k):
    import io
    data, sr = sf.read(io.BytesIO(path) if isinstance(path, (bytes, bytearray)) else path, dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), sr
def _sf_save(path, audio, sample_rate, **k):
    sf.write(str(path), audio.detach().cpu().numpy().T, sample_rate, subtype="PCM_16")
torchaudio.load, torchaudio.save = _sf_load, _sf_save  # torchaudio 2.9 routes load() through torchcodec, absent here
import outetts
from outetts.utils.preprocessing import text_normalizations
root = Path(__file__).parents[1]
out = Path(sys.argv[1]); log = Log("outetts-1.0", out)
for model_enum, tag in [(outetts.Models.VERSION_1_0_SIZE_1B, "1b"), (outetts.Models.VERSION_1_0_SIZE_0_6B, "0.6b")]:
    t0 = time.time()
    iface = outetts.Interface(config=outetts.ModelConfig.auto_config(model=model_enum, backend=outetts.Backend.HF))
    print(tag, "load_s", round(time.time() - t0, 1), flush=True)
    w = json.load(open(root / "ref/ref_m1.words.json"))
    speaker = iface.audio_processor.create_speaker_from_dict({"audio": {"bytes": open(root / "ref/ref_m1.wav", "rb").read()},
                                                              "text": text_normalizations(w["text"]), "words": w["words"]})
    speaker["interface_version"] = iface.config.interface_version.value
    for pid, text in texts(plus=False):
        t = time.time()
        res = iface.generate(config=outetts.GenerationConfig(text=text, generation_type=outetts.GenerationType.CHUNKED, speaker=speaker,
                                                             sampler_config=outetts.SamplerConfig(temperature=0.4)))
        dt = time.time() - t
        path = out / f"outetts-{tag}_ref-m1_{pid}.wav"; res.save(str(path))
        log.record(f"{tag}/ref-m1", pid, path, dt, False)
    del iface
