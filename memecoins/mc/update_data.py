#!/usr/bin/env python3
"""Memecoins: actualizare automată a datelor agregate (GitHub Actions la ~15 min, doar biblioteca standard, fără chei API).
Scrie memecoins/mc/data.json:
  cat     – CoinGecko /coins/categories: meme-token (total), solana-meme-coins, base-meme-coins + subcategorii (secțiunea 08)
  top     – CoinGecko /coins/markets?category=meme-token (primele 250 după mcap, 1h/24h/7d)
  majors  – Binance data-api.binance.vision: BTCUSDT, SOLUSDT (24h)
  fng     – api.alternative.me/fng (Fear & Greed, zilnic, ultimele 7 zile)
  trend   – GeckoTerminal trending_pools pe solana/base/bsc/eth
  vol     – GeckoTerminal trending_pools 24h (2 pagini) pe solana/base/bsc/eth, ordonate după volum (fără stablecoins/majore/volum spălat)
  boost   – DexScreener token-boosts/top/v1 + tokens/v1 (preț, volum, mcap)
  fresh   – GeckoTerminal new_pools pe solana/base/bsc/eth (fără curbele de bonding, lichiditate ≥ $5k)
  grad    – gradări recente: pool-uri PumpSwap (pump.fun) și Raydium (bonk.fun) create în ultimele 24–72h, după volum
  src     – starea fiecărei surse {ok, at, err}
Dacă o sursă eșuează sau întoarce gol, se păstrează ultima valoare bună din data.json existent (nicio secțiune nu se golește).
Știrile (news.json) NU sunt scrise aici: X nu are API public fără cheie. Opțional: dacă există variabila X_BEARER_TOKEN
(secret GitHub), scriptul reîmprospătează și news.json prin X API v2 recent search; altfel news.json rămâne neatins.
Ieșire mereu cu cod 0."""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
NEWS = os.path.join(HERE, "news.json")
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
UA = "Mozilla/5.0 (compatible; KishaDesk/1.0; +https://covaciucarina15-bot.github.io/dashboard/memecoins/)"
NETS = {"solana": "Solana", "base": "Base", "bsc": "BNB Chain", "eth": "Ethereum"}
DS_CHAIN = {"solana": "solana", "base": "base", "bsc": "bsc", "eth": "ethereum"}
# monede care nu sunt memecoinuri (stablecoins, majore, wrapped) – scoase din trending / volum / lansări
MAJORS = {"SOL", "WSOL", "USDC", "USDT", "USD1", "USDS", "PYUSD", "DAI", "FDUSD", "USDE", "USDG", "ETH", "WETH", "STETH", "WSTETH", "CBETH",
          "BTC", "WBTC", "CBBTC", "BTCB", "BNB", "WBNB", "JUP", "JITOSOL", "MSOL", "BSOL", "JLP", "INF", "EURC", "AERO", "VIRTUAL", "CAKE",
          "LINK", "UNI", "AAVE", "RAY", "ORCA", "TRX", "XRP", "HSOL", "BUSD", "TUSD", "FRAX", "LST", "SUSDE", "WEETH", "EZETH", "RETH", "ZORA", "TBTC", "LBTC", "SOLVBTC", "USDC.E", "WAVAX", "AVAX", "HYPE", "WHYPE", "ZRO"}
CURVE_DEX = {"pump-fun", "meteora-dbc", "letsbonk-fun", "raydium-launchlab", "boop-fun", "moonit", "moonshot", "heaven", "bags-fm",
             "daos-fun", "token-mill", "wavebreak", "printr-v2", "memefun", "stonkfun", "easya-kickstart", "virtuals-solana", "clanker-solana"}

def log(*a): print(*a, file=sys.stderr, flush=True)

def get(url, tries=3, timeout=30, headers=None):
    last = None
    for k in range(tries):
        try:
            h = {"User-Agent": UA, "Accept": "application/json"}
            if headers: h.update(headers)
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e; log("  retry", k + 1, url[:100], e)
            time.sleep((20 if "429" in str(e) else 3) * (k + 1))
    raise RuntimeError(str(last))

