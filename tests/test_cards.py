#!/usr/bin/env python
"""验证所有卡牌数据"""
import sys
sys.path.insert(0, "/Users/yuhaichuan/Documents/board_game_agent")

from src.data import ALL_ARTIFACTS, ALL_FUNCTION_CARDS, ALL_EVENT_CARDS

print("=" * 40)
print("《时空拍卖行》卡牌数据验证")
print("=" * 40)
print(f"文物卡: {len(ALL_ARTIFACTS)} 张")
print(f"功能卡: {len(ALL_FUNCTION_CARDS)} 张")
print(f"事件卡: {len(ALL_EVENT_CARDS)} 张")
print(f"总计: {len(ALL_ARTIFACTS) + len(ALL_FUNCTION_CARDS) + len(ALL_EVENT_CARDS)} 张")
print()

# 列出部分卡牌
print("文物示例:")
for a in ALL_ARTIFACTS[:3]:
    print(f"  - {a.name} ({a.era.value}) 💎{a.base_value} ⏳{a.time_cost}")

print("\n功能卡示例:")
for c in ALL_FUNCTION_CARDS[:3]:
    print(f"  - {c.name}: {c.effect[:30]}...")

print("\n事件卡示例:")
for e in ALL_EVENT_CARDS[:3]:
    print(f"  - {e.name}: {e.effect[:30]}...")

print("\n✓ 所有卡牌数据加载成功!")
