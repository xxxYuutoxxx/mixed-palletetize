"""
packer.py — 貪欲法による積付メインロジック
"""
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
from models import (
    CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig,
    Placement, PackResult, CandidatePosition
)
from candidate_generator import generate_candidates, get_support_z
from constraints import run_all_checks
from scoring import compute_score


# ---------------------------------------------------------------------------
# ケース供給キュー
# ---------------------------------------------------------------------------

def build_supply_queue(
    cases: List[CaseItem],
    supply: SupplyConfig
) -> List[CaseItem]:
    """
    供給モードに応じてケースの供給順序リストを生成する。
    戻り値は「次に供給可能なケース」の順序リスト。
    """
    items: List[CaseItem] = []
    for c in cases:
        items.extend([c] * c.quantity)

    if supply.mode == "fifo":
        # 入力順を厳守（並び替えなし）
        return items

    if supply.mode == "buffer":
        # バッファ内では自由に選択可能（ここでは入力順を維持しつつ
        # buffer_size 個ずつ取り出して最適順に並び替える簡易実装）
        return items  # packer側でbuffer_sizeを意識した選択をする

    # free モード: 重量降順（重いものを先に）
    items.sort(key=lambda c: c.weight, reverse=True)
    return items


def select_next_case(
    queue: List[CaseItem],
    placements: List[Placement],
    supply: SupplyConfig,
    rules: RuleConfig
) -> Optional[Tuple[int, CaseItem]]:
    """
    供給キューから次に配置すべきケースのインデックスと CaseItem を選ぶ。
    FIFOは先頭固定、bufferは先頭から buffer_size 個の中から選択、
    freeは全体から選択。
    """
    if not queue:
        return None

    if supply.mode == "fifo":
        return 0, queue[0]

    # 選択範囲を決める
    if supply.mode == "buffer":
        candidates = list(enumerate(queue[:supply.buffer_size]))
    else:
        candidates = list(enumerate(queue))

    # fragile_top: 割れ物は後回し（下にケースが置ける状況を優先）
    if rules.fragile_top:
        non_fragile = [(i, c) for i, c in candidates if not c.fragile]
        if non_fragile:
            candidates = non_fragile

    # heavy_bottom: 重いものを先
    if rules.heavy_bottom:
        candidates.sort(key=lambda ic: ic[1].weight, reverse=True)

    return candidates[0]


# ---------------------------------------------------------------------------
# 回転バリアント生成
# ---------------------------------------------------------------------------

def get_rotations(case: CaseItem) -> List[Tuple[int, int, int, int]]:
    """
    (length, width, height, rotation_deg) のリスト。
    高さは回転しない（Z軸回転のみ）。
    """
    l, w, h = case.length, case.width, case.height
    rotations = [(l, w, h, 0)]
    if l != w:
        rotations.append((w, l, h, 90))
    return rotations


# ---------------------------------------------------------------------------
# メイン貪欲アルゴリズム
# ---------------------------------------------------------------------------

def pack_single_pallet(
    cases_queue: List[CaseItem],
    pallet: PalletConfig,
    supply: SupplyConfig,
    rules: RuleConfig,
    score_cfg: ScoreConfig,
    exec_mode: str = "real"
) -> Tuple[List[Placement], List[CaseItem]]:
    """
    1パレット分の配置を実行する。
    戻り値: (配置済みリスト, 残りケースキュー)
    """
    placements: List[Placement] = []
    queue = list(cases_queue)
    truly_unplaceable: List[CaseItem] = []  # このパレット上で絶対置けないケース
    sequence = 0

    consecutive_failures = 0  # 連続して1個も置けなかった回数

    while queue:
        # 次に配置するケースを選択
        result = select_next_case(queue, placements, supply, rules)
        if result is None:
            break

        queue_idx, case_item = result

        # 候補位置を生成
        candidates = generate_candidates(placements, pallet)
        if not candidates:
            candidates = [CandidatePosition(0, 0, 0, "origin")]

        best_score = -1.0
        best_placement: Optional[Placement] = None

        for cand in candidates:
            for case_l, case_w, case_h, rot in get_rotations(case_item):
                # 実際の配置Z（重力落下: 直下の支持物の最大高さ）
                actual_z = get_support_z(cand.x, cand.y, case_l, case_w, placements)
                x, y, z = cand.x, cand.y, actual_z

                # 制約チェック
                if exec_mode != "ideal":
                    ok, _ = run_all_checks(
                        x, y, z, case_l, case_w, case_h,
                        case_item, placements, pallet, rules
                    )
                    if not ok:
                        continue
                else:
                    # idealモード: バウンド・衝突のみチェック
                    from constraints import check_pallet_bounds, check_collision
                    ok1, _ = check_pallet_bounds(x, y, z, case_l, case_w, case_h, pallet, 0.0)
                    ok2, _ = check_collision(x, y, z, case_l, case_w, case_h, placements)
                    if not (ok1 and ok2):
                        continue

                # スコア計算
                score = compute_score(
                    x, y, z, case_l, case_w, case_h,
                    case_item, placements, pallet, score_cfg, rules
                )

                if score > best_score:
                    best_score = score
                    best_placement = Placement(
                        sku_id=case_item.sku_id,
                        name=case_item.name,
                        x=x, y=y, z=z,
                        length=case_l, width=case_w, height=case_h,
                        weight=case_item.weight,
                        rotation=rot,
                        group=case_item.group,
                        fragile=case_item.fragile,
                        color=case_item.color,
                        sequence=sequence
                    )

        if best_placement is not None:
            placements.append(best_placement)
            queue.pop(queue_idx)
            sequence += 1
            consecutive_failures = 0
        else:
            # このケースは今の状態では置けない
            queue.pop(queue_idx)

            if not placements:
                # 空パレットでも置けない → 本当に配置不可能
                truly_unplaceable.append(case_item)
            else:
                # 今のパレットが埋まっていて置けない → 次のパレットへ持ち越し
                # キューの末尾に移す（他のケースを優先して配置してから再試行を避けるため残りに追加）
                queue.append(case_item)
                consecutive_failures += 1

            # キュー内の全ケースが連続して失敗した場合、このパレットは満杯
            if consecutive_failures >= len(queue) + 1:
                break

    # 残りキュー（次パレットへ）+ 本当に配置不可能なもの
    return placements, queue, truly_unplaceable


