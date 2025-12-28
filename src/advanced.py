"""高级功能模块 - AI对话、情绪分析、智能提醒、知识图谱、RSS、Webhook"""

import json
import re
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable
from xml.etree.ElementTree import Element, SubElement, tostring
import asyncio
import threading

from openai import OpenAI

from .config import config
from .twitter_client import Tweet, TwitterClient


# =============================================================================
# AI 对话助手
# =============================================================================

class AIAssistant:
    """AI 对话助手 - 基于推文内容回答问题"""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model
        self.conversation_history: list[dict] = []
        self.tweets_context: list[Tweet] = []

    def set_context(self, tweets: list[Tweet]) -> None:
        """设置推文上下文"""
        self.tweets_context = tweets
        self.conversation_history = []

    def _build_context(self) -> str:
        """构建推文上下文"""
        if not self.tweets_context:
            return "当前没有加载任何推文数据。"

        lines = [f"以下是最近的 {len(self.tweets_context)} 条推文：\n"]
        for i, tweet in enumerate(self.tweets_context[:50], 1):
            lines.append(
                f"[{i}] @{tweet.author_username} ({tweet.author_name}) - "
                f"{tweet.created_at.strftime('%m-%d %H:%M')}\n"
                f"{tweet.text}\n"
                f"互动: ❤️{tweet.like_count} 🔁{tweet.retweet_count}\n"
            )
        return "\n".join(lines)

    def chat(self, user_message: str) -> str:
        """对话"""
        context = self._build_context()

        system_prompt = f"""你是一个智能推特分析助手。用户会问你关于推文内容的问题。

当前推文上下文：
{context}

你的任务：
1. 根据推文内容回答用户问题
2. 提供有洞察力的分析
3. 如果问题超出推文范围，诚实说明
4. 使用中文回答

如果用户问"总结"、"要点"等，提供结构化的摘要。
如果用户问特定账号或话题，聚焦相关内容分析。"""

        self.conversation_history.append({"role": "user", "content": user_message})

        messages = [
            {"role": "system", "content": system_prompt},
            *self.conversation_history[-10:],  # 保留最近10轮对话
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=1500,
        )

        assistant_message = response.choices[0].message.content
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        return assistant_message

    def ask(self, question: str, tweets: list[Tweet] = None) -> str:
        """快速问答（不保留历史）"""
        if tweets:
            self.set_context(tweets)
        return self.chat(question)

    def clear_history(self) -> None:
        """清除对话历史"""
        self.conversation_history = []


# =============================================================================
# 情绪分析
# =============================================================================

@dataclass
class SentimentResult:
    """情绪分析结果"""
    score: float  # -1 到 1，负面到正面
    label: str  # negative, neutral, positive
    confidence: float
    keywords: list[str] = field(default_factory=list)

    @property
    def emoji(self) -> str:
        if self.score > 0.3:
            return "🟢"
        elif self.score < -0.3:
            return "🔴"
        return "🟡"


@dataclass
class MarketSentiment:
    """市场情绪指标"""
    overall_score: float
    bullish_count: int
    bearish_count: int
    neutral_count: int
    hot_topics: list[str]
    key_signals: list[str]
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def trend(self) -> str:
        if self.overall_score > 0.2:
            return "📈 看涨"
        elif self.overall_score < -0.2:
            return "📉 看跌"
        return "➡️ 震荡"


class SentimentAnalyzer:
    """情绪分析器"""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model
        self.cache: dict[str, SentimentResult] = {}

    def analyze_tweet(self, tweet: Tweet) -> SentimentResult:
        """分析单条推文情绪"""
        # 检查缓存
        cache_key = hashlib.md5(tweet.text.encode()).hexdigest()[:16]
        if cache_key in self.cache:
            return self.cache[cache_key]

        prompt = f"""分析以下推文的情绪，返回 JSON 格式：

推文: {tweet.text}

返回格式:
{{"score": 0.5, "label": "positive", "confidence": 0.8, "keywords": ["关键词1", "关键词2"]}}

score: -1(极度负面) 到 1(极度正面)
label: negative/neutral/positive
confidence: 0-1 置信度
keywords: 影响情绪判断的关键词"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )

        try:
            content = response.choices[0].message.content
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end])
            result = SentimentResult(**data)
        except (json.JSONDecodeError, KeyError):
            result = SentimentResult(score=0, label="neutral", confidence=0.5)

        self.cache[cache_key] = result
        return result

    def analyze_market_sentiment(
        self,
        tweets: list[Tweet],
        topic: str = None,
    ) -> MarketSentiment:
        """分析市场/话题整体情绪"""
        if not tweets:
            return MarketSentiment(
                overall_score=0,
                bullish_count=0,
                bearish_count=0,
                neutral_count=0,
                hot_topics=[],
                key_signals=[],
            )

        # 批量分析
        tweets_text = "\n\n".join([
            f"[@{t.author_username}] {t.text}"
            for t in tweets[:30]
        ])

        topic_hint = f"话题: {topic}\n" if topic else ""

        prompt = f"""{topic_hint}分析以下推文的整体市场情绪，返回 JSON：

