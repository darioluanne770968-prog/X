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
from .extensions import (
    ThreadExpander,
    Translator,
    ContentFilter,
    MarkdownExporter,
    AccountRecommender,
)

console = Console()


class XDailyDigest:
    """每日 X 摘要主程序"""

    def __init__(self):
        self.twitter = TwitterClient()
        self.summarizer = Summarizer()
        self.notifier = NotificationManager()
        self.thread_expander = ThreadExpander(self.twitter)
        self.translator = Translator()
        self.content_filter = ContentFilter()
        self.exporter = MarkdownExporter()
        self.recommender = AccountRecommender(self.twitter)

    async def generate_and_send_digest(
        self,
        hours: int = 24,
        translate: bool = False,
        export: bool = False,
    ) -> str:
        """生成并发送每日摘要"""
        console.print("\n[bold blue]🚀 开始生成每日摘要...[/bold blue]\n")

        # 1. 获取推文
        console.print("[yellow]📥 正在获取推文...[/yellow]")
        tweets = self.twitter.get_all_following_tweets(hours=hours)

        if not tweets:
            console.print("[red]❌ 没有获取到推文[/red]")
            return "没有获取到推文"

        console.print(f"[green]✅ 共获取 {len(tweets)} 条推文[/green]")

        # 2. 过滤内容
        original_count = len(tweets)
        tweets = self.content_filter.filter_tweets(tweets)
        filtered_count = original_count - len(tweets)
        if filtered_count > 0:
            console.print(f"[yellow]🔇 已过滤 {filtered_count} 条推文[/yellow]")

        # 3. 翻译（可选）
        if translate:
            console.print("[yellow]🌐 正在翻译推文...[/yellow]")
            tweets = self.translator.translate_tweets(tweets)

        # 4. 缓存推文
        self.twitter.cache_tweets(tweets)

        # 5. 生成摘要
        console.print("[yellow]🤖 正在生成 AI 摘要...[/yellow]")
        digest = self.summarizer.generate_digest(tweets)
        console.print("[green]✅ 摘要生成完成[/green]")

        # 6. 导出（可选）
        if export:
            filepath = self.exporter.export_digest(digest)
            console.print(f"[green]📁 已导出到: {filepath}[/green]")

        # 7. 发送通知
        console.print("[yellow]📤 正在发送通知...[/yellow]")
        title = f"📰 每日 X 摘要 - {datetime.now().strftime('%Y-%m-%d')}"

        results = await self.notifier.send_all(title, digest)
        for channel, success in results.items():
            status = "✅" if success else "⏭️ 跳过"
            console.print(f"  {channel}: {status}")

        # 8. 同时输出到控制台
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

    # =========================================================================
    # 新增功能
    # =========================================================================

    def expand_thread(self, tweet_url: str) -> None:
        """展开 Thread"""
        console.print(f"\n[bold blue]🧵 展开 Thread...[/bold blue]\n")

        # 从 URL 提取 tweet ID
        import re
        match = re.search(r"/status/(\d+)", tweet_url)
        if not match:
            console.print("[red]❌ 无效的推文链接[/red]")
            return

        tweet_id = match.group(1)
        thread = self.thread_expander.get_thread(tweet_id)

        if not thread:
            console.print("[red]❌ 无法获取 Thread[/red]")
            return

        console.print(f"[green]✅ 获取到 {len(thread.tweets)} 条推文[/green]\n")

        # 显示 Thread
        console.print(Panel(
            thread.to_markdown(),
            title=f"🧵 Thread by @{thread.author_username}",
            border_style="blue",
        ))

        # 自动导出
        filepath = self.exporter.export_thread(thread)
        console.print(f"\n[green]📁 已导出到: {filepath}[/green]")

    def translate_text(self, text: str, target: str = "zh") -> None:
        """翻译文本"""
        console.print("\n[yellow]🌐 正在翻译...[/yellow]\n")
        translated = self.translator.translate(text, target)
        console.print(Panel(translated, title="翻译结果", border_style="green"))

    def manage_filter(self, action: str, words: list[str] = None) -> None:
        """管理过滤器"""
        if action == "list":
            table = Table(title="🔇 过滤配置")
            table.add_column("类型", style="cyan")
            table.add_column("内容", style="yellow")

            table.add_row(
                "屏蔽词",
                ", ".join(self.content_filter.filter_config.blocked_words) or "(无)"
            )
            table.add_row(
                "屏蔽用户",
                ", ".join(self.content_filter.filter_config.blocked_users) or "(无)"
            )
            table.add_row(
                "最低互动",
                str(self.content_filter.filter_config.min_engagement)
            )
            table.add_row(
                "过滤广告",
                "✅" if self.content_filter.filter_config.filter_ads else "❌"
            )
            table.add_row(
                "过滤转推",
                "✅" if self.content_filter.filter_config.filter_retweets else "❌"
            )

            console.print(table)

        elif action == "add" and words:
            self.content_filter.add_blocked_words(words)
            console.print(f"[green]✅ 已添加屏蔽词: {', '.join(words)}[/green]")

        elif action == "remove" and words:
            self.content_filter.remove_blocked_words(words)
            console.print(f"[green]✅ 已移除屏蔽词: {', '.join(words)}[/green]")

    def export_cached(self) -> None:
        """导出缓存的推文"""
        tweets = self.twitter.load_cached_tweets()
        if not tweets:
            console.print("[yellow]没有缓存的推文[/yellow]")
            return

        filepath = self.exporter.export_tweets(tweets)
        console.print(f"[green]📁 已导出 {len(tweets)} 条推文到: {filepath}[/green]")

    def list_exports(self) -> None:
        """列出导出文件"""
        exports = self.exporter.list_exports()
        if not exports:
            console.print("[yellow]没有导出文件[/yellow]")
            return

        table = Table(title="📁 导出文件")
        table.add_column("文件名", style="cyan")
        table.add_column("大小", style="yellow")
        table.add_column("时间", style="green")

        for path in exports[:20]:
            stat = path.stat()
            size = f"{stat.st_size / 1024:.1f} KB"
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            table.add_row(path.name, size, mtime)

        console.print(table)

    def recommend_accounts(self, username: str = None) -> None:
        """推荐账号"""
        console.print("\n[bold blue]🔍 正在发现优质账号...[/bold blue]\n")

        if username:
            accounts = self.recommender.get_similar_accounts(username)
            console.print(f"[green]与 @{username} 相似的账号:[/green]\n")
        else:
            accounts = self.recommender.discover_from_following()
            console.print("[green]基于你的关注发现的新账号:[/green]\n")

        if not accounts:
            console.print("[yellow]没有找到推荐账号[/yellow]")
            return

        table = Table(title="🌟 推荐账号")
        table.add_column("用户名", style="cyan")
        table.add_column("名称", style="green")
        table.add_column("粉丝", style="yellow")
        table.add_column("简介", style="white", max_width=40)

        for acc in accounts[:15]:
            followers = f"{acc['followers']:,}"
            desc = acc['description'][:40] + "..." if len(acc['description']) > 40 else acc['description']
            table.add_row(f"@{acc['username']}", acc['name'], followers, desc)

        console.print(table)

        # AI 分析
        console.print("\n[yellow]🤖 AI 分析中...[/yellow]\n")
        analysis = self.recommender.analyze_accounts(accounts)
        console.print(Panel(analysis, title="📊 账号分析", border_style="blue"))


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="X Daily Digest - 每日推特摘要 Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  x-digest run                    立即生成并发送摘要
  x-digest run --translate        生成摘要并翻译英文内容
  x-digest run --export           生成摘要并导出 Markdown
  x-digest schedule               启动定时任务

  x-digest add elonmusk           添加关注账号
  x-digest remove elonmusk        移除关注账号
  x-digest list                   查看关注列表

  x-digest search "AI"            搜索话题

  x-digest thread <url>           展开 Thread
  x-digest translate "text"       翻译文本

  x-digest filter list            查看过滤配置
  x-digest filter add 广告 营销   添加屏蔽词
  x-digest filter remove 广告     移除屏蔽词

  x-digest export                 导出缓存的推文
  x-digest exports                查看导出文件列表

  x-digest recommend              发现推荐账号
  x-digest recommend elonmusk     查找与某账号相似的账号
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="立即生成并发送摘要")
    run_parser.add_argument("--hours", type=int, default=24, help="获取最近 N 小时的推文")
    run_parser.add_argument("--translate", "-t", action="store_true", help="翻译英文推文")
    run_parser.add_argument("--export", "-e", action="store_true", help="导出为 Markdown")

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

    # thread 命令
    thread_parser = subparsers.add_parser("thread", help="展开 Thread")
    thread_parser.add_argument("url", help="推文链接")

    # translate 命令
    translate_parser = subparsers.add_parser("translate", help="翻译文本")
    translate_parser.add_argument("text", help="要翻译的文本")
    translate_parser.add_argument("--to", default="zh", help="目标语言 (zh/en)")

    # filter 命令
    filter_parser = subparsers.add_parser("filter", help="管理过滤器")
    filter_parser.add_argument("action", choices=["list", "add", "remove"], help="操作类型")
    filter_parser.add_argument("words", nargs="*", help="屏蔽词列表")

    # export 命令
    subparsers.add_parser("export", help="导出缓存的推文为 Markdown")

    # exports 命令
    subparsers.add_parser("exports", help="查看导出文件列表")

    # recommend 命令
    recommend_parser = subparsers.add_parser("recommend", help="发现推荐账号")
    recommend_parser.add_argument("username", nargs="?", help="基于某账号推荐（可选）")

    args = parser.parse_args()

    app = XDailyDigest()

    if args.command == "run":
        asyncio.run(app.generate_and_send_digest(
            hours=args.hours,
            translate=args.translate,
            export=args.export,
        ))

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

    elif args.command == "thread":
        app.expand_thread(args.url)

    elif args.command == "translate":
        app.translate_text(args.text, args.to)

    elif args.command == "filter":
        app.manage_filter(args.action, args.words)

    elif args.command == "export":
        app.export_cached()

    elif args.command == "exports":
        app.list_exports()

    elif args.command == "recommend":
        app.recommend_accounts(args.username)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
