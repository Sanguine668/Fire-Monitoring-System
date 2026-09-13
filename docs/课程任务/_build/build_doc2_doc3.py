"""严格按课程参考文档格式生成：任务2 项目章程、任务3 非功能性需求部分。"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

sys.path.append(str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    BODY_SIZE,
    HEAD_CJK,
    add_page_number_footer,
    add_table,
    caption,
    configure_styles,
    set_run_font,
)

ROOT = Path(__file__).resolve().parents[3]
OUT_CHARTER = ROOT / "docs" / "课程任务" / "任务2-项目章程"
OUT_NFR = ROOT / "docs" / "课程任务" / "任务3-需求规格说明书"


def line(doc: Document, text: str, bold: bool = False, size=None):
    para = doc.add_paragraph()
    para.paragraph_format.first_line_indent = Pt(0)
    run = para.add_run(text)
    set_run_font(run, size=size or BODY_SIZE, bold=bold)
    return para


def numbered(doc: Document, items: list[str]) -> None:
    for idx, item in enumerate(items, start=1):
        line(doc, f"{idx}. {item}")


def build_charter() -> None:
    OUT_CHARTER.mkdir(parents=True, exist_ok=True)
    doc = Document()
    configure_styles(doc)
    add_page_number_footer(doc)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = title.add_run("项目章程")
    set_run_font(run, cjk=HEAD_CJK, size=Pt(18), bold=True)

    line(doc, "项目名称：火情智能监测与预警系统（FireGuard AI）")
    line(doc, "启动时间：2026 年 9 月 3 日")
    line(doc, "计划完工日期：2026 年 11 月 5 日")
    line(doc, "项目经理：蔡俊杰")
    line(doc, "联系方法：电话：19115973126　邮箱：alpaca10086@163.com")
    doc.add_paragraph()

    line(doc, "项目目标：在 8 周内交付一套可运行、可演示的视频火情监测与预警系统，实现\"视频源 → 烟火检测 → 分级预警 → 前端展示 → 历史留存\"的完整闭环；"
              "支持安卓手机摄像头在局域网/手机热点环境实时推流识别，并支持本地上传视频作为保底演示通道；"
              "完成自训练 YOLO 模型的训练、评测与公开模型对比；按老师新增要求实现智能体复核（降低误报）与远距离识别（远景小目标）能力；"
              "同时交付软件介绍、项目章程、需求规格说明书、工作任务分解说明书四项课程文档，做到过程可追溯、个人工作量可核查。")
    doc.add_paragraph()

    line(doc, "方法：", bold=True)
    numbered(doc, [
        "采用增量迭代方式开发，每周实训产出可演示版本，核心闭环优先，后置功能按进度取舍。",
        "每周固定站会并使用看板跟踪任务；会议纪要、评审意见与文档版本同步归档。",
        "使用 Git 分支 + Pull Request 协作，提交信息注明任务与作者；数据集与模型权重不进入仓库。",
        "文档按\"起草 v0.1 → 评审 v0.5 → 定稿 v1.0\"流程编写；模型与系统指标用真实测试数据支撑，演示采用手机推流 + 上传视频双通道并提前预演。",
    ])
    doc.add_paragraph()

    line(doc, "角色与职责：", bold=True)
    add_table(
        doc,
        ["姓名", "角色", "职责"],
        [
            ["蔡俊杰", "项目经理 / 技术负责人", "负责项目整体规划、进度控制与风险管理；主持需求评审与技术决策；负责系统架构与技术选型；负责 AI 模型训练、评测与优化；负责后端检测链路（视频源接入、检测任务、告警引擎、接口）开发与系统集成；负责演示总控与对外汇报。"],
            ["李汶航", "前端负责人 / 产品与界面", "负责系统前端整体设计与实现（监控总览、实时监控、告警中心、视频源管理、系统设置）；负责前后端接口联调与页面交互、视觉一致性；负责用户操作流程设计与界面原型；参与界面与非功能需求分析，承担演示现场操作。"],
            ["欧阳宇康", "需求与质量负责人", "负责需求获取、需求分析与需求文档维护；负责测试计划、测试用例设计、测试执行与缺陷跟踪；负责系统功能验证与验收、质量记录与评审组织；负责数据集与训练数据质量把关（含 smoke 类与远距离数据的收集核对）。"],
            ["陈泽恩", "配置管理与文档负责人", "负责项目配置管理与版本控制（Git 分支、提交规范、发布包）；负责文档模板、格式统一、版本归档与提交；负责项目管理工具（Microsoft Project）建库、进度计划与甘特图维护；负责环境配置记录、演示素材与数据归档。"],
        ],
        [2.0, 3.8, 9.6],
        center_body=False,
        font_size=Pt(9),
    )
    line(doc, "全员共同职责：参加每周例会与进度汇报，参与需求、设计、测试等评审，按规范提交过程材料，保证个人工作可追溯。")
    doc.add_paragraph()

    line(doc, "签名：", bold=True)
    for name in ["蔡俊杰（组长）", "李汶航", "欧阳宇康", "陈泽恩", "指导教师"]:
        line(doc, f"{name}：________________　　日期：____________")
    doc.add_paragraph()

    line(doc, "评述：", bold=True)
    numbered(doc, [
        "指导教师评述：待评阅后填写。",
        "项目组评述：项目已完成核心闭环并打通前后端，当前风险集中在数据集质量与远距离识别能力，已安排数据治理与数据补充计划；演示采用手机热点与上传视频双通道保障。",
    ])

    doc.save(OUT_CHARTER / "02_项目章程_火情智能监测与预警系统.docx")


def build_nfr() -> None:
    OUT_NFR.mkdir(parents=True, exist_ok=True)
    doc = Document()
    configure_styles(doc)
    add_page_number_footer(doc)

    title = doc.add_paragraph()
    run = title.add_run("软件需求规格说明书（非功能性需求部分）")
    set_run_font(run, cjk=HEAD_CJK, size=Pt(18), bold=True)

    line(doc, "项目：火情智能监测与预警系统（FireGuard AI）")
    line(doc, "说明：本章节与表格格式严格参照《软件需求规格说明书（上学期实训的）》，仅保留其第 4 章\"非功能性需求\"的章节与表格结构。")
    doc.add_paragraph()

    def heading(text: str, level: int = 1) -> None:
        para = doc.add_heading(text, level=level)
        para.paragraph_format.first_line_indent = Pt(0)

    heading("4. 非功能性需求", 1)

    heading("4.1 用户界面需求", 2)
    caption(doc, "表 4-1 用户界面需求")
    add_table(
        doc,
        ["需求名称", "详细要求"],
        [
            ["界面风格统一", "系统采用统一的深色侧栏与浅色内容区风格，五个页面的布局、色彩与控件样式保持一致。"],
            ["导航结构清晰", "采用侧栏菜单导航，包含监控总览、实时监控、告警中心、视频源管理、系统设置五个入口，核心功能三次点击内可达。"],
            ["实时画面展示", "实时监控页面按视频源数量自适应排列，画面按比例缩放不拉伸，画面内显示检测框，画面旁显示目标数量、风险分、帧率与延迟。"],
            ["告警提示明确", "新告警在 1 秒内以弹窗提示，顶部显示未处理告警数量；告警中心支持按告警类型与处理状态筛选。"],
            ["状态显示清晰", "视频源显示在线/离线与启用/停用状态；页面顶部显示实时通道连接状态。"],
            ["操作反馈友好", "上传、启停、参数保存等操作在 500ms 内给出成功或失败提示，失败信息包含原因与处理建议。"],
            ["分辨率适配", "支持 1366×768 及以上分辨率，推荐 1920×1080，页面显示正常且不出现横向滚动条。"],
            ["错误提示友好", "表单校验与接口异常均给出明确提示，例如\"请确认后端已启动\"。"],
        ],
        [3.4, 12.0],
        center_body=False,
    )

    doc.add_paragraph()
    heading("4.2 软硬件环境需求", 2)
    caption(doc, "表 4-2 软硬件环境需求")
    add_table(
        doc,
        ["需求名称", "详细要求"],
        [
            ["服务器/演示机操作系统", "支持 Windows 10/11 64 位操作系统。"],
            ["服务器硬件", "CPU 4 核以上、内存 8GB 以上（推荐 16GB）、可用磁盘空间 20GB 以上。"],
            ["GPU 环境", "支持 CUDA 的 NVIDIA 显卡，显存 4GB 以上（本项目使用 RTX 4050 6GB 验证）。"],
            ["后端运行环境", "Python 3.12 + PyTorch 2.11.0（CUDA）+ Ultralytics 8.4.145，运行于 ai/.venv 独立环境。"],
            ["前端运行环境", "Node.js 20 以上，基于 Vue3 + Vite + Element Plus + ECharts 构建。"],
            ["数据库环境", "使用本地 SQLite 数据库存储视频源、告警与配置数据，不依赖独立数据库服务。"],
            ["浏览器环境", "支持 Chrome / Edge 最新版本，需支持 WebSocket 与 MJPEG 画面显示。"],
            ["手机端环境", "安卓 8.0 以上手机，安装 IP Webcam 应用，用于局域网/热点推流。"],
            ["网络环境", "手机与电脑处于同一局域网或手机热点，电脑可访问手机推流地址，不依赖公网。"],
        ],
        [3.8, 11.6],
        center_body=False,
    )

    doc.add_paragraph()
    heading("4.3 产品质量需求", 2)
    caption(doc, "表 4-3 产品质量需求")
    add_table(
        doc,
        ["主要质量属性", "详细要求"],
        [
            ["正确性", "明火置信度达到阈值时产生严重告警，烟雾连续达到设定帧数后产生预警；告警记录、页面展示与统计结果保持一致；首轮模型验证集 mAP50 为 0.758，清洗数据集后复核，明火检测 mAP50 不低于 0.70。"],
            ["健壮性", "对不存在的视频地址、错误的文件格式、超过 500MB 的上传文件等异常输入进行校验并给出提示；单路视频源异常不影响其他视频源与接口服务。"],
            ["可靠性", "连续运行 2 小时无崩溃；视频源断流后按 1 秒至 60 秒退避自动重连，离线时告警状态机复位；告警写入 SQLite 成功率 100%，服务重启后记录仍可查询。"],
            ["性能，效率", "每路视频源检测帧率 3~5 FPS（默认 4 FPS）；局域网端到端画面延迟不超过 1 秒；告警产生到前端展示不超过 3 秒；GPU 模式支持 4 路并发，单帧推理不超过 100ms；后端含模型加载启动不超过 15 秒；单路 GPU 显存占用不超过 3GB，4 路服务内存占用不超过 4GB。"],
            ["易用性", "主要功能三步内可达；视频源支持一键启停；支持拖拽上传 MP4/MOV 文件；设置页对阈值、连续帧、冷却时间等参数给出含义说明。"],
            ["清晰性", "界面信息层级清晰，术语统一；视频源在线/离线、启用/停用与实时通道连接状态标识明确；告警按类型与级别用颜色区分；错误提示包含原因与处理建议；提供演示脚本与操作说明，非开发成员可独立完成演示。"],
            ["安全性", "系统仅部署在局域网或手机热点环境，不开放公网端口；视频源地址、告警记录与截图均存储在本地；演示素材不包含可识别的个人信息；API Key、密码等敏感信息不写入代码仓库。"],
            ["可扩展性", "后端按配置、数据库、检测器、检测任务、告警引擎、事件、接口等模块拆分；视频源类型、模型路径与阈值参数均可配置；预留智能体复核、远距离切片识别、多路 RTSP 接入与数据库切换的扩展空间。"],
            ["兼容性", "支持 Windows 10/11 与 Chrome、Edge 最新版本；支持 file、http（手机 IP Webcam）、rtsp 三类视频源接入；支持 NVIDIA GPU 推理与 CPU 降级运行；适配 1366×768 及以上分辨率；支持安卓 8.0 以上手机推流。"],
            ["可移植性", "系统不依赖云服务即可独立运行；模型路径、数据库路径、服务端口与检测参数均可配置；数据以本地 SQLite 文件存储，可直接备份迁移；未来可容器化部署并平滑切换数据库。"],
        ],
        [2.8, 12.6],
        center_body=False,
        font_size=Pt(9),
    )

    doc.add_paragraph()
    heading("4.4 项目进度要求", 2)
    line(doc, "本项目周期为 8 周（2026 年 9 月 3 日至 11 月 5 日）：前 3 周完成核心闭环，包括视频源接入、烟火检测、分级告警、前端页面与前后端打通；"
              "第 3~4 周完成数据去重与防泄漏重划分、模型重训与手机推流实测；第 5~7 周完成智能体复核与远距离识别；"
              "第 7~8 周完成结项材料整理与课堂演示。项目要求每周产出可演示增量，并在每次进度汇报时提供阶段成果与过程材料。")

    doc.add_paragraph()
    heading("4.5 其它需求", 2)
    caption(doc, "表 4-4 其它需求")
    add_table(
        doc,
        ["需求名称", "详细要求"],
        [
            ["文档与过程要求", "按课程模板提交软件介绍、项目章程、需求规格说明书、工作任务分解说明书；每份文档标注负责人，附过程证据与版本历史，并按\"起草—评审—定稿\"流程执行。"],
            ["演示与培训要求", "提供演示脚本与系统启动说明，非开发成员可独立完成课堂演示；演示前完成手机推流与上传视频两条链路的预演。"],
            ["数据与模型合规", "训练数据集仅用于学术探索并标注来源与许可；数据集与模型权重不进入代码仓库；训练参数与评测结果形成实验记录，保证可追溯。"],
            ["需求可追溯要求", "功能需求、用例、测试用例与工作任务分解工作包之间建立对应关系；评审意见、修改内容与修改人记录留痕。"],
            ["备份与恢复要求", "备份 storage/*.db 文件即可恢复告警记录与系统配置；提供备份与恢复操作说明。"],
            ["维护与演进要求", "架构预留智能体复核、远距离识别、多路 RTSP 接入与数据库切换空间；检测模型、告警规则与前端页面可独立升级，不相互阻塞。"],
        ],
        [3.4, 12.0],
        center_body=False,
        font_size=Pt(9),
    )

    doc.save(OUT_NFR / "03_需求规格说明书_非功能性需求部分.docx")


if __name__ == "__main__":
    build_charter()
    build_nfr()
    print("done")
