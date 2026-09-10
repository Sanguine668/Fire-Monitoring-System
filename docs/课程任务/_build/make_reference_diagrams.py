"""生成统一参考材料所需的三张图：系统架构、数据流、告警状态机。"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
matplotlib.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "课程任务" / "项目参考材料" / "images"
OUT.mkdir(parents=True, exist_ok=True)

BLUE = "#1F4D78"
LIGHT = "#E8EEF5"
ACCENT = "#E5484D"
GREEN = "#2F855A"


def box(ax, x, y, w, h, text, fill=LIGHT, edge=BLUE, size=10, bold=False, color="#1F2937"):
    patch = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.04",
        linewidth=1.1, edgecolor=edge, facecolor=fill,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size,
            fontweight="bold" if bold else "normal", color=color, linespacing=1.5)


def arrow(ax, x1, y1, x2, y2, color=BLUE, style="-|>", lw=1.3, text=None, offset=(0.0, 0.02)):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=12,
                                 linewidth=lw, color=color, shrinkA=1, shrinkB=1))
    if text:
        ax.text((x1 + x2) / 2 + offset[0], (y1 + y2) / 2 + offset[1], text, ha="center",
                va="bottom", fontsize=8, color=color)


def architecture() -> None:
    fig, ax = plt.subplots(figsize=(10.6, 7.2), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    box(ax, 0.6, 9.0, 8.8, 0.8, "用户层：值班人员 · 系统管理员 · 项目评审/教师", fill="#F2F4F7", bold=True)
    box(ax, 0.6, 7.7, 8.8, 1.0,
        "展示层：Vue3 + Vite + Element Plus + ECharts\n"
        "监控总览 · 实时监控 · 告警中心 · 视频源管理 · 系统设置", fill=LIGHT, bold=True)
    box(ax, 0.6, 6.2, 8.8, 1.2,
        "服务层：FastAPI 单进程\n"
        "REST 接口 · WebSocket 事件推送 · MJPEG 实时画面 · 检测 worker · 告警规则引擎", fill=LIGHT, bold=True)
    box(ax, 0.6, 4.7, 4.1, 1.2, "智能体复核（规划）\n多尺度切片 + 时序融合\n+ 视觉语言模型复核", fill="#FDECEC", edge=ACCENT, bold=True)
    box(ax, 5.3, 4.7, 4.1, 1.2, "AI 检测层\nUltralytics YOLO26n（fire，自训练）\n远距离小目标训练（规划）", fill="#FFF6E5", edge="#B7791F", bold=True)
    box(ax, 0.6, 3.2, 8.8, 1.1, "视频接入层：手机 IP Webcam 推流 · 本地上传 MP4（循环） · RTSP 摄像头", fill=LIGHT, bold=True)
    box(ax, 0.6, 1.7, 8.8, 1.1, "数据存储：SQLite（cameras / alarms / settings）· 上传文件与截图目录", fill="#EDF7F0", edge=GREEN, bold=True)
    box(ax, 0.6, 0.3, 8.8, 1.0, "运行环境：Windows 笔记本（RTX 4050 6GB）· 局域网/手机热点 · 单机部署", fill="#F2F4F7", bold=True)

    arrow(ax, 5, 9.0, 5, 8.75)
    arrow(ax, 5, 7.7, 5, 7.45)
    arrow(ax, 5, 6.2, 5, 5.95)
    arrow(ax, 2.65, 4.7, 2.65, 4.35)
    arrow(ax, 7.35, 4.7, 7.35, 4.35)
    arrow(ax, 5, 3.2, 5, 2.85)
    arrow(ax, 5, 1.7, 5, 1.35)

    ax.text(0.6, 9.95, "火情智能监测与预警系统 · 总体架构", fontsize=14, fontweight="bold", color=BLUE)
    fig.tight_layout()
    fig.savefig(OUT / "architecture.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def dataflow() -> None:
    fig, ax = plt.subplots(figsize=(11.2, 4.6), dpi=200)
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 5)
    ax.axis("off")
    labels = [
        "手机推流 /\n上传视频 /\nRTSP 摄像头",
        "OpenCV 取帧\n（3~5 FPS）",
        "YOLO26n\n烟火检测",
        "告警规则引擎\n连续帧+阈值+冷却\n（智能体复核规划）",
        "SQLite 落库\n+ WebSocket 推送",
        "前端展示\n检测框画面 + 告警弹窗",
    ]
    fills = [LIGHT, LIGHT, "#FFF6E5", "#FDECEC", "#EDF7F0", LIGHT]
    edges = [BLUE, BLUE, "#B7791F", ACCENT, GREEN, BLUE]
    w, h, gap = 1.62, 1.5, 0.32
    x = 0.35
    for idx, (text, fill, edge) in enumerate(zip(labels, fills, edges)):
        box(ax, x, 2.1, w, h, text, fill=fill, edge=edge, size=9)
        if idx < len(labels) - 1:
            arrow(ax, x + w, 2.85, x + w + gap, 2.85)
        x += w + gap
    ax.text(0.35, 4.3, "系统数据流：视频源 → 检测 → 告警判定 → 存储与推送 → 前端展示",
            fontsize=13, fontweight="bold", color=BLUE)
    ax.text(0.35, 1.2, "支路：标注帧缓存 → MJPEG 实时流；告警记录 → 历史查询与统计图表",
            fontsize=9, color="#4B5563")
    fig.tight_layout()
    fig.savefig(OUT / "dataflow.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def alarm_state() -> None:
    fig, ax = plt.subplots(figsize=(10.4, 5.8), dpi=200)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 6.0)
    ax.axis("off")
    box(ax, 0.3, 3.9, 2.3, 1.0, "正常状态\nnormal", fill="#EDF7F0", edge=GREEN, bold=True)
    box(ax, 3.4, 3.9, 2.9, 1.0, "疑似烟雾\nsmoke_streak 计数中", fill="#FFF6E5", edge="#B7791F", bold=True)
    box(ax, 7.1, 3.9, 2.6, 1.0, "黄色预警\nwarning", fill="#FFF6E5", edge="#B7791F", bold=True)
    box(ax, 3.4, 1.1, 2.9, 1.0, "红色火灾告警\ncritical", fill="#FDECEC", edge=ACCENT, bold=True)

    # smoke 链路：正常 → 疑似（计数） → 连续 N 帧 → 黄色预警
    arrow(ax, 2.6, 4.4, 3.4, 4.4, text="检出 smoke ≥ 阈值", offset=(0, 0.06), lw=1.4)
    ax.add_patch(
        FancyArrowPatch((4.8, 4.9), (5.9, 4.9), connectionstyle="arc3,rad=-1.1",
                        arrowstyle="-|>", mutation_scale=12, linewidth=1.3, color="#B7791F")
    )
    ax.text(5.35, 5.62, "连续检出 smoke：streak + 1", ha="center", fontsize=8.5, color="#B7791F")
    arrow(ax, 6.3, 4.4, 7.1, 4.4, text="streak ≥ 连续帧 N", offset=(0, 0.06), color="#B7791F", lw=1.4)

    # fire 链路：任意状态检出 fire 直接进入 critical
    arrow(ax, 1.5, 3.9, 4.0, 2.1, color=ACCENT, lw=1.5)
    arrow(ax, 4.8, 3.9, 4.8, 2.1, color=ACCENT, lw=1.5)
    arrow(ax, 8.4, 3.9, 5.6, 2.1, color=ACCENT, lw=1.5)
    ax.text(6.25, 2.75, "任意状态检出 fire ≥ 阈值\n→ 立即生成红色告警", ha="center", fontsize=9,
            color=ACCENT, fontweight="bold", linespacing=1.5)

    # 复位链路
    ax.add_patch(
        FancyArrowPatch((3.9, 3.9), (1.9, 4.9), connectionstyle="arc3,rad=0.35",
                        arrowstyle="-|>", mutation_scale=12, linewidth=1.1, color=GREEN, linestyle="--")
    )
    ax.add_patch(
        FancyArrowPatch((7.6, 3.9), (2.4, 4.9), connectionstyle="arc3,rad=-0.25",
                        arrowstyle="-|>", mutation_scale=12, linewidth=1.1, color=GREEN, linestyle="--")
    )
    ax.text(4.9, 3.45, "当前帧无有效烟火目标：streak 清零，状态回到 normal", ha="center",
            fontsize=8.5, color=GREEN)

    box(ax, 0.3, 0.25, 4.5, 0.75,
        "冷却规则：距上次落库不足 8 秒时，仅更新状态与风险分，不重复写库",
        fill="#F2F4F7", edge=BLUE, size=8.5)
    box(ax, 5.2, 0.25, 4.5, 0.75,
        "视频源离线：状态机复位（streak=0、status=normal），避免重连误报",
        fill="#F2F4F7", edge=BLUE, size=8.5)
    ax.text(0.3, 5.55, "告警判定状态机（每路视频源独立）", fontsize=13, fontweight="bold", color=BLUE)
    fig.tight_layout()
    fig.savefig(OUT / "alarm_state.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    dataflow()
    alarm_state()
    print(OUT)
