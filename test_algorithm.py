# -*- coding: utf-8 -*-
"""
test_algorithm.py — アルゴリズム単体テスト
python test_algorithm.py で実行 (pytest 不要)
"""
from __future__ import annotations
import sys
import traceback

from models import CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig
from packer import pack
from constraints import (
    check_pallet_bounds, check_collision, check_support_ratio
)
from candidate_generator import generate_candidates, get_support_z
from scoring import score_support_ratio, score_center_bias


PALLET = PalletConfig(length=1100, width=1100, base_height=150,
                      max_height=1650, effective_height=1500, max_weight=1000.0)
RULES = RuleConfig()
SUPPLY = SupplyConfig(mode="free")
SCORE = ScoreConfig()


def run_test(name: str, fn) -> bool:
    try:
        fn()
        print(f"  [PASS] {name}")
        return True
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"  [ERROR] {name}: {e}")
        traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# constraints テスト
# ---------------------------------------------------------------------------

def test_bounds_ok():
    ok, reason = check_pallet_bounds(0, 0, 0, 400, 300, 200, PALLET, 0.0)
    assert ok, reason

def test_bounds_x_over():
    ok, _ = check_pallet_bounds(800, 0, 0, 400, 300, 200, PALLET, 0.0)
    assert not ok

def test_bounds_height_over():
    ok, _ = check_pallet_bounds(0, 0, 1400, 400, 300, 200, PALLET, 0.0)
    assert not ok

def test_collision_none():
    from models import Placement
    p = Placement("A", "A", 0, 0, 0, 400, 300, 200, 10.0, 0)
    ok, _ = check_collision(500, 0, 0, 400, 300, 200, [p])
    assert ok

def test_collision_detected():
    from models import Placement
    p = Placement("A", "A", 0, 0, 0, 400, 300, 200, 10.0, 0)
    ok, _ = check_collision(200, 0, 0, 400, 300, 200, [p])
    assert not ok

def test_support_ground():
    ok, _ = check_support_ratio(0, 0, 0, 400, 300, [], 0.7)
    assert ok

def test_support_ratio_full():
    from models import Placement
    base = Placement("B", "B", 0, 0, 0, 400, 300, 200, 10.0, 0)
    ok, _ = check_support_ratio(0, 0, 200, 400, 300, [base], 0.7)
    assert ok

def test_support_ratio_partial():
    from models import Placement
    base = Placement("B", "B", 0, 0, 0, 200, 200, 200, 5.0, 0)
    # 300×300のケースを乗せようとするが200×200しか支持されない → 44%
    ok, reason = check_support_ratio(0, 0, 200, 300, 300, [base], 0.7)
    assert not ok, f"支持率不足チェックが通ってしまった: {reason}"


# ---------------------------------------------------------------------------
# candidate_generator テスト
# ---------------------------------------------------------------------------

def test_candidates_empty():
    cands = generate_candidates([], PALLET)
    assert len(cands) == 1
    assert cands[0].x == 0 and cands[0].y == 0

def test_candidates_one_placed():
    from models import Placement
    p = Placement("A", "A", 0, 0, 0, 400, 300, 200, 10.0, 0)
    cands = generate_candidates([p], PALLET)
    xys = [(c.x, c.y) for c in cands]
    assert (400, 0) in xys  # 右隣
    assert (0, 300) in xys  # 奥隣
    assert (0, 0) in xys    # 天面 (実Zは packer 側で get_support_z により再計算)
    # (x,y) の重複候補は同一配置に収束するため除去されている
    assert len(xys) == len(set(xys))

def test_get_support_z():
    from models import Placement
    p = Placement("A", "A", 0, 0, 0, 400, 300, 200, 10.0, 0)
    z = get_support_z(0, 0, 400, 300, [p])
    assert z == 200


# ---------------------------------------------------------------------------
# scoring テスト
# ---------------------------------------------------------------------------

def test_score_support_ground():
    s = score_support_ratio(0, 0, 0, 400, 300, [])
    assert s == 1.0

def test_score_center_bias():
    s_center = score_center_bias(350, 400, 400, 300, PALLET)
    s_corner = score_center_bias(0, 0, 400, 300, PALLET)
    assert s_center > s_corner


# ---------------------------------------------------------------------------
# packer 統合テスト
# ---------------------------------------------------------------------------

def test_pack_single_case():
    cases = [CaseItem("X", "X", 400, 300, 200, 10.0, 1)]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE)
    assert result.placed_cases == 1
    assert result.total_cases == 1
    assert len(result.unplaced) == 0

