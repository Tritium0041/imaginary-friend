"""
游戏工具测试
"""
import sys
from typing import Optional
sys.path.insert(0, "/Users/yuhaichuan/Documents/board_game_agent")

from src.tools import game_manager


def _find_card_location(private_state: dict, card_id: str) -> Optional[str]:
    for pid, pdata in private_state["players"].items():
        if any(card["id"] == card_id for card in pdata["function_cards"]):
            return pid
    if any(card["id"] == card_id for card in private_state["global_state"]["card_deck"]):
        return "deck"
    if any(card["id"] == card_id for card in private_state["global_state"]["card_discard_pile"]):
        return "card_discard"
    return None


def _find_card_name(private_state: dict, card_id: str) -> Optional[str]:
    for pdata in private_state["players"].values():
        for card in pdata["function_cards"]:
            if card["id"] == card_id:
                return card["name"]
    for card in private_state["global_state"]["card_deck"]:
        if card["id"] == card_id:
            return card["name"]
    for card in private_state["global_state"]["card_discard_pile"]:
        if card["id"] == card_id:
            return card["name"]
    return None


def _ensure_card_in_player(card_id: str, player_id: str = "player_0"):
    private_state = game_manager.get_game_state(include_private=True)
    source_location = _find_card_location(private_state, card_id)
    card_name = _find_card_name(private_state, card_id)
    assert source_location is not None
    assert card_name is not None
    if source_location != player_id:
        transfer = game_manager.transfer_item("card", card_name, source_location, player_id)
        assert transfer["success"] is True


def test_game_initialization():
    """测试游戏初始化"""
    result = game_manager.initialize_game(
        game_id="test001",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=100,
    )
    
    assert result["success"] is True
    assert result["player_count"] == 3
    assert result["initial_cards_dealt"] == 6
    assert result["initial_auction_pool_count"] == 4
    assert result["initial_event_count"] == 2
    print("✓ 游戏初始化测试通过")


def test_get_state():
    """测试状态获取"""
    state = game_manager.get_game_state()
    
    assert "players" in state
    assert len(state["players"]) == 3
    assert state["current_round"] == 1
    assert len(state["event_area"]) == 2
    assert state["function_deck_count"] == 18
    sample_player = next(iter(state["players"].values()))
    assert "artifacts" in sample_player
    assert isinstance(sample_player["artifacts"], list)
    print("✓ 状态获取测试通过")


def test_update_player_asset():
    """测试资产更新"""
    result = game_manager.update_player_asset(
        player_id="player_0",
        money_delta=-30,
        vp_delta=5,
    )
    
    assert result["success"] is True
    assert result["new_money"] == 70
    assert result["new_vp"] == 5
    print("✓ 资产更新测试通过")


def test_insufficient_money():
    """测试资金不足"""
    result = game_manager.update_player_asset(
        player_id="player_0",
        money_delta=-100,
    )
    
    assert "error" in result
    print("✓ 资金不足检测测试通过")


def test_add_artifact():
    """测试添加文物"""
    state_before = game_manager.get_game_state()
    before_count = len(state_before["auction_pool"])

    result = game_manager.add_artifact_to_pool(
        artifact_id="art001",
        name="远古神器",
        era="ancient",
        base_value=50,
        auction_type="open",
    )
    
    assert result["success"] is True
    
    state = game_manager.get_game_state()
    assert len(state["auction_pool"]) == before_count + 1
    print("✓ 添加文物测试通过")


def test_sealed_bid():
    """测试密封竞标"""
    # 添加密封竞标物品（使用合法时代）
    game_manager.add_artifact_to_pool(
        artifact_id="art002",
        name="未来圣杯",
        era="future",
        base_value=80,
        auction_type="sealed",
    )
    
    # 玩家出价
    r1 = game_manager.record_sealed_bid("player_0", "未来圣杯", 30)
    r2 = game_manager.record_sealed_bid("player_1", "未来圣杯", 45)
    r3 = game_manager.record_sealed_bid("player_2", "未来圣杯", 40)
    
    assert r1["success"] is True
    assert r2["success"] is True
    assert r3["success"] is True
    
    # 揭示结果
    result = game_manager.reveal_sealed_bids("未来圣杯")
    
    assert result["success"] is True
    assert result["winner_id"] == "player_1"
    assert result["winning_bid"] == 45
    print("✓ 密封竞标测试通过")


