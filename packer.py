"""
packer.py — 貪欲法 / ビームサーチによる積付メインロジック
"""
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any
from models import (
    CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig,
    Placement, PackResult, CandidatePosition, ConstraintHitStats
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
        return items

    if supply.mode == "buffer":
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
    """
    if not queue:
        return None

    if supply.mode == "fifo":
        return 0, queue[0]

    if supply.mode == "buffer":
        candidates = list(enumerate(queue[:supply.buffer_size]))
    else:
        candidates = list(enumerate(queue))

    if rules.fragile_top:
        non_fragile = [(i, c) for i, c in candidates if not c.fragile]
        if non_fragile:
            candidates = non_fragile

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
    no_flip=True の場合も Z軸回転のみなので影響なし（天地反転は行わない）。
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
    exec_mode: str = "real",
    hit_stats: Optional[ConstraintHitStats] = None,
) -> Tuple[List[Placement], List[CaseItem], List[CaseItem]]:
    """
    1パレット分の配置を実行する。
    戻り値: (配置済みリスト, 残りケースキュー, 絶対配置不可リスト)
    """
    placements: List[Placement] = []
    queue = list(cases_queue)
    truly_unplaceable: List[CaseItem] = []
    sequence = 0
    consecutive_failures = 0

    while queue:
        result = select_next_case(queue, placements, supply, rules)
        if result is None:
            break

        queue_idx, case_item = result
        candidates = generate_candidates(placements, pallet, rules.overhang_limit)
        if not candidates:
            candidates = [CandidatePosition(0, 0, 0, "origin")]

        best_score = -1.0
        best_placement: Optional[Placement] = None

        for cand in candidates:
            for case_l, case_w, case_h, rot in get_rotations(case_item):
                actual_z = get_support_z(cand.x, cand.y, case_l, case_w, placements)
                x, y, z = cand.x, cand.y, actual_z

                if exec_mode != "ideal":
                    ok, _ = run_all_checks(
                        x, y, z, case_l, case_w, case_h,
                        case_item, placements, pallet, rules,
                        hit_stats=hit_stats,
                    )
                    if not ok:
                        continue
                else:
                    from constraints import check_pallet_bounds, check_collision
                    ok1, _ = check_pallet_bounds(
                        x, y, z, case_l, case_w, case_h, pallet, 0.0)
                    ok2, _ = check_collision(
                        x, y, z, case_l, case_w, case_h, placements)
                    if not (ok1 and ok2):
                        if hit_stats is not None:
                            hit_stats.total_checked += 1
                            if not ok1:
                                hit_stats.pallet_bounds += 1
                            if not ok2:
                                hit_stats.collision += 1
                        continue
                    if hit_stats is not None:
                        hit_stats.total_checked += 1

                score, breakdown = compute_score(
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
                        sequence=sequence,
                        temperature=case_item.temperature,
                        max_top_load=case_item.max_top_load,
                        score_breakdown=breakdown,
                    )

        if best_placement is not None:
            placements.append(best_placement)
            queue.pop(queue_idx)
            sequence += 1
            consecutive_failures = 0
        else:
            queue.pop(queue_idx)

            if not placements:
                truly_unplaceable.append(case_item)
            else:
                queue.append(case_item)
                consecutive_failures += 1

            if consecutive_failures >= len(queue) + 1:
                break

    return placements, queue, truly_unplaceable


# ---------------------------------------------------------------------------
# ビームサーチ
# ---------------------------------------------------------------------------

def _get_valid_placements_for_item(
    item: CaseItem,
    placements: List[Placement],
    pallet: PalletConfig,
    rules: RuleConfig,
    score_cfg: ScoreConfig,
    exec_mode: str,
) -> List[Tuple[float, Placement]]:
    """有効な配置候補を (score, Placement) リストで返す (降順ソート済み)"""
    candidates = generate_candidates(placements, pallet, rules.overhang_limit)
    if not candidates:
        candidates = [CandidatePosition(0, 0, 0, "origin")]

    valid: List[Tuple[float, Placement]] = []
    for cand in candidates:
        for case_l, case_w, case_h, rot in get_rotations(item):
            actual_z = get_support_z(cand.x, cand.y, case_l, case_w, placements)
            x, y, z = cand.x, cand.y, actual_z

            if exec_mode != "ideal":
                ok, _ = run_all_checks(
                    x, y, z, case_l, case_w, case_h,
                    item, placements, pallet, rules)
            else:
                from constraints import check_pallet_bounds, check_collision
                ok1, _ = check_pallet_bounds(x, y, z, case_l, case_w, case_h, pallet, 0.0)
                ok2, _ = check_collision(x, y, z, case_l, case_w, case_h, placements)
                ok = ok1 and ok2

            if not ok:
                continue

            score, breakdown = compute_score(
                x, y, z, case_l, case_w, case_h,
                item, placements, pallet, score_cfg, rules
            )
            new_p = Placement(
                sku_id=item.sku_id, name=item.name,
                x=x, y=y, z=z,
                length=case_l, width=case_w, height=case_h,
                weight=item.weight, rotation=rot,
                group=item.group, fragile=item.fragile, color=item.color,
                sequence=len(placements),
                temperature=item.temperature,
                max_top_load=item.max_top_load,
                score_breakdown=breakdown,
            )
            valid.append((score, new_p))

    valid.sort(key=lambda v: v[0], reverse=True)
    return valid


def pack_single_pallet_beam(
    cases_queue: List[CaseItem],
    pallet: PalletConfig,
    supply: SupplyConfig,
    rules: RuleConfig,
    score_cfg: ScoreConfig,
    exec_mode: str = "real",
    beam_width: int = 3,
) -> Tuple[List[Placement], List[CaseItem], List[CaseItem]]:
    """
    ビームサーチによる1パレット積付。
    各アイテムを固定順で処理し、上位 beam_width 件の配置を並列探索する。
    戻り値: (配置済みリスト, 残りケース, 絶対配置不可リスト)
    """
    items = list(cases_queue)
    n = len(items)

    # ビームの各状態: (placements, placed_indices_frozenset, cumulative_score)
    beam: List[Tuple[List[Placement], frozenset, float]] = [([], frozenset(), 0.0)]

    for i, item in enumerate(items):
        next_candidates: List[Tuple[List[Placement], frozenset, float]] = []

        for placements, placed, cum_score in beam:
            valid = _get_valid_placements_for_item(
                item, placements, pallet, rules, score_cfg, exec_mode
            )

            if valid:
                # 上位 beam_width 件の配置でブランチ
                for score, new_p in valid[:beam_width]:
                    next_candidates.append(
                        (placements + [new_p], placed | frozenset([i]), cum_score + score)
                    )
            else:
                # このアイテムは配置不可 → スキップして状態を維持
                next_candidates.append((placements, placed, cum_score))

        # (配置数の多さ, スコアの高さ) 降順でソートし上位 beam_width 件を保持
        next_candidates.sort(key=lambda s: (len(s[1]), s[2]), reverse=True)
        beam = next_candidates[:beam_width]

    if not beam:
        return [], list(cases_queue), []

    best_placements, best_placed, _ = beam[0]

    # sequence を実際の配置順に振り直す
    for idx, p in enumerate(best_placements):
        p.sequence = idx

    remaining = [items[i] for i in range(n) if i not in best_placed]
    return best_placements, remaining, []


# ---------------------------------------------------------------------------
# メインエントリポイント
# ---------------------------------------------------------------------------

def pack(
    cases: List[CaseItem],
    pallet: PalletConfig,
    supply: SupplyConfig,
    rules: RuleConfig,
    score_cfg: ScoreConfig,
    exec_mode: str = "real",
    max_pallets: int = 10,
    beam_width: int = 1,
) -> PackResult:
    """
    メインエントリポイント。複数パレットにわたる積付を実行する。
    beam_width > 1 の場合はビームサーチを使用。
    """
    all_placements: List[Placement] = []
    unplaced_items: List[Dict[str, Any]] = []
    pallet_count = 0
    hit_stats = ConstraintHitStats()

    queue = build_supply_queue(cases, supply)
    total_cases = len(queue)

    while queue and pallet_count < max_pallets:
        pallet_count += 1
        if beam_width > 1:
            placements, remaining, truly_unplaceable = pack_single_pallet_beam(
                queue, pallet, supply, rules, score_cfg, exec_mode,
                beam_width=beam_width,
            )
        else:
            placements, remaining, truly_unplaceable = pack_single_pallet(
                queue, pallet, supply, rules, score_cfg, exec_mode,
                hit_stats=hit_stats,
            )

        for c in truly_unplaceable:
            unplaced_items.append({
                "sku_id": c.sku_id,
                "name": c.name,
                "reason": "配置不可能（サイズ・制約超過）"
            })

        if not placements and remaining:
            for c in remaining:
                unplaced_items.append({
                    "sku_id": c.sku_id,
                    "name": c.name,
                    "reason": "配置不可能（サイズ・制約超過）"
                })
            break

        for p in placements:
            p.pallet_id = pallet_count
        all_placements.extend(placements)
        queue = remaining

    for c in queue:
        unplaced_items.append({
            "sku_id": c.sku_id,
            "name": c.name,
            "reason": f"パレット数上限({max_pallets})に達した"
        })

    return _build_result(
        all_placements, unplaced_items, pallet_count,
        total_cases, pallet, rules, exec_mode, supply.mode, hit_stats
    )


def _build_result(
    placements: List[Placement],
    unplaced: List[Dict[str, Any]],
    pallet_count: int,
    total_cases: int,
    pallet: PalletConfig,
    rules: RuleConfig,
    exec_mode: str,
    supply_mode: str,
    hit_stats: ConstraintHitStats,
) -> PackResult:
    """PackResult を組み立てる"""
    placed_cases = len(placements)
    total_weight = sum(p.weight for p in placements)

    pallet_vol = pallet.length * pallet.width * pallet.effective_height
    case_vol = sum(p.length * p.width * p.height for p in placements)
    efficiency = (case_vol / pallet_vol * 100) if pallet_vol > 0 else 0.0

    max_height_used = max((p.z2 for p in placements), default=0)

    tier_zs = sorted(set(p.z for p in placements))
    tier_count = len(tier_zs)

    from scoring import score_support_ratio
    if placements:
        support_scores = [
            score_support_ratio(p.x, p.y, p.z, p.length, p.width, placements)
            for p in placements
        ]
        stability_score = sum(support_scores) / len(support_scores) * 100
    else:
        stability_score = 0.0

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
        supply_mode=supply_mode,
        constraint_hits=hit_stats,
    )
