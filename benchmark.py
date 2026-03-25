# -*- coding: utf-8 -*-
"""
benchmark.py — ベンチマーク評価スクリプト
5種類の固定ケース群をまとめて評価し、各種指標を出力する。

実行方法:
    python benchmark.py
    python benchmark.py --verbose    # 制約ヒット詳細も表示
"""
from __future__ import annotations
import sys
import time
import argparse

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from models import CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig
from packer import pack

# ---------------------------------------------------------------------------
# 共通設定
# ---------------------------------------------------------------------------

PALLET = PalletConfig(
    length=1100, width=1100, base_height=150,
    max_height=1650, effective_height=1500, max_weight=1000.0
)
RULES  = RuleConfig(
    fragile_top=True, heavy_bottom=True, no_overhang=True,
    support_ratio_min=0.7
)
SCORE  = ScoreConfig()

# ---------------------------------------------------------------------------
# ベンチマークシナリオ定義
# ---------------------------------------------------------------------------

SCENARIOS = {
    "easy": {
        "name": "積みやすいケース（均一サイズ）",
        "desc": "同サイズ・同重量の箱を均一配置。高効率が期待される基本ケース。",
        "cases": [
            CaseItem("E001", "均一箱A", 400, 300, 250, 10.0, 12),
            CaseItem("E002", "均一箱B", 400, 300, 250,  9.0, 10),
            CaseItem("E003", "均一箱C", 400, 300, 250,  8.5,  8),
        ],
        "supply_mode": "free",
        "exec_mode":   "real",
    },

    "varied": {
        "name": "寸法ばらつき大ケース",
        "desc": "大中小が混在するケース。スコアリングの空隙・支持率制御を検証する。",
        "cases": [
            CaseItem("V001", "大型箱",   500, 400, 350, 22.0, 4),
            CaseItem("V002", "中型箱",   350, 250, 200, 10.0, 8),
            CaseItem("V003", "小型箱",   200, 160, 150,  3.0, 15),
            CaseItem("V004", "細長箱",   450, 150, 280,  8.0, 6),
            CaseItem("V005", "扁平箱",   380, 320,  95,  5.0, 10),
        ],
        "supply_mode": "free",
        "exec_mode":   "real",
    },

    "fragile_heavy": {
        "name": "fragile制約強ケース",
        "desc": "重量物 + 割れ物が混在。fragile_top / heavy_bottom 制約の効き具合を検証する。",
        "cases": [
            CaseItem("F001", "重量品A",  420, 360, 320, 35.0, 4, fragile=False),
            CaseItem("F002", "重量品B",  400, 340, 290, 28.0, 4, fragile=False),
            CaseItem("F003", "ガラス品", 310, 260, 210,  5.0, 6, fragile=True),
            CaseItem("F004", "精密機器", 290, 240, 190,  4.5, 5, fragile=True),
            CaseItem("F005", "陶磁器",   260, 220, 180,  3.5, 5, fragile=True),
        ],
        "supply_mode": "free",
        "exec_mode":   "real",
    },

    "fifo_unfavorable": {
        "name": "FIFO不利ケース",
        "desc": "軽量小型品が先頭にある供給順。FIFOだと重い物を先に置けず積載率が低下する。",
        "cases": [
            # 軽い小さいものが最初に来る（FIFOで不利）
            CaseItem("I001", "小型軽量A", 200, 160, 150,  2.0, 8),
            CaseItem("I002", "小型軽量B", 220, 180, 160,  3.0, 6),
            CaseItem("I003", "中型品",    350, 280, 240, 12.0, 6),
            CaseItem("I004", "大型重量X", 460, 400, 360, 38.0, 3),
            CaseItem("I005", "大型重量Y", 440, 380, 340, 32.0, 3),
        ],
        "supply_mode": "fifo",
        "exec_mode":   "real",
    },

    "impossible": {
        "name": "積載不能ケース混在",
        "desc": "パレット寸法超過・重量超過・通常品が混在。未配置ケースの扱いを確認する。",
        "cases": [
            CaseItem("P001", "通常品A",       380, 290, 210,  9.0, 5),
            CaseItem("P002", "通常品B",       320, 240, 180,  7.0, 4),
            CaseItem("P003", "超大型（不可）", 1200, 1100, 300, 40.0, 2),
            CaseItem("P004", "超高型（不可）", 300, 300, 1600, 15.0, 1),
            CaseItem("P005", "重量超過品",     400, 350, 300, 400.0, 3),
        ],
        "supply_mode": "free",
        "exec_mode":   "real",
    },
}

# ---------------------------------------------------------------------------
# 実行・集計
# ---------------------------------------------------------------------------

