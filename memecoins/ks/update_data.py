#!/usr/bin/env python3
"""Kishastreet: actualizare automată a datelor (rulează în GitHub Actions, doar biblioteca standard, fără chei API).
Scrie memecoins/ks/data.json = {"fred": {fetched, series}, "tlt": {...}, "fc": {cpi, core, unrate, nfp, fed}, "mk": {materii prime Yahoo}, "fx": {forex și indici Yahoo}, "updated": ISO UTC}.
- FRED: CSV public fredgraph (aceleași serii ca kishastreet/fetch_fred.py).
- US Treasury Daily Par Yield Curve: completează DGS2/10/30 cu zilele mai noi decât FRED (dacă e coerent).
- TLT: Yahoo Finance chart API (închideri zilnice; bara zilei curente e scoasă cât timp piața e deschisă).
- Materii prime (mk): Yahoo Finance futures GC=F, SI=F, CL=F, BZ=F, PL=F, PA=F, HG=F (preț + închiderea anterioară).
- Forex și indici (fx): Yahoo Finance ^VIX, DX-Y.NYB, ^NDX, ^GSPC, EURUSD=X, GBPJPY=X, GBPUSD=X, ^GDAXI, ^N225 (preț + închiderea anterioară).
- Crypto (cr): BTC/ETH/SOL Binance 24h (rezervă TradingView), BTC.D/ETH.D/USDT.D/TOTAL/TOTAL2/TOTAL3/IBIT/ETHA din scanner-ul TradingView
  (rezervă CoinGecko /global), volum 24h CoinGecko /global, Fear & Greed alternative.me (30 de zile), Altcoin Season calculat (vezi alt_season).
Dacă o sursă eșuează, se păstrează ultimele valori bune din data.json existent. Ieșire mereu cu cod 0."""
import csv, io, json, os, sys, time, datetime as dt, urllib.request, urllib.parse, http.cookiejar

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
MONEN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]  # etichete fc afișate pe pagină (EN)
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
        item = {"date": nxt[0], "for": (MONEN[mi - 1] + ' ' + str(y)) if mi else ref, "value": None, "src": None}
        if num(nxt[6]) is not None: item.update(value=num(nxt[6]), src="Trading Economics (consens)")
        if item["value"] is None and ffname:
            for e in ff:
                if e.get("title") == ffname and e.get("date", "")[:10] == nxt[0] and num(e.get("forecast")) is not None:
                    item.update(value=num(e["forecast"]), src="ForexFactory (consens)"); break
        if item["value"] is None and num(nxt[7]) is not None: item.update(value=num(nxt[7]), src="Trading Economics (TE forecast)")
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
    fc["fed"] = {"date": d, "for": f"{MONEN[int(d[5:7]) - 1]} {int(d[8:])}, {d[:4]}", "move": mv, "prob": round(pr(top), 2),
                 "value": round(cur + mv, 2) if cur is not None else None, "src": "Kalshi (prediction market)"}
    log("forecast fed", fc["fed"])
except Exception as e:
    log("Kalshi eșuat (păstrez ultima valoare):", e)
    old = pfc.get("fed")
    if old and old.get("date", "") >= today.isoformat(): fc["fed"] = old

