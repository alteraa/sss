import os
import queue
import signal
import sys
import threading
import time
from collections import deque
from enum import Enum, auto

from audio_io import AudioIO
from llm import call_llm
from sr import vad_confidence, transcribe
from tts import TTSPlayer
from utils import (
    AFTER_CHUNKS,
    BEFORE_CHUNKS,
    DEBOUNCE_CHUNKS,
    INTERRUPT_GRACE_PERIOD,
    SPEAK_THRESHOLD,
    InterruptDetector,
    Streamer,
    is_speech_start,
    to_wav,
)

os.chdir("/tmp")


class State(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


def main():
    audio_io = AudioIO()
    interrupt_detector = InterruptDetector()
    tts_player = TTSPlayer(audio_io)

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
                to_wav(audio_buffer, path)
                result = transcribe(path)
                if len(result) > 2:
                    print(f"result: {result.strip()}", flush=True)
                    llm_response = call_llm(result.strip())
                    print(f"llm: {llm_response}", flush=True)
                    result_queue.put(llm_response.strip() if llm_response else None)
                else:
                    result_queue.put(None)
            except Exception as e:
                print(f"ERROR worker: {e}", file=sys.stderr, flush=True)
                result_queue.put(None)

    worker = threading.Thread(target=worker_loop, daemon=True)
    worker.start()

    before_chunks: deque[bytes] = deque(maxlen=BEFORE_CHUNKS)
    streamer: Streamer | None = None
    silence_counter = 0
    speak_counter = 0
    speaking_baseline_ready = False
    post_tts_ignore_chunks = 0
    POST_TTS_IGNORE_CHUNKS = 8

    def reset_to_idle():
        nonlocal state, streamer, silence_counter, speak_counter, speaking_baseline_ready
        nonlocal post_tts_ignore_chunks
        interrupt_detector.reset()
        before_chunks.clear()
        audio_io.clear_input_queue()
        streamer = None
        silence_counter = 0
        speak_counter = 0
        speaking_baseline_ready = False
        post_tts_ignore_chunks = POST_TTS_IGNORE_CHUNKS
        state = State.IDLE

    def exit_handler(signum, frame):
        nonlocal exited
        exited = True
        tts_player.stop()
        audio_io.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, exit_handler)
    signal.signal(signal.SIGTERM, exit_handler)

    log_state("ready")

    while not exited:
        try:
            raw = audio_io.read_chunk(timeout=0.2)
        except queue.Empty:
            raw = None

        if state == State.PROCESSING:
            try:
                llm_text = result_queue.get_nowait()
                if llm_text:
                    interrupt_detector.reset()
                    speaking_baseline_ready = False
                    tts_player.speak_async(llm_text)
                    state = State.SPEAKING
                    log_state("speaking")
                else:
                    reset_to_idle()
                    log_state("not_hear")
            except queue.Empty:
                pass
            if raw is None:
                continue

        if raw is None:
            continue

        if state == State.IDLE:
            before_chunks.append(raw)
            interrupt_detector.feed_rolling(raw)
            if post_tts_ignore_chunks > 0:
                post_tts_ignore_chunks -= 1
                continue
            baseline = interrupt_detector.current_baseline()
            if is_speech_start(raw, baseline):
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
            if streamer is None:
                streamer = Streamer()
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

        elif state == State.SPEAKING:
            if not tts_player.is_robot_speaking:
                reset_to_idle()
                log_state("not_hear")
                continue

            elapsed = time.time() - tts_player.get_start_time()
            if elapsed > INTERRUPT_GRACE_PERIOD:
                if not speaking_baseline_ready:
                    interrupt_detector.freeze_baseline()
                    speaking_baseline_ready = True
                if interrupt_detector.update(raw):
                    tts_player.stop()
                    before_chunks.clear()
                    streamer = Streamer()
                    streamer.add(raw)
                    silence_counter = 0
                    speak_counter = 0
                    speaking_baseline_ready = False
                    state = State.LISTENING
                    log_state("hear")
            else:
                # Grace süresinde AEC yeni oynatılan TTS'e adapte olurken
                # sadece baseline topluyoruz.
                interrupt_detector.feed_rolling(raw)


if __name__ == "__main__":
    main()
