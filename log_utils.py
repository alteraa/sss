import threading
import time
import sys

RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
CLEAR_LINE = "\033[K"
_LOG_LOCK = threading.Lock()
_STATUS_ACTIVE = False


def fmt_ms(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    return f"{seconds * 1000:.0f} ms"


def _normalize_debug_message(message: str) -> str:
    return message.removeprefix("DEBUG ").strip()


def _finish_status_locked():
    global _STATUS_ACTIVE
    if _STATUS_ACTIVE:
        sys.stderr.write("\n")
        sys.stderr.flush()
        _STATUS_ACTIVE = False


def log_plain(message: str, color: str | None = None, stream=None):
    target = stream or sys.stdout
    with _LOG_LOCK:
        _finish_status_locked()
        if color:
            target.write(f"{color}{message}{RESET}\n")
        else:
            target.write(f"{message}\n")
        target.flush()


def log_stage(stage: str, message: str, color: str = CYAN):
    log_plain(f"[{stage}] {message}", color=color)


def debug_status(message: str, color: str = CYAN):
    global _STATUS_ACTIVE
    text = _normalize_debug_message(message)
    with _LOG_LOCK:
        sys.stderr.write(f"\r{color}[DEBUG] {text}{RESET}{CLEAR_LINE}")
        sys.stderr.flush()
        _STATUS_ACTIVE = True


def finish_debug_status():
    with _LOG_LOCK:
        _finish_status_locked()


class TurnPerfTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[str, float | int | None] = self._empty_state()

    def _empty_state(self) -> dict[str, float | int | None]:
        return {
            "turn_id": None,
            "capture_started_at": None,
            "process_started_at": None,
            "sr_started_at": None,
            "sr_done_at": None,
            "llm_started_at": None,
            "llm_first_segment_at": None,
            "llm_done_at": None,
            "tts_first_enqueue_at": None,
            "tts_playback_started_at": None,
            "response_finished_at": None,
            "segment_count": 0,
            "received_segment_count": 0,
        }

    def begin_turn(
        self, turn_id: int, capture_started_at: float | None, process_started_at: float
    ):
        with self._lock:
            self._data = self._empty_state()
            self._data.update(
                {
                    "turn_id": turn_id,
                    "capture_started_at": capture_started_at,
                    "process_started_at": process_started_at,
                }
            )

    def update(self, turn_id: int, **values):
        with self._lock:
            if self._data["turn_id"] != turn_id:
                return
            self._data.update(values)

    def increment(self, turn_id: int, key: str, amount: int = 1):
        with self._lock:
            if self._data["turn_id"] != turn_id:
                return
            self._data[key] = int(self._data.get(key, 0) or 0) + amount

    def snapshot(self) -> dict[str, float | int | None]:
        with self._lock:
            return dict(self._data)


class TurnLogger:
    def __init__(self):
        self._perf = TurnPerfTracker()

    def speech_detected(self):
        log_stage("TURN", "speech detected, capture started", CYAN)

    def begin_turn(
        self,
        turn_id: int,
        capture_started_at: float | None,
        process_started_at: float,
        buffered_chunks: int,
    ):
        self._perf.begin_turn(turn_id, capture_started_at, process_started_at)
        perf = self._perf.snapshot()
        capture_ms = (
            fmt_ms(process_started_at - perf["capture_started_at"])
            if perf["capture_started_at"] is not None
            else "n/a"
        )
        log_stage(
            "TURN",
            f"turn={turn_id} capture complete | capture={capture_ms} | buffered_chunks={buffered_chunks}",
            CYAN,
        )

    def sr_started(self, turn_id: int, started_at: float):
        self._perf.update(turn_id, sr_started_at=started_at)

    def stale_before_sr(self, turn_id: int):
        log_stage("CANCEL", f"turn={turn_id} stale before SR", RED)

    def stale_after_sr(self, turn_id: int, sr_started_at: float, sr_done_at: float):
        log_stage(
            "CANCEL",
            f"turn={turn_id} stale after SR ({fmt_ms(sr_done_at - sr_started_at)})",
            RED,
        )

    def stale_during_llm(self, turn_id: int):
        log_stage("CANCEL", f"turn={turn_id} stale during LLM stream", RED)

    def sr_done(self, turn_id: int, sr_started_at: float, sr_done_at: float):
        self._perf.update(turn_id, sr_done_at=sr_done_at, llm_started_at=sr_done_at)
        perf = self._perf.snapshot()
        log_stage(
            "SR",
            (
                f"turn={turn_id} completed in {fmt_ms(sr_done_at - sr_started_at)}"
                f" | process->sr_done={fmt_ms(sr_done_at - perf['process_started_at'])}"
            ),
            BLUE,
        )

    def llm_first_segment(self, turn_id: int, sr_done_at: float, segment_at: float):
        self._perf.update(turn_id, llm_first_segment_at=segment_at)
        perf = self._perf.snapshot()
        log_stage(
            "LLM",
            (
                f"turn={turn_id} first segment in {fmt_ms(segment_at - sr_done_at)} after SR"
                f" | process->first_segment={fmt_ms(segment_at - perf['process_started_at'])}"
            ),
            MAGENTA,
        )

    def llm_segment(self, turn_id: int):
        self._perf.increment(turn_id, "segment_count")

    def llm_done(self, turn_id: int, sr_done_at: float, segment_count: int):
        llm_done_at = time.time()
        self._perf.update(turn_id, llm_done_at=llm_done_at)
        log_stage(
            "LLM",
            f"turn={turn_id} completed in {fmt_ms(llm_done_at - sr_done_at)} | segments={segment_count}",
            MAGENTA,
        )

    def tts_segment_received(self, turn_id: int) -> int:
        self._perf.increment(turn_id, "received_segment_count")
        perf = self._perf.snapshot()
        return int(perf["received_segment_count"] or 0)

    def tts_first_segment_queued(self, turn_id: int, queued_at: float):
        self._perf.update(turn_id, tts_first_enqueue_at=queued_at)
        perf = self._perf.snapshot()
        log_stage(
            "TTS",
            f"turn={turn_id} first segment queued in {fmt_ms(queued_at - perf['process_started_at'])} after process",
            YELLOW,
        )

    def tts_extra_segment_queued(self, turn_id: int, segment_index: int):
        log_stage("TTS", f"turn={turn_id} queued extra segment #{segment_index}", YELLOW)

    def tts_stream_closed(self, turn_id: int):
        perf = self._perf.snapshot()
        log_stage(
            "TTS",
            f"turn={turn_id} stream closed | queued_segments={perf['received_segment_count']}",
            YELLOW,
        )

    def turn_finished_without_speech(self, turn_id: int):
        perf = self._perf.snapshot()
        log_stage(
            "TURN",
            f"turn={turn_id} finished without speech response | total={fmt_ms(time.time() - perf['process_started_at'])}",
            RED,
        )

    def maybe_log_playback_started(self, turn_id: int | None, current_tts_start: float):
        if turn_id is None:
            return
        perf = self._perf.snapshot()
        if (
            perf["turn_id"] != turn_id
            or perf["tts_first_enqueue_at"] is None
            or perf["tts_playback_started_at"] is not None
            or current_tts_start < perf["tts_first_enqueue_at"]
        ):
            return

        self._perf.update(turn_id, tts_playback_started_at=current_tts_start)
        log_stage(
            "AUDIO",
            (
                f"turn={turn_id} playback started"
                f" | enqueue->play={fmt_ms(current_tts_start - perf['tts_first_enqueue_at'])}"
                f" | process->play={fmt_ms(current_tts_start - perf['process_started_at'])}"
            ),
            GREEN,
        )

    def response_finished(self, turn_id: int | None):
        if turn_id is None:
            return
        perf = self._perf.snapshot()
        if perf["turn_id"] != turn_id:
            return

        finished_at = time.time()
        self._perf.update(turn_id, response_finished_at=finished_at)
        log_stage(
            "TURN",
            (
                f"turn={turn_id} response finished"
                f" | total={fmt_ms(finished_at - perf['process_started_at'])}"
                f" | sr={fmt_ms((perf['sr_done_at'] or finished_at) - (perf['sr_started_at'] or finished_at))}"
                f" | llm_first={fmt_ms((perf['llm_first_segment_at'] or finished_at) - (perf['sr_done_at'] or finished_at))}"
                f" | play={fmt_ms((perf['tts_playback_started_at'] or finished_at) - (perf['process_started_at'] or finished_at))}"
            ),
            GREEN,
        )

    def interrupt(self, turn_id: int | None, elapsed: float):
        if turn_id is None:
            return
        log_stage(
            "INTERRUPT",
            f"turn={turn_id} interrupted after {fmt_ms(elapsed)} of playback",
            RED,
        )
