"""生成"增量式模型"示意图（用于进度管理计划的 2.1 节）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/课程任务/实验5-软件项目进度管理/images"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False

STAGES = ["需求分析", "设计", "实现", "测试"]
INCREMENTS = [
    ("增量 1", "核心闭环：视频源接入 / 检测 / 告警 / 前端展示", "#1F4D78"),
    ("增量 2", "数据与模型：数据治理 / 重训 / 对比评测", "#2E7D6F"),
    ("增量 3", "智能体与远距离：切片推理 / 视觉复核 / 远景评估", "#8A5A1F"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.6, 4.6), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    row_h, gap = 1.05, 0.42
    for r, (name, desc, color) in enumerate(INCREMENTS):
        y = 4.9 - r * (row_h + gap)
        ax.add_patch(
            FancyBboxPatch((0.35, y), 1.7, row_h, boxstyle="round,pad=0.06",
                           linewidth=0, facecolor=color, alpha=0.92)
        )
        ax.text(1.2, y + row_h / 2 + 0.12, name, ha="center", va="center",
                color="white", fontsize=11, fontweight="bold")
        ax.text(1.2, y + row_h / 2 - 0.24, "已交付版本", ha="center", va="center",
                color="white", fontsize=7.5)

        for c, stage in enumerate(STAGES):
            x = 2.35 + c * 1.62
            ax.add_patch(
                FancyBboxPatch((x, y), 1.45, row_h, boxstyle="round,pad=0.05",
                               linewidth=1.1, edgecolor=color, facecolor="white")
            )
            ax.text(x + 0.72, y + row_h / 2, stage, ha="center", va="center",
                    fontsize=9.5, color="#222222")

        ax.text(9.35, y + row_h / 2, "累积", ha="center", va="center",
                fontsize=9, color=color, rotation=90)
        if r < len(INCREMENTS) - 1:
            ax.add_patch(
                FancyArrowPatch((9.05, y - 0.08), (9.05, y - gap + 0.08),
                                arrowstyle="-|>", mutation_scale=14,
                                linewidth=1.2, color="#9AA2B0")
            )

    ax.text(0.35, 5.75, "增量式（Incremental）开发模型：每个增量都走一遍完整流程，交付一个可运行的版本",
            fontsize=10.5, color="#1F4D78", fontweight="bold")
    for r, (_n, desc, color) in enumerate(INCREMENTS):
        y = 4.9 - r * (row_h + gap)
        ax.text(0.35, y - 0.3, f"　{desc}", fontsize=8.5, color=color)

    ax.add_patch(
        FancyBboxPatch((0.35, 0.28), 9.3, 0.62, boxstyle="round,pad=0.08",
                       linewidth=0, facecolor="#F2F5F9")
    )
    ax.text(5.0, 0.59, "每个增量结束都产出可运行、可演示的版本；后续增量在已有版本上扩充，不推倒重来",
            ha="center", va="center", fontsize=9.5, color="#374151")

    fig.tight_layout()
    path = OUT / "increment_model.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"OK  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
