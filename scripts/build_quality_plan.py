"""根据质量管理库现有任务，生成要回填的工期、日期、责任人、自定义字段与备注。"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 20)

DATES = {
    2: "2026-09-08", 3: "2026-09-09", 4: "2026-09-10", 5: "2026-09-11",
    7: "2026-09-24", 8: "2026-09-25", 9: "2026-09-28", 10: "2026-09-29",
    11: "2026-09-30", 12: "2026-10-08", 13: "2026-10-09", 14: "2026-10-12", 15: "2026-10-13",
    17: "2026-10-14", 18: "2026-10-15", 19: "2026-10-16", 20: "2026-10-19",
    21: "2026-10-19", 22: "2026-10-20", 23: "2026-10-21",
    25: "2026-10-20", 26: "2026-10-22", 27: "2026-10-20", 28: "2026-10-23", 29: "2026-10-26",
    31: "2026-10-30", 32: "2026-11-02", 33: "2026-11-03", 34: "2026-11-04",
    35: "2026-11-04", 36: "2026-11-05", 37: "2026-11-05",
    39: "2026-09-21", 40: "2026-09-28", 41: "2026-10-09", 42: "2026-10-12",
    43: "2026-10-14", 44: "2026-10-16", 45: "2026-10-19", 46: "2026-10-22",
    47: "2026-10-26", 48: "2026-10-28",
}

TYPES = {
    2: "文档评审", 3: "文档评审", 4: "文档评审", 5: "文档评审",
    7: "代码走查", 8: "功能测试", 9: "功能测试", 10: "功能测试", 11: "集成测试",
    12: "代码走查", 13: "集成测试", 14: "功能测试", 15: "代码走查",
    17: "数据检查", 18: "数据检查", 19: "数据检查", 20: "数据检查",
    21: "模型评测", 22: "模型评测", 23: "模型评测",
    25: "代码走查", 26: "模型评测", 27: "代码走查", 28: "性能测试", 29: "模型评测",
    31: "测试评审", 32: "集成测试", 33: "可靠性测试", 34: "缺陷复测",
    35: "演示评审", 36: "质量门禁", 37: "质量门禁",
}

WBS = {
    2: "1.1", 3: "1.2", 4: "1.3", 5: "1.4",
    7: "2.1", 8: "2.1", 9: "2.2", 10: "2.3", 11: "2.4", 12: "2.5",
    13: "2.6", 14: "2.7", 15: "2.8",
    17: "3.1", 18: "3.1", 19: "3.2", 20: "3.3", 21: "3.3", 22: "3.4", 23: "3.4",
    25: "4.1", 26: "4.2", 27: "4.3", 28: "4.3", 29: "4.4",
    31: "5.1", 32: "5.2", 33: "5.2", 34: "5.2", 35: "5.3", 36: "5.4", 37: "5.4",
    39: "3.1", 40: "3.1", 41: "3.3", 42: "3.4", 43: "4.4",
    44: "2.3", 45: "2.4", 46: "2.2", 47: "2.5", 48: "3.4",
}

RESOURCES = {
    2: "蔡俊杰;欧阳宇康", 3: "蔡俊杰;欧阳宇康", 4: "蔡俊杰;欧阳宇康", 5: "蔡俊杰;欧阳宇康",
    7: "李汶航;欧阳宇康", 8: "李汶航;欧阳宇康", 9: "李汶航;欧阳宇康", 10: "李汶航;欧阳宇康",
    11: "李汶航;欧阳宇康", 12: "李汶航;欧阳宇康", 13: "李汶航;欧阳宇康",
    14: "李汶航;欧阳宇康", 15: "李汶航;欧阳宇康",
    17: "陈泽恩;欧阳宇康", 18: "陈泽恩;欧阳宇康", 19: "陈泽恩;欧阳宇康", 20: "陈泽恩;欧阳宇康",
    21: "蔡俊杰;欧阳宇康", 22: "陈泽恩;欧阳宇康", 23: "蔡俊杰;欧阳宇康",
    25: "蔡俊杰;欧阳宇康", 26: "蔡俊杰;欧阳宇康", 27: "蔡俊杰;欧阳宇康",
    28: "蔡俊杰;欧阳宇康", 29: "陈泽恩;欧阳宇康",
    31: "蔡俊杰;欧阳宇康", 32: "蔡俊杰;欧阳宇康", 33: "李汶航;欧阳宇康",
    34: "李汶航;欧阳宇康", 35: "蔡俊杰;欧阳宇康", 36: "蔡俊杰;欧阳宇康", 37: "蔡俊杰;欧阳宇康",
    39: "陈泽恩;欧阳宇康", 40: "陈泽恩;欧阳宇康", 41: "陈泽恩;欧阳宇康",
    42: "陈泽恩;蔡俊杰", 43: "陈泽恩;蔡俊杰", 44: "蔡俊杰;李汶航",
    45: "李汶航;陈泽恩", 46: "李汶航;陈泽恩", 47: "李汶航;蔡俊杰", 48: "欧阳宇康;蔡俊杰",
}

LONG_TASKS = {11, 23, 27, 31, 32, 35, 37}
PCT_OVERRIDE = {25: 50, 27: 50, 42: 50, 43: 50, 44: 80, 45: 50, 46: 30, 47: 0, 48: 0}
RESULT_OVERRIDE = {
    25: "整改中", 27: "整改中", 42: "整改中", 43: "整改中", 44: "整改中", 45: "整改中", 46: "整改中",
    47: "待处理", 48: "待处理", 39: "已关闭", 40: "已关闭", 41: "已关闭",
}

MEASURES = {
    1: "用 MD5+pHash 去重，按视频段重新划分训练/验证集",
    2: "引入 D-Fire 双类数据并重训 smoke/fire 模型",
    3: "补充远景小目标样本，训练后按小目标子集评估",
    4: "重训 YOLO26n 并对 fire/smoke 阈值重新校准",
    5: "建立困难负样本集，增加局部二次检测复核",
    6: "调整连续帧与告警冷却参数并做回归测试",
    7: "限制单路帧率，多路接入时自动降级",
    8: "增加心跳检测与指数退避重连",
    9: "为告警查询增加索引与分页",
    10: "由非训练者按脚本独立复算并留存记录",
}


def evidence_for(kind: str, task_id: int) -> str:
    if task_id in (17, 18, 19, 20):
        return "docs/课程任务/数据集质量报告/数据质量体检报告.md"
    if task_id in (21, 22, 23):
        return "ai/runs/fire26n-v2/results.csv"
    if task_id in (25, 26, 27, 28, 29):
        return "docs/superpowers/specs/2026-10-20-verification-agent-design.md"
    if kind == "文档评审":
        return "docs/课程任务/暂时定稿的文档/"
    if kind == "代码走查":
        return "backend/tests/"
    if kind in ("功能测试", "集成测试", "性能测试", "可靠性测试"):
        return "docs/test-records/"
    if kind == "缺陷复测":
        return "docs/test-records/report.json"
    return "docs/课程任务/"


CRITERIA = {
    "文档评审": "文档齐全、编号一致、评审记录完整且可追溯",
    "代码走查": "接口符合约定、异常分支有处理、相关单测通过",
    "功能测试": "用例通过率不低于 95%，无严重缺陷遗留",
    "集成测试": "端到端链路可复现，事件与页面数据一致",
    "性能测试": "单路推理延迟满足 4 FPS 采样要求",
    "可靠性测试": "断流、重连、异常输入均有明确处理",
    "数据检查": "无重复与泄漏，标注抽检合格率不低于 95%",
    "模型评测": "mAP50 与远景召回达到阶段目标并留存复算记录",
    "缺陷复测": "缺陷已修复，复测通过并更新状态",
    "测试评审": "用例覆盖核心流程，通过率与缺陷闭环可核查",
    "演示评审": "双通道演示流程完整，异常时有降级方案",
    "质量门禁": "交付物齐全，配置项与复现材料可追溯",
}


def build(dump: Path) -> list[dict]:
    tasks = {}
    for line in dump.read_text(encoding="utf-8").splitlines():
        parts = line.split("|")
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        tasks[int(parts[0])] = parts[1]

    plan: list[dict] = []
    for task_id, name in tasks.items():
        if task_id in (0, 1, 6, 16, 24, 30, 38):
            continue
        day = date.fromisoformat(DATES[task_id])
        is_defect = task_id >= 39
        kind = "缺陷复测" if is_defect else TYPES[task_id]
        evidence = evidence_for(kind, task_id)
        pct = PCT_OVERRIDE.get(task_id, 100 if day <= TODAY else 0)
        result = RESULT_OVERRIDE.get(task_id)
        if result is None:
            result = "通过" if pct == 100 else ("整改中" if pct > 0 else "待检查")
        code = re.match(r"^(Q\d+|DEF-\d+)", name)
        code_text = code.group(1) if code else ""

        if is_defect:
            idx = int(code_text.split("-")[1])
            hours = 16 if idx in (4, 5) else 8
            note = (
                f"缺陷描述：{name}。处理措施：{MEASURES[idx]}。"
                f"当前状态：{result}，完成度 {pct}%。"
            )
        else:
            hours = 8 if task_id in LONG_TASKS else 4
            note = (
                f"检查范围：{name}。通过判据：{CRITERIA[kind]}。"
                f"证据：{evidence}。当前结论：{result}。"
            )

        plan.append({
            "id": task_id,
            "code": code_text,
            "duration": f"{hours}h",
            "start": DATES[task_id],
            "pct": pct,
            "t1": code_text,
            "t2": WBS.get(task_id, ""),
            "t3": kind,
            "t4": evidence,
            "t5": result,
            "n1": 0,
            "n2": None,
            "res": RESOURCES.get(task_id, "欧阳宇康"),
            "notes": note,
        })
    return plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default="storage/tmp_mpxj/dump.txt")
    ap.add_argument("--out", default="storage/tmp_mpxj/quality_plan.json")
    args = ap.parse_args()
    plan = build(ROOT / args.dump)
    (ROOT / args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(plan)} tasks -> {args.out}")


if __name__ == "__main__":
    main()
