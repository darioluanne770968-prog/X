"""Web 服务器 - FastAPI 后端"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import config
from ..twitter_client import TwitterClient
from ..summarizer import Summarizer
from ..notifier import NotificationManager
from ..extensions import (
    ContentFilter,
    MarkdownExporter,
    Translator,
    AccountRecommender,
)

# 初始化 FastAPI
app = FastAPI(title="X Daily Digest", description="每日推特摘要管理界面")

# 模板配置
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# 全局状态
class AppState:
    twitter: TwitterClient = None
    summarizer: Summarizer = None
    notifier: NotificationManager = None
    filter: ContentFilter = None
    exporter: MarkdownExporter = None
    translator: Translator = None
    recommender: AccountRecommender = None

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


# =============================================================================
# 页面路由
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """仪表盘页面"""
    following = state.twitter.get_following_list()
    cached_tweets = state.twitter.load_cached_tweets()
    exports = state.exporter.list_exports()[:5]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "dashboard",
        "following_count": len(following),
        "cached_tweets_count": len(cached_tweets),
        "exports_count": len(exports),
        "last_digest": state.last_digest,
        "last_digest_time": state.last_digest_time,
        "current_task": state.current_task,
        "recent_tweets": cached_tweets[:10],
    })


@app.get("/following", response_class=HTMLResponse)
async def following_page(request: Request):
    """关注管理页面"""
    following = state.twitter.get_following_list()

    return templates.TemplateResponse("following.html", {
        "request": request,
        "page": "following",
        "following": following,
    })


@app.get("/filter", response_class=HTMLResponse)
async def filter_page(request: Request):
    """过滤器管理页面"""
    filter_config = state.filter.filter_config

    return templates.TemplateResponse("filter.html", {
        "request": request,
        "page": "filter",
        "blocked_words": filter_config.blocked_words,
        "blocked_users": filter_config.blocked_users,
        "min_engagement": filter_config.min_engagement,
        "filter_ads": filter_config.filter_ads,
        "filter_retweets": filter_config.filter_retweets,
    })


@app.get("/exports", response_class=HTMLResponse)
async def exports_page(request: Request):
    """导出文件页面"""
    exports = state.exporter.list_exports()

    export_list = []
    for path in exports[:50]:
        stat = path.stat()
        export_list.append({
            "name": path.name,
            "size": f"{stat.st_size / 1024:.1f} KB",
            "time": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "path": str(path),
        })

    return templates.TemplateResponse("exports.html", {
        "request": request,
        "page": "exports",
        "exports": export_list,
    })


@app.get("/recommend", response_class=HTMLResponse)
async def recommend_page(request: Request):
    """账号推荐页面"""
    return templates.TemplateResponse("recommend.html", {
        "request": request,
        "page": "recommend",
        "accounts": [],
        "analysis": None,
    })


# =============================================================================
# API 路由
# =============================================================================

@app.post("/api/following/add")
async def add_following(usernames: str = Form(...)):
    """添加关注账号"""
    names = [u.strip().lstrip("@") for u in usernames.split(",") if u.strip()]
    if names:
        state.twitter.add_following(names)
    return RedirectResponse(url="/following", status_code=303)


@app.post("/api/following/remove/{username}")
async def remove_following(username: str):
    """移除关注账号"""
    state.twitter.remove_following([username])
    return RedirectResponse(url="/following", status_code=303)


@app.post("/api/filter/words/add")
async def add_blocked_words(words: str = Form(...)):
    """添加屏蔽词"""
    word_list = [w.strip() for w in words.split(",") if w.strip()]
    if word_list:
        state.filter.add_blocked_words(word_list)
    return RedirectResponse(url="/filter", status_code=303)


@app.post("/api/filter/words/remove/{word}")
async def remove_blocked_word(word: str):
    """移除屏蔽词"""
    state.filter.remove_blocked_words([word])
    return RedirectResponse(url="/filter", status_code=303)


@app.post("/api/filter/users/add")
async def add_blocked_users(users: str = Form(...)):
    """添加屏蔽用户"""
    user_list = [u.strip().lstrip("@") for u in users.split(",") if u.strip()]
    if user_list:
        state.filter.add_blocked_users(user_list)
    return RedirectResponse(url="/filter", status_code=303)


@app.post("/api/digest/generate")
async def generate_digest(background_tasks: BackgroundTasks, hours: int = Form(24)):
    """生成摘要（后台任务）"""
    async def run_digest():
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

                # 生成摘要
                state.current_task = "正在生成 AI 摘要..."
                digest = state.summarizer.generate_digest(tweets)

                # 保存
                state.last_digest = digest
                state.last_digest_time = datetime.now()

                # 导出
                state.exporter.export_digest(digest)
        finally:
            state.current_task = None

    background_tasks.add_task(lambda: asyncio.run(run_digest()))
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/digest/send")
async def send_digest(background_tasks: BackgroundTasks):
    """发送摘要"""
    if not state.last_digest:
        return RedirectResponse(url="/", status_code=303)

    async def run_send():
        state.current_task = "正在发送通知..."
        try:
            title = f"📰 每日 X 摘要 - {datetime.now().strftime('%Y-%m-%d')}"
            await state.notifier.send_all(title, state.last_digest)
        finally:
            state.current_task = None

    background_tasks.add_task(lambda: asyncio.run(run_send()))
    return RedirectResponse(url="/", status_code=303)


@app.post("/api/recommend/discover")
async def discover_accounts(request: Request, username: str = Form(None)):
    """发现推荐账号"""
    if username:
        accounts = state.recommender.get_similar_accounts(username.lstrip("@"))
    else:
        accounts = state.recommender.discover_from_following()

    analysis = None
    if accounts:
        analysis = state.recommender.analyze_accounts(accounts)

    return templates.TemplateResponse("recommend.html", {
        "request": request,
        "page": "recommend",
        "accounts": accounts,
        "analysis": analysis,
        "search_username": username,
    })


@app.get("/api/export/{filename}")
async def view_export(request: Request, filename: str):
    """查看导出文件内容"""
    filepath = state.exporter.export_dir / filename

    if not filepath.exists():
        return RedirectResponse(url="/exports", status_code=303)

    content = filepath.read_text(encoding="utf-8")

    return templates.TemplateResponse("export_view.html", {
        "request": request,
        "page": "exports",
        "filename": filename,
        "content": content,
    })


@app.get("/api/status")
async def get_status():
    """获取当前状态"""
    return {
        "current_task": state.current_task,
        "has_digest": state.last_digest is not None,
        "last_digest_time": state.last_digest_time.isoformat() if state.last_digest_time else None,
    }


def run_server(host: str = "127.0.0.1", port: int = 8000):
    """启动服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
