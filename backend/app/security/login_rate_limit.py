# ---------------------------------------------------------------------------
# Login throttling — Phase A P0. Deliberately the simplest thing that works:
# an in-process, in-memory sliding window, no new dependency (no slowapi, no
# Redis). This project's current deployment (Render, a single web process)
# has nothing shared to coordinate across, so there is nothing an
# in-process store would fail to see.
#
# LIMITATION (documented, not hidden): if this backend is ever scaled to
# more than one process/instance behind a load balancer, this store does NOT
# share state across them — each instance would enforce its own independent
# window, effectively multiplying the real limit by the instance count. That
# would need a shared store (e.g. Redis) at that point; not needed today.
#
# Two independent counters, keyed separately, either one can trigger a
# lockout:
#   - per-account (lowercased email): stops one account being brute-forced
#     from anywhere (many IPs).
#   - per-IP: stops one source spraying many different accounts.
# Both use the same sliding window; a successful login clears only the
# per-account counter for that email (an IP shared by many legitimate users,
# e.g. a campus NAT, should not have one person's successful login reset
# everyone else's failure count).
# ---------------------------------------------------------------------------

import threading
import time

_LOCK = threading.Lock()
_ACCOUNT_FAILURES: dict[str, list[float]] = {}
_IP_FAILURES: dict[str, list[float]] = {}

WINDOW_SECONDS = 15 * 60
MAX_ACCOUNT_ATTEMPTS = 5
MAX_IP_ATTEMPTS = 20


def _prune(timestamps: list[float], now: float) -> list[float]:
    return [t for t in timestamps if now - t < WINDOW_SECONDS]


def is_locked_out(*, email: str, ip: str) -> bool:
    now = time.time()
    with _LOCK:
        account_hits = _prune(_ACCOUNT_FAILURES.get(email, []), now)
        ip_hits = _prune(_IP_FAILURES.get(ip, []), now)
        _ACCOUNT_FAILURES[email] = account_hits
        _IP_FAILURES[ip] = ip_hits
        return len(account_hits) >= MAX_ACCOUNT_ATTEMPTS or len(ip_hits) >= MAX_IP_ATTEMPTS


def record_failure(*, email: str, ip: str) -> None:
    now = time.time()
    with _LOCK:
        _ACCOUNT_FAILURES.setdefault(email, [])
        _ACCOUNT_FAILURES[email] = _prune(_ACCOUNT_FAILURES[email], now)
        _ACCOUNT_FAILURES[email].append(now)

        _IP_FAILURES.setdefault(ip, [])
        _IP_FAILURES[ip] = _prune(_IP_FAILURES[ip], now)
        _IP_FAILURES[ip].append(now)


def reset_account(email: str) -> None:
    with _LOCK:
        _ACCOUNT_FAILURES.pop(email, None)