# --- Materii prime (Yahoo Finance futures)
# GC=F aur, SI=F argint, CL=F WTI, BZ=F Brent, PL=F platină, PA=F paladiu, HG=F cupru
MK_Y = [("gold","GC=F",2),("silver","SI=F",3),("wti","CL=F",2),("brent","BZ=F",2),("plat","PL=F",2),("pall","PA=F",2),("copper","HG=F",4)]
FX_Y = [("vix","^VIX",2),("dxy","DX-Y.NYB",2),("nas100","^NDX",2),("sp500","^GSPC",2),("eurusd","EURUSD=X",5),("gbpjpy","GBPJPY=X",3),("gbpusd","GBPUSD=X",5),("dax","^GDAXI",2),("nikkei","^N225",2)]
pmk = (prev.get("mk") or {}).get("items") or {}
pfx_prev = (prev.get("fx") or {}).get("items") or {}
_yahoo_opener = None
_yahoo_crumb = None
def yahoo_body(url):
    """Yahoo poate răspunde 429 fără cookie; atunci folosim crumb + cookie de la fc.yahoo.com."""
    global _yahoo_opener, _yahoo_crumb
    try:
        return get(url, ua="Mozilla/5.0")
    except Exception as e1:
        if _yahoo_opener is None:
            cj = http.cookiejar.CookieJar()
            _yahoo_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
            try:
                _yahoo_opener.open(urllib.request.Request("https://fc.yahoo.com/", headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read()
            except Exception as e:
                log("yahoo cookie:", e)
            try:
                _yahoo_crumb = _yahoo_opener.open(urllib.request.Request("https://query1.finance.yahoo.com/v1/test/getcrumb", headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
            except Exception as e:
                _yahoo_crumb = ""
                log("yahoo crumb:", e)
            if not _yahoo_crumb or "Unauthorized" in _yahoo_crumb or len(_yahoo_crumb) > 80:
                raise RuntimeError(f"yahoo 429 și crumb invalid ({e1}); crumb={(_yahoo_crumb or '')[:80]}")
        sep = "&" if "?" in url else "?"
        req = urllib.request.Request(url + sep + "crumb=" + urllib.parse.quote(_yahoo_crumb), headers={"User-Agent": "Mozilla/5.0"})
        with _yahoo_opener.open(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")

def yahoo_quotes(pairs, prev_items, tag):
    items, failed = {}, []
    for key, sym, dp in pairs:
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym, safe="") + "?range=5d&interval=1d"
            r = json.loads(yahoo_body(url))["chart"]["result"][0]
            meta = r["meta"]
            off = meta.get("gmtoffset", 0)
            px = meta.get("regularMarketPrice")
            if px is None: px = meta.get("fulldayPrice")
            ch = meta.get("fulldayChange")
            chp = meta.get("fulldayChangePercent")
            if chp is None: chp = meta.get("regularMarketChangePercent")
            if px is None:
                raise RuntimeError("fără preț")
            if ch is None and chp is not None:
                prev_px = px / (1 + chp / 100.0) if chp != -100 else None
                ch = (px - prev_px) if prev_px is not None else None
            if chp is None and ch is not None and (px - ch) != 0:
                chp = 100.0 * ch / (px - ch)
            if ch is None or chp is None:
                # rezervă: ultimele două închideri zilnice
                rows = []
                for ts, c in zip(r.get("timestamp") or [], (r.get("indicators") or {}).get("quote", [{}])[0].get("close") or []):
                    if c is None: continue
                    rows.append((dt.datetime.fromtimestamp(ts + off, UTC).strftime("%Y-%m-%d"), c))
                rmt = meta.get("regularMarketTime")
                last_d = dt.datetime.fromtimestamp(rmt + off, UTC).strftime("%Y-%m-%d") if rmt else (rows[-1][0] if rows else None)
                prev_px = None
                for d, c in reversed(rows):
                    if last_d and d < last_d:
                        prev_px = c; break
                if prev_px is None and len(rows) >= 2: prev_px = rows[-2][1]
                if prev_px is None: raise RuntimeError("fără închiderea anterioară")
                ch = px - prev_px
                chp = 100.0 * ch / prev_px if prev_px else None
            prev_px = px - ch if ch is not None else None
            rmt = meta.get("regularMarketTime")
            day = dt.datetime.fromtimestamp(rmt + off, UTC).strftime("%Y-%m-%d") if rmt else None
            item = {"sym": sym, "px": round(float(px), dp), "prev": round(float(prev_px), dp) if prev_px is not None else None,
                    "chg": round(float(ch), dp), "chp": round(float(chp), 3), "date": day}
            items[key] = item
            log(tag, key, item)
        except Exception as e:
            failed.append(sym); log(tag + " eșuat", sym, e)
            if prev_items.get(key) and prev_items[key].get("px") is not None:
                items[key] = prev_items[key]
    return items, failed

mk_items, mk_failed = yahoo_quotes(MK_Y, pmk, "mk")
if mk_failed:
    failed.extend(mk_failed)
mk = {"fetched": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"), "source": "Yahoo Finance", "items": mk_items} if mk_items else (prev.get("mk") or {})
fx_items, fx_failed = yahoo_quotes(FX_Y, pfx_prev, "fx")
if fx_failed:
    failed.extend(fx_failed)
fx = {"fetched": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"), "source": "Yahoo Finance", "items": fx_items} if fx_items else (prev.get("fx") or {})

# --- Crypto (cr): TradingView scanner (CRYPTOCAP, ETF-uri), Binance (BTC/ETH/SOL 24h), CoinGecko /global (volum 24h),
#     alternative.me (Fear & Greed, 30 zile) și Altcoin Season calculat aici (vezi alt_season). Fiecare valoare eșuată păstrează ultima valoare bună.
def cr_update(prev_cr):
    pitems = (prev_cr or {}).get("items") or {}
    items, src_fail = {}, []
    def jget(url, tries=2):
        return json.loads(get(url, ua="Mozilla/5.0", timeout=25, tries=tries))
    def tv(sym):
        j = jget("https://scanner.tradingview.com/symbol?symbol=" + urllib.parse.quote(sym) + "&fields=close,change,change_abs,volume")
        if j.get("close") is None: raise RuntimeError("fără close")
        px, chp, ch = float(j["close"]), j.get("change"), j.get("change_abs")
        if ch is None and chp is not None: ch = px - px / (1 + chp / 100)
        return {"px": px, "chg": ch, "chp": chp, "src": "TradingView " + sym}
    # Binance: variație pe 24 h glisante
    try:
        l = jget("https://data-api.binance.vision/api/v3/ticker/24hr?symbols=" + urllib.parse.quote('["BTCUSDT","ETHUSDT","SOLUSDT"]'))
        for t in l:
            k = {"BTCUSDT": "btc", "ETHUSDT": "eth", "SOLUSDT": "sol"}.get(t.get("symbol"))
            if k: items[k] = {"px": float(t["lastPrice"]), "chg": float(t["priceChange"]), "chp": float(t["priceChangePercent"]), "src": "Binance " + t["symbol"]}
    except Exception as e: log("cr Binance eșuat", e)
    TVS = {"btc": "CRYPTO:BTCUSD", "eth": "CRYPTO:ETHUSD", "sol": "CRYPTO:SOLUSD", "btcd": "CRYPTOCAP:BTC.D", "ethd": "CRYPTOCAP:ETH.D", "usdtd": "CRYPTOCAP:USDT.D",
           "total": "CRYPTOCAP:TOTAL", "total2": "CRYPTOCAP:TOTAL2", "total3": "CRYPTOCAP:TOTAL3", "ibit": "NASDAQ:IBIT", "etha": "NASDAQ:ETHA"}
    for k, sym in TVS.items():
        if k in items: continue
        try: items[k] = tv(sym)
        except Exception as e: log("cr TV eșuat", sym, e)
        time.sleep(0.3)
    # CoinGecko /global: volum 24h + rezervă pentru capitalizare și dominanțe
    try:
        g = jget("https://api.coingecko.com/api/v3/global")["data"]
        tm, pc = g["total_market_cap"]["usd"], g.get("market_cap_percentage") or {}
        items["vol"] = {"px": g["total_volume"]["usd"], "chg": None, "chp": None, "src": "CoinGecko /global"}
        cg = {"total": (tm, g.get("market_cap_change_percentage_24h_usd")), "btcd": (pc.get("btc"), None), "ethd": (pc.get("eth"), None), "usdtd": (pc.get("usdt"), None)}
        if pc.get("btc") is not None: cg["total2"] = (tm * (1 - pc["btc"] / 100), None)
        if pc.get("btc") is not None and pc.get("eth") is not None: cg["total3"] = (tm * (1 - (pc["btc"] + pc["eth"]) / 100), None)
        for k, (v, chp) in cg.items():
            if k not in items and v is not None: items[k] = {"px": v, "chg": None, "chp": chp, "src": "CoinGecko /global"}
    except Exception as e: log("cr CoinGecko global eșuat", e)
    for k in list(TVS) + ["vol"]:
        if k not in items:
            src_fail.append(k)
            if pitems.get(k): items[k] = pitems[k]
    out = {"fetched": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"), "items": items, "failed": src_fail}
    # Fear & Greed (30 de zile)
    try:
        d = jget("https://api.alternative.me/fng/?limit=30").get("data") or []
        hist = [[dt.datetime.fromtimestamp(int(x["timestamp"]), UTC).strftime("%Y-%m-%d"), int(x["value"])] for x in d][::-1]
        out["fng"] = {"v": int(d[0]["value"]), "cls": d[0].get("value_classification"), "date": hist[-1][0], "hist": hist, "src": "alternative.me"}
    except Exception as e:
        log("cr F&G eșuat", e)
        if (prev_cr or {}).get("fng"): out["fng"] = prev_cr["fng"]
    try: out["alt"] = alt_season()
    except Exception as e:
        log("cr Altcoin Season eșuat", e)
        if (prev_cr or {}).get("alt"): out["alt"] = prev_cr["alt"]
    return out

STABLE = set("usdt usdc usde dai fdusd usds pyusd usd1 tusd busd rlusd usdg susde usdd usdx usdb frax lusd gusd eurc eure usdtb usdf usd0 bfusd usdai usdp buidl ustb ousg xaut paxg u usyc gho".split())  # + tokeni pe aur / fonduri de trezorerie
WRAP = set("wbtc weth steth wsteth cbbtc weeth reth ezeth meth rseth lbtc solvbtc tbtc cbeth bnsol jitosol msol bsol wbnb wsteth wbeth sweth oseth btcb fbtc clbtc susds sdai".split())
def alt_season(n_want=50, days=90, hist_days=30):
    """Metoda Blockchaincenter: din primele 50 de monede (fără stablecoins și tokeni wrapped/staked, fără BTC), câte au crescut
    mai mult decât BTC în ultimele 90 de zile, în procente (0–100). ≥ 75 = Altcoin season, ≤ 25 = Bitcoin season.
    Lista: CoinGecko /coins/markets (top 150 după mcap, azi); prețuri: închideri zilnice Binance (perechi USDT), deci monedele fără
    pereche USDT pe Binance sau cu sub 91 de zile de istoric sunt sărite și se trece la următoarea. Istoricul pe 30 de zile folosește aceeași listă de azi."""
    mk = json.loads(get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=150&page=1", ua="Mozilla/5.0", timeout=30, tries=2))
    pairs = {t["symbol"] for t in json.loads(get("https://data-api.binance.vision/api/v3/ticker/price", ua="Mozilla/5.0", timeout=30, tries=2))}
    def kl(sym):
        if sym + "USDT" not in pairs: raise RuntimeError("fără pereche USDT pe Binance")
        j = json.loads(get(f"https://data-api.binance.vision/api/v3/klines?symbol={sym}USDT&interval=1d&limit={days + hist_days + 2}", ua="Mozilla/5.0", timeout=20, tries=2))
        return [(dt.datetime.fromtimestamp(k[0] / 1000, UTC).strftime("%Y-%m-%d"), float(k[4])) for k in j]
    btc = kl("BTC")
    if len(btc) < days + hist_days: raise RuntimeError("istoric BTC prea scurt")
    dates = [d for d, _ in btc]
    coins, skipped = [], []
    for c in mk:
        s = (c.get("symbol") or "").lower(); cid = c.get("id") or ""
        if s in STABLE or s in WRAP or s == "btc" or "usd" in s or any(w in cid for w in ("wrapped", "staked", "bridged", "-peg", "tokenized")): continue
        try:
            k = dict(kl(s.upper()))
            if sum(1 for d in dates if d in k) < days + 1: raise RuntimeError("istoric scurt")
            coins.append((s.upper(), k))
        except Exception:
            skipped.append(s.upper())
        if len(coins) >= n_want: break
        time.sleep(0.1)
    if len(coins) < 30: raise RuntimeError(f"doar {len(coins)} monede eligibile")
    bc = dict(btc); hist = []
    for i in range(len(dates) - hist_days, len(dates)):
        d, d0 = dates[i], dates[i - days]
        rb = bc[d] / bc[d0] - 1
        el = [(k[d] / k[d0] - 1) for _, k in coins if d in k and d0 in k]
        if len(el) >= 30: hist.append([d, round(100 * sum(1 for r in el if r > rb) / len(el))])
    if not hist: raise RuntimeError("istoric gol")
    return {"v": hist[-1][1], "date": hist[-1][0], "hist": hist, "n": len(coins), "coins": [s for s, _ in coins], "skipped": skipped[:40],
            "method": "top 50 CoinGecko excluding stablecoins/wrapped, 90-day return vs BTC (Binance daily closes)", "src": "computed (CoinGecko + Binance)"}

cr = cr_update(prev.get("cr"))

if not series and not tlt:
    log("nimic descărcat și nimic salvat: nu scriu data.json"); sys.exit(0)

def strip(o):  # câmpurile de timp nu intră în comparație (commit doar dacă datele s-au schimbat)
    return {"fc": o.get("fc"), "fred": {"series": (o.get("fred") or {}).get("series")}, "tlt": {k: v for k, v in (o.get("tlt") or {}).items() if k != "fetched"}, "mk": {k: v for k, v in (o.get("mk") or {}).items() if k != "fetched"}, "fx": {k: v for k, v in (o.get("fx") or {}).items() if k != "fetched"}, "cr": {k: v for k, v in (o.get("cr") or {}).items() if k != "fetched"}}
new = {"fred": {"fetched": now_utc.strftime("%Y-%m-%d %H:%M"), "series": series}, "tlt": tlt or {}, "fc": fc, "mk": mk, "fx": fx, "cr": cr, "updated": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z")}
if prev and strip(prev) == strip(new):
    log("date neschimbate: nu rescriu data.json"); sys.exit(0)
new["status"] = {"failed": failed, "treasury": treas}
with open(OUT, "w", encoding="utf-8") as f: json.dump(new, f, separators=(",", ":"), ensure_ascii=False)
log("scris", OUT, "eșuate:", failed or "niciuna")
sys.exit(0)