def test_global_status_update():
    """测试全局状态更新"""
    result = game_manager.update_global_status(
        stability_delta=-10,
        era_multiplier_changes={"ancient": 0.2},
        new_phase="auction",
    )
    
    assert result["success"] is True
    assert result["stability"] == 90
    assert result["current_phase"] == "auction"
    print("✓ 全局状态更新测试通过")


def test_every_third_round_draws_function_card():
    """测试每3回合自动补功能卡"""
    before = game_manager.get_game_state()
    card_counts_before = {
        pid: pdata["card_count"] for pid, pdata in before["players"].items()
    }

    # 从回合1推进到回合3（触发自动抽卡）
    game_manager.update_global_status(next_round=True)
    game_manager.update_global_status(next_round=True)

    after = game_manager.get_game_state()
    assert after["current_round"] == 3
    for pid, pdata in after["players"].items():
        assert pdata["card_count"] == card_counts_before[pid] + 1


def test_play_function_card_and_resolve_event():
    """测试功能卡与事件卡结算工具"""
    # 强制给予一个可自动结算的功能卡（倍率冲击）
    private_state = game_manager.get_game_state(include_private=True)
    from_location = None
    for pid, pdata in private_state["players"].items():
        if any(card["id"] == "func_11" for card in pdata["function_cards"]):
            from_location = pid
            break
    if from_location is None and any(card["id"] == "func_11" for card in private_state["global_state"]["card_deck"]):
        from_location = "deck"
    if from_location is None and any(card["id"] == "func_11" for card in private_state["global_state"]["card_discard_pile"]):
        from_location = "card_discard"
    assert from_location is not None

    if from_location != "player_0":
        transfer = game_manager.transfer_item("card", "倍率冲击", from_location, "player_0")
        assert transfer["success"] is True

    state_before = game_manager.get_game_state()
    ancient_before = state_before["era_multipliers"]["ancient"]
    card_count_before = state_before["players"]["player_0"]["card_count"]

    play_result = game_manager.play_function_card(
        player_id="player_0",
        card_name="倍率冲击",
        target_era="ancient",
        multiplier_delta=0.5,
    )
    assert play_result["success"] is True
    assert play_result["manual_resolution_required"] is False

    state_after_play = game_manager.get_game_state()
    assert state_after_play["era_multipliers"]["ancient"] == min(2.5, ancient_before + 0.5)
    assert state_after_play["players"]["player_0"]["card_count"] == card_count_before - 1

    # 结算事件区里的“市场崩盘”(event_10)，若不在事件区则将其放入事件区
    gs = game_manager.game_state.global_state
    if not any(e.id == "event_10" for e in gs.event_area):
        event10 = None
        event10_index = next((i for i, e in enumerate(gs.event_deck) if e.id == "event_10"), None)
        if event10_index is not None:
            event10 = gs.event_deck.pop(event10_index)
        else:
            event10_index = next((i for i, e in enumerate(gs.event_discard_pile) if e.id == "event_10"), None)
            if event10_index is not None:
                event10 = gs.event_discard_pile.pop(event10_index)
        assert event10 is not None
        if gs.event_area:
            gs.event_discard_pile.append(gs.event_area[0])
            gs.event_area[0] = event10
        else:
            gs.event_area.append(event10)

    event10_name = next(e.name for e in gs.event_area if e.id == "event_10")
    state_before_event = game_manager.get_game_state()
    multipliers_before = dict(state_before_event["era_multipliers"])
    resolve_result = game_manager.resolve_event(event10_name, refill_area=True)
    assert resolve_result["success"] is True
    assert resolve_result["effect_result"]["manual_resolution_required"] is False

    state_after_event = game_manager.get_game_state()
    for era in ("ancient", "modern", "future"):
        expected = max(0.5, round(multipliers_before[era] - 0.5, 1))
        assert state_after_event["era_multipliers"][era] == expected


