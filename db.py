# db.py
import sqlite3, json, os, threading

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")
_LOCK = threading.Lock()

def init_db():
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        # Usuarios: agregamos temp_name para almacenar el nombre durante el flujo de agenda
        con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            consent INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'es',
            step TEXT DEFAULT 'start',
            temp_name TEXT
        )
        """)
        # Interacciones
        con.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Citas: ahora con full_name
        con.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT,
            full_name TEXT,
            preferred TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # --- Migraciones seguras por si ya existían tablas sin las columnas nuevas ---
        cols = [r[1] for r in con.execute("PRAGMA table_info(users)")]
        if "temp_name" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN temp_name TEXT")

        cols = [r[1] for r in con.execute("PRAGMA table_info(appointments)")]
        if "full_name" not in cols:
            con.execute("ALTER TABLE appointments ADD COLUMN full_name TEXT")
        con.commit()

def get_user(phone: str):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT phone, consent, lang, step, temp_name FROM users WHERE phone=?", (phone,))
        row = cur.fetchone()
        if not row:
            con.execute("INSERT INTO users (phone) VALUES (?)", (phone,))
            con.commit()
            return {"phone": phone, "consent": 0, "lang": "es", "step": "start", "temp_name": None}
        return {"phone": row[0], "consent": int(row[1]), "lang": row[2], "step": row[3], "temp_name": row[4]}

def update_user(phone: str, **fields):
    keys, vals = [], []
    for k, v in fields.items():
        keys.append(f"{k}=?"); vals.append(v)
    vals.append(phone)
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute(f"UPDATE users SET {', '.join(keys)} WHERE phone=?", tuple(vals))
        con.commit()

def log_interaction(phone: str, role: str, content: str):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO interactions (phone, role, content) VALUES (?,?,?)", (phone, role, content))
        con.commit()

def recent_history(phone: str, limit: int = 6):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT role, content FROM interactions WHERE phone=? ORDER BY id DESC LIMIT ?", (phone, limit))
        rows = cur.fetchall()[::-1]
        return rows

def add_appointment(phone: str, full_name: str, preferred: str, note: str):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO appointments (phone, full_name, preferred, note) VALUES (?,?,?,?)",
                    (phone, full_name, preferred, note))
        con.commit()

# (opcional) listar citas para admin
def list_appointments(limit: int = 50):
    with _LOCK, sqlite3.connect(DB_PATH) as con:
        cur = con.execute("""
            SELECT id, phone, full_name, preferred, note, created_at
            FROM appointments
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return [
            {"id": r[0], "phone": r[1], "full_name": r[2], "preferred": r[3], "note": r[4], "created_at": r[5]}
            for r in cur.fetchall()
        ]
