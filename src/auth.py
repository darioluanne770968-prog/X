"""用户认证模块"""

import secrets
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps

from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse

from .database import db


# Session 存储（生产环境应使用 Redis）
_sessions: dict[str, dict] = {}

SESSION_EXPIRE_HOURS = 24
SESSION_COOKIE_NAME = "session_id"


class AuthManager:
    """认证管理器"""

    def __init__(self):
        self.db = db

    def register(self, username: str, password: str, email: str = None) -> dict:
        """注册新用户"""
        # 检查用户名是否已存在
        if self.db.get_user_by_username(username):
            raise ValueError("用户名已存在")

        if len(password) < 6:
            raise ValueError("密码至少6位")

        user_id = self.db.create_user(username, password, email)

        # 创建默认配置
        self.db.save_filter_config(user_id, {
            "blocked_words": [],
            "blocked_users": [],
            "min_engagement": 0,
            "filter_ads": True,
            "filter_retweets": False
        })

        return self.db.get_user(user_id)

    def login(self, username: str, password: str) -> Optional[str]:
        """登录，返回 session_id"""
        user = self.db.authenticate_user(username, password)
        if not user:
            return None

        # 创建 session
        session_id = secrets.token_urlsafe(32)
        _sessions[session_id] = {
            "user_id": user["id"],
            "username": user["username"],
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=SESSION_EXPIRE_HOURS)
        }

        return session_id

    def logout(self, session_id: str) -> None:
        """登出"""
        if session_id in _sessions:
            del _sessions[session_id]

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取 session"""
        if session_id not in _sessions:
            return None

        session = _sessions[session_id]

        # 检查是否过期
        if datetime.now() > session["expires_at"]:
            del _sessions[session_id]
            return None

        return session

    def get_current_user(self, session_id: str) -> Optional[dict]:
        """获取当前用户"""
        session = self.get_session(session_id)
        if not session:
            return None
        return self.db.get_user(session["user_id"])

    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码"""
        user = self.db.get_user(user_id)
        if not user:
            return False

        # 验证旧密码
        if not self.db.authenticate_user(user["username"], old_password):
            return False

        if len(new_password) < 6:
            raise ValueError("密码至少6位")

        # 更新密码
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (self.db._hash_password(new_password), user_id)
            )

        return True

    def ensure_default_user(self) -> dict:
        """确保存在默认用户（用于单用户模式）"""
        default_user = self.db.get_user_by_username("admin")
        if not default_user:
            return self.register("admin", "admin123", "admin@localhost")
        return default_user


# 全局认证管理器
auth_manager = AuthManager()


# FastAPI 依赖注入
async def get_session_id(request: Request) -> Optional[str]:
    """从请求中获取 session_id"""
    return request.cookies.get(SESSION_COOKIE_NAME)


async def get_current_user(request: Request) -> Optional[dict]:
    """获取当前登录用户"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    return auth_manager.get_current_user(session_id)


async def require_auth(request: Request) -> dict:
    """要求用户登录"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def login_required(func):
    """装饰器：要求登录"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = await get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=303)
        request.state.user = user
        return await func(request, *args, **kwargs)
    return wrapper


class UserContext:
    """用户上下文，用于在请求中传递用户信息"""

    def __init__(self, user: dict = None):
        self.user = user
        self.user_id = user["id"] if user else None
        self.username = user["username"] if user else None
        self.is_authenticated = user is not None

    @property
    def settings(self) -> dict:
        """获取用户设置"""
        if not self.user:
            return {}
        import json
        return json.loads(self.user.get("settings", "{}"))
