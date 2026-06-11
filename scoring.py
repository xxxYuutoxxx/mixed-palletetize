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
    case_l: int, case_w: int, case_h: int,
    placements: List[Placement],
    pallet: PalletConfig
) -> float:
    """
    空隙抑制スコア: 底面支持率 + 既存ボックスとの面接触を評価。
    面接触がある位置（X/Y/Z方向に隣接）を優遇し、孤立配置を抑制する。
    note: score_lateral_contact は w_lateral=0 がデフォルトのため、
          ここで接触ボーナスを担保することで有効な密着配置を誘導する。
    """
    s_bottom = score_support_ratio(x, y, z, case_l, case_w, placements)

    if not placements:
        return s_bottom

    has_contact = False
    for p in placements:
        if x == p.x2 or x + case_l == p.x:
            if y < p.y2 and y + case_w > p.y and z < p.z2 and z + case_h > p.z:
                has_contact = True
                break
        if y == p.y2 or y + case_w == p.y:
            if x < p.x2 and x + case_l > p.x and z < p.z2 and z + case_h > p.z:
                has_contact = True
                break
        if z == p.z2:
            if x < p.x2 and x + case_l > p.x and y < p.y2 and y + case_w > p.y:
                has_contact = True
                break

    s_contact = 1.0 if has_contact else 0.0
    return (s_bottom + s_contact) / 2.0


def score_sku_block_continuation(
    x: int, y: int, z: int,
    case_l: int, case_w: int,
    case_item: CaseItem,
    placements: List[Placement]
) -> float:
    """
    同一SKUのブロック積みパターン継続スコア（面積み）。
    既存の同一SKU配置パターンを検出し、それを継続する位置に高スコアを返す。
      1.0: 同じ行を X 方向に延長する位置（行継続）
      0.9: 同じ列を Y 方向に延長する位置（列継続）
      0.8: 既存ブロックの隣に新しい行を開始する位置
      0.7: 完成したブロック段の真上（段積み継続）
      0.5: 同一SKUが未配置（最初の1個）→ 中立
      0.0: パターン外
    """
    same_sku = [p for p in placements if p.sku_id == case_item.sku_id]
    if not same_sku:
        return 0.5  # 最初の1個は中立

    same_z = [p for p in same_sku if p.z == z]

    # ① 行継続: 同じ Y・Z で X 方向に隣接（最優先）
    for p in same_z:
        if p.y == y and p.x2 == x:
            return 1.0
        if p.y == y and x + case_l == p.x:
            return 1.0

    # ② 新しい行の先頭: X=ブロック開始位置 かつ 左端列ケースの直隣（Y方向）
    #    block_y_max 一律ではなく左端列の各ケースの y2/y を参照することで
    #    回転混在時にも正しく新行開始位置を検出する
    if same_z:
        block_x_start = min(p.x for p in same_z)
        left_col = [p for p in same_z if p.x == block_x_start]
        if x == block_x_start:
            for p in left_col:
                if y == p.y2 or y + case_w == p.y:
                    return 0.8

    # ④ 段積み継続: 同一SKU群の最上面の真上
    for p in same_sku:
        if (p.x == x and p.y == y and p.z2 == z):
            return 0.7
        # XY が重なっていて z が接している場合も許容
        xy_match = (p.x == x and p.y == y)
        if xy_match and p.z2 == z:
            return 0.7

    return 0.0


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
    # グループ未設定の場合は sku_id をグループキーとして使用
    group_key = case_item.group if case_item.group else case_item.sku_id

    same_group_placements = [
        p for p in placements
        if (p.group if p.group else p.sku_id) == group_key
    ]

    # ── 段(tier)スコア ──────────────────────────────────────────
    # 同品種が未配置 → 中立
    # 同品種が同じ段(z)に存在 → 高スコア（横方向に広げる）
    # 同品種が違う段にしかない → 低スコア（段が違う = 同一段優先に反する）
    if not same_group_placements:
        tier_score = 0.5
    elif any(p.z == z for p in same_group_placements):
        tier_score = 0.9   # 同じ段に同品種あり: 強く優遇
    else:
        tier_score = 0.1   # 違う段にしかない: 強く抑制

    # ── 水平隣接スコア ───────────────────────────────────────────
    # Z方向（真上・真下）は除外し、XY方向の隣接のみ評価
    touches = 0
    total_neighbors = 0
    for p in placements:
        x_adj = (x == p.x2 or x + case_l == p.x)
        y_adj = (y == p.y2 or y + case_w == p.y)
        xz_ov = x < p.x2 and x + case_l > p.x and z < p.z2 and z + case_h > p.z
        yz_ov = y < p.y2 and y + case_w > p.y and z < p.z2 and z + case_h > p.z
        if (x_adj and yz_ov) or (y_adj and xz_ov):
            total_neighbors += 1
            p_group = p.group if p.group else p.sku_id
            if p_group == group_key:
                touches += 1

    if total_neighbors == 0:
        adj_score = 0.5
    elif touches == 0:
        adj_score = 0.3  # 全隣接が異品種: 軽微なペナルティ
    else:
        adj_score = touches / total_neighbors

    # 段スコアを主、隣接スコアを副として合成
    # 同品種同一段上でさらに同品種に隣接すれば最高スコア(1.0)
    if tier_score == 0.9 and total_neighbors > 0 and touches > 0:
        return min(1.0, 0.9 + 0.1 * (touches / total_neighbors))
    return 0.7 * tier_score + 0.3 * adj_score


