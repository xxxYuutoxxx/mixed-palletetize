"""
scoring.py — 配置候補のスコアリング
各候補位置に対してスコア (0.0〜1.0) を計算する。高スコアほど優先。
compute_score は (total_score, ScoreBreakdown) のタプルを返す。
"""
from __future__ import annotations
from typing import List, Tuple
from models import Placement, CaseItem, PalletConfig, ScoreConfig, RuleConfig, ScoreBreakdown


def score_support_ratio(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    placements: List[Placement]
) -> float:
    """支持率スコア: 底面がどれだけ下の配置物に支えられているか"""
    if z == 0:
        return 1.0  # パレット台面は完全支持

    case_area = case_l * case_w
    if case_area == 0:
        return 0.0

    supported = 0
    for p in placements:
        if p.z2 == z:
            ox = max(0, min(x + case_l, p.x2) - max(x, p.x))
            oy = max(0, min(y + case_w, p.y2) - max(y, p.y))
            supported += ox * oy

    return min(1.0, supported / case_area)


def score_center_bias(
    x: int, y: int,
    case_l: int, case_w: int,
    pallet: PalletConfig
) -> float:
    """
    重心中央スコア: ケース中心がパレット中心に近いほど高い。
    距離をパレット対角の半分で正規化。
    """
    cx = x + case_l / 2
    cy = y + case_w / 2
    px = pallet.length / 2
    py = pallet.width / 2

    dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
    max_dist = ((pallet.length ** 2 + pallet.width ** 2) ** 0.5) / 2

    return max(0.0, 1.0 - dist / max_dist) if max_dist > 0 else 1.0


def score_outer_wall(
    x: int, y: int,
    case_l: int, case_w: int,
    pallet: PalletConfig
) -> float:
    """外壁沿いスコア: ケースがパレット端に接しているほど高い"""
    touches = 0
    if x == 0:
        touches += 1
    if y == 0:
        touches += 1
    if x + case_l == pallet.length:
        touches += 1
    if y + case_w == pallet.width:
        touches += 1
    return min(1.0, touches / 2.0)


def score_height_suppression(
    z: int, case_h: int,
    pallet: PalletConfig
) -> float:
    """高さ抑制スコア: 低い位置ほど高いスコア"""
    top = z + case_h
    ratio = top / pallet.effective_height if pallet.effective_height > 0 else 1.0
    return max(0.0, 1.0 - ratio)


def score_void_suppression(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    placements: List[Placement],
    pallet: PalletConfig
) -> float:
    """
    空隙抑制スコア: この位置に置くことで生じる空隙が少ないほど高い。
    簡易版: 直下の支持面積率で代用（高支持率 = 低空隙）
    """
    return score_support_ratio(x, y, z, case_l, case_w, placements)


def score_sku_grouping(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    case_item: CaseItem,
    placements: List[Placement]
) -> float:
    """
    SKUグループ集約スコア: 同グループのケースに近いほど高い。
    接触面の数で評価。
    """
    if not case_item.group:
        return 0.5  # グループなしは中立

    touches = 0
    total_neighbors = 0

    for p in placements:
        x_adj = (x == p.x2 or x + case_l == p.x)
        y_adj = (y == p.y2 or y + case_w == p.y)
        z_adj = (z == p.z2 or z + case_h == p.z)

        xy_ov = x < p.x2 and x + case_l > p.x and y < p.y2 and y + case_w > p.y
        xz_ov = x < p.x2 and x + case_l > p.x and z < p.z2 and z + case_h > p.z
        yz_ov = y < p.y2 and y + case_w > p.y and z < p.z2 and z + case_h > p.z

        is_adjacent = (x_adj and yz_ov) or (y_adj and xz_ov) or (z_adj and xy_ov)

        if is_adjacent:
            total_neighbors += 1
            if p.group == case_item.group:
                touches += 1

    if total_neighbors == 0:
        return 0.5
    return touches / total_neighbors


def compute_score(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    case_item: CaseItem,
    placements: List[Placement],
    pallet: PalletConfig,
    score_cfg: ScoreConfig,
    rules: RuleConfig
) -> Tuple[float, ScoreBreakdown]:
    """
    全スコアの重み付き合計を返す (0.0〜1.0)。
    RuleConfigのフラグに応じて重みを動的調整。
    戻り値: (total_score, ScoreBreakdown)
    """
    s_support = score_support_ratio(x, y, z, case_l, case_w, placements)

    # stack_priority: 高い位置を優先（高さ抑制スコアを反転）
    if rules.stack_priority:
        top = z + case_h
        ratio = top / pallet.effective_height if pallet.effective_height > 0 else 1.0
        s_height = min(1.0, ratio)
    else:
        s_height = score_height_suppression(z, case_h, pallet)

    s_void = score_void_suppression(x, y, z, case_l, case_w, placements, pallet)
    s_group = score_sku_grouping(x, y, z, case_l, case_w, case_h, case_item, placements)

    # center vs outer は排他
    if rules.center_priority:
        s_position = score_center_bias(x, y, case_l, case_w, pallet)
    elif rules.outer_priority:
        s_position = score_outer_wall(x, y, case_l, case_w, pallet)
    else:
        s_position = (score_center_bias(x, y, case_l, case_w, pallet) +
                      score_outer_wall(x, y, case_l, case_w, pallet)) / 2

    # 重みを正規化して合計が常に 1.0 になるようにする
    w_support = score_cfg.w_support
    w_center  = score_cfg.w_center
    w_height  = score_cfg.w_height
    w_void    = score_cfg.w_void
    w_group   = score_cfg.w_group if rules.same_group else 0.0

    total_w = w_support + w_center + w_height + w_void + w_group
    if total_w > 0:
        norm = 1.0 / total_w
    else:
        norm = 0.0

    score = (
        s_support  * w_support * norm +
        s_position * w_center  * norm +
        s_height   * w_height  * norm +
        s_void     * w_void    * norm +
        s_group    * w_group   * norm
    )

    total = min(1.0, max(0.0, score))
    breakdown = ScoreBreakdown(
        support_score=round(s_support,  4),
        center_score =round(s_position, 4),
        height_score =round(s_height,   4),
        void_score   =round(s_void,     4),
        group_score  =round(s_group,    4),
        total_score  =round(total,      4),
    )
    return total, breakdown
