"""通知推送模块 - 支持 Telegram、邮件和 Discord"""

import smtplib
import asyncio
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from abc import ABC, abstractmethod

import aiohttp

from .config import config


class Notifier(ABC):
    """通知器基类"""

    @abstractmethod
    async def send(self, title: str, content: str) -> bool:
        """发送通知"""
        pass

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """是否启用"""
        pass


class TelegramNotifier(Notifier):
    """Telegram 通知"""

    def __init__(self):
        self.bot_token = config.telegram.bot_token
        self.chat_id = config.telegram.chat_id
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def enabled(self) -> bool:
        return config.telegram.enabled

    async def send(self, title: str, content: str) -> bool:
        """发送 Telegram 消息"""
        if not self.enabled:
            print("Telegram 未配置，跳过发送")
            return False

        # Telegram 消息有长度限制，需要分段发送
        full_message = f"*{title}*\n\n{content}"
        messages = self._split_message(full_message, max_length=4000)

        async with aiohttp.ClientSession() as session:
            for msg in messages:
                try:
                    async with session.post(
                        f"{self.api_base}/sendMessage",
                        json={
                            "chat_id": self.chat_id,
                            "text": msg,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True,
                        },
                    ) as resp:
                        if resp.status != 200:
                            error = await resp.text()
                            print(f"Telegram 发送失败: {error}")
                            return False
                except Exception as e:
                    print(f"Telegram 发送异常: {e}")
                    return False

        print("Telegram 消息发送成功")
        return True

    def _split_message(self, text: str, max_length: int = 4000) -> list[str]:
        """分割长消息"""
        if len(text) <= max_length:
            return [text]

        messages = []
        while text:
            if len(text) <= max_length:
                messages.append(text)
                break

            # 找到合适的分割点
            split_point = text.rfind("\n", 0, max_length)
            if split_point == -1:
                split_point = max_length

            messages.append(text[:split_point])
            text = text[split_point:].lstrip()

        return messages


class EmailNotifier(Notifier):
    """邮件通知"""

    def __init__(self):
        self.smtp_host = config.email.smtp_host
        self.smtp_port = config.email.smtp_port
        self.smtp_user = config.email.smtp_user
        self.smtp_password = config.email.smtp_password
        self.email_to = config.email.email_to

    @property
    def enabled(self) -> bool:
        return config.email.enabled

    async def send(self, title: str, content: str) -> bool:
        """发送邮件"""
        if not self.enabled:
            print("邮件未配置，跳过发送")
            return False

        # 在线程池中运行同步邮件发送
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_sync, title, content)

    def _send_sync(self, title: str, content: str) -> bool:
        """同步发送邮件"""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = title
            msg["From"] = self.smtp_user
            msg["To"] = self.email_to

            # 纯文本版本
            text_part = MIMEText(content, "plain", "utf-8")
            msg.attach(text_part)

            # HTML 版本（将 Markdown 简单转换）
            html_content = self._markdown_to_html(content)
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, [self.email_to], msg.as_string())

            print("邮件发送成功")
            return True

        except Exception as e:
            print(f"邮件发送失败: {e}")
            return False

    def _markdown_to_html(self, md: str) -> str:
        """简单的 Markdown 转 HTML"""
        import re

        html = md

        # 标题
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

        # 粗体和斜体
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

        # 链接
        html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)

        # 换行
        html = html.replace("\n", "<br>\n")

        return f"""
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                       line-height: 1.6; padding: 20px; max-width: 800px; margin: 0 auto; }}
                h1, h2, h3 {{ color: #1da1f2; }}
                a {{ color: #1da1f2; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>{html}</body>
        </html>
        """


class ConsoleNotifier(Notifier):
    """控制台输出（用于测试）"""

    @property
    def enabled(self) -> bool:
        return True

    async def send(self, title: str, content: str) -> bool:
        print("\n" + "=" * 60)
        print(f"📬 {title}")
        print("=" * 60)
        print(content)
        print("=" * 60 + "\n")
        return True


class DiscordNotifier(Notifier):
    """Discord Webhook 通知"""

    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url
        self._enabled = bool(webhook_url)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def send(self, title: str, content: str) -> bool:
        """发送 Discord 消息"""
        if not self.enabled:
            print("Discord Webhook 未配置，跳过发送")
            return False

        # Discord embed 格式
        embed = {
            "title": title,
            "description": content[:4096],  # Discord 限制
            "color": 0x1DA1F2,  # Twitter 蓝色
            "timestamp": datetime.now().isoformat(),
            "footer": {
                "text": "X Daily Digest"
            }
        }

        # 如果内容太长，分割发送
        messages = self._split_content(content, max_length=4096)

        async with aiohttp.ClientSession() as session:
            for i, msg_content in enumerate(messages):
                payload = {
                    "embeds": [{
                        "title": title if i == 0 else f"{title} (续 {i+1})",
                        "description": msg_content,
                        "color": 0x1DA1F2,
                    }]
                }

                try:
                    async with session.post(
                        self.webhook_url,
                        json=payload,
                    ) as resp:
                        if resp.status not in (200, 204):
                            error = await resp.text()
                            print(f"Discord 发送失败: {error}")
                            return False
                except Exception as e:
                    print(f"Discord 发送异常: {e}")
                    return False

        print("Discord 消息发送成功")
        return True

    def _split_content(self, text: str, max_length: int = 4096) -> list[str]:
        """分割长内容"""
        if len(text) <= max_length:
            return [text]

        messages = []
        while text:
            if len(text) <= max_length:
                messages.append(text)
                break

            split_point = text.rfind("\n", 0, max_length)
            if split_point == -1:
                split_point = max_length

            messages.append(text[:split_point])
            text = text[split_point:].lstrip()

        return messages


class NotificationManager:
    """通知管理器 - 统一管理多个通知渠道"""

    def __init__(self, discord_webhooks: list[str] = None):
        self.notifiers: list[Notifier] = [
            TelegramNotifier(),
            EmailNotifier(),
        ]
        # 添加 Discord webhooks
        if discord_webhooks:
            for webhook_url in discord_webhooks:
                self.notifiers.append(DiscordNotifier(webhook_url))

    def add_discord_webhook(self, webhook_url: str) -> None:
        """动态添加 Discord webhook"""
        self.notifiers.append(DiscordNotifier(webhook_url))

    async def send_all(self, title: str, content: str) -> dict[str, bool]:
        """通过所有启用的渠道发送通知"""
        results = {}

        for notifier in self.notifiers:
            name = notifier.__class__.__name__
            if notifier.enabled:
                results[name] = await notifier.send(title, content)
            else:
                results[name] = False

        return results

    async def send_telegram(self, title: str, content: str) -> bool:
        """只发送 Telegram"""
        notifier = TelegramNotifier()
        if notifier.enabled:
            return await notifier.send(title, content)
        return False

    async def send_email(self, title: str, content: str) -> bool:
        """只发送邮件"""
        notifier = EmailNotifier()
        if notifier.enabled:
            return await notifier.send(title, content)
        return False

    async def send_discord(self, title: str, content: str, webhook_url: str) -> bool:
        """发送到指定的 Discord webhook"""
        notifier = DiscordNotifier(webhook_url)
        if notifier.enabled:
            return await notifier.send(title, content)
        return False
