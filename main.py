"""
游戏主入口 - 命令行界面
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from src.agents import GMAgent
from src.tools import game_manager
from src.utils import setup_logging


def print_banner():
    """打印游戏横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║              🏛️  时 空 拍 卖 行  🏛️                          ║
║              Chronos Auction House                            ║
║                                                               ║
║           一个由 AI 驱动的单人桌游体验                        ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def get_player_setup() -> list[tuple[str, bool]]:
    """获取玩家设置"""
    print("\n【游戏设置】")
    
    # 人类玩家名称
    human_name = input("请输入你的名字 (默认: 玩家): ").strip() or "玩家"
    
    # AI 玩家数量
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


def run_game():
    """运行游戏"""
    setup_logging()
    logger = logging.getLogger(__name__)
    print_banner()
    
    # 检查 API Key
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  请先设置 ANTHROPIC_API_KEY 环境变量")
        print("   export ANTHROPIC_API_KEY=your-api-key")
        sys.exit(1)
    
    # 获取玩家设置
    players = get_player_setup()
    
    print(f"\n游戏玩家: {', '.join(name for name, _ in players)}")
    print("\n正在初始化游戏...")
    logger.info(
        "CLI game initialization started",
        extra={"game_id": "-", "action_id": "cli-start"},
    )
    
    # 创建 GM
    gm = GMAgent()
    
    try:
        # 开始游戏
        gm.start_game(players)
        
        # 游戏主循环
        while True:
            if gm.session and gm.session.is_waiting_for_human:
                # 等待人类输入
                user_input = input("\n你的行动 > ").strip()
                if user_input.lower() in ['quit', 'exit', '退出']:
                    logger.info(
                        "CLI player requested exit",
                        extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-exit"},
                    )
                    print("\n感谢游玩！再见！")
                    break
                if user_input.lower() == 'status':
                    state = game_manager.get_game_state()
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
                
                # 处理玩家输入
                gm.process(user_input)
            else:
                # 让 GM 继续推进游戏
                continue_input = input("\n[按 Enter 继续，或输入命令] > ").strip()
                if continue_input.lower() in ['quit', 'exit', '退出']:
                    logger.info(
                        "CLI player requested exit",
                        extra={"game_id": gm.session.game_id if gm.session else "-", "action_id": "cli-exit"},
                    )
                    print("\n感谢游玩！再见！")
                    break
                gm.process(continue_input or "继续游戏")
    
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


if __name__ == "__main__":
    run_game()
