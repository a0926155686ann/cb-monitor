"""環境檢查：只載入 YuantaSparkAPI.dll，不連線、不登入、不下單。"""
import os
import sys
from pathlib import Path

API_DIR = Path(os.environ.get("YUANTA_API_DIR", r"C:\YuantaSparkAPI_win-x64_Python"))

print(f"Python {sys.version.split()[0]} ({'64' if sys.maxsize > 2**32 else '32'} 位元)")
print(f"API 目錄: {API_DIR} {'存在' if (API_DIR / 'YuantaSparkAPI.dll').exists() else '找不到 YuantaSparkAPI.dll'}")

from pythonnet import load

load("coreclr")
import clr  # noqa: E402

sys.path.append(str(API_DIR))
os.add_dll_directory(str(API_DIR))
clr.AddReference("YuantaSparkAPI")

from YuantaOneAPI import KLineType, Quote, YuantaSparkAPITrader, enumEnvironmentMode, enumMarketType  # noqa: E402,F401

print("YuantaSparkAPI.dll 載入成功")
import System  # noqa: E402

print("市場代碼 enumMarketType:", list(System.Enum.GetNames(clr.GetClrType(enumMarketType))))
for name in ("YUANTA_ACCOUNT", "YUANTA_PASSWORD"):
    print(f"環境變數 {name}: {'已設定' if os.environ.get(name) else '未設定'}")
