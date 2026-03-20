"""
visualize.py — matplotlib による3D積付可視化
"""
from __future__ import annotations
from typing import List, Optional
import math

try:
    import matplotlib
    matplotlib.use("Agg")  # GUI不要のバックエンド
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from mpl_toolkits.mplot3d import Axes3D
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from models import Placement, PalletConfig, PackResult


def _make_box_faces(x, y, z, dx, dy, dz):
    """直方体の6面を Poly3DCollection 用の頂点リストで返す"""
    x2, y2, z2 = x + dx, y + dy, z + dz
    faces = [
        # Bottom
        [[x, y, z], [x2, y, z], [x2, y2, z], [x, y2, z]],
        # Top
        [[x, y, z2], [x2, y, z2], [x2, y2, z2], [x, y2, z2]],
        # Front (y=y)
        [[x, y, z], [x2, y, z], [x2, y, z2], [x, y, z2]],
        # Back (y=y2)
        [[x, y2, z], [x2, y2, z], [x2, y2, z2], [x, y2, z2]],
        # Left (x=x)
        [[x, y, z], [x, y2, z], [x, y2, z2], [x, y, z2]],
        # Right (x=x2)
        [[x2, y, z], [x2, y2, z], [x2, y2, z2], [x2, y, z2]],
    ]
    return faces


def _hex_to_rgb(hex_color: str):
    """#RRGGBB → (r, g, b) 0〜1"""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16) / 255
    g = int(h[2:4], 16) / 255
    b = int(h[4:6], 16) / 255
    return r, g, b


DEFAULT_COLORS = [
    "#4A90D9", "#E67E22", "#2ECC71", "#9B59B6",
    "#E74C3C", "#1ABC9C", "#F39C12", "#3498DB",
    "#D35400", "#27AE60", "#8E44AD", "#C0392B",
]


def visualize_3d(
    result: PackResult,
    pallet: PalletConfig,
    output_path: str = "palletize_result.png",
    title: str = "積付結果 3Dビュー",
    show: bool = False
) -> Optional[str]:
    """
    3D積付結果を matplotlib で描画し PNG 保存する。
    MATPLOTLIB_AVAILABLE が False の場合は None を返す。
    """
    if not MATPLOTLIB_AVAILABLE:
        print("[WARN] matplotlib が見つかりません。可視化をスキップします。")
        return None

    fig = plt.figure(figsize=(14, 9))
    ax = fig.add_subplot(111, projection="3d")

    # SKU別カラーマップ
    sku_ids = list(dict.fromkeys(p.sku_id for p in result.placements))
    sku_color_map = {}
    for i, sid in enumerate(sku_ids):
        # placement に color が設定されていればそれを使う
        for p in result.placements:
            if p.sku_id == sid:
                sku_color_map[sid] = p.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
                break

    # パレット台を描画（薄いグレー）
    pallet_faces = _make_box_faces(
        0, 0, -pallet.base_height,
        pallet.length, pallet.width, pallet.base_height
    )
    pallet_poly = Poly3DCollection(pallet_faces, alpha=0.15, linewidth=0.5)
    pallet_poly.set_facecolor("gray")
    pallet_poly.set_edgecolor("dimgray")
    ax.add_collection3d(pallet_poly)

    # 有効積付高さの上限ライン（破線）
    lx = [0, pallet.length, pallet.length, 0, 0]
    ly = [0, 0, pallet.width, pallet.width, 0]
    lz = [pallet.effective_height] * 5
    ax.plot(lx, ly, lz, "r--", linewidth=1, alpha=0.6, label=f"有効高さ {pallet.effective_height}mm")

    # ケースを描画
    for p in result.placements:
        hex_c = sku_color_map.get(p.sku_id, "#4A90D9")
        r, g, b = _hex_to_rgb(hex_c)
        faces = _make_box_faces(p.x, p.y, p.z, p.length, p.width, p.height)
        poly = Poly3DCollection(faces, alpha=0.75, linewidth=0.5)
        poly.set_facecolor((r, g, b, 0.75))
        poly.set_edgecolor("black")
        ax.add_collection3d(poly)

        # ケース中心にSKU IDラベル
        cx = p.x + p.length / 2
        cy = p.y + p.width / 2
        cz = p.z + p.height / 2
        short_id = p.sku_id[:6] if len(p.sku_id) > 6 else p.sku_id
        ax.text(cx, cy, cz, short_id, fontsize=6, ha="center", va="center",
                color="white", fontweight="bold")

    # 軸設定
    ax.set_xlim(0, pallet.length)
    ax.set_ylim(0, pallet.width)
    ax.set_zlim(-pallet.base_height, pallet.effective_height)
    ax.set_xlabel("X (mm)", fontsize=9)
    ax.set_ylabel("Y (mm)", fontsize=9)
    ax.set_zlabel("Z (mm)", fontsize=9)
    ax.set_title(title, fontsize=12, fontweight="bold")

    # 視点
    ax.view_init(elev=25, azim=-60)

    # 凡例
    legend_handles = [
        mpatches.Patch(color=sku_color_map[sid], label=sid)
        for sid in sku_ids
    ]
    ax.legend(handles=legend_handles, loc="upper left", fontsize=7,
              bbox_to_anchor=(0.0, 1.0))

    # KPI テキスト
    kpi_text = (
        f"配置: {result.placed_cases}/{result.total_cases}個  "
        f"効率: {result.efficiency:.1f}%  "
        f"高さ: {result.max_height_used}mm  "
        f"重量: {result.total_weight:.1f}kg  "
        f"安定: {result.stability_score:.1f}"
    )
    fig.text(0.5, 0.02, kpi_text, ha="center", fontsize=10,
             bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)

    return output_path


def visualize_top_view(
    result: PackResult,
    pallet: PalletConfig,
    output_path: str = "palletize_top.png",
    title: str = "積付結果 上面図"
) -> Optional[str]:
    """
    上面図（最上層のみ表示）を描画する簡易ビュー
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    fig, ax = plt.subplots(figsize=(8, 8))

    # パレット外形
    ax.set_xlim(-50, pallet.length + 50)
    ax.set_ylim(-50, pallet.width + 50)
    pallet_rect = mpatches.Rectangle(
        (0, 0), pallet.length, pallet.width,
        linewidth=2, edgecolor="black", facecolor="whitesmoke"
    )
    ax.add_patch(pallet_rect)

    sku_ids = list(dict.fromkeys(p.sku_id for p in result.placements))
    sku_color_map = {}
    for i, sid in enumerate(sku_ids):
        for p in result.placements:
            if p.sku_id == sid:
                sku_color_map[sid] = p.color or DEFAULT_COLORS[i % len(DEFAULT_COLORS)]
                break

    # 各ケースを上面から描画（上の層ほど後から描画）
    sorted_placements = sorted(result.placements, key=lambda p: p.z)
    for p in sorted_placements:
        hex_c = sku_color_map.get(p.sku_id, "#4A90D9")
        rect = mpatches.Rectangle(
            (p.x, p.y), p.length, p.width,
            linewidth=1, edgecolor="black", facecolor=hex_c, alpha=0.7
        )
        ax.add_patch(rect)
        ax.text(p.x + p.length / 2, p.y + p.width / 2,
                f"{p.sku_id}\nZ={p.z}", fontsize=7, ha="center", va="center",
                color="white", fontweight="bold")

    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(title)

    legend_handles = [
        mpatches.Patch(color=sku_color_map[sid], label=sid)
        for sid in sku_ids
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    return output_path
