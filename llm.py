import re
from collections.abc import Iterator
from typing import Callable

from openai_client import openai_client

OPENAI_MODEL = "gpt-4.1-nano"

_system = {
    "role": "system",
    "content": "You are a helpful humanoid robot made by Akinrobotics (Konya). Your name is Ada. Answer in Turkish.",
}

messages = []
SENTENCE_END_RE = re.compile(r"(.+?[.!?](?:[\"')\]]+)?)(?=\s+|$)", re.DOTALL)
PAUSE_BREAK_RE = re.compile(r"[,;:](?:[\"')\]]+)?(?=\s+|$)")
MIN_TTS_SEGMENT_CHARS = 40
TARGET_TTS_SEGMENT_CHARS = 90
MAX_TTS_SEGMENT_CHARS = 140


def _drain_completed_sentences(buffer: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    consumed = 0

    for match in SENTENCE_END_RE.finditer(buffer):
        sentence = match.group(1).strip()
        if sentence:
            sentences.append(sentence)
        consumed = match.end()

    remainder = buffer[consumed:].lstrip() if consumed else buffer
    return sentences, remainder


def _find_pause_break(text: str, max_chars: int) -> int | None:
    window = text[:max_chars]
    split_at = None

    for match in PAUSE_BREAK_RE.finditer(window):
        if match.end() >= MIN_TTS_SEGMENT_CHARS:
            split_at = match.end()

    return split_at


def _drain_partial_tts_segments(buffer: str) -> tuple[list[str], str]:
    segments: list[str] = []
    remaining = buffer

    while len(remaining.strip()) >= TARGET_TTS_SEGMENT_CHARS:
        split_at = _find_pause_break(remaining, MAX_TTS_SEGMENT_CHARS)
        if split_at is None:
            break

        segment = remaining[:split_at].strip()
        if not segment:
            break

        segments.append(segment)
        remaining = remaining[split_at:].lstrip()

    return segments, remaining


def _split_sentence_for_tts(sentence: str) -> list[str]:
    remaining = " ".join(sentence.split()).strip()
    if not remaining:
        return []

    segments: list[str] = []

    while len(remaining) > MAX_TTS_SEGMENT_CHARS:
        split_at = _find_pause_break(remaining, MAX_TTS_SEGMENT_CHARS)
        if split_at is None:
            split_at = remaining.rfind(" ", MIN_TTS_SEGMENT_CHARS, MAX_TTS_SEGMENT_CHARS)
            if split_at == -1:
                break

        segment = remaining[:split_at].strip()
        if not segment:
            break

        segments.append(segment)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        segments.append(remaining)

    return segments


def call_llm(text: str) -> str:
    global messages
    if not openai_client:
        return ""
    try:
        messages.append({"role": "user", "content": text})
        resp = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[_system, *messages],
            max_tokens=60,
        )
        messages.append(
            {"role": "assistant", "content": resp.choices[0].message.content}
        )
        messages = messages[2:] if len(messages) > 10 else messages
        print(f"messages: {messages}")
        print(f"message_len: {len(messages)}")
        return resp.choices[0].message.content or ""
    except Exception as e:
        print("ERROR LLM:", e)
        return ""


def stream_llm_sentences(
    text: str, should_continue: Callable[[], bool] | None = None
) -> Iterator[str]:
    global messages
    if not openai_client:
        return

    full_text_parts: list[str] = []
    sentence_buffer = ""
    stream = None

    try:
        messages.append({"role": "user", "content": text})
        stream = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[_system, *messages],
            max_tokens=60,
            stream=True,
        )

        for chunk in stream:
            if should_continue and not should_continue():
                return

            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue

            full_text_parts.append(delta)
            sentence_buffer += delta
            ready_partials, sentence_buffer = _drain_partial_tts_segments(sentence_buffer)

            for partial in ready_partials:
                if should_continue and not should_continue():
                    return
                yield partial

            ready_sentences, sentence_buffer = _drain_completed_sentences(sentence_buffer)

            for sentence in ready_sentences:
                if should_continue and not should_continue():
                    return
                for segment in _split_sentence_for_tts(sentence):
                    if should_continue and not should_continue():
                        return
                    yield segment

        full_text = "".join(full_text_parts).strip()
        if sentence_buffer.strip() and (not should_continue or should_continue()):
            for segment in _split_sentence_for_tts(sentence_buffer.strip()):
                if should_continue and not should_continue():
                    return
                yield segment

        if full_text and (not should_continue or should_continue()):
            messages.append({"role": "assistant", "content": full_text})
            messages = messages[2:] if len(messages) > 10 else messages
            print(f"messages: {messages}")
            print(f"message_len: {len(messages)}")
    except Exception as e:
        print("ERROR LLM:", e)
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()


def clear_messages():
    global messages
    messages = []
