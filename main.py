import os
import queue
import signal
import sys
import threading
import time
from collections import deque
from enum import Enum, auto

from audio_io import AudioIO
from llm import stream_llm_sentences
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

    work_queue: queue.Queue[tuple[int, list[bytes]]] = queue.Queue()
    result_queue: queue.Queue[tuple[str, int, str | None]] = queue.Queue()

    def worker_loop():
        while True:
            turn_id, audio_buffer = work_queue.get()
            try:
                def is_turn_active() -> bool:
                    return active_turn_id == turn_id

                path = "/tmp/tmp_sound_sr.wav"
                to_wav(audio_buffer, path)
                if not is_turn_active():
                    continue

                result = transcribe(path)
                if not is_turn_active():
                    continue

                if len(result) > 2:
                    print(f"result: {result.strip()}", flush=True)
                    full_response_parts: list[str] = []
                    emitted_segment = False

                    for sentence in stream_llm_sentences(
                        result.strip(), should_continue=is_turn_active
                    ):
                        if not is_turn_active():
                            break

                        segment = sentence.strip()
                        if not segment:
                            continue
                        full_response_parts.append(segment)
                        emitted_segment = True
                        print(f"llm segment: {segment}", flush=True)
                        result_queue.put(("segment", turn_id, segment))

                    if is_turn_active():
                        full_response = " ".join(full_response_parts).strip()
                        print(f"llm: {full_response}", flush=True)
                        result_queue.put(
                            ("done", turn_id, full_response if emitted_segment else None)
                        )
                else:
                    if is_turn_active():
                        result_queue.put(("done", turn_id, None))
            except Exception as e:
                print(f"ERROR worker: {e}", file=sys.stderr, flush=True)
                if active_turn_id == turn_id:
                    result_queue.put(("done", turn_id, None))

    worker = threading.Thread(target=worker_loop, daemon=True)
    worker.start()

    before_chunks: deque[bytes] = deque(maxlen=BEFORE_CHUNKS)
    streamer: Streamer | None = None
    silence_counter = 0
    speak_counter = 0
    speaking_baseline_ready = False
    post_tts_ignore_chunks = 0
    POST_TTS_IGNORE_CHUNKS = 8
    next_turn_id = 0
    active_turn_id: int | None = None
    tts_stream_started = False
    tts_stream_finished = False

    def reset_to_idle():
        nonlocal state, streamer, silence_counter, speak_counter, speaking_baseline_ready
        nonlocal post_tts_ignore_chunks, active_turn_id, tts_stream_started, tts_stream_finished
        interrupt_detector.reset()
        before_chunks.clear()
        audio_io.clear_input_queue()
        streamer = None
        silence_counter = 0
        speak_counter = 0
        speaking_baseline_ready = False
        post_tts_ignore_chunks = POST_TTS_IGNORE_CHUNKS
        active_turn_id = None
        tts_stream_started = False
        tts_stream_finished = False
        state = State.IDLE

    def consume_result_queue():
        nonlocal state, speaking_baseline_ready, active_turn_id
        nonlocal tts_stream_started, tts_stream_finished

        while True:
            try:
                event_type, turn_id, payload = result_queue.get_nowait()
            except queue.Empty:
                break

            if active_turn_id is None or turn_id != active_turn_id:
                continue

            if event_type == "segment" and payload:
                if not tts_stream_started:
                    interrupt_detector.reset()
                    speaking_baseline_ready = False
                    tts_player.start_stream()
                    tts_stream_started = True
                    state = State.SPEAKING
                    log_state("speaking")

                tts_player.enqueue_segment(payload)
                continue

            if event_type == "done":
                if tts_stream_started and not tts_stream_finished:
                    tts_player.finish_stream()
                    tts_stream_finished = True
                elif not tts_stream_started:
                    reset_to_idle()
                    log_state("not_hear")

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
        if state in (State.PROCESSING, State.SPEAKING):
            consume_result_queue()

        try:
            raw = audio_io.read_chunk(timeout=0.2)
        except queue.Empty:
            raw = None

        if state == State.PROCESSING:
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
                next_turn_id += 1
                active_turn_id = next_turn_id
                tts_stream_started = False
                tts_stream_finished = False
                work_queue.put((active_turn_id, streamer.audio_buffer))
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
                    active_turn_id = None
                    tts_stream_started = False
                    tts_stream_finished = False
                    state = State.LISTENING
                    log_state("hear")
            else:
                # Grace süresinde AEC yeni oynatılan TTS'e adapte olurken
                # sadece baseline topluyoruz.
                interrupt_detector.feed_rolling(raw)


if __name__ == "__main__":
    main()
