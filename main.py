# -*- coding: utf-8 -*-
"""
main.py — CLIエントリポイント
使用例:
    python main.py sample_free.json
    python main.py sample_fifo.json --output result.json --viz
    python main.py sample_impossible.json --mode ideal --viz --top
"""
from __future__ import annotations
import argparse
import json
import sys
import os

# Windows コンソール UTF-8 出力対応
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from io_handler import load_input_file, parse_input, result_to_dict, save_output_file
from packer import pack
from visualize import visualize_3d, visualize_top_view, MATPLOTLIB_AVAILABLE


def print_summary(result, verbose: bool = False) -> None:
    s = result
    print("\n" + "=" * 55)
    print("  積付計算結果サマリー")
    print("=" * 55)
    print(f"  モード          : {s.exec_mode} / 供給:{s.supply_mode}")
    print(f"  配置ケース数    : {s.placed_cases} / {s.total_cases}")
    print(f"  未配置ケース数  : {len(s.unplaced)}")
    print(f"  使用パレット数  : {s.pallet_count}")
    print(f"  体積効率        : {s.efficiency:.1f}%")
    print(f"  実使用高さ      : {s.max_height_used} mm")
    print(f"  総重量          : {s.total_weight:.1f} kg")
    print(f"  安定性スコア    : {s.stability_score:.1f} / 100")
    print(f"  段数            : {s.tier_count}")
    print(f"  適用ルール      : {', '.join(s.applied_rules) if s.applied_rules else 'なし'}")

    if s.warnings:
        print("\n  [警告]")
        for w in s.warnings:
            print(f"    ⚠ {w}")

    if s.unplaced:
        print("\n  [未配置ケース]")
        for u in s.unplaced:
            print(f"    - {u['sku_id']} ({u['name']}): {u['reason']}")

    if verbose and s.placements:
        print("\n  [配置詳細]")
        print(f"  {'#':>3}  {'SKU':<12} {'X':>5} {'Y':>5} {'Z':>5} "
              f"{'L':>5} {'W':>5} {'H':>5} {'rot':>4}")
        print("  " + "-" * 52)
        for i, p in enumerate(s.placements):
            print(f"  {i+1:>3}  {p.sku_id:<12} {p.x:>5} {p.y:>5} {p.z:>5} "
                  f"{p.length:>5} {p.width:>5} {p.height:>5} {p.rotation:>3}°")

    print("=" * 55 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="混載パレタイズ積付計算システム Phase 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python main.py sample_free.json
  python main.py sample_fifo.json --output result.json --viz
  python main.py sample_free.json --mode ideal --viz --top --verbose
        """
    )
    parser.add_argument("input", help="入力JSONファイルパス")
    parser.add_argument(
        "--output", "-o", default=None,
        help="出力JSONファイルパス (省略時は <input_stem>_result.json)"
    )
    parser.add_argument(
        "--mode", "-m", choices=["real", "ideal", "robot"],
        default=None,
        help="実行モード上書き (入力JSONのexec_modeより優先)"
    )
    parser.add_argument(
        "--viz", "-v", action="store_true",
        help="3D可視化画像を出力する"
    )
    parser.add_argument(
        "--top", "-t", action="store_true",
        help="上面図も出力する"
    )
    parser.add_argument(
        "--show", action="store_true",
        help="matplotlib ウィンドウを表示する (GUI環境のみ)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="配置詳細を表示する"
    )
    parser.add_argument(
        "--max-pallets", type=int, default=10,
        help="最大使用パレット数 (デフォルト: 10)"
    )

    args = parser.parse_args()

    # 入力ファイル読み込み
    if not os.path.exists(args.input):
        print(f"[ERROR] 入力ファイルが見つかりません: {args.input}", file=sys.stderr)
        return 1

    try:
        data = load_input_file(args.input)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSONパースエラー: {e}", file=sys.stderr)
        return 1

    try:
        cases, pallet, supply, rules, score_cfg, exec_mode = parse_input(data)
    except (KeyError, ValueError, TypeError) as e:
        print(f"[ERROR] 入力データ形式エラー: {e}", file=sys.stderr)
        return 1

    # モード上書き
    if args.mode:
        exec_mode = args.mode

    print(f"\n入力: {args.input}")
    print(f"  ケース種類: {len(cases)} SKU / 供給モード: {supply.mode} / 実行モード: {exec_mode}")
    print(f"  パレット: {pallet.length}×{pallet.width}mm / 有効高さ: {pallet.effective_height}mm")

    # 計算実行
    result = pack(
        cases=cases,
        pallet=pallet,
        supply=supply,
        rules=rules,
        score_cfg=score_cfg,
        exec_mode=exec_mode,
        max_pallets=args.max_pallets
    )

    # サマリー表示
    print_summary(result, verbose=args.verbose)

    # 出力JSONパス決定
    input_stem = os.path.splitext(os.path.basename(args.input))[0]
    output_path = args.output or f"{input_stem}_result.json"

    # JSON出力
    out_data = result_to_dict(result, pallet)
    save_output_file(out_data, output_path)
    print(f"結果JSON: {output_path}")

    # 可視化
    if args.viz:
        if not MATPLOTLIB_AVAILABLE:
            print("[WARN] matplotlib が未インストールです: pip install matplotlib")
        else:
            viz_path = f"{input_stem}_3d.png"
            title = f"積付結果 [{exec_mode}モード / 供給:{supply.mode}]"
            out = visualize_3d(result, pallet, viz_path, title=title, show=args.show)
            if out:
                print(f"3Dビュー: {out}")

            if args.top:
                top_path = f"{input_stem}_top.png"
                out2 = visualize_top_view(result, pallet, top_path)
                if out2:
                    print(f"上面図  : {out2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
