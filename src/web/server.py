"""Web 服务器 - FastAPI 后端（支持多用户、认证、新功能）"""

import asyncio
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from collections import Counter

from fastapi import FastAPI, Request, Form, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import config
from ..twitter_client import TwitterClient, DataSourceStatus
from ..summarizer import Summarizer, SUMMARY_STYLES
from ..notifier import NotificationManager, DiscordNotifier
from ..database import db
from ..auth import auth_manager, get_current_user, SESSION_COOKIE_NAME
from ..extensions import (
    ContentFilter,
    MarkdownExporter,
    Translator,
    AccountRecommender,
)
from ..advanced import (
    AIAssistant,
    SentimentAnalyzer,
    AlertSystem,
    KnowledgeGraph,
    RSSGenerator,
    WebhookManager,
)

# 初始化 FastAPI
app = FastAPI(title="X Daily Digest", description="每日推特摘要管理界面")

# 静态文件和模板配置
static_dir = Path(__file__).parent / "static"
templates_dir = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

# 添加自定义模板过滤器
def from_json(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except:
        return []

templates.env.filters["from_json"] = from_json


# 全局状态
class AppState:
    twitter: TwitterClient = None
    summarizer: Summarizer = None
    notifier: NotificationManager = None
    filter: ContentFilter = None
    exporter: MarkdownExporter = None
    translator: Translator = None
    recommender: AccountRecommender = None

    # 高级功能
    ai_assistant: AIAssistant = None
    sentiment: SentimentAnalyzer = None
    alerts: AlertSystem = None
    graph: KnowledgeGraph = None
    rss: RSSGenerator = None
    webhooks: WebhookManager = None

    # 任务状态
    current_task: Optional[str] = None
    last_digest: Optional[str] = None
    last_digest_time: Optional[datetime] = None


state = AppState()


@app.on_event("startup")
async def startup():
    """初始化服务"""
    state.twitter = TwitterClient()
    state.summarizer = Summarizer()
    state.notifier = NotificationManager()
    state.filter = ContentFilter()
    state.exporter = MarkdownExporter()
    state.translator = Translator()
    state.recommender = AccountRecommender(state.twitter)

    # 高级功能
    state.ai_assistant = AIAssistant()
    state.sentiment = SentimentAnalyzer()
    state.alerts = AlertSystem()
    state.graph = KnowledgeGraph()
    state.rss = RSSGenerator()
    state.webhooks = WebhookManager()

    # 确保默认用户存在
    auth_manager.ensure_default_user()


# =============================================================================
# 辅助函数
# =============================================================================

def get_base_context(request: Request, page: str = ""):
    """获取基础模板上下文"""
    user = None
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        user = auth_manager.get_current_user(session_id)

    return {
        "request": request,
        "page": page,
        "user": user,
        "current_task": state.current_task,
    }


def require_login(request: Request):
    """检查登录状态"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    return auth_manager.get_current_user(session_id)


# =============================================================================
# PWA 路由
# =============================================================================

@app.get("/manifest.json")
async def manifest():
    """PWA Manifest"""
    manifest_path = static_dir / "manifest.json"
    if manifest_path.exists():
        return JSONResponse(json.loads(manifest_path.read_text()))
    return JSONResponse({})


@app.get("/sw.js")
async def service_worker():
    """Service Worker"""
    sw_path = static_dir / "sw.js"
    if sw_path.exists():
        return Response(content=sw_path.read_text(), media_type="application/javascript")
    return Response(content="", media_type="application/javascript")


@app.get("/offline.html")
async def offline():
    """离线页面"""
    offline_path = static_dir / "offline.html"
    if offline_path.exists():
        return HTMLResponse(offline_path.read_text())
    return HTMLResponse("<h1>Offline</h1>")


# =============================================================================
# 认证路由
# =============================================================================

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    """处理登录"""
    session_id = auth_manager.login(username, password)
    if not session_id:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "用户名或密码错误"
        })

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        max_age=86400,  # 24小时
        samesite="lax"
    )
    return response


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """注册页面"""
    return templates.TemplateResponse("register.html", {"request": request})


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    email: str = Form(None)
):
    """处理注册"""
    if password != password2:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "两次输入的密码不一致"
        })

    if len(username) < 3:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": "用户名至少3位"
        })

    try:
        auth_manager.register(username, password, email)
        session_id = auth_manager.login(username, password)

        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            max_age=86400,
            samesite="lax"
        )
        return response
    except ValueError as e:
        return templates.TemplateResponse("register.html", {
            "request": request,
            "error": str(e)
        })


@app.get("/logout")
async def logout(request: Request):
    """登出"""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        auth_manager.logout(session_id)

    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


# =============================================================================
# 页面路由
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """仪表盘页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]

    # 获取用户的关注列表
    following = db.get_following(user_id)
    cached_tweets = state.twitter.load_cached_tweets()
    exports = state.exporter.list_exports()[:5]
    data_source = state.twitter.get_data_source_status()

    context = get_base_context(request, "dashboard")
    context.update({
        "following_count": len(following),
        "cached_tweets_count": len(cached_tweets),
        "exports_count": len(exports),
        "last_digest": state.last_digest,
        "last_digest_time": state.last_digest_time,
        "recent_tweets": cached_tweets[:10],
        "styles": state.summarizer.get_styles(),
        "data_source": data_source,
    })

    return templates.TemplateResponse("dashboard.html", context)


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    """统计仪表盘"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]

    # 获取统计数据
    cached_tweets = state.twitter.load_cached_tweets()
    stats = db.get_stats(user_id, days=30)
    digests = db.get_digests(user_id, limit=10)

    # 计算今日推文
    today = date.today().isoformat()
    today_tweets = len([t for t in cached_tweets
                        if t.created_at.date().isoformat() == today])

    # 本周摘要数
    week_digests = len([d for d in digests
                        if d["created_at"][:10] >= (date.today().isoformat())])

    # 平均互动
    avg_engagement = 0
    if cached_tweets:
        avg_engagement = sum(t.engagement_score for t in cached_tweets) // len(cached_tweets)

    # 热门作者
    author_counts = Counter(t.author_username for t in cached_tweets)
    top_authors = [{"username": a, "count": c} for a, c in author_counts.most_common(10)]

    # 图表数据
    chart_labels = []
    chart_data = []
    for stat in reversed(stats[:30]):
        chart_labels.append(stat["date"])
        chart_data.append(stat.get("tweet_count", 0))

    # 情绪数据
    sentiment_labels = chart_labels
    sentiment_data = [stat.get("sentiment_score", 0) or 0 for stat in reversed(stats[:30])]

    context = get_base_context(request, "stats")
    context.update({
        "today_tweets": today_tweets,
        "week_digests": week_digests,
        "avg_engagement": avg_engagement,
        "sentiment_score": sentiment_data[-1] if sentiment_data else 0,
        "top_authors": top_authors,
        "top_topics": [],  # TODO: 实现话题提取
        "recent_digests": digests,
        "chart_labels": chart_labels,
        "chart_data": chart_data,
        "sentiment_labels": sentiment_labels,
        "sentiment_data": sentiment_data,
    })

    return templates.TemplateResponse("stats.html", context)


@app.get("/bookmarks", response_class=HTMLResponse)
async def bookmarks_page(request: Request, tag: str = None):
    """书签页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]
    bookmarks = db.get_bookmarks(user_id, tag)
    tags = db.get_bookmark_tags(user_id)

    context = get_base_context(request, "bookmarks")
    context.update({
        "bookmarks": bookmarks,
        "tags": tags,
        "current_tag": tag,
    })

    return templates.TemplateResponse("bookmarks.html", context)


