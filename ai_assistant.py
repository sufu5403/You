# -*- coding: utf-8 -*-
"""
================================================================================
  現代化科技風格 Windows 桌面個人智慧助理
  ----------------------------------------------------------------------------
  技術棧：
    - GUI       : customtkinter (dark / blue)
    - AI 大腦   : google-genai SDK (gemini-3.6-flash，文字模式) +
                  Gemini Live API (gemini-3.1-flash-live-preview，通話模式即時語音)
    - 系統控制  : shutdown / subprocess / webbrowser
  功能：
    - 文字模式（打字對話）與通話模式（Gemini Live 即時雙向語音，支援隨時插話打斷）
    - 螢幕懸浮膠囊 (Picture-in-Picture)
    - 排程關機 / 分鐘倒數關機 / 取消關機（文字或語音跟鎮宇說即可，無專屬按鈕）
    - 開啟瀏覽器 / 開啟應用程式
    - 瀏覽器自動化操控（點擊、輸入文字、捲動、讀取頁面內容）
    - 電腦層級滑鼠/鍵盤自動化（不限瀏覽器，操作前彈窗二次確認，可於設定關閉）
  打包建議：
    pyinstaller --noconsole --onefile --collect-all customtkinter ai_assistant.py
================================================================================
"""

import os
import sys
import json
import time
import threading
import subprocess
import webbrowser
import platform
from datetime import datetime, timedelta

import customtkinter as ctk

# ------------------------------------------------------------------------
# google-genai SDK
#   pip install google-genai
# ------------------------------------------------------------------------
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# ------------------------------------------------------------------------
# pyaudio + asyncio：Gemini Live 即時語音通話所需的音訊串流與非同步事件迴圈
#   pip install pyaudio
#   （Windows 上若直接 pip install pyaudio 失敗，可改用：
#     pip install pipwin && pipwin install pyaudio）
# ------------------------------------------------------------------------
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

import asyncio

# ------------------------------------------------------------------------
# Selenium：讓 AI 真正操控瀏覽器（點擊、輸入文字、捲動、讀取頁面內容）
#   pip install selenium webdriver-manager
#   （webdriver-manager 會自動下載對應版本的 chromedriver，不用手動配置）
# ------------------------------------------------------------------------
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False

# ------------------------------------------------------------------------
# pyautogui：電腦層級的滑鼠 / 鍵盤自動化（不限於瀏覽器）
#   pip install pyautogui pyperclip
#   pyperclip 用於輸入中文等非英數文字（透過剪貼簿貼上，
#   因為 pyautogui.typewrite 本身只支援英數字元）
# ------------------------------------------------------------------------
try:
    import pyautogui
    pyautogui.FAILSAFE = True   # 安全機制：滑鼠移到螢幕左上角(0,0)可強制中斷自動化
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False


# ============================================================================
# ▼▼▼ 使用者設定區（請在此填入你的金鑰 / 反代網址）▼▼▼
# ============================================================================
GEMINI_API_KEY = "AQ.Ab8RN6LufaNAh2h6ChcUIFTcTI_OnXESDMRDswVKgqUbnJ0P4A"     # <-- 你的 Gemini API Key
PROXY_BASE_URL = ""                              # <-- 若使用反代中繼站，請填入 base_url，例如：
                                                  #     "https://your-proxy-domain.com/v1"
                                                  #     留空則使用官方預設端點
MODEL_NAME = "gemini-3.6-flash"
ASSISTANT_NAME = "鎮宇"

# 電腦層級操作（滑鼠移動/點擊、鍵盤輸入/組合鍵）是否需要彈窗跳出並等待你按「允許」才執行。
#   True  ：跳出確認視窗，需你手動按下「允許執行」才會真的動作（較安全，預設值）
#   False ：不阻擋、直接執行，只在聊天視窗留下一則「正在執行：xxx」的提示訊息讓你知情
# 注意：關掉之後，鎮宇對滑鼠鍵盤的操作將不會再等你同意，請自行評估風險後再關閉。
REQUIRE_ACTION_CONFIRMATION = True
# ============================================================================
# ▲▲▲ 使用者設定區 ▲▲▲
# ============================================================================


IS_WINDOWS = platform.system() == "Windows"


# ============================================================================
#  電腦層級操作的「使用者確認」機制
#  ----------------------------------------------------------------------
#  滑鼠移動/點擊、鍵盤輸入等操作風險較高（會影響使用者當下正在做的任何事），
#  因此每次執行前都會透過此機制彈出確認視窗，阻塞等待使用者按下「允許」或
#  「拒絕」，逾時則視為拒絕。彈窗必須在 GUI 主執行緒建立，因此這裡透過
#  app.after(0, ...) 把顯示彈窗的工作排程回主執行緒，本身則在呼叫端
#  （背景執行緒）阻塞等待結果。
# ============================================================================

_app_ref = {"app": None}


def register_app_instance(app):
    """讓工具函式能夠存取目前執行中的 AssistantApp 實例（用於彈出確認視窗/提示訊息）。"""
    _app_ref["app"] = app


def notify_action(description: str):
    """
    在聊天視窗留下一則不需要使用者回應的提示訊息（非阻塞）。
    用於 REQUIRE_ACTION_CONFIRMATION = False 時的「事後告知」，
    或是像開啟應用程式這類低風險操作的「事前警告」。
    """
    app = _app_ref.get("app")
    if app is not None:
        app.after(0, lambda: app._append_bubble(f"ℹ️ {description}", is_user=False))


def request_user_confirmation(action_description: str, timeout: float = 30.0) -> bool:
    """
    依照 REQUIRE_ACTION_CONFIRMATION 設定決定行為：
      - True ：彈出確認視窗並阻塞等待使用者回應；逾時或找不到 App 實例視為拒絕（安全預設）
      - False：不阻擋，僅留下一則提示訊息，直接視為允許
    必須在背景執行緒中呼叫。
    """
    if not REQUIRE_ACTION_CONFIRMATION:
        notify_action(f"正在執行：{action_description}")
        return True

    app = _app_ref.get("app")
    if app is None:
        return False

    event = threading.Event()
    result = {"approved": False}

    app.after(0, lambda: app._show_confirmation_dialog(action_description, event, result))
    event.wait(timeout=timeout)
    return result["approved"]


# ============================================================================
#  系統底層控制工具函式 (Function Calling 實際執行邏輯)
# ============================================================================

