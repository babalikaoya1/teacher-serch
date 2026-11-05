"""设备凭证使用 Windows DPAPI；队列按绑定设备分开保存。"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta


def data_home():
    path = Path(os.getenv("TEACHER_HELPER_HOME", str(Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "TeacherSearchSync")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_binding(binding):
    import win32crypt
    encrypted = win32crypt.CryptProtectData(json.dumps(binding).encode(), "家教同步设备凭证", None, None, None, 0)
    path = data_home() / "binding.bin"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)


def load_binding():
    import win32crypt
    path = data_home() / "binding.bin"
    if not path.exists():
        return None
    try:
        return json.loads(win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1])
    except Exception:
        raise RuntimeError("保存的设备凭证无法解密，请重新配对")


class Outbox:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (source TEXT, key TEXT, payload TEXT, sent INTEGER DEFAULT 0, created TEXT, PRIMARY KEY(source,key))")
        self.db.execute("CREATE TABLE IF NOT EXISTS checkpoints (source TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.commit()

    def remember(self, source, messages):
        """消息分钟、发送人、正文和同分钟重复次数组成可重复计算的指纹。"""
        counts = {}
        for message in messages:
            base = json.dumps([message.get("sent_at"), message.get("sender"), message["text"]], ensure_ascii=False)
            occurrence = counts.get(base, 0)
            counts[base] = occurrence + 1
            key = hashlib.sha256(f"{base}:{occurrence}".encode()).hexdigest()
            event = {**message, "message_key": key}
            self.db.execute("INSERT OR IGNORE INTO outbox(source,key,payload,created) VALUES(?,?,?,?)",
                (source, key, json.dumps(event, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def batch(self, source):
        rows = self.db.execute("SELECT payload FROM outbox WHERE source=? AND sent=0 ORDER BY rowid LIMIT 100", (source,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def acknowledge(self, source, messages):
        self.db.executemany("UPDATE outbox SET sent=1,payload='' WHERE source=? AND key=?", [(source, message["message_key"]) for message in messages])
        self.db.execute("DELETE FROM outbox WHERE created<?", ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),))
        self.db.commit()

    def close(self):
        self.db.close()

    def checkpoint(self, source):
        row = self.db.execute("SELECT value FROM checkpoints WHERE source=?", (source,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_checkpoint(self, source, value):
        self.db.execute("INSERT INTO checkpoints(source,value) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET value=excluded.value", (source, json.dumps(value)))
        self.db.commit()