def pack(
    cases: List[CaseItem],
    pallet: PalletConfig,
    supply: SupplyConfig,
    rules: RuleConfig,
    score_cfg: ScoreConfig,
    exec_mode: str = "real",
    max_pallets: int = 10
) -> PackResult:
    """
    メインエントリポイント。複数パレットにわたる積付を実行する。
    """
    all_placements: List[Placement] = []
    unplaced_items: List[Dict[str, Any]] = []
    pallet_count = 0

    queue = build_supply_queue(cases, supply)
    total_cases = len(queue)

    while queue and pallet_count < max_pallets:
        pallet_count += 1
        placements, remaining, truly_unplaceable = pack_single_pallet(
            queue, pallet, supply, rules, score_cfg, exec_mode
        )

        # 本当に置けないケース（サイズ超過等）を記録
        for c in truly_unplaceable:
            unplaced_items.append({
                "sku_id": c.sku_id,
                "name": c.name,
                "reason": "配置不可能（サイズ・制約超過）"
            })

        if not placements and remaining:
            # 1個も置けない（残りはすべて未配置）
            for c in remaining:
                unplaced_items.append({
                    "sku_id": c.sku_id,
                    "name": c.name,
                    "reason": "配置不可能（サイズ・制約超過）"
                })
            break

        all_placements.extend(placements)
        queue = remaining

    # パレット数上限に達した残りキュー
    for c in queue:
        unplaced_items.append({
            "sku_id": c.sku_id,
            "name": c.name,
            "reason": f"パレット数上限({max_pallets})に達した"
        })

    # 結果計算
    return _build_result(
        all_placements, unplaced_items, pallet_count,
        total_cases, pallet, rules, exec_mode, supply.mode
    )


def _build_result(
    placements: List[Placement],
    unplaced: List[Dict[str, Any]],
    pallet_count: int,
    total_cases: int,
    pallet: PalletConfig,
    rules: RuleConfig,
    exec_mode: str,
    supply_mode: str
) -> PackResult:
    """PackResult を組み立てる"""
    placed_cases = len(placements)
    total_weight = sum(p.weight for p in placements)

    # 体積効率: 配置ケース総体積 / パレット有効体積
    pallet_vol = pallet.length * pallet.width * pallet.effective_height
    case_vol = sum(p.length * p.width * p.height for p in placements)
    efficiency = (case_vol / pallet_vol * 100) if pallet_vol > 0 else 0.0

    # 実使用高さ
    max_height_used = max((p.z2 for p in placements), default=0)

    # 段数（ユニークなZ底面の数）
    tier_zs = sorted(set(p.z for p in placements))
    tier_count = len(tier_zs)

    # 安定性スコア（全配置物の平均支持率）
    from scoring import score_support_ratio
    if placements:
        support_scores = [
            score_support_ratio(p.x, p.y, p.z, p.length, p.width, placements)
            for p in placements
        ]
        stability_score = sum(support_scores) / len(support_scores) * 100
    else:
        stability_score = 0.0

    # 適用ルールリスト
    applied_rules: List[str] = []
    if rules.fragile_top:
        applied_rules.append("割れ物最上段")
    if rules.heavy_bottom:
        applied_rules.append("重量物下段")
    if rules.same_group:
        applied_rules.append("同品種集約")
    if rules.center_priority:
        applied_rules.append("重心中央優先")
    if rules.outer_priority:
        applied_rules.append("外壁沿い優先")
    if rules.no_overhang:
        applied_rules.append("はみ出し禁止")
    if rules.temp_separate:
        applied_rules.append("温度帯分離")

    warnings: List[str] = []
    if pallet_count > 1:
        warnings.append(f"複数パレット使用: {pallet_count}枚")
    if unplaced:
        warnings.append(f"未配置ケース: {len(unplaced)}個")

    return PackResult(
        placements=placements,
        unplaced=unplaced,
        pallet_count=pallet_count,
        total_cases=total_cases,
        placed_cases=placed_cases,
        efficiency=round(efficiency, 1),
        max_height_used=max_height_used,
        total_weight=round(total_weight, 1),
        stability_score=round(stability_score, 1),
        tier_count=tier_count,
        warnings=warnings,
        applied_rules=applied_rules,
        exec_mode=exec_mode,
        supply_mode=supply_mode
    )
