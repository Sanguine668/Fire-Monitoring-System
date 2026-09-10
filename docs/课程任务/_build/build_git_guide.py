"""生成《Git 协作与仓库使用说明（组员版）》.docx。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from common import add_table, h1, h2, new_document, numbers, p  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "课程任务" / "项目参考材料"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = new_document(
        "火情智能监测与预警系统",
        "Git 协作与仓库使用说明（组员版）",
        [
            ("仓库地址", "https://github.com/Sanguine668/Fire-Monitoring-System"),
            ("协作方式", "分支开发 + Pull Request 合并；main 分支只由组长合并"),
            ("适用对象", "李汶航、欧阳宇康、陈泽恩（蔡俊杰负责仓库管理与合并）"),
            ("版本 / 日期", "v1.0 / 2026 年 9 月 10 日"),
        ],
        doc_number="FGA-GIT-2026-001",
    )

    h1(doc, "1. 加入仓库（第一步）")
    numbers(doc, [
        "组长在 GitHub 仓库页面进入 Settings → Collaborators，按你的 GitHub 用户名或邮箱发出邀请；",
        "登录你的 GitHub 账号，在邮箱里接受邀请（没有账号就先注册，用户名建议用真实姓名拼音）；",
        "安装 Git（Windows 版），安装后在任意位置右键打开 Git Bash；",
        "配置身份信息（只需一次）：",
    ])
    add_table(
        doc,
        ["命令", "作用"],
        [
            ["git config --global user.name \"你的姓名拼音\"", "设置提交者名称"],
            ["git config --global user.email \"你的邮箱\"", "设置提交者邮箱（与 GitHub 一致）"],
        ],
        [8.0, 7.4],
    )
    p(doc, "推送方式二选一：① 配置 SSH 密钥（推荐，一次配置长期使用）；② 使用 HTTPS 地址配合 GitHub Personal Access Token"
           "（注意：GitHub 已不支持用账号密码推送，必须用 Token）。不确定选哪种就先问组长，不要反复试错。", indent=True)

    h1(doc, "2. 首次下载与目录约定")
    add_table(
        doc,
        ["命令", "作用"],
        [
            ["git clone https://github.com/Sanguine668/Fire-Monitoring-System.git", "把仓库下载到本地"],
            ["cd Fire-Monitoring-System", "进入项目目录"],
            ["git status", "查看当前改动状态（应显示干净）"],
        ],
        [8.0, 7.4],
    )
    add_table(
        doc,
        ["目录", "放什么", "要求"],
        [
            ["docs/课程任务/<任务名称>/", "你负责的 Word/Markdown 成果", "只放自己负责的文档，文件名带姓名与版本"],
            ["docs/课程任务/过程记录/<姓名>/", "访谈记录、截图、测试记录、会议纪要", "命名带日期，例如 20260912_访谈记录_李汶航.docx"],
            ["docs/images/ 或文档同级 images/", "你画的图（用例图、流程图、WBS 树状图）", "同时提交源文件（.drawio/.vsdx/.puml）与导出的 PNG"],
            ["backend/、frontend/、ai/、scripts/", "系统代码与脚本", "除非分工明确且已和组长确认，否则不要修改"],
        ],
        [4.6, 5.6, 5.2],
    )

    h1(doc, "3. 每次提交的标准流程（重要）")
    numbers(doc, [
        "先同步最新代码：git switch main（或 master，以仓库实际分支为准）→ git pull；",
        "新建自己的工作分支，名称格式：类型/姓名-任务，例如 docs/liwenhang-charter；",
        "在自己的分支上修改文件，改完用 git status 与 git diff 检查；",
        "只添加自己改的文件：git add <文件路径>（不要图省事用 git add . 把所有东西都加进去）；",
        "提交并写清信息：git commit -m \"docs(任务2): 完成项目章程初稿 - 李汶航\"；",
        "推送到远程：git push -u origin docs/liwenhang-charter；",
        "在 GitHub 上发起 Pull Request（目标分支 main），等组长检查合并；",
        "合并后回到 main 并拉取最新：git switch main → git pull → 删除本地已完成分支。",
    ])
    add_table(
        doc,
        ["提交信息示例", "适用场景"],
        [
            ["docs(任务3): 完成附录A需求调查记录 - 欧阳宇康", "文档类提交"],
            ["test(任务3): 补充5条功能测试记录与截图 - 欧阳宇康", "测试类提交"],
            ["fig(任务4): 新增WBS树状图源文件与PNG - 陈泽恩", "图表类提交"],
            ["fix(docs): 修正章程里程碑日期 - 李汶航", "修改与纠错"],
        ],
        [8.6, 6.8],
    )

    h1(doc, "4. 禁止事项（违反会导致仓库混乱）")
    numbers(doc, [
        "禁止直接往 main 分支提交或强推（git push -f）：main 只由组长合并；",
        "禁止提交大数据与权重：datasets/、runs/、*.pt、*.onnx、*.weights、node_modules/、dist/、__pycache__/、"
        "storage/*.db、storage/uploads/（这些已在 .gitignore 中，若发现能提交说明你操作有误，先问组长）；",
        "禁止提交密钥与隐私：账号密码、Token、API Key、身份证号、手机号、个人住址；",
        "禁止修改或删除他人负责的文件；确需修改时先在群里说明，由文件主责人确认；",
        "禁止一次性提交几十兆的压缩包、视频、录屏（演示视频请放本地，按需单独发送）；",
        "禁止使用 git reset --hard、git clean -fdx 等会丢失工作的命令；遇到问题先截图问组长。",
    ])

    h1(doc, "5. 常见问题与处理")
    add_table(
        doc,
        ["现象", "原因", "处理办法"],
        [
            ["认证失败", "GitHub 不再支持账号密码推送", "改用 Personal Access Token 或配置 SSH 密钥"],
            ["推送被拒绝", "远程已有新提交，本地落后", "先 git pull（或 git pull --rebase），解决冲突后再 push"],
            ["不小心提交了大文件", "把数据/权重/依赖加进来了", "git rm --cached <文件>，确认 .gitignore 已包含，再提交；必要时请组长清理历史"],
            ["提交到了错误的分支", "忘了先建分支", "在当前分支把改动提交后，cherry-pick 到新分支；或直接找组长协助"],
            ["冲突不会解决", "两人改了同一文件同一位置", "不要强推，先把冲突文件发给组长，由文件主责人协商后合并"],
            ["clone 很慢或失败", "网络问题", "改用 SSH 或稍后重试；也可先接收组长的压缩包，网络恢复后再 clone"],
        ],
        [3.6, 4.4, 7.4],
    )

    h1(doc, "6. 每周协作节奏与工作量留痕")
    numbers(doc, [
        "每周至少提交一次自己的进展（文档或图表），并在群里发一句进度说明；",
        "每次提交的作者必须是你本人配置的 Git 身份，不要替他人提交；",
        "重要节点（起草、评审、定稿）分别提交，便于体现个人工作量；",
        "如果本周没有产出，也要提交一条说明性更新（例如在个人过程记录中补充会议纪要）；",
        "组长每周合并一次分支，合并前在群里通知；合并后所有人先 git pull 再继续工作。",
    ])

    h1(doc, "7. 求助流程")
    p(doc, "遇到不会的命令或报错，按以下顺序处理：① 先截图报错信息发群里；② 说明你执行的是什么命令、想达到什么效果；"
           "③ 等组长确认后再操作。不要凭感觉重复尝试高危命令。如果实在无法使用 Git，可以把文件打包发组长，"
           "由组长代为提交，并在提交信息中注明原作者。", indent=True)

    path = OUT / "Git协作与仓库使用说明（组员版）.docx"
    doc.save(path)
    print(path)


if __name__ == "__main__":
    main()