{tweets_text}

返回格式:
{{
    "overall_score": 0.3,
    "bullish_count": 10,
    "bearish_count": 5,
    "neutral_count": 15,
    "hot_topics": ["话题1", "话题2"],
    "key_signals": ["信号1: 描述", "信号2: 描述"]
}}

overall_score: -1(极度悲观) 到 1(极度乐观)
bullish_count/bearish_count/neutral_count: 各类推文数量
hot_topics: 热门讨论话题
key_signals: 关键信号和洞察"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=500,
        )

        try:
            content = response.choices[0].message.content
            start = content.find("{")
            end = content.rfind("}") + 1
            data = json.loads(content[start:end])
            return MarketSentiment(**data)
        except (json.JSONDecodeError, KeyError):
            return MarketSentiment(
                overall_score=0,
                bullish_count=0,
                bearish_count=0,
                neutral_count=len(tweets),
                hot_topics=[],
                key_signals=["分析失败"],
            )

    def get_sentiment_trend(
        self,
        tweets: list[Tweet],
        interval_hours: int = 6,
    ) -> list[dict]:
        """获取情绪趋势（按时间段）"""
        if not tweets:
            return []

        # 按时间分组
        now = datetime.now(tweets[0].created_at.tzinfo)
        intervals = []
        current = now

        for _ in range(24 // interval_hours):
            start = current - timedelta(hours=interval_hours)
            interval_tweets = [
                t for t in tweets
                if start <= t.created_at < current
            ]

            if interval_tweets:
                scores = []
                for t in interval_tweets[:10]:  # 每个时段分析10条
                    result = self.analyze_tweet(t)
                    scores.append(result.score)

                avg_score = sum(scores) / len(scores) if scores else 0
                intervals.append({
                    "time": start.strftime("%m-%d %H:%M"),
                    "score": round(avg_score, 2),
                    "count": len(interval_tweets),
                })

            current = start

        return list(reversed(intervals))


# =============================================================================
# 智能提醒系统
# =============================================================================

@dataclass
class AlertRule:
    """提醒规则"""
    id: str
    name: str
    rule_type: str  # keyword, user, engagement, sentiment
    condition: dict
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "AlertRule":
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


@dataclass
class Alert:
    """提醒"""
    rule: AlertRule
    tweet: Tweet
    triggered_at: datetime = field(default_factory=datetime.now)
    message: str = ""


class AlertSystem:
    """智能提醒系统"""

    def __init__(self):
        self.rules_file = config.data_dir / "alert_rules.json"
        self.rules: list[AlertRule] = self._load_rules()
        self.callbacks: list[Callable[[Alert], None]] = []
        self.triggered_ids: set[str] = set()  # 已触发的推文 ID

    def _load_rules(self) -> list[AlertRule]:
        """加载规则"""
        if self.rules_file.exists():
            with open(self.rules_file) as f:
                data = json.load(f)
                return [AlertRule.from_dict(r) for r in data]
        return []

    def _save_rules(self) -> None:
        """保存规则"""
        with open(self.rules_file, "w") as f:
            json.dump([r.to_dict() for r in self.rules], f, indent=2)

    def add_keyword_rule(self, name: str, keywords: list[str]) -> AlertRule:
        """添加关键词规则"""
        rule = AlertRule(
            id=hashlib.md5(f"{name}{datetime.now()}".encode()).hexdigest()[:8],
            name=name,
            rule_type="keyword",
            condition={"keywords": keywords},
        )
        self.rules.append(rule)
        self._save_rules()
        return rule

    def add_user_rule(self, name: str, usernames: list[str]) -> AlertRule:
        """添加用户规则（指定用户发推就提醒）"""
        rule = AlertRule(
            id=hashlib.md5(f"{name}{datetime.now()}".encode()).hexdigest()[:8],
            name=name,
            rule_type="user",
            condition={"usernames": [u.lower() for u in usernames]},
        )
        self.rules.append(rule)
        self._save_rules()
        return rule

    def add_engagement_rule(self, name: str, min_likes: int = 0, min_retweets: int = 0) -> AlertRule:
        """添加互动量规则"""
        rule = AlertRule(
            id=hashlib.md5(f"{name}{datetime.now()}".encode()).hexdigest()[:8],
            name=name,
            rule_type="engagement",
            condition={"min_likes": min_likes, "min_retweets": min_retweets},
        )
        self.rules.append(rule)
        self._save_rules()
        return rule

    def remove_rule(self, rule_id: str) -> bool:
        """移除规则"""
        for i, rule in enumerate(self.rules):
            if rule.id == rule_id:
                self.rules.pop(i)
                self._save_rules()
                return True
        return False

    def toggle_rule(self, rule_id: str) -> bool:
        """切换规则状态"""
        for rule in self.rules:
            if rule.id == rule_id:
                rule.enabled = not rule.enabled
                self._save_rules()
                return rule.enabled
        return False

    def check_tweet(self, tweet: Tweet) -> list[Alert]:
        """检查推文是否触发规则"""
        if tweet.id in self.triggered_ids:
            return []

        alerts = []
        for rule in self.rules:
            if not rule.enabled:
                continue

            triggered = False
            message = ""

            if rule.rule_type == "keyword":
                keywords = rule.condition.get("keywords", [])
                text_lower = tweet.text.lower()
                matched = [k for k in keywords if k.lower() in text_lower]
                if matched:
                    triggered = True
                    message = f"匹配关键词: {', '.join(matched)}"

            elif rule.rule_type == "user":
                usernames = rule.condition.get("usernames", [])
                if tweet.author_username.lower() in usernames:
                    triggered = True
                    message = f"@{tweet.author_username} 发布了新推文"

            elif rule.rule_type == "engagement":
                min_likes = rule.condition.get("min_likes", 0)
                min_retweets = rule.condition.get("min_retweets", 0)
                if tweet.like_count >= min_likes and tweet.retweet_count >= min_retweets:
                    triggered = True
                    message = f"高互动推文: ❤️{tweet.like_count} 🔁{tweet.retweet_count}"

            if triggered:
                alert = Alert(rule=rule, tweet=tweet, message=message)
                alerts.append(alert)
                self.triggered_ids.add(tweet.id)

                # 触发回调
                for callback in self.callbacks:
                    try:
                        callback(alert)
                    except Exception as e:
                        print(f"Alert callback error: {e}")

        return alerts

    def check_tweets(self, tweets: list[Tweet]) -> list[Alert]:
        """批量检查推文"""
        all_alerts = []
        for tweet in tweets:
            alerts = self.check_tweet(tweet)
            all_alerts.extend(alerts)
        return all_alerts

    def on_alert(self, callback: Callable[[Alert], None]) -> None:
        """注册提醒回调"""
        self.callbacks.append(callback)

    def get_rules(self) -> list[AlertRule]:
        """获取所有规则"""
        return self.rules


# =============================================================================
# 知识图谱
# =============================================================================

@dataclass
class GraphNode:
    """图节点"""
    id: str
    label: str
    type: str  # user, topic, tweet
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """图边"""
    source: str
    target: str
    type: str  # mentions, discusses, retweets, similar
    weight: float = 1.0


class KnowledgeGraph:
    """知识图谱 - 账号和话题关系网络"""

    def __init__(self):
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    def build_from_tweets(self, tweets: list[Tweet]) -> None:
        """从推文构建图谱"""
        self.nodes = {}
        self.edges = []

        # 添加用户节点
        user_tweet_count: dict[str, int] = {}
        user_engagement: dict[str, int] = {}

        for tweet in tweets:
            username = tweet.author_username
            if username not in user_tweet_count:
                user_tweet_count[username] = 0
                user_engagement[username] = 0
            user_tweet_count[username] += 1
            user_engagement[username] += tweet.engagement_score

            # 添加用户节点
            if username not in self.nodes:
                self.nodes[username] = GraphNode(
                    id=username,
                    label=f"@{username}",
                    type="user",
                    properties={
                        "name": tweet.author_name,
                        "tweet_count": 0,
                        "total_engagement": 0,
                    },
                )

            self.nodes[username].properties["tweet_count"] = user_tweet_count[username]
            self.nodes[username].properties["total_engagement"] = user_engagement[username]

            # 提取 @mentions
            mentions = re.findall(r"@(\w+)", tweet.text)
            for mention in mentions:
                if mention != username:
                    # 添加被提及用户节点
                    if mention not in self.nodes:
                        self.nodes[mention] = GraphNode(
                            id=mention,
                            label=f"@{mention}",
                            type="user",
                            properties={"mentioned": True},
                        )

                    # 添加边
                    self.edges.append(GraphEdge(
                        source=username,
                        target=mention,
                        type="mentions",
                    ))

            # 提取话题标签
            hashtags = re.findall(r"#(\w+)", tweet.text)
            for tag in hashtags:
                tag_id = f"#{tag}"
                if tag_id not in self.nodes:
                    self.nodes[tag_id] = GraphNode(
                        id=tag_id,
                        label=tag_id,
                        type="topic",
                        properties={"count": 0},
                    )
                self.nodes[tag_id].properties["count"] = \
                    self.nodes[tag_id].properties.get("count", 0) + 1

                self.edges.append(GraphEdge(
                    source=username,
                    target=tag_id,
                    type="discusses",
                ))

    def get_user_connections(self, username: str) -> dict:
        """获取用户连接"""
        mentions_out = []  # 该用户提及的人
        mentions_in = []  # 提及该用户的人
        topics = []  # 讨论的话题

        for edge in self.edges:
            if edge.source == username:
                if edge.type == "mentions":
                    mentions_out.append(edge.target)
                elif edge.type == "discusses":
                    topics.append(edge.target)
            elif edge.target == username and edge.type == "mentions":
                mentions_in.append(edge.source)

        return {
            "username": username,
            "mentions_out": list(set(mentions_out)),
            "mentions_in": list(set(mentions_in)),
            "topics": list(set(topics)),
        }

    def get_topic_users(self, topic: str) -> list[str]:
        """获取讨论某话题的用户"""
        users = []
        topic_id = topic if topic.startswith("#") else f"#{topic}"
        for edge in self.edges:
            if edge.target == topic_id and edge.type == "discusses":
                users.append(edge.source)
        return list(set(users))

    def to_json(self) -> dict:
        """导出为 JSON 格式（用于可视化）"""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.type,
                    **n.properties,
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.type,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
        }

    def get_stats(self) -> dict:
        """获取图谱统计"""
        user_nodes = [n for n in self.nodes.values() if n.type == "user"]
        topic_nodes = [n for n in self.nodes.values() if n.type == "topic"]

        return {
            "total_nodes": len(self.nodes),
            "user_count": len(user_nodes),
            "topic_count": len(topic_nodes),
            "edge_count": len(self.edges),
            "top_users": sorted(
                user_nodes,
                key=lambda n: n.properties.get("total_engagement", 0),
                reverse=True,
            )[:10],
            "top_topics": sorted(
                topic_nodes,
                key=lambda n: n.properties.get("count", 0),
                reverse=True,
            )[:10],
        }


