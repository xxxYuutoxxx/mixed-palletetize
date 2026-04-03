# -*- coding: utf-8 -*-
"""
server.py — FastAPI サーバー
フロントエンド(index.html)とバックエンド(packer.py等)を繋ぐAPIサーバー

起動方法:
    pip install fastapi uvicorn
    python server.py
"""
from __future__ import annotations
import os
import secrets
import time
import uvicorn
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from typing import List, Any, Dict, Optional

from models import CaseItem, PalletConfig, SupplyConfig, RuleConfig, ScoreConfig
from packer import pack
from io_handler import result_to_dict
from log_db import extract_case_features, insert_log, get_logs, get_log_count, export_csv

app = FastAPI(title="パレタイズ積付計算システム")
BASE_DIR = Path(__file__).parent
security = HTTPBasic()

# 環境変数からID/パスワードを取得（未設定時はデフォルト値）
APP_USER     = os.environ.get("APP_USER",     "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "palletize2026")


def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username.encode(), APP_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), APP_PASSWORD.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="認証に失敗しました",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def index():
    return (BASE_DIR / "index.html").read_text(encoding="utf-8")


class PackRequest(BaseModel):
    cases: List[Dict[str, Any]]
    pallet: Dict[str, Any] = {}
    supply: Dict[str, Any] = {}
    rules: Dict[str, Any] = {}
    scoring: Dict[str, Any] = {}
    exec_mode: str = "real"
    beam_width: int = 1


@app.post("/api/pack", dependencies=[Depends(require_auth)])
def api_pack(req: PackRequest):
    import json
    print("\n=== REQUEST PARAMS ===")
    print(json.dumps({"pallet": req.pallet, "supply": req.supply, "rules": req.rules, "exec_mode": req.exec_mode, "beam_width": req.beam_width}, ensure_ascii=False, indent=2))
    print("=====================\n")
    cases = [
        CaseItem(
            sku_id=c.get("sku_id", ""),
            name=c.get("name", ""),
            length=int(c.get("length", 0)),
            width=int(c.get("width", 0)),
            height=int(c.get("height", 0)),
            weight=float(c.get("weight", 0)),
            quantity=int(c.get("quantity", 1)),
            fragile=bool(c.get("fragile", False)),
            stackable=bool(c.get("stackable", True)),
            max_stack=int(c.get("max_stack", 5)),
            group=c.get("group", ""),
            temperature=c.get("temperature", "normal"),
            color=c.get("color", "#4A90D9"),
            max_top_load=float(c.get("max_top_load", 0.0)),
            no_flip=bool(c.get("no_flip", False)),
            support_ratio_required=float(c.get("support_ratio_required", 0.0)),
        )
        for c in req.cases
    ]

    p = req.pallet
    pallet = PalletConfig(
        length=int(p.get("length", 1100)),
        width=int(p.get("width", 1100)),
        base_height=int(p.get("base_height", 150)),
        max_height=int(p.get("max_height", 1650)),
        effective_height=int(p.get("effective_height", 1500)),
        max_weight=float(p.get("max_weight", 1000.0)),
    )

    s = req.supply
    supply = SupplyConfig(
        mode=s.get("mode", "free"),
        buffer_size=int(s.get("buffer_size", 3)),
        fifo_strict=bool(s.get("fifo_strict", True)),
    )

    r = req.rules
    rules = RuleConfig(
        fragile_top=bool(r.get("fragile_top", True)),
        heavy_bottom=bool(r.get("heavy_bottom", True)),
        same_group=bool(r.get("same_group", False)),
        center_priority=bool(r.get("center_priority", False)),
        outer_priority=bool(r.get("outer_priority", False)),
        stack_priority=bool(r.get("stack_priority", False)),
        no_overhang=bool(r.get("no_overhang", True)),
        temp_separate=bool(r.get("temp_separate", False)),
        overhang_limit=float(r.get("overhang_limit", 0.0)),
        support_ratio_min=float(r.get("support_ratio_min", 0.7)),
        height_tolerance=int(r.get("height_tolerance", 0)),
        block_stacking=bool(r.get("block_stacking", False)),
    )

    sc = req.scoring
    total_w = sum([
        sc.get("w_support", 35), sc.get("w_center", 25),
        sc.get("w_height", 20), sc.get("w_void", 10), sc.get("w_group", 10)
    ])
    def norm(v):
        return float(v) / total_w if total_w > 0 else 0.0

    score_cfg = ScoreConfig(
        w_support=norm(sc.get("w_support", 35)),
        w_center=norm(sc.get("w_center", 25)),
        w_height=norm(sc.get("w_height", 20)),
        w_void=norm(sc.get("w_void", 10)),
        w_group=norm(sc.get("w_group", 10)),
        w_block=float(sc.get("w_block", 0.50)),  # ブロック積み重みは別途正規化
    )

    beam_width = max(1, min(int(req.beam_width), 10))  # 1〜10 に制限

    t0 = time.perf_counter()
    result = pack(cases, pallet, supply, rules, score_cfg,
                  exec_mode=req.exec_mode, beam_width=beam_width)
    calc_time_ms = (time.perf_counter() - t0) * 1000

    result_dict = result_to_dict(result, pallet)

    # ログ記録（失敗しても計算結果は返す）
    try:
        insert_log(
            case_features=extract_case_features(req.cases),
            supply_mode=req.supply.get("mode", "free"),
            beam_width=beam_width,
            exec_mode=req.exec_mode,
            buffer_size=int(req.supply.get("buffer_size", 3)),
            rules=req.rules,
            scoring={
                "w_support": sc.get("w_support", 35),
                "w_center":  sc.get("w_center", 25),
                "w_height":  sc.get("w_height", 20),
                "w_void":    sc.get("w_void", 10),
                "w_group":   sc.get("w_group", 10),
            },
            result=result_dict.get("summary", result_dict),
            calc_time_ms=calc_time_ms,
        )
    except Exception as e:
        print(f"[log_db] ログ記録に失敗しました: {e}")

    return result_dict


@app.get("/api/logs", dependencies=[Depends(require_auth)])
def api_logs(limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    """蓄積された積付計算ログを返す（新しい順）。"""
    rows = get_logs(limit=limit, offset=offset)
    total = get_log_count()
    return {"total": total, "limit": limit, "offset": offset, "logs": rows}


@app.get("/api/logs/export", dependencies=[Depends(require_auth)], response_class=PlainTextResponse)
def api_logs_export():
    """全ログをCSV形式でダウンロードする。"""
    csv_text = export_csv()
    from fastapi.responses import Response
    return Response(
        content=csv_text.encode("utf-8-sig"),  # BOM付きUTF-8（Excel対応）
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=pack_logs.csv"},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
