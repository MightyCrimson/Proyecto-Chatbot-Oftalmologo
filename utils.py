import re, time, os
MAX_WORDS=int(os.getenv('MAX_WORDS','120'))
RATE_LIMIT_PER_MIN=int(os.getenv('RATE_LIMIT_PER_MIN','20'))
_BUCKETS={}

def limit_words(text,max_words=MAX_WORDS):
    words=re.findall(r'\S+', text or '')
    return text if len(words)<=max_words else ' '.join(words[:max_words])

def rate_limit(key):
    now=time.time(); window=int(now//60); b=_BUCKETS.setdefault(key,[window,0])
    if b[0]!=window: b[0]=window; b[1]=0
    if b[1]>=RATE_LIMIT_PER_MIN: return False,0
    b[1]+=1; return True, RATE_LIMIT_PER_MIN-b[1]
