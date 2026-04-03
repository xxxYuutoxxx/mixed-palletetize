# -*- coding: utf-8 -*-
"""
log_db.py — 積付計算ログ記録モジュール

ケース構成の統計特徴量・使用パラメータ・結果KPIをSQLiteに記録する。
フェーズ1（ルールベース蓄積）の基盤となるデータ収集層。
"""
from __future__ import annotations
import sqlite3
import statistics
import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path(__file__).parent / "pack_logs.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pack_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT    NOT NULL,

    -- ケース構成統計特徴量
    num_skus         INTEGER,   -- 品種数
    total_cases      INTEGER,   -- 総ケース数
    weight_mean      REAL,      -- 重量 平均 kg
    weight_cv        REAL,      -- 重量 変動係数（標準偏差/平均）
    volume_mean      REAL,      -- 体積 平均 mm³
    volume_cv        REAL,      -- 体積 変動係数
    fragile_ratio    REAL,      -- fragileケース率 0.0〜1.0
    temp_variety     INTEGER,   -- 使用温度帯の種類数
    has_no_flip      INTEGER,   -- 天地無用ケースの有無 0/1
    max_stack_min    INTEGER,   -- max_stack の最小値（最も制約が厳しい値）

    -- 供給・探索パラメータ
    supply_mode      TEXT,
    beam_width       INTEGER,
    exec_mode        TEXT,
    buffer_size      INTEGER,

    -- 積付ルール
    fragile_top      INTEGER,
    heavy_bottom     INTEGER,
    same_group       INTEGER,
    block_stacking   INTEGER,
    no_overhang      INTEGER,
    temp_separate    INTEGER,
    center_priority  INTEGER,
    outer_priority   INTEGER,
    stack_priority   INTEGER,
    overhang_limit   REAL,
    support_ratio_min REAL,
    height_tolerance INTEGER,

    -- スコアリング重み（正規化後）
    w_support        REAL,
    w_center         REAL,
    w_height         REAL,
    w_void           REAL,
    w_group          REAL,

    -- 結果KPI
    placed_cases     INTEGER,
    placement_rate   REAL,      -- 配置率 0.0〜1.0
    efficiency       REAL,      -- 体積効率 %
    pallet_count     INTEGER,
    tier_count       INTEGER,
    stability_score  REAL,
    calc_time_ms     REAL
)
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()
    return conn


def _compute_cv(values: List[float]) -> float:
    """変動係数（CV）= 標準偏差 / 平均。値が1件以下またはゼロ平均は0.0を返す。"""
    if len(values) < 2:
        return 0.0
    mean = statistics.mean(values)
    if mean == 0:
        return 0.0
    return statistics.stdev(values) / mean


