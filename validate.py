#!/usr/bin/env python3
"""课表 JSON（tabito-course-timetable/v1）自查。只用标准库。用法：python3 validate.py 课表.json
与平台的核对规则一致（server/teaching-course-import.js），但不查老师、科目、重名——那些只有平台知道。"""
import datetime
import json
import re
import sys

FORMAT = "tabito-course-timetable/v1"
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
TOP = {"format", "title", "subtitle", "term", "subject", "teacher", "mode", "room", "description", "expected", "sessions", "breaks"}
SESSION = {"number", "date", "weekday", "start", "end", "topic"}
LIMITS = {"title": 120, "subtitle": 200, "term": 60, "subject": 40, "teacher": 100, "room": 200, "description": 3700}
CLOCK = re.compile(r"\A([01][0-9]|2[0-3]):[0-5][0-9]\Z")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def parse_date(value):
    if not isinstance(value, str) or not re.match(r"\A(20[0-9]{2}|21[0-9]{2}|2200)-[0-9]{2}-[0-9]{2}\Z", value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def minutes(clock):
    return int(clock[:2]) * 60 + int(clock[3:])


def check(t):
    problems, notes = [], []
    if not isinstance(t, dict):
        return ["最外层必须是一个对象。"], notes
    if t.get("format") != FORMAT:
        problems.append(f'format 必须是 "{FORMAT}"。')
    for key in t:
        if key not in TOP:
            problems.append(f"不认识的字段「{key}」。")
    for key in ("title", "subject", "teacher"):
        if not isinstance(t.get(key), str) or not t[key].strip():
            problems.append(f"缺少 {key}。")
    for key, limit in LIMITS.items():
        if key in t and t[key] is not None and (not isinstance(t[key], str) or len(t[key].strip()) > limit or CONTROL.search(t[key])):
            problems.append(f"{key} 必须是 {limit} 字以内的文字。")
    if t.get("mode") not in ("offline", "online", "hybrid"):
        problems.append("mode 必须是 offline、online 或 hybrid。")

    rows = []
    sessions = t.get("sessions")
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 200:
        problems.append("sessions 要有 1 到 200 回课。")
        sessions = []
    for i, row in enumerate(sessions):
        where = f"sessions 第 {i + 1} 行"
        if not isinstance(row, dict):
            problems.append(f"{where}：必须是对象。")
            continue
        bad = False
        for key in row:
            if key not in SESSION:
                problems.append(f"{where}：不认识的字段「{key}」。")
                bad = True
        day = parse_date(row.get("date"))
        if day is None:
            problems.append(f"{where}：date 要写成 2026-08-28，且是真实日期。")
            bad = True
        elif row.get("weekday") not in WEEKDAYS:
            problems.append(f"{where}：weekday 要写成 周一 … 周日。")
            bad = True
        elif WEEKDAYS[day.weekday()] != row["weekday"]:
            problems.append(f"{where}：{row['date']} 是{WEEKDAYS[day.weekday()]}，课表上写的是{row['weekday']}。请核对日期或年份（不要改 weekday 去凑）。")
            bad = True
        start, end = row.get("start"), row.get("end")
        if not (isinstance(start, str) and CLOCK.match(start) and isinstance(end, str) and (CLOCK.match(end) or end == "24:00")):
            problems.append(f"{where}：start / end 要写成 14:00 这样的 24 小时制。")
            bad = True
        elif minutes(end) <= minutes(start):
            problems.append(f"{where}：结束时间必须晚于开始时间。")
            bad = True
        number = row.get("number")
        if number is not None and not (isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= 999):
            problems.append(f"{where}：number 要写成整数。")
            bad = True
        if row.get("topic") is not None and (not isinstance(row["topic"], str) or len(row["topic"].strip()) > 500 or CONTROL.search(row["topic"])):
            problems.append(f"{where}：topic 必须是 500 字以内的文字。")
            bad = True
        if not bad:
            rows.append({"n": number, "date": row["date"], "start": start, "end": end})

    breaks = []
    listed = t.get("breaks")
    if listed is not None and (not isinstance(listed, list) or len(listed) > 100):
        problems.append("breaks 必须是数组（最多 100 项）。")
        listed = []
    for i, gap in enumerate(listed or []):
        a, b = (parse_date(gap.get("from")), parse_date(gap.get("to"))) if isinstance(gap, dict) else (None, None)
        label_ok = isinstance(gap, dict) and ("label" not in gap or (isinstance(gap["label"], str) and len(gap["label"]) <= 40 and not CONTROL.search(gap["label"])))
        if a is None or b is None or b < a or not label_ok or set(gap) - {"from", "to", "label"}:
            problems.append(f'breaks 第 {i + 1} 项要写成 {{"from": "2026-09-20", "to": "2026-10-08", "label": "停课"}}。')
        else:
            breaks.append((gap["from"], gap["to"], gap.get("label") or "停课"))

    if problems:
        return problems, notes
    rows.sort(key=lambda r: (r["date"], r["start"]))
    for before, row in zip(rows, rows[1:]):
        if before["date"] == row["date"] and row["start"] < before["end"]:
            problems.append(f"{row['date']} 有两回课时间重叠。")
    for row in rows:
        for a, b, label in breaks:
            if a <= row["date"] <= b:
                problems.append(f"{row['date']} 的课落在「{label}」期间（{a} 至 {b}）。")
    total = sum(minutes(r["end"]) - minutes(r["start"]) for r in rows)
    expected = t.get("expected")
    if expected is not None:
        if not isinstance(expected, dict) or set(expected) - {"sessionCount", "totalHours", "firstDate", "lastDate"}:
            problems.append("expected 只能有 sessionCount、totalHours、firstDate、lastDate。")
        else:
            count, hours = expected.get("sessionCount"), expected.get("totalHours")
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 1):
                problems.append("expected.sessionCount 必须是正整数。")
                expected = {**expected, "sessionCount": None}
            if hours is not None and (isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0):
                problems.append("expected.totalHours 必须是正数。")
                expected = {**expected, "totalHours": None}
            for key in ("firstDate", "lastDate"):
                if expected.get(key) is not None and parse_date(expected[key]) is None:
                    problems.append(f"expected.{key} 要写成 2026-08-28 这样。")
                    expected = {**expected, key: None}
            if expected.get("sessionCount") is not None and expected["sessionCount"] != len(rows):
                problems.append(f"课表写的是 {expected['sessionCount']} 回，JSON 里有 {len(rows)} 回。")
            if expected.get("totalHours") is not None and round(expected["totalHours"] * 60) != total:
                problems.append(f"课表写的是 {expected['totalHours']} 小时，JSON 里各回加起来是 {total / 60:g} 小时。")
            if expected.get("firstDate") is not None and expected["firstDate"] != rows[0]["date"]:
                problems.append(f"课表写的开始日期是 {expected['firstDate']}，JSON 里第一回是 {rows[0]['date']}。")
            if expected.get("lastDate") is not None and expected["lastDate"] != rows[-1]["date"]:
                problems.append(f"课表写的结束日期是 {expected['lastDate']}，JSON 里最后一回是 {rows[-1]['date']}。")
    else:
        notes.append("没有 expected：课表上写了回数或总课时的话，请补上用来对账。")
    numbers = [r["n"] for r in rows if r["n"] is not None]
    if len(numbers) != len(set(numbers)):
        problems.append("number 有重复。")
    else:
        for position, row in enumerate(rows, start=1):
            if row["n"] is not None and row["n"] != position:
                notes.append(f"课次跳号：课表的第{row['n']}回（{row['date']}）在平台上会是第 {position} 回，之后顺延。交给用户时请说明。")
                break
    notes.append(f"共 {len(rows)} 回，{total / 60:g} 小时，{rows[0]['date']} 至 {rows[-1]['date']}。")
    return problems, notes


def main():
    if len(sys.argv) != 2:
        print("用法：python3 validate.py 课表.json")
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            timetable = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"读不了这个文件：{error}")
        return 1
    problems, notes = check(timetable)
    for line in notes:
        print(f"提示  {line}")
    for line in problems:
        print(f"问题  {line}")
    print("通过" if not problems else f"未通过：{len(problems)} 处问题")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
