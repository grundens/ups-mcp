"""In-memory TTL cache for UPS responses.

Why this exists: every operator with the plugin authenticates as the same UPS
application, so they share one rate limit. Repeated lookups of the same package
during a triage session are pure waste, and the waste is charged to everyone.

Why the TTL varies by result rather than being a single number: a delivered
package is finished. Its tracking history will never change again, so caching it
for minutes is needlessly timid. A package in transit changes through the day. A
label with no scans yet will change shortly, so caching it at all risks a stale
"not found" outliving the truth.

Deliberately in-memory only. A disk cache would survive restarts, but tracking
responses can carry delivery detail and signature data, and a cache file is a
place for that to sit unmanaged. Process lifetime is enough to cover a working
session, which is where the repetition actually happens.
"""
import json
import os
import threading
import time

# Seconds. Override with UPS_CACHE_TTL_* env vars; set UPS_CACHE_TTL=0 to disable
# caching entirely.
TTL_TERMINAL = int(os.getenv("UPS_CACHE_TTL_TERMINAL", 86400))   # delivered: a day
TTL_IN_TRANSIT = int(os.getenv("UPS_CACHE_TTL_TRANSIT", 900))    # moving: 15 min
TTL_NOT_FOUND = int(os.getenv("UPS_CACHE_TTL_NOTFOUND", 60))     # no scans yet: 1 min
TTL_ADDRESS = int(os.getenv("UPS_CACHE_TTL_ADDRESS", 86400))     # USPS data: a day

_DISABLED = os.getenv("UPS_CACHE_TTL") == "0"

# UPS status codes that mean the package is done moving.
_TERMINAL_STATUS_CODES = {"011"}          # Delivered
_TERMINAL_STATUS_TYPES = {"D"}            # D = Delivered


class _TTLCache:
    def __init__(self, max_entries=512):
        self._data = {}
        self._lock = threading.Lock()
        self._max = max_entries
        self.hits = 0
        self.misses = 0

    def get(self, key):
        if _DISABLED:
            return None
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, expires_at = entry
            if time.time() >= expires_at:
                del self._data[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def put(self, key, value, ttl):
        if _DISABLED or ttl <= 0:
            return
        with self._lock:
            if len(self._data) >= self._max:
                # Cheap eviction: drop whatever expires soonest. Not LRU, but the
                # working set here is small and this avoids tracking access order.
                soonest = min(self._data, key=lambda k: self._data[k][1])
                del self._data[soonest]
            self._data[key] = (value, time.time() + ttl)

    def stats(self):
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}


responses = _TTLCache()


def key(*parts):
    return "|".join(str(p) for p in parts)


def tracking_ttl(raw_response):
    """Pick a TTL by reading what UPS actually said.

    Delivered -> long. Not-found -> very short. Anything else -> in-transit.
    """
    try:
        shipments = json.loads(raw_response)["trackResponse"]["shipment"]
    except (ValueError, KeyError, TypeError):
        return TTL_IN_TRANSIT

    saw_package = False
    all_terminal = True

    for shipment in shipments:
        if shipment.get("warnings") and not shipment.get("package"):
            # TW0001 "Tracking Information Not Found": a label exists but UPS has
            # not scanned it. This flips as soon as the package is collected, so
            # holding it would make us report a stale negative.
            return TTL_NOT_FOUND
        for package in shipment.get("package", []):
            saw_package = True
            status = package.get("currentStatus", {})
            if (status.get("statusCode") not in _TERMINAL_STATUS_CODES
                    and status.get("type") not in _TERMINAL_STATUS_TYPES):
                all_terminal = False

    if not saw_package:
        return TTL_NOT_FOUND
    return TTL_TERMINAL if all_terminal else TTL_IN_TRANSIT
