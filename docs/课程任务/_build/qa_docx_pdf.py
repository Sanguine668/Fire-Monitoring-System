"""对 Word 转出的 PDF 做逐页结构检查（页数、每页字数、有没有异常空白页）。

转换由 PowerShell 调 Word COM 完成，见 build_exp56_docx.py 的说明。
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/课程任务/_qa"


def inspect(pdf: Path) -> None:
    with pymupdf.open(str(pdf)) as doc:
        print(f"--- {pdf.name} ---")
        print(f"  页数: {doc.page_count}")
        thin = []
        overflow = []
        for idx, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            chars = len(text.replace("\n", ""))
            first = text.splitlines()[0][:40] if text else "(空页)"
            if chars < 60:
                thin.append((idx, chars, first))
            rect = page.rect
            # A4 + 上下 2.54cm、左 3.0cm、右 2.6cm 的正文区（单位 pt，1cm=28.3465pt）
            left, right = 85.0, rect.width - 73.7
            top, bottom = 60.0, rect.height - 40.0   # 页脚允许范围放宽
            for block in page.get_text("blocks"):
                x0, y0, x1, y1 = block[:4]
                if x0 < left - 2 or x1 > right + 2 or y0 < top - 2 or y1 > bottom + 2:
                    snippet = str(block[4]).strip().replace("\n", " ")[:30]
                    overflow.append((idx, round(x0), round(y0), round(x1), round(y1), snippet))
            print(f"  第 {idx:>2} 页: {chars:>5} 字 | {first}")
        if thin:
            print("  !! 内容偏少的页:", thin)
        else:
            print("  未发现内容异常偏少的页面")
        if overflow:
            print(f"  !! 越界文本块 {len(overflow)} 处（前 8 条）:")
            for item in overflow[:8]:
                print("     ", item)
        else:
            print("  未发现超出页边距的文本块")


def main() -> None:
    pdfs = sorted(OUT.glob("*.pdf"))
    if not pdfs:
        print(f"没有找到 PDF，请先转换到 {OUT}")
        return
    for pdf in pdfs:
        inspect(pdf)


if __name__ == "__main__":
    main()