def _run_shutdown_command(seconds: int) -> str:
    """底層執行 shutdown /s /f /t <seconds>"""
    if not IS_WINDOWS:
        return f"[模擬環境] 非 Windows 系統，無法真的關機。若在 Windows 上，將於 {seconds} 秒後關機。"
    try:
        subprocess.Popen(
            ["shutdown", "/s", "/f", "/t", str(seconds)],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return f"已成功排程，將於 {seconds} 秒後關機。"
    except Exception as e:
        return f"執行關機指令時發生錯誤：{e}"


def schedule_shutdown(target_time_str: str) -> str:
    """
    指定時間關機。
    Args:
        target_time_str: 目標時間，格式為 HH:MM（24 小時制），例如 "23:30"
    """
    try:
        now = datetime.now()
        target = datetime.strptime(target_time_str, "%H:%M")
        target = now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
        if target <= now:
            # 如果目標時間已經過了，代表是明天的這個時間
            target += timedelta(days=1)
        diff_seconds = int((target - now).total_seconds())
        if diff_seconds <= 0:
            diff_seconds = 1
        result = _run_shutdown_command(diff_seconds)
        return f"{result}（目標時間：{target.strftime('%Y-%m-%d %H:%M')}，倒數約 {diff_seconds // 60} 分鐘）"
    except Exception as e:
        return f"解析時間格式失敗，請使用 HH:MM 格式（例如 23:30）。錯誤：{e}"


def shutdown_in_minutes(minutes: int) -> str:
    """
    幾分鐘後關機。
    Args:
        minutes: 幾分鐘後執行關機
    """
    try:
        minutes = int(minutes)
        seconds = max(1, minutes * 60)
        result = _run_shutdown_command(seconds)
        return f"{result}（將於 {minutes} 分鐘後關機）"
    except Exception as e:
        return f"設定倒數關機失敗：{e}"


def cancel_shutdown() -> str:
    """取消目前已排程的關機。"""
    if not IS_WINDOWS:
        return "[模擬環境] 非 Windows 系統，沒有實際排程可取消。"
    try:
        subprocess.Popen(
            ["shutdown", "/a"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return "已取消排程關機。"
    except Exception as e:
        return f"取消關機時發生錯誤（可能目前沒有排程中的關機）：{e}"


def open_browser(url_or_keyword: str) -> str:
    """
    開啟瀏覽器，前往指定網址，或以關鍵字進行 Google 搜尋。
    Args:
        url_or_keyword: 網址（如 https://www.google.com）或搜尋關鍵字（如 "台北天氣"）
    """
    try:
        text = url_or_keyword.strip()
        if text.startswith("http://") or text.startswith("https://"):
            url = text
        elif "." in text and " " not in text:
            url = "https://" + text
        else:
            url = "https://www.google.com/search?q=" + text.replace(" ", "+")
        webbrowser.open(url)
        return f"已為您開啟瀏覽器：{url}"
    except Exception as e:
        return f"開啟瀏覽器失敗：{e}"


# 常見應用程式名稱對應表（可自行擴充）
APP_ALIAS_MAP = {
    "小算盤": "calc",
    "計算機": "calc",
    "記事本": "notepad",
    "小畫家": "mspaint",
    "小畫家3d": "mspaint",
    "檔案總管": "explorer",
    "工作管理員": "taskmgr",
    "命令提示字元": "cmd",
    "終端機": "wt",
    "控制台": "control",
}


def open_app(app_name: str) -> str:
    """
    開啟 Windows 應用程式。
    Args:
        app_name: 應用程式名稱，例如 notepad、calc、mspaint，或中文別名如「記事本」「小算盤」
    """
    try:
        key = app_name.strip().lower()
        exe = APP_ALIAS_MAP.get(app_name.strip(), None) or APP_ALIAS_MAP.get(key, None) or app_name.strip()
        notify_action(f"即將開啟應用程式：{exe}")
        if not IS_WINDOWS:
            return f"[模擬環境] 非 Windows 系統，無法實際啟動「{exe}」。"
        subprocess.Popen(exe, shell=True)
        return f"已為您開啟應用程式：{exe}"
    except Exception as e:
        return f"開啟應用程式「{app_name}」失敗：{e}"


# ============================================================================
#  瀏覽器自動化控制（Selenium）—— 讓 AI 真正「操作」瀏覽器
#  與 open_browser() 不同：open_browser() 只是用系統預設瀏覽器開一個新分頁；
#  這裡是啟動一個獨立、由程式完全掌控的 Chrome 視窗，可以點擊、輸入文字、
#  捲動、讀取頁面內容，供 AI 依照頁面實際狀況決定下一步動作。
# ============================================================================

class BrowserController:
    """
    封裝 Selenium WebDriver，維護單一瀏覽器視窗的生命週期。
    所有操作皆用 threading.Lock 保護，避免多執行緒同時操作同一個 driver。
    """

    def __init__(self):
        self.driver = None
        self.available = SELENIUM_AVAILABLE
        self.error = None if SELENIUM_AVAILABLE else (
            "尚未安裝瀏覽器自動化套件，請執行：pip install selenium webdriver-manager"
        )
        self._lock = threading.Lock()

    def _ensure_driver(self):
        """確保有一個可用的 driver；若已存在且還活著就直接沿用（維持同一個瀏覽器視窗）。"""
        if self.driver is not None:
            try:
                _ = self.driver.title  # 探測 driver 是否仍然存活（例如視窗被手動關掉會拋例外）
                return
            except Exception:
                self.driver = None

        options = ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        if WEBDRIVER_MANAGER_AVAILABLE:
            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        else:
            # 退而求其次：假設系統 PATH 中已經有相容版本的 chromedriver.exe
            self.driver = webdriver.Chrome(options=options)

    @staticmethod
    def _xpath_literal(text: str) -> str:
        """把使用者提供的文字安全地轉成 XPath 字串常值（處理內含單引號的情況）。"""
        if "'" not in text:
            return f"'{text}'"
        if '"' not in text:
            return f'"{text}"'
        parts = text.split("'")
        return "concat('" + "', \"'\", '".join(parts) + "')"

    def navigate(self, url_or_keyword: str) -> str:
        if not self.available:
            raise RuntimeError(self.error)
        with self._lock:
            self._ensure_driver()
            text = url_or_keyword.strip()
            if text.startswith("http://") or text.startswith("https://"):
                url = text
            elif "." in text and " " not in text:
                url = "https://" + text
            else:
                url = "https://www.google.com/search?q=" + text.replace(" ", "+")
            self.driver.get(url)
            time.sleep(1.2)  # 等待頁面初步載入完成
            return f"已導覽至：{self.driver.title or url}"

    def click_by_text(self, text: str) -> str:
        if not self.available or self.driver is None:
            raise RuntimeError("瀏覽器尚未開啟，請先呼叫 browser_navigate 開啟網頁。")
        with self._lock:
            literal = self._xpath_literal(text)
            xpath_priority = (
                "//*[self::a or self::button or @role='button' or @type='submit' "
                f"or @type='button'][contains(normalize-space(.), {literal})]"
            )
            elements = [e for e in self.driver.find_elements(By.XPATH, xpath_priority) if e.is_displayed()]
            if not elements:
                xpath_fallback = f"//*[contains(normalize-space(.), {literal})]"
                elements = [e for e in self.driver.find_elements(By.XPATH, xpath_fallback) if e.is_displayed()]
            if not elements:
                return f"找不到包含文字「{text}」且可見的可點擊元素。"
            elements[0].click()
            time.sleep(0.8)
            return f"已點擊包含「{text}」的元素。"

    def type_text(self, value: str, field_hint: str = "") -> str:
        if not self.available or self.driver is None:
            raise RuntimeError("瀏覽器尚未開啟，請先呼叫 browser_navigate 開啟網頁。")
        with self._lock:
            target = None
            candidates = [
                el for el in self.driver.find_elements(By.XPATH, "//input | //textarea")
                if el.is_displayed()
            ]
            if field_hint:
                hint_lower = field_hint.lower()
                for el in candidates:
                    attrs = " ".join([
                        el.get_attribute("placeholder") or "",
                        el.get_attribute("name") or "",
                        el.get_attribute("id") or "",
                        el.get_attribute("aria-label") or "",
                    ]).lower()
                    if hint_lower in attrs:
                        target = el
                        break
            if target is None and candidates:
                target = candidates[0]
            if target is None:
                return "目前頁面上找不到可輸入文字的欄位。"
            target.click()
            target.clear()
            target.send_keys(value)
            return f"已在輸入欄位填入：{value}"

    def press_enter(self) -> str:
        if not self.available or self.driver is None:
            raise RuntimeError("瀏覽器尚未開啟，請先呼叫 browser_navigate 開啟網頁。")
        with self._lock:
            try:
                el = self.driver.switch_to.active_element
                el.send_keys(Keys.ENTER)
                time.sleep(0.8)
                return "已送出（模擬按下 Enter）。"
            except Exception as e:
                return f"送出失敗：{e}"

    def scroll(self, direction: str = "down") -> str:
        if not self.available or self.driver is None:
            raise RuntimeError("瀏覽器尚未開啟，請先呼叫 browser_navigate 開啟網頁。")
        with self._lock:
            amount = -700 if direction == "up" else 700
            self.driver.execute_script(f"window.scrollBy(0, {amount});")
            return f"已向{'上' if amount < 0 else '下'}捲動頁面。"

    def get_page_summary(self, max_chars: int = 1200) -> str:
        if not self.available or self.driver is None:
            raise RuntimeError("瀏覽器尚未開啟，請先呼叫 browser_navigate 開啟網頁。")
        with self._lock:
            title = self.driver.title
            url = self.driver.current_url
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
            except Exception:
                body_text = ""
            snippet = body_text[:max_chars]
            return f"頁面標題：{title}\n網址：{url}\n內容摘要：\n{snippet}"

    def close(self) -> str:
        with self._lock:
            if self.driver is not None:
                try:
                    self.driver.quit()
                except Exception:
                    pass
                self.driver = None
            return "已關閉自動化瀏覽器視窗。"


# 全域唯一的瀏覽器控制器實例
browser_controller = BrowserController()


def browser_navigate(url_or_keyword: str) -> str:
    """
    開啟（或沿用既有的）自動化瀏覽器視窗，並導覽至指定網址或關鍵字搜尋結果。
    Args:
        url_or_keyword: 網址或搜尋關鍵字
    """
    try:
        return browser_controller.navigate(url_or_keyword)
    except Exception as e:
        return f"瀏覽器導覽失敗：{e}"


def browser_click(text: str) -> str:
    """
    在目前自動化瀏覽器頁面上，點擊包含指定文字的連結或按鈕。
    Args:
        text: 要點擊的元素上顯示的文字，例如「登入」「下一步」「立即購買」
    """
    try:
        return browser_controller.click_by_text(text)
    except Exception as e:
        return f"點擊失敗：{e}"


def browser_type_text(value: str, field_hint: str = "") -> str:
    """
    在目前自動化瀏覽器頁面的輸入欄位中填入文字。
    Args:
        value: 要輸入的文字內容
        field_hint: （選填）用來辨識目標欄位的提示，例如欄位的 placeholder、
                    名稱或用途描述（如「搜尋」「帳號」「email」）；留空則填入頁面上第一個可見輸入框
    """
    try:
        return browser_controller.type_text(value, field_hint)
    except Exception as e:
        return f"輸入文字失敗：{e}"


def browser_press_enter() -> str:
    """在目前聚焦的輸入欄位模擬按下 Enter 鍵，常用於送出搜尋或表單。"""
    try:
        return browser_controller.press_enter()
    except Exception as e:
        return f"送出失敗：{e}"


def browser_scroll(direction: str = "down") -> str:
    """
    捲動目前自動化瀏覽器頁面。
    Args:
        direction: 捲動方向，"down"（向下，預設）或 "up"（向上）
    """
    try:
        return browser_controller.scroll(direction)
    except Exception as e:
        return f"捲動失敗：{e}"


def browser_get_page_summary() -> str:
    """讀取目前自動化瀏覽器頁面的標題、網址與內容摘要，讓 AI 了解頁面上實際有什麼，再決定下一步操作。"""
    try:
        return browser_controller.get_page_summary()
    except Exception as e:
        return f"讀取頁面內容失敗：{e}"


def browser_close() -> str:
    """關閉目前的自動化瀏覽器視窗。"""
    try:
        return browser_controller.close()
    except Exception as e:
        return f"關閉瀏覽器失敗：{e}"


# ============================================================================
#  電腦層級控制（滑鼠 / 鍵盤自動化，不限於瀏覽器）
#  每個會實際操作滑鼠/鍵盤的工具，執行前都會呼叫 request_user_confirmation()
#  跳出確認視窗，使用者必須按「允許」才會真的執行，拒絕或逾時一律取消。
# ============================================================================

def _ensure_pyautogui():
    if not PYAUTOGUI_AVAILABLE:
        raise RuntimeError("尚未安裝電腦自動化套件，請執行：pip install pyautogui pyperclip")


def get_screen_size() -> str:
    """取得目前螢幕解析度（唯讀，不需使用者確認）。"""
    try:
        _ensure_pyautogui()
        w, h = pyautogui.size()
        return f"目前螢幕解析度為 {w} x {h}。"
    except Exception as e:
        return f"取得螢幕大小失敗：{e}"


def take_screenshot() -> str:
    """
    截取目前整個螢幕畫面並存成圖片檔（唯讀操作，不需使用者確認）。
    存放於使用者桌面，檔名包含時間戳記。
    """
    try:
        _ensure_pyautogui()
        target_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(target_dir):
            target_dir = os.getcwd()
        filename = f"assistant_screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        filepath = os.path.join(target_dir, filename)
        pyautogui.screenshot().save(filepath)
        return f"已截圖並儲存至：{filepath}"
    except Exception as e:
        return f"截圖失敗：{e}"


def mouse_move(x: int, y: int) -> str:
    """
    移動滑鼠到指定螢幕座標（不點擊）。需使用者確認。
    Args:
        x, y: 目標螢幕座標
    """
    try:
        _ensure_pyautogui()
        x, y = int(x), int(y)
        if not request_user_confirmation(f"將滑鼠移動到座標 ({x}, {y})"):
            return "使用者拒絕了這個操作，已取消。"
        pyautogui.moveTo(x, y, duration=0.3)
        return f"已將滑鼠移動到 ({x}, {y})。"
    except Exception as e:
        return f"移動滑鼠失敗：{e}"


def mouse_click(x: int = None, y: int = None, button: str = "left", double: bool = False) -> str:
    """
    在指定座標（或目前滑鼠位置）執行滑鼠點擊。需使用者確認。
    Args:
        x, y: 目標座標（留空則在目前游標位置點擊）
        button: 'left'、'right' 或 'middle'
        double: 是否雙擊
    """
    try:
        _ensure_pyautogui()
        has_pos = x is not None and y is not None
        if has_pos:
            x, y = int(x), int(y)
        pos_desc = f"({x}, {y})" if has_pos else "目前游標位置"
        action = "雙擊" if double else "點擊"
        if not request_user_confirmation(f"在 {pos_desc} 執行滑鼠{button}鍵{action}"):
            return "使用者拒絕了這個操作，已取消。"
        kwargs = {"button": button}
        if has_pos:
            kwargs["x"], kwargs["y"] = x, y
        if double:
            pyautogui.doubleClick(**kwargs)
        else:
            pyautogui.click(**kwargs)
        return f"已在 {pos_desc} 執行{action}。"
    except Exception as e:
        return f"滑鼠點擊失敗：{e}"


def mouse_scroll(amount: int) -> str:
    """
    捲動滑鼠滾輪。需使用者確認。
    Args:
        amount: 正數向上捲動，負數向下捲動
    """
    try:
        _ensure_pyautogui()
        amount = int(amount)
        if not request_user_confirmation(f"捲動滑鼠滾輪 {amount} 單位"):
            return "使用者拒絕了這個操作，已取消。"
        pyautogui.scroll(amount)
        return f"已捲動 {amount} 單位。"
    except Exception as e:
        return f"捲動失敗：{e}"


def keyboard_type(text: str) -> str:
    """
    模擬鍵盤輸入文字到目前作用中的視窗（支援中文，透過剪貼簿貼上）。需使用者確認。
    Args:
        text: 要輸入的文字
    """
    try:
        _ensure_pyautogui()
        if not request_user_confirmation(f"在目前作用中的視窗輸入文字：「{text}」"):
            return "使用者拒絕了這個操作，已取消。"
        if text.isascii():
            pyautogui.typewrite(text, interval=0.02)
        else:
            if not PYPERCLIP_AVAILABLE:
                return "輸入中文等非英數文字需要安裝 pyperclip：pip install pyperclip"
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        return f"已輸入文字：{text}"
    except Exception as e:
        return f"輸入文字失敗：{e}"


def keyboard_press(key: str) -> str:
    """
    模擬按下單一按鍵，例如 enter、esc、tab、f5、up、down、left、right、backspace。需使用者確認。
    Args:
        key: 按鍵名稱
    """
    try:
        _ensure_pyautogui()
        if not request_user_confirmation(f"按下按鍵：{key}"):
            return "使用者拒絕了這個操作，已取消。"
        pyautogui.press(key)
        return f"已按下按鍵：{key}"
    except Exception as e:
        return f"按鍵操作失敗：{e}"


def keyboard_hotkey(keys: str) -> str:
    """
    模擬組合鍵，例如 "ctrl+c"、"ctrl+v"、"alt+tab"、"win+d"。需使用者確認。
    Args:
        keys: 用加號分隔的按鍵組合，例如 "ctrl+c"
    """
    try:
        _ensure_pyautogui()
        key_list = [k.strip() for k in keys.split("+") if k.strip()]
        if not key_list:
            return "未指定任何按鍵。"
        combo_desc = " + ".join(key_list)
        if not request_user_confirmation(f"執行組合鍵：{combo_desc}"):
            return "使用者拒絕了這個操作，已取消。"
        pyautogui.hotkey(*key_list)
        return f"已執行組合鍵：{combo_desc}"
    except Exception as e:
        return f"組合鍵操作失敗：{e}"


# 工具名稱 -> 實際函式 的對應表，供 Function Calling 分派使用
TOOL_FUNCTIONS = {
    "schedule_shutdown": schedule_shutdown,
    "shutdown_in_minutes": shutdown_in_minutes,
    "cancel_shutdown": cancel_shutdown,
    "open_browser": open_browser,
    "open_app": open_app,
    "browser_navigate": browser_navigate,
    "browser_click": browser_click,
    "browser_type_text": browser_type_text,
    "browser_press_enter": browser_press_enter,
    "browser_scroll": browser_scroll,
    "browser_get_page_summary": browser_get_page_summary,
    "browser_close": browser_close,
    "get_screen_size": get_screen_size,
    "take_screenshot": take_screenshot,
    "mouse_move": mouse_move,
    "mouse_click": mouse_click,
    "mouse_scroll": mouse_scroll,
    "keyboard_type": keyboard_type,
    "keyboard_press": keyboard_press,
    "keyboard_hotkey": keyboard_hotkey,
}


# ============================================================================
#  Gemini AI 大腦封裝
# ============================================================================

def build_shared_tools():
    """建立 Function Calling 的工具定義，文字模式（GeminiBrain）與語音模式（GeminiLiveController）共用。"""
    schedule_shutdown_decl = types.FunctionDeclaration(
        name="schedule_shutdown",
        description="在指定的今天或明天時間點執行電腦關機，時間格式為 HH:MM（24小時制）。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "target_time_str": {
                    "type": "STRING",
                    "description": "目標關機時間，24小時制字串，例如 '23:30' 或 '08:00'",
                }
            },
            "required": ["target_time_str"],
        },
    )

    shutdown_in_minutes_decl = types.FunctionDeclaration(
        name="shutdown_in_minutes",
        description="從現在開始，經過指定的分鐘數後關機。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "minutes": {
                    "type": "INTEGER",
                    "description": "幾分鐘後關機，例如 30",
                }
            },
            "required": ["minutes"],
        },
    )

    cancel_shutdown_decl = types.FunctionDeclaration(
        name="cancel_shutdown",
        description="取消目前已經排程但尚未執行的關機動作。",
        parameters={"type": "OBJECT", "properties": {}},
    )

    open_browser_decl = types.FunctionDeclaration(
        name="open_browser",
        description="開啟瀏覽器並前往指定網址，或使用關鍵字進行 Google 搜尋。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "url_or_keyword": {
                    "type": "STRING",
                    "description": "完整網址（含 http/https）或搜尋關鍵字",
                }
            },
            "required": ["url_or_keyword"],
        },
    )

    open_app_decl = types.FunctionDeclaration(
        name="open_app",
        description="開啟 Windows 應用程式，例如記事本、小算盤、小畫家等。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "應用程式名稱，例如 notepad、calc，或中文名稱如「記事本」",
                }
            },
            "required": ["app_name"],
        },
    )

    browser_navigate_decl = types.FunctionDeclaration(
        name="browser_navigate",
        description=(
            "開啟或沿用一個由程式完全掌控的自動化瀏覽器視窗，並導覽至指定網址或關鍵字搜尋。"
            "這與 open_browser 不同：open_browser 只是用系統預設瀏覽器開一個新分頁；"
            "而這個工具開出來的瀏覽器可以被 browser_click / browser_type_text 等工具繼續操作。"
            "想要『操控』網頁（點擊、輸入、瀏覽內容）時，請一律先呼叫這個工具。"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "url_or_keyword": {
                    "type": "STRING",
                    "description": "完整網址（含 http/https）或搜尋關鍵字",
                }
            },
            "required": ["url_or_keyword"],
        },
    )

    browser_click_decl = types.FunctionDeclaration(
        name="browser_click",
        description="在目前自動化瀏覽器頁面上，點擊包含指定文字的連結或按鈕。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "text": {
                    "type": "STRING",
                    "description": "要點擊的元素上顯示的文字，例如「登入」「下一步」「立即購買」",
                }
            },
            "required": ["text"],
        },
    )

    browser_type_text_decl = types.FunctionDeclaration(
        name="browser_type_text",
        description="在目前自動化瀏覽器頁面的輸入欄位中填入文字（例如搜尋框、表單欄位）。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "value": {
                    "type": "STRING",
                    "description": "要輸入的文字內容",
                },
                "field_hint": {
                    "type": "STRING",
                    "description": "（選填）辨識目標欄位的提示，例如「搜尋」「帳號」「email」；留空則填入頁面上第一個可見輸入框",
                },
            },
            "required": ["value"],
        },
    )

    browser_press_enter_decl = types.FunctionDeclaration(
        name="browser_press_enter",
        description="在目前聚焦的輸入欄位模擬按下 Enter 鍵，常用於送出搜尋或表單。",
        parameters={"type": "OBJECT", "properties": {}},
    )

    browser_scroll_decl = types.FunctionDeclaration(
        name="browser_scroll",
        description="捲動目前自動化瀏覽器頁面。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "direction": {
                    "type": "STRING",
                    "description": "捲動方向，'down'（向下，預設）或 'up'（向上）",
                }
            },
        },
    )

    browser_get_page_summary_decl = types.FunctionDeclaration(
        name="browser_get_page_summary",
        description=(
            "讀取目前自動化瀏覽器頁面的標題、網址與內容摘要。"
            "在執行 browser_click 或 browser_type_text 之前，建議先呼叫這個工具了解頁面上實際有什麼內容與可互動元素。"
        ),
        parameters={"type": "OBJECT", "properties": {}},
    )

    browser_close_decl = types.FunctionDeclaration(
        name="browser_close",
        description="關閉目前的自動化瀏覽器視窗。",
        parameters={"type": "OBJECT", "properties": {}},
    )

    get_screen_size_decl = types.FunctionDeclaration(
        name="get_screen_size",
        description="取得目前螢幕解析度（寬 x 高，像素）。在移動滑鼠或點擊特定座標前，建議先確認螢幕大小。",
        parameters={"type": "OBJECT", "properties": {}},
    )

    take_screenshot_decl = types.FunctionDeclaration(
        name="take_screenshot",
        description="截取目前整個螢幕畫面並存成圖片檔，回傳存放路徑，方便使用者事後查看畫面狀態。",
        parameters={"type": "OBJECT", "properties": {}},
    )

    mouse_move_decl = types.FunctionDeclaration(
        name="mouse_move",
        description="移動滑鼠游標到指定的螢幕座標（不點擊）。這是電腦層級操作，會跳出確認視窗給使用者。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "目標 X 座標（像素）"},
                "y": {"type": "INTEGER", "description": "目標 Y 座標（像素）"},
            },
            "required": ["x", "y"],
        },
    )

    mouse_click_decl = types.FunctionDeclaration(
        name="mouse_click",
        description="在指定座標（或目前游標位置）執行滑鼠點擊。這是電腦層級操作，會跳出確認視窗給使用者。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "x": {"type": "INTEGER", "description": "目標 X 座標，留空則在目前游標位置點擊"},
                "y": {"type": "INTEGER", "description": "目標 Y 座標，留空則在目前游標位置點擊"},
                "button": {"type": "STRING", "description": "'left'、'right' 或 'middle'，預設 left"},
                "double": {"type": "BOOLEAN", "description": "是否雙擊，預設 false"},
            },
        },
    )

    mouse_scroll_decl = types.FunctionDeclaration(
        name="mouse_scroll",
        description="捲動滑鼠滾輪（作用於目前作用中的視窗，不限瀏覽器）。這是電腦層級操作，會跳出確認視窗給使用者。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "amount": {"type": "INTEGER", "description": "正數向上捲動，負數向下捲動"},
            },
            "required": ["amount"],
        },
    )

    keyboard_type_decl = types.FunctionDeclaration(
        name="keyboard_type",
        description=(
            "模擬鍵盤輸入文字到目前作用中的視窗（支援中文）。"
            "這是電腦層級操作，作用範圍是使用者『目前聚焦』的任何程式視窗，不限瀏覽器。會跳出確認視窗給使用者。"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "要輸入的文字內容"},
            },
            "required": ["text"],
        },
    )

    keyboard_press_decl = types.FunctionDeclaration(
        name="keyboard_press",
        description="模擬按下單一按鍵，例如 enter、esc、tab、f5、up、down、left、right、backspace。這是電腦層級操作，會跳出確認視窗給使用者。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "按鍵名稱"},
            },
            "required": ["key"],
        },
    )

    keyboard_hotkey_decl = types.FunctionDeclaration(
        name="keyboard_hotkey",
        description="模擬組合鍵，例如 'ctrl+c'、'ctrl+v'、'alt+tab'、'win+d'。這是電腦層級操作，會跳出確認視窗給使用者。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "keys": {"type": "STRING", "description": "用加號分隔的按鍵組合，例如 'ctrl+c'"},
            },
            "required": ["keys"],
        },
    )

    return [
        types.Tool(
            function_declarations=[
                schedule_shutdown_decl,
                shutdown_in_minutes_decl,
                cancel_shutdown_decl,
                open_browser_decl,
                open_app_decl,
                browser_navigate_decl,
                browser_click_decl,
                browser_type_text_decl,
                browser_press_enter_decl,
                browser_scroll_decl,
                browser_get_page_summary_decl,
                browser_close_decl,
                get_screen_size_decl,
                take_screenshot_decl,
                mouse_move_decl,
                mouse_click_decl,
                mouse_scroll_decl,
                keyboard_type_decl,
                keyboard_press_decl,
                keyboard_hotkey_decl,
            ]
        )
    ]


