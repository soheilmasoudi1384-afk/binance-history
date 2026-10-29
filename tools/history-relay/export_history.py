#!/usr/bin/env python3
"""Binance PUBLIC kline relay, meant to run inside GitHub Actions (GitHub's runners are not
in Iran, so Binance's public market-data hosts answer them).

It keeps one gzip CSV per symbol/timeframe, e.g. BTCUSDT_1h.csv.gz (columns t,o,h,l,c,v,ct,
same layout as the project's own CSV cache) plus manifest.json, and only downloads candles
that are newer than what is already stored, so every run is small and fast.

Only the Python standard library is used. No API key, nothing secret.

  python3 export_history.py --out out --years 3
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT"]
TF_MS = {"1h": 3_600_000, "4h": 14_400_000}
YEAR_MS = int(365.25 * 86_400_000)


def http_json(url: str, params: dict):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{q}", headers={"User-Agent": "history-relay/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def get_klines(symbol: str, tf: str, start_ms: int, hosts=None) -> list:
    """One page (<= 1000 rows), trying every host, with retries and backoff."""
    last = None
    for attempt in range(5):
        for host in hosts or HOSTS:
            try:
                return http_json(host + "/api/v3/klines",
                                 {"symbol": symbol, "interval": tf, "startTime": start_ms, "limit": 1000})
            except urllib.error.HTTPError as e:
                last = f"{host}: HTTP {e.code}"
            except Exception as e:  # noqa: BLE001
                last = f"{host}: {type(e).__name__}: {e}"
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"{symbol} {tf}: {last}")


def fetch(symbol: str, tf: str, start_ms: int, now_ms: int, pager=get_klines) -> list:
    """Closed candles from start_ms up to now (the forming candle is dropped)."""
    out, start = [], start_ms
    while start < now_ms:
        rows = pager(symbol, tf, start)
        if not rows:
            break
        for k in rows:
            if k[6] < now_ms:
                out.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                            "c": float(k[4]), "v": float(k[5]), "ct": int(k[6])})
        start = int(rows[-1][6]) + 1
        if len(rows) < 1000:
            break
        time.sleep(0.1)
    return out


def read_csv_gz(path: str) -> list:
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return [{"t": int(r["t"]), "o": float(r["o"]), "h": float(r["h"]), "l": float(r["l"]),
                 "c": float(r["c"]), "v": float(r["v"]), "ct": int(r["ct"])} for r in csv.DictReader(fh)]


def write_csv_gz(path: str, candles: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["t", "o", "h", "l", "c", "v", "ct"])
    for c in candles:
        w.writerow([c["t"], repr(c["o"]), repr(c["h"]), repr(c["l"]), repr(c["c"]), repr(c["v"]), c["ct"]])
    raw = gzip.compress(buf.getvalue().encode("utf-8"), compresslevel=9, mtime=0)   # mtime=0: stable bytes
    with open(path, "wb") as fh:
        fh.write(raw)
    return hashlib.sha256(raw).hexdigest()


def merge(old: list, new: list) -> list:
    by_t = {c["t"]: c for c in old}
    by_t.update({c["t"]: c for c in new})           # newer download wins on overlap
    return [by_t[t] for t in sorted(by_t)]


def update_one(out_dir: str, symbol: str, tf: str, years: float, now_ms: int, pager=get_klines) -> dict:
    path = os.path.join(out_dir, f"{symbol}_{tf}.csv.gz")
    old = read_csv_gz(path)
    start = old[-1]["t"] + TF_MS[tf] if old else now_ms - int(years * YEAR_MS)
    new = fetch(symbol, tf, start, now_ms, pager)
    merged = merge(old, new)
    if not merged:
        raise RuntimeError(f"{symbol} {tf}: no candles at all")
    digest = write_csv_gz(path, merged)
    return {"rows": len(merged), "added": len(new), "first_t": merged[0]["t"], "last_t": merged[-1]["t"],
            "sha256": digest}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--tfs", default=",".join(TF_MS))
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    now_ms = int(time.time() * 1000)
    manifest, failed, ok = {}, [], []
    mpath = os.path.join(a.out, "manifest.json")
    if os.path.exists(mpath):
        try:
            manifest = json.load(open(mpath, encoding="utf-8")).get("files", {})
        except (OSError, ValueError):
            manifest = {}
    for symbol in [s.strip().upper() for s in a.symbols.split(",") if s.strip()]:
        for tf in [t.strip() for t in a.tfs.split(",") if t.strip()]:
            name = f"{symbol}_{tf}.csv.gz"
            try:
                info = update_one(a.out, symbol, tf, a.years, now_ms)
                manifest[name] = info
                ok.append(name)
                print(f"ok   {name}: {info['rows']} rows (+{info['added']})", flush=True)
            except Exception as e:  # noqa: BLE001
                failed.append(name)
                print(f"FAIL {name}: {e}", file=sys.stderr, flush=True)
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "source": "Binance public klines (data-api.binance.vision)", "files": manifest},
                  fh, indent=1, sort_keys=True)
    # partial failures keep the old file for that series; only total failure fails the job
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
