import sqlite3, json, os, threading
DB_PATH=os.path.join(os.path.dirname(__file__),'data.db')
_LOCK=threading.Lock()

def init_db():
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute('CREATE TABLE IF NOT EXISTS users (phone TEXT PRIMARY KEY, consent INTEGER DEFAULT 0, lang TEXT DEFAULT "es", step TEXT DEFAULT "start")')
        con.execute('CREATE TABLE IF NOT EXISTS interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, role TEXT, content TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        con.execute('CREATE TABLE IF NOT EXISTS appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, preferred TEXT, note TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
        con.commit()

def get_user(phone:str):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        cur=con.execute('SELECT phone,consent,lang,step FROM users WHERE phone=?',(phone,))
        row=cur.fetchone()
        if not row:
            con.execute('INSERT INTO users (phone) VALUES (?)',(phone,)); con.commit();
            return {'phone':phone,'consent':0,'lang':'es','step':'start'}
        return {'phone':row[0],'consent':int(row[1]),'lang':row[2],'step':row[3]}

def update_user(phone:str, **fields):
    keys,vals=[],[]
    for k,v in fields.items(): keys.append(f"{k}=?"); vals.append(v)
    vals.append(phone)
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute(f"UPDATE users SET {', '.join(keys)} WHERE phone=?", tuple(vals)); con.commit()

def log_interaction(phone,role,content):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute('INSERT INTO interactions (phone,role,content) VALUES (?,?,?)',(phone,role,content)); con.commit()

def recent_history(phone, limit=6):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        cur=con.execute('SELECT role,content FROM interactions WHERE phone=? ORDER BY id DESC LIMIT ?',(phone,limit));
        rows=cur.fetchall()[::-1]; return rows

def add_appointment(phone,preferred,note):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute('INSERT INTO appointments (phone,preferred,note) VALUES (?,?,?)',(phone,preferred,note)); con.commit()
