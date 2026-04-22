"""数据库持久化模块 - 使用 SQLite"""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import hashlib

from .config import config


class Database:
    """SQLite 数据库管理"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or config.data_dir / "x_digest.db"
        self._init_db()

    @contextmanager
    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 用户表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    settings TEXT DEFAULT '{}'
                )
            """)

            # 关注账号表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS following (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    twitter_username TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, twitter_username)
                )
            """)

            # 推文缓存表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tweets (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    author_id TEXT NOT NULL,
                    author_username TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    like_count INTEGER DEFAULT 0,
                    retweet_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    quote_count INTEGER DEFAULT 0,
                    url TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 书签/收藏表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    tweet_id TEXT NOT NULL,
                    note TEXT,
                    tags TEXT DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (tweet_id) REFERENCES tweets(id),
                    UNIQUE(user_id, tweet_id)
                )
            """)

            # 摘要历史表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    content TEXT NOT NULL,
                    tweet_count INTEGER,
                    style TEXT DEFAULT 'default',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # 过滤配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS filter_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    blocked_words TEXT DEFAULT '[]',
                    blocked_users TEXT DEFAULT '[]',
                    min_engagement INTEGER DEFAULT 0,
                    filter_ads BOOLEAN DEFAULT 1,
                    filter_retweets BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id)
                )
            """)

            # 提醒规则表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    config TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # 定时任务配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    hour INTEGER,
                    minute INTEGER,
                    days TEXT DEFAULT '[]',
                    enabled BOOLEAN DEFAULT 1,
                    action TEXT NOT NULL,
                    action_config TEXT DEFAULT '{}',
                    last_run TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # 统计数据表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    user_id INTEGER,
                    tweet_count INTEGER DEFAULT 0,
                    digest_count INTEGER DEFAULT 0,
                    top_authors TEXT DEFAULT '[]',
                    top_topics TEXT DEFAULT '[]',
                    avg_engagement REAL DEFAULT 0,
                    sentiment_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(date, user_id)
                )
            """)

            # 推文评论表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tweet_comments (
                    id TEXT PRIMARY KEY,
                    tweet_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    author_username TEXT NOT NULL,
                    author_name TEXT NOT NULL,
                    like_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tweet_id) REFERENCES tweets(id)
                )
            """)

            # Discord webhook 配置表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discord_webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    events TEXT DEFAULT '["digest"]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tweets_author ON tweets(author_username)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets(created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_following_user ON following(user_id)")

    # =========================================================================
    # 用户管理
    # =========================================================================

    def create_user(self, username: str, password: str, email: str = None) -> int:
        """创建用户"""
        password_hash = self._hash_password(password)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                (username, password_hash, email)
            )
            return cursor.lastrowid

    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """验证用户"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1",
                (username,)
            )
            row = cursor.fetchone()
            if row and self._verify_password(password, row["password_hash"]):
                # 更新最后登录时间
                cursor.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (datetime.now(), row["id"])
                )
                return dict(row)
            return None

    def get_user(self, user_id: int) -> Optional[dict]:
        """获取用户信息"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """根据用户名获取用户"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_user_settings(self, user_id: int, settings: dict) -> None:
        """更新用户设置"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET settings = ? WHERE id = ?",
                (json.dumps(settings), user_id)
            )

    def _hash_password(self, password: str) -> str:
        """哈希密码"""
        return hashlib.sha256(password.encode()).hexdigest()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码"""
        return self._hash_password(password) == password_hash

    # =========================================================================
    # 关注管理
    # =========================================================================

    def get_following(self, user_id: int) -> list[str]:
        """获取用户的关注列表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT twitter_username FROM following WHERE user_id = ?",
                (user_id,)
            )
            return [row["twitter_username"] for row in cursor.fetchall()]

    def add_following(self, user_id: int, usernames: list[str]) -> None:
        """添加关注账号"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for username in usernames:
                cursor.execute(
                    "INSERT OR IGNORE INTO following (user_id, twitter_username) VALUES (?, ?)",
                    (user_id, username.lower())
                )

    def remove_following(self, user_id: int, usernames: list[str]) -> None:
        """移除关注账号"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for username in usernames:
                cursor.execute(
                    "DELETE FROM following WHERE user_id = ? AND twitter_username = ?",
                    (user_id, username.lower())
                )

    # =========================================================================
    # 推文管理
    # =========================================================================

    def cache_tweets(self, tweets: list) -> None:
        """缓存推文"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for tweet in tweets:
                cursor.execute("""
                    INSERT OR REPLACE INTO tweets
                    (id, text, author_id, author_username, author_name, created_at,
                     like_count, retweet_count, reply_count, quote_count, url, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tweet.id, tweet.text, tweet.author_id, tweet.author_username,
                    tweet.author_name, tweet.created_at, tweet.like_count,
                    tweet.retweet_count, tweet.reply_count, tweet.quote_count,
                    tweet.url, datetime.now()
                ))

    def get_cached_tweets(self, limit: int = 100) -> list[dict]:
        """获取缓存的推文"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tweets ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_tweet(self, tweet_id: str) -> Optional[dict]:
        """获取单条推文"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tweets WHERE id = ?", (tweet_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # =========================================================================
    # 书签管理
    # =========================================================================

    def add_bookmark(self, user_id: int, tweet_id: str, note: str = None, tags: list = None) -> int:
        """添加书签"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO bookmarks (user_id, tweet_id, note, tags) VALUES (?, ?, ?, ?)",
                (user_id, tweet_id, note, json.dumps(tags or []))
            )
            return cursor.lastrowid

    def remove_bookmark(self, user_id: int, tweet_id: str) -> None:
        """移除书签"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM bookmarks WHERE user_id = ? AND tweet_id = ?",
                (user_id, tweet_id)
            )

    def get_bookmarks(self, user_id: int, tag: str = None) -> list[dict]:
        """获取用户的书签"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if tag:
                cursor.execute("""
                    SELECT b.*, t.* FROM bookmarks b
                    JOIN tweets t ON b.tweet_id = t.id
                    WHERE b.user_id = ? AND b.tags LIKE ?
                    ORDER BY b.created_at DESC
                """, (user_id, f'%"{tag}"%'))
            else:
                cursor.execute("""
                    SELECT b.*, t.text as tweet_text, t.author_username, t.author_name,
                           t.like_count, t.retweet_count, t.url, t.created_at as tweet_created_at
                    FROM bookmarks b
                    JOIN tweets t ON b.tweet_id = t.id
                    WHERE b.user_id = ?
                    ORDER BY b.created_at DESC
                """, (user_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_bookmark_tags(self, user_id: int) -> list[str]:
        """获取用户的所有书签标签"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tags FROM bookmarks WHERE user_id = ?",
                (user_id,)
            )
            all_tags = set()
            for row in cursor.fetchall():
                tags = json.loads(row["tags"])
                all_tags.update(tags)
            return sorted(all_tags)

    # =========================================================================
    # 摘要历史
    # =========================================================================

    def save_digest(self, content: str, tweet_count: int = None,
                    style: str = "default", user_id: int = None) -> int:
        """保存摘要"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO digests (user_id, content, tweet_count, style) VALUES (?, ?, ?, ?)",
                (user_id, content, tweet_count, style)
            )
            return cursor.lastrowid

    def get_digests(self, user_id: int = None, limit: int = 10) -> list[dict]:
        """获取摘要历史"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute(
                    "SELECT * FROM digests WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit)
                )
            else:
                cursor.execute(
                    "SELECT * FROM digests ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # 过滤配置
    # =========================================================================

    def get_filter_config(self, user_id: int) -> dict:
        """获取过滤配置"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM filter_configs WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                config = dict(row)
                config["blocked_words"] = json.loads(config["blocked_words"])
                config["blocked_users"] = json.loads(config["blocked_users"])
                return config
            return {
                "blocked_words": [],
                "blocked_users": [],
                "min_engagement": 0,
                "filter_ads": True,
                "filter_retweets": False
            }

    def save_filter_config(self, user_id: int, config: dict) -> None:
        """保存过滤配置"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO filter_configs
                (user_id, blocked_words, blocked_users, min_engagement, filter_ads, filter_retweets)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                json.dumps(config.get("blocked_words", [])),
                json.dumps(config.get("blocked_users", [])),
                config.get("min_engagement", 0),
                config.get("filter_ads", True),
                config.get("filter_retweets", False)
            ))

    # =========================================================================
    # 定时任务
    # =========================================================================

    def add_schedule(self, user_id: int, name: str, schedule_type: str,
                     hour: int, minute: int, action: str,
                     days: list = None, action_config: dict = None) -> int:
        """添加定时任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO schedules
                (user_id, name, schedule_type, hour, minute, days, action, action_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id, name, schedule_type, hour, minute,
                json.dumps(days or []), action, json.dumps(action_config or {})
            ))
            return cursor.lastrowid

    def get_schedules(self, user_id: int = None) -> list[dict]:
        """获取定时任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute(
                    "SELECT * FROM schedules WHERE user_id = ? ORDER BY hour, minute",
                    (user_id,)
                )
            else:
                cursor.execute("SELECT * FROM schedules ORDER BY hour, minute")

            schedules = []
            for row in cursor.fetchall():
                schedule = dict(row)
                schedule["days"] = json.loads(schedule["days"])
                schedule["action_config"] = json.loads(schedule["action_config"])
                schedules.append(schedule)
            return schedules

    def update_schedule(self, schedule_id: int, **kwargs) -> None:
        """更新定时任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            values = []
            for key, value in kwargs.items():
                if key in ["days", "action_config"]:
                    value = json.dumps(value)
                updates.append(f"{key} = ?")
                values.append(value)
            values.append(schedule_id)
            cursor.execute(
                f"UPDATE schedules SET {', '.join(updates)} WHERE id = ?",
                values
            )

    def delete_schedule(self, schedule_id: int) -> None:
        """删除定时任务"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def toggle_schedule(self, schedule_id: int) -> None:
        """切换定时任务状态"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE schedules SET enabled = NOT enabled WHERE id = ?",
                (schedule_id,)
            )

    # =========================================================================
    # 统计数据
    # =========================================================================

    def save_daily_stats(self, date: str, user_id: int = None, **stats) -> None:
        """保存每日统计"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO statistics
                (date, user_id, tweet_count, digest_count, top_authors, top_topics,
                 avg_engagement, sentiment_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date, user_id,
                stats.get("tweet_count", 0),
                stats.get("digest_count", 0),
                json.dumps(stats.get("top_authors", [])),
                json.dumps(stats.get("top_topics", [])),
                stats.get("avg_engagement", 0),
                stats.get("sentiment_score")
            ))

    def get_stats(self, user_id: int = None, days: int = 30) -> list[dict]:
        """获取统计数据"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("""
                    SELECT * FROM statistics
                    WHERE user_id = ?
                    ORDER BY date DESC LIMIT ?
                """, (user_id, days))
            else:
                cursor.execute("""
                    SELECT * FROM statistics
                    ORDER BY date DESC LIMIT ?
                """, (days,))

            stats = []
            for row in cursor.fetchall():
                stat = dict(row)
                stat["top_authors"] = json.loads(stat["top_authors"])
                stat["top_topics"] = json.loads(stat["top_topics"])
                stats.append(stat)
            return stats

    # =========================================================================
    # 推文评论
    # =========================================================================

    def cache_comments(self, tweet_id: str, comments: list[dict]) -> None:
        """缓存推文评论"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for comment in comments:
                cursor.execute("""
                    INSERT OR REPLACE INTO tweet_comments
                    (id, tweet_id, text, author_username, author_name, like_count, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    comment["id"], tweet_id, comment["text"],
                    comment["author_username"], comment["author_name"],
                    comment.get("like_count", 0), comment["created_at"]
                ))

    def get_comments(self, tweet_id: str) -> list[dict]:
        """获取推文评论"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tweet_comments WHERE tweet_id = ? ORDER BY like_count DESC",
                (tweet_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Discord Webhook
    # =========================================================================

    def add_discord_webhook(self, user_id: int, name: str, webhook_url: str,
                            events: list = None) -> int:
        """添加 Discord webhook"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO discord_webhooks (user_id, name, webhook_url, events) VALUES (?, ?, ?, ?)",
                (user_id, name, webhook_url, json.dumps(events or ["digest"]))
            )
            return cursor.lastrowid

    def get_discord_webhooks(self, user_id: int) -> list[dict]:
        """获取 Discord webhook"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM discord_webhooks WHERE user_id = ?",
                (user_id,)
            )
            webhooks = []
            for row in cursor.fetchall():
                webhook = dict(row)
                webhook["events"] = json.loads(webhook["events"])
                webhooks.append(webhook)
            return webhooks

    def delete_discord_webhook(self, webhook_id: int) -> None:
        """删除 Discord webhook"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM discord_webhooks WHERE id = ?", (webhook_id,))

    def toggle_discord_webhook(self, webhook_id: int) -> None:
        """切换 Discord webhook 状态"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE discord_webhooks SET enabled = NOT enabled WHERE id = ?",
                (webhook_id,)
            )


# 全局数据库实例
db = Database()