@app.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    """定时任务页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]
    schedules = db.get_schedules(user_id)

    context = get_base_context(request, "schedules")
    context.update({
        "schedules": schedules,
        "styles": state.summarizer.get_styles(),
    })

    return templates.TemplateResponse("schedules.html", context)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]

    # 获取配置
    discord_webhooks = db.get_discord_webhooks(user_id)
    filter_config = db.get_filter_config(user_id)
    user_settings = json.loads(user.get("settings", "{}"))

    context = get_base_context(request, "settings")
    context.update({
        "discord_webhooks": discord_webhooks,
        "filter_config": filter_config,
        "telegram_enabled": config.telegram.enabled,
        "email_enabled": config.email.enabled,
        "styles": state.summarizer.get_styles(),
        "user_settings": user_settings,
    })

    return templates.TemplateResponse("settings.html", context)


@app.get("/following", response_class=HTMLResponse)
async def following_page(request: Request):
    """关注管理页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]
    following = db.get_following(user_id)

    context = get_base_context(request, "following")
    context.update({
        "following": following,
    })

    return templates.TemplateResponse("following.html", context)


@app.get("/manual-input", response_class=HTMLResponse)
async def manual_input_page(request: Request):
    """手动输入推文页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    manual_tweets = state.twitter.get_manual_tweets(hours=168)  # 最近7天
    data_source = state.twitter.get_data_source_status()

    context = get_base_context(request, "manual-input")
    context.update({
        "manual_tweets": manual_tweets,
        "data_source": data_source,
    })

    return templates.TemplateResponse("manual_input.html", context)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """AI 对话页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    cached_tweets = state.twitter.load_cached_tweets()
    state.ai_assistant.set_context(cached_tweets)

    context = get_base_context(request, "chat")
    context.update({
        "tweets_count": len(cached_tweets),
        "history": state.ai_assistant.conversation_history,
    })

    return templates.TemplateResponse("chat.html", context)


