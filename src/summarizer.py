"""AI 摘要生成模块"""

from datetime import datetime
from openai import OpenAI

from .config import config
from .twitter_client import Tweet


class Summarizer:
    """使用 AI 生成推文摘要"""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model

    def _format_tweets_for_prompt(self, tweets: list[Tweet]) -> str:
        """格式化推文用于 prompt"""
        formatted = []
        for i, tweet in enumerate(tweets, 1):
            formatted.append(
                f"[{i}] @{tweet.author_username} ({tweet.author_name})\n"
                f"内容: {tweet.text}\n"
                f"互动: ❤️{tweet.like_count} 🔁{tweet.retweet_count} 💬{tweet.reply_count}\n"
                f"链接: {tweet.url}\n"
            )
        return "\n".join(formatted)

    def generate_digest(
        self,
        tweets: list[Tweet],
        top_n: int = 20,
        categories: list[str] = None,
    ) -> str:
        """生成每日摘要"""
        if not tweets:
            return "今日没有获取到推文。"

        # 取 top N 条推文
        top_tweets = tweets[:top_n]
        tweets_text = self._format_tweets_for_prompt(top_tweets)

        category_hint = ""
        if categories:
            category_hint = f"请特别关注以下领域的内容: {', '.join(categories)}\n"

        language = "中文" if config.digest.language == "zh" else "English"

        prompt = f"""你是一个专业的信息摘要助手。请分析以下推文，生成一份简洁有价值的每日摘要。

{category_hint}

要求:
1. 使用{language}输出
2. 按主题/领域分类整理
3. 提取关键信息和洞见
4. 标注重要推文的原始链接
5. 忽略广告和无价值内容
6. 突出有争议或热门的讨论

输出格式:
# 📰 每日 X 摘要 - {datetime.now().strftime("%Y-%m-%d")}

## 🔥 今日要点
(3-5 条最重要的信息)

## 📂 分类内容
(按主题分类的详细内容)

## 💡 值得关注
(有意思的观点或讨论)

---

以下是今日推文:

{tweets_text}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的信息整理助手，擅长从社交媒体内容中提取有价值的信息。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )

        return response.choices[0].message.content

    def generate_topic_summary(
        self,
        tweets: list[Tweet],
        topic: str,
    ) -> str:
        """针对特定话题生成摘要"""
        if not tweets:
            return f"没有找到关于「{topic}」的推文。"

        tweets_text = self._format_tweets_for_prompt(tweets)
        language = "中文" if config.digest.language == "zh" else "English"

        prompt = f"""请分析以下关于「{topic}」的推文，生成一份专题摘要。

要求:
1. 使用{language}输出
2. 总结主要观点和讨论方向
3. 识别不同立场和争议点
4. 提取有价值的见解
5. 标注重要推文的原始链接

---

推文内容:

{tweets_text}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的话题分析师，擅长从社交媒体讨论中提取核心观点。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )

        return response.choices[0].message.content

    def extract_insights(self, tweets: list[Tweet]) -> list[str]:
        """提取关键洞见"""
        if not tweets:
            return []

        tweets_text = self._format_tweets_for_prompt(tweets[:30])

        prompt = f"""从以下推文中提取 5-10 条最有价值的洞见或观点。
每条洞见用一句话概括，并注明来源账号。

推文:
{tweets_text}

输出格式（JSON 数组）:
["洞见1 - @来源", "洞见2 - @来源", ...]
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=800,
        )

        try:
            import json
            content = response.choices[0].message.content
            # 提取 JSON 部分
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return []

    def filter_quality_tweets(self, tweets: list[Tweet], min_score: int = 50) -> list[Tweet]:
        """过滤高质量推文"""
        return [t for t in tweets if t.engagement_score >= min_score]

    def categorize_tweets(self, tweets: list[Tweet]) -> dict[str, list[Tweet]]:
        """对推文进行分类"""
        if not tweets:
            return {}

        tweets_text = self._format_tweets_for_prompt(tweets[:50])

        prompt = f"""请将以下推文按主题分类，返回 JSON 格式。

分类建议: 技术/AI, 创业/商业, 观点/思考, 新闻/资讯, 生活/其他

推文:
{tweets_text}

输出格式:
{{"分类名": [推文序号列表], ...}}
例如: {{"技术/AI": [1, 3, 5], "创业/商业": [2, 4]}}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )

        try:
            import json
            content = response.choices[0].message.content
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                categories = json.loads(content[start:end])
                result = {}
                for cat, indices in categories.items():
                    result[cat] = [tweets[i - 1] for i in indices if 0 < i <= len(tweets)]
                return result
        except (json.JSONDecodeError, ValueError, IndexError):
            pass

        return {"未分类": tweets}
