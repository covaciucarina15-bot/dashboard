#!/usr/bin/env python3
"""Kishastreet: actualizare automată a datelor (rulează în GitHub Actions, doar biblioteca standard, fără chei API).
Scrie memecoins/ks/data.json = {"fred": {fetched, series}, "tlt": {fetched, source, symbol, closes}, "updated": ISO UTC}.
- FRED: CSV public fredgraph (aceleași serii ca kishastreet/fetch_fred.py).
- US Treasury Daily Par Yield Curve: completează DGS2/10/30 cu zilele mai noi decât FRED (dacă e coerent).
- TLT: Yahoo Finance chart API (închideri zilnice; bara zilei curente e scoasă cât timp piața e deschisă).
Dacă o sursă eșuează, se păstrează ultimele valori bune din data.json existent. Ieșire mereu cu cod 0."""
import csv, io, json, os, sys, time, datetime as dt, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
SERIES = ["DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30",
          "DFEDTARU", "T10Y2Y", "T10YIE", "PAYEMS", "UNRATE", "CPIAUCSL", "CPILFESL"]
TREAS_COLS = {"DGS2": "2 Yr", "DGS10": "10 Yr", "DGS30": "30 Yr"}
UTC = dt.timezone.utc
today = dt.datetime.now(UTC).date()
START = (today - dt.timedelta(days=760)).isoformat()

def log(*a): print(*a, file=sys.stderr, flush=True)

def get(url, ua=None, timeout=40, tries=3):
    # FRED blochează antetele de browser: pentru FRED se folosește User-Agent-ul implicit urllib.
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua} if ua else {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e; log("  retry", k + 1, url[:90], e); time.sleep(3 + 3 * k)
    raise RuntimeError(str(last))

try: prev = json.load(open(OUT, encoding="utf-8"))
except Exception: prev = {}
pfred = (prev.get("fred") or {}).get("series") or {}
ptlt = prev.get("tlt") or {}

now_utc = dt.datetime.now(UTC)
series, failed = {}, []
for s in SERIES:
    try:
        raw = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={s}&cosd={START}")
        if not (raw.startswith("observation_date") or raw.startswith("DATE")): raise RuntimeError("răspuns neașteptat")
        pts = [[d, round(float(v), 3)] for d, v in list(csv.reader(io.StringIO(raw)))[1:] if v not in ("", ".")]
        if not pts: raise RuntimeError("serie goală")
        # nu accepta o serie mai veche decât cea deja salvată
        old = pfred.get(s)
        if old and old[-1][0] > pts[-1][0]: raise RuntimeError("mai veche decât data.json")
        series[s] = pts; log(s, len(pts), pts[-1])
    except Exception as e:
        failed.append(s); log("FRED eșuat", s, e)
        if pfred.get(s): series[s] = pfred[s]

# --- Trezoreria SUA: zile mai noi decât FRED pentru DGS2/10/30
treas = {"status": "neîncercat"}
try:
    rows = []
    for y in sorted({today.year, (today - dt.timedelta(days=10)).year}):
        raw = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                  f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv", ua="Mozilla/5.0", tries=2)
        rows += list(csv.DictReader(io.StringIO(raw)))
    tv = {}
    for r in rows:
        try:
            m, d, y = r["Date"].split("/"); day = f"{y}-{int(m):02d}-{int(d):02d}"
            vals = {k: float(r[c]) for k, c in TREAS_COLS.items()}
            if all(0 < v < 25 for v in vals.values()): tv[day] = vals
        except Exception: pass
    if not tv: raise RuntimeError("niciun rând valid")
    added = []
    if all(series.get(k) for k in TREAS_COLS):
        last = min(series[k][-1][0] for k in TREAS_COLS)
        # coerență: în zilele comune, Treasury și FRED trebuie să coincidă (FRED preia aceleași cifre)
        common = [d for d in tv if all(d in dict(series[k]) for k in TREAS_COLS)]
        bad = [d for d in common[-10:] if any(abs(dict(series[k])[d] - tv[d][k]) > 0.02 for k in TREAS_COLS)]
        if bad: raise RuntimeError(f"nepotrivire cu FRED în {len(bad)} zile, nu adaug")
        for day in sorted(d for d in tv if d > last):
            for k in TREAS_COLS:
                if series[k][-1][0] < day:
                    if abs(tv[day][k] - series[k][-1][1]) > 0.75: raise RuntimeError(f"salt suspect {k} {day}")
                    series[k].append([day, round(tv[day][k], 3)])
            added.append(day)
    treas = {"status": "ok", "latest": max(tv), "added": added}
    log("Treasury ok, ultima zi", max(tv), "adăugat", added)
except Exception as e:
    treas = {"status": "eșuat", "error": str(e)[:200]}; log("Treasury eșuat (ignorat):", e)

# --- TLT (Yahoo Finance)
tlt = ptlt if ptlt.get("closes") else None
try:
    r = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/TLT?range=2y&interval=1d", ua="Mozilla/5.0"))["chart"]["result"][0]
    meta = r["meta"]; off = meta.get("gmtoffset", -18000)
    end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end", 0)
    rows = [[dt.datetime.fromtimestamp(t + off, UTC).strftime("%Y-%m-%d"), round(c, 2), t]
            for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c is not None]
    if rows and rows[-1][2] >= end - 86400 and time.time() < end: rows.pop()  # bară intraday
    rows = [x[:2] for x in rows]
    if not rows: raise RuntimeError("fără închideri")
    if tlt and tlt["closes"][-1][0] > rows[-1][0]: raise RuntimeError("mai veche decât data.json")
    tlt = {"fetched": now_utc.isoformat(timespec="seconds"), "source": "Yahoo Finance", "symbol": "TLT", "closes": rows}
    log("TLT", len(rows), rows[-1])
except Exception as e:
    failed.append("TLT"); log("TLT eșuat", e)

if not series and not tlt:
    log("nimic descărcat și nimic salvat: nu scriu data.json"); sys.exit(0)

def strip(o):  # câmpurile de timp nu intră în comparație (commit doar dacă datele s-au schimbat)
    return {"fred": {"series": (o.get("fred") or {}).get("series")}, "tlt": {k: v for k, v in (o.get("tlt") or {}).items() if k != "fetched"}}
new = {"fred": {"fetched": now_utc.strftime("%Y-%m-%d %H:%M"), "series": series}, "tlt": tlt or {}, "updated": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")}
if prev and strip(prev) == strip(new):
    log("date neschimbate: nu rescriu data.json"); sys.exit(0)
new["status"] = {"failed": failed, "treasury": treas}
with open(OUT, "w", encoding="utf-8") as f: json.dump(new, f, separators=(",", ":"), ensure_ascii=False)
log("scris", OUT, "eșuate:", failed or "niciuna")
sys.exit(0)
