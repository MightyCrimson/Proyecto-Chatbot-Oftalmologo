import os, re, datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse
from dotenv import load_dotenv
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from db import init_db, get_user, update_user, log_interaction, add_appointment
from utils import rate_limit
from i18n import ES, EN
from chat_logic import make_reply
from ollama_client import chat_json  # ahora usa Groq por debajo

load_dotenv()
app = FastAPI(title="Ophthalmology WhatsApp Chatbot — Conversational")
init_db()

DEFAULT_LANG = os.getenv("DEFAULT_LANG", "es").lower()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

def t(user, key):
    return (EN if (user.get("lang", "es") == "en") else ES)[key]

def build_twiML(message: str) -> PlainTextResponse:
    resp = MessagingResponse()
    resp.message(message)
    return PlainTextResponse(str(resp), media_type="application/xml")

def twilio_ok(request: Request):
    # Bypass en desarrollo si no hay token
    if not TWILIO_AUTH_TOKEN:
        return True
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    sig = request.headers.get("X-Twilio-Signature", "")
    url = str(request.url)
    form = request._form
    return validator.validate(url, dict(form), sig)

@app.get("/healthz")
def healthz():
    return {"ok": True, "ts": datetime.datetime.utcnow().isoformat()}

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.datetime.utcnow().isoformat()}
    
@app.get("/groq-test")
async def groq_test():
    msgs = [
        {"role": "system", "content": 'Return JSON only: {"ok": true}.'},
        {"role": "user", "content": 'Give me {"pong": true} as JSON only.'}
    ]
    try:
        res = await chat_json(msgs, format_json=True)
        return {"ok": True, "groq": res}
    except Exception as e:
        # no exponemos secretos; solo el mensaje de error
        return {"ok": False, "error": str(e)}
        
@app.post("/whatsapp")
async def whatsapp(request: Request):
    form = await request.form()
    request._form = form
    if not twilio_ok(request):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    from_number = form.get("From", "")
    body = (form.get("Body", "") or "").strip()
    user = get_user(from_number)

    # ---- Comandos globales ----
    if re.fullmatch(r"(RESET|REINICIAR|NUEVO|START)", body, flags=re.I):
        update_user(from_number, consent=0, step="start", lang=DEFAULT_LANG)
        user = get_user(from_number)
        msg = f"{t(user,'welcome')}\n\n{t(user,'disclaimer')}\n\n{t(user,'lang_hint')}"
        return build_twiML(msg)

    if re.fullmatch(r"EN", body, flags=re.I):
        update_user(from_number, lang="en"); user = get_user(from_number)
    elif re.fullmatch(r"ES", body, flags=re.I):
        update_user(from_number, lang="es"); user = get_user(from_number)

    # ---- Inicio / consentimiento ----
    if user["step"] == "start":
        update_user(from_number, step="consent")
        msg = f"{t(user,'welcome')}\n\n{t(user,'disclaimer')}\n\n{t(user,'lang_hint')}"
        return build_twiML(msg)

    if user["step"] == "consent":
        if re.search(r"^(ACEPTO|ACCEPT)$", body, flags=re.I):
            update_user(from_number, consent=1, step="chat")
            user = get_user(from_number)
            return build_twiML(t(user, "accepted"))
        elif re.search(r"^(NO ACEPTO|DECLINE|NO)$", body, flags=re.I):
            return build_twiML(t(user, "not_accepted"))
        else:
            return build_twiML(t(user, "disclaimer"))

    # ---- Rate limit ----
    ok, _ = rate_limit(from_number)
    if not ok:
        return build_twiML("Has superado el límite de mensajes por minuto. Intenta en unos segundos.")

    # ---- Hotfix A: NO cambiar a schedule automático ----
    # Detección de intención de agendar ANTES de llamar a la IA
    if re.search(r"\b(cita|agendar|agenda|appointment|schedule)\b", body, flags=re.I):
        update_user(from_number, step="schedule")
        return build_twiML(t(user, "schedule_ask"))

    # ---- Estado schedule (solo si el usuario lo pidió) ----
    if user["step"] == "schedule":
        # Usuario no quiere agendar ahora -> volver a chat
        if re.search(r"\b(no|no gracias|luego|despues|más tarde|mas tarde|no quiero)\b", body, flags=re.I):
            update_user(from_number, step="chat")
            return build_twiML("Sin problema. Cuéntame tus síntomas y te orientaré.")

        # Si vuelve a pedir cita sin fecha, recuerda el formato
        if re.search(r"\b(cita|agendar|appointment|schedule)\b", body, flags=re.I):
            return build_twiML(t(user, "schedule_ask"))

        # Formato fecha/hora simple
        m = re.match(r"(?P<dt>\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)\s*(?P<note>.*)", body)
        if m:
            preferred = m.group("dt")
            note = (m.group("note") or "")[:200]
            add_appointment(user["phone"], preferred=preferred, note=note)
            update_user(from_number, step="chat")
            return build_twiML(t(user, "scheduled"))

        # Si no reconoce fecha, sigue conversando con IA
        log_interaction(from_number, "user", body)
        result = await make_reply(chat_json, user, body)
        reply_text = result["response"]
        log_interaction(from_number, "assistant", reply_text)
        return build_twiML(reply_text)

    # ---- Chat conversacional (IA) ----
    log_interaction(from_number, "user", body)
    result = await make_reply(chat_json, user, body)
    reply_text = result["response"]

    # Hotfix A: NO cambiar a schedule por la respuesta de la IA
    # (antes aquí había un update_user(..., step="schedule") automático)

    log_interaction(from_number, "assistant", reply_text)
    return build_twiML(reply_text)

@app.get("/", response_class=HTMLResponse)
def home():
    return "<h3>Ophthalmology WhatsApp Chatbot — Conversational</h3><p>POST /whatsapp (Twilio).</p>"
