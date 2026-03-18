import os
import queue
import signal
import sys
import threading
import time
from collections import deque
from enum import Enum, auto

import pyaudio

from llm import call_llm
from sr import vad_confidence, transcribe
from tts import TTSPlayer
from utils import (
    BEFORE_CHUNKS,
    AFTER_CHUNKS,
    DEBOUNCE_CHUNKS,
    NUM_SAMPLES,
    SPEAK_THRESHOLD,
    INTERRUPT_GRACE_PERIOD,
    InterruptDetector,
    Streamer,
    to_wav,
)

os.chdir("/tmp")


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


def drain_mic_buffer(stream, count=1):
    for _ in range(count):
        try:
            stream.read(NUM_SAMPLES, exception_on_overflow=False)
        except Exception:
            pass


def main():
    pyaudio_ = pyaudio.PyAudio()
    stream = pyaudio_.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=NUM_SAMPLES,
    )

    interrupt_detector = InterruptDetector()
    tts_player = TTSPlayer()

    state = State.IDLE
    exited = False

    def log_state(label: str):
        print(f"state: {label}", flush=True)

    work_queue: queue.Queue[list[bytes]] = queue.Queue()
    result_queue: queue.Queue[str | None] = queue.Queue()

    def worker_loop():
        while True:
            audio_buffer = work_queue.get()
            try:
                path = "/tmp/tmp_sound_sr.wav"
                to_wav(audio_buffer, path, pyaudio_)
                result = transcribe(path)
                if len(result) > 2:
                    print(f"result: {result.strip()}", flush=True)
                    llm_response = call_llm(result.strip())
                    print(f"llm: {llm_response}", flush=True)
                    result_queue.put(llm_response.strip() if llm_response else None)
                else:
                    result_queue.put(None)
            except Exception as e:
                print(f"ERROR worker: {e}", file=sys.stderr)
                result_queue.put(None)

    worker = threading.Thread(target=worker_loop, daemon=True)
    worker.start()

    before_chunks: deque[bytes] = deque(maxlen=BEFORE_CHUNKS)
    streamer = None
    silence_counter = 0
    speak_counter = 0

    def exit_handler(signum, frame):
        nonlocal exited
        exited = True
        tts_player.stop()
        pyaudio_.close(stream)
        sys.exit(0)

    signal.signal(signal.SIGINT, exit_handler)
    signal.signal(signal.SIGTERM, exit_handler)

    log_state("ready")

    while not exited:
        try:
            raw = stream.read(NUM_SAMPLES, exception_on_overflow=False)
        except Exception as e:
            print(f"ERROR read: {e}", file=sys.stderr)
            continue

        if state == State.IDLE:
            before_chunks.append(raw)
            interrupt_detector.feed_rolling(raw)
            conf = vad_confidence(raw)
            if conf > SPEAK_THRESHOLD:
                speak_counter += 1
                if speak_counter >= DEBOUNCE_CHUNKS:
                    state = State.LISTENING
                    log_state("hear")
                    streamer = Streamer()
                    for c in before_chunks:
                        streamer.add(c)
                    speak_counter = 0
            else:
                speak_counter = 0

        elif state == State.LISTENING:
            streamer.add(raw)
            conf = vad_confidence(raw)
            if conf > SPEAK_THRESHOLD:
                silence_counter = 0
            else:
                silence_counter += 1

            if silence_counter > AFTER_CHUNKS:
                log_state("process")
                work_queue.put(streamer.audio_buffer)
                state = State.PROCESSING
                streamer = None
                silence_counter = 0

        elif state == State.PROCESSING:
            try:
                llm_text = result_queue.get_nowait()
                if llm_text:
                    interrupt_detector.freeze_baseline()
                    tts_player.speak_async(llm_text)
                    state = State.SPEAKING
                    log_state("speaking")
                else:
                    state = State.IDLE
                    before_chunks.clear()
                    log_state("not_hear")
            except queue.Empty:
                pass

        elif state == State.SPEAKING:
            if not tts_player.is_robot_speaking:
                drain_mic_buffer(stream)
                interrupt_detector.reset()
                state = State.IDLE
                before_chunks.clear()
                log_state("not_hear")
            elif tts_player.is_audio_playing:
                elapsed = time.time() - tts_player.get_start_time()
                if elapsed > INTERRUPT_GRACE_PERIOD:
                    if interrupt_detector.update(raw):
                        tts_player.stop()
                        drain_mic_buffer(stream)
                        state = State.IDLE
                        before_chunks.clear()
                        log_state("ready")


if __name__ == "__main__":
    main()
