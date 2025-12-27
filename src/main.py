"""X Daily Digest - 主程序入口"""

import asyncio
import argparse
from datetime import datetime

import schedule
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import config
from .twitter_client import TwitterClient
from .summarizer import Summarizer
from .notifier import NotificationManager, ConsoleNotifier

console = Console()


class XDailyDigest:
    """每日 X 摘要主程序"""

    def __init__(self):
        self.twitter = TwitterClient()
        self.summarizer = Summarizer()
        self.notifier = NotificationManager()

    async def generate_and_send_digest(self, hours: int = 24) -> str:
        """生成并发送每日摘要"""
        console.print("\n[bold blue]🚀 开始生成每日摘要...[/bold blue]\n")

        # 1. 获取推文
        console.print("[yellow]📥 正在获取推文...[/yellow]")
        tweets = self.twitter.get_all_following_tweets(hours=hours)

        if not tweets:
            console.print("[red]❌ 没有获取到推文[/red]")
            return "没有获取到推文"

        console.print(f"[green]✅ 共获取 {len(tweets)} 条推文[/green]")

        # 2. 缓存推文
        self.twitter.cache_tweets(tweets)

        # 3. 生成摘要
        console.print("[yellow]🤖 正在生成 AI 摘要...[/yellow]")
        digest = self.summarizer.generate_digest(tweets)
        console.print("[green]✅ 摘要生成完成[/green]")

        # 4. 发送通知
        console.print("[yellow]📤 正在发送通知...[/yellow]")
        title = f"📰 每日 X 摘要 - {datetime.now().strftime('%Y-%m-%d')}"

        results = await self.notifier.send_all(title, digest)
        for channel, success in results.items():
            status = "✅" if success else "⏭️ 跳过"
            console.print(f"  {channel}: {status}")

        # 5. 同时输出到控制台
        console_notifier = ConsoleNotifier()
        await console_notifier.send(title, digest)

        return digest

    def add_accounts(self, usernames: list[str]) -> None:
        """添加关注账号"""
        self.twitter.add_following(usernames)
        console.print(f"[green]✅ 已添加 {len(usernames)} 个账号[/green]")
        self._show_following_list()

    def remove_accounts(self, usernames: list[str]) -> None:
        """移除关注账号"""
        self.twitter.remove_following(usernames)
        console.print(f"[green]✅ 已移除 {len(usernames)} 个账号[/green]")
        self._show_following_list()

    def _show_following_list(self) -> None:
        """显示当前关注列表"""
        usernames = self.twitter.get_following_list()
        if not usernames:
            console.print("[yellow]当前没有关注任何账号[/yellow]")
            return

        table = Table(title="📋 关注列表")
        table.add_column("序号", style="cyan")
        table.add_column("用户名", style="green")

        for i, username in enumerate(usernames, 1):
            table.add_row(str(i), f"@{username}")

        console.print(table)

    async def search_topic(self, query: str, hours: int = 24) -> str:
        """搜索特定话题并生成摘要"""
        console.print(f"\n[bold blue]🔍 搜索话题: {query}[/bold blue]\n")

        tweets = self.twitter.search_tweets(query, hours=hours)

        if not tweets:
            return f"没有找到关于「{query}」的推文"

        console.print(f"[green]✅ 找到 {len(tweets)} 条相关推文[/green]")

        summary = self.summarizer.generate_topic_summary(tweets, query)

        # 输出到控制台
        console_notifier = ConsoleNotifier()
        await console_notifier.send(f"🔍 话题摘要: {query}", summary)

        return summary

    def run_scheduler(self) -> None:
        """运行定时任务"""
        schedule_time = f"{config.digest.hour:02d}:{config.digest.minute:02d}"

        console.print(
            Panel(
                f"⏰ 定时任务已启动\n"
                f"每日 {schedule_time} 发送摘要\n"
                f"按 Ctrl+C 停止",
                title="X Daily Digest",
                border_style="blue",
            )
        )

        def job():
            asyncio.run(self.generate_and_send_digest())

        schedule.every().day.at(schedule_time).do(job)

        while True:
            schedule.run_pending()
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(60))


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="X Daily Digest - 每日推特摘要 Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  x-digest run              立即生成并发送摘要
  x-digest schedule         启动定时任务
  x-digest add elonmusk     添加关注账号
  x-digest remove elonmusk  移除关注账号
  x-digest list             查看关注列表
  x-digest search "AI"      搜索话题
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="立即生成并发送摘要")
    run_parser.add_argument("--hours", type=int, default=24, help="获取最近 N 小时的推文")

    # schedule 命令
    subparsers.add_parser("schedule", help="启动定时任务")

    # add 命令
    add_parser = subparsers.add_parser("add", help="添加关注账号")
    add_parser.add_argument("usernames", nargs="+", help="要添加的用户名（不含@）")

    # remove 命令
    remove_parser = subparsers.add_parser("remove", help="移除关注账号")
    remove_parser.add_argument("usernames", nargs="+", help="要移除的用户名")

    # list 命令
    subparsers.add_parser("list", help="查看关注列表")

    # search 命令
    search_parser = subparsers.add_parser("search", help="搜索话题")
    search_parser.add_argument("query", help="搜索关键词")
    search_parser.add_argument("--hours", type=int, default=24, help="搜索最近 N 小时")

    args = parser.parse_args()

    app = XDailyDigest()

    if args.command == "run":
        asyncio.run(app.generate_and_send_digest(hours=args.hours))

    elif args.command == "schedule":
        app.run_scheduler()

    elif args.command == "add":
        app.add_accounts(args.usernames)

    elif args.command == "remove":
        app.remove_accounts(args.usernames)

    elif args.command == "list":
        app._show_following_list()

    elif args.command == "search":
        asyncio.run(app.search_topic(args.query, hours=args.hours))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
