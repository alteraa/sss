import wave
from collections import deque
from typing import Optional

import numpy as np

from log_utils import debug_status, finish_debug_status, log_plain
from sr import rms, vad_confidence

CHANNELS = 1
SAMPLE_RATE = 16000
NUM_SAMPLES = 1536

SPEAK_THRESHOLD = 0.5
START_RMS_MULTIPLIER = 2.2
MIN_START_RMS = 180.0
MAX_START_CREST_FACTOR = 6.5

# Echo (hoparlörden mikrofona yansıma) daha yüksek olduğu senaryolarda
# robota kendi sesinden dolayı yanlış interrupt atılmasını azaltır.
INTERRUPT_RMS_MULTIPLIER = 2.5
INTERRUPT_VAD_THRESHOLD = 0.7
INTERRUPT_HOLD = 3
INTERRUPT_GRACE_PERIOD = 1.0
BASELINE_WINDOW = 40


def second_to_chunks(sec: float) -> int:
    return int(sec * (SAMPLE_RATE / NUM_SAMPLES))


BEFORE_CHUNKS = second_to_chunks(0.8)
AFTER_CHUNKS = second_to_chunks(0.5)
DEBOUNCE_CHUNKS = second_to_chunks(0.3)


class InterruptDetector:
    def __init__(self):
        self._rolling: deque[float] = deque(maxlen=BASELINE_WINDOW)
        self._frozen_baseline: Optional[float] = None
        self._counter: int = 0

    def freeze_baseline(self):
        if len(self._rolling) >= 5:
            self._frozen_baseline = float(np.mean(self._rolling))
        else:
            self._frozen_baseline = None
        self._counter = 0
        debug_status(f"DEBUG baseline frozen={self._frozen_baseline}")

    def reset(self):
        self._counter = 0
        self._frozen_baseline = None
        # Rolling pencereyi de temizle ki bir sonraki freeze_baseline,
        # özellikle TTS başlangıcından sonraki grace dönemindeki seviyeye
        # daha doğru dayansın.
        self._rolling.clear()

    def reset_counter(self):
        """
        Sadece ardışık sayaç sıfırlar.

        Not: `freeze_baseline()` tarafından dondurulmuş baseline'i bozmaz.
        """
        self._counter = 0

    def feed_rolling(self, audio_chunk: bytes):
        self._rolling.append(rms(audio_chunk))

    def current_baseline(self) -> float:
        if len(self._rolling) >= 5:
            return float(np.mean(self._rolling))
        return 80.0

    def update(self, audio_chunk: bytes) -> bool:
        current_rms = rms(audio_chunk)
        current_vad = vad_confidence(audio_chunk)

        baseline = self._frozen_baseline
        if baseline is None or baseline < 10:
            baseline = max(baseline or 0, 80.0)

        threshold = baseline * INTERRUPT_RMS_MULTIPLIER
        rms_ok = current_rms > threshold
        vad_ok = current_vad > INTERRUPT_VAD_THRESHOLD

        debug_status(
            f"DEBUG rms={current_rms:.1f} baseline={baseline:.1f} "
            f"thr={threshold:.1f} vad={current_vad:.3f}"
        )

        if rms_ok and vad_ok:
            self._counter += 1
        else:
            self._counter = 0

        if self._counter >= INTERRUPT_HOLD:
            finish_debug_status()
            log_plain("interrupt: human_speaking_while_robot")
            self.reset()
            return True
        return False


def crest_factor(audio_chunk: bytes) -> float:
    arr = np.frombuffer(audio_chunk, np.int16).astype("float32")
    if len(arr) == 0:
        return 0.0
    chunk_rms = float(np.sqrt(np.mean(arr**2)))
    if chunk_rms < 1e-6:
        return 0.0
    peak = float(np.max(np.abs(arr)))
    return peak / chunk_rms


def is_speech_start(audio_chunk: bytes, baseline: float) -> bool:
    current_vad = vad_confidence(audio_chunk)
    if current_vad <= SPEAK_THRESHOLD:
        return False

    current_rms = rms(audio_chunk)
    rms_threshold = max(MIN_START_RMS, baseline * START_RMS_MULTIPLIER)
    if current_rms <= rms_threshold:
        return False

    # Parmak şıklatma, alkış, kısa darbe gibi transient sesler genelde
    # konuşmaya göre daha yüksek crest factor üretir.
    if crest_factor(audio_chunk) > MAX_START_CREST_FACTOR:
        return False

    return True


def to_wav(audio: list[bytes], path: str):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(audio))


class Streamer:
    def __init__(self):
        self.audio_buffer: list[bytes] = []

    def add(self, chunk: bytes):
        self.audio_buffer.append(chunk)