def extract_case_features(cases_raw: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    ケース入力リストからフェーズ1ログ用の統計特徴量を計算して返す。

    Args:
        cases_raw: API リクエストの cases リスト（dict のリスト）

    Returns:
        特徴量 dict（pack_logs テーブルのカラム名と対応）
    """
    if not cases_raw:
        return {
            "num_skus": 0, "total_cases": 0,
            "weight_mean": 0.0, "weight_cv": 0.0,
            "volume_mean": 0.0, "volume_cv": 0.0,
            "fragile_ratio": 0.0, "temp_variety": 0,
            "has_no_flip": 0, "max_stack_min": 0,
        }

    # 品種ごとの情報（quantity を無視した品種単位の特徴量）
    num_skus = len(cases_raw)

    # ケース個数を展開した統計（quantity 分の重みで計算）
    weights_expanded: List[float] = []
    volumes_expanded: List[float] = []
    fragile_count = 0
    total_cases = 0
    temps = set()
    has_no_flip = False
    max_stack_values: List[int] = []

    for c in cases_raw:
        qty = int(c.get("quantity", 1))
        w = float(c.get("weight", 0))
        l = int(c.get("length", 0))
        wd = int(c.get("width", 0))
        h = int(c.get("height", 0))
        vol = l * wd * h

        weights_expanded.extend([w] * qty)
        volumes_expanded.extend([vol] * qty)
        total_cases += qty

        if bool(c.get("fragile", False)):
            fragile_count += qty

        temps.add(c.get("temperature", "normal"))

        if bool(c.get("no_flip", False)):
            has_no_flip = True

        max_stack_values.append(int(c.get("max_stack", 5)))

    weight_mean = statistics.mean(weights_expanded) if weights_expanded else 0.0
    weight_cv   = _compute_cv(weights_expanded)
    volume_mean = statistics.mean(volumes_expanded) if volumes_expanded else 0.0
    volume_cv   = _compute_cv(volumes_expanded)
    fragile_ratio = fragile_count / total_cases if total_cases > 0 else 0.0
    max_stack_min = min(max_stack_values) if max_stack_values else 0

    return {
        "num_skus":      num_skus,
        "total_cases":   total_cases,
        "weight_mean":   round(weight_mean, 3),
        "weight_cv":     round(weight_cv, 3),
        "volume_mean":   round(volume_mean, 1),
        "volume_cv":     round(volume_cv, 3),
        "fragile_ratio": round(fragile_ratio, 3),
        "temp_variety":  len(temps),
        "has_no_flip":   1 if has_no_flip else 0,
        "max_stack_min": max_stack_min,
    }


def insert_log(
    case_features: Dict[str, Any],
    supply_mode: str,
    beam_width: int,
    exec_mode: str,
    buffer_size: int,
    rules: Dict[str, Any],
    scoring: Dict[str, Any],
    result: Dict[str, Any],
    calc_time_ms: float,
) -> int:
    """
    1回の積付計算結果をDBに記録する。

    Returns:
        挿入された行の id
    """
    row = {
        "timestamp":        datetime.now().isoformat(timespec="seconds"),
        # ケース特徴量
        **case_features,
        # パラメータ
        "supply_mode":      supply_mode,
        "beam_width":       beam_width,
        "exec_mode":        exec_mode,
        "buffer_size":      buffer_size,
        "fragile_top":      1 if rules.get("fragile_top", True)  else 0,
        "heavy_bottom":     1 if rules.get("heavy_bottom", True) else 0,
        "same_group":       1 if rules.get("same_group", False)  else 0,
        "block_stacking":   1 if rules.get("block_stacking", False) else 0,
        "no_overhang":      1 if rules.get("no_overhang", True)  else 0,
        "temp_separate":    1 if rules.get("temp_separate", False) else 0,
        "center_priority":  1 if rules.get("center_priority", False) else 0,
        "outer_priority":   1 if rules.get("outer_priority", False) else 0,
        "stack_priority":   1 if rules.get("stack_priority", False) else 0,
        "overhang_limit":   float(rules.get("overhang_limit", 0.0)),
        "support_ratio_min": float(rules.get("support_ratio_min", 0.7)),
        "height_tolerance": int(rules.get("height_tolerance", 0)),
        "w_support":        float(scoring.get("w_support", 0.35)),
        "w_center":         float(scoring.get("w_center", 0.25)),
        "w_height":         float(scoring.get("w_height", 0.20)),
        "w_void":           float(scoring.get("w_void", 0.10)),
        "w_group":          float(scoring.get("w_group", 0.10)),
        # 結果KPI
        "placed_cases":     int(result.get("placed_cases", 0)),
        "placement_rate":   round(
            result.get("placed_cases", 0) / result.get("total_cases", 1), 4
        ) if result.get("total_cases", 0) > 0 else 0.0,
        "efficiency":       float(result.get("efficiency_pct", result.get("efficiency", 0.0))),
        "pallet_count":     int(result.get("pallet_count", 1)),
        "tier_count":       int(result.get("tier_count", 0)),
        "stability_score":  float(result.get("stability_score", 0.0)),
        "calc_time_ms":     round(calc_time_ms, 1),
    }

    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    sql = f"INSERT INTO pack_logs ({cols}) VALUES ({placeholders})"

    with _get_conn() as conn:
        cur = conn.execute(sql, list(row.values()))
        return cur.lastrowid


def get_logs(limit: Optional[int] = 200, offset: int = 0) -> List[Dict[str, Any]]:
    """最新のログを返す（新しい順）。limit=None で全件取得。"""
    # SQLite は LIMIT -1 で全件取得（OFFSET のみも可能になる）
    sql_limit = -1 if limit is None else limit
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pack_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (sql_limit, offset)
        ).fetchall()
    return [dict(r) for r in rows]


def get_log_count() -> int:
    with _get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM pack_logs").fetchone()[0]


def find_best_preset(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    入力ケース構成の特徴量に類似した過去ログを検索し、
    最もパレット枚数が少なかったパラメータ設定を返す。

    Returns:
        {
          "rules": {...},          # 推薦ルール設定
          "scoring": {...},        # 推薦スコアリング重み
          "preset_label": str,     # 人間可読ラベル
          "expected_pallets": float,
          "similar_count": int,    # 類似ケース数
          "reason": str
        }
    """
    tc   = features.get("total_cases", 0)
    ns   = features.get("num_skus", 0)
    wcv  = features.get("weight_cv", 0.0)

    # 類似判定: total_cases ±40%, num_skus ±4, weight_cv ±0.3
    tc_lo, tc_hi = tc * 0.6, tc * 1.4
    ns_lo, ns_hi = max(1, ns - 4), ns + 4
    wcv_lo, wcv_hi = max(0.0, wcv - 0.3), wcv + 0.3

    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT outer_priority, stack_priority, block_stacking, same_group,
                   center_priority, support_ratio_min, height_tolerance,
                   w_support, w_center, w_height, w_void, w_group,
                   AVG(pallet_count) as avg_pc, COUNT(*) as cnt
            FROM pack_logs
            WHERE total_cases BETWEEN ? AND ?
              AND num_skus    BETWEEN ? AND ?
              AND weight_cv   BETWEEN ? AND ?
            GROUP BY outer_priority, stack_priority, block_stacking, same_group,
                     center_priority, support_ratio_min, height_tolerance,
                     w_support, w_center, w_height, w_void, w_group
            HAVING cnt >= 1
            ORDER BY avg_pc ASC
            LIMIT 1
        """, (tc_lo, tc_hi, ns_lo, ns_hi, wcv_lo, wcv_hi)).fetchall()

    # 類似ケースが見つからなければ全体ベストにフォールバック
    if not rows:
        rows = conn.execute("""
            SELECT outer_priority, stack_priority, block_stacking, same_group,
                   center_priority, support_ratio_min, height_tolerance,
                   w_support, w_center, w_height, w_void, w_group,
                   AVG(pallet_count) as avg_pc, COUNT(*) as cnt
            FROM pack_logs
            GROUP BY outer_priority, stack_priority, block_stacking, same_group,
                     center_priority, support_ratio_min, height_tolerance,
                     w_support, w_center, w_height, w_void, w_group
            HAVING cnt >= 3
            ORDER BY avg_pc ASC
            LIMIT 1
        """).fetchall()
        similar_count = 0
    else:
        similar_count = int(rows[0]["cnt"])

    if not rows:
        # DBが空: デフォルト値を返す
        return {
            "rules":    {"outer_priority": True, "support_ratio_min": 0.5},
            "scoring":  {"w_support": 35, "w_center": 25, "w_height": 20, "w_void": 10, "w_group": 10},
            "preset_label": "外周優先＋支持率緩和",
            "expected_pallets": None,
            "similar_count": 0,
            "reason": "蓄積データなし。実績に基づくデフォルト推薦を適用しました。",
        }

    best = dict(rows[0])
    rules = {
        "outer_priority":   bool(best["outer_priority"]),
        "stack_priority":   bool(best["stack_priority"]),
        "block_stacking":   bool(best["block_stacking"]),
        "same_group":       bool(best["same_group"]),
        "center_priority":  bool(best["center_priority"]),
        "support_ratio_min": float(best["support_ratio_min"]),
        "height_tolerance": int(best["height_tolerance"]),
    }
    scoring = {
        "w_support": float(best["w_support"]),
        "w_center":  float(best["w_center"]),
        "w_height":  float(best["w_height"]),
        "w_void":    float(best["w_void"]),
        "w_group":   float(best["w_group"]),
    }

    # ラベル生成
    labels = []
    if rules["outer_priority"]:   labels.append("外周優先")
    if rules["stack_priority"]:   labels.append("縦積み優先")
    if rules["block_stacking"]:   labels.append("面積み優先")
    if rules["same_group"]:       labels.append("同品種集約")
    if rules["support_ratio_min"] < 0.65: labels.append("支持率緩和")
    if rules["height_tolerance"] > 0:     labels.append("高さ差許容")
    if not labels: labels.append("標準")
    preset_label = "＋".join(labels)

    reason_parts = []
    if similar_count > 0:
        reason_parts.append(f"類似ケース構成 {similar_count} 件の実績から推薦")
    else:
        reason_parts.append("全実績データから推薦")
    reason_parts.append(f"期待パレット枚数: {best['avg_pc']:.2f} 枚")

    return {
        "rules":            rules,
        "scoring":          scoring,
        "preset_label":     preset_label,
        "expected_pallets": round(float(best["avg_pc"]), 2),
        "similar_count":    similar_count,
        "reason":           " / ".join(reason_parts),
    }


def export_csv() -> str:
    """全ログをCSV文字列として返す。"""
    import csv, io
    rows = get_logs(limit=None)  # 全件取得

    if not rows:
        return ""

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
