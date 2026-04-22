"""X/Twitter 数据获取模块 - 支持多种数据源（TweeterPy / Nitter / 手动输入）"""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import hashlib
import logging

import aiohttp
import asyncio

from .config import config

# 尝试导入 TweeterPy
try:
    from tweeterpy import TweeterPy
    TWEETERPY_AVAILABLE = True
except ImportError:
    TWEETERPY_AVAILABLE = False
    TweeterPy = None

# 配置日志
logging.getLogger("tweeterpy").setLevel(logging.WARNING)


# 数据源状态
class DataSourceStatus:
    """数据源状态跟踪"""
    TWEETERPY_AVAILABLE = TWEETERPY_AVAILABLE
    NITTER_AVAILABLE = False
    LAST_CHECK_TIME: Optional[datetime] = None
    WORKING_INSTANCE: Optional[str] = None
    ERROR_MESSAGE: str = "未检测"
    LAST_ERROR: Optional[str] = None


@dataclass
class Tweet:
    """推文数据结构"""

    id: str
    text: str
    author_id: str
    author_username: str
    author_name: str
    created_at: datetime
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    url: str = ""

    def __post_init__(self):
        if not self.url:
            self.url = f"https://x.com/{self.author_username}/status/{self.id}"

    @property
    def engagement_score(self) -> int:
        """互动分数，用于排序"""
        return self.like_count * 1 + self.retweet_count * 3 + self.reply_count * 2 + self.quote_count * 4

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Tweet":
        if isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class TwitterClient:
    """Twitter 客户端 - 支持多种数据源（TweeterPy / Nitter RSS / 手动输入）"""

    # Nitter 实例列表（大部分已失效，保留作为备用）
    NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.woodland.cafe",
        "https://nitter.1d4.us",
        "https://nitter.kavin.rocks",
        "https://nitter.unixfox.eu",
    ]

    def __init__(self):
        self.following_file = config.data_dir / "following.json"
        self.cache_file = config.data_dir / "tweets_cache.json"
        self.manual_tweets_file = config.data_dir / "manual_tweets.json"
        self.user_id_cache_file = config.data_dir / "user_id_cache.json"
        self.working_instance = None  # Nitter 实例

        # 初始化 TweeterPy（如果可用）
        self._tweeterpy = None
        if TWEETERPY_AVAILABLE:
            try:
                self._tweeterpy = TweeterPy()
                DataSourceStatus.TWEETERPY_AVAILABLE = True
            except Exception as e:
                DataSourceStatus.TWEETERPY_AVAILABLE = False
                DataSourceStatus.LAST_ERROR = str(e)

        # 用户 ID 缓存
        self._user_id_cache = self._load_user_id_cache()

    def _load_user_id_cache(self) -> dict:
        """加载用户 ID 缓存"""
        if self.user_id_cache_file.exists():
            try:
                with open(self.user_id_cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_user_id_cache(self) -> None:
        """保存用户 ID 缓存"""
        with open(self.user_id_cache_file, "w", encoding="utf-8") as f:
            json.dump(self._user_id_cache, f, ensure_ascii=False, indent=2)

    # ========== TweeterPy 数据获取方法 ==========

    def _get_user_id_tweeterpy(self, username: str) -> Optional[str]:
        """使用 TweeterPy 获取用户 ID"""
        if not self._tweeterpy:
            return None

        # 先检查缓存
        username_lower = username.lower()
        if username_lower in self._user_id_cache:
            return self._user_id_cache[username_lower]

        try:
            user_id = self._tweeterpy.get_user_id(username)
            if user_id:
                self._user_id_cache[username_lower] = str(user_id)
                self._save_user_id_cache()
                return str(user_id)
        except Exception as e:
            print(f"  获取 @{username} ID 失败: {e}")

        return None

    def _get_tweets_tweeterpy(self, username: str, max_results: int = 20, hours: int = 24) -> list[Tweet]:
        """使用 TweeterPy 获取用户推文"""
        if not self._tweeterpy:
            return []

        tweets = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            # 获取用户 ID
            user_id = self._get_user_id_tweeterpy(username)
            if not user_id:
                return []

            # 获取推文
            tweets_data = self._tweeterpy.get_user_tweets(user_id, total=max_results)

            if not tweets_data or "data" not in tweets_data:
                return []

            for item in tweets_data["data"]:
                try:
                    tweet = self._parse_tweeterpy_tweet(item, username)
                    if tweet and tweet.created_at >= cutoff_time:
                        tweets.append(tweet)
                except Exception as e:
                    continue

        except Exception as e:
            print(f"  TweeterPy 获取 @{username} 推文失败: {e}")
            DataSourceStatus.LAST_ERROR = str(e)

        return tweets

    def _parse_tweeterpy_tweet(self, item: dict, fallback_username: str = "") -> Optional[Tweet]:
        """解析 TweeterPy 返回的推文数据"""
        try:
            content = item.get("content", {})
            item_content = content.get("itemContent", {})
            tweet_results = item_content.get("tweet_results", {})
            result = tweet_results.get("result", {})

            # 跳过非推文类型
            if result.get("__typename") not in ["Tweet", "TweetWithVisibilityResults"]:
                return None

            # 如果是 TweetWithVisibilityResults，需要再深入一层
            if result.get("__typename") == "TweetWithVisibilityResults":
                result = result.get("tweet", {})

            # 获取推文 ID
            tweet_id = result.get("rest_id", "")
            if not tweet_id:
                return None

            # 获取推文文本
            legacy = result.get("legacy", {})
            text = legacy.get("full_text", "")

            # 获取用户信息
            core = result.get("core", {})
            user_results = core.get("user_results", {}).get("result", {})
            user_core = user_results.get("core", {})
            user_legacy = user_results.get("legacy", {})

            username = user_core.get("screen_name", fallback_username)
            name = user_core.get("name", username)

            # 获取互动数据
            like_count = legacy.get("favorite_count", 0)
            retweet_count = legacy.get("retweet_count", 0)
            reply_count = legacy.get("reply_count", 0)
            quote_count = legacy.get("quote_count", 0)

            # 解析时间
            created_at_str = legacy.get("created_at", "")
            created_at = self._parse_twitter_date(created_at_str)
            if not created_at:
                created_at = datetime.now(timezone.utc)

            return Tweet(
                id=tweet_id,
                text=text,
                author_id=user_results.get("rest_id", username),
                author_username=username,
                author_name=name,
                created_at=created_at,
                like_count=like_count,
                retweet_count=retweet_count,
                reply_count=reply_count,
                quote_count=quote_count,
                url=f"https://x.com/{username}/status/{tweet_id}",
            )

        except Exception as e:
            return None

    def _parse_twitter_date(self, date_str: str) -> Optional[datetime]:
        """解析 Twitter 日期格式"""
        if not date_str:
            return None

        try:
            # Twitter 格式: "Tue Jan 24 20:14:18 +0000 2023"
            dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
            return dt
        except ValueError:
            pass

        return None

    # ========== 手动输入相关方法 ==========

    def add_manual_tweet(
        self,
        text: str,
        author_username: str,
        author_name: str = "",
        url: str = "",
        created_at: Optional[datetime] = None,
    ) -> Tweet:
        """添加手动输入的推文"""
        if not author_name:
            author_name = author_username

        if created_at is None:
            created_at = datetime.now(timezone.utc)

        # 生成唯一 ID
        tweet_id = hashlib.md5(f"{author_username}{text}{created_at}".encode()).hexdigest()[:16]

        # 从 URL 提取 ID（如果有）
        if url:
            extracted_id = self._extract_tweet_id(url)
            if extracted_id:
                tweet_id = extracted_id

        tweet = Tweet(
            id=tweet_id,
            text=text,
            author_id=author_username,
            author_username=author_username,
            author_name=author_name,
            created_at=created_at,
            url=url or f"https://x.com/{author_username}/status/{tweet_id}",
        )

        # 保存到手动推文文件
        manual_tweets = self._load_manual_tweets()
        manual_tweets.append(tweet.to_dict())
        self._save_manual_tweets(manual_tweets)

        return tweet

    def add_manual_tweets_batch(self, tweets_data: list[dict]) -> list[Tweet]:
        """批量添加手动推文"""
        tweets = []
        for data in tweets_data:
            tweet = self.add_manual_tweet(
                text=data.get("text", ""),
                author_username=data.get("author_username", "unknown"),
                author_name=data.get("author_name", ""),
                url=data.get("url", ""),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            )
            tweets.append(tweet)
        return tweets

    def _load_manual_tweets(self) -> list[dict]:
        """加载手动推文"""
        if not self.manual_tweets_file.exists():
            return []
        try:
            with open(self.manual_tweets_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, KeyError):
            return []

    def _save_manual_tweets(self, tweets: list[dict]) -> None:
        """保存手动推文"""
        with open(self.manual_tweets_file, "w", encoding="utf-8") as f:
            json.dump(tweets, f, ensure_ascii=False, indent=2)

    def get_manual_tweets(self, hours: int = 24) -> list[Tweet]:
        """获取手动输入的推文（按时间过滤）"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        tweets = []

        for data in self._load_manual_tweets():
            try:
                tweet = Tweet.from_dict(data)
                if tweet.created_at >= cutoff_time:
                    tweets.append(tweet)
            except Exception:
                continue

        return sorted(tweets, key=lambda t: t.created_at, reverse=True)

    def clear_manual_tweets(self, before_hours: int = None) -> int:
        """清理手动推文"""
        if before_hours is None:
            # 清理全部
            count = len(self._load_manual_tweets())
            self._save_manual_tweets([])
            return count

        # 清理指定时间之前的
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=before_hours)
        manual_tweets = self._load_manual_tweets()
        kept = []
        removed = 0

        for data in manual_tweets:
            try:
                tweet = Tweet.from_dict(data)
                if tweet.created_at >= cutoff_time:
                    kept.append(data)
                else:
                    removed += 1
            except Exception:
                removed += 1

        self._save_manual_tweets(kept)
        return removed

    # ========== 数据源检测 ==========

    async def check_nitter_status(self) -> bool:
        """检测 Nitter 实例是否可用"""
        DataSourceStatus.LAST_CHECK_TIME = datetime.now(timezone.utc)

        async with aiohttp.ClientSession() as session:
            for instance in self.NITTER_INSTANCES:
                try:
                    url = f"{instance}/elonmusk/rss"
                    async with session.get(
                        url,
                        timeout=aiohttp.ClientTimeout(total=5),
                        headers={"User-Agent": "Mozilla/5.0"}
                    ) as resp:
                        if resp.status == 200:
                            content = await resp.text()
                            # 检查是否真的是 RSS 内容
                            if "<rss" in content and "<item>" in content:
                                DataSourceStatus.NITTER_AVAILABLE = True
                                DataSourceStatus.WORKING_INSTANCE = instance
                                DataSourceStatus.ERROR_MESSAGE = "可用"
                                self.working_instance = instance
                                return True
                except Exception as e:
                    continue

        DataSourceStatus.NITTER_AVAILABLE = False
        DataSourceStatus.WORKING_INSTANCE = None
        DataSourceStatus.ERROR_MESSAGE = "所有 Nitter 实例均不可用"
        return False

    def get_data_source_status(self) -> dict:
        """获取数据源状态"""
        manual_count = len(self._load_manual_tweets())

        # 判断推荐的数据源
        if self._tweeterpy:
            recommendation = "TweeterPy（自动）"
            auto_available = True
        elif DataSourceStatus.NITTER_AVAILABLE:
            recommendation = "Nitter RSS"
            auto_available = True
        else:
            recommendation = "手动输入"
            auto_available = False

        return {
            "tweeterpy_available": self._tweeterpy is not None,
            "nitter_available": DataSourceStatus.NITTER_AVAILABLE,
            "working_instance": DataSourceStatus.WORKING_INSTANCE,
            "last_check": DataSourceStatus.LAST_CHECK_TIME.isoformat() if DataSourceStatus.LAST_CHECK_TIME else None,
            "error_message": DataSourceStatus.ERROR_MESSAGE,
            "last_error": DataSourceStatus.LAST_ERROR,
            "manual_tweets_count": manual_count,
            "recommendation": recommendation,
            "auto_available": auto_available,
        }

    def get_following_list(self) -> list[str]:
        """获取关注列表（从本地文件读取）"""
        if self.following_file.exists():
            with open(self.following_file) as f:
                data = json.load(f)
                return data.get("usernames", [])
        return []

    def add_following(self, usernames: list[str]) -> None:
        """添加关注账号"""
        current = set(self.get_following_list())
        # 清理用户名（移除 @ 和空格）
        cleaned = [u.strip().lstrip("@").lower() for u in usernames if u.strip()]
        current.update(cleaned)
        with open(self.following_file, "w") as f:
            json.dump({"usernames": sorted(current)}, f, indent=2)

    def remove_following(self, usernames: list[str]) -> None:
        """移除关注账号"""
        current = set(self.get_following_list())
        cleaned = [u.strip().lstrip("@").lower() for u in usernames]
        current -= set(cleaned)
        with open(self.following_file, "w") as f:
            json.dump({"usernames": sorted(current)}, f, indent=2)

    async def _fetch_rss(self, username: str) -> Optional[str]:
        """从 Nitter 获取 RSS feed"""
        # 如果有缓存的可用实例，优先使用
        instances = self.NITTER_INSTANCES.copy()
        if self.working_instance:
            instances.remove(self.working_instance) if self.working_instance in instances else None
            instances.insert(0, self.working_instance)

        async with aiohttp.ClientSession() as session:
            for instance in instances:
                url = f"{instance}/{username}/rss"
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            self.working_instance = instance  # 缓存可用实例
                            return await resp.text()
                except Exception as e:
                    print(f"  {instance} 失败: {e}")
                    continue

        return None

    def _parse_rss(self, rss_content: str, username: str, hours: int = 24) -> list[Tweet]:
        """解析 RSS feed 内容"""
        tweets = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            root = ET.fromstring(rss_content)
            channel = root.find("channel")
            if channel is None:
                return []

            # 获取作者名称
            author_name = username
            title_elem = channel.find("title")
            if title_elem is not None and title_elem.text:
                # 格式通常是 "Name / @username"
                parts = title_elem.text.split(" / ")
                if parts:
                    author_name = parts[0].strip()

            for item in channel.findall("item"):
                try:
                    # 解析发布时间
                    pub_date = item.find("pubDate")
                    if pub_date is None or not pub_date.text:
                        continue

                    # RSS 日期格式: "Wed, 25 Dec 2024 10:30:00 GMT"
                    created_at = self._parse_rss_date(pub_date.text)
                    if created_at is None:
                        continue

                    # 过滤时间范围
                    if created_at < cutoff_time:
                        continue

                    # 获取推文内容
                    description = item.find("description")
                    if description is None or not description.text:
                        continue

                    text = self._clean_html(description.text)

                    # 获取链接和 ID
                    link = item.find("link")
                    tweet_url = link.text if link is not None and link.text else ""
                    tweet_id = self._extract_tweet_id(tweet_url)

                    if not tweet_id:
                        # 生成一个基于内容的 ID
                        tweet_id = hashlib.md5(f"{username}{text}{created_at}".encode()).hexdigest()[:16]

                    tweets.append(Tweet(
                        id=tweet_id,
                        text=text,
                        author_id=username,
                        author_username=username,
                        author_name=author_name,
                        created_at=created_at,
                        url=tweet_url.replace("nitter.privacydev.net", "x.com")
                                     .replace("nitter.poast.org", "x.com")
                                     .replace("nitter.woodland.cafe", "x.com")
                                     .replace("nitter.1d4.us", "x.com")
                                     .replace("nitter.kavin.rocks", "x.com")
                                     .replace("nitter.unixfox.eu", "x.com")
                                     if tweet_url else f"https://x.com/{username}/status/{tweet_id}",
                        # Nitter RSS 不提供互动数据，设为 0
                        like_count=0,
                        retweet_count=0,
                        reply_count=0,
                        quote_count=0,
                    ))

                except Exception as e:
                    print(f"  解析推文失败: {e}")
                    continue

        except ET.ParseError as e:
            print(f"  RSS 解析错误: {e}")

        return tweets

    def _parse_rss_date(self, date_str: str) -> Optional[datetime]:
        """解析 RSS 日期格式"""
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        # 尝试手动解析
        try:
            # "Wed, 25 Dec 2024 10:30:00 GMT" -> 移除时区名
            date_str = date_str.replace("GMT", "+0000").replace("UTC", "+0000")
            dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
            return dt
        except:
            pass

        return None

    def _clean_html(self, html: str) -> str:
        """清理 HTML 标签，提取纯文本"""
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', html)
        # 处理 HTML 实体
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        text = text.replace("&nbsp;", " ")
        # 清理多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_tweet_id(self, url: str) -> Optional[str]:
        """从 URL 提取推文 ID"""
        if not url:
            return None
        match = re.search(r'/status/(\d+)', url)
        return match.group(1) if match else None

    def get_user_tweets(
        self,
        username: str,
        hours: int = 24,
        max_results: int = None,
    ) -> list[Tweet]:
        """获取用户最近的推文（同步包装）"""
        return asyncio.get_event_loop().run_until_complete(
            self._get_user_tweets_async(username, hours, max_results)
        )

    async def _get_user_tweets_async(
        self,
        username: str,
        hours: int = 24,
        max_results: int = None,
    ) -> list[Tweet]:
        """获取用户最近的推文"""
        if max_results is None:
            max_results = config.digest.max_tweets_per_user

        rss_content = await self._fetch_rss(username)
        if not rss_content:
            print(f"  无法获取 @{username} 的 RSS")
            return []

        tweets = self._parse_rss(rss_content, username, hours)

        # 限制数量
        return tweets[:max_results]

    def get_all_following_tweets(self, hours: int = 24, include_manual: bool = True) -> list[Tweet]:
        """获取所有关注账号的推文（同步方法，适用于后台任务）"""
        all_tweets = []
        usernames = self.get_following_list()

        tweeterpy_success = False

        # 1. 优先使用 TweeterPy（同步，最可靠）
        if usernames and self._tweeterpy:
            print(f"正在使用 TweeterPy 获取 {len(usernames)} 个账号的推文...")
            for username in usernames:
                print(f"正在获取 @{username} 的推文...")
                tweets = self._get_tweets_tweeterpy(username, hours=hours)
                all_tweets.extend(tweets)
                if tweets:
                    tweeterpy_success = True
                print(f"  获取到 {len(tweets)} 条推文")

        # 2. 如果 TweeterPy 失败且没有推文，提示用户
        if not tweeterpy_success and usernames:
            print("TweeterPy 获取失败，请尝试手动输入推文")

        # 3. 获取手动输入的推文
        if include_manual:
            manual_tweets = self.get_manual_tweets(hours=hours)
            if manual_tweets:
                print(f"从手动输入获取 {len(manual_tweets)} 条推文")
                all_tweets.extend(manual_tweets)

        # 4. 去重（按 ID）
        seen_ids = set()
        unique_tweets = []
        for tweet in all_tweets:
            if tweet.id not in seen_ids:
                seen_ids.add(tweet.id)
                unique_tweets.append(tweet)

        # 5. 按时间排序（最新的在前）
        unique_tweets.sort(key=lambda t: t.created_at, reverse=True)

        # 状态信息
        source_info = []
        if tweeterpy_success:
            source_info.append("TweeterPy ✓")
        else:
            source_info.append("自动获取 ✗")

        manual_count = len(self.get_manual_tweets(hours))
        if manual_count > 0:
            source_info.append(f"手动 {manual_count} 条")

        print(f"共获取 {len(unique_tweets)} 条推文 ({', '.join(source_info)})")
        return unique_tweets

    def search_tweets(
        self,
        query: str,
        hours: int = 24,
        max_results: int = 50,
    ) -> list[Tweet]:
        """搜索推文 - Nitter 不支持搜索，返回空"""
        print("注意: Nitter RSS 不支持搜索功能")
        return []

    def cache_tweets(self, tweets: list[Tweet]) -> None:
        """缓存推文到本地"""
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in tweets], f, ensure_ascii=False, indent=2)

    def load_cached_tweets(self) -> list[Tweet]:
        """从本地加载缓存的推文"""
        if not self.cache_file.exists():
            return []
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                data = json.load(f)
                return [Tweet.from_dict(t) for t in data]
        except (json.JSONDecodeError, KeyError) as e:
            print(f"加载缓存失败: {e}")
            return []

    def get_tweet_comments(
        self,
        tweet_id: str,
        max_results: int = 20,
    ) -> list[dict]:
        """获取推文评论 - Nitter 不支持，返回空"""
        return []

    def get_tweet_by_id(self, tweet_id: str) -> Optional[Tweet]:
        """根据 ID 获取推文 - Nitter 不直接支持"""
        # 尝试从缓存中查找
        cached = self.load_cached_tweets()
        for tweet in cached:
            if tweet.id == tweet_id:
                return tweet
        return None
