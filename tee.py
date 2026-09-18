# -*- coding: utf-8 -*-
"""Bot status panel on screen, the whole stream to the file.

The console window is where the operator watches the bot, and the file is
what remains when that window is gone. PowerShell's Tee-Object cannot do
the second half here: on Windows PowerShell 5.1 it writes UTF-16 and offers
no encoding switch, so every Korean line lands as mojibake.

2026-09-18, user instruction: "터미널에 봇 현황만 띄워". The stream scrolled
about twelve hundred lines a day and redrew the seat table whole every
cycle, which made the window shake. Now the screen holds one panel that is
rewritten in place: the seats, the last few things that actually happened,
and the clock of the last line seen. Everything -- every skipped symbol,
every retry, every wake-up -- still goes to the file, which is what the
analysis reads.

`--all` (or OA_TEE_ALL=1) turns the panel off and streams as before.
"""
import io
import os
import re
import sys
import time

# 화면의 '무슨 일이 있었나' 칸에 남길 것. 나머지는 파일에만 간다.
EVENTS = (
    "진입", "체결", "청산", "손절", "익절", "트레일", "만기",
    "접으라", "역전", "⚠️", "실패", "오류", "정지", "halt",
    "BTC 방향", "평평해서", "잔고", "강제",
)
KEEP = 8                       # 사건은 최근 몇 줄까지
BLOCK_HEAD = "모드] 보유"


def main() -> int:
    if len(sys.argv) < 2:
        print("사용법: python tee.py <로그파일> [--all]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    show_all = "--all" in sys.argv[2:] or os.environ.get("OA_TEE_ALL") == "1"
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8",
                             errors="replace")
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                           errors="replace")
    seats: list[str] = []
    events: list[str] = []
    block: list[str] = []
    in_block = False
    n_lines = 0
    last_stamp = ""
    last_draw = 0.0

    def draw():
        # 커서를 맨 위로 보내고 지운다. 스크롤이 없으니 흔들리지 않는다.
        out.write("[H[2J")
        head = seats[0] if seats else ""
        m2 = re.search(r"보유\s*(\d+)\s*·\s*청산 누적\s*(\d+)", head)
        held = m2.group(1) if m2 else "?"
        done = m2.group(2) if m2 else "?"
        # 자리는 종목과 방향만. 익절·손절 값은 파일에 있다 (09-18 지시).
        names = []
        for ln in seats[1:]:
            mm = re.match(r"\s*(\S+)\s+(long|short)", ln)
            if mm:
                names.append("%s %s" % (mm.group(1),
                                        "롱" if mm.group(2) == "long" else "숏"))
        tail = seats[-1].strip() if len(seats) > 1 else ""
        score = tail if tail.startswith("전략") else ""
        print("  브래킷 트레이더 · %s" % (last_stamp or "..."), file=out)
        print("  " + "-" * 66, file=out)
        print("  자리 %s개 · 청산 누적 %s건" % (held, done), file=out)
        print("  %s" % (" · ".join(names) if names else "(비어 있음)"),
              file=out)
        if score:
            print("  %s" % score[:68], file=out)
        print("  " + "-" * 66, file=out)
        for e in events[-KEEP:]:
            print("  " + e.rstrip()[:70], file=out)
        for _ in range(KEEP - len(events[-KEEP:])):
            print("", file=out)
        print("  " + "-" * 66, file=out)
        print("  로그 %d줄 -> %s   (전부 보려면 OA_TEE_ALL=1)"
              % (n_lines, os.path.basename(path)), file=out)
        out.flush()

    with open(path, "a", encoding="utf-8", errors="replace") as f:
        for line in stdin:
            f.write(line)                  # 파일에는 무조건 다 적는다
            f.flush()
            n_lines += 1
            if show_all:
                out.write(line)
                out.flush()
                continue
            # 시각은 [09-18 10:00:00] 모양만. [base 모드] 는 시각이 아니다.
            m = re.match(r"^\[(\d\d-\d\d[^\]]*)\]", line)
            if m:
                last_stamp = m.group(1)
            # 덩어리는 **원문**으로 알아본다. 머리를 떼면 못 알아본다.
            raw = line.rstrip()
            if BLOCK_HEAD in raw and not line.startswith(" "):
                block, in_block = [raw], True
                continue
            if in_block:
                if line.startswith(" "):
                    block.append(raw)
                    continue
                in_block = False
                seats = list(block)
                block = []
                draw()
                last_draw = time.time()
            body = re.sub(r"^\[[^\]]*\]\s*", "", line).rstrip()
            if body and any(k in body for k in EVENTS):
                stamp = (last_stamp[-8:] if last_stamp else "")
                if not events or events[-1] != body:
                    events.append("%s  %s" % (stamp, body))
                    draw()
                    last_draw = time.time()
            elif time.time() - last_draw > 20:
                draw()                      # 살아 있다는 표시
                last_draw = time.time()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
