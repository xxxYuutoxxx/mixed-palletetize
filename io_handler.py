"""
io_handler.py — JSON入出力の変換処理
UIモックの入出力JSONフォーマットとPythonデータクラス間の変換
"""
from __future__ import annotations
import json
from typing import Any, Dict, List
from models import (
    CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig,
    Placement, PackResult
)


# ---------------------------------------------------------------------------
# 入力JSON → データクラス変換
# ---------------------------------------------------------------------------

def parse_input(data: Dict[str, Any]):
    """
    入力JSONを各設定データクラスに変換する。
    戻り値: (cases, pallet, supply, rules, score_cfg, exec_mode)
    """
    cases: List[CaseItem] = []
    for c in data.get("cases", []):
        cases.append(CaseItem(
            sku_id=c["sku_id"],
            name=c.get("name", c["sku_id"]),
            length=int(c["length"]),
            width=int(c["width"]),
            height=int(c["height"]),
            weight=float(c["weight"]),
            quantity=int(c["quantity"]),
            fragile=bool(c.get("fragile", False)),
            stackable=bool(c.get("stackable", True)),
            max_stack=int(c.get("max_stack", 5)),
            group=c.get("group", ""),
            temperature=c.get("temperature", "normal"),
            color=c.get("color", "#4A90D9"),
            max_top_load=float(c.get("max_top_load", 0.0)),
            no_flip=bool(c.get("no_flip", False)),
            support_ratio_required=float(c.get("support_ratio_required", 0.0)),
        ))

    p = data.get("pallet", {})
    pallet = PalletConfig(
        length=int(p.get("length", 1100)),
        width=int(p.get("width", 1100)),
        base_height=int(p.get("base_height", 150)),
        max_height=int(p.get("max_height", 1650)),
        effective_height=int(p.get("effective_height", 1500)),
        max_weight=float(p.get("max_weight", 1000.0)),
    )

    s = data.get("supply", {})
    supply = SupplyConfig(
        mode=s.get("mode", "free"),
        buffer_size=int(s.get("buffer_size", 3)),
        fifo_strict=bool(s.get("fifo_strict", True)),
    )

    r = data.get("rules", {})
    rules = RuleConfig(
        fragile_top=bool(r.get("fragile_top", True)),
        heavy_bottom=bool(r.get("heavy_bottom", True)),
        same_group=bool(r.get("same_group", False)),
        center_priority=bool(r.get("center_priority", False)),
        outer_priority=bool(r.get("outer_priority", False)),
        stack_priority=bool(r.get("stack_priority", False)),
        no_overhang=bool(r.get("no_overhang", True)),
        layer_first=bool(r.get("layer_first", False)),
        temp_separate=bool(r.get("temp_separate", False)),
        overhang_limit=float(r.get("overhang_limit", 0.0)),
        support_ratio_min=float(r.get("support_ratio_min", 0.7)),
        height_tolerance=int(r.get("height_tolerance", 0)),
        block_stacking=bool(r.get("block_stacking", False)),
        priority_order=r.get("priority_order", ["heavy_bottom", "fragile_top"]),
    )

    sc = data.get("scoring", {})
    score_cfg = ScoreConfig(
        w_support=float(sc.get("w_support", 0.35)),
        w_center=float(sc.get("w_center", 0.25)),
        w_height=float(sc.get("w_height", 0.20)),
        w_void=float(sc.get("w_void", 0.10)),
        w_group=float(sc.get("w_group", 0.10)),
        w_block=float(sc.get("w_block", 0.50)),
    )

    exec_mode = data.get("exec_mode", "real")

    return cases, pallet, supply, rules, score_cfg, exec_mode


# ---------------------------------------------------------------------------
# PackResult → 出力JSON変換
# ---------------------------------------------------------------------------

def result_to_dict(result: PackResult, pallet: PalletConfig) -> Dict[str, Any]:
    """PackResult を出力JSON用辞書に変換する"""
    placements_out = []
    for p in result.placements:
        entry: Dict[str, Any] = {
            "sku_id":   p.sku_id,
            "name":     p.name,
            "x":        p.x,
            "y":        p.y,
            "z":        p.z,
            "length":   p.length,
            "width":    p.width,
            "height":   p.height,
            "weight":   p.weight,
            "rotation": p.rotation,
            "group":    p.group,
            "fragile":  p.fragile,
            "color":    p.color,
            "sequence": p.sequence,
            "pallet_id": p.pallet_id,
        }
        if p.score_breakdown is not None:
            entry["score_breakdown"] = p.score_breakdown.to_dict()
        placements_out.append(entry)

    return {
        "summary": {
            "placed_cases":      result.placed_cases,
            "total_cases":       result.total_cases,
            "unplaced_cases":    len(result.unplaced),
            "pallet_count":      result.pallet_count,
            "efficiency_pct":    result.efficiency,
            "max_height_used_mm": result.max_height_used,
            "total_weight_kg":   result.total_weight,
            "stability_score":   result.stability_score,
            "tier_count":        result.tier_count,
            "exec_mode":         result.exec_mode,
            "supply_mode":       result.supply_mode,
        },
        "applied_rules":    result.applied_rules,
        "warnings":         result.warnings,
        "placements":       placements_out,
        "unplaced":         result.unplaced,
        "pallet": {
            "length":           pallet.length,
            "width":            pallet.width,
            "effective_height": pallet.effective_height,
        },
        "constraint_hits": result.constraint_hits.to_dict(),
    }


def load_input_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_output_file(data: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
