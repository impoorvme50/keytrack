#!/usr/bin/env python3
"""keytrack 命令行入口。

用法：
    python kbd.py setup-ime         # 把采集钩子装进鼠须管（一次性配置）
    python kbd.py install-agent     # 装 launchd 常驻 helper（登录即自动采集）
    python kbd.py record            # 前台手动采集（装了 agent 就不用管）
    python kbd.py today             # 查看今天输入了什么
    python kbd.py today --json      # 同上，JSON 输出（给看板/脚本用）
    python kbd.py show 2026-07-28   # 查看指定某天
    python kbd.py days              # 列出库里有数据的所有日期
    python kbd.py ingest            # 手动吸入一次待收事件（补录）
    python kbd.py status            # 常驻 helper / 待收事件状态
    python kbd.py install-kev-agent /path/to/Kev  # 安装可开关的 Kev 0.8B 服务
    python kbd.py setup-kev-rime     # 安装雾凇拼音候选建议钩子
    python kbd.py kev on|off|status  # 开关 Kev 候选建议
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from keytrack import (
    agent,
    console,
    doctor,
    ax_capture,
    ergo,
    heatmap,
    ime_ingest,
    kev_rime_setup,
    kev_switch,
    kev_service,
    query,
    rime_setup,
    runner,
    storage,
    viewer,
    week,
)


def _show(day_arg: str, db_path: str, full: bool, as_json: bool) -> None:
    day = viewer.parse_day(day_arg)
    # 查询前先把还躺在 jsonl 里的事件补进库（helper 没跑也不丢数据）
    ime_ingest.ingest_once(db_path=db_path, quiet=True)
    if as_json:
        print(json.dumps(query.day_report(day, db_path=db_path), ensure_ascii=False, indent=2))
    else:
        viewer.show_day(day, db_path=db_path, full=full)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kbd", description="本地键盘输入内容记录与回看")
    parser.add_argument("--db", default=storage.DEFAULT_DB_PATH, help="数据库路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="前台采集（装了 install-agent 后一般不用手动跑）")
    p_rec.add_argument("-v", "--verbose", action="store_true", help="实时打印落库片段")
    p_rec.add_argument(
        "--pynput",
        action="store_true",
        help="额外开 pynput 系统级按键监听（仅当还在用别的输入法时；需输入监控权限）",
    )

    p_today = sub.add_parser("today", help="查看今天输入了什么")
    p_today.add_argument("--full", action="store_true", help="完整内容不截断")
    p_today.add_argument("--json", action="store_true", help="JSON 输出")

    p_show = sub.add_parser("show", help="查看指定某天（YYYY-MM-DD / today / yesterday）")
    p_show.add_argument("day")
    p_show.add_argument("--full", action="store_true", help="完整内容不截断")
    p_show.add_argument("--json", action="store_true", help="JSON 输出")

    sub.add_parser("days", help="列出库里有数据的所有日期")
    sub.add_parser("ingest", help="手动吸入一次待收事件（补录）")

    p_heat = sub.add_parser("heatmap", help="导出键盘热力图 HTML 并打开")
    p_heat.add_argument("day", nargs="?", help="YYYY-MM-DD，缺省为全部累计")

    p_ergo = sub.add_parser("ergo", help="手/指负载均衡与按键熵分析")
    p_ergo.add_argument("day", nargs="?", help="YYYY-MM-DD，缺省为全部累计")

    p_week = sub.add_parser("week", help="最近 7 天周报")
    p_week.add_argument("--json", action="store_true", help="JSON 输出")
    p_week.add_argument("--push-webhook", metavar="URL", help="推送到 Lark 自定义机器人 webhook")

    sub.add_parser("setup-ime", help="安装/更新鼠须管的 keytrack 采集钩子并触发部署")
    sub.add_parser("setup-kev-rime", help="安装 Kev 按需候选建议（仅雾凇拼音）")
    p_kev = sub.add_parser("kev", help="开关 Kev 候选建议（默认关闭）")
    p_kev.add_argument("action", choices=("on", "off", "toggle", "status"))
    p_kev_agent = sub.add_parser("install-kev-agent", help="安装可随 Kev 开关启停的本机 0.8B 服务")
    p_kev_agent.add_argument("repo", help="Kev 仓库本机路径（需已有 .venv）")
    sub.add_parser("uninstall-kev-agent", help="停止并卸载 Kev 0.8B 服务")
    sub.add_parser("install-agent", help="安装 launchd 常驻 helper（登录即自动采集）")
    sub.add_parser("uninstall-agent", help="卸载常驻 helper")
    sub.add_parser("status", help="常驻 helper 与待收事件状态")
    sub.add_parser("ui", help="打开 Keytrack 本地控制台窗口")
    p_console = sub.add_parser("console", help="启动本地输入控制台")
    p_console.add_argument("--port", type=int, default=0, help="本机端口，缺省自动选择")
    p_console.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p_console.add_argument("--demo", action="store_true", help="用隔离测试数据验证界面")
    p_native = sub.add_parser("console-native", help=argparse.SUPPRESS)
    p_native.add_argument("--demo", action="store_true")
    p_doctor = sub.add_parser("doctor", help="只读检查输入法钩子、部署与本机 Kev 服务")
    p_doctor.add_argument("--json", action="store_true", help="JSON 输出")
    sub.add_parser("probe", help="实时探测辅助功能能读到哪个应用的输入内容（诊断用）")

    args = parser.parse_args(argv)

    if args.cmd == "record":
        runner.run(db_path=args.db, verbose=args.verbose, pynput=args.pynput)
    elif args.cmd == "today":
        _show("today", args.db, args.full, args.json)
    elif args.cmd == "show":
        _show(args.day, args.db, args.full, args.json)
    elif args.cmd == "days":
        for d in query.available_days(db_path=args.db):
            print(d)
    elif args.cmd == "ingest":
        n = ime_ingest.ingest_once(db_path=args.db, verbose=True)
        print(f"已吸入 {n} 条记录。")
    elif args.cmd == "heatmap":
        day = viewer.parse_day(args.day) if args.day else None
        out = heatmap.export(day=day, db_path=args.db)
        print("热力图已导出：", out)
    elif args.cmd == "ergo":
        day = viewer.parse_day(args.day) if args.day else None
        ergo.show(day=day, db_path=args.db)
    elif args.cmd == "week":
        rep = week.week_report(db_path=args.db)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        else:
            week.show(rep)
        if args.push_webhook:
            ok = week.push_lark(args.push_webhook, week.format_text(rep))
            print("已推送到 Lark。" if ok else "推送失败（见上方原因）。")
    elif args.cmd == "setup-ime":
        return 0 if rime_setup.setup() else 1
    elif args.cmd == "setup-kev-rime":
        return 0 if kev_rime_setup.setup() else 1
    elif args.cmd == "kev":
        return 0 if kev_switch.command(args.action) else 1
    elif args.cmd == "install-kev-agent":
        return 0 if kev_service.install(Path(args.repo)) else 1
    elif args.cmd == "uninstall-kev-agent":
        kev_switch.set_enabled(False)
        return 0 if kev_service.uninstall() else 1
    elif args.cmd == "install-agent":
        return 0 if agent.install() else 1
    elif args.cmd == "uninstall-agent":
        return 0 if agent.uninstall() else 1
    elif args.cmd == "status":
        agent.status()
    elif args.cmd == "ui":
        return 0 if console.launch() else 1
    elif args.cmd == "console":
        console.serve(args.port, args.db, args.demo, not args.no_open)
    elif args.cmd == "console-native":
        console.native_serve(args.db, args.demo)
    elif args.cmd == "doctor":
        return 0 if doctor.command(args.json) else 1
    elif args.cmd == "probe":
        ax_capture.probe()
    return 0


if __name__ == "__main__":
    sys.exit(main())
