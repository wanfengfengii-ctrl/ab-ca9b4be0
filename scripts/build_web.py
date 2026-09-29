#!/usr/bin/env python3
"""零依赖前端构建：校验后把 CSS/JS 内联为单文件 dist/index.html。

用法：python scripts/build_web.py
存在 node 时额外用 `node --check` 做 JS 语法校验。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def read_asset(rel: str) -> pathlib.Path:
    asset = (WEB / rel).resolve()
    if not str(asset).startswith(str(WEB.resolve())):
        raise SystemExit(f"拒绝内联 web 目录之外的资源: {rel}")
    if not asset.exists():
        raise SystemExit(f"缺失前端资源: {rel}")
    return asset


def check_js(asset: pathlib.Path) -> None:
    if shutil.which("node") is None:
        print("  (未检测到 node，跳过 JS 语法校验)", file=sys.stderr)
        return
    r = subprocess.run(["node", "--check", str(asset)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"JS 语法校验失败:\n{r.stderr}")


def main() -> int:
    html = (WEB / "index.html").read_text(encoding="utf-8")

    def sub_css(m: re.Match) -> str:
        content = read_asset(m.group(1)).read_text(encoding="utf-8")
        return f"<style>\n{content}\n</style>"

    def sub_js(m: re.Match) -> str:
        asset = read_asset(m.group(1))
        check_js(asset)
        return f"<script>\n{asset.read_text(encoding='utf-8')}\n</script>"

    html = re.sub(r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*/?>',
                  sub_css, html)
    html = re.sub(r'<script\s+src="([^"]+)"\s*></script>', sub_js, html)

    out_dir = WEB / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(html, encoding="utf-8")

    if ('src="' in html and 'src="src/' in html) \
            or 'href="src/' in html:
        raise SystemExit("构建产物仍引用外部 src 资源，内联失败")
    print(f"前端构建完成：{out.relative_to(ROOT)}（{len(html)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
