"""AI 摘要生成模块"""

from datetime import datetime
from openai import OpenAI

from .config import config
from .twitter_client import Tweet


# AI 总结风格定义
SUMMARY_STYLES = {
    "default": {
        "name": "默认",
        "description": "标准摘要格式，按主题分类整理",
        "system_prompt": "你是一个专业的信息整理助手，擅长从社交媒体内容中提取有价值的信息。",
        "style_hint": "请按主题分类整理，提取关键信息和洞见。"
    },
    "concise": {
        "name": "简洁",
        "description": "精简版摘要，只保留最核心信息",
        "system_prompt": "你是一个极简主义的信息整理助手，只提取最关键的信息。",
        "style_hint": "请用最简洁的方式总结，每个要点不超过一句话，总共不超过10个要点。"
    },
    "detailed": {
        "name": "详细",
        "description": "详尽分析，包含背景和深度解读",
        "system_prompt": "你是一个深度分析师，擅长对信息进行全面深入的解读。",
        "style_hint": "请进行详细分析，包括背景信息、深度解读、潜在影响和相关联系。"
    },
    "humorous": {
        "name": "幽默",
        "description": "轻松幽默的风格，让阅读更有趣",
        "system_prompt": "你是一个幽默风趣的信息整理助手，善于用轻松的方式传递信息。",
        "style_hint": "请用轻松幽默的语气总结，可以适当加入表情和俏皮话，但不要失去信息价值。"
    },
    "professional": {
        "name": "专业",
        "description": "正式专业的商业报告风格",
        "system_prompt": "你是一个专业的商业分析师，提供严谨的市场情报。",
        "style_hint": "请使用正式、专业的语言，像商业报告一样结构化，包含执行摘要和详细分析。"
    },
    "bullet": {
        "name": "条目",
        "description": "纯粹的条目列表，快速浏览",
        "system_prompt": "你是一个高效的信息整理助手，专注于条目化输出。",
        "style_hint": "请只使用条目列表格式输出，不要段落文字，每条一个独立信息点。"
    }
}


class Summarizer:
    """使用 AI 生成推文摘要"""

    def __init__(self):
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model
        self.available_styles = SUMMARY_STYLES

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

    def get_styles(self) -> dict:
        """获取所有可用的总结风格"""
        return {k: {"name": v["name"], "description": v["description"]}
                for k, v in self.available_styles.items()}

    def generate_digest(
        self,
        tweets: list[Tweet],
        top_n: int = 20,
        categories: list[str] = None,
        style: str = "default",
    ) -> str:
        """生成每日摘要

        Args:
            tweets: 推文列表
            top_n: 取前 N 条推文
            categories: 关注的领域
            style: 总结风格 (default/concise/detailed/humorous/professional/bullet)
        """
        if not tweets:
            return "今日没有获取到推文。"

        # 获取风格配置
        style_config = self.available_styles.get(style, self.available_styles["default"])

        # 取 top N 条推文
        top_tweets = tweets[:top_n]
        tweets_text = self._format_tweets_for_prompt(top_tweets)

        category_hint = ""
        if categories:
            category_hint = f"请特别关注以下领域的内容: {', '.join(categories)}\n"

        language = "中文" if config.digest.language == "zh" else "English"

        # 根据风格调整输出格式
        if style == "concise":
            output_format = f"""
# 📰 每日 X 摘要 - {datetime.now().strftime("%Y-%m-%d")}

## 核心要点
(最多10条精简要点)
"""
        elif style == "bullet":
            output_format = f"""
# 📰 每日 X 摘要 - {datetime.now().strftime("%Y-%m-%d")}

(纯条目列表)
"""
        elif style == "professional":
            output_format = f"""
# 📊 X 信息简报 - {datetime.now().strftime("%Y-%m-%d")}

## 执行摘要
(核心发现概述)

## 详细分析
(按领域深度分析)

## 趋势与建议
(市场趋势和行动建议)
"""
        else:
            output_format = f"""
# 📰 每日 X 摘要 - {datetime.now().strftime("%Y-%m-%d")}

## 🔥 今日要点
(3-5 条最重要的信息)

## 📂 分类内容
(按主题分类的详细内容)

## 💡 值得关注
(有意思的观点或讨论)
"""

        prompt = f"""请分析以下推文，生成一份摘要。

{category_hint}

风格要求: {style_config["style_hint"]}

基本要求:
1. 使用{language}输出
2. 提取关键信息和洞见
3. 标注重要推文的原始链接
4. 忽略广告和无价值内容

输出格式:
{output_format}

---

以下是今日推文:

{tweets_text}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": style_config["system_prompt"],
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7 if style != "professional" else 0.5,
            max_tokens=2000 if style != "concise" else 1000,
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
