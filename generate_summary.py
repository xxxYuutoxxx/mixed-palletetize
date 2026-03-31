# -*- coding: utf-8 -*-
"""
generate_summary.py
全CSVデータに対して積み付け計算を実行し、
等角3D図付きのExcelサマリーを出力する。
"""
from __future__ import annotations
import sys
import io
import csv
import traceback
import math
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).parent))

from models import CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig
from packer import pack


# ---------------------------------------------------------------------------
# パレット設定（UIデフォルト値に合わせる）
# ---------------------------------------------------------------------------
DEFAULT_PALLET  = PalletConfig(max_height=1800, effective_height=1650)
DEFAULT_SUPPLY  = SupplyConfig(mode='fifo', buffer_size=5)
DEFAULT_RULES   = RuleConfig(
    fragile_top=False,
    heavy_bottom=True,
    center_priority=True,
    no_overhang=False,
    overhang_limit=25/1100,
    height_tolerance=5,
)
# ブラウザUIデフォルト値 (50,50,30,20,30) を正規化
_SW = 50 + 50 + 30 + 20 + 30  # 180
DEFAULT_SCORING = ScoreConfig(
    w_support = 50 / _SW,
    w_center  = 50 / _SW,
    w_height  = 30 / _SW,
    w_void    = 20 / _SW,
    w_group   = 30 / _SW,
)
DEFAULT_BEAM    = 5          # 高精度（ビームサーチ width=5）
DEFAULT_EXEC    = 'real'     # 現実制約モード


# ---------------------------------------------------------------------------
# CSV 読み込み
# ---------------------------------------------------------------------------
def parse_csv(filepath: Path) -> list[CaseItem]:
    """品番,品名,長さ,幅,高さ,重量,数量 フォーマットを読む"""
    cases: list[CaseItem] = []
    with open(filepath, encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader, None)          # ヘッダースキップ
        for row in reader:
            if len(row) < 7 or not row[0].strip():
                continue
            try:
                cases.append(CaseItem(
                    sku_id   = row[0].strip(),
                    name     = row[1].strip(),
                    length   = int(row[2]),
                    width    = int(row[3]),
                    height   = int(row[4]),
                    weight   = float(row[5]),
                    quantity = int(row[6]),
                ))
            except (ValueError, IndexError):
                continue
    return cases


# ---------------------------------------------------------------------------
# 等角3D図生成
# ---------------------------------------------------------------------------
SKU_COLORS = [
    '#4A90D9','#E74C3C','#2ECC71','#F39C12','#9B59B6',
    '#1ABC9C','#E67E22','#3498DB','#E91E63','#00BCD4',
    '#8BC34A','#FF5722','#607D8B','#795548','#FF9800',
    '#673AB7','#03A9F4','#8D6E63','#546E7A','#F06292',
]

def _hex_to_rgba(hex_color: str, alpha: float = 0.78) -> tuple:
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
    return (r, g, b, alpha)

def _draw_box(ax, x, y, z, dx, dy, dz, facecolor, edgecolor='#ffffff'):
    x0, x1 = x, x + dx
    y0, y1 = y, y + dy
    z0, z1 = z, z + dz
    faces = [
        [[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0]],   # bottom
        [[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]],   # top
        [[x0,y0,z0],[x1,y0,z0],[x1,y0,z1],[x0,y0,z1]],   # front
        [[x0,y1,z0],[x1,y1,z0],[x1,y1,z1],[x0,y1,z1]],   # back
        [[x0,y0,z0],[x0,y1,z0],[x0,y1,z1],[x0,y0,z1]],   # left
        [[x1,y0,z0],[x1,y1,z0],[x1,y1,z1],[x1,y0,z1]],   # right
    ]
    poly = Poly3DCollection(faces, facecolor=facecolor,
                            edgecolor=edgecolor, linewidth=0.35)
    ax.add_collection3d(poly)

