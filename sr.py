import numpy as np
import torch
import sys
import math

torch.set_num_threads(2)

silero_vad_model, _ = torch.hub.load(
    # Lokal klasörden okumak yerine Torch Hub üzerinden indir.
    # İlgili repo: snakers4/silero-vad (önceden snakers4_silero-vad_master olarak kullanılıyordu)
    repo_or_dir="snakers4/silero-vad",
    source="github",
    model="silero_vad",
)

SAMPLE_RATE = 16000
NUM_SAMPLES = 1536
SPEAK_THRESHOLD = 0.5


def int2float(sound: bytes) -> np.ndarray:
    arr = np.frombuffer(sound, np.int16).astype("float32")
    peak = np.abs(arr).max()
    if peak > 0:
        arr *= 1.0 / 32768.0
    return arr.squeeze()


def rms(audio_chunk: bytes) -> float:
    arr = np.frombuffer(audio_chunk, np.int16).astype("float32")
    return float(np.sqrt(np.mean(arr**2))) if len(arr) > 0 else 0.0


def vad_confidence(audio_chunk: bytes) -> float:
    audio_float = int2float(audio_chunk)
    x = torch.from_numpy(audio_float).float()
    if x.dim() == 1:
        x = x.unsqueeze(0)  # (batch, time)

    # Silero VAD, 16kHz için 512 örneklik input bekliyor.
    expected = int(round((512 / 16000) * SAMPLE_RATE))
    length = int(x.shape[-1])

    if length == expected:
        with torch.no_grad():
            return float(silero_vad_model(x, SAMPLE_RATE).item())

    # Chunk boyutumuz 512 değil (ör. 1536). Beklenen pencereye bölüp
    # confidence değerlerini birleştiriyoruz.
    n = int(math.ceil(length / expected)) if expected > 0 else 0
    if n <= 0:
        return 0.0

    max_conf = 0.0
    with torch.no_grad():
        for i in range(n):
            start = i * expected
            end = min((i + 1) * expected, length)
            seg = x[..., start:end]
            if int(seg.shape[-1]) < expected:
                pad = expected - int(seg.shape[-1])
                seg = torch.nn.functional.pad(seg, (0, pad))
            conf = float(silero_vad_model(seg, SAMPLE_RATE).item())
            if conf > max_conf:
                max_conf = conf

    return max_conf


def transcribe(audio_path: str) -> str:
    # OpenAI Whisper API ile transkripsiyon yap.
    # Not: Bu fonksiyon main.py içinde worker thread tarafından çağrılıyor.
    try:
        import llm  # lazy import (sr.py tek başına import edilse bile patlamasın)

        client = getattr(llm, "openai_client", None)
        if not client:
            return ""

        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="tr",
            )

        return (getattr(resp, "text", "") or "").strip()
    except Exception as e:
        print(f"ERROR transcribe: {e}", file=sys.stderr, flush=True)
        return ""
