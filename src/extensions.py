"""扩展功能模块 - Thread展开、翻译、过滤、导出、推荐"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import OpenAI

from .config import config
from .twitter_client import Tweet, TwitterClient


# =============================================================================
# Thread 展开器
# =============================================================================

@dataclass
class Thread:
    """Thread 数据结构"""

    tweets: list[Tweet]
    author_username: str
    author_name: str
    created_at: datetime
    total_engagement: int = 0

    def __post_init__(self):
        if self.tweets:
            self.total_engagement = sum(t.engagement_score for t in self.tweets)

    @property
    def full_text(self) -> str:
        """合并所有推文文本"""
        return "\n\n".join(t.text for t in self.tweets)

    @property
    def url(self) -> str:
        """Thread 首条推文链接"""
        if self.tweets:
            return self.tweets[0].url
        return ""

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"# Thread by @{self.author_username}",
            f"**{self.author_name}** · {self.created_at.strftime('%Y-%m-%d %H:%M')}",
            f"[原文链接]({self.url})",
            "",
            "---",
            "",
        ]

        for i, tweet in enumerate(self.tweets, 1):
            lines.append(f"**[{i}/{len(self.tweets)}]**")
            lines.append(tweet.text)
            lines.append("")

        lines.extend([
            "---",
            f"❤️ {sum(t.like_count for t in self.tweets)} · "
            f"🔁 {sum(t.retweet_count for t in self.tweets)} · "
            f"💬 {sum(t.reply_count for t in self.tweets)}",
        ])

        return "\n".join(lines)


class ThreadExpander:
    """Thread 展开器 - 获取完整 Thread"""

    def __init__(self, twitter_client: TwitterClient = None):
        self.twitter = twitter_client or TwitterClient()

    def get_thread(self, tweet_id: str) -> Optional[Thread]:
        """获取完整 Thread"""
        try:
            # 获取对话上下文
            response = self.twitter.client.get_tweet(
                id=tweet_id,
                tweet_fields=["conversation_id", "created_at", "public_metrics", "author_id"],
                user_fields=["username", "name"],
                expansions=["author_id"],
            )

            if not response.data:
                return None

            conversation_id = response.data.conversation_id
            author_id = response.data.author_id

            # 获取用户信息
            users = {u.id: u for u in (response.includes.get("users", []) or [])}
            author = users.get(author_id)

            # 搜索同一对话中该作者的所有推文
            search_response = self.twitter.client.search_recent_tweets(
                query=f"conversation_id:{conversation_id} from:{author.username}",
                max_results=100,
                tweet_fields=["created_at", "public_metrics", "author_id"],
                user_fields=["username", "name"],
                expansions=["author_id"],
            )

            if not search_response.data:
                # 如果搜索失败，至少返回原始推文
                metrics = response.data.public_metrics or {}
                single_tweet = Tweet(
                    id=str(response.data.id),
                    text=response.data.text,
                    author_id=str(author_id),
                    author_username=author.username if author else "unknown",
                    author_name=author.name if author else "Unknown",
                    created_at=response.data.created_at,
                    like_count=metrics.get("like_count", 0),
                    retweet_count=metrics.get("retweet_count", 0),
                    reply_count=metrics.get("reply_count", 0),
                    quote_count=metrics.get("quote_count", 0),
                )
                return Thread(
                    tweets=[single_tweet],
                    author_username=single_tweet.author_username,
                    author_name=single_tweet.author_name,
                    created_at=single_tweet.created_at,
                )

            # 构建 Thread
            tweets = []
            for tweet in search_response.data:
                metrics = tweet.public_metrics or {}
                tweets.append(
                    Tweet(
                        id=str(tweet.id),
                        text=tweet.text,
                        author_id=str(tweet.author_id),
                        author_username=author.username if author else "unknown",
                        author_name=author.name if author else "Unknown",
                        created_at=tweet.created_at,
                        like_count=metrics.get("like_count", 0),
                        retweet_count=metrics.get("retweet_count", 0),
                        reply_count=metrics.get("reply_count", 0),
                        quote_count=metrics.get("quote_count", 0),
                    )
                )

            # 按时间排序
            tweets.sort(key=lambda t: t.created_at)

            return Thread(
                tweets=tweets,
                author_username=tweets[0].author_username,
                author_name=tweets[0].author_name,
                created_at=tweets[0].created_at,
            )

        except Exception as e:
            print(f"获取 Thread 失败: {e}")
            return None

    def detect_threads(self, tweets: list[Tweet]) -> list[Thread]:
        """从推文列表中检测 Thread（基于回复关系）"""
        # 按作者分组
        by_author: dict[str, list[Tweet]] = {}
        for tweet in tweets:
            if tweet.author_username not in by_author:
                by_author[tweet.author_username] = []
            by_author[tweet.author_username].append(tweet)

        threads = []
        for username, user_tweets in by_author.items():
            # 按时间排序
            user_tweets.sort(key=lambda t: t.created_at)

            # 简单策略：如果同一作者在短时间内连续发多条推文，可能是 Thread
            if len(user_tweets) >= 3:
                threads.append(
                    Thread(
                        tweets=user_tweets,
                        author_username=username,
                        author_name=user_tweets[0].author_name,
                        created_at=user_tweets[0].created_at,
                    )
                )

        return threads


# =============================================================================
# 推文翻译器
# =============================================================================

class Translator:
    """推文翻译器 - 使用 AI 翻译"""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model
        self.cache: dict[str, str] = {}

    def detect_language(self, text: str) -> str:
        """简单的语言检测"""
        # 检测中文字符
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text.replace(" ", ""))

        if total_chars == 0:
            return "unknown"

        if chinese_chars / total_chars > 0.3:
            return "zh"
        return "en"

    def translate(self, text: str, target_lang: str = "zh") -> str:
        """翻译文本"""
        # 检查缓存
        cache_key = f"{text[:50]}_{target_lang}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 检测语言
        source_lang = self.detect_language(text)
        if source_lang == target_lang:
            return text

        target_name = "中文" if target_lang == "zh" else "English"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": f"你是一个专业翻译，将文本翻译成{target_name}。保持原文的语气和风格，不要添加解释。",
                },
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        translated = response.choices[0].message.content
        self.cache[cache_key] = translated
        return translated

    def translate_tweet(self, tweet: Tweet, target_lang: str = "zh") -> Tweet:
        """翻译单条推文"""
        if self.detect_language(tweet.text) == target_lang:
            return tweet

        translated_text = self.translate(tweet.text, target_lang)

        # 创建新的 Tweet 对象，包含翻译
        return Tweet(
            id=tweet.id,
            text=f"{translated_text}\n\n---\n📝 原文: {tweet.text}",
            author_id=tweet.author_id,
            author_username=tweet.author_username,
            author_name=tweet.author_name,
            created_at=tweet.created_at,
            like_count=tweet.like_count,
            retweet_count=tweet.retweet_count,
            reply_count=tweet.reply_count,
            quote_count=tweet.quote_count,
            url=tweet.url,
        )

    def translate_tweets(self, tweets: list[Tweet], target_lang: str = "zh") -> list[Tweet]:
        """批量翻译推文"""
        return [self.translate_tweet(t, target_lang) for t in tweets]


# =============================================================================
# 内容过滤器
# =============================================================================

@dataclass
class FilterConfig:
    """过滤配置"""

    blocked_words: list[str] = field(default_factory=list)
    blocked_users: list[str] = field(default_factory=list)
    min_engagement: int = 0
    filter_ads: bool = True
    filter_retweets: bool = False


class ContentFilter:
    """内容过滤器"""

    def __init__(self):
        self.config_file = config.data_dir / "filter_config.json"
        self.filter_config = self._load_config()

        # 广告关键词
        self.ad_patterns = [
            r"#ad\b",
            r"#sponsored",
            r"promo code",
            r"discount code",
            r"use code",
            r"link in bio",
            r"check out my",
            r"subscribe to my",
            r"giveaway",
            r"airdrop",
            r"whitelist",
            r"presale",
        ]

    def _load_config(self) -> FilterConfig:
        """加载过滤配置"""
        if self.config_file.exists():
            with open(self.config_file) as f:
                data = json.load(f)
                return FilterConfig(**data)
        return FilterConfig()

    def save_config(self) -> None:
        """保存过滤配置"""
        with open(self.config_file, "w") as f:
            json.dump(
                {
                    "blocked_words": self.filter_config.blocked_words,
                    "blocked_users": self.filter_config.blocked_users,
                    "min_engagement": self.filter_config.min_engagement,
                    "filter_ads": self.filter_config.filter_ads,
                    "filter_retweets": self.filter_config.filter_retweets,
                },
                f,
                indent=2,
            )

    def add_blocked_words(self, words: list[str]) -> None:
        """添加屏蔽词"""
        self.filter_config.blocked_words.extend(words)
        self.filter_config.blocked_words = list(set(self.filter_config.blocked_words))
        self.save_config()

    def remove_blocked_words(self, words: list[str]) -> None:
        """移除屏蔽词"""
        self.filter_config.blocked_words = [
            w for w in self.filter_config.blocked_words if w not in words
        ]
        self.save_config()

    def add_blocked_users(self, users: list[str]) -> None:
        """添加屏蔽用户"""
        self.filter_config.blocked_users.extend(users)
        self.filter_config.blocked_users = list(set(self.filter_config.blocked_users))
        self.save_config()

    def is_ad(self, tweet: Tweet) -> bool:
        """检测是否是广告"""
        text_lower = tweet.text.lower()
        for pattern in self.ad_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def is_retweet(self, tweet: Tweet) -> bool:
        """检测是否是转推"""
        return tweet.text.startswith("RT @")

    def filter_tweet(self, tweet: Tweet) -> bool:
        """检查推文是否应该被过滤（返回 True 表示保留）"""
        # 检查屏蔽用户
        if tweet.author_username.lower() in [u.lower() for u in self.filter_config.blocked_users]:
            return False

        # 检查屏蔽词
        text_lower = tweet.text.lower()
        for word in self.filter_config.blocked_words:
            if word.lower() in text_lower:
                return False

        # 检查互动量
        if tweet.engagement_score < self.filter_config.min_engagement:
            return False

        # 检查广告
        if self.filter_config.filter_ads and self.is_ad(tweet):
            return False

        # 检查转推
        if self.filter_config.filter_retweets and self.is_retweet(tweet):
            return False

        return True

    def filter_tweets(self, tweets: list[Tweet]) -> list[Tweet]:
        """过滤推文列表"""
        return [t for t in tweets if self.filter_tweet(t)]


# =============================================================================
# Markdown 导出器
# =============================================================================

class MarkdownExporter:
    """Markdown 导出器"""

    def __init__(self):
        self.export_dir = config.data_dir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_digest(self, digest: str, title: str = None) -> Path:
        """导出摘要为 Markdown 文件"""
        if title is None:
            title = f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        filename = f"{title}.md"
        filepath = self.export_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(digest)

        return filepath

    def export_tweets(self, tweets: list[Tweet], title: str = None) -> Path:
        """导出推文列表为 Markdown 文件"""
        if title is None:
            title = f"tweets_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        lines = [
            f"# {title}",
            f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"共 {len(tweets)} 条推文",
            "",
            "---",
            "",
        ]

        for tweet in tweets:
            lines.extend([
                f"## @{tweet.author_username}",
                f"**{tweet.author_name}** · {tweet.created_at.strftime('%Y-%m-%d %H:%M')}",
                "",
                tweet.text,
                "",
                f"❤️ {tweet.like_count} · 🔁 {tweet.retweet_count} · 💬 {tweet.reply_count}",
                f"[原文链接]({tweet.url})",
                "",
                "---",
                "",
            ])

        filename = f"{title}.md"
        filepath = self.export_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return filepath

    def export_thread(self, thread: Thread, title: str = None) -> Path:
        """导出 Thread 为 Markdown 文件"""
        if title is None:
            title = f"thread_{thread.author_username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        filename = f"{title}.md"
        filepath = self.export_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(thread.to_markdown())

        return filepath

    def list_exports(self) -> list[Path]:
        """列出所有导出文件"""
        return sorted(self.export_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


# =============================================================================
# 账号推荐器
# =============================================================================

class AccountRecommender:
    """账号推荐器 - 发现优质账号"""

    def __init__(self, twitter_client: TwitterClient = None):
        self.twitter = twitter_client or TwitterClient()
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model

    def get_similar_accounts(self, username: str, limit: int = 10) -> list[dict]:
        """获取与指定账号相似的账号"""
        try:
            # 获取用户 ID
            user_id = self.twitter.get_user_id(username)
            if not user_id:
                return []

            # 获取该用户关注的人
            response = self.twitter.client.get_users_following(
                id=user_id,
                max_results=min(limit * 2, 100),
                user_fields=["description", "public_metrics", "verified"],
            )

            if not response.data:
                return []

            accounts = []
            for user in response.data:
                metrics = user.public_metrics or {}
                accounts.append({
                    "username": user.username,
                    "name": user.name,
                    "description": user.description or "",
                    "followers": metrics.get("followers_count", 0),
                    "verified": user.verified or False,
                })

            # 按粉丝数排序
            accounts.sort(key=lambda x: x["followers"], reverse=True)
            return accounts[:limit]

        except Exception as e:
            print(f"获取相似账号失败: {e}")
            return []

    def analyze_accounts(self, accounts: list[dict]) -> str:
        """使用 AI 分析账号列表"""
        if not accounts:
            return "没有找到推荐账号"

        accounts_text = "\n".join([
            f"@{a['username']} ({a['name']}): {a['description'][:100]}... "
            f"[{a['followers']:,} followers]"
            for a in accounts
        ])

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个社交媒体分析专家，帮助用户发现优质账号。",
                },
                {
                    "role": "user",
                    "content": f"""分析以下 Twitter 账号，并推荐值得关注的：

{accounts_text}

请：
1. 按领域/主题分类这些账号
2. 推荐最值得关注的 5 个账号，说明理由
3. 指出可能是营销号或低质量的账号""",
                },
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        return response.choices[0].message.content

    def discover_from_following(self, limit: int = 20) -> list[dict]:
        """从当前关注列表发现新账号"""
        following = self.twitter.get_following_list()
        if not following:
            return []

        all_recommendations = []
        seen_usernames = set(following)

        for username in following[:5]:  # 只检查前 5 个关注的人
            similar = self.get_similar_accounts(username, limit=10)
            for account in similar:
                if account["username"] not in seen_usernames:
                    seen_usernames.add(account["username"])
                    all_recommendations.append(account)

        # 去重并按粉丝数排序
        all_recommendations.sort(key=lambda x: x["followers"], reverse=True)
        return all_recommendations[:limit]
