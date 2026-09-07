"""Telegram notifications; console only when no token is configured.

The token lives in .env, and until 2026-08-19 this module read it straight
from os.environ. Anything that fired before the first client was built ran
with an empty environment, so a bot refusing to start, a watchdog reviving
one, and every circuit-breaker warning went to a console nobody was
watching. The .env is loaded here instead, once, on first use.
"""

import os
import threading
import time

import requests

_env_loaded = False

# 09-07: the turn guard added on 09-06 calls send() on every unexpected
# error and sleeps five seconds, so one stuck condition rang the phone
# twelve times a minute until Telegram's own rate limit turned the calls
# into "[알림 실패]" lines.
#
# Folding is OPT-IN, not the default. The first draft folded everything and
# keyed on the text with digits masked, which would have silenced a warning
# whose number was getting worse: "손절 이탈 3%" and "손절 이탈 8%" keyed the
# same. An alert that goes quiet as the condition escalates is worse than a
# noisy phone. So the key is the exact text, and only the call site that was
# measured to repeat asks for the fold. The first one always goes out at
# once; repeats inside REPEAT_S are counted and reported with the next.
REPEAT_S = 900.0
_LOCK = threading.Lock()
_LAST: dict[str, tuple[float, int]] = {}


def _throttle(text: str) -> tuple[bool, int]:
    """(send it?, how many were folded in since the last one)."""
    key = text[:400]
    now = time.monotonic()
    with _LOCK:
        prev = _LAST.get(key)
        if prev is None or now - prev[0] >= REPEAT_S:
            _LAST[key] = (now, 0)
            # A process that runs for weeks must not grow a key per
            # distinct message; the oldest go first once it is large.
            if len(_LAST) > 500:
                for k, _v in sorted(_LAST.items(),
                                    key=lambda kv: kv[1][0])[:100]:
                    _LAST.pop(k, None)
            return True, 0 if prev is None else prev[1]
        _LAST[key] = (prev[0], prev[1] + 1)
        return False, 0


def _load_env_once() -> None:
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for cand in (os.environ.get("PACIFICA_ENV_FILE"),
                 os.path.join(os.path.expanduser("~"), ".ocean-agent", ".env"),
                 os.path.join(os.getcwd(), ".env"),
                 os.path.join(os.path.dirname(os.path.dirname(
                     os.path.abspath(__file__))), ".env")):
        if cand and os.path.exists(cand):
            load_dotenv(cand, override=False)
            break


def send(text: str, *, fold: bool = False) -> None:
    """Say it. Every call goes out unless the caller asks to fold repeats.

    `fold=True` is for a call site that fires on a loop while one condition
    persists: the first goes at once, then at most one per REPEAT_S, each
    carrying how many were folded in. The console keeps every line either
    way.
    """
    print(f"[알림] {text}")
    _load_env_once()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    body = text
    if fold:
        go, folded = _throttle(text)
        if not go:
            return                      # console still has every line
        if folded:
            body = f"{text}\n(같은 알림 {folded}건 묶임)"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": body},
            timeout=10,
        )
        # The warning path is the account's only voice now (the halt was
        # traded halts for warnings), so a silent delivery failure means no
        # protection at all. An expired token or wrong chat_id returns 4xx
        # with ok=false and no exception; say so instead of believing it.
        if r.status_code != 200 or not r.json().get("ok", False):
            print(f"[알림 실패] 텔레그램 응답 {r.status_code}: "
                  f"{r.text[:120]}")
    except (requests.RequestException, ValueError) as e:
        # The exception text can embed the request URL, which contains the
        # bot token. Redact it so logs never leak the credential.
        msg = str(e).replace(token, "***") if token else str(e)
        print(f"[알림 실패] {msg}")
