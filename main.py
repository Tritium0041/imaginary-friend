"""
游戏主入口 - 命令行界面
基于文档型存储引擎（DocStore + rules.md）
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from src.agents import GMAgent, GMConfig
from src.utils import setup_logging


def print_banner():
    """打印游戏横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║          🎲  通用桌游 Agent 系统  🎲                          ║
║          Universal Board Game Agent                           ║
║                                                               ║
║         支持任意桌游 · 由 AI 驱动的智能体验                  ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def select_game() -> str:
    """显示游戏选择菜单，返回选中的 game_id。"""
    from src.core.game_loader import discover_games

    games = discover_games()

    if not games:
        print("❌ 没有找到任何游戏定义")
        sys.exit(1)

    print("\n【选择游戏】")
    for idx, g in enumerate(games, 1):
        source_tag = "内置" if g["source"] == "builtin" else "导入"
        print(f"  {idx}) 🎲 {g['name']}（{source_tag}）")
    print(f"  {len(games) + 1}) 📄 从规则书导入新游戏（PDF/DOCX/MD）")

    while True:
        try:
            choice = input(f"\n请选择 (1-{len(games) + 1}, 默认 1): ").strip() or "1"
            choice_num = int(choice)
            if 1 <= choice_num <= len(games):
                selected = games[choice_num - 1]
                print(f"\n已选择: {selected['name']}")
                return selected["id"]
            if choice_num == len(games) + 1:
                result = _import_from_file()
                if result:
                    return result
                continue
            print(f"请输入 1 到 {len(games) + 1} 之间的数字")
        except ValueError:
            print("请输入有效数字")


def _import_from_file() -> Optional[str]:
    """从规则书文件导入新游戏（支持 PDF/DOCX/MD）"""
    file_path = input("\n请输入规则书路径（支持 .pdf .docx .md）: ").strip()
    if not file_path or not Path(file_path).exists():
        print("❌ 文件不存在")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌ 需要设置 ANTHROPIC_API_KEY 来解析规则书")
        return None

    print("\n📄 正在解析规则书...")
    try:
        import anthropic
        from src.parser.document_parser import parse_file
        from src.parser.rule_cleaner import RuleCleaner
        from src.parser.cache_manager import CacheManager
        from src.core.game_loader import save_game_rules

        raw_doc = parse_file(file_path)
        print(f"  ✅ 提取文本完成 ({len(raw_doc.raw_text)} 字符)")

        cache = CacheManager()

        cached = cache.get_rules(raw_doc.sha256)
        if cached:
            rules_md, metadata = cached
            game_name = metadata.get("game_name", "Unknown")
            print(f"  ✅ 使用缓存: {game_name}")
            game_id = raw_doc.sha256[:8]
            save_game_rules(game_id, rules_md, metadata)
            return game_id

        client = anthropic.Anthropic(api_key=api_key)
        cleaner = RuleCleaner(client=client)
        print("  🤖 正在用 AI 清洗规则书（这可能需要 1-2 分钟）...")
        result = cleaner.clean(raw_doc.raw_text)

        cache.set_rules(raw_doc.sha256, result.rules_md, result.metadata)

        game_id = raw_doc.sha256[:8]
        save_game_rules(game_id, result.rules_md, result.metadata)

        game_name = result.metadata.get("game_name", "Unknown")
        print(f"  ✅ 成功解析游戏: {game_name}")
        return game_id

    except Exception as e:
        print(f"❌ 规则书解析失败: {e}")
        return None


def get_player_setup(game_name: str) -> list[tuple[str, bool]]:
    """获取玩家设置"""
    print(f"\n【{game_name} · 游戏设置】")

    human_name = input("请输入你的名字 (默认: 玩家): ").strip() or "玩家"

    while True:
        try:
            ai_count = int(input("选择 AI 对手数量 (2-4, 默认: 2): ").strip() or "2")
            if 2 <= ai_count <= 4:
                break
            print("请输入 2-4 之间的数字")
        except ValueError:
            print("请输入有效数字")

    players = [(human_name, True)]
    for i in range(ai_count):
        players.append((f"AI玩家{i+1}", False))

    return players


def run_game_cli(game_id: str, players: list[tuple[str, bool]]):
    """运行游戏（CLI 模式）"""
    logger = logging.getLogger(__name__)
    from src.core.game_loader import load_game_rules

    result = load_game_rules(game_id)
    if result is None:
        print(f"❌ 找不到游戏: {game_id}")
        sys.exit(1)

    rules_md, metadata = result
    game_name = metadata.get("game_name", game_id)

    print(f"\n正在初始化 {game_name}...")
    logger.info(
        "CLI game initialization started (game=%s)",
        game_name,
        extra={"game_id": "-", "action_id": "cli-start"},
    )

    gm = GMAgent(
        rules_md=rules_md,
        metadata=metadata,
        config=GMConfig(),
    )

    try:
        gm.start_game(players)
        print(f"\n🎲 {game_name} 已就绪！")
        _game_loop(gm)
    except KeyboardInterrupt:
        logger.warning(
            "CLI interrupted by keyboard",
            extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-interrupt"},
        )
        print("\n\n游戏中断。再见！")
    except Exception as e:
        logger.exception(
            "CLI game crashed: %s",
            e,
            extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-error"},
        )
        print(f"\n❌ 发生错误: {e}")
        raise


def _game_loop(gm: GMAgent):
    """通用游戏主循环"""
    while True:
        if gm.session and gm.session.is_waiting_for_human:
            user_input = input("\n你的行动 > ").strip()
            if user_input.lower() in ['quit', 'exit', '退出']:
                print("\n感谢游玩！再见！")
                break
            if user_input.lower() == 'help':
                print("\n可用命令: quit/exit/退出 退出游戏, help 显示帮助")
                continue
            gm.process(user_input)
        else:
            continue_input = input("\n[按 Enter 继续，或输入 quit 退出] > ").strip()
            if continue_input.lower() in ['quit', 'exit', '退出']:
                print("\n感谢游玩！再见！")
                break
            gm.process(continue_input or "继续游戏")


def run_game():
    """运行游戏"""
    setup_logging()
    print_banner()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  请先设置 ANTHROPIC_API_KEY 环境变量")
        print("   export ANTHROPIC_API_KEY=your-api-key")
        sys.exit(1)

    game_id = select_game()

    from src.core.game_loader import load_game_rules
    result = load_game_rules(game_id)
    game_name = result[1].get("game_name", game_id) if result else game_id

    players = get_player_setup(game_name)
    print(f"\n游戏玩家: {', '.join(name for name, _ in players)}")

    run_game_cli(game_id, players)


if __name__ == "__main__":
    run_game()
