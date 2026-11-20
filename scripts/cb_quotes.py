r"""可轉債報價表:合併 CBAS 已發行 CB、櫃買中心發行資料、元大即時報價,輸出給 cb-quotes.html。

輸出:
    data\cb_quotes.js    網頁直接讀(window.CB_QUOTES = {...}),file:// 開啟也能用
    data\cb_quotes.json  同內容,給其他程式用
快取:
    data\cb_hist.json    CB 日K 歷史(算 一週/一月/一年% 與 五日均量),每天抓一次
    data\stock_market.json  標的股是上市/上櫃/興櫃

用法:
    python scripts\cb_quotes.py                # 抓一次(當天第一次會順便更新日K歷史,約 8 分鐘)
    python scripts\cb_quotes.py --no-history   # 不更新日K歷史(快,一週/一月/一年% 用舊快取)
    python scripts\cb_quotes.py --loop 30      # 盤中每 30 秒更新一次報價
    python scripts\cb_quotes.py --loop 30 --until 13:35   # 每 30 秒更新,13:35 收盤後結束
只呼叫查詢函式,不含任何下單。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_cb_list import fetch as fetch_cbas  # noqa: E402
from treasury import fetch_all as fetch_treasury  # noqa: E402
from treasury import fetch_progress  # noqa: E402
from yuanta_client import YuantaClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HIST = DATA / "cb_hist.json"
MKTF = DATA / "stock_market.json"
STKH = DATA / "stk_hist.json"
TREAS = DATA / "treasury.json"
TPROG = DATA / "treasury_progress.json"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/bond_ISSBD5_data"


def num(s, default=None):
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def fetch_tpex() -> dict[str, dict]:
    req = urllib.request.Request(TPEX_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode("utf-8"))
    return {str(x.get("BondCode", "")).strip(): x for x in rows}


def issued_lots(issue_amount: float | None, outstanding_lots: float | None) -> int | None:
    """發行張數(面額 10 萬/張)。櫃買的 IssueAmount 是募得金額(含溢價發行),
    取「≤ 金額/10萬 的最大 500 張倍數」且溢價 ≤ 20%;否則用金額/10萬 四捨五入。屬推估。"""
    if not issue_amount:
        return None
    base = issue_amount / 100_000
    if abs(base - round(base / 100) * 100) < 0.5:
        return int(round(base))
    n = int(base // 500) * 500
    if n > 0 and base / n <= 1.2 and (outstanding_lots is None or n >= outstanding_lots):
        return n
    return int(round(base))


def ref_close(bars: list[dict], before: date, tol_days: int = 0) -> float | None:
    """回傳日期 ≤ before 的最後一根收盤價;歷史不夠早則 None。
    tol_days:最早一根若在 before 之後 tol_days 天內,也拿來用(K 線最多只能查 364 天)。"""
    if not bars:
        return None
    if bars[0]["date"] > before.isoformat():
        if bars[0]["date"] <= (before + timedelta(days=tol_days)).isoformat():
            return bars[0]["close"]
        return None
    c = None
    for b in bars:
        if b["date"] <= before.isoformat():
            c = b["close"]
        else:
            break
    return c


def pct(now, ref):
    if now is None or not ref:
        return None
    return round((now / ref - 1) * 100, 2)


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def update_history(yc: YuantaClient, codes: list[str], hist: dict) -> dict:
    today = date.today()
    start = (today - timedelta(days=364)).strftime("%Y/%m/%d")  # GetKLine 區間超過約 365 天會不回應
    end = today.strftime("%Y/%m/%d")
    bars = hist.get("bars", {})
    print(f"更新 CB 日K 歷史:{len(codes)} 檔(K 線每秒最多 1 次,約 {len(codes) * 1.2 / 60:.0f} 分鐘)")
    for i, c in enumerate(codes, 1):
        try:
            bars[c] = yc.daily_kline(c, "otc", start, end)
        except Exception as e:
            print(f"  {c} 日K 失敗:{e}")
        if i % 50 == 0 or i == len(codes):
            print(f"  CB 日K 進度 {i * 100 // len(codes)}%({i}/{len(codes)})")
    return {"date": today.isoformat(), "bars": bars}


def resolve_markets(yc: YuantaClient, codes: list[str], known: dict) -> tuple[dict, dict]:
    """查標的股報價;不知道市場別的依序試 上市→上櫃→興櫃。回傳 (quotes by code, market map)。"""
    quotes = {}
    todo = [c for c in codes if c not in known]
    for mkt in ("tse", "otc", "emg"):
        if not todo:
            break
        got = {q["code"]: q for q in yc.quotes([(c, mkt) for c in todo]) if q["yst"] > 0 or q["deal"] > 0}
        for c, q in got.items():
            known[c] = mkt
            quotes[c] = q
        todo = [c for c in todo if c not in got]
    need = [(c, known[c]) for c in codes if c in known and c not in quotes]
    for q in yc.quotes(need):
        quotes[q["code"]] = q
    if todo:
        print(f"注意:{len(todo)} 檔標的查不到報價:{todo[:10]}")
    return quotes, known


def build(cbas: list[dict], tpex: dict, cbq: dict, stq: dict, hist: dict) -> list[dict]:
    today = date.today()
    out = []
    for r in cbas:
        code = r["bond_code"].strip()
        stk = r["convert_target_code"].strip()
        q = cbq.get(code, {})
        s = stq.get(stk, {})
        t = tpex.get(code, {})
        bars = [b for b in hist.get("bars", {}).get(code, []) if b["date"] < today.isoformat()]

        yst = q.get("yst") or None
        deal = q.get("deal") or None
        now = deal or yst
        chg = round(deal - yst, 2) if deal and yst else (0.0 if yst else None)
        tv, ov, iv = q.get("total_vol", 0), q.get("out_vol", 0), q.get("in_vol", 0)
        ratio = round(ov / (ov + iv) * 100, 2) if (ov + iv) > 0 else None

        cp = num(r.get("conversion_price"))
        sp = (s.get("deal") or s.get("yst")) if s else None
        if cp and sp:
            cv = round(sp / cp * 100, 2)
        else:
            cv = num(r.get("conversion_value"))
        prem = round((now / cv - 1) * 100, 2) if now and cv else num(r.get("premium_rate"))

        out_amt = num(t.get("OutstandingAmount"))
        remain = int(out_amt / 100_000) if out_amt is not None else int(num(r.get("circulating_balance"), 0) or 0)
        issued = issued_lots(num(t.get("IssueAmount")), remain)
        conv_pct = round((1 - remain / issued) * 100, 2) if issued else round(100 - (num(r.get("balance_ratio"), 100)), 2)

        g = t.get("Guaranteed")
        guar = ("是" if str(g) == "1" else "否") if g is not None else ("否" if r.get("guarantee_situation", "").startswith("無") else "是")

        vols = [b["vol"] for b in bars[-5:]]
        out.append(
            {
                "name": q.get("name") or r.get("underlying_bond", "").strip(),
                "code": code,
                "stk": stk,
                "stkName": s.get("name", ""),
                "ind": s.get("industry", ""),
                "yst": yst,
                "bid": q.get("bid") or None,
                "ask": q.get("ask") or None,
                "deal": deal,
                "chg": chg,
                "chgPct": round(chg / yst * 100, 2) if chg is not None and yst else None,
                "vol": q.get("vol") or 0,
                "ratio": ratio,
                "totalVol": tv,
                "avg5": round(sum(vols) / len(vols)) if vols else None,
                "w1": pct(now, ref_close(bars, today - timedelta(days=7))),
                "m1": pct(now, ref_close(bars, today - timedelta(days=30))),
                "y1": pct(now, ref_close(bars, today - timedelta(days=365), tol_days=7)),
                "convPrice": cp,
                "convValue": cv,
                "premium": prem,
                "convPct": conv_pct,
                "issued": issued,
                "guar": guar,
                "issueDate": r.get("issue_date", "").strip(),
                "expiry": r.get("expiry_date", "").strip(),
                "remain": remain,
                "underwriter": re.sub(r"^[0-9A-Za-z]+", "", str(t.get("Underwriter", "")).strip()),
                "stkPrice": sp,
                "stopConv": " ~ ".join(x for x in (r.get("stop_conversion_date", "").strip(), r.get("stop_converting_until_date", "").strip()) if x),
                "stopFrom": r.get("stop_conversion_date", "").strip(),
                "stopTo": r.get("stop_converting_until_date", "").strip(),
                "time": q.get("time", ""),
            }
        )
    return out


def update_stock_history(yc: YuantaClient, codes: list[str], markets: dict) -> dict:
    """標的股近 30 天日K(算前五日最高價)。"""
    today = date.today()
    start = (today - timedelta(days=30)).strftime("%Y/%m/%d")
    end = today.strftime("%Y/%m/%d")
    codes = [c for c in codes if c in markets]
    print(f"更新標的股日K:{len(codes)} 檔(約 {len(codes) * 1.2 / 60:.0f} 分鐘)")
    bars = {}
    for i, c in enumerate(codes, 1):
        try:
            bars[c] = yc.daily_kline(c, markets[c], start, end)
        except Exception as e:
            print(f"  {c} 日K 失敗:{e}")
        if i % 50 == 0 or i == len(codes):
            print(f"  標的股日K 進度 {i * 100 // len(codes)}%({i}/{len(codes)})")
    return {"date": today.isoformat(), "bars": bars}


def _d(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%Y/%m/%d").date()
    except (AttributeError, ValueError):
        return None


def build_breakout(rows: list[dict], stq: dict, stk_hist: dict) -> list[dict]:
    """發債突破:每檔 CB 一列,附標的股是否突破前五日最高價。
    燈數(暫定,待使用者定義):①突破五日新高 ②股價漲幅≥3% ③CB今日有成交 ④轉換溢價率≤20% ⑤距到期≥180天
    市值 = 轉換價值(暫定);停 = 今天在停止轉換期間內(暫定)。"""
    today = date.today()
    out = []
    for r in rows:
        s = stq.get(r["stk"], {})
        yst, deal = s.get("yst") or None, s.get("deal") or None
        price = deal or yst
        chg = round((deal / yst - 1) * 100, 2) if deal and yst else 0.0
        bars = [b for b in stk_hist.get("bars", {}).get(r["stk"], []) if b["date"] < today.isoformat()][-5:]
        hi5 = max(b["high"] for b in bars) if len(bars) == 5 else None
        brk = bool(hi5 and deal and deal > hi5)
        exp = _d(r["expiry"])
        days = (exp - today).days if exp else None
        f, t = _d(r.get("stopFrom", "")), _d(r.get("stopTo", ""))
        stop = 1 if f and f <= today and (t is None or today <= t) else 0
        conds = [
            ("突破五日新高", brk),
            ("漲幅≥3%", chg >= 3),
            ("CB有成交", (r.get("totalVol") or 0) > 0),
            ("溢價率≤20%", r.get("premium") is not None and r["premium"] <= 20),
            ("距到期≥180天", days is not None and days >= 180),
        ]
        out.append(
            {
                "stars": sum(ok for _, ok in conds),
                "why": "、".join(n for n, ok in conds if ok),
                "name": s.get("name") or r.get("stkName") or r["stk"],
                "code": r["stk"],
                "ind": s.get("industry", ""),
                "chg": chg,
                "price": price or 0,
                "hi5": hi5,
                "breakout": brk,
                "cb": r["name"],
                "cbcode": r["code"],
                "cbp": r.get("deal") or 0,
                "mv": r.get("convValue") or 0,
                "days": days if days is not None else 0,
                "stop": stop,
                "premium": r.get("premium"),
                "uw": r.get("underwriter", ""),
            }
        )
    return out


def active_buybacks(treas: list[dict], stk_codes: set[str]) -> dict[str, dict]:
    """有 CB 的標的中,庫藏股正在進行或即將開始者:{代碼: 最新一筆}。"""
    ti = date.today().isoformat()
    latest: dict[str, dict] = {}
    for t in treas:
        if t["code"] in stk_codes and (t["code"] not in latest or (t["board"], t["from"]) > (latest[t["code"]]["board"], latest[t["code"]]["from"])):
            latest[t["code"]] = t
    return {c: t for c, t in latest.items() if t["to"] >= ti}


def load_progress(active: dict[str, dict], max_age_h: float = 3) -> dict[str, list]:
    """進行中庫藏股的「買回達一定標準」申報,快取 max_age_h 小時。"""
    cache = load_json(TPROG, {})
    try:
        age = (datetime.now() - datetime.fromisoformat(cache.get("time", "2000-01-01T00:00:00"))).total_seconds() / 3600
    except ValueError:
        age = 99
    data = cache.get("data", {})
    if age < max_age_h and set(active) <= set(data):
        return data
    print(f"抓庫藏股執行進度:{len(active)} 家")
    new = {}
    for i, (code, t) in enumerate(sorted(active.items()), 1):
        try:
            new[code] = fetch_progress(code, t["market"])
        except Exception as e:
            print(f"  {code} 失敗:{e}")
            new[code] = data.get(code, [])
        if i < len(active):
            time.sleep(2)  # MOPS 查太快會被擋
    TPROG.write_text(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), "data": new}, ensure_ascii=False), encoding="utf-8")
    return new


def build_treasury(rows: list[dict], stq: dict, treas: list[dict], keep_days: int = 0, progress: dict | None = None) -> list[dict]:
    """發債庫藏:標的股庫藏股「正在進行或即將開始」的 CB,每檔 CB 一列(使用者指定不含已結束)。
    keep_days > 0 時另外保留近 keep_days 天內結束的。"""
    today = date.today()
    ti = today.isoformat()
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    by_stk: dict[str, list[dict]] = {}
    for t in treas:
        by_stk.setdefault(t["code"], []).append(t)
    out = []
    for r in rows:
        lst = sorted(by_stk.get(r["stk"], []), key=lambda t: (t["board"], t["from"]))
        if not lst:
            continue
        cur = lst[-1]
        if cur["to"] < cutoff:
            continue
        # 同一次董事會可能分多筆(例如不同買回目的),合併計算
        same = [t for t in lst if t["board"] == cur["board"]]
        prev_list = [t for t in lst if t["board"] < cur["board"]]
        prev = prev_list[-1] if prev_list else None
        if prev:
            prev_same = [t for t in prev_list if t["board"] == prev["board"]]
        status = "進行中" if cur["from"] <= ti <= cur["to"] else ("即將開始" if ti < cur["from"] else "已結束")
        s = stq.get(r["stk"], {})
        yst, deal = s.get("yst") or None, s.get("deal") or None
        px = deal or yst
        plan = sum(t["planShares"] or 0 for t in same)
        bought = sum(t["boughtShares"] or 0 for t in same) if all(t["done"] for t in same) else None
        pos = None
        if px and cur["pxLow"] and cur["pxHigh"]:
            pos = "低於區間" if px < cur["pxLow"] else ("高於區間" if px > cur["pxHigh"] else "區間內")
        to_d = datetime.strptime(cur["to"], "%Y-%m-%d").date()
        # 本次買回期間內的「買回達一定標準」申報 → 目前已買回(至少)
        p_from = min(t["from"] for t in same)
        reps = [x for x in (progress or {}).get(r["stk"], []) if x["buyDate"] and x["buyDate"] >= p_from]
        reps.sort(key=lambda x: (x["buyDate"], x["report"]))
        now_sh = reps[-1]["cumShares"] if reps else None
        now_amt = sum(x["amount"] or 0 for x in reps) if reps else None
        out.append({
            "nowLots": round(now_sh / 1000) if now_sh else (0 if progress is not None and r["stk"] in progress else None),
            "nowPct": round(now_sh / plan * 100, 2) if now_sh and plan else None,
            "nowAmt": now_amt,
            "nowAvg": round(now_amt / now_sh, 2) if now_sh and now_amt else None,
            "nowAsOf": reps[-1]["buyDate"] if reps else "",
            "nowReports": len(reps),
            "status": status,
            "name": s.get("name") or r.get("stkName") or cur["name"],
            "code": r["stk"],
            "ind": s.get("industry", ""),
            "chg": round((deal / yst - 1) * 100, 2) if deal and yst else 0.0,
            "price": px or 0,
            "cb": r["name"],
            "cbcode": r["code"],
            "cbp": r.get("deal") or 0,
            "premium": r.get("premium"),
            "uw": r.get("underwriter", ""),
            "board": cur["board"],
            "from": min(t["from"] for t in same),
            "to": max(t["to"] for t in same),
            "daysLeft": (to_d - today).days,
            "planLots": round(plan / 1000) if plan else None,
            "maxAmt": cur["maxAmt"],
            "pxLow": cur["pxLow"],
            "pxHigh": cur["pxHigh"],
            "pos": pos,
            "purpose": "、".join(dict.fromkeys(t["purpose"] for t in same)),
            "boughtLots": round(bought / 1000) if bought is not None else None,
            "execPct": round(bought / plan * 100, 2) if bought is not None and plan else None,
            "prevBoard": prev["board"] if prev else "",
            "prevFrom": min(t["from"] for t in prev_same) if prev else "",
            "prevTo": max(t["to"] for t in prev_same) if prev else "",
            "prevPlanLots": round(sum(t["planShares"] or 0 for t in prev_same) / 1000) if prev else None,
            "prevExecPct": (round(sum(t["boughtShares"] or 0 for t in prev_same) / max(1, sum(t["planShares"] or 0 for t in prev_same)) * 100, 2)
                            if prev and all(t["done"] for t in prev_same) else None),
            "count3y": len({t["board"] for t in lst}),
        })
    return out


def load_treasury() -> list[dict]:
    """庫藏股資料每天抓一次(MOPS),失敗就用舊快取。"""
    cache = load_json(TREAS, {})
    if cache.get("date") == date.today().isoformat():
        return cache.get("rows", [])
    try:
        rows = fetch_treasury()
        TREAS.write_text(json.dumps({"date": date.today().isoformat(), "rows": rows}, ensure_ascii=False), encoding="utf-8")
        print(f"庫藏股:{len(rows)} 筆(近 3 年)")
        return rows
    except Exception as e:
        print(f"庫藏股抓取失敗({e}),使用快取 {cache.get('date', '無')}")
        return cache.get("rows", [])


def write_js(name: str, var: str, payload: dict):
    DATA.mkdir(exist_ok=True)
    s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (DATA / f"{name}.json").write_text(s, encoding="utf-8")
    tmp = DATA / f"{name}.js.tmp"
    tmp.write_text(f"window.{var}=" + s + ";\n", encoding="utf-8")
    tmp.replace(DATA / f"{name}.js")


def write(rows: list[dict], meta: dict):
    write_js("cb_quotes", "CB_QUOTES", {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **meta, "rows": rows})


def publish():
    """呼叫 scripts\\publish.ps1 把網頁與 data\\*.js 推到 gh-pages;失敗不中斷報價更新。"""
    import subprocess

    ps1 = Path(__file__).resolve().parent / "publish.ps1"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                           capture_output=True, text=True, timeout=180)
        msg = (r.stdout or r.stderr).strip().splitlines()
        print(f"  發布 GitHub Pages:{msg[-1] if msg else ''}" if r.returncode == 0 else f"  發布失敗:{msg[-3:]}")
    except Exception as e:
        print(f"  發布失敗:{e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-history", action="store_true", help="不更新日K歷史")
    ap.add_argument("--history", action="store_true", help="強制更新日K歷史")
    ap.add_argument("--loop", type=int, default=0, help="每 N 秒更新一次(≥10)")
    ap.add_argument("--until", default="", help="搭配 --loop,到此時間(HH:MM)做最後一次更新後結束,例 13:35")
    ap.add_argument("--publish-every", type=int, default=0,
                    help="每 N 秒發布到 GitHub Pages(scripts\\publish.ps1),結束前再發布一次;0 = 不發布")
    a = ap.parse_args()
    until = datetime.strptime(a.until, "%H:%M").time() if a.until else None

    print("抓 CBAS 已發行 CB…")
    cbas = fetch_cbas()
    print(f"  {len(cbas)} 檔,資料時間 {cbas[0].get('create_date', '')}")
    print("抓櫃買中心發行資料…")
    try:
        tpex = fetch_tpex()
        print(f"  {len(tpex)} 筆")
    except Exception as e:
        print(f"  失敗({e}),發行張數/擔保改用 CBAS 推算")
        tpex = {}

    cb_codes = [r["bond_code"].strip() for r in cbas]
    stk_codes = sorted({r["convert_target_code"].strip() for r in cbas})
    hist = load_json(HIST, {})
    markets = load_json(MKTF, {})

    stk_hist = load_json(STKH, {})
    treas = load_treasury()
    try:
        progress = load_progress(active_buybacks(treas, set(stk_codes)))
    except Exception as e:
        print(f"庫藏股執行進度抓取失敗:{e}")
        progress = {}

    with YuantaClient() as yc:
        today_s = date.today().isoformat()
        need_hist = a.history or (not a.no_history and hist.get("date") != today_s)
        if need_hist:
            hist = update_history(yc, cb_codes, hist)
            HIST.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
        if a.history or (not a.no_history and stk_hist.get("date") != today_s) or not stk_hist:
            _, markets = resolve_markets(yc, stk_codes, markets)
            MKTF.write_text(json.dumps(markets, ensure_ascii=False), encoding="utf-8")
            stk_hist = update_stock_history(yc, stk_codes, markets)
            STKH.write_text(json.dumps(stk_hist, ensure_ascii=False), encoding="utf-8")
        last_pub = 0.0
        while True:
            t0 = time.monotonic()
            cbq = {q["code"]: q for q in yc.quotes([(c, "otc") for c in cb_codes])}
            stq, markets = resolve_markets(yc, stk_codes, markets)
            MKTF.write_text(json.dumps(markets, ensure_ascii=False), encoding="utf-8")
            rows = build(cbas, tpex, cbq, stq, hist)
            now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            meta = {"cbasTime": cbas[0].get("create_date", ""), "histDate": hist.get("date", "")}
            write(rows, meta)
            brk = build_breakout(rows, stq, stk_hist)
            write_js("cb_breakout", "CB_BREAKOUT", {"updated": now_s, **meta, "rows": brk})
            tre = build_treasury(rows, stq, treas, progress=progress)
            write_js("cb_treasury", "CB_TREASURY", {"updated": now_s, **meta, "treasDate": date.today().isoformat(), "rows": tre})
            n = sum(1 for b in brk if b["breakout"])
            print(f"  發債庫藏:{len(tre)} 檔 CB(進行中 {sum(1 for t in tre if t['status'] == '進行中')})")
            print(f"{datetime.now():%H:%M:%S} 已更新 {len(rows)} 檔 CB(有報價 {len(cbq)}),突破五日新高 {n} 檔 CB")
            last_round = a.loop < 10 or (until and datetime.now().time() >= until)
            if a.publish_every and (last_round or time.monotonic() - last_pub >= a.publish_every):
                publish()
                last_pub = time.monotonic()
            sys.stdout.flush()
            if last_round:
                break
            time.sleep(max(0, a.loop - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