def build_shared_system_instruction(voice_mode: bool = False) -> str:
    """
    建立 System Instruction，文字模式（GeminiBrain）與語音模式（GeminiLiveController）共用。
    Args:
        voice_mode: True 時會額外提醒模型目前是即時語音通話（回覆應簡短口語化，避免條列/長篇大論）。
    """
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
    weekday_str = weekday_map[now.weekday()]

    base = (
        f"你是一位名叫「{ASSISTANT_NAME}」的桌面語音助理，個性親切、簡潔、有效率，"
        f"以繁體中文回應使用者。\n"
        f"目前系統時間為：{now_str}（星期{weekday_str}）。\n"
        f"當使用者提到與時間相關的關機需求時（例如「晚點關機」「半小時後關機」「晚上11點關機」），"
        f"請你依照目前系統時間精準換算，並呼叫對應的工具函式完成任務，不要只用文字回答而不呼叫工具。\n"
        f"若使用者只是想『開啟』某個網站或搜尋資訊（不需要進一步互動），請用 open_browser。\n"
        f"若使用者想要你『操作』網頁——例如點擊按鈕、在欄位輸入文字、捲動頁面、幫忙填表單、"
        f"查詢頁面上的資訊——請改用 browser_navigate 開啟頁面，並視需要搭配 "
        f"browser_get_page_summary（先了解頁面內容）、browser_click、browser_type_text、"
        f"browser_press_enter、browser_scroll 等工具完成任務，完成後可視情況呼叫 browser_close。\n"
        f"操作瀏覽器時請每次只做一個明確步驟，並在必要時用 browser_get_page_summary 確認結果，"
        f"避免連續盲目點擊。\n"
        f"若使用者要求的是『電腦層級』的操作——控制瀏覽器以外的其他任意程式視窗，例如移動滑鼠、"
        f"點擊螢幕上特定座標、輸入文字到某個軟體、按組合鍵（如 alt+tab、ctrl+c）——請使用 "
        f"mouse_move、mouse_click、mouse_scroll、keyboard_type、keyboard_press、keyboard_hotkey "
        f"這些工具。這些操作會自動跳出視窗請使用者確認，你不需要事先用文字再三詢問是否要執行，"
        f"直接呼叫工具即可，系統會處理確認流程；若使用者拒絕，如實告知即可。"
        f"需要座標時可先呼叫 get_screen_size 了解螢幕大小，或用 take_screenshot 截圖供使用者確認畫面狀態。\n"
        f"若使用者想開啟應用程式，也請呼叫對應工具完成，而非只是用文字說明步驟。\n"
        f"完成工具呼叫後，請用簡短自然的口語向使用者確認結果。"
    )

    if voice_mode:
        base += (
            "\n目前是即時語音通話模式：使用者是用『說話』跟你互動，你的回覆也會直接用語音唸出來。"
            "請用簡短、口語化、像講電話一樣的方式回答，避免條列式清單或長篇大論；"
            "使用者隨時可能中途插話打斷你，這是正常現象，請自然銜接。"
        )

    return base


