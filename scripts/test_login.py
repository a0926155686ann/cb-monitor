"""最小測試：連線 → 登入 → 查一檔報價與日K → 登出。

只呼叫查詢函式，不含任何下單、條件單、圈存功能。
帳號密碼從環境變數 YUANTA_ACCOUNT / YUANTA_PASSWORD 讀取，不印出。

用法：
    python scripts\test_login.py            # 預設查 2330(上市)
    python scripts\test_login.py 6223 otc   # 查上櫃股票
"""
import os
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

API_DIR = Path(os.environ.get("YUANTA_API_DIR", r"C:\YuantaSparkAPI_win-x64_Python"))
ACCOUNT = os.environ.get("YUANTA_ACCOUNT", "")
PASSWORD = os.environ.get("YUANTA_PASSWORD", "")

if not ACCOUNT or not PASSWORD:
    sys.exit("請先設定環境變數 YUANTA_ACCOUNT 與 YUANTA_PASSWORD(設定後需開新的 PowerShell 視窗)")

STOCK = sys.argv[1] if len(sys.argv) > 1 else "2330"
MARKET = sys.argv[2].lower() if len(sys.argv) > 2 else "tse"

# ---- 載入元件 ----
from pythonnet import load  # noqa: E402

load("coreclr")
import clr  # noqa: E402

sys.path.append(str(API_DIR))
os.add_dll_directory(str(API_DIR))
clr.AddReference("System.Collections")
clr.AddReference("YuantaSparkAPI")
from System.Collections.Generic import List  # noqa: E402
from YuantaOneAPI import (  # noqa: E402
    KLineType,
    OnResponseEventHandler,
    Quote,
    YuantaSparkAPITrader,
    enumEnvironmentMode,
    enumLogType,
    enumMarketType,
)

MKT = enumMarketType.TWOTC if MARKET in ("otc", "twotc", "上櫃") else enumMarketType.TWSE

# ---- 非同步回應：用 Event 等結果 ----
results: dict[str, object] = {}
events = {k: threading.Event() for k in ("Login", "GetWatchListAll", "GetKLine")}


def on_response(intMark, dwIndex, strIndex, objHandle, objValue):
    try:
        if intMark == 0:  # 系統訊息
            print(f"[系統] {objValue}")
        elif intMark == 1 and strIndex in events:
            results[strIndex] = objValue
            events[strIndex].set()
        elif intMark == 1:
            print(f"[回應] {strIndex}: {objValue}")
    except Exception as e:  # 事件內例外不能往外丟
        print(f"[事件處理錯誤] {e}")


def wait(name: str, timeout: float = 15) -> object | None:
    if not events[name].wait(timeout):
        print(f"✗ {name} 等待逾時({timeout} 秒)")
        return None
    return results[name]


api = YuantaSparkAPITrader()
api.OnResponse += OnResponseEventHandler(on_response)
api.SetLogType(enumLogType.COMMON)

try:
    # 1. 連線正式環境
    print("連線中(正式環境)…")
    api.Open(enumEnvironmentMode.PROD)
    time.sleep(2)

    # 2. 登入(只印結果代碼,不印姓名/身分證)
    print("登入中…")
    api.Login(ACCOUNT, PASSWORD)
    r = wait("Login")
    if r is None:
        sys.exit(1)
    st = r.LoginStatus
    print(f"登入結果:{st.MsgCode} {st.MsgContent}(帳號筆數 {st.Count})")
    if st.MsgCode not in ("0001", "00001") and st.Count == 0:
        sys.exit("✗ 登入失敗,請確認帳號、電子密碼、憑證是否已匯入、API 是否已開通")
    time.sleep(2)  # 官方建議登入後稍等

    # 3. 報價表查詢
    print(f"\n查詢報價:{STOCK}({MKT})")
    ql = List[Quote]()
    q = Quote()
    q.MarketType = MKT
    q.StockCode = STOCK
    ql.Add(q)
    api.GetWatchListAll(ACCOUNT, ql)
    r = wait("GetWatchListAll")
    if r is not None:
        lst = r.QueryWatchList
        if lst.Count == 0:
            print("✗ 查無資料(代碼或市場別可能不對)")
        for i in range(lst.Count):
            w = lst[i]
            t = w.Time
            print(f"  {w.StkCode} {w.StkName} 產業:{w.IndustryName}")
            print(f"  成交 {w.DealPrice}  昨收 {w.YstPrice}  開 {w.OpenPrice}  高 {w.HighPrice}  低 {w.LowPrice}")
            print(f"  漲停 {w.UpStopPrice}  跌停 {w.DownStopPrice}  總量 {w.TotalVol}  小數位 {w.Decimal}")
            print(f"  時間 {t.Hour}:{t.Minute:02d}:{t.Second:02d}")
    time.sleep(1)

    # 4. 日K(近 15 天,取前五個交易日最高價)
    end = date.today()
    start = end - timedelta(days=15)
    print(f"\n查詢日K:{start} ~ {end}")
    api.GetKLine(ACCOUNT, KLineType(11), MKT, STOCK, start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d"))
    r = wait("GetKLine")
    if r is not None:
        kl = r.KLineList
        rows = [kl[i] for i in range(kl.Count)]
        print(f"  共 {len(rows)} 根")
        for k in rows:
            print(f"  {k.TimeStamp}  開 {k.OpenPrice}  高 {k.HighPrice}  低 {k.LowPrice}  收 {k.ClosePrice}  量 {k.DealVol}")
finally:
    print("\n登出並關閉連線")
    try:
        api.LogOut()
        api.Close()
        api.Dispose()
    except Exception as e:
        print(f"關閉時錯誤:{e}")