@app.get("/sentiment", response_class=HTMLResponse)
async def sentiment_page(request: Request):
    """情绪分析页面"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    cached_tweets = state.twitter.load_cached_tweets()
    market_sentiment = None
    trend = []

    if cached_tweets:
        market_sentiment = state.sentiment.analyze_market_sentiment(cached_tweets)
        trend = state.sentiment.get_sentiment_trend(cached_tweets)

    context = get_base_context(request, "sentiment")
    context.update({
        "tweets_count": len(cached_tweets),
        "sentiment": market_sentiment,
        "trend": trend,
    })

    return templates.TemplateResponse("sentiment.html", context)


# =============================================================================
# API 路由
# =============================================================================

@app.post("/api/following/add")
async def add_following(request: Request, usernames: str = Form(...)):
    """添加关注账号"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    names = [u.strip().lstrip("@") for u in usernames.split(",") if u.strip()]
    if names:
        db.add_following(user["id"], names)
    return RedirectResponse(url="/following", status_code=303)


@app.post("/api/following/remove/{username}")
async def remove_following(request: Request, username: str):
    """移除关注账号"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.remove_following(user["id"], [username])
    return RedirectResponse(url="/following", status_code=303)


@app.post("/api/digest/generate")
async def generate_digest(
    request: Request,
    background_tasks: BackgroundTasks,
    hours: int = Form(24),
    style: str = Form("default")
):
    """生成摘要（后台任务）"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = user["id"]

    def run_digest_sync():
        """同步执行摘要生成任务"""
        state.current_task = "正在生成摘要..."
        try:
            # 获取推文
            state.current_task = "正在获取推文..."
            tweets = state.twitter.get_all_following_tweets(hours=hours)

            if tweets:
                # 过滤
                state.current_task = "正在过滤内容..."
                tweets = state.filter.filter_tweets(tweets)

                # 缓存
                state.twitter.cache_tweets(tweets)
                db.cache_tweets(tweets)

                # 生成摘要
                state.current_task = "正在生成 AI 摘要..."
                digest = state.summarizer.generate_digest(tweets, style=style)

                # 保存
                state.last_digest = digest
                state.last_digest_time = datetime.now()

                # 保存到数据库
                db.save_digest(digest, len(tweets), style, user_id)

                # 导出
                state.exporter.export_digest(digest)

                # 保存每日统计
                db.save_daily_stats(
                    date.today().isoformat(),
                    user_id,
                    tweet_count=len(tweets),
                    digest_count=1
                )
            else:
                print("没有获取到任何推文")
        except Exception as e:
            print(f"摘要生成失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            state.current_task = None

    background_tasks.add_task(run_digest_sync)
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/digest/send")
async def send_digest(request: Request, background_tasks: BackgroundTasks):
    """发送摘要"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if not state.last_digest:
        return RedirectResponse(url="/", status_code=303)

    user_id = user["id"]

    async def run_send():
        state.current_task = "正在发送通知..."
        try:
            title = f"📰 每日 X 摘要 - {datetime.now().strftime('%Y-%m-%d')}"

            # 发送到默认渠道
            await state.notifier.send_all(title, state.last_digest)

            # 发送到用户的 Discord webhooks
            discord_webhooks = db.get_discord_webhooks(user_id)
            for webhook in discord_webhooks:
                if webhook["enabled"]:
                    await state.notifier.send_discord(
                        title, state.last_digest, webhook["webhook_url"]
                    )
        except Exception as e:
            print(f"发送失败: {e}")
        finally:
            state.current_task = None

    background_tasks.add_task(run_send)
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/bookmarks/add/{tweet_id}")
async def add_bookmark(
    request: Request,
    tweet_id: str,
    note: str = Form(None),
    tags: str = Form(None)
):
    """添加书签"""
    user = require_login(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    db.add_bookmark(user["id"], tweet_id, note, tag_list)
    return JSONResponse({"success": True})


@app.post("/api/bookmarks/remove/{tweet_id}")
async def remove_bookmark(request: Request, tweet_id: str):
    """移除书签"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.remove_bookmark(user["id"], tweet_id)
    return RedirectResponse(url="/bookmarks", status_code=303)


@app.post("/api/schedules/add")
async def add_schedule(
    request: Request,
    name: str = Form(...),
    action: str = Form(...),
    schedule_type: str = Form(...),
    hour: int = Form(...),
    minute: int = Form(...),
    days: list = Form(None),
    style: str = Form("default")
):
    """添加定时任务"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.add_schedule(
        user["id"], name, schedule_type, hour, minute, action,
        days=days, action_config={"style": style}
    )
    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/api/schedules/toggle/{schedule_id}")
async def toggle_schedule(request: Request, schedule_id: int):
    """切换定时任务状态"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.toggle_schedule(schedule_id)
    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/api/schedules/delete/{schedule_id}")
async def delete_schedule(request: Request, schedule_id: int):
    """删除定时任务"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.delete_schedule(schedule_id)
    return RedirectResponse(url="/schedules", status_code=303)


@app.post("/api/discord/add")
async def add_discord(
    request: Request,
    name: str = Form(...),
    webhook_url: str = Form(...)
):
    """添加 Discord webhook"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.add_discord_webhook(user["id"], name, webhook_url)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/discord/toggle/{webhook_id}")