def dispatch_function_call(function_call) -> dict:
    """執行單一 function call，回傳結果 dict。文字模式與語音模式共用同一套分派邏輯。"""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"未知的工具：{name}"}
    try:
        result_text = func(**args)
        return {"result": result_text}
    except Exception as e:
        return {"error": f"執行工具 {name} 時發生例外：{e}"}


class GeminiBrain:
    """封裝 google-genai SDK 呼叫、動態 System Instruction 與 Function Calling 分派。"""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.model_name = model_name
        self.chat_history = []  # list[types.Content]
        self.client = None
        self.error = None

        if not GENAI_AVAILABLE:
            self.error = "尚未安裝 google-genai，請執行：pip install google-genai"
            return

        try:
            http_options = None
            if base_url:
                http_options = types.HttpOptions(base_url=base_url)

            if http_options:
                self.client = genai.Client(api_key=api_key, http_options=http_options)
            else:
                self.client = genai.Client(api_key=api_key)
        except Exception as e:
            self.error = f"初始化 Gemini Client 失敗：{e}"

    def send_message(self, user_text: str) -> str:
        """
        送出使用者訊息，處理可能的多輪 Function Calling，
        最終回傳可顯示給使用者的純文字回覆。
        此方法為同步阻塞呼叫，請務必在背景執行緒中呼叫。
        """
        if self.error:
            return f"[AI 初始化錯誤] {self.error}"
        if self.client is None:
            return "[AI 尚未就緒] 請檢查 API Key 與網路設定。"

        try:
            tools = build_shared_tools()
            system_instruction = build_shared_system_instruction()

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=tools,
            )

            self.chat_history.append(
                types.Content(role="user", parts=[types.Part(text=user_text)])
            )

            # 最多允許連續 5 輪 function calling，避免無窮迴圈
            for _ in range(5):
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=self.chat_history,
                    config=config,
                )

                candidate = response.candidates[0] if response.candidates else None
                if candidate is None:
                    return "抱歉，我暫時無法理解，請再說一次。"

                content = candidate.content
                self.chat_history.append(content)

                function_calls = []
                text_parts = []
                for part in content.parts:
                    if getattr(part, "function_call", None):
                        function_calls.append(part.function_call)
                    elif getattr(part, "text", None):
                        text_parts.append(part.text)

                if function_calls:
                    function_response_parts = []
                    for fc in function_calls:
                        result = dispatch_function_call(fc)
                        function_response_parts.append(
                            types.Part.from_function_response(
                                name=fc.name,
                                response=result,
                            )
                        )
                    # 把工具執行結果回傳給模型，讓它產生最終自然語言回覆
                    self.chat_history.append(
                        types.Content(role="user", parts=function_response_parts)
                    )
                    continue  # 進入下一輪，讓模型根據工具結果生成回覆
                else:
                    final_text = "".join(text_parts).strip()
                    return final_text if final_text else "好的。"

            return "任務處理輪數過多，已中止，請重新描述您的需求。"

        except Exception as e:
            return f"[AI 呼叫發生錯誤] {e}"


