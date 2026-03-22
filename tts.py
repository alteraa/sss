import subprocess
import sys
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np

from audio_io import AudioIO
from openai_client import openai_client

OPENAI_TTS_VOICE = "nova"


class TTSPlayer:
    def __init__(self, audio_io: AudioIO):
        self.audio_io = audio_io
        self.tts_start_time = 0.0
        self.tts_lock = threading.Lock()
        self.is_robot_speaking = False
        self.on_finish: Optional[Callable[[], None]] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def is_audio_playing(self) -> bool:
        return self.audio_io.is_playing

    def speak(self, text: str):
        with self.tts_lock:
            if self.audio_io.is_playing:
                return

        if not openai_client:
            print("ERROR: openai_client is None, cannot speak", file=sys.stderr)
            self.is_robot_speaking = False
            return
        try:
            self.is_robot_speaking = True

            tts_path = "/tmp/robot_tts.mp3"
            response = openai_client.audio.speech.create(
                model="tts-1",
                voice=OPENAI_TTS_VOICE,
                input=text,
            )
            response.stream_to_file(tts_path)

            reference_wav_path = "/tmp/robot_tts_ref.wav"
            try:
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-loglevel",
                        "quiet",
                        "-i",
                        tts_path,
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        reference_wav_path,
                    ],
                    check=True,
                )

                with wave.open(reference_wav_path, "rb") as wf:
                    if wf.getnchannels() != 1:
                        raise RuntimeError("Reference WAV must be mono")
                    if wf.getsampwidth() != 2:
                        raise RuntimeError("Reference WAV must be 16-bit PCM")
                    frames = wf.readframes(wf.getnframes())
                    ref = np.frombuffer(frames, dtype=np.int16).copy()
            except Exception as e:
                print(f"ERROR reference audio: {e}", file=sys.stderr, flush=True)
                ref = None

            if ref is None or len(ref) == 0:
                self.is_robot_speaking = False
                return

            with self.tts_lock:
                self.tts_start_time = time.time()
            self.audio_io.start_playback(ref)

            while self.audio_io.is_playing and self.is_robot_speaking:
                time.sleep(0.01)
        finally:
            with self.tts_lock:
                self.is_robot_speaking = False
            self.audio_io.stop_playback()
            if self.on_finish:
                self.on_finish()

    def speak_async(self, text: str):
        with self.tts_lock:
            if self._thread is not None and self._thread.is_alive():
                return
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        with self.tts_lock:
            self._thread = t
        t.start()

    def stop(self):
        with self.tts_lock:
            self.audio_io.stop_playback()
        self.is_robot_speaking = False

    def get_start_time(self) -> float:
        with self.tts_lock:
            return self.tts_start_time