# =============================================================================
# RSS 输出
# =============================================================================

class RSSGenerator:
    """RSS Feed 生成器"""

    def __init__(self):
        self.feed_dir = config.data_dir / "feeds"
        self.feed_dir.mkdir(parents=True, exist_ok=True)

    def generate_feed(
        self,
        tweets: list[Tweet],
        title: str = "X Daily Digest",
        description: str = "每日推特精选",
        link: str = "https://x.com",
    ) -> str:
        """生成 RSS feed"""
        rss = Element("rss", version="2.0")
        channel = SubElement(rss, "channel")

        SubElement(channel, "title").text = title
        SubElement(channel, "description").text = description
        SubElement(channel, "link").text = link
        SubElement(channel, "lastBuildDate").text = datetime.now().strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )

        for tweet in tweets[:50]:
            item = SubElement(channel, "item")
            SubElement(item, "title").text = f"@{tweet.author_username}: {tweet.text[:50]}..."
            SubElement(item, "link").text = tweet.url
            SubElement(item, "description").text = tweet.text
            SubElement(item, "pubDate").text = tweet.created_at.strftime(
                "%a, %d %b %Y %H:%M:%S +0000"
            )
            SubElement(item, "guid").text = tweet.id

        xml_str = tostring(rss, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

    def save_feed(
        self,
        tweets: list[Tweet],
        filename: str = "digest.xml",
        **kwargs,
    ) -> Path:
        """保存 RSS feed 到文件"""
        xml_content = self.generate_feed(tweets, **kwargs)
        filepath = self.feed_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(xml_content)
        return filepath

    def get_feed_url(self, filename: str = "digest.xml") -> str:
        """获取 feed URL（用于本地服务）"""
        return f"/api/rss/{filename}"


# =============================================================================
# Webhook 集成
# =============================================================================

@dataclass
class WebhookConfig:
    """Webhook 配置"""
    id: str
    name: str
    url: str
    events: list[str]  # digest, alert, new_tweets
    enabled: bool = True
    secret: str = ""
    headers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WebhookConfig":
        return cls(**data)


class WebhookManager:
    """Webhook 管理器"""

    def __init__(self):
        self.config_file = config.data_dir / "webhooks.json"
        self.webhooks: list[WebhookConfig] = self._load_config()

    def _load_config(self) -> list[WebhookConfig]:
        """加载配置"""
        if self.config_file.exists():
            with open(self.config_file) as f:
                data = json.load(f)
                return [WebhookConfig.from_dict(w) for w in data]
        return []

    def _save_config(self) -> None:
        """保存配置"""
        with open(self.config_file, "w") as f:
            json.dump([w.to_dict() for w in self.webhooks], f, indent=2)

    def add_webhook(
        self,
        name: str,
        url: str,
        events: list[str],
        secret: str = "",
        headers: dict = None,
    ) -> WebhookConfig:
        """添加 Webhook"""
        webhook = WebhookConfig(
            id=hashlib.md5(f"{name}{url}{datetime.now()}".encode()).hexdigest()[:8],
            name=name,
            url=url,
            events=events,
            secret=secret,
            headers=headers or {},
        )
        self.webhooks.append(webhook)
        self._save_config()
        return webhook

    def remove_webhook(self, webhook_id: str) -> bool:
        """移除 Webhook"""
        for i, webhook in enumerate(self.webhooks):
            if webhook.id == webhook_id:
                self.webhooks.pop(i)
                self._save_config()
                return True
        return False

    def toggle_webhook(self, webhook_id: str) -> bool:
        """切换 Webhook 状态"""
        for webhook in self.webhooks:
            if webhook.id == webhook_id:
                webhook.enabled = not webhook.enabled
                self._save_config()
                return webhook.enabled
        return False

    async def trigger(self, event: str, data: dict) -> list[dict]:
        """触发 Webhook"""
        import aiohttp

        results = []
        for webhook in self.webhooks:
            if not webhook.enabled or event not in webhook.events:
                continue

            payload = {
                "event": event,
                "timestamp": datetime.now().isoformat(),
                "data": data,
            }

            headers = {"Content-Type": "application/json", **webhook.headers}

            # 添加签名
            if webhook.secret:
                import hmac
                signature = hmac.new(
                    webhook.secret.encode(),
                    json.dumps(payload).encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Signature"] = signature

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        webhook.url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        results.append({
                            "webhook_id": webhook.id,
                            "success": resp.status < 400,
                            "status": resp.status,
                        })
            except Exception as e:
                results.append({
                    "webhook_id": webhook.id,
                    "success": False,
                    "error": str(e),
                })

        return results

    def trigger_sync(self, event: str, data: dict) -> list[dict]:
        """同步触发 Webhook"""
        return asyncio.run(self.trigger(event, data))

    def get_webhooks(self) -> list[WebhookConfig]:
        """获取所有 Webhook"""
        return self.webhooks