def score_layer_fill(
    z: int,
    placements: List[Placement],
    pallet: PalletConfig
) -> float:
    """
    面積みスコア: 現在アクティブな最下層を優先して水平展開。
    z が配置済み最小 z 以下なら 1.0、上段ほど急減。
    """
    if not placements:
        return 1.0
    min_z = min(p.z for p in placements)
    if z <= min_z:
        return 1.0
    z_ratio = (z - min_z) / max(1, pallet.effective_height)
    return max(0.0, 1.0 - z_ratio * 5)


def score_overhang_use(
    x: int, y: int,
    case_l: int, case_w: int,
    pallet: PalletConfig
) -> float:
    """
    オーバーハング活用スコア: 実際にパレット端を超える配置を優遇。
    1辺でもはみ出していれば 1.0、パレット内に収まる場合は 0.0。
    """
    if (x < 0 or y < 0 or
            x + case_l > pallet.length or y + case_w > pallet.width):
        return 1.0
    return 0.0


def score_lateral_contact(
    x: int, y: int, z: int,
    case_l: int, case_w: int, case_h: int,
    placements: List[Placement],
    pallet: PalletConfig
) -> float:
    """
    水平側面接触スコア: ケースの4側面（X+/X-/Y+/Y-）のうち、
    隣接する配置済みケースまたはパレット壁に接している面の割合。
    搬送中の棒積み荷崩れ防止を目的とする。
      1.0: 全4面が接触（または壁）
      0.9: 3面接触
      0.7: 2面接触（1面との差を大きくし2面を強く誘導）
      0.2: 1面接触
      0.0: 全く接触なし
    """
    contact_count = 0

    # パレット壁との接触
    if x == 0:
        contact_count += 1
    if x + case_l == pallet.length:
        contact_count += 1
    if y == 0:
        contact_count += 1
    if y + case_w == pallet.width:
        contact_count += 1

    # 既存ケースとの側面接触（Z方向に重なりがある場合のみカウント）
    x_min_touched = (x == 0)
    x_max_touched = (x + case_l == pallet.length)
    y_min_touched = (y == 0)
    y_max_touched = (y + case_w == pallet.width)

    for p in placements:
        z_overlap = z < p.z2 and z + case_h > p.z
        if not z_overlap:
            continue
        # X- 面（ケース左面）に右端が接触
        if not x_min_touched and p.x2 == x:
            if y < p.y2 and y + case_w > p.y:
                x_min_touched = True
        # X+ 面（ケース右面）に左端が接触
        if not x_max_touched and p.x == x + case_l:
            if y < p.y2 and y + case_w > p.y:
                x_max_touched = True
        # Y- 面（ケース前面）に後端が接触
        if not y_min_touched and p.y2 == y:
            if x < p.x2 and x + case_l > p.x:
                y_min_touched = True
        # Y+ 面（ケース後面）に前端が接触
        if not y_max_touched and p.y == y + case_w:
            if x < p.x2 and x + case_l > p.x:
                y_max_touched = True

    contact_count = sum([x_min_touched, x_max_touched, y_min_touched, y_max_touched])
    # 非線形スコア: 2面以上で大きく加点し、2面接触を強く誘導する
    scores = [0.0, 0.2, 0.7, 0.9, 1.0]
    return scores[contact_count]


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

    s_void = score_void_suppression(x, y, z, case_l, case_w, case_h, placements, pallet)
    s_group = score_sku_grouping(x, y, z, case_l, case_w, case_h, case_item, placements)
    s_block = score_sku_block_continuation(x, y, z, case_l, case_w, case_item, placements)
    s_overhang = score_overhang_use(x, y, case_l, case_w, pallet)
    s_layer = score_layer_fill(z, placements, pallet)
    s_lateral = score_lateral_contact(x, y, z, case_l, case_w, case_h, placements, pallet)

    # center vs outer は排他
    if rules.center_priority:
        s_position = score_center_bias(x, y, case_l, case_w, pallet)
    elif rules.outer_priority:
        s_position = score_outer_wall(x, y, case_l, case_w, pallet)
    else:
        s_position = (score_center_bias(x, y, case_l, case_w, pallet) +
                      score_outer_wall(x, y, case_l, case_w, pallet)) / 2

    # 重みを正規化して合計が常に 1.0 になるようにする
    w_support  = score_cfg.w_support
    w_center   = score_cfg.w_center
    w_height   = score_cfg.w_height
    w_void     = score_cfg.w_void
    w_group    = score_cfg.w_group if rules.same_group else 0.0
    w_block    = score_cfg.w_block if rules.block_stacking else 0.0
    w_overhang = score_cfg.w_overhang
    w_layer    = 0.6 if rules.layer_first else 0.0
    w_lateral  = score_cfg.w_lateral

    total_w = w_support + w_center + w_height + w_void + w_group + w_block + w_overhang + w_layer + w_lateral
    if total_w > 0:
        norm = 1.0 / total_w
    else:
        norm = 0.0

    score = (
        s_support  * w_support  * norm +
        s_position * w_center   * norm +
        s_height   * w_height   * norm +
        s_void     * w_void     * norm +
        s_group    * w_group    * norm +
        s_block    * w_block    * norm +
        s_overhang * w_overhang * norm +
        s_layer    * w_layer    * norm +
        s_lateral  * w_lateral  * norm
    )

    total = min(1.0, max(0.0, score))
    breakdown = ScoreBreakdown(
        support_score  = round(s_support,  4),
        center_score   = round(s_position, 4),
        height_score   = round(s_height,   4),
        void_score     = round(s_void,     4),
        group_score    = round(s_group,    4),
        block_score    = round(s_block,    4),
        lateral_score  = round(s_lateral,  4),
        layer_score    = round(s_layer,    4),
        overhang_score = round(s_overhang, 4),
        total_score    = round(total,      4),
    )
    return total, breakdown
