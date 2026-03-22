import queue
import sys
import threading
import time
from typing import Callable, Optional

import numpy as np

from audio_io import AudioIO
from openai_client import openai_client
from utils import SAMPLE_RATE

OPENAI_TTS_VOICE = "nova"
OPENAI_TTS_SAMPLE_RATE = 24000


class TTSPlayer:
    def __init__(self, audio_io: AudioIO):
        self.audio_io = audio_io
        self.tts_start_time = 0.0
        self.tts_lock = threading.Lock()
        self.is_robot_speaking = False
        self.on_finish: Optional[Callable[[], None]] = None
        self._synthesis_queue: queue.Queue[tuple[int, Optional[str], bool]] = queue.Queue()
        self._playback_queue: queue.Queue[tuple[int, Optional[np.ndarray], bool]] = queue.Queue()
        self._stream_id = 0
        self._synthesis_worker = threading.Thread(target=self._synthesis_loop, daemon=True)
        self._playback_worker = threading.Thread(target=self._playback_loop, daemon=True)
        self._synthesis_worker.start()
        self._playback_worker.start()

    @property
    def is_audio_playing(self) -> bool:
        return self.audio_io.is_playing

    def _resample_to_output_rate(self, samples: np.ndarray) -> np.ndarray:
        if len(samples) == 0 or OPENAI_TTS_SAMPLE_RATE == SAMPLE_RATE:
            return samples

        source_positions = np.arange(len(samples), dtype=np.float32)
        target_length = max(1, int(round(len(samples) * SAMPLE_RATE / OPENAI_TTS_SAMPLE_RATE)))
        target_positions = np.linspace(0, len(samples) - 1, num=target_length, dtype=np.float32)
        resampled = np.interp(target_positions, source_positions, samples.astype(np.float32))
        return np.clip(np.round(resampled), -32768, 32767).astype(np.int16)

    def _synthesize(self, text: str) -> Optional[np.ndarray]:
        if not openai_client:
            print("ERROR: openai_client is None, cannot speak", file=sys.stderr)
            return None
        try:
            response = openai_client.audio.speech.create(
                model="tts-1",
                voice=OPENAI_TTS_VOICE,
                input=text,
                response_format="pcm",
            )

            audio_bytes = response.read()
            if not audio_bytes:
                return None

            ref = np.frombuffer(audio_bytes, dtype=np.int16).copy()
            ref = self._resample_to_output_rate(ref)

            if ref is None or len(ref) == 0:
                return None

            return ref
        except Exception as e:
            print(f"ERROR TTS: {e}", file=sys.stderr, flush=True)
            return None

    def _synthesis_loop(self):
        while True:
            stream_id, text, is_end = self._synthesis_queue.get()

            with self.tts_lock:
                if stream_id != self._stream_id:
                    continue

            if is_end:
                self._playback_queue.put((stream_id, None, True))
                continue

            if not text:
                continue

            ref = self._synthesize(text)
            if ref is None:
                continue

            with self.tts_lock:
                if stream_id != self._stream_id:
                    continue

            self._playback_queue.put((stream_id, ref, False))

    def _playback_loop(self):
        while True:
            stream_id, ref, is_end = self._playback_queue.get()

            with self.tts_lock:
                if stream_id != self._stream_id:
                    continue

            if is_end:
                while self.audio_io.is_playing:
                    time.sleep(0.01)
                with self.tts_lock:
                    if stream_id != self._stream_id:
                        continue
                    self.is_robot_speaking = False
                if self.on_finish:
                    self.on_finish()
                continue

            if ref is None:
                continue

            with self.tts_lock:
                if stream_id != self._stream_id:
                    continue
                if not self.audio_io.is_playing:
                    self.tts_start_time = time.time()

            self.audio_io.enqueue_playback(ref)

    def start_stream(self):
        with self.tts_lock:
            self._stream_id += 1
            self.is_robot_speaking = False

    def enqueue_segment(self, text: str):
        segment = text.strip()
        if not segment:
            return

        with self.tts_lock:
            stream_id = self._stream_id
            self.is_robot_speaking = True

        self._synthesis_queue.put((stream_id, segment, False))

    def finish_stream(self):
        with self.tts_lock:
            stream_id = self._stream_id
        self._synthesis_queue.put((stream_id, None, True))

    def speak_async(self, text: str):
        self.start_stream()
        self.enqueue_segment(text)
        self.finish_stream()

    def stop(self):
        with self.tts_lock:
            self._stream_id += 1
            self.audio_io.stop_playback()
            self.is_robot_speaking = False

    def get_start_time(self) -> float:
        with self.tts_lock:
            return self.tts_start_time
