"""Repository for owner credentials, devices, sessions and login throttling."""

from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


class AuthRepository:
    def __init__(self, database) -> None:
        self.database = database

    def owner_exists(self) -> bool:
        with self.database.connection() as conn:
            return conn.execute("SELECT 1 FROM auth_owner WHERE id=1").fetchone() is not None

    def create_owner(self, password_hash: str) -> bool:
        now = stamp()
        with self.database.connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO auth_owner(id,password_hash,created_at,password_changed_at) VALUES(1,?,?,?)",
                (password_hash, now, now),
            )
            return cursor.rowcount == 1

    def reset_owner(self, password_hash: str) -> None:
        now = stamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM auth_owner WHERE id=1").fetchone() is None:
                raise RuntimeError("O proprietário ainda não foi cadastrado.")
            conn.execute("UPDATE auth_owner SET password_hash=?, password_changed_at=? WHERE id=1", (password_hash, now))
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,))

    def password_hash(self) -> str | None:
        with self.database.connection() as conn:
            row = conn.execute("SELECT password_hash FROM auth_owner WHERE id=1").fetchone()
            return row[0] if row else None

    def is_locked(self, now: datetime) -> bool:
        with self.database.connection() as conn:
            row = conn.execute("SELECT locked_until FROM auth_login_throttle WHERE id=1").fetchone()
            return bool(row and row[0] and datetime.fromisoformat(row[0]) > now)

    def record_login_failure(self, now: datetime) -> None:
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM auth_login_throttle WHERE id=1").fetchone()
            if row is None:
                conn.execute("INSERT INTO auth_login_throttle(id,failed_attempts,window_started_at) VALUES(1,1,?)", (stamp(now),))
                return
            start = datetime.fromisoformat(row["window_started_at"]) if row["window_started_at"] else now
            failures = row["failed_attempts"] + 1 if now - start <= timedelta(minutes=10) else 1
            level = row["lock_level"]
            locked_until = None
            if failures >= 5:
                level += 1
                locked_until = stamp(now + timedelta(seconds=min(30 * (2 ** (level - 1)), 900)))
                failures = 0
                start = now
            conn.execute(
                "UPDATE auth_login_throttle SET failed_attempts=?,window_started_at=?,lock_level=?,locked_until=? WHERE id=1",
                (failures, stamp(start), level, locked_until),
            )

    def record_login_success(self) -> None:
        with self.database.connection() as conn:
            conn.execute("DELETE FROM auth_login_throttle WHERE id=1")

    def create_session(self, device_id: str, label: str, user_agent: str, raw_token: str) -> dict:
        now = utc_now()
        session_id = str(uuid4())
        token_hash = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
        expires = now + timedelta(days=30)
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            device = conn.execute("SELECT id,revoked_at FROM auth_devices WHERE id=?", (device_id,)).fetchone()
            if device and device["revoked_at"]:
                device_id = str(uuid4())
                device = None
            if device is None:
                conn.execute(
                    "INSERT INTO auth_devices(id,label,user_agent,created_at,last_seen_at) VALUES(?,?,?,?,?)",
                    (device_id, label[:80] or "Dispositivo local", user_agent[:160], stamp(now), stamp(now)),
                )
            else:
                conn.execute("UPDATE auth_devices SET last_seen_at=?,user_agent=? WHERE id=?", (stamp(now), user_agent[:160], device_id))
            conn.execute(
                "INSERT INTO auth_sessions(id,device_id,token_hash,created_at,last_seen_at,expires_at) VALUES(?,?,?,?,?,?)",
                (session_id, device_id, token_hash, stamp(now), stamp(now), stamp(expires)),
            )
        return {"id": session_id, "device_id": device_id, "created_at": stamp(now), "expires_at": stamp(expires)}

    def get_session(self, raw_token: str) -> dict | None:
        token_hash = hashlib.sha256(raw_token.encode("ascii", "ignore")).hexdigest()
        now = utc_now()
        with self.database.connection() as conn:
            row = conn.execute(
                """SELECT s.*,d.label,d.revoked_at AS device_revoked FROM auth_sessions s
                   JOIN auth_devices d ON d.id=s.device_id WHERE s.token_hash=? AND s.revoked_at IS NULL""",
                (token_hash,),
            ).fetchone()
            if row is None or row["device_revoked"] or datetime.fromisoformat(row["expires_at"]) <= now:
                return None
            if datetime.fromisoformat(row["last_seen_at"]) + timedelta(hours=12) <= now:
                conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=?", (stamp(now), row["id"]))
                return None
            conn.execute("UPDATE auth_sessions SET last_seen_at=? WHERE id=?", (stamp(now), row["id"]))
            conn.execute("UPDATE auth_devices SET last_seen_at=? WHERE id=?", (stamp(now), row["device_id"]))
            return dict(row)

    def revoke_session(self, session_id: str, owner_device: str | None = None) -> bool:
        with self.database.connection() as conn:
            if owner_device:
                cursor = conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND device_id=? AND revoked_at IS NULL", (stamp(), session_id, owner_device))
            else:
                cursor = conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (stamp(), session_id))
            return cursor.rowcount == 1

    def revoke_device(self, device_id: str) -> bool:
        now = stamp()
        with self.database.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("UPDATE auth_devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now, device_id))
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE device_id=? AND revoked_at IS NULL", (now, device_id))
            return cursor.rowcount == 1

    def list_sessions(self) -> list[dict]:
        now = stamp()
        inactivity_cutoff = stamp(utc_now() - timedelta(hours=12))
        with self.database.connection() as conn:
            return [dict(row) for row in conn.execute(
                """SELECT s.id,s.device_id,d.label,s.created_at,s.last_seen_at,s.expires_at
                   FROM auth_sessions s JOIN auth_devices d ON d.id=s.device_id
                   WHERE s.revoked_at IS NULL AND d.revoked_at IS NULL
                     AND s.expires_at>? AND s.last_seen_at>? ORDER BY s.last_seen_at DESC""",
                (now, inactivity_cutoff),
            )]

    def revoke_token(self, raw_token: str) -> None:
        token_hash = hashlib.sha256(raw_token.encode("ascii", "ignore")).hexdigest()
        with self.database.connection() as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (stamp(), token_hash))