# ============================================================================
#  Gemini Live 即時語音對話引擎 —— 取代原本「錄音轉文字→問AI→轉語音」的拼接做法
#  ----------------------------------------------------------------------
#  通話模式下，麥克風收音會即時串流給 Gemini Live 模型，模型的語音回覆也是
#  即時串流播放，具備原生的語音活動偵測（VAD）與可隨時打斷（barge-in）的能力，
#  體感上更接近真的講電話，而不是「按下說話→等待→聽回覆」那種一問一答。
#
#  整個生命週期跑在獨立的背景執行緒 + 專屬的 asyncio event loop 中，
#  透過建構子傳入的 callback（都會安全地排程回 GUI 主執行緒）跟介面溝通狀態。
# ============================================================================

LIVE_MODEL_NAME = "gemini-3.1-flash-live-preview"  # Gemini 最新的即時語音（Audio-to-Audio）模型
LIVE_SEND_SAMPLE_RATE = 16000     # 送給模型的麥克風音訊取樣率（16-bit PCM, mono）
LIVE_RECEIVE_SAMPLE_RATE = 24000  # 模型回傳語音的取樣率
LIVE_CHUNK_SIZE = 1024


def list_input_devices():
    """
    列出系統上所有可用的麥克風（輸入）裝置。
    Returns:
        list[tuple[int, str]]：每個元素為 (裝置索引, 裝置名稱)。
        若 pyaudio 未安裝或列舉失敗，回傳空list。
    """
    if not PYAUDIO_AVAILABLE:
        return []
    devices = []
    pa = None
    try:
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append((i, info.get("name", f"裝置 {i}")))
    except Exception:
        pass
    finally:
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass
    return devices