def f(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception: return None

def r(v, n=6):
    return None if v is None else round(v, n)

try: prev = json.load(open(OUT, encoding="utf-8"))
except Exception: prev = {}
data = dict(prev)
src = dict(prev.get("src") or {})

def run(key, fn, ok=lambda v: bool(v)):
    """Rulează o sursă; dacă eșuează sau e goală, păstrează valoarea veche."""
    try:
        v = fn()
        if not ok(v): raise RuntimeError("răspuns gol")
        data[key] = v; src[key] = {"ok": True, "at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
        log("OK", key)
    except Exception as e:
        old = (src.get(key) or {}).get("at")
        src[key] = {"ok": False, "at": old, "err": str(e)[:160]}
        log("EȘUAT", key, e, "(păstrez valoarea veche)" if key in prev else "(nicio valoare veche)")

# ---------- CoinGecko: categorii
SUBS = [("dog-themed-coins", "Dogs"), ("cat-themed-coins", "Cats"), ("frog-themed-coins", "Frogs"), ("4chan-themed", "4chan"),
        ("ai-meme-coins", "AI meme"), ("chinese-meme", "Chinese memes"), ("politifi", "PolitiFi (politics)"),
        ("celebrity-themed-coins", "Celebrities"), ("ip-meme", "IP memes (characters, brands)"), ("tiktok-meme", "TikTok meme"),
        ("wojak-themed", "Wojak"), ("parody-meme-coins", "Parodies"), ("stock-market-themed", "Stock-market themes"),
        ("anime-themed-coins", "Anime"), ("zoo-themed", "Zoo animals"), ("pump-fun", "pump.fun ecosystem"),
        ("letsbonk-fun-ecosystem", "bonk.fun ecosystem"), ("four-meme-ecosystem", "Four.meme (BNB)"),
        ("robinhood-chain-meme", "Robinhood Chain meme"), ("bitcoin-meme", "Bitcoin meme"), ("ton-meme-coins", "TON meme"),
        ("sui-meme", "Sui meme"), ("tron-meme", "TRON meme")]
def cats():
    l = get("https://api.coingecko.com/api/v3/coins/categories")
    by = {c["id"]: c for c in l if isinstance(c, dict) and c.get("id")}
    def one(cid, name=None):
        c = by.get(cid)
        if not c or not c.get("market_cap"): return None
        return {"id": cid, "name": name or c.get("name"), "mcap": r(f(c.get("market_cap")), 0), "chg24": r(f(c.get("market_cap_change_24h")), 3),
                "vol24": r(f(c.get("volume_24h")), 0), "top": c.get("top_3_coins_id") or [], "at": c.get("updated_at")}
    out = {"meme": one("meme-token", "Meme"), "sol": one("solana-meme-coins", "Solana Meme"), "base": one("base-meme-coins", "Base Meme"),
           "subs": [x for x in (one(cid, nm) for cid, nm in SUBS) if x]}
    if not out["meme"]: raise RuntimeError("lipsește meme-token")
    out["subs"].sort(key=lambda x: -(x["mcap"] or 0))
    return out
run("cat", cats)

# ---------- CoinGecko: top memes după mcap
def top():
    l = get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=meme-token&order=market_cap_desc&per_page=250&page=1"
            "&sparkline=false&price_change_percentage=1h,24h,7d")
    out = []
    for c in l:
        if not c.get("market_cap") or __import__("re").search(r"^(binance-peg|bridged|wrapped)|-(bridged|wormhole|peg)", c.get("id") or ""): continue
        out.append({"id": c["id"], "sym": (c.get("symbol") or "").upper(), "name": c.get("name"), "rank": c.get("market_cap_rank"),
                    "px": f(c.get("current_price")), "mc": r(f(c.get("market_cap")), 0), "vol": r(f(c.get("total_volume")), 0),
                    "h1": r(f(c.get("price_change_percentage_1h_in_currency")), 3), "h24": r(f(c.get("price_change_percentage_24h_in_currency")), 3),
                    "d7": r(f(c.get("price_change_percentage_7d_in_currency")), 3), "ath": f(c.get("ath")), "athp": r(f(c.get("ath_change_percentage")), 2)})
    return out
run("top", top, lambda v: len(v) >= 20)

# ---------- Binance: BTC, SOL
def majors():
    l = get("https://data-api.binance.vision/api/v3/ticker/24hr?symbols=" + urllib.parse.quote('["BTCUSDT","SOLUSDT"]'))
    out = {}
    for t in l:
        k = {"BTCUSDT": "btc", "SOLUSDT": "sol"}.get(t.get("symbol"))
        if k: out[k] = {"px": f(t.get("lastPrice")), "chg": f(t.get("priceChange")), "chp": f(t.get("priceChangePercent")), "vol": r(f(t.get("quoteVolume")), 0)}
    if len(out) < 2: raise RuntimeError("lipsă BTC/SOL")
    return out
run("majors", majors)

# ---------- Fear & Greed
def fng():
    j = get("https://api.alternative.me/fng/?limit=8")
    d = j.get("data") or []
    if not d: raise RuntimeError("gol")
    hist = [{"v": int(x["value"]), "cls": x.get("value_classification"), "date": dt.datetime.fromtimestamp(int(x["timestamp"]), UTC).strftime("%Y-%m-%d")} for x in d]
    return {"v": hist[0]["v"], "cls": hist[0]["cls"], "date": hist[0]["date"], "hist": hist}
run("fng", fng)

# ---------- GeckoTerminal: pool -> obiect normalizat
def gt_pool(p, net, tok):
    a = p.get("attributes") or {}; rel = p.get("relationships") or {}
    bid = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
    t = tok.get(bid) or {}
    sym = t.get("symbol") or (a.get("name") or "?").split(" / ")[0]
    pc = a.get("price_change_percentage") or {}; vu = a.get("volume_usd") or {}; tx = (a.get("transactions") or {}).get("h1") or {}
    addr = t.get("address") or bid.split("_", 1)[-1]
    return {"sym": sym, "name": t.get("name") or sym, "chain": NETS[net], "addr": addr, "pool": a.get("address"),
            "dex": ((rel.get("dex") or {}).get("data") or {}).get("id"), "px": f(a.get("base_token_price_usd")),
            "mc": r(f(a.get("market_cap_usd")) or f(a.get("fdv_usd")), 0), "liq": r(f(a.get("reserve_in_usd")), 0),
            "vol24": r(f(vu.get("h24")), 0), "vol1": r(f(vu.get("h1")), 0), "m5": r(f(pc.get("m5")), 2), "h1": r(f(pc.get("h1")), 2),
            "h24": r(f(pc.get("h24")), 2), "b1": tx.get("buys"), "s1": tx.get("sells"), "created": a.get("pool_created_at"),
            "url": f"https://dexscreener.com/{DS_CHAIN[net]}/{a.get('address')}"}

def gt_list(url, net):
    j = get(url)
    tok = {x["id"]: x.get("attributes") or {} for x in (j.get("included") or []) if x.get("type") == "token"}
    return [gt_pool(p, net, tok) for p in (j.get("data") or [])]

STOCK = __import__("re").compile(r"^[A-Z]{2,5}[cx]$")  # acțiuni tokenizate (xStocks NVDAx, Base NVDAc …)
def meme_ok(x):
    s = (x["sym"] or "").lstrip("$")
    u = s.upper()
    wrapped = u.endswith("BTC") or (u.endswith("ETH") and len(u) > 3) or (s[:2] in ("cb", "st", "wst") and len(s) > 4)
    return u not in MAJORS and "USD" not in u and not STOCK.match(s) and not wrapped
def sane(x, mc=20000, liq=5000):
    """scoate pool-urile cu lichiditate fictivă sau volum spălat (mcap uriaș pe lichiditate mică)."""
    m, l = x["mc"] or 0, x["liq"] or 0
    return m >= mc and l >= liq and m / max(l, 1) <= 100 and abs(x["h24"] or 0) <= 20000

def per_net(key, fn, n=12):
    out, errs = {}, []
    for net in NETS:
        try:
            l = [x for x in fn(net) if meme_ok(x)]
            seen, ded = set(), []
            for x in l:
                k = (x["addr"] or "").lower()
                if k in seen: continue
                seen.add(k); ded.append(x)
            out[NETS[net]] = ded[:n]
        except Exception as e:
            errs.append(f"{net}: {e}")
        time.sleep(2.2)  # GeckoTerminal: max ~30 cereri/minut
    if not out: raise RuntimeError("; ".join(errs) or "gol")
    old = prev.get(key) or {}
    for k, v in old.items():  # rețea eșuată -> păstrează lista veche
        if k not in out or not out[k]: out[k] = v
    return out

def trend(net): return gt_list(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools?include=base_token,dex&duration=1h", net)
def vol(net):
    # pools?sort=h24_volume_usd_desc e dominat de pool-uri cu volum spălat; folosim trending 24h (2 pagini), ordonat după volum
    l = gt_list(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools?include=base_token,dex&duration=24h", net)
    time.sleep(2.2)
    l += gt_list(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools?include=base_token,dex&duration=24h&page=2", net)
    return sorted([x for x in l if sane(x, 100000, 25000)], key=lambda x: -(x["vol24"] or 0))
def fresh(net):
    # pe Solana o pagină de new_pools acoperă doar câteva secunde (curbele pump.fun), deci citim mai multe pagini
    l = []
    for pg in range(1, (6 if net == "solana" else 3)):
        l += gt_list(f"https://api.geckoterminal.com/api/v2/networks/{net}/new_pools?include=base_token,dex&page={pg}", net)
        time.sleep(2.2)
    l = [x for x in l if x["dex"] not in CURVE_DEX and sane(x, 20000, 5000)]
    # se adaugă perechile din rulările anterioare (ultimele 24 h), ca lista să nu fie goală între lansări
    lim = (NOW - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    l += [x for x in ((prev.get("fresh") or {}).get(NETS[net]) or []) if (x.get("created") or "") >= lim]
    return sorted(l, key=lambda x: x["created"] or "", reverse=True)
run("trend", lambda: per_net("trend", trend))
run("vol", lambda: per_net("vol", vol))
run("fresh", lambda: per_net("fresh", fresh, 15))

# ---------- Gradări pump.fun / bonk.fun
def grad():
    out = []
    lim24 = (NOW - dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lim72 = (NOW - dt.timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # sortare după numărul de tranzacții: după volum, primele locuri sunt pool-uri cu lichiditate ~0 și volum spălat
    for page in (1, 2, 3, 4, 5):
        for x in gt_list(f"https://api.geckoterminal.com/api/v2/networks/solana/dexes/pumpswap/pools?include=base_token,dex&sort=h24_tx_count_desc&page={page}", "solana"):
            if (x["addr"] or "").endswith("pump") and (x["created"] or "") >= lim24 and sane(x, 50000, 10000):
                x["via"] = "pump.fun → PumpSwap"; out.append(x)
        time.sleep(2.2)
    for page in (1, 2):
        for x in gt_list(f"https://api.geckoterminal.com/api/v2/networks/solana/dexes/raydium/pools?include=base_token,dex&sort=h24_tx_count_desc&page={page}", "solana"):
            if (x["addr"] or "").endswith("bonk") and (x["created"] or "") >= lim72 and sane(x, 30000, 5000):
                x["via"] = "bonk.fun → Raydium"; out.append(x)
        time.sleep(2.2)
    seen, ded = set(), []
    for x in sorted(out, key=lambda x: -(x["vol24"] or 0)):
        if x["addr"] in seen: continue
        seen.add(x["addr"]); ded.append(x)
    ded.sort(key=lambda x: x["created"] or "", reverse=True)
    return ded[:16]
run("grad", grad, lambda v: isinstance(v, list))

# ---------- DexScreener: cele mai promovate (boost)
def boost():
    l = get("https://api.dexscreener.com/token-boosts/top/v1")
    want = {}
    for b in l:
        c = b.get("chainId")
        if c in ("solana", "base", "bsc", "ethereum") and b.get("tokenAddress"):
            want.setdefault(c, []).append((b["tokenAddress"], b.get("totalAmount") or b.get("amount") or 0))
    out = []
    rev = {v: k for k, v in DS_CHAIN.items()}
    for c, items in want.items():
        addrs = [a for a, _ in items][:30]
        pairs = get(f"https://api.dexscreener.com/tokens/v1/{c}/" + ",".join(addrs))
        best = {}
        for p in pairs if isinstance(pairs, list) else []:
            a = (p.get("baseToken") or {}).get("address") or ""
            if a.lower() not in {x.lower() for x in addrs}: continue
            if a.lower() not in best or (p.get("liquidity") or {}).get("usd", 0) > (best[a.lower()].get("liquidity") or {}).get("usd", 0): best[a.lower()] = p
        for a, amt in items:
            p = best.get(a.lower())
            if not p: continue
            pc = p.get("priceChange") or {}; vo = p.get("volume") or {}
            out.append({"sym": (p.get("baseToken") or {}).get("symbol"), "name": (p.get("baseToken") or {}).get("name"), "chain": NETS[rev[c]],
                        "addr": a, "pool": p.get("pairAddress"), "dex": p.get("dexId"), "px": f(p.get("priceUsd")), "mc": r(f(p.get("marketCap")) or f(p.get("fdv")), 0),
                        "liq": r(f((p.get("liquidity") or {}).get("usd")), 0), "vol24": r(f(vo.get("h24")), 0), "vol1": r(f(vo.get("h1")), 0),
                        "m5": f(pc.get("m5")), "h1": f(pc.get("h1")), "h24": f(pc.get("h24")), "boost": amt,
                        "created": dt.datetime.fromtimestamp(p["pairCreatedAt"] / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if p.get("pairCreatedAt") else None,
                        "url": p.get("url")})
    out.sort(key=lambda x: -(x["boost"] or 0))
    return out[:30]
run("boost", boost)

# ---------- Știri X (opțional, doar cu secretul X_BEARER_TOKEN)
def news():
    tok = os.environ.get("X_BEARER_TOKEN")
    if not tok: return None
    H = {"Authorization": "Bearer " + tok}
    try: old = json.load(open(NEWS, encoding="utf-8"))
    except Exception: old = {}
    def search(q, n=20):
        u = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode({"query": q, "max_results": n, "tweet.fields": "created_at,public_metrics,note_tweet",
                                                                               "expansions": "author_id", "user.fields": "name,username"})
        j = get(u, headers=H, tries=2)
        us = {x["id"]: x for x in (j.get("includes") or {}).get("users", [])}
        out = []
        for p in j.get("data") or []:
            u2 = us.get(p["author_id"], {})
            t = ((p.get("note_tweet") or {}).get("text") or p.get("text") or "").strip()
            out.append({"id": p["id"], "author": u2.get("name"), "handle": u2.get("username"), "text": t[:420], "date": p.get("created_at"),
                        "likes": (p.get("public_metrics") or {}).get("like_count"), "url": f"https://x.com/{u2.get('username')}/status/{p['id']}"})
        return out
    accts = old.get("accounts") or ["WatcherGuru", "Cointelegraph", "decryptmedia", "BSCNews", "solana_daily", "bubblemaps", "SolanaFloor", "lookonchain", "beincrypto", "cryptodotnews"]
    terms = '(memecoin OR memecoins OR "meme coin" OR "meme coins" OR pump.fun OR pumpfun OR letsbonk OR $PEPE OR $BONK OR $WIF OR $DOGE OR $SHIB OR $PENGU OR $TRUMP OR $PUMP)'
    q = "(" + " OR ".join("from:" + a for a in accts) + ") " + terms + " -is:retweet -is:reply"
    newsl = search(q, 25)
    kisha = search("from:kishainu1 -is:retweet -is:reply", 15)
    if not newsl and not kisha: raise RuntimeError("X a întors gol")
    res = dict(old)
    if newsl: res["news"] = newsl
    if kisha: res["kisha"] = kisha
    res["fetched"] = NOW.strftime("%Y-%m-%dT%H:%M:%SZ"); res["via"] = "X API v2 (GitHub Actions)"
    json.dump(res, open(NEWS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return True
try:
    if news(): src["news"] = {"ok": True, "at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ")}
except Exception as e:
    src["news"] = {"ok": False, "at": (src.get("news") or {}).get("at"), "err": str(e)[:160]}; log("Știri X eșuate:", e)

data["src"] = src
data["updated"] = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
tmp = OUT + ".tmp"
json.dump(data, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
os.replace(tmp, OUT)
log("scris", OUT, os.path.getsize(OUT), "octeți")
