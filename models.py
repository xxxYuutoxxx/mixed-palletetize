"""
models.py — データクラス定義
混載パレタイズ積付計算システム Phase 1
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class CaseItem:
    """ケース（荷物）1品種の定義"""
    sku_id: str              # SKU識別子
    name: str                # 品名
    length: int              # 長さ mm (X方向)
    width: int               # 幅 mm (Y方向)
    height: int              # 高さ mm (Z方向)
    weight: float            # 重量 kg
    quantity: int            # 供給数量
    fragile: bool = False    # 割れ物フラグ（上にのせ禁止）
    stackable: bool = True   # 積み重ね可能フラグ
    max_stack: int = 5       # 最大積段数
    group: str = ""          # グループ/品種（同品種集約用）
    temperature: str = "normal"  # 温度帯: normal / chilled / frozen
    color: str = "#4A90D9"   # 可視化用カラー
    max_top_load: float = 0.0        # 上面許容荷重 kg (0=制限なし)
    no_flip: bool = False            # 天地無用フラグ（天地反転禁止）
    support_ratio_required: float = 0.0  # 個別支持率下限 (0=グローバル設定使用)


@dataclass
class PalletConfig:
    """パレット設定"""
    length: int = 1100       # パレット長さ mm (X)
    width: int = 1100        # パレット幅 mm (Y)
    base_height: int = 150   # パレット台高さ mm
    max_height: int = 1650   # 最大積付高さ mm (パレット込み)
    effective_height: int = 1500  # 有効積付高さ mm (ケースのみ)
    max_weight: float = 1000.0    # 最大積載重量 kg


@dataclass
class SupplyConfig:
    """供給制約設定"""
    mode: str = "free"       # "fifo" / "buffer" / "free"
    buffer_size: int = 3     # バッファモード時の同時供給数
    fifo_strict: bool = True # FIFOモード厳密フラグ


@dataclass
class RuleConfig:
    """積付ルール設定"""
    fragile_top: bool = True       # 割れ物は最上段
    heavy_bottom: bool = True      # 重いものは下
    same_group: bool = False       # 同品種集約
    center_priority: bool = False  # 重心中央優先
    outer_priority: bool = False   # 外壁沿い優先
    stack_priority: bool = False   # 縦積み優先
    no_overhang: bool = True       # はみ出し禁止
    layer_first: bool = False      # 面積み優先（現在層を埋めてから上段へ）
    temp_separate: bool = False    # 温度帯分離
    overhang_limit: float = 0.0    # 許容はみ出し率 0.0〜0.3
    support_ratio_min: float = 0.7 # 最小支持率
    height_tolerance: int = 0      # 同一平面とみなす高さ差許容値 mm (0=完全一致)
    block_stacking: bool = False   # 同一品種ブロック積み優先（面積み）
    priority_order: List[str] = field(default_factory=lambda: [
        "heavy_bottom", "fragile_top", "same_group"
    ])


@dataclass
class ScoreConfig:
    """スコアリング重み設定"""
    w_support: float = 0.35   # 支持率
    w_center: float = 0.25    # 重心中央
    w_height: float = 0.20    # 高さ抑制
    w_void: float = 0.10      # 空隙抑制
    w_group: float = 0.10     # SKUグループ集約
    w_block: float = 0.50     # ブロック積みパターン継続（block_stacking有効時のみ使用）
    w_overhang: float = 0.0   # オーバーハング活用（B-2モード: pack()内で自動設定）


@dataclass
class ScoreBreakdown:
    """配置スコア内訳（採用された配置の各指標値）"""
    support_score: float = 0.0
    center_score: float = 0.0
    height_score: float = 0.0
    void_score: float = 0.0
    group_score: float = 0.0
    block_score: float = 0.0
    total_score: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "support_score": round(self.support_score, 3),
            "center_score":  round(self.center_score,  3),
            "height_score":  round(self.height_score,  3),
            "void_score":    round(self.void_score,    3),
            "group_score":   round(self.group_score,   3),
            "block_score":   round(self.block_score,   3),
            "total_score":   round(self.total_score,   3),
        }


@dataclass
class ConstraintHitStats:
    """制約ヒット集計（候補配置の棄却理由カウンタ）"""
    pallet_bounds: int = 0   # パレット範囲外
    collision: int = 0       # 衝突
    support_ratio: int = 0   # 支持率不足
    fragile: int = 0         # fragile違反
    heavy_bottom: int = 0    # 重量物違反
    max_stack: int = 0       # 積段数超過
    temperature: int = 0     # 温度帯違反
    total_weight: int = 0    # 総重量超過
    max_top_load: int = 0    # 上面荷重超過
    stackable: int = 0       # 積み重ね不可違反
    total_checked: int = 0   # 全候補チェック数（回転×位置の組み合わせ）

    def to_dict(self) -> Dict[str, int]:
        return {
            "範囲外":           self.pallet_bounds,
            "衝突":             self.collision,
            "支持率不足":       self.support_ratio,
            "fragile違反":      self.fragile,
            "重量物違反":       self.heavy_bottom,
            "積段数超過":       self.max_stack,
            "温度帯違反":       self.temperature,
            "総重量超過":       self.total_weight,
            "上面荷重超過":     self.max_top_load,
            "積み重ね不可違反": self.stackable,
            "総チェック数":     self.total_checked,
        }


@dataclass
class Placement:
    """配置済みケース1個の情報"""
    sku_id: str
    name: str
    x: int          # X座標 mm (パレット原点から)
    y: int          # Y座標 mm
    z: int          # Z座標 mm (パレット台面=0)
    length: int     # 配置後の長さ (回転考慮)
    width: int      # 配置後の幅
    height: int     # 高さ
    weight: float
    rotation: int   # 0 or 90 degrees (Z軸回転)
    group: str = ""
    fragile: bool = False
    stackable: bool = True       # 積み重ね可能フラグ (CaseItemから引き継ぎ)
    color: str = "#4A90D9"
    sequence: int = 0  # 配置順序
    temperature: str = "normal"  # 温度帯
    max_top_load: float = 0.0    # 上面許容荷重 (CaseItemから引き継ぎ)
    pallet_id: int = 1           # パレット番号 (1始まり)
    score_breakdown: Optional[ScoreBreakdown] = None  # スコア内訳

    @property
    def x2(self) -> int:
        return self.x + self.length

    @property
    def y2(self) -> int:
        return self.y + self.width

    @property
    def z2(self) -> int:
        return self.z + self.height

    def overlaps_xy(self, other: "Placement") -> bool:
        """XY平面での重なり判定"""
        return (self.x < other.x2 and self.x2 > other.x and
                self.y < other.y2 and self.y2 > other.y)

    def overlaps_xyz(self, other: "Placement") -> bool:
        """3D空間での重なり判定"""
        return (self.x < other.x2 and self.x2 > other.x and
                self.y < other.y2 and self.y2 > other.y and
                self.z < other.z2 and self.z2 > other.z)


@dataclass
class PackResult:
    """積付計算結果"""
    placements: List[Placement] = field(default_factory=list)
    unplaced: List[Dict[str, Any]] = field(default_factory=list)
    pallet_count: int = 1
    total_cases: int = 0
    placed_cases: int = 0
    efficiency: float = 0.0        # 体積効率 %
    max_height_used: int = 0       # 実使用高さ mm
    total_weight: float = 0.0      # 総重量 kg
    stability_score: float = 0.0   # 安定性スコア 0-100
    tier_count: int = 0            # 段数
    warnings: List[str] = field(default_factory=list)
    applied_rules: List[str] = field(default_factory=list)
    exec_mode: str = "real"
    supply_mode: str = "free"
    constraint_hits: ConstraintHitStats = field(default_factory=ConstraintHitStats)


@dataclass
class CandidatePosition:
    """候補配置位置"""
    x: int
    y: int
    z: int
    source: str  # "origin" / "right" / "depth" / "top"

    def __repr__(self) -> str:
        return f"Pos({self.x},{self.y},{self.z})[{self.source}]"