def test_transfer_card_accepts_card_discard_pile_alias():
    """测试 transfer_item(card) 兼容 card_discard_pile 位置别名。"""
    game_manager.initialize_game(
        game_id="test_card_alias01",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_23")

    play = game_manager.play_function_card("player_0", "代理竞标")
    assert play["success"] is True

    transfer = game_manager.transfer_item("card", "代理竞标", "card_discard_pile", "player_0")
    assert transfer["success"] is True
    assert transfer["requested_item_name"] == "代理竞标"
    assert transfer["resolved_from_location"] == "card_discard"
    assert transfer["resolved_to_location"] == "player_0"


def test_transfer_card_accepts_card_discard_pile_alias_as_target():
    """测试 transfer_item(card) 兼容 to_location=card_discard_pile。"""
    game_manager.initialize_game(
        game_id="test_card_alias02",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_23")
    transfer = game_manager.transfer_item("card", "代理竞标", "player_0", "card_discard_pile")
    assert transfer["success"] is True
    assert transfer["resolved_from_location"] == "player_0"
    assert transfer["resolved_to_location"] == "card_discard"

    private_state = game_manager.get_game_state(include_private=True)
    assert any(card["id"] == "func_23" for card in private_state["global_state"]["card_discard_pile"])


def test_transfer_card_rejects_card_id_reference():
    """测试 transfer_item(card) 禁止使用功能卡ID。"""
    game_manager.initialize_game(
        game_id="test_card_alias03",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_23")
    result = game_manager.transfer_item("card", "func_23", "player_0", "card_discard")
    assert "error" in result
    assert "必须使用卡牌名称" in result["error"]


def test_play_function_card_supports_card_name_reference():
    """测试 play_function_card 支持按唯一卡名引用。"""
    game_manager.initialize_game(
        game_id="test_card_name01",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_23")

    result = game_manager.play_function_card("player_0", "代理竞标")
    assert result["success"] is True
    assert result["requested_card_name"] == "代理竞标"
    assert result["resolved_card_name"] == "代理竞标"


def test_play_function_card_rejects_card_id_reference():
    """测试 play_function_card 禁止使用功能卡ID。"""
    game_manager.initialize_game(
        game_id="test_card_name02",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_23")
    before = game_manager.get_game_state()
    before_count = before["players"]["player_0"]["card_count"]

    result = game_manager.play_function_card("player_0", "func_23")
    assert "error" in result
    assert "必须使用卡牌名称" in result["error"]

    after = game_manager.get_game_state()
    assert after["players"]["player_0"]["card_count"] == before_count


def test_play_function_card_error_includes_available_cards():
    """测试 play_function_card 失败时返回可修复信息。"""
    game_manager.initialize_game(
        game_id="test_card_err01",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )
    result = game_manager.play_function_card("player_0", "func_999")
    assert "error" in result
    assert result["requested_card_name"] == "func_999"
    assert "available_function_cards" in result
    assert isinstance(result["available_function_cards"], list)


def test_resolve_event_rejects_event_id_reference():
    """测试 resolve_event 禁止使用事件ID。"""
    game_manager.initialize_game(
        game_id="test_event_name01",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )
    private_state = game_manager.get_game_state(include_private=True)
    event_area = private_state["global_state"]["event_area"]
    assert event_area
    event_id = event_area[0]["id"]

    result = game_manager.resolve_event(event_id)
    assert "error" in result
    assert "必须使用事件名称" in result["error"]


def test_play_function_card_partial_name_ambiguity_returns_matches():
    """测试 play_function_card 在部分匹配不唯一时返回 matched_cards。"""
    game_manager.initialize_game(
        game_id="test_card_err03",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )

    _ensure_card_in_player("func_18")
    _ensure_card_in_player("func_19")
    before = game_manager.get_game_state(include_private=True)
    before_cards = before["players"]["player_0"]["function_cards"]

    result = game_manager.play_function_card("player_0", "密标")
    assert "error" in result
    assert result["error"] == "功能卡名称引用不唯一 密标"
    matched_names = {card["name"] for card in result["matched_cards"]}
    assert {"密标窥探", "密标干扰"}.issubset(matched_names)

    after = game_manager.get_game_state(include_private=True)
    after_cards = after["players"]["player_0"]["function_cards"]
    assert len(after_cards) == len(before_cards)


def test_transfer_card_invalid_location_reports_valid_locations():
    """测试 transfer_item(card) 非法位置错误包含合法位置提示。"""
    game_manager.initialize_game(
        game_id="test_card_err02",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )
    result = game_manager.transfer_item("card", "代理竞标", "player_0", "card_discard_pile_invalid")
    assert "error" in result
    assert "valid_card_locations" in result
    assert "card_discard" in result["valid_card_locations"]


def test_action_log():
    """测试行动日志"""
    logs = game_manager.get_action_log()
    
    assert len(logs) > 0
    print("✓ 行动日志测试通过")
    print("\n最近日志:")
    for log in logs[-5:]:
        print(f"  {log}")


def test_transfer_item_rejects_auction_pool_alias_reference():
    """测试拍卖区文物禁止使用 artifact_N 别名。"""
    game_manager.initialize_game(
        game_id="test_alias01",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=20,
    )
    state = game_manager.get_game_state()
    assert state["auction_pool"]

    transfer = game_manager.transfer_item("artifact", "artifact_1", "auction_pool", "player_0")
    assert "error" in transfer
    assert "必须使用文物名称" in transfer["error"]
    assert transfer["requested_item_name"] == "artifact_1"


def test_record_sealed_bid_rejects_auction_pool_alias_reference():
    """测试密封竞标禁止使用 artifact_N 别名。"""
    game_manager.initialize_game(
        game_id="test_alias02",
        player_names=[
            ("真实玩家", True),
            ("AI玩家1", False),
            ("AI玩家2", False),
        ],
        initial_money=50,
    )
    private_state = game_manager.get_game_state(include_private=True)
    sealed_item = next(
        (ai["artifact"] for ai in private_state["global_state"]["auction_pool"] if ai["auction_type"] == "sealed"),
        None,
    )
    if sealed_item is None:
        refill_result = game_manager.refill_auction_pool(target_size=len(private_state["players"]) + 4)
        assert "error" not in refill_result
        private_state = game_manager.get_game_state(include_private=True)
        sealed_item = next(
            (ai["artifact"] for ai in private_state["global_state"]["auction_pool"] if ai["auction_type"] == "sealed"),
            None,
        )
    assert sealed_item is not None

    pool = private_state["global_state"]["auction_pool"]
    alias_index = next(i for i, ai in enumerate(pool) if ai["artifact"]["id"] == sealed_item["id"])
    alias = f"artifact_{alias_index + 1}"
    bid_result = game_manager.record_sealed_bid("player_0", alias, 10)
    assert "error" in bid_result
    assert "必须使用文物名称" in bid_result["error"]
    assert bid_result["requested_item_name"] == alias


if __name__ == "__main__":
    print("=" * 50)
    print("运行游戏工具测试")
    print("=" * 50)
    
    test_game_initialization()
    test_get_state()
    test_update_player_asset()
    test_insufficient_money()
    test_add_artifact()
    test_sealed_bid()
    test_global_status_update()
    test_every_third_round_draws_function_card()
    test_play_function_card_and_resolve_event()
    test_action_log()
    
    print("\n" + "=" * 50)
    print("所有测试通过! ✓")
    print("=" * 50)
