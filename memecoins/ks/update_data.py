#!/usr/bin/env python3
"""Kishastreet: actualizare automată a datelor (rulează în GitHub Actions, doar biblioteca standard, fără chei API).
Scrie memecoins/ks/data.json = {"fred": {fetched, series}, "tlt": {...}, "fc": {cpi, core, unrate, nfp, fed}, "updated": ISO UTC}.
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
        if old and old[-1][0] > pts[-1][0]:
            if s in TREAS_COLS: pts += [p for p in old if p[0] > pts[-1][0]]  # zile deja preluate de la Trezorerie
            else: raise RuntimeError("mai veche decât data.json")
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


# --- Forecast (consens) pentru următoarea publicare: Trading Economics (Consensus, apoi TEForecast), ForexFactory (săptămâna curentă), Kalshi (decizia Fed)
# Nicio valoare inventată: doar ce apare publicat. Se păstrează ultima valoare bună doar pentru aceeași publicare viitoare.
import html as _html, re as _re
CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
MONRO = ['ian','feb','mar','apr','mai','iun','iul','aug','sep','oct','nov','dec']
MONEN = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
def num(s):
    m = _re.search(r'-?\d+(?:\.\d+)?', (s or '').replace(',', ''))
    if not m: return None
    v = float(m.group(0))
    if s.strip().upper().endswith('M'): v *= 1000  # NFP în milioane -> mii
    return v
pfc = prev.get("fc") or {}
fc = {}
TE = {"cpi": ("inflation-cpi", "Inflation Rate YoY", "CPI y/y"), "core": ("core-inflation-rate", "Core Inflation Rate YoY", None),
      "unrate": ("unemployment-rate", "Unemployment Rate", "Unemployment Rate"), "nfp": ("non-farm-payrolls", "Non Farm Payrolls", "Non-Farm Employment Change")}
ff = []
try: ff = [e for e in json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", ua=CHROME, tries=2)) if e.get("country") == "USD"]
except Exception as e: log("ForexFactory eșuat (ignorat):", e)
for key, (slug, name, ffname) in TE.items():
    nxt = None
    try:
        page = get(f"https://tradingeconomics.com/united-states/{slug}", ua=CHROME, tries=2)
        tab = _re.search(r"<table[^>]*>.*?Consensus.*?</table>", page, _re.S).group(0)
        for r in _re.findall(r"<tr.*?</tr>", tab, _re.S):
            c = [_re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", "", x))).strip() for x in _re.findall(r"<td[^>]*>(.*?)</td>", r, _re.S)]
            if len(c) >= 8 and c[2] == name and c[0] >= today.isoformat() and not c[4]:
                nxt = c; break
    except Exception as e: log("Trading Economics eșuat", key, e)
    item = None
    if nxt:
        ref = nxt[3]; mi = MONEN.index(ref) + 1 if ref in MONEN else None
        y = int(nxt[0][:4]) - (1 if mi and mi > int(nxt[0][5:7]) else 0)
        item = {"date": nxt[0], "for": (MONRO[mi - 1] + ' ' + str(y)) if mi else ref, "value": None, "src": None}
        if num(nxt[6]) is not None: item.update(value=num(nxt[6]), src="Trading Economics (consens)")
        if item["value"] is None and ffname:
            for e in ff:
                if e.get("title") == ffname and e.get("date", "")[:10] == nxt[0] and num(e.get("forecast")) is not None:
                    item.update(value=num(e["forecast"]), src="ForexFactory (consens)"); break
        if item["value"] is None and num(nxt[7]) is not None: item.update(value=num(nxt[7]), src="Trading Economics (prognoză TE)")
    old = pfc.get(key)
    if old and old.get("value") is not None and old.get("date", "") >= today.isoformat() and (not item or (item["date"] == old["date"] and item["value"] is None)):
        item = old  # ultima valoare bună pentru aceeași publicare
    if item: fc[key] = item
    log("forecast", key, item)
# Fed: piața Kalshi (public, fără cheie), cea mai probabilă decizie la următoarea ședință
try:
    ev = json.loads(get("https://api.elections.kalshi.com/trade-api/v2/events?series_ticker=KXFEDDECISION&status=open&with_nested_markets=true", ua=CHROME, tries=2))["events"]
    best = None
    for e in ev:
        ms = [m for m in e.get("markets", []) if m.get("status") == "active"]
        if not ms: continue
        cl = min(m["close_time"] for m in ms)
        if cl < now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"): continue
        if best is None or cl < best[0]: best = (cl, ms)
    if not best: raise RuntimeError("nicio piață deschisă")
    def pr(m):
        b, a = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
        return (b + a) / 2 if b > 0 and a > 0 else float(m.get("last_price_dollars") or 0)
    top = max(best[1], key=pr)
    cs = top.get("custom_strike") or {}
    kind, bp = next(iter(cs.items()))
    if bp.startswith(">"): raise RuntimeError("cel mai probabil e o mișcare > 25 pb (fără valoare exactă)")
    mv = (1 if kind == "Hike" else -1) * int(bp) / 100
    cur = series["DFEDTARU"][-1][1] if series.get("DFEDTARU") else None
    d = best[0][:10]
    fc["fed"] = {"date": d, "for": f"{int(d[8:])} {MONRO[int(d[5:7]) - 1]} {d[:4]}", "move": mv, "prob": round(pr(top), 2),
                 "value": round(cur + mv, 2) if cur is not None else None, "src": "Kalshi (piața de predicție)"}
    log("forecast fed", fc["fed"])
except Exception as e:
    log("Kalshi eșuat (păstrez ultima valoare):", e)
    old = pfc.get("fed")
    if old and old.get("date", "") >= today.isoformat(): fc["fed"] = old

if not series and not tlt:
    log("nimic descărcat și nimic salvat: nu scriu data.json"); sys.exit(0)

def strip(o):  # câmpurile de timp nu intră în comparație (commit doar dacă datele s-au schimbat)
    return {"fc": o.get("fc"), "fred": {"series": (o.get("fred") or {}).get("series")}, "tlt": {k: v for k, v in (o.get("tlt") or {}).items() if k != "fetched"}}
new = {"fred": {"fetched": now_utc.strftime("%Y-%m-%d %H:%M"), "series": series}, "tlt": tlt or {}, "fc": fc, "updated": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")}
if prev and strip(prev) == strip(new):
    log("date neschimbate: nu rescriu data.json"); sys.exit(0)
new["status"] = {"failed": failed, "treasury": treas}
with open(OUT, "w", encoding="utf-8") as f: json.dump(new, f, separators=(",", ":"), ensure_ascii=False)
log("scris", OUT, "eșuate:", failed or "niciuna")
sys.exit(0)
