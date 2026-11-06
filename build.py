#!/usr/bin/env python3
"""把 src/pages 里的正文套上统一的页头、步骤导航和页脚，生成到 site/。

只用 Python 标准库，不需要安装任何东西：

    python3 build.py

生成的 site/ 目录直接就是网站，Cloudflare Pages 的输出目录填 site 即可。
"""
from pathlib import Path
import html
import shutil

ROOT = Path(__file__).parent
SRC = ROOT / "src" / "pages"
OUT = ROOT / "site"
REPO = "https://github.com/heranhe/hello-microduck"

# 飞特方案的五个步骤，顺序就是教程顺序
FEETECH = [
    ("materials", "准备材料和打印"),
    ("servo-id", "给舵机设 ID"),
    ("boards", "主板、HAT 和接线"),
    ("system", "写入系统、通电"),
    ("calibrate", "用调试工具标定"),
]

# (输出路径, 源文件, 页面标题, 所属步骤编号；0 表示不在步骤里)
PAGES = [
    ("index.html", "index.html", "hello-microduck", 0),
    ("feetech/index.html", "feetech/index.html", "飞特 HD-1910 方案", 0),
    *[
        (f"feetech/{slug}.html", f"feetech/{slug}.html", f"第 {i} 步：{name}", i)
        for i, (slug, name) in enumerate(FEETECH, 1)
    ],
    ("xl330/index.html", "xl330/index.html", "官方 XL330 方案", 0),
]


def rel(depth: int) -> str:
    """从当前页面回到网站根目录的相对路径。"""
    return "../" * depth


def step_nav(step: int, up: str) -> str:
    items = []
    for i, (slug, name) in enumerate(FEETECH, 1):
        cls = "now" if i == step else ("done" if i < step else "")
        cur = ' aria-current="step"' if i == step else ""
        items.append(
            f'<li class="{cls}"><a href="{up}feetech/{slug}.html"{cur}><b>{i}</b><span>{html.escape(name)}</span></a></li>'
        )
    return f'<nav class="steps" aria-label="飞特方案的步骤"><ol>{"".join(items)}</ol></nav>'


def pager(step: int, up: str) -> str:
    prev = (
        f'<a class="btn" href="{up}feetech/{FEETECH[step - 2][0]}.html">← 上一步：{FEETECH[step - 2][1]}</a>'
        if step > 1
        else f'<a class="btn" href="{up}feetech/">← 方案总览</a>'
    )
    nxt = (
        f'<a class="btn main" href="{up}feetech/{FEETECH[step][0]}.html">下一步：{FEETECH[step][1]} →</a>'
        if step < len(FEETECH)
        else f'<a class="btn main" href="{up}tool/">打开调试工具 →</a>'
    )
    return f'<div class="pager">{prev}{nxt}</div>'


def page(title: str, body: str, step: int, depth: int) -> str:
    up = rel(depth)
    full_title = "hello-microduck" if title == "hello-microduck" else f"{title} · hello-microduck"
    eyebrow = (
        f'<p class="eyebrow">飞特 HD-1910 · 第 {step} 步，共 {len(FEETECH)} 步</p>' if step else ""
    )
    layout = (
        f'<div class="with-steps">{step_nav(step, up)}<main class="content">{eyebrow}{body}{pager(step, up)}</main></div>'
        if step
        else f'<main class="content wide">{body}</main>'
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{html.escape(full_title)}</title>
<meta name="description" content="手把手做一只 MicroDuck：材料、接线、写系统、标定，一步一步来。非官方教程。">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Noto+Sans+SC:wght@400;500;700;900&display=swap">
<link rel="stylesheet" href="{up}assets/style.css">
</head>
<body>
<header class="top">
  <a class="brand" href="{up}">hello-microduck</a>
  <nav class="topnav" aria-label="网站导航">
    <a href="{up}feetech/">飞特方案</a>
    <a href="{up}xl330/">XL330 方案</a>
    <a href="{up}tool/">调试工具</a>
    <a href="{REPO}" target="_blank" rel="noopener">GitHub ↗</a>
  </nav>
</header>
{layout}
<footer class="foot">
  <p><b>非官方教程。</b>与 MicroDuck 官方团队 Pollen Robotics 无关，没有得到官方授权或认可。MicroDuck 是 Pollen Robotics 的开源项目。</p>
  <p>照片和接线图来自作者的实际装配。<a href="{REPO}" target="_blank" rel="noopener">在 GitHub 上查看或修改这个教程 ↗</a></p>
</footer>
</body>
</html>
"""


def main() -> None:
    for out, src, title, step in PAGES:
        body = (SRC / src).read_text(encoding="utf-8")
        dest = OUT / out
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(title, body, step, out.count("/")), encoding="utf-8")
        print("生成", dest.relative_to(ROOT))
    # 调试工具是一个独立的单文件页面，补上文档声明后原样放进去
    tool = (ROOT / "tool" / "calibration.html").read_text(encoding="utf-8")
    (OUT / "tool").mkdir(parents=True, exist_ok=True)
    (OUT / "tool" / "index.html").write_text('<!doctype html>\n<html lang="zh-CN">\n' + tool, encoding="utf-8")
    print("生成 site/tool/index.html")
    shutil.copy(ROOT / "src" / "style.css", OUT / "assets" / "style.css")
    print("生成 site/assets/style.css")


if __name__ == "__main__":
    main()