def run_scenario(key: str, scenario: dict, verbose: bool = False) -> dict:
    """1シナリオを実行して指標を返す"""
    cases = scenario["cases"]
    supply = SupplyConfig(mode=scenario["supply_mode"])
    rules  = RULES

    t0 = time.perf_counter()
    result = pack(cases, PALLET, supply, rules, SCORE,
                  exec_mode=scenario["exec_mode"])
    elapsed_ms = (time.perf_counter() - t0) * 1000

    hits = result.constraint_hits.to_dict()
    total_checked = hits.pop("総チェック数", 0)

    return {
        "key":               key,
        "name":              scenario["name"],
        "placed_cases":      result.placed_cases,
        "total_cases":       result.total_cases,
        "unplaced_cases":    len(result.unplaced),
        "pallet_count":      result.pallet_count,
        "efficiency_pct":    result.efficiency,
        "max_height_used_mm": result.max_height_used,
        "total_weight_kg":   result.total_weight,
        "stability_score":   result.stability_score,
        "calc_time_ms":      round(elapsed_ms, 1),
        "warnings":          result.warnings,
        "constraint_hits":   hits,
        "total_checked":     total_checked,
    }


def print_table(results: list, verbose: bool = False) -> None:
    """集計テーブルをコンソールに出力"""
    cols = [
        ("シナリオ",        "name",              28),
        ("配置/合計",       "placed_total",       10),
        ("未配置",          "unplaced_cases",      6),
        ("パレット",        "pallet_count",        6),
        ("効率%",           "efficiency_pct",      7),
        ("使用高mm",        "max_height_used_mm",  8),
        ("総重kg",          "total_weight_kg",     8),
        ("安定性",          "stability_score",     7),
        ("計算ms",          "calc_time_ms",        8),
    ]

    header = "  ".join(h.center(w) for h, _, w in cols)
    sep    = "  ".join("-" * w for _, _, w in cols)
    print("\n" + "=" * len(sep))
    print("  ベンチマーク評価結果")
    print("=" * len(sep))
    print(header)
    print(sep)

    for r in results:
        r["placed_total"] = f"{r['placed_cases']}/{r['total_cases']}"
        row = []
        for _, key, w in cols:
            v = str(r.get(key, ""))
            row.append(v.ljust(w) if key == "name" else v.center(w))
        print("  ".join(row))
        if r["warnings"]:
            for w_msg in r["warnings"]:
                print(f"    ⚠ {w_msg}")

    print("=" * len(sep))

    if verbose:
        print("\n【制約ヒット集計（棄却理由）】")
        hit_labels = ["範囲外","衝突","支持率不足","fragile違反",
                      "重量物違反","積段数超過","温度帯違反","総重量超過","上面荷重超過"]
        header2 = f"  {'シナリオ':<20}" + "".join(f"  {lb:>10}" for lb in hit_labels) + f"  {'総候補数':>8}"
        print(header2)
        print("  " + "-" * (len(header2) - 2))
        for r in results:
            hits = r["constraint_hits"]
            row2 = f"  {r['key']:<20}" + "".join(
                f"  {hits.get(lb, 0):>10}" for lb in hit_labels
            ) + f"  {r['total_checked']:>8}"
            print(row2)
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="混載パレタイズ ベンチマーク評価")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="制約ヒット詳細を表示")
    parser.add_argument("--scenario", "-s", default=None,
                        help="特定シナリオのみ実行 (easy/varied/fragile_heavy/fifo_unfavorable/impossible)")
    args = parser.parse_args()

    targets = SCENARIOS
    if args.scenario:
        if args.scenario not in SCENARIOS:
            print(f"[ERROR] 不明なシナリオ: {args.scenario}")
            print(f"  選択肢: {list(SCENARIOS.keys())}")
            sys.exit(1)
        targets = {args.scenario: SCENARIOS[args.scenario]}

    results = []
    for key, scenario in targets.items():
        print(f"  実行中: [{key}] {scenario['name']} ...", end="", flush=True)
        r = run_scenario(key, scenario, verbose=args.verbose)
        results.append(r)
        print(f" {r['calc_time_ms']:.1f}ms")

    print_table(results, verbose=args.verbose)

    # スコア内訳の表示（最初のシナリオの最初の5配置）
    if args.verbose and results:
        print("【スコア内訳サンプル（easyシナリオ 先頭5配置）】")
        cases_easy = SCENARIOS["easy"]["cases"]
        supply_easy = SupplyConfig(mode="free")
        result_easy = pack(cases_easy, PALLET, supply_easy, RULES, SCORE, exec_mode="real")
        print(f"  {'No':>3}  {'SKU':<10}  {'支持率':>6}  {'重心':>6}  {'高さ':>6}  {'空隙':>6}  {'集約':>6}  {'合計':>6}")
        print("  " + "-" * 60)
        for i, p in enumerate(result_easy.placements[:5]):
            if p.score_breakdown:
                bd = p.score_breakdown
                print(
                    f"  {i+1:>3}  {p.sku_id:<10}  "
                    f"{bd.support_score:>6.3f}  {bd.center_score:>6.3f}  "
                    f"{bd.height_score:>6.3f}  {bd.void_score:>6.3f}  "
                    f"{bd.group_score:>6.3f}  {bd.total_score:>6.3f}"
                )
        print()


if __name__ == "__main__":
    main()
