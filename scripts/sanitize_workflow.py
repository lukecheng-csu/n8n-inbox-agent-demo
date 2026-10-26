#!/usr/bin/env python3
"""
sanitize_workflow.py — n8n 工作流脱敏

用途：把 n8n 原生导出的 JSON（含 credentials / pinData / 硬编码密钥）清成
      可安全公开到 GitHub 的版本，同时保留节点结构与配置不变。

用法：
    python3 sanitize_workflow.py inbox-agent.json clean.json
    python3 sanitize_workflow.py inbox-agent.json clean.json --aggressive
    python3 sanitize_workflow.py inbox-agent.json --report-only

做了什么：
  1. 删除根级 / 节点级 credentials（凭证 ID 与名称）
  2. 删除 pinData（会泄露真实历史数据）
  3. 删除 webhookId、meta.instanceId
  4. 按 key 名清理**密钥类**参数（token / secret / password / apikey ...）
  5. 识别明显的密钥字符串（Bearer xxx、xoxb-、sk-）
  6. --aggressive 时额外掩码邮箱、长十六进制串、JWT、Drive/Slack 文件 ID

重要：以下字段是**配置**而不是密钥，永远不脱敏，否则导入后节点会坏：
    authentication / genericAuthType / nodeCredentialType / jsCode / code

退出码：0 成功，1 输入有问题（含「误伤配置」自检失败）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 值需要打码的 key 名（不区分大小写，包含匹配）——仅限真正的凭证
SECRET_KEY_HINTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "pwd",
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "privatekey",
    "private_key",
    "accesskey",
    "access_key",
    "clientsecret",
    "client_secret",
    "cookie",
    "signature",
)

# 这些 key 是节点配置，不是密钥——即使名字里含 auth/credential 也不能动
SAFE_KEYS = {
    "authentication",
    "genericauthtype",
    "nodecredentialtype",
    "jscode",
    "code",
    "sourceproperty",
    "destinationkey",
    "query",
    "url",
    "path",
    "name",
    "description",
}

# 这些 key 的内容不做任何替换（代码里出现邮箱、ID 都是正常的）
NO_CONTENT_SCRUB = {"jscode", "code", "query"}

ROOT_DROP = ("credentials", "pinData")
NODE_DROP = ("credentials",)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")
DRIVE_ID_RE = re.compile(r"\b1[A-Za-z0-9_\-]{25,}\b")
SLACK_FILE_RE = re.compile(r"\bF[A-Z0-9]{8,}\b")

# 明显的密钥字符串：无论 --aggressive 与否都要处理
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._\-]{10,}|xox[bap]-[A-Za-z0-9\-]{10,}|sk-[A-Za-z0-9]{16,})"
)

PLACEHOLDER = "<REDACTED>"
EMAIL_PLACEHOLDER = "<email>"
ID_PLACEHOLDER = "<id>"


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


def _norm(key: str) -> str:
    return key.lower().replace("-", "").replace("_", "")


SAFE_NORMALIZED = {_norm(k) for k in SAFE_KEYS}


def is_safe(key: str) -> bool:
    return _norm(key) in SAFE_NORMALIZED


def is_secret(key: str) -> bool:
    if is_safe(key):
        return False
    k = key.lower().replace("-", "_")
    return any(h in k for h in SECRET_KEY_HINTS)


def scrub_string(value: str, aggressive: bool, allow_content_scrub: bool) -> str:
    if not allow_content_scrub:
        return value

    out = SECRET_VALUE_RE.sub(PLACEHOLDER, value)
    if not aggressive:
        return out

    out = JWT_RE.sub(PLACEHOLDER, out)
    out = EMAIL_RE.sub(EMAIL_PLACEHOLDER, out)
    out = HEX_RE.sub(PLACEHOLDER, out)
    out = DRIVE_ID_RE.sub(ID_PLACEHOLDER, out)
    out = SLACK_FILE_RE.sub(ID_PLACEHOLDER, out)
    return out


def walk(value, path: str, aggressive: bool, report: Report):
    if isinstance(value, dict):
        new = {}
        for k, v in value.items():
            if is_secret(k) and isinstance(v, str) and v.strip():
                report.add(f"{path}.{k}  → 打码（长度 {len(v)}）")
                new[k] = PLACEHOLDER
            elif is_secret(k) and isinstance(v, (dict, list)) and v:
                new[k] = walk(v, f"{path}.{k}", aggressive, report)
            else:
                new[k] = walk(v, f"{path}.{k}", aggressive, report)
        return new
    if isinstance(value, list):
        return [walk(v, f"{path}[{i}]", aggressive, report) for i, v in enumerate(value)]
    if isinstance(value, str):
        leaf = path.rsplit(".", 1)[-1].split("[")[0]
        allow = _norm(leaf) not in {_norm(k) for k in NO_CONTENT_SCRUB}
        cleaned = scrub_string(value, aggressive, allow)
        if cleaned != value:
            report.add(f"{path}  → 内容掩码")
        return cleaned
    return value


def sanitize(data: dict, aggressive: bool) -> tuple[dict, Report]:
    report = Report()

    for key in ROOT_DROP:
        if key in data:
            report.add(f"根级字段 {key} 已移除")
            del data[key]

    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in ("instanceId", "templateId"):
            if key in meta:
                report.add(f"meta.{key} 已移除")
                meta.pop(key, None)
        data["meta"] = meta

    for idx, node in enumerate(data.get("nodes", [])):
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
        if "parameters" in node:
            node["parameters"] = walk(
                node["parameters"], f'节点「{name}」.parameters', aggressive, report
            )

    return data, report


def self_check(clean: dict) -> bool:
    """确认没有把节点配置误当成密钥。"""
    ok = True
    for node in clean.get("nodes", []):
        params = node.get("parameters", {})
        for key in ("authentication", "genericAuthType", "nodeCredentialType"):
            if params.get(key) == PLACEHOLDER:
                print(
                    f"错误：节点「{node.get('name')}」的 {key} 被误判为密钥，导入后会坏",
                    file=sys.stderr,
                )
                ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="n8n 工作流脱敏")
    ap.add_argument("input", help="n8n 导出的原始 JSON")
    ap.add_argument("output", nargs="?", help="输出文件（不给则打印到 stdout）")
    ap.add_argument(
        "--aggressive",
        action="store_true",
        help="额外掩码邮箱 / 长十六进制 / JWT / Drive·Slack 文件 ID",
    )
    ap.add_argument("--report-only", action="store_true", help="只检查并报告，不写文件")
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

    if not self_check(clean):
        return 1

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
