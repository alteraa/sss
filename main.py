import os
import queue
import signal
import sys
import threading
import time
from collections import deque
from enum import Enum, auto

import numpy as np
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
    rms,
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
    speaking_baseline_ready = False
    speaking_chunk_idx = 0
    echo_calib_mic_rms: list[float] = []
    speaking_echo_offset_chunks = 0
    speaking_ref_rms_mean = 0.0
    speaking_echo_gain = 0.0
    speaking_echo_rms_corr = 0.0
    speaking_echo_debug_lines = 0
    speaking_post_mic_rms: list[float] = []
    speaking_post_ref_rms: list[float] = []

    # Robot echo ile mikrofondaki sinyal benzerliği çok yüksekse interrupt
    # bastırılır (robotun kendi sesini insan gibi kesmemesi için).
    # Echo residual ile tahmin edilen enerji arasındaki hata toleransı.
    ECHO_PRED_ERROR_THRESHOLD = 0.8
    # Enerji ve korelasyon gate'ini çok katı tutmuyoruz; hizalama/oda
    # etkileri nedeniyle hata kaçınılmaz.
    ECHO_RMS_CORR_THRESHOLD = 0.25
    # Referans ile mikrofona yansıyan yankı arasındaki gecikme/ayar farkları için
    # offset aralığını geniş tutuyoruz.
    ECHO_OFFSET_SEARCH_CHUNKS = 30

    # Suppress kararında, global offset'e ek olarak referansın etrafında
    # küçük bir local shift penceresi deniyoruz (RMS üzerinden).
    ECHO_LOCAL_SHIFT_RANGE = 2
    ECHO_PRED_MIN_RATIO = 0.01
    # TTS başladıktan hemen sonra, birkaç chunk boyunca interrupt detection yerine
    # echo-gain'i daha doğru tahmin etmeye odaklanırız.
    ECHO_POST_CALIB_CHUNKS = 3

    ECHO_DEBUG_MAX_LINES = 25

    # TTS dururken/yeni TTS başlarken mikrofon buffer'ında kalan yankı kuyruğunu
    # daha iyi temizlemek için flush miktarı.
    MIC_DRAIN_ON_TTS_STOP_CHUNKS = 4
    MIC_DRAIN_ON_TTS_START_CHUNKS = 2

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
                    # TTS başladıktan hemen önceki baseline yerine, TTS sırasında
                    # mikrofon yankı seviyesine göre grace biterken baseline'i
                    # ayarlayacağız.
                    interrupt_detector.reset()
                    speaking_baseline_ready = False
                    speaking_chunk_idx = 0
                    echo_calib_mic_rms = []
                    speaking_echo_offset_chunks = 0
                    speaking_ref_rms_mean = 0.0
                    speaking_echo_gain = 0.0
                    speaking_echo_rms_corr = 0.0
                    speaking_echo_debug_lines = 0
                    speaking_post_mic_rms = []
                    speaking_post_ref_rms = []
                    tts_player.speak_async(llm_text)
                    # TTS başladıktan hemen sonra mikrofon buffer'ını flush edip
                    # önceki yankıların baseline/VAD'e sızmasını azaltıyoruz.
                    drain_mic_buffer(stream, count=MIC_DRAIN_ON_TTS_START_CHUNKS)
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
                drain_mic_buffer(stream, count=MIC_DRAIN_ON_TTS_STOP_CHUNKS)
                interrupt_detector.reset()
                speaking_baseline_ready = False
                speaking_chunk_idx = 0
                echo_calib_mic_rms = []
                speaking_echo_offset_chunks = 0
                speaking_ref_rms_mean = 0.0
                speaking_echo_gain = 0.0
                speaking_echo_rms_corr = 0.0
                speaking_echo_debug_lines = 0
                speaking_post_mic_rms = []
                speaking_post_ref_rms = []
                state = State.IDLE
                before_chunks.clear()
                log_state("not_hear")
            elif tts_player.is_audio_playing:
                elapsed = time.time() - tts_player.get_start_time()
                speaking_chunk_idx += 1
                if elapsed > INTERRUPT_GRACE_PERIOD:
                    if not speaking_baseline_ready:
                        # Grace bittiğinde robotun hoparlörden oluşturduğu yankı seviyesini
                        # baseline olarak dondurup, yanlış interruptları azaltıyoruz.
                        interrupt_detector.freeze_baseline()

                        # Grace boyunca mic RMS dizisi ile referans audio RMS dizisi arasında
                        # chunk ofsetini tahmin ediyoruz (echo gating için).
                        ref = tts_player.get_reference_samples()
                        if ref is not None and len(echo_calib_mic_rms) >= 3:
                            m = len(echo_calib_mic_rms)

                            def chunk_rms(ref_samples: np.ndarray, chunk_i: int) -> float:
                                start = chunk_i * NUM_SAMPLES
                                end = start + NUM_SAMPLES
                                if start >= len(ref_samples):
                                    return 0.0
                                c = ref_samples[start:end].astype(np.float32)
                                if len(c) < NUM_SAMPLES:
                                    c = np.pad(c, (0, NUM_SAMPLES - len(c)))
                                return float(np.sqrt(np.mean(c * c)))

                            ref_rms_base = [chunk_rms(ref, i) for i in range(m)]
                            if len(ref_rms_base) > 0:
                                speaking_ref_rms_mean = float(np.mean(ref_rms_base))
                            else:
                                speaking_ref_rms_mean = 0.0

                            best_off = 0
                            best_score = -1e9
                            for off in range(
                                -ECHO_OFFSET_SEARCH_CHUNKS, ECHO_OFFSET_SEARCH_CHUNKS + 1
                            ):
                                a = []
                                b = []
                                for k in range(m):
                                    j = k + off
                                    if 0 <= j < m:
                                        a.append(echo_calib_mic_rms[k])
                                        b.append(ref_rms_base[j])
                                if len(a) < 3:
                                    continue
                                a_arr = np.array(a, dtype=np.float32)
                                b_arr = np.array(b, dtype=np.float32)
                                a_arr = a_arr - a_arr.mean()
                                b_arr = b_arr - b_arr.mean()
                                denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr)) + 1e-6
                                score = float(np.dot(a_arr, b_arr) / denom)
                                if score > best_score:
                                    best_score = score
                                    best_off = off

                            speaking_echo_offset_chunks = best_off
                            speaking_echo_rms_corr = float(best_score)

                            # Least-squares slope ile mic_rms ~= gain * ref_rms modeli kur.
                            a = []
                            b = []
                            for k in range(m):
                                j = k + best_off
                                if 0 <= j < m:
                                    a.append(echo_calib_mic_rms[k])
                                    b.append(ref_rms_base[j])
                            if len(a) >= 3:
                                a_arr = np.array(a, dtype=np.float32)
                                b_arr = np.array(b, dtype=np.float32)
                                denom = float(np.dot(b_arr, b_arr)) + 1e-6
                                speaking_echo_gain = float(np.dot(a_arr, b_arr) / denom)
                            else:
                                speaking_echo_gain = 0.0
                        else:
                            speaking_echo_offset_chunks = 0
                            speaking_ref_rms_mean = 0.0
                            speaking_echo_gain = 0.0
                            speaking_echo_rms_corr = 0.0
                        speaking_baseline_ready = True
                        speaking_post_mic_rms = []
                        speaking_post_ref_rms = []
                    # Reference RMS'in mic RMS'i ne kadar iyi açıkladığına bakarak
                    # robot yankısını interrupt'dan bastırıyoruz (phase bağımsız).
                    suppress_interrupt = False
                    ref = tts_player.get_reference_samples()
                    if ref is not None and len(ref) >= NUM_SAMPLES:
                        mic_rms_now = rms(raw)
                        corr_gate = speaking_echo_rms_corr > ECHO_RMS_CORR_THRESHOLD

                        best_err = 1e9
                        best_pred = 0.0
                        best_ref_rms = 0.0
                        best_local_shift = 0

                        base_ref_chunk_i = speaking_chunk_idx + speaking_echo_offset_chunks
                        for local_shift in range(
                            -ECHO_LOCAL_SHIFT_RANGE, ECHO_LOCAL_SHIFT_RANGE + 1
                        ):
                            ref_chunk_i = base_ref_chunk_i + local_shift
                            start = ref_chunk_i * NUM_SAMPLES
                            end = start + NUM_SAMPLES
                            if start < 0 or start >= len(ref):
                                continue

                            ref_chunk = ref[start:end].astype(np.float32)
                            if len(ref_chunk) < NUM_SAMPLES:
                                ref_chunk = np.pad(
                                    ref_chunk, (0, NUM_SAMPLES - len(ref_chunk))
                                )

                            ref_rms_now = float(
                                np.sqrt(np.mean(ref_chunk * ref_chunk)) + 1e-6
                            )
                            pred_mic_rms = speaking_echo_gain * ref_rms_now

                            # Çok küçük pred değerleri yankı bastırma için anlamsız.
                            if pred_mic_rms <= (ECHO_PRED_MIN_RATIO * speaking_ref_rms_mean):
                                continue

                            err = abs(mic_rms_now - pred_mic_rms) / (pred_mic_rms + 1e-6)
                            if err < best_err:
                                best_err = err
                                best_pred = pred_mic_rms
                                best_ref_rms = ref_rms_now
                                best_local_shift = local_shift

                        energy_gate = best_pred > (ECHO_PRED_MIN_RATIO * speaking_ref_rms_mean)
                        suppress_interrupt = corr_gate and energy_gate and (
                            best_err < ECHO_PRED_ERROR_THRESHOLD
                        )

                        # Post-calibration: ilk birkaç chunk'ta interrupt'i
                        # devre dışı bırakıp echo-gain'i rafine ederiz.
                        if (
                            len(speaking_post_mic_rms) < ECHO_POST_CALIB_CHUNKS
                            and best_ref_rms > 1e-6
                        ):
                            speaking_post_mic_rms.append(mic_rms_now)
                            speaking_post_ref_rms.append(best_ref_rms)
                            if len(speaking_post_mic_rms) >= 3:
                                a_arr = np.array(
                                    speaking_post_mic_rms, dtype=np.float32
                                )
                                b_arr = np.array(
                                    speaking_post_ref_rms, dtype=np.float32
                                )
                                denom = float(np.dot(b_arr, b_arr)) + 1e-6
                                speaking_echo_gain = float(
                                    np.dot(a_arr, b_arr) / denom
                                )
                            suppress_interrupt = True
                            energy_gate = True
                            corr_gate = True

                        # Debug: ilk birkaç "robot yankısı ihtimali yüksek" chunk için
                        # neden suppress edilmediğini gösteriyoruz.
                        if (
                            speaking_echo_debug_lines < ECHO_DEBUG_MAX_LINES
                            and best_pred > (0.02 * speaking_ref_rms_mean)
                        ):
                            speaking_echo_debug_lines += 1
                            err_disp = "n/a" if best_err >= 1e8 else f"{best_err:.3f}"
                            print(
                                "DEBUG echo_gate "
                                f"idx={speaking_chunk_idx} mic_rms={mic_rms_now:.1f} "
                                f"ref_rms={best_ref_rms:.1f} gain={speaking_echo_gain:.3f} "
                                f"pred={best_pred:.1f} "
                                f"ref_mean={speaking_ref_rms_mean:.1f} "
                                f"energy_gate={energy_gate} corr_gate={corr_gate} "
                                f"best_err={err_disp} "
                                f"best_local_shift={best_local_shift} "
                                f"suppress={suppress_interrupt}",
                                file=sys.stderr,
                                flush=True,
                            )

                    if suppress_interrupt:
                        # Bastırdığımız (robot yankısı olma ihtimali yüksek) chunk'lar
                        # ardışık sayaç mantığını bozmasın; bir sonraki gerçek
                        # konuşma adayını daha temiz yakalamak için sayaç sıfırlıyoruz.
                        interrupt_detector.reset_counter()
                    elif interrupt_detector.update(raw):
                        tts_player.stop()
                        drain_mic_buffer(stream, count=MIC_DRAIN_ON_TTS_STOP_CHUNKS)
                        state = State.IDLE
                        before_chunks.clear()
                        speaking_baseline_ready = False
                        speaking_chunk_idx = 0
                        echo_calib_mic_rms = []
                        speaking_echo_offset_chunks = 0
                        speaking_ref_rms_mean = 0.0
                        speaking_echo_gain = 0.0
                        speaking_echo_rms_corr = 0.0
                        speaking_post_mic_rms = []
                        speaking_post_ref_rms = []
                        log_state("ready")
                else:
                    # Grace döneminde interrupt detection kapalı; sadece baseline ölçüyoruz.
                    interrupt_detector.feed_rolling(raw)
                    echo_calib_mic_rms.append(rms(raw))


if __name__ == "__main__":
    main()