async def toggle_discord(request: Request, webhook_id: int):
    """切换 Discord webhook 状态"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.toggle_discord_webhook(webhook_id)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/discord/delete/{webhook_id}")
async def delete_discord(request: Request, webhook_id: int):
    """删除 Discord webhook"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    db.delete_discord_webhook(webhook_id)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/discord/test/{webhook_id}")
async def test_discord(request: Request, webhook_id: int):
    """测试 Discord webhook"""
    user = require_login(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    webhooks = db.get_discord_webhooks(user["id"])
    webhook = next((w for w in webhooks if w["id"] == webhook_id), None)

    if webhook:
        notifier = DiscordNotifier(webhook["webhook_url"])
        success = await notifier.send("测试消息", "这是一条来自 X Daily Digest 的测试消息 🎉")
        return JSONResponse({"success": success})

    return JSONResponse({"error": "Webhook not found"}, status_code=404)


@app.post("/api/filter/update")
async def update_filter(
    request: Request,
    blocked_words: str = Form(""),
    blocked_users: str = Form(""),
    min_engagement: int = Form(0),
    filter_ads: bool = Form(False),
    filter_retweets: bool = Form(False)
):
    """更新过滤配置"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    filter_config = {
        "blocked_words": [w.strip() for w in blocked_words.split(",") if w.strip()],
        "blocked_users": [u.strip() for u in blocked_users.split(",") if u.strip()],
        "min_engagement": min_engagement,
        "filter_ads": filter_ads,
        "filter_retweets": filter_retweets,
    }

    db.save_filter_config(user["id"], filter_config)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/settings/digest")
async def update_digest_settings(
    request: Request,
    default_style: str = Form("default"),
    language: str = Form("zh"),
    max_tweets_per_user: int = Form(20)
):
    """更新摘要设置"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    settings = json.loads(user.get("settings", "{}"))
    settings.update({
        "default_style": default_style,
        "language": language,
        "max_tweets_per_user": max_tweets_per_user,
    })

    db.update_user_settings(user["id"], settings)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/settings/password")
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """修改密码"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if new_password != confirm_password:
        # TODO: 显示错误消息
        return RedirectResponse(url="/settings", status_code=303)

    try:
        auth_manager.change_password(user["id"], old_password, new_password)
    except ValueError:
        pass

    return RedirectResponse(url="/settings", status_code=303)


@app.post("/api/chat")
async def chat_api(request: Request, message: str = Form(...)):
    """AI 对话 API"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    response = state.ai_assistant.chat(message)
    cached_tweets = state.twitter.load_cached_tweets()

    context = get_base_context(request, "chat")
    context.update({
        "tweets_count": len(cached_tweets),
        "history": state.ai_assistant.conversation_history,
    })

    return templates.TemplateResponse("chat.html", context)


@app.post("/api/chat/clear")
async def clear_chat(request: Request):
    """清除对话历史"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    state.ai_assistant.clear_history()
    return RedirectResponse(url="/chat", status_code=303)


@app.get("/api/status")
async def get_status():
    """获取当前状态"""
    return {
        "current_task": state.current_task,
        "has_digest": state.last_digest is not None,
        "last_digest_time": state.last_digest_time.isoformat() if state.last_digest_time else None,
    }


# =============================================================================
# 手动输入推文 API
# =============================================================================

@app.post("/api/manual-tweets/add")
async def add_manual_tweet(
    request: Request,
    text: str = Form(...),
    author_username: str = Form(...),
    author_name: str = Form(""),
    url: str = Form("")
):
    """添加手动推文"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    state.twitter.add_manual_tweet(
        text=text,
        author_username=author_username.strip().lstrip("@"),
        author_name=author_name.strip() or None,
        url=url.strip() or None,
    )
    return RedirectResponse(url="/manual-input", status_code=303)


