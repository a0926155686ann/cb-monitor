r"""抓公開資訊觀測站「買回自己公司股份彙總統計表」(庫藏股),上市 + 上櫃。

來源:https://mopsov.twse.com.tw/mops/web/ajax_t35sc09 (新版 MOPS「庫藏股統計彙總表」實際也是轉到這裡)
用法:python scripts\treasury.py      → 存 data\treasury.json 並印出筆數
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

URL = "https://mopsov.twse.com.tw/mops/web/ajax_t35sc09"
OUT = Path(__file__).resolve().parent.parent / "data" / "treasury.json"
PURPOSE = {"1": "轉讓股份予員工", "2": "配合股權轉換", "3": "維護公司信用及股東權益"}


def roc(d: date) -> str:
    return f"{d.year - 1911}{d.month:02d}{d.day:02d}"


def roc_to_iso(s: str) -> str:
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s.strip())
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    return f"{y + 1911:04d}-{mo:02d}-{d:02d}"


def _num(s: str):
    s = s.replace(",", "").strip()
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def fetch_market(typek: str, d1: date, d2: date) -> list[dict]:
    data = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "TYPEK": typek,
            "d1": roc(d1), "d2": roc(d2), "RD": "1"}
    req = urllib.request.Request(
        URL, data=urllib.parse.urlencode(data).encode(),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://mopsov.twse.com.tw/mops/web/t35sc09"})
    page = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")
    if "查詢過於頻繁" in page or "安全性考量" in page:
        raise RuntimeError("MOPS 暫時拒絕查詢(太頻繁),稍後再試")
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ").strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c) for c in cells]
        if len(cells) < 18 or not cells[0].isdigit() or not re.fullmatch(r"\d{4,6}", cells[1]):
            continue
        out.append({
            "market": "上市" if typek == "sii" else "上櫃",
            "code": cells[1],
            "name": cells[2].rstrip("*"),
            "board": roc_to_iso(cells[3]),
            "purpose": PURPOSE.get(cells[4], cells[4]),
            "maxAmt": _num(cells[5]),
            "planShares": _num(cells[6]),
            "pxLow": _num(cells[7]),
            "pxHigh": _num(cells[8]),
            "from": roc_to_iso(cells[9]),
            "to": roc_to_iso(cells[10]),
            "done": cells[11].upper() == "Y",
            "boughtShares": _num(cells[13]),
            "cancelShares": _num(cells[14]),
            "execPct": _num(cells[15]),
            "boughtAmt": _num(cells[16]),
            "avgPx": _num(cells[17]),
            "pctOfIssued": _num(cells[18]) if len(cells) > 18 else None,
            "note": cells[19] if len(cells) > 19 else "",
        })
    return out


PROGRESS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t35sb01"


def fetch_progress(code: str, market: str) -> list[dict]:
    """「買回達一定標準」申報(公司每累積買回達已發行 2% 或 3 億元就要申報一次)。
    回傳每次申報:{report, buyDate, shares, amount, avgPx, cumShares, cumPct}(日期 ISO)。"""
    typek = "sii" if market == "上市" else "otc"
    data = {"colorchg": "1", "step": "2", "TYPEK": typek, "co_id": code, "firstin": "true",
            "encodeURIComponent": "1", "off": "1"}
    req = urllib.request.Request(
        PROGRESS_URL, data=urllib.parse.urlencode(data).encode(),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://mopsov.twse.com.tw/mops/web/t35sc09"})
    page = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I)]
        if len(cells) < 9 or not cells[0].isdigit() or not re.match(r"\d{2,3}/\d{1,2}/\d{1,2}", cells[1]):
            continue
        out.append({
            "report": roc_to_iso(cells[1]),
            "buyDate": roc_to_iso(cells[3]),
            "shares": _num(cells[4]),
            "amount": _num(cells[5]),
            "avgPx": _num(cells[6]),
            "cumShares": _num(cells[7]),
            "cumPct": _num(cells[8].rstrip("%")),
        })
    return out


def fetch_all(years: int = 3) -> list[dict]:
    today = date.today()
    d1 = today - timedelta(days=365 * years)
    rows = []
    for i, typek in enumerate(("sii", "otc")):
        if i:
            time.sleep(3)  # 對 MOPS 客氣一點
        rows += fetch_market(typek, d1, today)
    rows.sort(key=lambda r: (r["code"], r["board"], r["from"]))
    return rows


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = fetch_all()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"date": date.today().isoformat(), "rows": rows}, ensure_ascii=False), encoding="utf-8")
    today = date.today().isoformat()
    active = [r for r in rows if r["from"] <= today <= r["to"]]
    print(f"庫藏股 {len(rows)} 筆(近 3 年),目前在買回期間內 {len(active)} 筆 → {OUT}")


if __name__ == "__main__":
    main()
