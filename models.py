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
    temp_separate: bool = False    # 温度帯分離
    overhang_limit: float = 0.0    # 許容はみ出し率 0.0〜0.3
    support_ratio_min: float = 0.7 # 最小支持率
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
    color: str = "#4A90D9"
    sequence: int = 0  # 配置順序

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


@dataclass
class CandidatePosition:
    """候補配置位置"""
    x: int
    y: int
    z: int
    source: str  # "origin" / "right" / "depth" / "top"

    def __repr__(self) -> str:
        return f"Pos({self.x},{self.y},{self.z})[{self.source}]"
