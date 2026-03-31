"""
candidate_generator.py — 候補配置位置の生成
Origin / Right-adjacent / Depth-adjacent / Top-surface の4種類
"""
from __future__ import annotations
from typing import List, Set, Tuple
from models import CandidatePosition, Placement, PalletConfig


def generate_candidates(
    placements: List[Placement],
    pallet: PalletConfig,
    overhang_limit: float = 0.0
) -> List[CandidatePosition]:
    """
    既存配置リストから次に試すべき候補位置を全列挙する。
    重複は除去し、パレット範囲内のものだけを返す。
    """
    seen: Set[Tuple[int, int, int]] = set()
    candidates: List[CandidatePosition] = []

    def add(x: int, y: int, z: int, source: str) -> None:
        if (x, y, z) not in seen:
            seen.add((x, y, z))
            candidates.append(CandidatePosition(x, y, z, source))

    # 原点候補の設定
    if overhang_limit > 0:
        oh_x = int(pallet.length * overhang_limit)
        oh_y = int(pallet.width * overhang_limit)
        if not placements:
            # 1ケース目: XY両方向にオーバーハング分ずらした位置を起点にする。
            # これにより正方向のオーバーハング領域も2ケース目以降で使えるようになる。
            add(-oh_x, -oh_y, 0, "origin")
        else:
            add(0, 0, 0, "origin")
            add(-oh_x, -oh_y, 0, "origin")
            add(-oh_x,      0, 0, "origin")
            add(     0, -oh_y, 0, "origin")
    else:
        add(0, 0, 0, "origin")

    for p in placements:
        # 右隣 (X方向)
        add(p.x2, p.y, p.z, "right")

        # 奥隣 (Y方向)
        add(p.x, p.y2, p.z, "depth")

        # 天面 (Z方向)
        add(p.x, p.y, p.z2, "top")

        # 右隣の奥隣
        add(p.x2, p.y2, p.z, "right")

        # 奥隣の右隣 (同じだが source 違い — 重複除去で統合される)
        add(p.x2, p.y2, p.z, "depth")

        # 天面の右隣・奥隣
        add(p.x2, p.y, p.z2, "top")
        add(p.x, p.y2, p.z2, "top")

    # パレット範囲をはみ出す候補を除去（配置時に詳細チェックするが事前フィルタ）
    max_x = pallet.length * (1 + overhang_limit)
    max_y = pallet.width * (1 + overhang_limit)
    min_x = -int(pallet.length * overhang_limit)
    min_y = -int(pallet.width * overhang_limit)
    candidates = [
        c for c in candidates
        if c.x >= min_x and c.y >= min_y
        and c.x < max_x and c.y < max_y
        and c.z < pallet.effective_height
    ]

    # Z昇順 → Y昇順 → X昇順でソート（下から左奥から埋める基本方針）
    candidates.sort(key=lambda c: (c.z, c.y, c.x))

    return candidates


def snap_to_ground(
    x: int, y: int, z_raw: int,
    case_l: int, case_w: int,
    placements: List[Placement]
) -> int:
    """
    (x,y) の位置でケース底面を支持するZを求める。
    直下にある配置物の最大Z2を返す（なければ0）。
    """
    support_z = 0
    for p in placements:
        # XY重なりがあるか
        if p.x < x + case_l and p.x2 > x and p.y < x + case_w and p.y2 > y:
            # NOTE: y系の比較が必要
            pass
        if (p.x < x + case_l and p.x2 > x and
                p.y < y + case_w and p.y2 > y):
            if p.z2 <= z_raw:
                support_z = max(support_z, p.z2)
    return support_z


def get_support_z(
    x: int, y: int,
    case_l: int, case_w: int,
    placements: List[Placement]
) -> int:
    """
    指定XY領域の真下にある最高Z2を返す（= このケースを置けるZ座標）。
    パレット台面(z=0)以上を保証。
    """
    support_z = 0
    for p in placements:
        if (p.x < x + case_l and p.x2 > x and
                p.y < y + case_w and p.y2 > y):
            support_z = max(support_z, p.z2)
    return support_z
