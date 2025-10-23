import os, re, datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse, JSONResponse
from dotenv import load_dotenv
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from db import (
    init_db, get_user, update_user, log_interaction,
    add_appointment, list_appointments
)
from utils import rate_limit
from i18n import ES, EN
from chat_logic import make_reply
from ollama_client import chat_json  # usa Groq por debajo si cambiaste el cliente

load_dotenv()
app = FastAPI(title="Ophthalmology WhatsApp Chatbot — Conversational")
init_db()

DEFAULT_LANG = os.getenv("DEFAULT_LANG", "es").lower()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
ADMIN_SECRET = os.getenv("APPOINTMENTS_SECRET", "")
ADMIN_WHATSAPP = os.getenv("ADMIN_WHATSAPP", "")

def t(user, key):
    return (EN if (user.get("lang", "es") == "en") else ES)[key]

def t_fallback(user, key, default_text):
    try:
        return t(user, key)
    except KeyError:
        return default_text

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
        return {"ok": False, "error": str(e)}

@app.get("/admin/appointments")
def admin_appointments(secret: str = ""):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return JSONResponse({"appointments": list_appointments(100)})

@app.post("/whatsapp")
async def whatsapp(request: Request):
    form = await request.form()
    request._form = form
    if not twilio_ok(request):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    from_number = form.get("From", "")
    body = (form.get("Body", "") or "").strip()
    user = get_user(from_number)

    # --- ACEPTAR en cualquier estado (respuesta inmediata) ---
    if re.fullmatch(r"(ACEPTO|ACCEPT)", body, flags=re.I):
        update_user(from_number, consent=1, step="chat")
        user = get_user(from_number)
        log_interaction(from_number, "assistant", "[accepted_any_state]")
        return build_twiML(t(user, "accepted"))
    # ---------------------------------------------------------

    # --- Admin por WhatsApp: lista de citas (solo tu número) ---
    if from_number == ADMIN_WHATSAPP and re.fullmatch(r"(LISTA\s+CITAS|CITAS)", body, flags=re.I):
        items = list_appointments(10)
        if not items:
            return build_twiML("No hay citas registradas.")
        lines = [
            f"#{it.get('id')} {it.get('preferred') or '(sin fecha)'} – {it.get('full_name') or 'N/D'} – "
            f"{it.get('phone')} – {(it.get('note') or '')[:40]}"
            for it in items
        ]
        return build_twiML("Últimas citas:\n" + "\n".join(lines))
    # ------------------------------------------------------------

    # ---- Comandos globales ----
    if re.fullmatch(r"(RESET|REINICIAR|NUEVO|START)", body, flags=re.I):
        update_user(from_number, consent=0, step="start", lang=DEFAULT_LANG, temp_name=None)
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

    # =========================
    # AGENDA SOLO A PEDIDO
    # =========================

    # 0) Disparador explícito de agenda -> Paso 1: nombre y apellido
    if re.search(r"\b(cita|agendar|agenda|appointment|schedule)\b", body, flags=re.I):
        update_user(from_number, step="schedule_name", temp_name=None)
        msg_name = t_fallback(
            user,
            "schedule_ask",
            "Perfecto, para agendar necesito primero tu *nombre y apellido*. "
            "Escríbelos tal como figuran en tu documento."
        )
        return build_twiML(msg_name)

    # 1) Paso 1: capturar nombre y apellido
    if user["step"] == "schedule_name":
        name = body.strip()
        # Validación simple: al menos 2 palabras
        if len(name.split()) < 2 or len(name) < 3:
            return build_twiML("Por favor envía *nombre y apellido* (ej. Ana Pérez).")
        update_user(from_number, temp_name=name, step="schedule_datetime")
        msg_dt = t_fallback(
            user,
            "schedule_ask_datetime",
            "Gracias. Ahora indícame *fecha y hora* (ej. 2025-11-05 15:30) y una *nota breve* (motivo)."
        )
        return build_twiML(msg_dt)

    # 2) Paso 2: capturar fecha/hora + nota y guardar cita
    if user["step"] == "schedule_datetime":
        # Permitir cancelar (no agendar)
        if re.search(r"\b(no|no gracias|luego|despues|más tarde|mas tarde|no quiero)\b", body, flags=re.I):
            update_user(from_number, temp_name=None, step="chat")
            return build_twiML("Sin problema. Cuéntame tus síntomas y te orientaré.")

        import re as _re
        m = _re.match(r"(?P<dt>\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)\s*(?P<note>.*)", body)
        if not m:
            return build_twiML("Formato no reconocido. Ejemplo: 2025-11-05 15:30 dolor ocular desde ayer.")

        preferred = m.group("dt")
        note = (m.group("note") or "")[:200]

        # Recuperar el nombre capturado en el paso 1
        u = get_user(from_number)
        full_name = u.get("temp_name") or ""

        # Guardar cita (soporta firmas vieja/nueva)
        try:
            # Nueva firma: add_appointment(phone, full_name, preferred, note)
            add_appointment(u["phone"], full_name=full_name, preferred=preferred, note=note)
        except TypeError:
            # Vieja firma: add_appointment(phone, preferred, note) -> inyecta el nombre en la nota
            combo_note = (full_name + " — " + note) if full_name else note
            add_appointment(u["phone"], preferred=preferred, note=combo_note)

        update_user(from_number, temp_name=None, step="chat")
        return build_twiML(t(u, "scheduled"))

    # =========================
    # CHAT CONVERSACIONAL (IA)
    # =========================
    log_interaction(from_number, "user", body)
    result = await make_reply(chat_json, user, body)
    reply_text = result["response"]

    # No pasar a 'schedule' automáticamente (solo a pedido)
    log_interaction(from_number, "assistant", reply_text)
    return build_twiML(reply_text)

@app.get("/", response_class=HTMLResponse)
def home():
    return "<h3>Ophthalmology WhatsApp Chatbot — Conversational</h3><p>POST /whatsapp (Twilio).</p>"
