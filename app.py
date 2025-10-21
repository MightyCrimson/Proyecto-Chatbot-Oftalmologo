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
from ollama_client import chat_json

load_dotenv()
app = FastAPI(title='Ophthalmology WhatsApp Chatbot — Conversational')
init_db()
DEFAULT_LANG=os.getenv('DEFAULT_LANG','es').lower()
TWILIO_AUTH_TOKEN=os.getenv('TWILIO_AUTH_TOKEN','')

def t(user,key): return (EN if (user.get('lang','es')=='en') else ES)[key]

def build_twiML(message:str):
    resp=MessagingResponse(); resp.message(message); return PlainTextResponse(str(resp), media_type='application/xml')

def twilio_ok(request:Request):
    if not TWILIO_AUTH_TOKEN: return True
    validator=RequestValidator(TWILIO_AUTH_TOKEN)
    sig=request.headers.get('X-Twilio-Signature',''); url=str(request.url); form=request._form
    return validator.validate(url, dict(form), sig)

@app.get('/healthz')
def healthz(): return {'ok':True,'ts':datetime.datetime.utcnow().isoformat()}

@app.get('/health')
def health(): return {'ok':True,'ts':datetime.datetime.utcnow().isoformat()}

@app.post('/whatsapp')
async def whatsapp(request:Request):
    form=await request.form(); request._form=form
    if not twilio_ok(request): raise HTTPException(status_code=403, detail='Invalid Twilio signature')
    from_number=form.get('From',''); body=(form.get('Body','') or '').strip(); user=get_user(from_number)

    if re.fullmatch(r'(RESET|REINICIAR|NUEVO|START)', body, flags=re.I):
        update_user(from_number, consent=0, step='start', lang=DEFAULT_LANG)
        user=get_user(from_number); msg=f"{t(user,'welcome')}\n\n{t(user,'disclaimer')}\n\n{t(user,'lang_hint')}"; return build_twiML(msg)

    if re.fullmatch(r'EN', body, flags=re.I): update_user(from_number, lang='en'); user=get_user(from_number)
    elif re.fullmatch(r'ES', body, flags=re.I): update_user(from_number, lang='es'); user=get_user(from_number)

    if user['step']=='start':
        update_user(from_number, step='consent')
        msg=f"{t(user,'welcome')}\n\n{t(user,'disclaimer')}\n\n{t(user,'lang_hint')}"; return build_twiML(msg)

    if user['step']=='consent':
        if re.search(r'^(ACEPTO|ACCEPT)$', body, flags=re.I):
            update_user(from_number, consent=1, step='chat'); user=get_user(from_number)
            return build_twiML(t(user,'accepted'))
        elif re.search(r'^(NO ACEPTO|DECLINE|NO)$', body, flags=re.I):
            return build_twiML(t(user,'not_accepted'))
        else:
            return build_twiML(t(user,'disclaimer'))

    ok,_=rate_limit(from_number)
    if not ok: return build_twiML('Has superado el límite por minuto. Intenta en unos segundos.')

    if user['step']=='schedule':
        import re as _re
        m=_re.match(r'(?P<dt>\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)\s*(?P<note>.*)', body)
        preferred=m.group('dt') if m else ''
        note=m.group('note') if m else body
        add_appointment(user['phone'], preferred=preferred, note=note[:200])
        update_user(from_number, step='chat')
        return build_twiML(t(user,'scheduled'))

    # Chat
    log_interaction(from_number, 'user', body)
    result=await make_reply(chat_json, user, body)
    reply_text=result['response']
    if result.get('suggest_schedule', False) and result.get('urgency') in ('priority','nonurgent'):
        update_user(from_number, step='schedule')
    log_interaction(from_number, 'assistant', reply_text)
    return build_twiML(reply_text)

@app.get('/', response_class=HTMLResponse)
def home(): return '<h3>Ophthalmology WhatsApp Chatbot — Conversational</h3><p>POST /whatsapp (Twilio).</p>'
