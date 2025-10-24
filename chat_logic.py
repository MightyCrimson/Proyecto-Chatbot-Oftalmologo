import asyncio
from i18n import ES, EN
from utils import limit_words
from db import recent_history

SYSTEM_ES = """Eres un asistente de orientación inicial en oftalmología.
Reglas: no diagnostiques ni prescribas; detecta red flags (trauma, químico, dolor severo,
pérdida súbita, flashes/cortina, muchas moscas nuevas, ojo rojo con baja visual marcada,
problemas con lentes de contacto). Responde en ≤120 palabras, claro y sin diagnósticos.
NO ofrezcas agendar citas a menos que el usuario lo pida explícitamente y RECHAZA temas fuera de oftalmología con un breve recordatorio del alcance.
Devuelve SOLO JSON: {"language":"es|en","urgency":"emergent|priority|nonurgent","response":"...","suggest_schedule":false}
"""

SYSTEM_EN = """You are an ophthalmology guidance assistant. No diagnosis/prescribing.
Detect red flags (trauma, chemical, severe pain, sudden vision loss, flashes/curtain,
many new floaters, marked red eye with vision drop, contact-lens issues).
Replies ≤120 words, plain language. Do NOT offer to schedule unless the user asks and REJECTS topics outside of ophthalmology with a brief reminder of the scope.
Return JSON ONLY: {"language":"en|es","urgency":"emergent|priority|nonurgent","response":"...","suggest_schedule":false}
"""

def system_for(lang: str) -> str:
    return SYSTEM_EN if lang == "en" else SYSTEM_ES

async def make_reply(chat_fn, user, user_message: str):
    # contexto breve
    history = recent_history(user["phone"], limit=6)
    msgs = [{"role": "system", "content": system_for(user.get("lang", "es"))}]
    for role, content in history:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": user_message})

    try:
        res = await asyncio.wait_for(chat_fn(msgs, format_json=True), timeout=8.5)
    except Exception:
        lang = user.get("lang", "es")
        text = (ES if lang == "es" else EN)["nonurgent"]
        return {"urgency": "nonurgent", "response": limit_words(text), "language": lang, "suggest_schedule": False}

    lang = (res or {}).get("language", user.get("lang", "es"))
    urgency = (res or {}).get("urgency", "nonurgent")
    response = limit_words((res or {}).get("response", ""))

    # Nunca activar agenda desde aquí
    return {"urgency": urgency, "response": response, "language": lang, "suggest_schedule": False}
