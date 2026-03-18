import subprocess
import sys
import threading
import time
from typing import Callable, Optional

OPENAI_TTS_VOICE = "nova"


class TTSPlayer:
    def __init__(self):
        self.tts_process: Optional[subprocess.Popen] = None
        self.tts_start_time = 0.0
        self.tts_lock = threading.Lock()
        self.is_robot_speaking = False
        self.on_finish: Optional[Callable[[], None]] = None

    @property
    def is_audio_playing(self) -> bool:
        with self.tts_lock:
            return self.tts_process is not None and self.tts_process.poll() is None

    def speak(self, text: str):
        import llm

        with self.tts_lock:
            if self.tts_process is not None:
                self.is_robot_speaking = False
                return

        openai_client = llm.openai_client
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

            with self.tts_lock:
                self.tts_start_time = time.time()
                self.tts_process = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", tts_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            with self.tts_lock:
                proc = self.tts_process
            if proc is not None:
                proc.wait()
        finally:
            with self.tts_lock:
                self.tts_process = None
                self.is_robot_speaking = False
            if self.on_finish:
                self.on_finish()

    def speak_async(self, text: str):
        with self.tts_lock:
            if self.tts_process is not None:
                return
            self.is_robot_speaking = True
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()

    def stop(self):
        with self.tts_lock:
            if self.tts_process is not None:
                try:
                    self.tts_process.kill()
                    self.tts_process.wait(timeout=1)
                except Exception:
                    pass
                self.tts_process = None
        self.is_robot_speaking = False

    def get_start_time(self) -> float:
        with self.tts_lock:
            return self.tts_start_time
