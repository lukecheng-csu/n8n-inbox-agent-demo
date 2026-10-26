#!/usr/bin/env python3
"""
sanitize_workflow.py — n8n 工作流脱敏脚本

用途：把 n8n 原生导出的 JSON（含 credentials / pinData / 硬编码密钥）清成
      可安全公开到 GitHub 的版本，同时保留节点结构与连线不变。

用法：
    python3 sanitize_workflow.py inbox-agent.json clean.json
    python3 sanitize_workflow.py inbox-agent.json clean.json --aggressive
    python3 sanitize_workflow.py inbox-agent.json --report-only

做了什么：
  1. 删除根级 credentials
  2. 删除根级 pinData（会泄露真实历史数据）
  3. 删除每个节点内的 credentials（凭证 ID / 名称）
  4. 删除 / 覆写可能的实例信息（meta.instanceId、webhookId 等）
  5. 按 key 名启发式清理参数里的密钥：token / secret / key / password /
     authorization / apiKey / clientSecret ...
  6. 掩码邮箱地址、长十六进制串、JWT、Slack/Drive 文件 ID（--aggressive 时）
  7. 输出一份「改了什么」的清单到 stderr

退出码：0 成功，1 输入有问题
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# 规则
# ----------------------------------------------------------------------------

# 值需要被打码的 key 名（不区分大小写，做包含匹配）
SECRET_KEY_HINTS = (
    "token", "secret", "password", "passwd", "pwd", "apikey", "api_key",
    "authorization", "auth", "bearer", "privatekey", "private_key",
    "accesskey", "access_key", "clientsecret", "client_secret",
    "credential", "cookie", "session", "signature",
)

# 根级要删掉的字段
ROOT_DROP = ("credentials", "pinData")

# 节点级要删掉的字段
NODE_DROP = ("credentials",)

# 邮箱
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 长十六进制（32+）
HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")

# JWT
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")

# Google Drive / Docs 常见长 ID、Slack 文件 ID
DRIVE_ID_RE = re.compile(r"\b1[A-Za-z0-9_\-]{20,}\b")
SLACK_FILE_RE = re.compile(r"\bF[A-Z0-9]{8,}\b")

PLACEHOLDER = "<REDACTED>"


class Report:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def dump(self) -> None:
        print("\n=== 脱敏清单 ===", file=sys.stderr)
        if not self.items:
            print("  (未发现需要处理的内容)", file=sys.stderr)
        for line in self.items:
            print(f"  - {line}", file=sys.stderr)
        print("=== 共 %d 处 ===\n" % len(self.items), file=sys.stderr)


def looks_secret_key(key: str) -> bool:
    k = key.lower().replace("-", "_")
    return any(h in k for h in SECRET_KEY_HINTS)


def scrub_string(value: str, aggressive: bool) -> str:
    out = value
    if aggressive:
        out = JWT_RE.sub(PLACEHOLDER, out)
        out = EMAIL_RE.sub("<email>", out)
        out = HEX_RE.sub(PLACEHOLDER, out)
        out = DRIVE_ID_RE.sub("<drive-id>", out)
        out = SLACK_FILE_RE.sub("<slack-file-id>", out)
    return out


def walk(value, path: str, aggressive: bool, report: Report):
    """递归清理参数树，返回新值。"""
    if isinstance(value, dict):
        new = {}
        for k, v in value.items():
            if looks_secret_key(k) and isinstance(v, str) and v.strip():
                report.add(f"{path}.{k}  → 值已打码（长度 {len(v)}）")
                new[k] = PLACEHOLDER
            elif looks_secret_key(k) and isinstance(v, (dict, list)) and v:
                # 形如 "auth": {"token": "..."} 的嵌套
                new[k] = walk(v, f"{path}.{k}", aggressive, report)
            else:
                new[k] = walk(v, f"{path}.{k}", aggressive, report)
        return new
    if isinstance(value, list):
        return [walk(v, f"{path}[{i}]", aggressive, report) for i, v in enumerate(value)]
    if isinstance(value, str):
        cleaned = scrub_string(value, aggressive)
        if cleaned != value:
            report.add(f"{path}  → 内容打码")
        return cleaned
    return value


def sanitize(data: dict, aggressive: bool) -> tuple[dict, Report]:
    report = Report()

    # 1) 根级
    for key in ROOT_DROP:
        if key in data:
            report.add(f"根级字段 {key} 已移除")
            del data[key]

    # 2) meta 里的实例标识
    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in ("instanceId", "templateId", "templateCredsSetupCompleted"):
            if key in meta:
                report.add(f"meta.{key} 已移除")
                meta.pop(key, None)
        data["meta"] = meta

    # 3) 节点
    nodes = data.get("nodes", [])
    for idx, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        name = node.get("name", f"node#{idx}")
        for key in NODE_DROP:
            if key in node:
                report.add(f"节点「{name}」的 {key} 已移除")
                node.pop(key, None)
        if "webhookId" in node:
            report.add(f"节点「{name}」的 webhookId 已移除")
            node.pop("webhookId", None)
        # 4) 参数树
        if "parameters" in node:
            node["parameters"] = walk(
                node["parameters"], f'节点「{name}」.parameters', aggressive, report
            )

    return data, report


def main() -> int:
    ap = argparse.ArgumentParser(description="n8n 工作流脱敏")
    ap.add_argument("input", help="n8n 导出的原始 JSON")
    ap.add_argument("output", nargs="?", help="输出文件（不给则打印到 stdout）")
    ap.add_argument(
        "--aggressive",
        action="store_true",
        help="额外打码邮箱 / 长十六进制 / JWT / Drive·Slack ID",
    )
    ap.add_argument(
        "--report-only", action="store_true", help="只检查并报告，不写文件"
    )
    args = ap.parse_args()

    src = Path(args.input)
    if not src.is_file():
        print(f"错误：找不到输入文件 {src}", file=sys.stderr)
        return 1

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误：不是合法 JSON — {e}", file=sys.stderr)
        return 1

    if not isinstance(data, dict):
        print("错误：顶层不是对象，可能不是 n8n 工作流导出", file=sys.stderr)
        return 1

    clean, report = sanitize(data, args.aggressive)
    report.dump()

    if args.report_only:
        print("（--report-only，未写文件）", file=sys.stderr)
        return 0

    out_text = json.dumps(clean, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out_text, encoding="utf-8")
        print(f"已写入脱敏文件：{args.output}", file=sys.stderr)
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