def generate_isometric_figure(placements, pallet: PalletConfig,
                               case_id: str) -> io.BytesIO:
    """ブラウザ表示に近い3D積付図を生成し BytesIO で返す"""
    fig = plt.figure(figsize=(7, 6))
    ax = fig.add_subplot(111, projection='3d')

    # ブラウザのカメラ角度に近い視点（正面やや左上から）
    ax.view_init(elev=28, azim=-60)

    # SKU → 色マッピング
    skus = list(dict.fromkeys(p.sku_id for p in placements))
    sku_rgba = {
        sku: _hex_to_rgba(SKU_COLORS[i % len(SKU_COLORS)])
        for i, sku in enumerate(skus)
    }

    # 軸設定（描画前に確定してアスペクト比に使う）
    pl, pw = pallet.length, pallet.width
    max_z = max((p.z2 for p in placements), default=pallet.effective_height)
    z_top = max(max_z, 400)

    # パレット台座
    _draw_box(ax, 0, 0, -150,
              pallet.length, pallet.width, 150,
              facecolor=(0.60, 0.50, 0.35, 0.55),
              edgecolor='#888888')

    # 各ケース描画
    for p in placements:
        _draw_box(ax, p.x, p.y, p.z,
                  p.length, p.width, p.height,
                  facecolor=sku_rgba.get(p.sku_id, (0.29, 0.56, 0.85, 0.78)))

    ax.set_xlim(0, pl)
    ax.set_ylim(0, pw)
    ax.set_zlim(-150, z_top)

    # 実寸比率でボックスアスペクトを設定（縦横比を正確に）
    ax.set_box_aspect([pl, pw, z_top + 150])

    ax.set_xlabel('X(mm)', fontsize=7, labelpad=2)
    ax.set_ylabel('Y(mm)', fontsize=7, labelpad=2)
    ax.set_zlabel('Z(mm)', fontsize=7, labelpad=2)
    ax.tick_params(axis='both', labelsize=6, pad=1)
    ax.set_title(f'Case {case_id}', fontsize=9, fontweight='bold', pad=4)

    # 凡例（最大12品種まで）
    from matplotlib.patches import Patch
    legend_skus = skus[:12]
    handles = [
        Patch(facecolor=SKU_COLORS[i % len(SKU_COLORS)], label=sku)
        for i, sku in enumerate(legend_skus)
    ]
    if handles:
        ax.legend(handles=handles, loc='upper left',
                  fontsize=6, framealpha=0.6,
                  bbox_to_anchor=(-0.05, 1.0))

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=110, bbox_inches='tight',
                facecolor='white')
    buf.seek(0)
    plt.close(fig)
    return buf


# ---------------------------------------------------------------------------
# Excel 出力
# ---------------------------------------------------------------------------
def _make_border(style='thin'):
    s = Side(style=style)
    return Border(left=s, right=s, top=s, bottom=s)

HEADER_FILL  = PatternFill('solid', fgColor='1F4E79')
HEADER_FONT  = Font(name='メイリオ', bold=True, color='FFFFFF', size=9)
ALT_FILL     = PatternFill('solid', fgColor='EBF3FB')
CENTER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
BORDER       = _make_border()

SUMMARY_HEADERS = [
    ('ケース番号',    10),
    ('品種数',         7),
    ('総ケース数',     9),
    ('配置数',         7),
    ('未配置数',       8),
    ('パレット数',     9),
    ('体積効率(%)',   10),
    ('最大高さ(mm)',  11),
    ('総重量(kg)',    10),
    ('安定性\nスコア', 9),
    ('段数',           6),
    ('等角3D図',      42),
]

IMAGE_W_PX = 300    # Excel 画像幅 [px]
IMAGE_H_PX = 228    # Excel 画像高さ [px]
ROW_HEIGHT_PT = 174 # 行高 [pt]  ≈ IMAGE_H_PX * 72/96
MAX_PALLETS = 3     # 最大パレット数（列数）


