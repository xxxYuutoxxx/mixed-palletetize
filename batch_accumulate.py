# -*- coding: utf-8 -*-
"""
batch_accumulate.py — dataフォルダのCSVを複数パラメータ設定で一括積付計算してログを蓄積する

使い方:
    python batch_accumulate.py          # 全プリセット実行
    python batch_accumulate.py default  # 特定プリセットのみ実行
"""
from __future__ import annotations
import csv
import json
import sys
import urllib.request
import base64
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
API_URL  = "http://127.0.0.1:8000/api/pack"
USER     = "admin"
PASSWORD = "palletize2026"

_auth = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Basic {_auth}",
}

# ---------------------------------------------------------------
# パラメータプリセット定義
# ---------------------------------------------------------------
# scoring キーは正規化前の整数値（server.py側で正規化する）
PRESETS: dict[str, dict] = {
    "default": {
        "scoring": {"w_support": 35, "w_center": 25, "w_height": 20, "w_void": 10, "w_group": 10},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "support_heavy": {
        "scoring": {"w_support": 55, "w_center": 20, "w_height": 15, "w_void": 5, "w_group": 5},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "height_heavy": {
        "scoring": {"w_support": 25, "w_center": 20, "w_height": 45, "w_void": 5, "w_group": 5},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "void_heavy": {
        "scoring": {"w_support": 25, "w_center": 20, "w_height": 20, "w_void": 30, "w_group": 5},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "center_heavy": {
        "scoring": {"w_support": 25, "w_center": 45, "w_height": 15, "w_void": 10, "w_group": 5},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "group_heavy": {
        "scoring": {"w_support": 25, "w_center": 20, "w_height": 20, "w_void": 10, "w_group": 25},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 1,
    },
    "beam3": {
        "scoring": {"w_support": 35, "w_center": 25, "w_height": 20, "w_void": 10, "w_group": 10},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 3,
    },
    "beam3_support": {
        "scoring": {"w_support": 55, "w_center": 20, "w_height": 15, "w_void": 5, "w_group": 5},
        "rules":   {"support_ratio_min": 0.7},
        "beam_width": 3,
    },
    "loose_support": {
        "scoring": {"w_support": 35, "w_center": 25, "w_height": 20, "w_void": 10, "w_group": 10},
        "rules":   {"support_ratio_min": 0.5},
        "beam_width": 1,
    },
    "block_stacking": {
        "scoring": {"w_support": 35, "w_center": 25, "w_height": 20, "w_void": 10, "w_group": 10},
        "rules":   {"support_ratio_min": 0.7, "block_stacking": True},
        "beam_width": 1,
    },
}


def load_csv(path: Path) -> list[dict]:
    cases = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            try:
                cases.append({
                    "sku_id":   str(row.get("品番", f"SKU{i}")),
                    "name":     str(row.get("品名", "")),
                    "length":   int(float(row.get("長さ", 0))),
                    "width":    int(float(row.get("幅",  0))),
                    "height":   int(float(row.get("高さ", 0))),
                    "weight":   float(row.get("重量", 0)),
                    "quantity": int(float(row.get("数量", 1))),
                })
            except (ValueError, KeyError) as e:
                print(f"  [skip row] {path.name} row {i+1}: {e}")
    return cases


def call_api(cases: list[dict], preset: dict) -> dict:
    body = {
        "cases":      cases,
        "scoring":    preset["scoring"],
        "rules":      preset.get("rules", {}),
        "beam_width": preset.get("beam_width", 1),
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def run_presets(target_presets: list[str]):
    csv_files = sorted(DATA_DIR.glob("*.csv"))
    n_files   = len(csv_files)
    n_presets = len(target_presets)
    total_runs = n_files * n_presets
    success = fail = 0
    run = 0

    print(f"ファイル数: {n_files}  プリセット数: {n_presets}  合計実行数: {total_runs}")
    print("-" * 60)

    for path in csv_files:
        cases = load_csv(path)
        if not cases:
            print(f"  {path.name}: ケースなし → スキップ")
            continue

        for preset_name in target_presets:
            run += 1
            preset = PRESETS[preset_name]
            try:
                result  = call_api(cases, preset)
                summary = result.get("summary", {})
                print(
                    f"[{run:4}/{total_runs}] {path.name:<12} "
                    f"({preset_name:<15}): "
                    f"{summary.get('placed_cases','?'):>3}/{summary.get('total_cases','?'):<3} "
                    f"効率{summary.get('efficiency_pct', 0):5.1f}% "
                    f"P{summary.get('pallet_count','?')}枚"
                )
                success += 1
            except Exception as e:
                print(f"[{run:4}/{total_runs}] {path.name} ({preset_name}): エラー → {e}")
                fail += 1

    print("-" * 60)
    print(f"完了: 成功 {success} / 失敗 {fail} / 合計 {total_runs}")


def main():
    if len(sys.argv) > 1:
        # コマンドライン引数でプリセット指定
        target = [p for p in sys.argv[1:] if p in PRESETS]
        unknown = [p for p in sys.argv[1:] if p not in PRESETS]
        if unknown:
            print(f"不明なプリセット: {unknown}")
            print(f"利用可能: {list(PRESETS.keys())}")
            return
    else:
        target = list(PRESETS.keys())

    run_presets(target)


if __name__ == "__main__":
    main()
