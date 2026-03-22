from openai_client import openai_client

OPENAI_MODEL = "gpt-4.1-nano"

_system = {
    "role": "system",
    "content": "You are a helpful humanoid robot made by Akinrobotics (Konya). Your name is Ada. Answer in Turkish.",
}

messages = []


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


def clear_messages():
    global messages
    messages = []
