#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Repo2Kindle
===========
把任意 GitHub 仓库里"按日期命名子目录发布"的文件（epub/mobi/pdf/...），
自动挑最新一期下载并通过邮件发送到 Kindle（或任何邮箱）。

用法：
    python repo2kindle.py                 # 正常运行，发现新内容就发送
    python repo2kindle.py --dry-run       # 只打印会发送什么，不真正发邮件
    python repo2kindle.py --config other.yaml

配置在 config.yaml 里描述"监控哪些仓库/哪些路径"，加新的订阅源不需要改代码，
详见 config.yaml 里的注释和 README.md。

环境变量（建议放在 GitHub Actions secrets 里，不要写进代码/配置文件）：
    KINDLE_EMAIL   默认收件邮箱（单个 source 可以在 config.yaml 里用
                   recipient 字段覆盖）
    SMTP_HOST      发件邮箱 SMTP 服务器，如 smtp.gmail.com / smtp.qq.com
    SMTP_PORT      587 (STARTTLS) 或 465 (SSL)
    SMTP_USER      发件邮箱地址（需已加入 Kindle "已认可发件人列表"）
    SMTP_PASS      应用专用密码 / 授权码（不是登录密码）
    GITHUB_TOKEN   可选，GitHub Actions 会自动注入，用于提高 API 限额
    SOURCES        可选，逗号分隔，只处理 config.yaml 里指定 name 的 source
                   例如 "economist,new_yorker"
"""

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import requests
import yaml

BASE_DIR = Path(__file__).parent
DEFAULT_CONFIG = BASE_DIR / "config.yaml"
DEFAULT_STATE_FILE = BASE_DIR / "state.json"

MIME_MAP = {
    "epub": ("application", "epub+zip"),
    "mobi": ("application", "x-mobipocket-ebook"),
    "azw3": ("application", "x-mobi8-ebook"),
    "pdf": ("application", "pdf"),
    "txt": ("text", "plain"),
}

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


# --------------------------------------------------------------------------
# GitHub API 相关
# --------------------------------------------------------------------------

def gh_get(url: str):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def find_latest_dir(repo: str, path: str, pattern: str):
    """在 repo/path 下找到目录名匹配 pattern、日期最新的一个，返回目录名。"""
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    items = gh_get(url)
    candidates = []
    for item in items:
        if item["type"] != "dir":
            continue
        m = re.match(pattern, item["name"])
        if not m:
            continue
        candidates.append((m.groups(), item["name"]))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def find_attachment(repo: str, path: str, issue_dir: str, format_priority: list):
    """在期号目录里按优先级找文件，返回 (文件名, 下载链接)。"""
    url = f"https://api.github.com/repos/{repo}/contents/{path}/{issue_dir}"
    items = gh_get(url)
    files = {f["name"]: f for f in items if f["type"] == "file"}
    for ext in format_priority:
        for name, meta in files.items():
            if name.lower().endswith(f".{ext}"):
                return name, meta["download_url"]
    return None, None


def download(url: str) -> bytes:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


# --------------------------------------------------------------------------
# 邮件发送
# --------------------------------------------------------------------------

def send_mail(recipient: str, subject: str, filename: str, content: bytes) -> None:
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg.set_content("已通过 Repo2Kindle 自动发送，请查收附件。")

    ext = filename.rsplit(".", 1)[-1].lower()
    maintype, subtype = MIME_MAP.get(ext, ("application", "octet-stream"))
    msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context()) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)


# --------------------------------------------------------------------------
# 配置 / 状态
# --------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# 主逻辑
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Repo2Kindle")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--state", default=str(DEFAULT_STATE_FILE), help="状态文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打印会发送什么，不真正发邮件/不写状态")
    args = parser.parse_args()

    config_path = Path(args.config)
    state_path = Path(args.state)

    config = load_config(config_path)
    default_formats = config.get("defaults", {}).get("format_priority", ["epub", "mobi", "pdf"])
    sources = config.get("sources", [])

    only = os.environ.get("SOURCES")
    only_names = set(n.strip() for n in only.split(",")) if only else None

    global_recipient = os.environ.get("KINDLE_EMAIL")

    state = load_state(state_path)
    updated = False
    had_error = False

    for source in sources:
        name = source["name"]
        if only_names and name not in only_names:
            continue

        label = source.get("label", name)
        repo = source["repo"]
        path = source["path"]
        pattern = source["pattern"]
        format_priority = source.get("format_priority", default_formats)
        recipient = source.get("recipient") or global_recipient

        if not recipient:
            print(f"[跳过] {label}：既没有 source.recipient 也没有 KINDLE_EMAIL 环境变量")
            continue

        try:
            latest = find_latest_dir(repo, path, pattern)
        except Exception as e:
            print(f"[错误] {label} 获取目录失败: {e}")
            had_error = True
            continue

        if latest is None:
            print(f"[跳过] {label}：{repo}/{path} 下未找到匹配 pattern 的目录")
            continue

        if state.get(name) == latest:
            print(f"[无更新] {label}：最新一期仍是 {latest}，已发送过，跳过")
            continue

        try:
            filename, url = find_attachment(repo, path, latest, format_priority)
            if not url:
                print(f"[跳过] {label}/{latest} 未找到匹配格式 {format_priority} 的文件")
                continue

            if args.dry_run:
                print(f"[dry-run] 会发送 {label} {latest} -> {filename} 到 {recipient}")
                continue

            print(f"[发送中] {label} {latest} -> {filename} -> {recipient}")
            content = download(url)
            send_mail(recipient, f"{label} {latest}", filename, content)
            print(f"[已发送] {label} {latest}")

            state[name] = latest
            updated = True
            time.sleep(2)  # 避免连续发信触发邮箱服务商的限速/风控
        except Exception as e:
            print(f"[错误] 处理 {label}/{latest} 时失败: {e}")
            had_error = True

    if args.dry_run:
        print("dry-run 结束，未修改状态文件")
    elif updated:
        save_state(state_path, state)
        print(f"状态文件 {state_path} 已更新")
    else:
        print("本次运行没有新一期需要发送")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
