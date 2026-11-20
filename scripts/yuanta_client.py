r"""元大 Spark API 查詢用的共用模組(只含查詢,不含任何下單/條件單/圈存)。

用法:
    from yuanta_client import YuantaClient
    with YuantaClient() as yc:
        rows = yc.quotes([("84891", "otc"), ("2330", "tse")])
        bars = yc.daily_kline("2330", "tse", "2026/11/01", "2026/11/20")

帳號密碼從環境變數 YUANTA_ACCOUNT / YUANTA_PASSWORD 讀取,若目前程序沒有,
會再讀 Windows「使用者」環境變數(剛設定、尚未重開視窗時也能用)。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

API_DIR = Path(os.environ.get("YUANTA_API_DIR", r"C:\YuantaSparkAPI_win-x64_Python"))


def _env(name: str) -> str:
    v = os.environ.get(name, "")
    if not v and sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v = winreg.QueryValueEx(k, name)[0]
        except OSError:
            v = ""
    return v


_loaded = False


def _load_dll():
    global _loaded, List, KLineType, OnResponseEventHandler, Quote, YuantaSparkAPITrader
    global enumEnvironmentMode, enumLogType, enumMarketType
    if _loaded:
        return
    from pythonnet import load

    load("coreclr")
    import clr

    sys.path.append(str(API_DIR))
    os.add_dll_directory(str(API_DIR))
    clr.AddReference("System.Collections")
    clr.AddReference("YuantaSparkAPI")
    from System.Collections.Generic import List  # noqa: F811
    from YuantaOneAPI import (  # noqa: F811
        KLineType,
        OnResponseEventHandler,
        Quote,
        YuantaSparkAPITrader,
        enumEnvironmentMode,
        enumLogType,
        enumMarketType,
    )

    globals().update(locals())
    _loaded = True


class RateLimiter:
    """確保同一類呼叫的間隔 ≥ interval 秒。"""

    def __init__(self, interval: float):
        self.interval = interval
        self.last = 0.0

    def wait(self):
        d = time.monotonic() - self.last
        if d < self.interval:
            time.sleep(self.interval - d)
        self.last = time.monotonic()


class YuantaClient:
    def __init__(self, verbose: bool = True):
        self.account = _env("YUANTA_ACCOUNT")
        self.password = _env("YUANTA_PASSWORD")
        if not self.account or not self.password:
            raise SystemExit("請先設定環境變數 YUANTA_ACCOUNT 與 YUANTA_PASSWORD")
        self.verbose = verbose
        self._lock = threading.Lock()
        self._waiting: dict[str, tuple[threading.Event, list]] = {}
        # 官方限制:報價類同功能每秒 3 次、K 線每秒 1 次;保守一點
        self._rl_quote = RateLimiter(0.5)
        self._rl_kline = RateLimiter(1.2)
        self.api = None

    # ---- 事件 ----
    def _on_response(self, intMark, dwIndex, strIndex, objHandle, objValue):
        try:
            if intMark == 0:
                if self.verbose:
                    print(f"[系統] {objValue}")
                return
            if intMark != 1:
                return
            with self._lock:
                w = self._waiting.get(strIndex)
            if w:
                w[1].append(objValue)
                w[0].set()
            elif self.verbose and strIndex:
                print(f"[回應] {strIndex}: {objValue}")
        except Exception as e:  # 事件內不能丟例外
            print(f"[事件處理錯誤] {e}")

    def _call(self, name: str, fn, timeout: float = 20):
        ev, box = threading.Event(), []
        with self._lock:
            self._waiting[name] = (ev, box)
        try:
            fn()
            if not ev.wait(timeout):
                raise TimeoutError(f"{name} 等待逾時")
            return box[0]
        finally:
            with self._lock:
                self._waiting.pop(name, None)

    # ---- 連線 ----
    def __enter__(self):
        _load_dll()
        self.api = YuantaSparkAPITrader()
        self.api.OnResponse += OnResponseEventHandler(self._on_response)
        self.api.SetLogType(enumLogType.COMMON)
        self.api.Open(enumEnvironmentMode.PROD)
        time.sleep(2)
        r = self._call("Login", lambda: self.api.Login(self.account, self.password))
        st = r.LoginStatus
        if st.MsgCode not in ("0001", "00001") and st.Count == 0:
            self.close()
            raise SystemExit(f"登入失敗:{st.MsgCode} {st.MsgContent}")
        if self.verbose:
            print(f"登入成功:{st.MsgCode}")
        time.sleep(2)
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.api is None:
            return
        try:
            self.api.LogOut()
            self.api.Close()
            self.api.Dispose()
        except Exception as e:
            print(f"關閉時錯誤:{e}")
        self.api = None

    # ---- 查詢 ----
    @staticmethod
    def _mkt(market: str):
        m = market.lower()
        if m in ("otc", "twotc", "上櫃"):
            return enumMarketType.TWOTC
        if m in ("emg", "twemerging", "興櫃"):
            return enumMarketType.TWEMERGING
        return enumMarketType.TWSE

    def quotes(self, items: list[tuple[str, str]], chunk: int = 200) -> list[dict]:
        """報價表查詢。items = [(代碼, 'tse'|'otc'), ...]。回傳 dict 清單。"""
        out = []
        for i in range(0, len(items), chunk):
            ql = List[Quote]()
            for code, mkt in items[i : i + chunk]:
                q = Quote()
                q.MarketType = self._mkt(mkt)
                q.StockCode = code
                ql.Add(q)
            self._rl_quote.wait()
            r = self._call("GetWatchListAll", lambda: self.api.GetWatchListAll(self.account, ql))
            lst = r.QueryWatchList
            for j in range(lst.Count):
                w = lst[j]
                t = w.Time
                out.append(
                    {
                        "code": str(w.StkCode).strip(),
                        "name": str(w.StkName).strip(),
                        "industry": str(w.IndustryName).strip(),
                        "market": str(w.MarketNo),
                        "yst": float(w.YstPrice),
                        "open": float(w.OpenPrice),
                        "high": float(w.HighPrice),
                        "low": float(w.LowPrice),
                        "deal": float(w.DealPrice),
                        "bid": float(w.BuyPrice),
                        "ask": float(w.SellPrice),
                        "up": float(w.UpStopPrice),
                        "down": float(w.DownStopPrice),
                        "vol": int(w.Vol),
                        "total_vol": int(w.TotalVol),
                        "out_vol": int(w.TotalOutVol),
                        "in_vol": int(w.TotalInVol),
                        "time": f"{t.Hour:02d}:{t.Minute:02d}:{t.Second:02d}",
                    }
                )
        return out

    def daily_kline(self, code: str, market: str, start: str, end: str) -> list[dict]:
        """日K。start/end 格式 'YYYY/MM/DD'。回傳 [{date, open, high, low, close, vol}],日期 'YYYY-MM-DD'。"""
        self._rl_kline.wait()
        # 注意:start~end 超過約 365 天時 API 不回應,只會逾時
        r = self._call(
            "GetKLine",
            lambda: self.api.GetKLine(self.account, KLineType(11), self._mkt(market), code, start, end),
            timeout=8,
        )
        kl = r.KLineList
        bars = []
        if kl is None:  # 查無資料(例如新上市)
            return bars
        for i in range(kl.Count):
            k = kl[i]
            ts = k.TimeStamp
            try:
                d = f"{ts.Year:04d}-{ts.Month:02d}-{ts.Day:02d}"
            except AttributeError:
                d = str(ts).split()[0].replace("/", "-")
            bars.append(
                {
                    "date": d,
                    "open": float(k.OpenPrice),
                    "high": float(k.HighPrice),
                    "low": float(k.LowPrice),
                    "close": float(k.ClosePrice),
                    "vol": int(k.DealVol),
                }
            )
        return bars
