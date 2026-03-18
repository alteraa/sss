import sys
import wave
from collections import deque
from typing import Optional

import numpy as np
import pyaudio

from sr import rms, vad_confidence

FORMAT = pyaudio.paInt16
CHANNELS = 1
SAMPLE_RATE = 16000
NUM_SAMPLES = 1536

SPEAK_THRESHOLD = 0.5

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
        print(
            f"DEBUG baseline frozen={self._frozen_baseline}",
            file=sys.stderr,
            flush=True,
        )

    def reset(self):
        self._counter = 0
        self._frozen_baseline = None
        # Rolling pencereyi de temizle ki bir sonraki freeze_baseline,
        # özellikle TTS başlangıcından sonraki grace dönemindeki seviyeye
        # daha doğru dayansın.
        self._rolling.clear()

    def feed_rolling(self, audio_chunk: bytes):
        self._rolling.append(rms(audio_chunk))

    def update(self, audio_chunk: bytes) -> bool:
        current_rms = rms(audio_chunk)
        current_vad = vad_confidence(audio_chunk)

        baseline = self._frozen_baseline
        if baseline is None or baseline < 10:
            baseline = max(baseline or 0, 80.0)

        threshold = baseline * INTERRUPT_RMS_MULTIPLIER
        rms_ok = current_rms > threshold
        vad_ok = current_vad > INTERRUPT_VAD_THRESHOLD

        print(
            f"DEBUG rms={current_rms:.1f} baseline={baseline:.1f} "
            f"thr={threshold:.1f} vad={current_vad:.3f}",
            file=sys.stderr,
            flush=True,
            # end="\r",
        )

        if rms_ok and vad_ok:
            self._counter += 1
        else:
            self._counter = 0

        if self._counter >= INTERRUPT_HOLD:
            print("interrupt: human_speaking_while_robot", flush=True)
            self.reset()
            return True
        return False


def to_wav(audio: list[bytes], path: str, pyaudio_: pyaudio.PyAudio):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(pyaudio_.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(audio))


class Streamer:
    def __init__(self):
        self.audio_buffer: list[bytes] = []

    def add(self, chunk: bytes):
        self.audio_buffer.append(chunk)
