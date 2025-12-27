"""X/Twitter 数据获取模块"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import tweepy

from .config import config


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
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class TwitterClient:
    """Twitter API 客户端"""

    def __init__(self):
        self.client = tweepy.Client(
            bearer_token=config.twitter.bearer_token,
            consumer_key=config.twitter.api_key,
            consumer_secret=config.twitter.api_secret,
            access_token=config.twitter.access_token,
            access_token_secret=config.twitter.access_token_secret,
            wait_on_rate_limit=True,
        )
        self.following_file = config.data_dir / "following.json"
        self.cache_file = config.data_dir / "tweets_cache.json"

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
        current.update(usernames)
        with open(self.following_file, "w") as f:
            json.dump({"usernames": list(current)}, f, indent=2)

    def remove_following(self, usernames: list[str]) -> None:
        """移除关注账号"""
        current = set(self.get_following_list())
        current -= set(usernames)
        with open(self.following_file, "w") as f:
            json.dump({"usernames": list(current)}, f, indent=2)

    def get_user_id(self, username: str) -> Optional[str]:
        """根据用户名获取用户 ID"""
        try:
            user = self.client.get_user(username=username)
            if user.data:
                return user.data.id
        except tweepy.TweepyException as e:
            print(f"获取用户 {username} 失败: {e}")
        return None

    def get_user_tweets(
        self,
        username: str,
        hours: int = 24,
        max_results: int = None,
    ) -> list[Tweet]:
        """获取用户最近的推文"""
        if max_results is None:
            max_results = config.digest.max_tweets_per_user

        user_id = self.get_user_id(username)
        if not user_id:
            return []

        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            response = self.client.get_users_tweets(
                id=user_id,
                start_time=start_time,
                max_results=min(max_results, 100),
                tweet_fields=["created_at", "public_metrics", "author_id"],
                user_fields=["username", "name"],
                expansions=["author_id"],
            )

            if not response.data:
                return []

            # 获取用户信息
            users = {u.id: u for u in (response.includes.get("users", []) or [])}

            tweets = []
            for tweet in response.data:
                author = users.get(tweet.author_id)
                metrics = tweet.public_metrics or {}

                tweets.append(
                    Tweet(
                        id=str(tweet.id),
                        text=tweet.text,
                        author_id=str(tweet.author_id),
                        author_username=author.username if author else username,
                        author_name=author.name if author else username,
                        created_at=tweet.created_at,
                        like_count=metrics.get("like_count", 0),
                        retweet_count=metrics.get("retweet_count", 0),
                        reply_count=metrics.get("reply_count", 0),
                        quote_count=metrics.get("quote_count", 0),
                    )
                )

            return tweets

        except tweepy.TweepyException as e:
            print(f"获取 {username} 推文失败: {e}")
            return []

    def get_all_following_tweets(self, hours: int = 24) -> list[Tweet]:
        """获取所有关注账号的推文"""
        all_tweets = []
        usernames = self.get_following_list()

        for username in usernames:
            print(f"正在获取 @{username} 的推文...")
            tweets = self.get_user_tweets(username, hours=hours)
            all_tweets.extend(tweets)
            print(f"  获取到 {len(tweets)} 条推文")

        # 按互动分数排序
        all_tweets.sort(key=lambda t: t.engagement_score, reverse=True)

        return all_tweets

    def search_tweets(
        self,
        query: str,
        hours: int = 24,
        max_results: int = 50,
    ) -> list[Tweet]:
        """搜索推文"""
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        try:
            response = self.client.search_recent_tweets(
                query=query,
                start_time=start_time,
                max_results=min(max_results, 100),
                tweet_fields=["created_at", "public_metrics", "author_id"],
                user_fields=["username", "name"],
                expansions=["author_id"],
            )

            if not response.data:
                return []

            users = {u.id: u for u in (response.includes.get("users", []) or [])}

            tweets = []
            for tweet in response.data:
                author = users.get(tweet.author_id)
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

            return tweets

        except tweepy.TweepyException as e:
            print(f"搜索推文失败: {e}")
            return []

    def cache_tweets(self, tweets: list[Tweet]) -> None:
        """缓存推文到本地"""
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in tweets], f, ensure_ascii=False, indent=2)

    def load_cached_tweets(self) -> list[Tweet]:
        """从本地加载缓存的推文"""
        if not self.cache_file.exists():
            return []
        with open(self.cache_file, encoding="utf-8") as f:
            data = json.load(f)
            return [Tweet.from_dict(t) for t in data]
