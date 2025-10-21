import asyncio
from i18n import ES, EN
from utils import limit_words
from db import log_interaction, recent_history

SYSTEM_ES='''Eres un asistente de orientación inicial en oftalmología.\nReglas: no diagnostiques ni prescribas; detecta red flags (trauma, químico, dolor severo, pérdida súbita, flashes/cortina, muchas moscas nuevas, ojo rojo con baja visual marcada, problemas con lentes de contacto).\nDevuelve SOLO JSON: {"language":"es|en","urgency":"emergent|priority|nonurgent","response":"texto","suggest_schedule":true|false}. Responde max 120 palabras, claro y seguro.''' 
SYSTEM_EN='''You are an ophthalmology guidance assistant. No diagnoses. Detect red flags. Return ONLY JSON: {"language":"en|es","urgency":"emergent|priority|nonurgent","response":"text","suggest_schedule":true|false}. Keep replies <=120 words.''' 

def system_for(lang):
    return SYSTEM_EN if lang=='en' else SYSTEM_ES

async def make_reply(ollama_chat_fn, user, user_message:str):
    history=recent_history(user['phone'], limit=6)
    msgs=[{'role':'system','content':system_for(user.get('lang','es'))}]
    for role,content in history: msgs.append({'role':role,'content':content})
    msgs.append({'role':'user','content':user_message})
    try:
        res=await asyncio.wait_for(ollama_chat_fn(msgs, format_json=True), timeout=8.5)
    except Exception:
        lang=user.get('lang','es'); text=(ES if lang=='es' else EN)['nonurgent']+'\n\n'+(ES if lang=='es' else EN)['schedule_ask']
        return {'urgency':'nonurgent','response':limit_words(text),'language':lang,'suggest_schedule':True}
    lang=res.get('language','es'); urgency=res.get('urgency','nonurgent'); response=res.get('response',''); suggest=bool(res.get('suggest_schedule', urgency!='emergent'))
    response=limit_words(response)
    if suggest: response += '\n\n' + ((ES if lang=='es' else EN)['schedule_ask'])
    return {'urgency':urgency,'response':response,'language':lang,'suggest_schedule':suggest}
