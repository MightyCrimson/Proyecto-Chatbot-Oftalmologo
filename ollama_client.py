import os, httpx, json

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")  # rápido y económico

async def chat_json(messages, format_json=True):
    if not GROQ_API_KEY:
        raise RuntimeError("Missing GROQ_API_KEY")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }
    if format_json:
        payload["response_format"] = {"type": "json_object"}

    timeout = httpx.Timeout(connect=2.0, read=7.5, write=7.5, pool=2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content) if format_json else {"text": content}