def test_pack_multiple_cases():
    cases = [
        CaseItem("A", "A", 400, 300, 200, 10.0, 3),
        CaseItem("B", "B", 350, 250, 150, 8.0, 3),
    ]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE)
    assert result.placed_cases == 6
    assert result.efficiency > 0

def test_pack_oversized_case():
    """パレットより大きいケースは未配置になる"""
    cases = [
        CaseItem("SMALL", "SMALL", 400, 300, 200, 5.0, 2),
        CaseItem("HUGE", "HUGE", 1200, 1200, 400, 30.0, 1),
    ]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE)
    assert result.placed_cases == 2
    assert len(result.unplaced) == 1
    assert result.unplaced[0]["sku_id"] == "HUGE"

def test_pack_fragile_top():
    """割れ物は配置可能 (制約が過剰でない)"""
    rules = RuleConfig(fragile_top=True, heavy_bottom=True)
    cases = [
        CaseItem("HEAVY", "HEAVY", 400, 300, 200, 20.0, 2),
        CaseItem("FRAGILE", "FRAGILE", 300, 250, 150, 3.0, 1, fragile=True),
    ]
    result = pack(cases, PALLET, SUPPLY, rules, SCORE)
    assert result.placed_cases == 3

def test_pack_fifo_order():
    """FIFOモードでは入力順通りに配置される"""
    supply = SupplyConfig(mode="fifo")
    cases = [
        CaseItem("FIRST", "FIRST", 400, 300, 200, 5.0, 1),
        CaseItem("SECOND", "SECOND", 350, 250, 150, 3.0, 1),
    ]
    result = pack(cases, PALLET, supply, RULES, SCORE)
    assert result.placed_cases == 2
    # FIRST が先に配置されている
    assert result.placements[0].sku_id == "FIRST"

def test_pack_efficiency_not_zero():
    cases = [CaseItem("A", "A", 400, 300, 200, 8.0, 4)]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE)
    assert result.efficiency > 0

def test_pack_ideal_mode():
    """idealモードでは制約を緩和して配置できる"""
    cases = [CaseItem("A", "A", 400, 300, 200, 8.0, 5)]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE, exec_mode="ideal")
    assert result.placed_cases == 5
    assert result.exec_mode == "ideal"


# ---------------------------------------------------------------------------
# バグ修正回帰テスト (2026-06)
# ---------------------------------------------------------------------------

def test_temp_lateral_adjacency():
    """温度帯分離: 横の面接触も違反として検出される"""
    from models import Placement
    from constraints import check_temperature_separation
    rules = RuleConfig(temp_separate=True)
    frozen = CaseItem("FZ", "FZ", 400, 300, 200, 5.0, 1, temperature="frozen")
    placed = [Placement("NM", "NM", 0, 0, 0, 400, 300, 200, 5.0, 0,
                        temperature="normal")]
    ok, _ = check_temperature_separation(frozen, placed, 400, 0, 0, 400, 300, 200, rules)
    assert not ok, "横隣接の温度帯違反が検出されない"
    # 離れていればOK
    ok, _ = check_temperature_separation(frozen, placed, 500, 0, 0, 400, 300, 200, rules)
    assert ok
    # コーナー接触のみ（面接触なし）はOK
    ok, _ = check_temperature_separation(frozen, placed, 400, 300, 0, 400, 300, 200, rules)
    assert ok

def test_max_top_load_multi_tier():
    """上面許容荷重: 2段以上下のケースの許容荷重超過も検出される"""
    from models import Placement
    from constraints import check_max_top_load
    a = Placement("A", "A", 0, 0, 0, 400, 300, 200, 10.0, 0, max_top_load=10.0)
    b = Placement("B", "B", 0, 0, 200, 400, 300, 200, 8.0, 0, max_top_load=100.0)
    # Bの上に8kg → Aには 8+8=16kg > 10kg
    c = CaseItem("C", "C", 400, 300, 200, 8.0, 1)
    ok, _ = check_max_top_load(0, 0, 400, 400, 300, c, [a, b])
    assert not ok, "多段積みの許容荷重超過が検出されない"
    # 合計が許容内ならOK (8+1.5=9.5 <= 10)
    c2 = CaseItem("C2", "C2", 400, 300, 200, 1.5, 1)
    ok, _ = check_max_top_load(0, 0, 400, 400, 300, c2, [a, b])
    assert ok

def test_free_mode_no_early_pallet_close():
    """freeモード: 配置不能アイテムがあっても他のアイテムは同一パレットに配置される"""
    cases = [
        CaseItem("BIG", "BIG", 900, 900, 400, 50.0, 2, stackable=False),
        CaseItem("SML", "SML", 200, 200, 200, 1.0, 20),
    ]
    result = pack(cases, PALLET, SupplyConfig(mode="free"), RULES, SCORE)
    pallet1_smalls = sum(
        1 for p in result.placements if p.pallet_id == 1 and p.sku_id == "SML")
    assert pallet1_smalls > 0, "大箱の失敗でパレットが早期に閉じ、小箱が入らなかった"

