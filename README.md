# X Daily Digest 📰

每日 X/Twitter 摘要 Bot - 自动抓取推文，AI 生成精华摘要，推送到 Telegram/邮箱。

**告别无限刷推，每天只看精华！**

## 功能特性

### 核心功能
- 🐦 **自动抓取** - 获取关注账号的最新推文
- 🤖 **AI 摘要** - 使用 GPT 生成结构化摘要
- 📊 **智能排序** - 按互动热度筛选高质量内容
- 🔍 **话题搜索** - 搜索特定话题并生成专题报告
- 📬 **多渠道推送** - 支持 Telegram、邮件
- ⏰ **定时任务** - 每天固定时间自动发送

### 扩展功能
- 🧵 **Thread 展开** - 把长 Thread 合并成完整文章，方便阅读
- 🌐 **推文翻译** - 自动翻译英文推文为中文
- 🔇 **内容过滤** - 屏蔽词、过滤广告、过滤转推
- 📁 **Markdown 导出** - 导出推文和摘要为 Markdown 文件
- 🌟 **账号推荐** - 发现优质账号，扩展信息源

## 快速开始

### 1. 安装依赖

```bash
cd X

# 安装依赖 (推荐使用 uv)
uv pip install -e .

# 或者使用 pip
pip install -e .
```

### 2. 配置 API

复制配置文件并填写你的 API 密钥：

```bash
cp .env.example .env
```

需要配置的 API：

| API | 获取地址 | 必需 |
|-----|---------|------|
| Twitter API | https://developer.twitter.com/en/portal/dashboard | ✅ |
| OpenAI API | https://platform.openai.com/api-keys | ✅ |
| Telegram Bot | @BotFather | 可选 |
| 邮件 SMTP | 你的邮箱设置 | 可选 |

### 3. 添加关注账号

```bash
x-digest add elonmusk sama karpathy
```

### 4. 运行

```bash
# 立即生成摘要
x-digest run

# 启动定时任务（每天 8:00 自动发送）
x-digest schedule
```

## 命令参考

### 基础命令

```bash
# 生成摘要
x-digest run                    # 立即生成并发送摘要
x-digest run --hours 12         # 只获取最近 12 小时的推文
x-digest run --translate        # 生成摘要并翻译英文内容
x-digest run --export           # 生成摘要并导出 Markdown

# 定时任务
x-digest schedule               # 启动定时任务

# 账号管理
x-digest add <usernames>        # 添加关注账号
x-digest remove <usernames>     # 移除关注账号
x-digest list                   # 查看关注列表

# 话题搜索
x-digest search "AI"            # 搜索话题并生成摘要
x-digest search "GPT" --hours 48
```

### 扩展命令

```bash
# Thread 展开
x-digest thread <推文链接>      # 展开 Thread 并导出

# 翻译
x-digest translate "Hello world"     # 翻译文本
x-digest translate "你好" --to en    # 翻译为英文

# 内容过滤
x-digest filter list            # 查看过滤配置
x-digest filter add 广告 营销   # 添加屏蔽词
x-digest filter remove 广告     # 移除屏蔽词

# 导出
x-digest export                 # 导出缓存的推文为 Markdown
x-digest exports                # 查看导出文件列表

# 账号推荐
x-digest recommend              # 基于关注发现新账号
x-digest recommend elonmusk     # 查找与某账号相似的账号
```

## 配置说明

在 `.env` 文件中可以配置：

```bash
# 摘要时间（每天几点发送）
DIGEST_HOUR=8
DIGEST_MINUTE=0

# 每个账号最多获取多少条推文
MAX_TWEETS_PER_USER=20

# 摘要语言 (zh/en)
DIGEST_LANGUAGE=zh

# AI 模型
OPENAI_MODEL=gpt-4o-mini
```

## 项目结构

```
X/
├── src/
│   ├── __init__.py
│   ├── config.py          # 配置管理
│   ├── twitter_client.py  # Twitter API 客户端
│   ├── summarizer.py      # AI 摘要生成
│   ├── notifier.py        # 通知推送
│   ├── extensions.py      # 扩展功能（Thread/翻译/过滤/导出/推荐）
│   └── main.py            # 主程序入口
├── data/
│   ├── following.json     # 关注列表
│   ├── filter_config.json # 过滤配置
│   ├── tweets_cache.json  # 推文缓存
│   └── exports/           # 导出文件目录
├── .env.example
├── pyproject.toml
└── README.md
```

## 获取 Twitter API

1. 访问 [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
2. 创建一个项目和应用
3. 申请 **Basic** 或更高级别的访问权限
4. 生成 Bearer Token 和 Access Token

## 获取 Telegram Bot

1. 在 Telegram 中搜索 `@BotFather`
2. 发送 `/newbot` 创建 Bot
3. 获取 Bot Token
4. 与 Bot 对话，然后访问 `https://api.telegram.org/bot<TOKEN>/getUpdates` 获取 Chat ID

## 进阶用法

### 作为 Python 库使用

```python
from src.twitter_client import TwitterClient
from src.summarizer import Summarizer
from src.extensions import Translator, ContentFilter, ThreadExpander

# 获取推文
client = TwitterClient()
tweets = client.get_user_tweets("elonmusk", hours=24)

# 过滤内容
filter = ContentFilter()
filter.add_blocked_words(["广告", "营销"])
tweets = filter.filter_tweets(tweets)

# 翻译推文
translator = Translator()
tweets = translator.translate_tweets(tweets, target_lang="zh")

# 生成摘要
summarizer = Summarizer()
digest = summarizer.generate_digest(tweets)
print(digest)
```

### 展开 Thread

```python
from src.extensions import ThreadExpander

expander = ThreadExpander()
thread = expander.get_thread("1234567890")

print(thread.full_text)        # 完整文本
print(thread.to_markdown())    # Markdown 格式
```

### 发现优质账号

```python
from src.extensions import AccountRecommender

recommender = AccountRecommender()

# 基于关注列表发现
accounts = recommender.discover_from_following()

# 分析账号质量
analysis = recommender.analyze_accounts(accounts)
print(analysis)
```

## License

MIT
