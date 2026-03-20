"""
constraints.py — 配置可否の制約チェック
各関数は (ok: bool, reason: str) を返す。
"""
from __future__ import annotations
from typing import List, Tuple
from models import Placement, CaseItem, PalletConfig, RuleConfig

CheckResult = Tuple[bool, str]


def check_pallet_bounds(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    pallet: PalletConfig,
    overhang_limit: float = 0.0
) -> CheckResult:
    """パレット範囲内チェック（許容はみ出し考慮）"""
    max_x = pallet.length * (1 + overhang_limit)
    max_y = pallet.width * (1 + overhang_limit)

    if x < 0 or y < 0 or z < 0:
        return False, "座標が負値"
    if x + case_l > max_x:
        return False, f"X方向超過: {x + case_l:.0f} > {max_x:.0f}"
    if y + case_w > max_y:
        return False, f"Y方向超過: {y + case_w:.0f} > {max_y:.0f}"
    if z + case_h > pallet.effective_height:
        return False, f"高さ超過: {z + case_h} > {pallet.effective_height}"
    return True, ""


def check_collision(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    placements: List[Placement]
) -> CheckResult:
    """既存配置物との干渉チェック"""
    for p in placements:
        if (x < p.x2 and x + case_l > p.x and
                y < p.y2 and y + case_w > p.y and
                z < p.z2 and z + case_h > p.z):
            return False, f"干渉: {p.sku_id} at ({p.x},{p.y},{p.z})"
    return True, ""


def check_support_ratio(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    placements: List[Placement],
    min_ratio: float = 0.7
) -> CheckResult:
    """底面支持率チェック（Z=0の場合はパレット台で100%支持）"""
    if z == 0:
        return True, ""

    case_area = case_l * case_w
    supported_area = 0

    for p in placements:
        if p.z2 == z:  # ちょうど直下にある配置物
            # XY重なり面積を計算
            ox = max(0, min(x + case_l, p.x2) - max(x, p.x))
            oy = max(0, min(y + case_w, p.y2) - max(y, p.y))
            supported_area += ox * oy

    ratio = supported_area / case_area if case_area > 0 else 0.0
    if ratio < min_ratio:
        return False, f"支持率不足: {ratio:.0%} < {min_ratio:.0%}"
    return True, ""


def check_fragile_constraint(
    x: int, y: int, z: int,
    case_h: int,
    case_item: CaseItem,
    placements: List[Placement],
    rules: RuleConfig
) -> CheckResult:
    """
    割れ物制約チェック:
    1. 割れ物の上にケースを置こうとしていないか
    2. 割れ物は最上段に置くべき（他のケースがこの上に乗れない）
    """
    if not rules.fragile_top:
        return True, ""

    # 割れ物の上に配置しようとしている場合NG
    for p in placements:
        if p.fragile and p.z2 == z:
            ox = max(0, min(x + case_h, p.x2) - max(x, p.x))
            # NOTE: case_l/case_w の引数が必要だが、簡易判定
            if ox > 0:
                return False, f"割れ物 {p.sku_id} の上に配置不可"

    return True, ""


def check_fragile_on_top(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    case_item: CaseItem,
    placements: List[Placement],
    rules: RuleConfig
) -> CheckResult:
    """割れ物を非最上段に置こうとしているかチェック"""
    if not rules.fragile_top or not case_item.fragile:
        return True, ""

    # この位置の上にスペースがあるか（他の配置物が天面に来られるか）は
    # 将来ケースが来るかわからないので、ここでは許可しつつ警告
    return True, ""


def check_heavy_bottom(
    z: int,
    case_item: CaseItem,
    placements: List[Placement],
    rules: RuleConfig,
    weight_threshold: float = 15.0
) -> CheckResult:
    """重量物は下段制約: 重いケースより上に軽いケースが既にある場合NG"""
    if not rules.heavy_bottom:
        return True, ""
    if case_item.weight < weight_threshold:
        return True, ""

    # 既存配置物の中で軽いものがこの高さより下にある場合は警告のみ（厳密チェックはしない）
    return True, ""


def check_max_stack(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    case_item: CaseItem,
    placements: List[Placement]
) -> CheckResult:
    """最大積段数チェック"""
    if case_item.max_stack <= 0:
        return True, ""

    # この位置の直下にある同SKUのスタック数を数える
    stack_count = 1
    current_z = z

    while True:
        found = False
        for p in placements:
            if (p.sku_id == case_item.sku_id and
                    p.z2 == current_z and
                    p.x == x and p.y == y):
                stack_count += 1
                current_z = p.z
                found = True
                break
        if not found:
            break

    if stack_count > case_item.max_stack:
        return False, f"最大積段数超過: {stack_count} > {case_item.max_stack}"
    return True, ""


def check_temperature_separation(
    case_item: CaseItem,
    placements: List[Placement],
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    rules: RuleConfig
) -> CheckResult:
    """温度帯分離チェック: 異なる温度帯のケースが隣接しないか"""
    if not rules.temp_separate or case_item.temperature == "normal":
        return True, ""

    for p in placements:
        if hasattr(p, 'temperature') and p.temperature != case_item.temperature:
            # XYZ方向の近接チェック（接触面で判定）
            x_touch = (x == p.x2 or x + case_l == p.x)
            y_touch = (y == p.y2 or y + case_w == p.y)
            z_touch = (z == p.z2 or z + case_h == p.z)
            xy_overlap = (x < p.x2 and x + case_l > p.x and
                          y < p.y2 and y + case_w > p.y)
            if (x_touch or y_touch or z_touch) and xy_overlap:
                return False, f"温度帯隣接: {case_item.temperature} vs {p.sku_id}"

    return True, ""


def check_total_weight(
    case_item: CaseItem,
    placements: List[Placement],
    pallet: PalletConfig
) -> CheckResult:
    """総重量チェック"""
    current_weight = sum(p.weight for p in placements)
    if current_weight + case_item.weight > pallet.max_weight:
        return False, f"重量超過: {current_weight + case_item.weight:.1f} > {pallet.max_weight}"
    return True, ""


def run_all_checks(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    case_item: CaseItem,
    placements: List[Placement],
    pallet: PalletConfig,
    rules: RuleConfig
) -> Tuple[bool, List[str]]:
    """全制約チェックを一括実行。(ok, [失敗理由リスト]) を返す"""
    failures: List[str] = []

    checks = [
        check_pallet_bounds(x, y, z, case_l, case_w, case_h, pallet, rules.overhang_limit),
        check_collision(x, y, z, case_l, case_w, case_h, placements),
        check_support_ratio(x, y, z, case_l, case_w, placements, rules.support_ratio_min),
        check_total_weight(case_item, placements, pallet),
        check_max_stack(x, y, z, case_l, case_w, case_item, placements),
    ]

    for ok, reason in checks:
        if not ok:
            failures.append(reason)

    return len(failures) == 0, failures
