#!/usr/bin/env python3

from typing import List, NamedTuple, Optional, Set

import argparse
import psutil
import re
import sys
import time

import colorama
from colorama import Fore, Style


ES_BRIGHT = Style.BRIGHT
ES_COLOR_RED = Fore.RED
ES_COLOR_BLUE = Fore.BLUE
ES_RESET = Style.RESET_ALL


class ProcessDesc(NamedTuple):
    pid: int
    name: str
    cmdline: List[str]
    cwd: str


def format_text_bold(text: str, query_pat: re.Pattern, es_base: str) -> str:
    return query_pat.sub(lambda m: ES_BRIGHT + m.group(0) + ES_RESET + es_base, text)


def format_command_line(command_line: List[str], query_pat: re.Pattern, es_base: str) -> str:
    prev_arg_printed = True
    args_printed = [es_base]
    for i, a in enumerate(command_line):
        if i in [0, 1] or query_pat.search(a):
            if prev_arg_printed:
                args_printed.append(format_text_bold(a, query_pat, es_base))
            else:
                args_printed.append("...")
                args_printed.append(format_text_bold(a, query_pat, es_base))
            prev_arg_printed = True
        else:
            prev_arg_printed = False
    if not prev_arg_printed:
        args_printed.append("...")
    return " ".join(args_printed)


def get_proc_descriptions(
    query_pat: re.Pattern, cmd_exclude_list: Optional[List[str]] = None, pid_exclude_list: Optional[List[int]] = None
) -> List[ProcessDesc]:
    cmd_blacklist_set: Set(str) = set(cmd_exclude_list) if cmd_exclude_list else set()
    pid_blacklist_set: Set(int) = set(pid_exclude_list) if pid_exclude_list else set()
    descs = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
        if p.pid in pid_blacklist_set:
            continue
        try:
            desc = ProcessDesc(p.pid, p.name(), p.cmdline(), p.cwd())
            if p.name() not in cmd_blacklist_set and (
                query_pat.search(desc.name) or any(query_pat.search(a) for a in desc.cmdline) or query_pat.search(desc.cwd)
            ):
                descs.append(desc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return descs


def get_all_related_process_ids():
    pid_blacklist = []
    p = psutil.Process()
    pid_blacklist.append(p.pid)
    for cp in p.children(recursive=True):
        pid_blacklist.append(cp.pid)
    return pid_blacklist


def main():
    parser = argparse.ArgumentParser(
        description="Watch processes and show life-and-death information of them.",
        usage="%(prog)s [-i INTERVAL] [-l DURATION] [-x CMDNAME]... query",
    )
    parser.add_argument("query", metavar="query", type=str, help="query pattern (regular expression) to identify processes to watch")
    parser.add_argument(
        "-i",
        "--interval",
        metavar="INTERVAL",
        type=float,
        default=0.5,
        help="set the interval between checks (in seconds), default is 0.5",
    )
    parser.add_argument(
        "-l",
        "--highlight",
        metavar="DURATION",
        type=float,
        default=3.0,
        help="set the duration to highlight the results (in seconds), default is 3.0",
    )
    parser.add_argument(
        "-x",
        "--cmd-exclude",
        metavar="CMDNAME",
        type=str,
        action="append",
        help="add a command name to ignore",
    )
    args = parser.parse_args()

    colorama.init()

    life_and_death_history_max_length = int(args.highlight / args.interval)
    try:
        query_pat = re.compile(args.query)
    except re.error as e:
        print("Error: invalid pattern: %s", repr(args.query), file=sys.stderr)
        print("  %s" % e, file=sys.stderr)
        sys.exit(1)

    process_descs_queue = [
        get_proc_descriptions(query_pat, cmd_exclude_list=args.cmd_exclude, pid_exclude_list=get_all_related_process_ids())
    ]

    while True:
        process_descs_queue.append(
            get_proc_descriptions(
                query_pat, cmd_exclude_list=args.cmd_exclude, pid_exclude_list=get_all_related_process_ids()
            )
        )

        if len(process_descs_queue) > life_and_death_history_max_length:
            process_descs_queue.pop(0)

        all_pid_set = set()
        for pds in process_descs_queue:
            all_pid_set.update(pd.pid for pd in pds)

        new_pid_set = all_pid_set - set(pd.pid for pd in process_descs_queue[0])
        dead_pid_set = all_pid_set - set(pd.pid for pd in process_descs_queue[-1])

        lines = []
        pid_done_set = set()
        for pds in reversed(process_descs_queue):
            for pd in pds:
                pid = pd.pid
                if pid in pid_done_set:
                    continue
                pid_done_set.add(pid)
                if pid in dead_pid_set:
                    es_color = ES_COLOR_RED
                    header = "-"
                elif pid in new_pid_set:
                    es_color = ES_COLOR_BLUE
                    header = "+"
                else:
                    es_color = ""
                    header = " "
                s = "%s%spid %d, name %s, cmdline %s, cwd %s%s" % (
                    es_color,
                    header,
                    pid,
                    format_text_bold(pd.name, query_pat, es_color),
                    format_command_line(pd.cmdline, query_pat, es_color),
                    format_text_bold(pd.cwd, query_pat, es_color),
                    ES_RESET,
                )
                lines.append(s)

        title_line = "[process-life-and-death-monitor] query %s" % repr(args.query)
        if args.cmd_exclude:
            title_line += ", cmd-exclude %s" % ",".join(repr(b) for b in args.cmd_exclude)
        lines = [
            title_line,
            "---"
        ] + lines
        print("\033[1;1H\033[2J" + "\n".join(lines))

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