def test_fifo_strict_order():
    """厳密FIFO: 途中のケースが置けない場合も配置順序が入力順を維持する"""
    cases = [
        CaseItem("A", "A", 400, 400, 300, 10.0, 1),
        CaseItem("B", "B", 1050, 1050, 400, 30.0, 1, stackable=False),
        CaseItem("C", "C", 400, 400, 300, 10.0, 1),
    ]
    supply = SupplyConfig(mode="fifo", fifo_strict=True)
    result = pack(cases, PALLET, supply, RULES, SCORE)
    order = [p.sku_id for p in sorted(result.placements, key=lambda p: p.sequence)]
    assert order == ["A", "B", "C"], f"FIFO順序違反: {order}"

def test_full_support_flag():
    """full_support=False で部分支持（レンガ積み）が許可される"""
    from models import Placement
    from constraints import run_all_checks
    base = Placement("B", "B", 0, 0, 0, 400, 300, 200, 10.0, 0)
    item = CaseItem("T", "T", 400, 300, 200, 5.0, 1)
    # x=120 に置くと支持率 280/400 = 70%
    rules_strict = RuleConfig()  # full_support=True (デフォルト)
    ok, _ = run_all_checks(120, 0, 200, 400, 300, 200, item, [base], PALLET, rules_strict)
    assert not ok, "完全支持要求なのに部分支持が許可された"
    rules_brick = RuleConfig(full_support=False, support_ratio_min=0.7)
    ok, reasons = run_all_checks(120, 0, 200, 400, 300, 200, item, [base], PALLET, rules_brick)
    assert ok, f"支持率70%が棄却された: {reasons}"
    # 下限未満 (支持率 50%) は引き続き棄却
    ok, _ = run_all_checks(200, 0, 200, 400, 300, 200, item, [base], PALLET, rules_brick)
    assert not ok


def test_empty_pallet_not_counted():
    """1個も置けなかったパレットは pallet_count に数えない"""
    cases = [
        CaseItem("OK", "OK", 400, 300, 200, 5.0, 2),
        CaseItem("NG", "NG", 1200, 1200, 400, 30.0, 1),  # どのパレットにも不可
    ]
    result = pack(cases, PALLET, SUPPLY, RULES, SCORE)
    used = set(p.pallet_id for p in result.placements)
    assert result.pallet_count == len(used), (
        f"空パレットがカウントされている: count={result.pallet_count}, 実使用={used}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        ("bounds_ok", test_bounds_ok),
        ("bounds_x_over", test_bounds_x_over),
        ("bounds_height_over", test_bounds_height_over),
        ("collision_none", test_collision_none),
        ("collision_detected", test_collision_detected),
        ("support_ground", test_support_ground),
        ("support_ratio_full", test_support_ratio_full),
        ("support_ratio_partial", test_support_ratio_partial),
        ("candidates_empty", test_candidates_empty),
        ("candidates_one_placed", test_candidates_one_placed),
        ("get_support_z", test_get_support_z),
        ("score_support_ground", test_score_support_ground),
        ("score_center_bias", test_score_center_bias),
        ("pack_single_case", test_pack_single_case),
        ("pack_multiple_cases", test_pack_multiple_cases),
        ("pack_oversized_case", test_pack_oversized_case),
        ("pack_fragile_top", test_pack_fragile_top),
        ("pack_fifo_order", test_pack_fifo_order),
        ("pack_efficiency_not_zero", test_pack_efficiency_not_zero),
        ("pack_ideal_mode", test_pack_ideal_mode),
        ("temp_lateral_adjacency", test_temp_lateral_adjacency),
        ("max_top_load_multi_tier", test_max_top_load_multi_tier),
        ("free_mode_no_early_pallet_close", test_free_mode_no_early_pallet_close),
        ("fifo_strict_order", test_fifo_strict_order),
        ("full_support_flag", test_full_support_flag),
        ("empty_pallet_not_counted", test_empty_pallet_not_counted),
    ]

    print(f"\n{'='*50}")
    print("  アルゴリズム単体テスト")
    print(f"{'='*50}")

    passed = sum(run_test(name, fn) for name, fn in tests)
    total = len(tests)

    print(f"{'='*50}")
    print(f"  結果: {passed}/{total} PASS")
    print(f"{'='*50}\n")

    sys.exit(0 if passed == total else 1)
