import queue
import sys
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
from aec_audio_processing import AudioProcessor

from utils import CHANNELS, NUM_SAMPLES, SAMPLE_RATE

AUDIO_PROCESSOR_DELAY_MS = 60
AUDIO_PROCESSOR_FRAME_SIZE = 160  # 10 ms @ 16 kHz
INPUT_QUEUE_MAX_CHUNKS = 64


class AudioIO:
    def __init__(self):
        self._input_queue: queue.Queue[bytes] = queue.Queue(maxsize=INPUT_QUEUE_MAX_CHUNKS)
        self._playback_lock = threading.Lock()
        self._playback_samples: Optional[np.ndarray] = None
        self._playback_cursor = 0
        self._playback_active = False
        self._stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            blocksize=NUM_SAMPLES,
            dtype="int16",
            channels=CHANNELS,
            callback=self._callback,
            latency="low",
        )
        self._processor = self._create_processor()
        self._stream.start()

    def _create_processor(self) -> AudioProcessor:
        processor = AudioProcessor(enable_aec=True, enable_ns=True, enable_agc=False)
        processor.set_stream_format(SAMPLE_RATE, CHANNELS, SAMPLE_RATE, CHANNELS)
        processor.set_reverse_stream_format(SAMPLE_RATE, CHANNELS)
        processor.set_stream_delay(AUDIO_PROCESSOR_DELAY_MS)
        return processor

    def _reset_processor(self):
        self._processor = self._create_processor()

    def _queue_input_chunk(self, chunk: bytes):
        try:
            self._input_queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._input_queue.put_nowait(chunk)
            except queue.Full:
                pass

    def _consume_playback(self, frames: int) -> np.ndarray:
        with self._playback_lock:
            if not self._playback_active or self._playback_samples is None:
                return np.zeros(frames, dtype=np.int16)

            end = min(self._playback_cursor + frames, len(self._playback_samples))
            chunk = self._playback_samples[self._playback_cursor:end]
            self._playback_cursor = end

            if len(chunk) < frames:
                padded = np.zeros(frames, dtype=np.int16)
                padded[: len(chunk)] = chunk
                chunk = padded

            if self._playback_cursor >= len(self._playback_samples):
                self._playback_active = False
                self._playback_samples = None
                self._playback_cursor = 0

            return chunk

    def _process_chunk(self, mic_chunk: np.ndarray, ref_chunk: np.ndarray) -> np.ndarray:
        out_parts: list[np.ndarray] = []

        for start in range(0, len(mic_chunk), AUDIO_PROCESSOR_FRAME_SIZE):
            end = min(start + AUDIO_PROCESSOR_FRAME_SIZE, len(mic_chunk))
            mic_frame = mic_chunk[start:end]
            ref_frame = ref_chunk[start:end]

            valid_len = len(mic_frame)
            if valid_len < AUDIO_PROCESSOR_FRAME_SIZE:
                mic_frame = np.pad(
                    mic_frame, (0, AUDIO_PROCESSOR_FRAME_SIZE - valid_len), constant_values=0
                )
                ref_frame = np.pad(
                    ref_frame, (0, AUDIO_PROCESSOR_FRAME_SIZE - valid_len), constant_values=0
                )

            self._processor.process_reverse_stream(ref_frame.astype(np.int16).tobytes())
            cleaned = self._processor.process_stream(mic_frame.astype(np.int16).tobytes())
            cleaned_arr = np.frombuffer(cleaned, dtype=np.int16).copy()
            out_parts.append(cleaned_arr[:valid_len])

        if not out_parts:
            return mic_chunk.copy()
        return np.concatenate(out_parts)

    def _callback(self, indata, outdata, frames, time_info, status):
        if status:
            print(f"ERROR audio callback status: {status}", file=sys.stderr, flush=True)

        playback = self._consume_playback(frames)
        outdata[:, 0] = playback

        mic = np.ascontiguousarray(indata[:, 0].copy(), dtype=np.int16)
        try:
            cleaned = self._process_chunk(mic, playback)
        except Exception as e:
            print(f"ERROR audio processing: {e}", file=sys.stderr, flush=True)
            cleaned = np.zeros_like(mic)

        self._queue_input_chunk(cleaned.astype(np.int16).tobytes())

    def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        return self._input_queue.get(timeout=timeout)

    def clear_input_queue(self):
        while True:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break

    def start_playback(self, samples: np.ndarray):
        with self._playback_lock:
            self._playback_samples = np.ascontiguousarray(samples.astype(np.int16))
            self._playback_cursor = 0
            self._playback_active = len(self._playback_samples) > 0
        self.clear_input_queue()
        self._reset_processor()

    def stop_playback(self):
        with self._playback_lock:
            self._playback_active = False
            self._playback_samples = None
            self._playback_cursor = 0
        self.clear_input_queue()
        self._reset_processor()

    @property
    def is_playing(self) -> bool:
        with self._playback_lock:
            return self._playback_active

    def close(self):
        self.stop_playback()
        self._stream.stop()
        self._stream.close()
