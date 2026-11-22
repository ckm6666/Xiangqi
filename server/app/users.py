"""SQLite 用户库、密码哈希与登录令牌。

0.7.0 使用标准库 sqlite3 + PBKDF2-HMAC-SHA256：
    * 昵称唯一（大小写不敏感），排位分、战绩、头像与好友持久化；
    * 注册/登录通过 REST 完成，返回一次性 Bearer 令牌；
    * WebSocket 首帧用令牌认证，之后以账号身份加入房间/排位；
    * 好友私聊消息存入 direct_messages 表，支持历史与未读/已读；
    * 令牌保存在服务端内存，有效期 24 小时，服务端重启后需重新登录。

这套实现面向本地/局域网娱乐，不是面向公网的生产级认证系统。
"""

from __future__ import annotations

import atexit
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from xiangqi.shared.profile import (
    CUSTOM_AVATAR_ID,
    DEFAULT_AVATAR_IDS,
    MAX_AVATAR_BYTES,
    is_valid_avatar_id,
)

PBKDF2_ITERATIONS = 200_000
TOKEN_TTL_SECONDS = 24 * 3600
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
DEFAULT_RATING = 1200
DEFAULT_AVATAR = DEFAULT_AVATAR_IDS[0]

#: 账号查询列；有意排除 avatar_blob，避免每次认证/走子都读取头像大对象。
_USER_COLUMNS: tuple[str, ...] = (
    "id",
    "nickname",
    "password_hash",
    "rating",
    "created_at",
    "wins",
    "losses",
    "draws",
    "best_streak",
    "current_streak",
    "avatar",
    "best_rating",
)
_USER_SELECT = ", ".join(_USER_COLUMNS)
_USER_SELECT_JOIN = ", ".join(
    f"users.{name}" for name in _USER_COLUMNS
)


class UserStoreError(Exception):
    """用户库错误基类。"""


class ValidationError(UserStoreError):
    """昵称或密码格式不合法。"""


class NicknameTaken(UserStoreError):
    """昵称已注册。"""


class InvalidCredentials(UserStoreError):
    """昵称或密码错误。"""


class FriendNotFound(UserStoreError):
    """要添加的好友不存在。"""


class FriendAlreadyExists(UserStoreError):
    """已经是好友。"""


class FriendRequestAlreadySent(UserStoreError):
    """已经发送过好友申请。"""


class FriendRequestNotFound(UserStoreError):
    """没有待处理的好友申请。"""


@dataclass(frozen=True)
class User:
    """已认证用户及其联机战绩。"""

    id: int
    nickname: str
    rating: int
    wins: int = 0
    losses: int = 0
    draws: int = 0
    best_streak: int = 0
    current_streak: int = 0
    avatar: str = DEFAULT_AVATAR
    best_rating: int = DEFAULT_RATING


@dataclass(frozen=True)
class DirectMessage:
    """一条已持久化的好友私聊消息。"""

    id: int
    sender_id: int
    recipient_id: int
    content: str
    sent_at_ms: int
    read_at: Optional[str] = None


def validate_nickname(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("昵称无效")
    nickname = value.strip()
    if not 2 <= len(nickname) <= 20:
        raise ValidationError("昵称需为 2-20 个字符")
    if any(ord(char) < 32 for char in nickname):
        raise ValidationError("昵称不能包含控制字符")
    return nickname


def validate_password(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("密码无效")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"密码至少 {MIN_PASSWORD_LENGTH} 位"
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValidationError("密码过长")
    return value


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}"
        f"${salt.hex()}${digest.hex()}"
    )


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def default_database_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "server"
        / "data"
        / "xiangqi.db"
    )


