#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把构建产物上传为 CNB Release 附件（尽力而为，脚本源管理器版本的移植）。

与 scripts/upload_release_asset.ps1 的流程一致，适用于 Linux 流水线容器：

    1. GET  /{repo}/-/releases/tags/{tag}                 -> release_id
    2. POST /{repo}/-/releases/{id}/asset-upload-url      -> upload_url
    3. PUT  upload_url（流式上传文件内容）
    4. POST /{repo}/-/releases/{id}/asset-upload-confirmation/{token}/{path}

Release 不存在时跳过上传并以非零码退出（调用方可用 ``||`` 兜底），
不会抛出未捕获异常导致流水线失败。

用法：
    python scripts/upload_artifact.py --tag v1.0.0 --file xxx.zip

环境变量：
    CNB_TOKEN          流水线临时令牌（CI 中自动注入）
    CNB_API_ENDPOINT   CNB API 地址，默认 https://api.cnb.cool
    CNB_REPO_SLUG      当前仓库路径（如 star_fu/cad-translation-web）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ApiError(RuntimeError):
    pass


def request(
    method: str,
    url: str,
    token: str,
    *,
    body: dict | None = None,
    raw: bytes | None = None,
    auth: bool = True,
) -> dict:
    headers: dict = {}
    if auth:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.cnb.api+json"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if raw is not None:
        data = raw
        headers["Content-Type"] = "application/octet-stream"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:500]
        raise ApiError(f"HTTP {exc.code} on {method} {url}: {detail!r}") from exc
    text = payload.decode("utf-8", "replace").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def data_field(obj: object) -> dict:
    """兼容 {data: {...}} 与直接返回 {...} 两种响应结构。"""
    if isinstance(obj, dict):
        inner = obj.get("data")
        if isinstance(inner, dict):
            return inner
        return obj
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Release 对应的 tag 名")
    parser.add_argument("--file", required=True, help="待上传文件路径")
    parser.add_argument("--asset-name", default=None, help="附件名（默认取文件名）")
    parser.add_argument("--repo", default=os.environ.get("CNB_REPO_SLUG", ""))
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("CNB_API_ENDPOINT", "https://api.cnb.cool"),
    )
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--retry-interval", type=float, default=20.0)
    args = parser.parse_args()

    token = os.environ.get("CNB_TOKEN", "")
    file_path = Path(args.file)
    if not token:
        print("WARN: CNB_TOKEN not set; skip upload.")
        return 2
    if not file_path.is_file():
        print(f"ERROR: file not found: {file_path}")
        return 2
    if not args.repo:
        print("ERROR: repo slug missing (use --repo or set CNB_REPO_SLUG).")
        return 2

    endpoint = args.endpoint.rstrip("/")
    asset_name = args.asset_name or file_path.name
    size = file_path.stat().st_size

    # 1. 按 tag 查找 Release（带重试：tag_push 场景下 Release 可能正被并行创建）
    release: dict | None = None
    for attempt in range(1, args.retries + 1):
        try:
            resp = request(
                "GET",
                f"{endpoint}/{args.repo}/-/releases/tags/"
                f"{urllib.parse.quote(args.tag, safe='')}",
                token,
            )
            release = data_field(resp)
            if not (isinstance(release, dict) and release.get("id")):
                release = None
        except ApiError as exc:
            print(f"get release by tag failed (attempt {attempt}): {exc}")
            release = None
        if release:
            break
        if attempt < args.retries:
            time.sleep(args.retry_interval)

    if not release:
        print(f"WARN: Release for tag '{args.tag}' not found; upload skipped.")
        return 2

    release_id = release.get("id") or release.get("release_id")
    print(f"found release id={release_id}")

    # 2. 请求上传地址
    resp = request(
        "POST",
        f"{endpoint}/{args.repo}/-/releases/{release_id}/asset-upload-url",
        token,
        body={"asset_name": asset_name, "size": size, "overwrite": True},
    )
    up = data_field(resp)
    upload_url = (
        up.get("upload_url")
        or up.get("verify_url")
        or resp.get("upload_url")
        or resp.get("verify_url")
    )
    verify_url = up.get("verify_url") or resp.get("verify_url")
    if not upload_url:
        print("WARN: no upload_url returned; upload skipped.")
        return 2

    # 3. 上传文件（upload_url 是预签名地址，自带鉴权，不再附加 Authorization 头）
    print(f"uploading {asset_name} ({size} bytes) ...")
    request("PUT", upload_url, token, raw=file_path.read_bytes(), auth=False)
    print("upload PUT done.")

    # 4. 确认上传：verify_url 本身就是完整的确认地址（含 upload_token 与
    #    URL 编码后的 asset_path），直接 POST 即可，无需手动解析拼接。
    if verify_url:
        try:
            request("POST", verify_url, token, body={})
            print("upload confirmed.")
        except ApiError as exc:
            print(f"WARN: upload confirmation failed: {exc}")
    else:
        print("WARN: no verify_url returned; confirmation skipped.")

    print(f"DONE: asset '{asset_name}' attached to release '{args.tag}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