@app.post("/api/manual-tweets/batch")
async def add_manual_tweets_batch(request: Request, json_data: str = Form(...)):
    """批量添加手动推文"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        tweets_data = json.loads(json_data)
        if isinstance(tweets_data, list):
            state.twitter.add_manual_tweets_batch(tweets_data)
    except json.JSONDecodeError:
        pass  # TODO: 显示错误消息

    return RedirectResponse(url="/manual-input", status_code=303)


@app.post("/api/manual-tweets/delete/{tweet_id}")
async def delete_manual_tweet(request: Request, tweet_id: str):
    """删除手动推文"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # 从手动推文列表中删除
    manual_tweets = state.twitter._load_manual_tweets()
    manual_tweets = [t for t in manual_tweets if t.get("id") != tweet_id]
    state.twitter._save_manual_tweets(manual_tweets)

    return RedirectResponse(url="/manual-input", status_code=303)


@app.post("/api/manual-tweets/clear")
async def clear_manual_tweets(request: Request):
    """清空所有手动推文"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    state.twitter.clear_manual_tweets()
    return RedirectResponse(url="/manual-input", status_code=303)


@app.post("/api/check-nitter")
async def check_nitter_status(request: Request, background_tasks: BackgroundTasks):
    """检测 Nitter 状态"""
    user = require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async def run_check():
        state.current_task = "正在检测 Nitter 实例..."
        try:
            await state.twitter.check_nitter_status()
        finally:
            state.current_task = None

    background_tasks.add_task(lambda: asyncio.run(run_check()))
    return RedirectResponse(url="/manual-input", status_code=303)


@app.get("/api/tweets/{tweet_id}/comments")
async def get_tweet_comments(request: Request, tweet_id: str):
    """获取推文评论"""
    user = require_login(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # 先从缓存获取
    comments = db.get_comments(tweet_id)
    if not comments:
        # 从 API 获取
        comments = state.twitter.get_tweet_comments(tweet_id)
        if comments:
            db.cache_comments(tweet_id, comments)

    return JSONResponse({"comments": comments})


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """启动服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