class UserStore:
    """线程安全的 SQLite 用户库（账号、排位分、战绩、头像与好友）。"""

    _EXTRA_COLUMNS: dict[str, str] = {
        "wins": "INTEGER NOT NULL DEFAULT 0",
        "losses": "INTEGER NOT NULL DEFAULT 0",
        "draws": "INTEGER NOT NULL DEFAULT 0",
        "best_streak": "INTEGER NOT NULL DEFAULT 0",
        "current_streak": "INTEGER NOT NULL DEFAULT 0",
        "avatar": f"TEXT NOT NULL DEFAULT '{DEFAULT_AVATAR}'",
        "avatar_blob": "BLOB",
        "best_rating": f"INTEGER NOT NULL DEFAULT {DEFAULT_RATING}",
    }

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.path = Path(db_path) if db_path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._closed = False
        atexit.register(self.close)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    rating INTEGER NOT NULL DEFAULT 1200,
                    created_at TEXT NOT NULL,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    best_streak INTEGER NOT NULL DEFAULT 0,
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    avatar TEXT NOT NULL DEFAULT 'default:1',
                    avatar_blob BLOB,
                    best_rating INTEGER NOT NULL DEFAULT 1200
                )
                """
            )
            existing = {
                str(row["name"])
                for row in self._conn.execute("PRAGMA table_info(users)")
            }
            for name, definition in self._EXTRA_COLUMNS.items():
                if name not in existing:
                    self._conn.execute(
                        f"ALTER TABLE users ADD COLUMN {name} {definition}"
                    )
            # 旧库升级后，把历史最高分补齐到当前排位分。
            self._conn.execute(
                "UPDATE users SET best_rating = MAX(best_rating, rating)"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS friends (
                    user_id INTEGER NOT NULL,
                    friend_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, friend_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS friend_requests (
                    from_id INTEGER NOT NULL,
                    to_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (from_id, to_id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS direct_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    sent_at_ms INTEGER NOT NULL,
                    read_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_direct_messages_pair
                ON direct_messages (sender_id, recipient_id, id)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_direct_messages_unread
                ON direct_messages (recipient_id, read_at)
                """
            )
            self._conn.commit()

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=int(row["id"]),
            nickname=str(row["nickname"]),
            rating=int(row["rating"]),
            wins=int(row["wins"]),
            losses=int(row["losses"]),
            draws=int(row["draws"]),
            best_streak=int(row["best_streak"]),
            current_streak=int(row["current_streak"]),
            avatar=str(row["avatar"]),
            best_rating=int(row["best_rating"]),
        )

    def register(self, nickname: object, password: object) -> User:
        clean_nickname = validate_nickname(nickname)
        clean_password = validate_password(password)
        password_hash = _hash_password(clean_password)
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    INSERT INTO users
                        (nickname, password_hash, rating, created_at)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (clean_nickname, password_hash, DEFAULT_RATING),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                raise NicknameTaken("昵称已被注册") from exc
            user_id = int(cursor.lastrowid)
        return User(user_id, clean_nickname, DEFAULT_RATING)

    def login(self, nickname: object, password: object) -> User:
        if not isinstance(nickname, str) or not isinstance(password, str):
            raise InvalidCredentials("昵称或密码错误")
        clean_nickname = nickname.strip()
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_USER_SELECT} FROM users "
                "WHERE nickname = ? COLLATE NOCASE",
                (clean_nickname,),
            ).fetchone()
        if row is None or not _verify_password(
            password, str(row["password_hash"])
        ):
            raise InvalidCredentials("昵称或密码错误")
        return self._row_to_user(row)

    def get(self, user_id: int) -> Optional[User]:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_USER_SELECT} FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def find_by_nickname(self, nickname: object) -> Optional[User]:
        """按昵称（大小写不敏感）查找账号。"""
        if not isinstance(nickname, str):
            return None
        clean_nickname = nickname.strip()
        if not clean_nickname:
            return None
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_USER_SELECT} FROM users "
                "WHERE nickname = ? COLLATE NOCASE",
                (clean_nickname,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def set_rating(self, user_id: int, rating: int) -> None:
        value = max(100, int(rating))
        with self._lock:
            self._conn.execute(
                """
                UPDATE users
                SET rating = ?, best_rating = MAX(best_rating, ?)
                WHERE id = ?
                """,
                (value, value, user_id),
            )
            self._conn.commit()

    def record_result(self, user_id: int, outcome: str) -> None:
        """记录一局联机对局结果：``win`` / ``loss`` / ``draw``。"""
        if outcome not in ("win", "loss", "draw"):
            raise ValueError(f"未知对局结果：{outcome!r}")
        with self._lock:
            row = self._conn.execute(
                """
                SELECT wins, losses, draws, best_streak, current_streak
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if row is None:
                return
            wins = int(row["wins"])
            losses = int(row["losses"])
            draws = int(row["draws"])
            best = int(row["best_streak"])
            current = int(row["current_streak"])
            if outcome == "win":
                wins += 1
                current += 1
                best = max(best, current)
            elif outcome == "loss":
                losses += 1
                current = 0
            else:
                draws += 1
                current = 0
            self._conn.execute(
                """
                UPDATE users
                SET wins = ?, losses = ?, draws = ?,
                    best_streak = ?, current_streak = ?
                WHERE id = ?
                """,
                (wins, losses, draws, best, current, user_id),
            )
            self._conn.commit()

    def set_avatar(
        self,
        user_id: int,
        avatar_id: str,
        blob: Optional[bytes] = None,
    ) -> None:
        """选择默认头像或保存自定义头像 PNG。"""
        if not is_valid_avatar_id(avatar_id):
            raise ValidationError("头像标识无效")
        if avatar_id == CUSTOM_AVATAR_ID:
            if not isinstance(blob, (bytes, bytearray)) or not blob:
                raise ValidationError("请上传头像图片")
            data = bytes(blob)
            if len(data) > MAX_AVATAR_BYTES:
                raise ValidationError("头像文件不能超过 512 KB")
        else:
            data = None
        with self._lock:
            self._conn.execute(
                "UPDATE users SET avatar = ?, avatar_blob = ? WHERE id = ?",
                (avatar_id, data, user_id),
            )
            self._conn.commit()

    def get_avatar(
        self, user_id: int
    ) -> Optional[tuple[str, Optional[bytes]]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT avatar, avatar_blob FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        blob = row["avatar_blob"]
        return (
            str(row["avatar"]),
            bytes(blob) if isinstance(blob, (bytes, bytearray)) else None,
        )

    def _find_user_locked(self, nickname: object) -> Optional[User]:
        """按昵称查找（调用方必须已持有锁）。"""
        if not isinstance(nickname, str):
            return None
        clean_nickname = nickname.strip()
        if not clean_nickname:
            return None
        row = self._conn.execute(
            f"SELECT {_USER_SELECT} FROM users "
            "WHERE nickname = ? COLLATE NOCASE",
            (clean_nickname,),
        ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def _insert_friendship_locked(self, first_id: int, second_id: int) -> None:
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO friends
                (user_id, friend_id, created_at)
            VALUES (?, ?, datetime('now'))
            """,
            ((first_id, second_id), (second_id, first_id)),
        )

    def relationship(self, user_id: int, target_id: int) -> str:
        """返回 ``self`` / ``friend`` / ``pending_out`` / ``pending_in`` / ``none``。"""
        if user_id == target_id:
            return "self"
        with self._lock:
            if self._conn.execute(
                "SELECT 1 FROM friends WHERE user_id = ? AND friend_id = ?",
                (user_id, target_id),
            ).fetchone() is not None:
                return "friend"
            if self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (user_id, target_id),
            ).fetchone() is not None:
                return "pending_out"
            if self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (target_id, user_id),
            ).fetchone() is not None:
                return "pending_in"
        return "none"

    def send_friend_request(
        self, user_id: int, friend_nickname: object
    ) -> User:
        """向另一位玩家发送好友申请。

        如果对方已经先发来申请，则视为双方同意，直接成为好友。
        """
        if not isinstance(friend_nickname, str):
            raise ValidationError("昵称无效")
        if not friend_nickname.strip():
            raise ValidationError("请填写好友昵称")
        with self._lock:
            friend = self._find_user_locked(friend_nickname)
            if friend is None:
                raise FriendNotFound("没有找到该昵称的玩家")
            if friend.id == user_id:
                raise ValidationError("不能添加自己为好友")
            if self._conn.execute(
                "SELECT 1 FROM friends WHERE user_id = ? AND friend_id = ?",
                (user_id, friend.id),
            ).fetchone() is not None:
                raise FriendAlreadyExists("对方已经是你的好友")
            incoming = self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (friend.id, user_id),
            ).fetchone()
            if incoming is not None:
                self._insert_friendship_locked(user_id, friend.id)
                self._conn.execute(
                    """
                    DELETE FROM friend_requests
                    WHERE (from_id = ? AND to_id = ?)
                       OR (from_id = ? AND to_id = ?)
                    """,
                    (user_id, friend.id, friend.id, user_id),
                )
                self._conn.commit()
                return friend
            outgoing = self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (user_id, friend.id),
            ).fetchone()
            if outgoing is not None:
                raise FriendRequestAlreadySent("好友申请已发送，等待对方同意")
            self._conn.execute(
                """
                INSERT INTO friend_requests (from_id, to_id, created_at)
                VALUES (?, ?, datetime('now'))
                """,
                (user_id, friend.id),
            )
            self._conn.commit()
        return friend

    def accept_friend_request(
        self, user_id: int, requester_nickname: object
    ) -> User:
        """同意来自指定昵称玩家的好友申请。"""
        with self._lock:
            requester = self._find_user_locked(requester_nickname)
            if requester is None:
                raise FriendNotFound("没有找到该昵称的玩家")
            pending = self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (requester.id, user_id),
            ).fetchone()
            if pending is None:
                raise FriendRequestNotFound("没有待处理的好友申请")
            self._insert_friendship_locked(user_id, requester.id)
            self._conn.execute(
                """
                DELETE FROM friend_requests
                WHERE (from_id = ? AND to_id = ?)
                   OR (from_id = ? AND to_id = ?)
                """,
                (user_id, requester.id, requester.id, user_id),
            )
            self._conn.commit()
        return requester

    def decline_friend_request(
        self, user_id: int, requester_nickname: object
    ) -> None:
        with self._lock:
            requester = self._find_user_locked(requester_nickname)
            if requester is None:
                raise FriendNotFound("没有找到该昵称的玩家")
            pending = self._conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE from_id = ? AND to_id = ?
                """,
                (requester.id, user_id),
            ).fetchone()
            if pending is None:
                raise FriendRequestNotFound("没有待处理的好友申请")
            self._conn.execute(
                """
                DELETE FROM friend_requests
                WHERE (from_id = ? AND to_id = ?)
                   OR (from_id = ? AND to_id = ?)
                """,
                (user_id, requester.id, requester.id, user_id),
            )
            self._conn.commit()

    def list_friends(self, user_id: int) -> tuple[User, ...]:
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {_USER_SELECT_JOIN} FROM friends
                JOIN users ON users.id = friends.friend_id
                WHERE friends.user_id = ?
                ORDER BY users.nickname COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        return tuple(self._row_to_user(row) for row in rows)

    def list_friend_requests(
        self, user_id: int
    ) -> tuple[tuple[User, ...], tuple[User, ...]]:
        """返回 ``(incoming, outgoing)`` 好友申请人列表。"""
        with self._lock:
            incoming_rows = self._conn.execute(
                f"""
                SELECT {_USER_SELECT_JOIN} FROM friend_requests
                JOIN users ON users.id = friend_requests.from_id
                WHERE friend_requests.to_id = ?
                ORDER BY friend_requests.created_at
                """,
                (user_id,),
            ).fetchall()
            outgoing_rows = self._conn.execute(
                f"""
                SELECT {_USER_SELECT_JOIN} FROM friend_requests
                JOIN users ON users.id = friend_requests.to_id
                WHERE friend_requests.from_id = ?
                ORDER BY friend_requests.created_at
                """,
                (user_id,),
            ).fetchall()
        return (
            tuple(self._row_to_user(row) for row in incoming_rows),
            tuple(self._row_to_user(row) for row in outgoing_rows),
        )

    @staticmethod
    def _row_to_direct_message(row: sqlite3.Row) -> DirectMessage:
        return DirectMessage(
            id=int(row["id"]),
            sender_id=int(row["sender_id"]),
            recipient_id=int(row["recipient_id"]),
            content=str(row["content"]),
            sent_at_ms=int(row["sent_at_ms"]),
            read_at=(
                str(row["read_at"])
                if row["read_at"] is not None
                else None
            ),
        )

    def create_direct_message(
        self,
        sender_id: int,
        recipient_id: int,
        content: str,
        sent_at_ms: int,
    ) -> DirectMessage:
        """保存一条好友私聊并返回带 id 的记录。"""
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO direct_messages
                    (sender_id, recipient_id, content, sent_at_ms)
                VALUES (?, ?, ?, ?)
                """,
                (sender_id, recipient_id, content, int(sent_at_ms)),
            )
            self._conn.commit()
            row = self._conn.execute(
                """
                SELECT id, sender_id, recipient_id, content,
                       sent_at_ms, read_at
                FROM direct_messages WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:  # pragma: no cover - 插入后立即查询不应失败
            raise UserStoreError("私聊保存失败")
        return self._row_to_direct_message(row)

    def list_direct_messages(
        self,
        user_id: int,
        other_id: int,
        limit: int = 50,
    ) -> tuple[DirectMessage, ...]:
        """返回两人最近的私聊，按时间从早到晚排列。"""
        count = max(1, min(200, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, sender_id, recipient_id, content,
                       sent_at_ms, read_at
                FROM direct_messages
                WHERE (sender_id = ? AND recipient_id = ?)
                   OR (sender_id = ? AND recipient_id = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, other_id, other_id, user_id, count),
            ).fetchall()
        return tuple(
            self._row_to_direct_message(row)
            for row in reversed(rows)
        )

    def mark_direct_messages_read(
        self,
        user_id: int,
        sender_id: int,
        message_ids: list[int],
    ) -> int:
        """把发给 ``user_id`` 的指定消息标记为已读。"""
        ids = [int(item) for item in message_ids if int(item) > 0]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self._lock:
            cursor = self._conn.execute(
                f"""
                UPDATE direct_messages
                SET read_at = datetime('now')
                WHERE recipient_id = ?
                  AND sender_id = ?
                  AND read_at IS NULL
                  AND id IN ({placeholders})
                """,
                (user_id, sender_id, *ids),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def unread_counts(self, user_id: int) -> dict[int, int]:
        """按发送者统计某用户收到的未读私聊数量。"""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT sender_id, COUNT(*) AS total
                FROM direct_messages
                WHERE recipient_id = ? AND read_at IS NULL
                GROUP BY sender_id
                """,
                (user_id,),
            ).fetchall()
        return {
            int(row["sender_id"]): int(row["total"])
            for row in rows
        }

    def search_users(
        self,
        query: str,
        *,
        limit: int = 20,
        exclude_id: Optional[int] = None,
    ) -> tuple[User, ...]:
        """按昵称模糊搜索玩家，精确匹配优先。"""
        if not isinstance(query, str):
            return ()
        clean = query.strip()
        if not clean:
            return ()
        escaped = (
            clean.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        count = max(1, min(50, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {_USER_SELECT} FROM users
                WHERE nickname LIKE ? ESCAPE '\\'
                  AND (? IS NULL OR id != ?)
                ORDER BY
                  CASE WHEN nickname = ? COLLATE NOCASE THEN 0 ELSE 1 END,
                  rating DESC,
                  nickname COLLATE NOCASE
                LIMIT ?
                """,
                (
                    pattern,
                    exclude_id,
                    exclude_id,
                    clean,
                    count,
                ),
            ).fetchall()
        return tuple(self._row_to_user(row) for row in rows)

    def leaderboard(self, limit: int = 50) -> tuple[User, ...]:
        """按积分降序返回榜单；收录所有已登录（注册）账号。

        新账号即使还没有完成过联机对局，也会以初始积分出现在榜单中。
        """
        count = max(1, min(1000, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT {_USER_SELECT} FROM users
                ORDER BY rating DESC, nickname COLLATE NOCASE
                LIMIT ?
                """,
                (count,),
            ).fetchall()
        return tuple(self._row_to_user(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()


class AuthManager:
    """登录令牌管理（内存，24 小时有效）。"""

    def __init__(self, users: UserStore) -> None:
        self.users = users
        self._tokens: dict[str, tuple[int, float]] = {}

    def issue(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = (
            user.id,
            time.monotonic() + TOKEN_TTL_SECONDS,
        )
        return token

    def resolve(self, token: object) -> Optional[User]:
        if not isinstance(token, str) or not token:
            return None
        entry = self._tokens.get(token)
        if entry is None:
            return None
        user_id, expires_at = entry
        if time.monotonic() >= expires_at:
            self._tokens.pop(token, None)
            return None
        return self.users.get(user_id)

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)


__all__ = [
    "User",
    "DirectMessage",
    "UserStore",
    "UserStoreError",
    "ValidationError",
    "NicknameTaken",
    "InvalidCredentials",
    "FriendNotFound",
    "FriendAlreadyExists",
    "FriendRequestAlreadySent",
    "FriendRequestNotFound",
    "AuthManager",
    "validate_nickname",
    "validate_password",
    "default_database_path",
    "DEFAULT_RATING",
    "DEFAULT_AVATAR",
    "CUSTOM_AVATAR_ID",
    "MAX_AVATAR_BYTES",
    "DEFAULT_AVATAR_IDS",
]
