"""Menyamakan warna suara narasi baru dengan pembicara di video sumber (mode Re-create).

Memakai ToneColorConverter dari OpenVoice V2 (MyShell, lisensi MIT) di D:\\tools\\openvoice: kode sumber di src/,
model di checkpoints_v2/converter. Hanya bagian konverter yang dipakai (tanpa TTS bawaannya dan tanpa paket
watermark), dijalankan di CPU supaya tidak berebut memori GPU dengan Ollama.
Dipakai HANYA kalau pengguna menyatakan video & suara sumbernya milik sendiri atau sudah ada izin.
"""
import subprocess
import sys
import threading
from pathlib import Path

from .alat import CACHE, FFMPEG, hash_pendek

OPENVOICE = Path(r"D:\tools\openvoice")
_CKPT = OPENVOICE / "checkpoints_v2" / "converter" / "checkpoint.pth"
_CFG = OPENVOICE / "checkpoints_v2" / "converter" / "config.json"
FOLDER = CACHE / "suara-mirip"
_model = None
_kunci = threading.Lock()


def tersedia():
    if not (_CKPT.exists() and _CFG.exists() and (OPENVOICE / "src" / "openvoice" / "models.py").exists()):
        return False
    try:
        import librosa  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _muat():
    global _model
    with _kunci:
        if _model is None:
            if str(OPENVOICE / "src") not in sys.path:
                sys.path.insert(0, str(OPENVOICE / "src"))
            import torch
            from openvoice import utils
            from openvoice.models import SynthesizerTrn
            hps = utils.get_hparams_from_file(str(_CFG))
            model = SynthesizerTrn(len(getattr(hps, "symbols", [])), hps.data.filter_length // 2 + 1,
                                   n_speakers=hps.data.n_speakers, **hps.model)
            # weights_only=True: checkpoint hanya boleh berisi tensor (tidak menjalankan kode pickle)
            ck = torch.load(str(_CKPT), map_location="cpu", weights_only=True)
            model.load_state_dict(ck["model"], strict=False)
            model.eval()
            torch.set_num_threads(max(2, (torch.get_num_threads() or 4)))
            _model = (model, hps)
    return _model


def _wav(src, tujuan, sr):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(sr), str(tujuan)],
                   check=True, timeout=600)
    return tujuan


def _spek(path):
    import librosa
    import torch
    from openvoice.mel_processing import spectrogram_torch
    model, hps = _muat()
    audio, _ = librosa.load(str(path), sr=hps.data.sampling_rate)
    y = torch.FloatTensor(audio).unsqueeze(0)
    return spectrogram_torch(y, hps.data.filter_length, hps.data.sampling_rate, hps.data.hop_length,
                             hps.data.win_length, center=False)


def sidik(daftar_audio):
    """Embedding warna suara (rata-rata dari beberapa potongan rekaman)."""
    import torch
    model, hps = _muat()
    gs = []
    FOLDER.mkdir(parents=True, exist_ok=True)
    for a in daftar_audio:
        w = _wav(a, FOLDER / f"ref-{hash_pendek(str(a))}.wav", hps.data.sampling_rate)
        with torch.no_grad():
            gs.append(model.ref_enc(_spek(w).transpose(1, 2)).unsqueeze(-1))
    return torch.stack(gs).mean(0)


def samakan(audio_baru, audio_referensi, tujuan, tau=0.3):
    """Ubah warna suara `audio_baru` (narasi Edge TTS) supaya mirip pembicara di `audio_referensi` (daftar file).
    Durasi & waktu kata tidak berubah, jadi subtitle tetap sinkron."""
    import soundfile
    import torch
    model, hps = _muat()
    FOLDER.mkdir(parents=True, exist_ok=True)
    w = _wav(audio_baru, FOLDER / f"src-{hash_pendek(str(audio_baru))}.wav", hps.data.sampling_rate)
    src_se = sidik([w])
    tgt_se = sidik(audio_referensi)
    spec = _spek(w)
    with torch.no_grad():
        hasil = model.voice_conversion(spec, torch.LongTensor([spec.size(-1)]), sid_src=src_se, sid_tgt=tgt_se,
                                       tau=tau)[0][0, 0].data.cpu().float().numpy()
    soundfile.write(str(tujuan), hasil, hps.data.sampling_rate)
    return tujuan
