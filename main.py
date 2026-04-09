"""
游戏主入口 - 命令行界面
支持通用桌游模式（GameDefinition）和原版时空拍卖行模式
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from src.agents import GMAgent
from src.tools import game_manager
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


def select_game() -> Optional[str]:
    """
    显示游戏选择菜单，返回选中的 game_id 或 None（使用原版模式）。
    """
    from src.core.game_loader import discover_games

    games = discover_games()

    print("\n【选择游戏】")
    print("  0) 🏛️  时空拍卖行（原版模式）")
    for idx, g in enumerate(games, 1):
        source_tag = "内置" if g["source"] == "builtin" else "导入"
        print(f"  {idx}) 🎲 {g['name']}（{source_tag}·通用引擎）")
    print(f"  {len(games) + 1}) 📄 从 PDF 规则书导入新游戏")

    while True:
        try:
            choice = input(f"\n请选择 (0-{len(games) + 1}, 默认 0): ").strip() or "0"
            choice_num = int(choice)
            if choice_num == 0:
                return None  # 原版模式
            if 1 <= choice_num <= len(games):
                selected = games[choice_num - 1]
                print(f"\n已选择: {selected['name']}")
                return selected["id"]
            if choice_num == len(games) + 1:
                return _import_from_pdf()
            print(f"请输入 0 到 {len(games) + 1} 之间的数字")
        except ValueError:
            print("请输入有效数字")


def _import_from_pdf() -> Optional[str]:
    """从 PDF 导入新游戏（需要 API Key）"""
    pdf_path = input("\n请输入 PDF 规则书路径: ").strip()
    if not pdf_path or not Path(pdf_path).exists():
        print("❌ 文件不存在，回退到原版模式")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌ 需要设置 ANTHROPIC_API_KEY 来解析 PDF")
        return None

    print("\n📄 正在解析 PDF 规则书...")
    try:
        import anthropic
        from src.parser.pdf_extractor import PdfExtractor
        from src.parser.llm_extractor import LlmExtractor
        from src.parser.cache_manager import CacheManager
        from src.core.game_loader import save_game_definition

        extractor = PdfExtractor()
        doc = extractor.extract(pdf_path)
        print(f"  ✅ 提取文本完成 ({doc.page_count} 页, {len(doc.blocks)} 个文本块)")

        cache = CacheManager()
        cached = cache.get_game_def(doc.sha256)
        if cached:
            print(f"  ✅ 使用缓存的 GameDefinition: {cached.name}")
            return cached.id

        client = anthropic.Anthropic(api_key=api_key)
        llm = LlmExtractor(client=client)
        print("  🤖 正在用 AI 分析游戏规则（这可能需要 1-2 分钟）...")
        game_def = llm.extract(doc.full_text)
        save_game_definition(game_def)
        cache.set_game_def(doc.sha256, game_def)
        print(f"  ✅ 成功解析游戏: {game_def.name}")
        return game_def.id

    except Exception as e:
        print(f"❌ PDF 解析失败: {e}")
        print("回退到原版模式")
        return None


def get_player_setup(game_name: str = "时空拍卖行") -> list[tuple[str, bool]]:
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


def run_classic_game(players: list[tuple[str, bool]]):
    """运行原版时空拍卖行（向后兼容）"""
    logger = logging.getLogger(__name__)
    print("\n正在初始化时空拍卖行...")
    logger.info(
        "CLI game initialization started (classic mode)",
        extra={"game_id": "-", "action_id": "cli-start"},
    )

    gm = GMAgent()

    try:
        gm.start_game(players)
        _game_loop(gm, game_manager)
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


def run_universal_game(game_id: str, players: list[tuple[str, bool]]):
    """运行通用引擎游戏"""
    logger = logging.getLogger(__name__)
    from src.core.game_loader import load_game_definition
    from src.core.universal_manager import UniversalGameManager
    from src.core.tool_generator import ToolGenerator, ToolRouter
    from src.core.prompt_generator import PromptGenerator

    game_def = load_game_definition(game_id)
    if game_def is None:
        print(f"❌ 找不到游戏定义: {game_id}")
        sys.exit(1)

    print(f"\n正在初始化 {game_def.name}（通用引擎）...")
    logger.info(
        "CLI game initialization started (universal mode, game=%s)",
        game_def.name,
        extra={"game_id": "-", "action_id": "cli-start"},
    )

    # 创建通用引擎组件
    ugm = UniversalGameManager(game_def)
    player_ids = [f"player_{i}" for i in range(len(players))]
    ugm.initialize_game(player_ids, [name for name, _ in players])

    tool_gen = ToolGenerator(game_def)
    tools = tool_gen.generate_tools()
    router = ToolRouter(game_def, ugm)

    prompt_gen = PromptGenerator(game_def)
    system_prompt = prompt_gen.generate()

    print(f"  ✅ 已生成 {len(tools)} 个工具")
    print(f"  ✅ 系统 Prompt 已生成 ({len(system_prompt)} 字)")
    print(f"\n{game_def.name} 通用引擎已就绪")
    print("（注意：通用引擎的完整 GM 集成将在后续版本中提供）")
    print(f"当前游戏状态: {ugm.get_game_state()['current_phase']}")


def _game_loop(gm: GMAgent, mgr):
    """原版游戏主循环"""
    logger = logging.getLogger(__name__)

    gm.start_game if not gm.session else None  # session already started

    while True:
        if gm.session and gm.session.is_waiting_for_human:
            user_input = input("\n你的行动 > ").strip()
            if user_input.lower() in ['quit', 'exit', '退出']:
                logger.info(
                    "CLI player requested exit",
                    extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-exit"},
                )
                print("\n感谢游玩！再见！")
                break
            if user_input.lower() == 'status':
                state = mgr.get_game_state()
                print(f"\n当前状态: 回合 {state['current_round']}, 阶段 {state['current_phase']}")
                print(f"稳定性: {state['stability']}")
                for pid, p in state['players'].items():
                    print(f"  {p['name']}: 💰{p['money']} VP:{p['victory_points']}")
                continue
            if user_input.lower() == 'help':
                print("""
可用命令:
  status  - 查看当前游戏状态
  help    - 显示帮助
  quit    - 退出游戏

行动示例:
  我出价 20
  我放弃
  我用这件文物和你交易
""")
                continue
            gm.process(user_input)
        else:
            continue_input = input("\n[按 Enter 继续，或输入命令] > ").strip()
            if continue_input.lower() in ['quit', 'exit', '退出']:
                logger.info(
                    "CLI player requested exit",
                    extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-exit"},
                )
                print("\n感谢游玩！再见！")
                break
            gm.process(continue_input or "继续游戏")


def run_game():
    """运行游戏"""
    setup_logging()
    print_banner()

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  请先设置 ANTHROPIC_API_KEY 环境变量")
        print("   export ANTHROPIC_API_KEY=your-api-key")
        sys.exit(1)

    game_id = select_game()
    game_name = "时空拍卖行" if game_id is None else game_id
    players = get_player_setup(game_name)
    print(f"\n游戏玩家: {', '.join(name for name, _ in players)}")

    if game_id is None:
        run_classic_game(players)
    else:
        run_universal_game(game_id, players)


if __name__ == "__main__":
    run_game()
