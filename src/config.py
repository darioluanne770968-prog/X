"""配置管理模块"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TwitterConfig:
    """Twitter API 配置"""

    bearer_token: str = field(default_factory=lambda: os.getenv("TWITTER_BEARER_TOKEN", ""))
    api_key: str = field(default_factory=lambda: os.getenv("TWITTER_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("TWITTER_API_SECRET", ""))
    access_token: str = field(default_factory=lambda: os.getenv("TWITTER_ACCESS_TOKEN", ""))
    access_token_secret: str = field(
        default_factory=lambda: os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")
    )


@dataclass
class OpenAIConfig:
    """OpenAI API 配置"""

    api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""

    bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass
class EmailConfig:
    """邮件配置"""

    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    email_to: str = field(default_factory=lambda: os.getenv("EMAIL_TO", ""))

    @property
    def enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_to)


@dataclass
class DigestConfig:
    """摘要配置"""

    hour: int = field(default_factory=lambda: int(os.getenv("DIGEST_HOUR", "8")))
    minute: int = field(default_factory=lambda: int(os.getenv("DIGEST_MINUTE", "0")))
    max_tweets_per_user: int = field(
        default_factory=lambda: int(os.getenv("MAX_TWEETS_PER_USER", "20"))
    )
    language: str = field(default_factory=lambda: os.getenv("DIGEST_LANGUAGE", "zh"))


@dataclass
class Config:
    """全局配置"""

    twitter: TwitterConfig = field(default_factory=TwitterConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
    data_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "data")

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)


config = Config()