def build_excel(results: list[dict], output_path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = 'サマリー一覧'

    # 画像列ヘッダーをパレット数分追加
    pallet_img_headers = [
        (f'等角3D図({i+1}枚目)', 42) for i in range(MAX_PALLETS)
    ]
    all_headers = SUMMARY_HEADERS + pallet_img_headers

    # ---- ヘッダー行 ----
    for col, (label, width) in enumerate(all_headers, 1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.alignment = CENTER_ALIGN
        cell.border    = BORDER
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 32

    # ---- データ行 ----
    for row_idx, d in enumerate(results, 2):
        fill = ALT_FILL if row_idx % 2 == 0 else None

        row_vals = [
            d['case_id'],
            d['sku_count'],
            d['total_cases'],
            d['placed_cases'],
            d['unplaced_cases'],
            d['pallet_count'],
            d['efficiency'],
            d['max_height'],
            d['total_weight'],
            d['stability_score'],
            d['tier_count'],
        ]
        for col, val in enumerate(row_vals, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.alignment = CENTER_ALIGN
            cell.border    = BORDER
            if fill:
                cell.fill = fill

        # パレットごとの 3D 図を各列に貼り付け
        img_bufs = d.get('img_bufs', [])
        for pallet_idx, img_buf in enumerate(img_bufs):
            if img_buf is None:
                continue
            try:
                img = XLImage(img_buf)
                img.width  = IMAGE_W_PX
                img.height = IMAGE_H_PX
                col_num = 12 + pallet_idx
                anchor = f"{get_column_letter(col_num)}{row_idx}"
                ws.add_image(img, anchor)
            except Exception as e:
                print(f"  [WARN] image insert error ({d['case_id']} pallet {pallet_idx+1}): {e}")

        ws.row_dimensions[row_idx].height = ROW_HEIGHT_PT

    # ---- 先頭行を固定 ----
    ws.freeze_panes = 'A2'

    wb.save(output_path)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    data_dir = Path('data')
    csv_files = sorted(data_dir.glob('*.csv'), key=lambda p: p.stem)

    print(f"CSV files found: {len(csv_files)}")
    print("-" * 60)

    results: list[dict] = []

    for csv_file in csv_files:
        case_id = csv_file.stem
        print(f"[{case_id}] ", end='', flush=True)

        try:
            cases = parse_csv(csv_file)
            if not cases:
                print("  no data, skip")
                continue

            result = pack(cases, DEFAULT_PALLET, DEFAULT_SUPPLY,
                          DEFAULT_RULES, DEFAULT_SCORING,
                          exec_mode=DEFAULT_EXEC, beam_width=DEFAULT_BEAM)

            # パレットごとに等角3D図を生成
            pallet_ids = sorted(set(p.pallet_id for p in result.placements))
            img_bufs = []
            for pid in pallet_ids:
                pallet_placements = [p for p in result.placements if p.pallet_id == pid]
                label = f"{case_id}-P{pid}" if len(pallet_ids) > 1 else case_id
                try:
                    buf = generate_isometric_figure(pallet_placements, DEFAULT_PALLET, label)
                except Exception as img_e:
                    print(f"[fig error P{pid}: {img_e}] ", end='')
                    buf = None
                img_bufs.append(buf)

            results.append({
                'case_id':        case_id,
                'sku_count':      len(cases),
                'total_cases':    result.total_cases,
                'placed_cases':   result.placed_cases,
                'unplaced_cases': len(result.unplaced),
                'pallet_count':   result.pallet_count,
                'efficiency':     result.efficiency,
                'max_height':     result.max_height_used,
                'total_weight':   result.total_weight,
                'stability_score':result.stability_score,
                'tier_count':     result.tier_count,
                'img_bufs':       img_bufs,
            })

            status = "OK" if not result.unplaced else f"NG(unplaced={len(result.unplaced)})"
            print(f"  {status}  placed={result.placed_cases}/{result.total_cases}"
                  f"  eff={result.efficiency}%  h={result.max_height_used}mm"
                  f"  w={result.total_weight}kg  pallets={result.pallet_count}")

        except Exception as e:
            print(f"ERROR: {e}")
            traceback.print_exc()

    # Excel 出力
    output_path = 'Summary_混載パレタイズ積付計算結果.xlsx'
    print("-" * 60)
    print(f"Writing Excel... ({len(results)} cases)")
    build_excel(results, output_path)
    print(f"Done: {output_path}")


if __name__ == '__main__':
    main()
