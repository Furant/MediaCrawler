# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/api/routers/crawler.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#
# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os

from ..schemas import CrawlerStartRequest, CrawlerStatusResponse, SaveDataOptionEnum
from ..services import crawler_manager

router = APIRouter(prefix="/crawler", tags=["crawler"])


@router.post("/start")
async def start_crawler(request: CrawlerStartRequest):
    """Start crawler task"""
    success = await crawler_manager.start(request)
    if not success:
        # Handle concurrent/duplicate requests: if process is already running, return 400 instead of 500
        if crawler_manager.process and crawler_manager.process.poll() is None:
            raise HTTPException(status_code=400, detail="Crawler is already running")
        raise HTTPException(status_code=500, detail="Failed to start crawler")

    return {"status": "ok", "message": "Crawler started successfully"}


@router.post("/stop")
async def stop_crawler():
    """Stop crawler task"""
    success = await crawler_manager.stop()
    if not success:
        # Handle concurrent/duplicate requests: if process already exited/doesn't exist, return 400 instead of 500
        if not crawler_manager.process or crawler_manager.process.poll() is not None:
            raise HTTPException(status_code=400, detail="No crawler is running")
        raise HTTPException(status_code=500, detail="Failed to stop crawler")

    return {"status": "ok", "message": "Crawler stopped successfully"}


@router.get("/status", response_model=CrawlerStatusResponse)
async def get_crawler_status():
    """Get crawler status"""
    return crawler_manager.get_status()


@router.get("/logs")
async def get_logs(limit: int = 100):
    """Get recent logs"""
    logs = crawler_manager.logs[-limit:] if limit > 0 else crawler_manager.logs
    return {"logs": [log.model_dump() for log in logs]}


# ---- 下面是给后端服务（如 freud-collect）调用的同步一次性抓取接口 ----

DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _find_latest_json_files(platform: str) -> Dict[str, Optional[Path]]:
    """
    在 data 目录下为指定平台找到最新的 contents / comments json 文件（如果有）。
    约定路径类似：data/xhs/json/search_contents_xxx.json / search_comments_xxx.json
    """
    if not DATA_DIR.exists():
        return {"contents": None, "comments": None}

    latest_contents: Optional[Path] = None
    latest_comments: Optional[Path] = None
    latest_contents_mtime = 0.0
    latest_comments_mtime = 0.0

    for root, dirs, files in os.walk(DATA_DIR):
        root_path = Path(root)
        rel = str(root_path.relative_to(DATA_DIR))
        if platform.lower() not in rel.lower():
            continue

        for name in files:
            if not name.lower().endswith(".json"):
                continue
            path = root_path / name
            mtime = path.stat().st_mtime
            lower_name = name.lower()

            if "content" in lower_name or "contents" in lower_name:
                if mtime > latest_contents_mtime:
                    latest_contents_mtime = mtime
                    latest_contents = path
            if "comment" in lower_name or "comments" in lower_name:
                if mtime > latest_comments_mtime:
                    latest_comments_mtime = mtime
                    latest_comments = path

    return {"contents": latest_contents, "comments": latest_comments}


def _load_json_file(path: Optional[Path]) -> Any:
    if not path:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@router.post("/run-once")
async def run_crawler_once(request: CrawlerStartRequest):
    """
    同步执行一次抓取任务，并返回本次生成的最新 JSON 数据（内容 + 评论）。

    注意：
    - 内部会强制将 save_option 设为 json，方便直接读取文件。
    - 调用方应控制好频率，避免长时间阻塞。
    """
    # 强制保存为 JSON，其他参数沿用调用方传入
    req_dict = request.model_dump()
    req_dict["save_option"] = SaveDataOptionEnum.JSON
    effective_req = CrawlerStartRequest(**req_dict)

    ok = await crawler_manager.run_once(effective_req)
    if not ok:
        raise HTTPException(status_code=500, detail="Crawler execution failed or timed out")

    # 进程结束后，从 data 目录中找到该平台最新的 json 文件
    files = _find_latest_json_files(platform=effective_req.platform.value)
    contents_data = _load_json_file(files["contents"])
    comments_data = _load_json_file(files["comments"])

    return {
        "status": "ok",
        "platform": effective_req.platform.value,
        "crawler_type": effective_req.crawler_type.value,
        "files": {
            "contents": str(files["contents"].relative_to(DATA_DIR)) if files["contents"] else None,
            "comments": str(files["comments"].relative_to(DATA_DIR)) if files["comments"] else None,
        },
        "data": {
            "contents": contents_data,
            "comments": comments_data,
        },
    }