class GeminiLiveController:
    """
    封裝 google-genai 的 Live API（client.aio.live.connect），
    負責：麥克風即時收音 → 串流送給模型、接收模型語音串流 → 即時播放，
    並支援與文字模式共用的 Function Calling 工具。
    """

    def __init__(self, api_key: str, base_url: str,
                 on_status_change=None, on_transcript=None, on_error=None):
        """
        Args:
            on_status_change: callback(connected: bool)，連線狀態改變時呼叫
            on_transcript: callback(role: str, text: str)，role 為 'user' 或 'model'，
                           有語音轉錄文字時呼叫（用來在聊天視窗顯示逐字稿）
            on_error: callback(message: str)，發生錯誤時呼叫
        """
        self.api_key = api_key
        self.base_url = base_url
        self.on_status_change = on_status_change
        self.on_transcript = on_transcript
        self.on_error = on_error

        self.available = GENAI_AVAILABLE and PYAUDIO_AVAILABLE
        self.error = None
        if not GENAI_AVAILABLE:
            self.error = "尚未安裝 google-genai，請執行：pip install google-genai"
        elif not PYAUDIO_AVAILABLE:
            self.error = "尚未安裝 pyaudio（即時語音需要），請執行：pip install pyaudio"

        self._pyaudio = None
        self._loop = None
        self._thread = None
        self._session = None
        self._mic_stream = None
        self._speaker_stream = None
        self._muted = False
        self._active = False
        self.input_device_index = None  # None = 使用系統預設麥克風

    # ------------------------------------------------------------------
    # 對外介面：啟動 / 停止 / 靜音切換 / 選擇麥克風
    # ------------------------------------------------------------------
    def set_input_device(self, device_index):
        """
        指定要使用的麥克風裝置索引（見 list_input_devices()）。
        傳入 None 代表改回使用系統預設麥克風。
        注意：若通話已經在進行中，需要結束通話再重新開始，設定才會生效
        （麥克風串流一旦開啟就固定使用當時的裝置）。
        """
        self.input_device_index = device_index

    def start(self):
        """啟動 Live 對話（建立新的背景執行緒 + asyncio event loop）。非阻塞。"""
        if not self.available:
            if self.on_error:
                self.on_error(self.error or "語音通話功能未啟用。")
            return
        if self._thread is not None and self._thread.is_alive():
            return  # 已經在跑了
        self._active = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止 Live 對話，關閉連線與音訊裝置。"""
        self._active = False
        if self._loop is not None and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
            except Exception:
                pass

    def set_muted(self, muted: bool):
        """靜音切換：靜音時仍持續連線，但不會把麥克風音訊送給模型。"""
        self._muted = muted

    # ------------------------------------------------------------------
    # 內部：背景執行緒 + asyncio 主流程
    # ------------------------------------------------------------------
    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            if self.on_error:
                self.on_error(f"語音通話發生錯誤：{e}")
        finally:
            if self.on_status_change:
                self.on_status_change(False)
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    async def _async_stop(self):
        self._active = False

    async def _main(self):
        http_options = types.HttpOptions(base_url=self.base_url) if self.base_url else None
        client = (
            genai.Client(api_key=self.api_key, http_options=http_options)
            if http_options else genai.Client(api_key=self.api_key)
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=build_shared_system_instruction(voice_mode=True),
            tools=build_shared_tools(),
            input_audio_transcription={},
            output_audio_transcription={},
        )

        self._pyaudio = pyaudio.PyAudio()
        try:
            async with client.aio.live.connect(model=LIVE_MODEL_NAME, config=config) as session:
                self._session = session
                if self.on_status_change:
                    self.on_status_change(True)

                mic_task = asyncio.ensure_future(self._send_audio_loop(session))
                recv_task = asyncio.ensure_future(self._receive_loop(session))

                # 只要 self._active 還是 True 就持續等待，直到使用者按下掛斷
                while self._active:
                    await asyncio.sleep(0.2)

                mic_task.cancel()
                recv_task.cancel()
                for t in (mic_task, recv_task):
                    try:
                        await t
                    except Exception:
                        pass
        finally:
            self._cleanup_audio()
            self._session = None

    async def _send_audio_loop(self, session):
        """持續讀取麥克風並串流送給模型（靜音時改送靜音資料，不中斷連線）。"""
        # 若使用者透過 set_input_device() 指定了裝置就用該裝置，否則用系統預設麥克風
        if self.input_device_index is not None:
            device_index = self.input_device_index
        else:
            device_index = self._pyaudio.get_default_input_device_info()["index"]

        self._mic_stream = await asyncio.to_thread(
            self._pyaudio.open,
            format=pyaudio.paInt16,
            channels=1,
            rate=LIVE_SEND_SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=LIVE_CHUNK_SIZE,
        )
        try:
            while True:
                data = await asyncio.to_thread(
                    self._mic_stream.read, LIVE_CHUNK_SIZE, exception_on_overflow=False
                )
                if self._muted:
                    continue  # 靜音時不送出音訊，但連線與接收仍持續
                await session.send_realtime_input(
                    audio={"data": data, "mime_type": "audio/pcm"}
                )
        except asyncio.CancelledError:
            pass

    async def _receive_loop(self, session):
        """接收模型的語音/文字回覆並即時播放，同時把逐字稿丟給 on_transcript。"""
        self._speaker_stream = await asyncio.to_thread(
            self._pyaudio.open,
            format=pyaudio.paInt16,
            channels=1,
            rate=LIVE_RECEIVE_SAMPLE_RATE,
            output=True,
        )
        try:
            while True:
                turn = session.receive()
                async for response in turn:
                    server_content = getattr(response, "server_content", None)

                    # 播放模型語音
                    if server_content and server_content.model_turn:
                        for part in server_content.model_turn.parts:
                            inline = getattr(part, "inline_data", None)
                            if inline and isinstance(inline.data, (bytes, bytearray)):
                                await asyncio.to_thread(self._speaker_stream.write, inline.data)

                    # 使用者語音轉錄文字
                    input_transcript = getattr(server_content, "input_transcription", None) if server_content else None
                    if input_transcript and getattr(input_transcript, "text", None):
                        if self.on_transcript:
                            self.on_transcript("user", input_transcript.text)

                    # 模型語音轉錄文字
                    output_transcript = getattr(server_content, "output_transcription", None) if server_content else None
                    if output_transcript and getattr(output_transcript, "text", None):
                        if self.on_transcript:
                            self.on_transcript("model", output_transcript.text)

                    # Function Calling：模型要求呼叫工具
                    tool_call = getattr(response, "tool_call", None)
                    if tool_call and getattr(tool_call, "function_calls", None):
                        responses = []
                        for fc in tool_call.function_calls:
                            result = dispatch_function_call(fc)
                            responses.append(
                                types.FunctionResponse(
                                    id=getattr(fc, "id", None),
                                    name=fc.name,
                                    response=result,
                                )
                            )
                        await session.send_tool_response(function_responses=responses)
        except asyncio.CancelledError:
            pass

    def _cleanup_audio(self):
        for stream in (self._mic_stream, self._speaker_stream):
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        self._mic_stream = None
        self._speaker_stream = None
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None


# ============================================================================
#  GUI 主程式
# ============================================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLOR_BG = "#0d1117"
COLOR_PANEL = "#161b22"
COLOR_USER_BUBBLE = "#1f6feb"
COLOR_AI_BUBBLE = "#21262d"
COLOR_ONLINE = "#3fb950"
COLOR_STANDBY = "#8b949e"
COLOR_ACCENT = "#58a6ff"
COLOR_DANGER = "#f85149"


class ChatBubble(ctk.CTkFrame):
    """單一聊天氣泡元件。"""

    def __init__(self, master, text: str, is_user: bool, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        bubble_color = COLOR_USER_BUBBLE if is_user else COLOR_AI_BUBBLE
        anchor_side = "e" if is_user else "w"
        justify = "right" if is_user else "left"

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="x", expand=True)

        bubble = ctk.CTkLabel(
            container,
            text=text,
            fg_color=bubble_color,
            text_color="#ffffff",
            corner_radius=14,
            justify=justify,
            anchor="w",
            wraplength=340,
            padx=14,
            pady=10,
            font=ctk.CTkFont(size=13),
        )

        if is_user:
            bubble.pack(anchor="e", padx=(60, 10), pady=4)
        else:
            bubble.pack(anchor="w", padx=(10, 60), pady=4)


class FloatingPill(ctk.CTkToplevel):
    """螢幕懸浮膠囊（PiP）視窗。"""

    def __init__(self, master, on_restore, on_hangup, on_toggle_mute):
        super().__init__(master)
        self.master_app = master
        self.on_restore = on_restore
        self.on_hangup = on_hangup
        self.on_toggle_mute = on_toggle_mute

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.97)
        except Exception:
            pass

        self.configure(fg_color=COLOR_PANEL)

        pill_width, pill_height = 260, 64
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = screen_w - pill_width - 30
        y = screen_h - pill_height - 80
        self.geometry(f"{pill_width}x{pill_height}+{x}+{y}")

        self.frame = ctk.CTkFrame(
            self, fg_color=COLOR_PANEL, corner_radius=28,
            border_width=1, border_color="#30363d",
        )
        self.frame.pack(fill="both", expand=True, padx=2, pady=2)

        self.status_dot = ctk.CTkLabel(
            self.frame, text="●", text_color=COLOR_STANDBY,
            font=ctk.CTkFont(size=16), width=20,
        )
        self.status_dot.pack(side="left", padx=(14, 4))

        self.name_label = ctk.CTkLabel(
            self.frame, text=ASSISTANT_NAME,
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#e6edf3",
        )
        self.name_label.pack(side="left", padx=2)

        self.restore_btn = ctk.CTkButton(
            self.frame, text="🗖", width=32, height=32, corner_radius=16,
            fg_color="#21262d", hover_color="#30363d",
            command=self._restore,
        )
        self.restore_btn.pack(side="right", padx=(2, 10))

        self.hangup_btn = ctk.CTkButton(
            self.frame, text="🛑", width=32, height=32, corner_radius=16,
            fg_color=COLOR_DANGER, hover_color="#c0392b",
            command=self._hangup,
        )
        self.hangup_btn.pack(side="right", padx=2)

        # Gemini Live 通話期間持續自動聆聽，這裡只需要一個「靜音麥克風」開關
        self.mute_btn = ctk.CTkButton(
            self.frame, text="🎤", width=32, height=32, corner_radius=16,
            fg_color=COLOR_ACCENT, hover_color="#3f8ae0",
            command=self._toggle_mute,
        )
        self.mute_btn.pack(side="right", padx=2)

        # 拖曳移動
        self._drag_x = 0
        self._drag_y = 0
        for widget in (self.frame, self.name_label, self.status_dot):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)

    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        x = self.winfo_pointerx() - self._drag_x
        y = self.winfo_pointery() - self._drag_y
        self.geometry(f"+{x}+{y}")

    def _restore(self):
        self.on_restore()

    def _hangup(self):
        self.on_hangup()

    def _toggle_mute(self):
        self.on_toggle_mute()

    def set_mic_muted(self, muted: bool):
        """更新麥克風按鈕的顏色，反映目前是否靜音。"""
        if muted:
            self.mute_btn.configure(text="🔇", fg_color=COLOR_DANGER, hover_color="#c0392b")
        else:
            self.mute_btn.configure(text="🎤", fg_color=COLOR_ACCENT, hover_color="#3f8ae0")

    def set_status(self, online: bool):
        self.status_dot.configure(text_color=COLOR_ONLINE if online else COLOR_STANDBY)


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{ASSISTANT_NAME} · 智慧助理")
        self.geometry("480x720")
        self.minsize(400, 600)
        self.configure(fg_color=COLOR_BG)

        self.pill_window = None
        self.mode = "text"          # "text" 文字模式 / "call" 通話模式（Gemini Live 即時語音）
        self.live_connected = False
        self.mic_muted = False

        self.brain = GeminiBrain(GEMINI_API_KEY, PROXY_BASE_URL, MODEL_NAME)
        self.live_controller = GeminiLiveController(
            GEMINI_API_KEY, PROXY_BASE_URL,
            on_status_change=self._on_live_status_change,
            on_transcript=self._on_live_transcript,
            on_error=self._on_live_error,
        )
        register_app_instance(self)  # 讓電腦層級工具（滑鼠/鍵盤）能呼叫本視窗跳出確認彈窗

        self._build_ui()

        if self.brain.error:
            self._append_bubble(f"⚠️ {self.brain.error}", is_user=False)
        if self.live_controller.error:
            self._append_bubble(f"⚠️ 通話模式（Gemini Live 語音）未啟用：{self.live_controller.error}", is_user=False)
        if not PYAUTOGUI_AVAILABLE:
            self._append_bubble(
                "⚠️ 電腦層級操作（滑鼠/鍵盤自動化）未啟用：請執行 pip install pyautogui pyperclip",
                is_user=False,
            )

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # 電腦層級操作確認彈窗（由 request_user_confirmation() 排程呼叫）
    # ------------------------------------------------------------------
    def _show_confirmation_dialog(self, description: str, event: threading.Event, result: dict):
        dialog = ctk.CTkToplevel(self)
        dialog.title("需要您的確認")
        dialog.geometry("380x200")
        dialog.attributes("-topmost", True)
        dialog.configure(fg_color=COLOR_PANEL)
        dialog.resizable(False, False)
        try:
            dialog.grab_set()
        except Exception:
            pass

        ctk.CTkLabel(
            dialog, text="⚠️ 電腦層級操作確認",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_DANGER,
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            dialog, text=f"{ASSISTANT_NAME} 想要執行：\n{description}",
            font=ctk.CTkFont(size=13), wraplength=330, justify="center",
        ).pack(padx=16, pady=(0, 10))

        def finish(approved: bool):
            result["approved"] = approved
            event.set()
            try:
                dialog.grab_release()
            except Exception:
                pass
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=14)

        ctk.CTkButton(
            btn_frame, text="✅ 允許執行", width=120, fg_color=COLOR_ONLINE,
            hover_color="#2ea043", command=lambda: finish(True),
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame, text="❌ 拒絕", width=120, fg_color=COLOR_DANGER,
            hover_color="#c0392b", command=lambda: finish(False),
        ).pack(side="left", padx=8)

        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))

    # ------------------------------------------------------------------
    # UI 建構
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---- 頂部狀態列 ----
        top_bar = ctk.CTkFrame(self, fg_color=COLOR_PANEL, height=48, corner_radius=0)
        top_bar.pack(side="top", fill="x")

        self.status_label = ctk.CTkLabel(
            top_bar, text="●  STANDBY", text_color=COLOR_STANDBY,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_label.pack(side="left", padx=16, pady=10)

        self.pill_btn = ctk.CTkButton(
            top_bar, text="🗗 懸浮小窗", width=110, height=30,
            fg_color="#21262d", hover_color="#30363d",
            command=self._enter_pip_mode,
        )
        self.pill_btn.pack(side="right", padx=12, pady=9)

        # ---- 通話資訊面板 ----
        call_panel = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=0)
        call_panel.pack(side="top", fill="x")

        ctk.CTkLabel(
            call_panel, text=ASSISTANT_NAME,
            font=ctk.CTkFont(size=20, weight="bold"), text_color="#e6edf3",
        ).pack(pady=(14, 0))

        self.call_state_label = ctk.CTkLabel(
            call_panel, text="尚未接通", font=ctk.CTkFont(size=12),
            text_color=COLOR_STANDBY,
        )
        self.call_state_label.pack(pady=(2, 8))

        # ---- 模式切換：文字模式（像 ChatGPT 打字）／ 通話模式（只能靠麥克風）----
        self.mode_switch = ctk.CTkSegmentedButton(
            call_panel,
            values=["💬 文字模式", "📞 通話模式"],
            command=self._on_mode_change,
            selected_color=COLOR_ACCENT,
        )
        self.mode_switch.set("💬 文字模式")
        self.mode_switch.pack(pady=(0, 14))

        # ---- 聊天氣泡區 ----
        self.chat_frame = ctk.CTkScrollableFrame(self, fg_color=COLOR_BG)
        self.chat_frame.pack(side="top", fill="both", expand=True, padx=6, pady=6)

        # ---- 輸入區容器：依模式切換顯示「文字輸入列」或「通話麥克風列」----
        self.input_container = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=0)
        self.input_container.pack(side="top", fill="x")

        # (A) 文字模式：像 ChatGPT 一樣打字輸入
        self.text_input_bar = ctk.CTkFrame(self.input_container, fg_color=COLOR_PANEL, corner_radius=0)

        self.entry = ctk.CTkEntry(
            self.text_input_bar, placeholder_text="輸入訊息給助理...",
            height=40, corner_radius=20,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(12, 8), pady=10)
        # 注意：CTkEntry 本身沒有 command 參數（那是 CTkButton 才有的功能）。
        # 正確監聽 Enter 鍵的方式是 bind("<Return>", ...)，只要事件字串正確
        # （不是空字串 ""），就不會出現 "no events specified in binding" 錯誤。
        self.entry.bind("<Return>", lambda event: self._on_send())

        self.send_btn = ctk.CTkButton(
            self.text_input_bar, text="送出", width=64, height=40, corner_radius=20,
            command=self._on_send,
        )
        self.send_btn.pack(side="right", padx=(0, 12), pady=10)

        # (B) 通話模式：不能打字，Gemini Live 會持續聆聽，不用手動按著說話
        self.call_input_bar = ctk.CTkFrame(self.input_container, fg_color=COLOR_PANEL, corner_radius=0)

        self.call_status_label = ctk.CTkLabel(
            self.call_input_bar, text="🔴 通話中，請直接開始說話...",
            font=ctk.CTkFont(size=13), text_color=COLOR_ONLINE,
        )
        self.call_status_label.pack(pady=(14, 4))

        # 麥克風選擇下拉選單：預設「系統預設麥克風」，也可指定特定裝置
        self._mic_name_to_index = {}  # 顯示字串 -> 裝置索引（None 代表系統預設）
        self.mic_select_menu = ctk.CTkOptionMenu(
            self.call_input_bar, values=["系統預設麥克風"],
            width=260, command=self._on_mic_selected,
            fg_color="#21262d", button_color="#30363d", button_hover_color="#3a4149",
        )
        self.mic_select_menu.pack(pady=(0, 8))
        self._refresh_mic_options()

        call_btn_row = ctk.CTkFrame(self.call_input_bar, fg_color="transparent")
        call_btn_row.pack(pady=(0, 14))

        self.call_mute_btn = ctk.CTkButton(
            call_btn_row, text="🎤 靜音麥克風", width=140, height=40, corner_radius=20,
            fg_color="#21262d", hover_color="#30363d",
            command=self._toggle_live_mute,
        )
        self.call_mute_btn.pack(side="left", padx=8)

        self.end_call_btn = ctk.CTkButton(
            call_btn_row, text="🛑 結束通話", width=140, height=40, corner_radius=20,
            fg_color=COLOR_DANGER, hover_color="#c0392b",
            command=self._end_call,
        )
        self.end_call_btn.pack(side="left", padx=8)

        # 預設顯示文字模式列
        self.text_input_bar.pack(side="top", fill="x")

        # ---- 底部：只留一個「開新對話」按鈕，取消排程請直接跟鎮宇說/打字即可 ----
        bottom_bar = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=0, height=56)
        bottom_bar.pack(side="top", fill="x")

        self.new_chat_btn = ctk.CTkButton(
            bottom_bar, text="🆕 新對話", width=140, height=38, corner_radius=19,
            fg_color="#21262d", hover_color="#30363d",
            command=self._new_conversation,
        )
        self.new_chat_btn.pack(pady=10)

        self._append_bubble(
            f"您好，我是 {ASSISTANT_NAME}。「💬 文字模式」可以像打字聊天一樣輸入訊息；"
            f"切換到「📞 通話模式」會開始 Gemini Live 即時語音通話，直接開口說話就好，"
            f"不用按著麥克風，講到一半也可以隨時插話打斷我。",
            is_user=False,
        )

    # ------------------------------------------------------------------
    # 聊天氣泡工具函式
    # ------------------------------------------------------------------
    def _append_bubble(self, text: str, is_user: bool):
        bubble = ChatBubble(self.chat_frame, text=text, is_user=is_user)
        bubble.pack(fill="x", anchor="e" if is_user else "w")
        self.after(50, lambda: self.chat_frame._parent_canvas.yview_moveto(1.0))

    # ------------------------------------------------------------------
    # 狀態列（只反映目前模式與 Live 連線狀態，不再有獨立的「接通」概念）
    # ------------------------------------------------------------------
    def _refresh_status_bar(self):
        if self.mode == "call" and self.live_connected:
            self.status_label.configure(text="●  ONLINE", text_color=COLOR_ONLINE)
            self.call_state_label.configure(text="語音通話中", text_color=COLOR_ONLINE)
        elif self.mode == "call":
            self.status_label.configure(text="●  連線中...", text_color=COLOR_ACCENT)
            self.call_state_label.configure(text="正在連線 Gemini Live...", text_color=COLOR_ACCENT)
        else:
            self.status_label.configure(text="●  STANDBY", text_color=COLOR_STANDBY)
            self.call_state_label.configure(text="文字模式", text_color=COLOR_STANDBY)
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.set_status(self.mode == "call" and self.live_connected)

    def _new_conversation(self):
        """開新對話：清空聊天紀錄與畫面，若在通話中會一併結束通話。"""
        if self.mode == "call":
            self.live_controller.stop()
            self.mode = "text"
            self.call_input_bar.pack_forget()
            self.text_input_bar.pack(side="top", fill="x")
            self.mode_switch.set("💬 文字模式")

        self.brain.chat_history = []
        for widget in self.chat_frame.winfo_children():
            widget.destroy()
        self._refresh_status_bar()
        self._append_bubble(f"已開始新的對話。我是 {ASSISTANT_NAME}，有什麼可以幫你的嗎？", is_user=False)

    # ------------------------------------------------------------------
    # 模式切換：文字模式（打字） ／ 通話模式（Gemini Live 即時語音）
    # ------------------------------------------------------------------
    def _on_mode_change(self, value: str):
        if "通話" in value:
            self.mode = "call"
            self.text_input_bar.pack_forget()
            self.call_input_bar.pack(side="top", fill="x")
            self.mic_muted = False
            self.call_mute_btn.configure(text="🎤 靜音麥克風", fg_color="#21262d", hover_color="#30363d")
            self._refresh_mic_options()
            self._append_bubble("正在連線 Gemini Live，請稍候...", is_user=False)
            self._refresh_status_bar()
            self.live_controller.start()
        else:
            if self.mode == "call":
                self.live_controller.stop()
            self.mode = "text"
            self.call_input_bar.pack_forget()
            self.text_input_bar.pack(side="top", fill="x")
            self._refresh_status_bar()
            self._append_bubble("已切換到文字模式，可以直接輸入文字對話。", is_user=False)

    def _refresh_mic_options(self):
        """重新掃描系統上的麥克風清單，更新下拉選單內容（盡量保留使用者原本的選擇）。"""
        previous_selection = self.mic_select_menu.get() if hasattr(self, "mic_select_menu") else "系統預設麥克風"
        devices = list_input_devices()
        self._mic_name_to_index = {"系統預設麥克風": None}
        values = ["系統預設麥克風"]
        for idx, name in devices:
            # 避免不同裝置同名造成選單顯示混淆，附上索引編號
            display = f"{name} (#{idx})"
            self._mic_name_to_index[display] = idx
            values.append(display)
        self.mic_select_menu.configure(values=values)
        # 若先前選擇的裝置仍然存在就保留，否則退回系統預設
        self.mic_select_menu.set(previous_selection if previous_selection in values else values[0])

    def _on_mic_selected(self, selected: str):
        device_index = self._mic_name_to_index.get(selected)
        self.live_controller.set_input_device(device_index)
        if self.mode == "call" and self.live_connected:
            self._append_bubble(
                "已記住這個麥克風選擇，請按「🛑 結束通話」後重新切換到通話模式，設定才會套用。",
                is_user=False,
            )

    def _end_call(self):
        """結束通話：停止 Gemini Live、切回文字模式。"""
        self.live_controller.stop()
        self.mode = "text"
        self.call_input_bar.pack_forget()
        self.text_input_bar.pack(side="top", fill="x")
        self.mode_switch.set("💬 文字模式")
        self.live_connected = False
        self._refresh_status_bar()
        self._append_bubble("通話已結束。", is_user=False)

    def _toggle_live_mute(self):
        self.mic_muted = not self.mic_muted
        self.live_controller.set_muted(self.mic_muted)
        if self.mic_muted:
            self.call_mute_btn.configure(text="🔇 已靜音", fg_color=COLOR_DANGER, hover_color="#c0392b")
        else:
            self.call_mute_btn.configure(text="🎤 靜音麥克風", fg_color="#21262d", hover_color="#30363d")
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.set_mic_muted(self.mic_muted)

    # ------------------------------------------------------------------
    # Gemini Live callback（由背景執行緒呼叫，內部都會排程回主執行緒）
    # ------------------------------------------------------------------
    def _on_live_status_change(self, connected: bool):
        def update():
            self.live_connected = connected
            self._refresh_status_bar()
            if not connected and self.mode == "call":
                # 連線意外中斷（非使用者主動掛斷）
                self._append_bubble("與 Gemini Live 的連線已中斷。", is_user=False)
        self.after(0, update)

    def _on_live_transcript(self, role: str, text: str):
        def update():
            self._append_bubble(text, is_user=(role == "user"))
        self.after(0, update)

    def _on_live_error(self, message: str):
        def update():
            self._append_bubble(f"⚠️ {message}", is_user=False)
        self.after(0, update)

    # ------------------------------------------------------------------
    # 訊息送出與 AI 呼叫（文字模式專用，皆在背景執行緒，確保 GUI 不卡死）
    # ------------------------------------------------------------------
    def _on_send(self):
        user_text = self.entry.get().strip()
        if not user_text:
            return
        self.entry.delete(0, "end")
        self._send_text(user_text)

    def _send_text(self, user_text: str):
        """文字模式的送出邏輯：純文字問答，不會觸發任何語音播放。"""
        if not user_text:
            return

        self._append_bubble(user_text, is_user=True)
        self._append_bubble("思考中...", is_user=False)
        thinking_bubble_ref = self.chat_frame.winfo_children()[-1]

        def worker():
            reply_text = self.brain.send_message(user_text)

            def update_ui():
                try:
                    thinking_bubble_ref.destroy()
                except Exception:
                    pass
                self._append_bubble(reply_text, is_user=False)

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 懸浮膠囊模式 (PiP)
    # ------------------------------------------------------------------
    def _enter_pip_mode(self):
        self.withdraw()
        if self.pill_window is None or not self.pill_window.winfo_exists():
            self.pill_window = FloatingPill(
                self, on_restore=self._exit_pip_mode, on_hangup=self._pip_hangup,
                on_toggle_mute=self._toggle_live_mute,
            )
            self.pill_window.set_status(self.mode == "call" and self.live_connected)
            self.pill_window.set_mic_muted(self.mic_muted)
        else:
            self.pill_window.deiconify()

    def _exit_pip_mode(self):
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.withdraw()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _pip_hangup(self):
        if self.mode == "call":
            self._end_call()
        self._exit_pip_mode()

    def _on_close(self):
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.destroy()
        try:
            self.live_controller.stop()
        except Exception:
            pass
        try:
            browser_controller.close()
        except Exception:
            pass
        register_app_instance(None)
        self.destroy()


# ============================================================================
#  程式進入點
# ============================================================================

def main():
    if not GENAI_AVAILABLE:
        print("[警告] 尚未安裝 google-genai，請先執行：pip install google-genai")
    app = AssistantApp()
    app.mainloop()


if __name__ == "__main__":
    main()
