# -*- coding: utf-8 -*-
"""
================================================================================
  現代化科技風格 Windows 桌面個人智慧助理
  ----------------------------------------------------------------------------
  技術棧：
    - GUI       : customtkinter (dark / blue)
    - AI 大腦   : google-genai SDK (gemini-2.5-flash) + Function Calling
    - 系統控制  : shutdown / subprocess / webbrowser
  功能：
    - 通話模式風格聊天介面（文字模式 / 語音通話模式可切換）
    - 螢幕懸浮膠囊 (Picture-in-Picture)
    - 排程關機 / 分鐘倒數關機 / 取消關機
    - 開啟瀏覽器 / 開啟應用程式
    - 瀏覽器自動化操控（點擊、輸入文字、捲動、讀取頁面內容）
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
# pyttsx3：離線文字轉語音（TTS），不需要額外的雲端金鑰
#   pip install pyttsx3
#   Windows 上會使用系統內建的 SAPI5 語音引擎
# ------------------------------------------------------------------------
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

# ------------------------------------------------------------------------
# SpeechRecognition：語音辨識（STT），通話模式用麥克風輸入靠這個
#   pip install SpeechRecognition pyaudio
#   （Windows 上 pyaudio 若直接 pip install 失敗，可改用：
#     pip install pipwin && pipwin install pyaudio）
# ------------------------------------------------------------------------
try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False

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

import queue


# ============================================================================
# ▼▼▼ 使用者設定區（請在此填入你的金鑰 / 反代網址）▼▼▼
# ============================================================================
GEMINI_API_KEY = "AQ.Ab8RN6J8JjiG10boBe0xLex3ny7o3DxgfGQbiACo29TuoQF4pQ"     # <-- 你的 Gemini API Key
PROXY_BASE_URL = ""                              # <-- 若使用反代中繼站，請填入 base_url，例如：
                                                  #     "https://your-proxy-domain.com/v1"
                                                  #     留空則使用官方預設端點
MODEL_NAME = "gemini-3.6-flash"
ASSISTANT_NAME = "鎮宇"
# ============================================================================
# ▲▲▲ 使用者設定區 ▲▲▲
# ============================================================================


IS_WINDOWS = platform.system() == "Windows"


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
}


# ============================================================================
#  Gemini AI 大腦封裝
# ============================================================================

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

    # -- 工具定義（Function Declarations） ---------------------------------
    @staticmethod
    def _build_tools():
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
                ]
            )
        ]

    def _build_system_instruction(self) -> str:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        weekday_map = ["一", "二", "三", "四", "五", "六", "日"]
        weekday_str = weekday_map[now.weekday()]

        return (
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
            f"若使用者想開啟應用程式，也請呼叫對應工具完成，而非只是用文字說明步驟。\n"
            f"完成工具呼叫後，請用簡短自然的口語向使用者確認結果。"
        )

    def _dispatch_function_call(self, function_call) -> dict:
        """執行單一 function call，回傳結果 dict。"""
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
            tools = self._build_tools()
            system_instruction = self._build_system_instruction()

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
                        result = self._dispatch_function_call(fc)
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
#  文字轉語音（TTS）引擎封裝
# ============================================================================

class SpeechEngine:
    """
    封裝 pyttsx3，提供非阻塞的文字轉語音功能。
    使用獨立背景執行緒 + Queue 依序播放，避免多段語音互相打斷，
    也避免在 GUI 執行緒中呼叫 runAndWait() 造成介面卡死。
    """

    def __init__(self):
        self.available = False
        self.error = None
        self._queue = queue.Queue()
        self.engine = None

        if not PYTTSX3_AVAILABLE:
            self.error = "尚未安裝 pyttsx3，請執行：pip install pyttsx3"
            return

        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", 185)
            self.engine.setProperty("volume", 1.0)
            self._select_chinese_voice()
            self.available = True
        except Exception as e:
            self.error = f"初始化語音引擎失敗：{e}"
            return

        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _select_chinese_voice(self):
        """嘗試自動挑選系統中已安裝的中文語音（若無則使用系統預設）。"""
        try:
            voices = self.engine.getProperty("voices")
            keywords = ["chinese", "mandarin", "zh-", "zh_cn", "zh_tw",
                        "huihui", "yating", "hanhan", "taiwan", "zh"]
            for v in voices:
                blob = f"{getattr(v, 'name', '')} {getattr(v, 'id', '')}".lower()
                if any(k in blob for k in keywords):
                    self.engine.setProperty("voice", v.id)
                    return
        except Exception:
            pass  # 找不到中文語音就使用系統預設語音

    def _worker_loop(self):
        """背景執行緒：依序從佇列取出文字並播放語音，確保同一時間只播一句。"""
        while True:
            text = self._queue.get()
            if not text:
                continue
            try:
                self.engine.say(text)
                self.engine.runAndWait()
            except Exception:
                pass

    def speak(self, text: str):
        """將文字加入播放佇列（非阻塞，可安全從任意執行緒呼叫）。"""
        if self.available and text:
            self._queue.put(text)

    def stop(self):
        """清空佇列並嘗試立即停止目前的語音播放。"""
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
        except Exception:
            pass
        try:
            if self.engine:
                self.engine.stop()
        except Exception:
            pass


# ============================================================================
#  語音辨識（STT）引擎封裝 —— 通話模式使用麥克風輸入
# ============================================================================

class VoiceInputEngine:
    """
    封裝 speech_recognition，提供「點擊開始說話 → 自動偵測停頓 → 轉成文字」
    的錄音辨識功能。listen_and_transcribe() 為同步阻塞呼叫，
    因此一律要在背景執行緒中呼叫，避免卡住 GUI。
    """

    def __init__(self):
        self.available = False
        self.error = None
        self.recognizer = None

        if not SR_AVAILABLE:
            self.error = "尚未安裝語音辨識套件，請執行：pip install SpeechRecognition pyaudio"
            return

        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.pause_threshold = 0.8  # 停頓超過 0.8 秒視為一句話講完
            self.available = True
        except Exception as e:
            self.error = f"初始化語音辨識失敗：{e}"

    def listen_and_transcribe(self, timeout: int = 6, phrase_time_limit: int = 20) -> str:
        """
        開啟麥克風錄音並轉成文字（繁體中文）。
        Args:
            timeout: 等待使用者「開始說話」的最長秒數，超過就放棄
            phrase_time_limit: 單次錄音的最長秒數上限
        Returns:
            辨識出的文字（str）
        Raises:
            RuntimeError / sr.WaitTimeoutError / sr.UnknownValueError / sr.RequestError
        """
        if not self.available:
            raise RuntimeError(self.error or "語音辨識未啟用")

        with sr.Microphone() as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = self.recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_time_limit
            )

        # 使用 Google 免費線上語音辨識（需要網路連線），語言設定為繁體中文
        text = self.recognizer.recognize_google(audio, language="zh-TW")
        return text


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

    def __init__(self, master, on_restore, on_hangup, on_mic):
        super().__init__(master)
        self.master_app = master
        self.on_restore = on_restore
        self.on_hangup = on_hangup
        self.on_mic = on_mic

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

        # 通話模式下的「點擊說話」麥克風按鈕：最小化後仍可用語音對話
        self.mic_btn = ctk.CTkButton(
            self.frame, text="🎤", width=32, height=32, corner_radius=16,
            fg_color=COLOR_ACCENT, hover_color="#3f8ae0",
            command=self._mic,
        )
        self.mic_btn.pack(side="right", padx=2)

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

    def _mic(self):
        self.on_mic()

    def set_mic_listening(self, listening: bool):
        """聆聽中時把麥克風按鈕變色，給使用者明確回饋。"""
        if listening:
            self.mic_btn.configure(fg_color=COLOR_DANGER, hover_color="#c0392b", state="disabled")
        else:
            self.mic_btn.configure(fg_color=COLOR_ACCENT, hover_color="#3f8ae0", state="normal")

    def set_status(self, online: bool):
        self.status_dot.configure(text_color=COLOR_ONLINE if online else COLOR_STANDBY)


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{ASSISTANT_NAME} · 智慧助理")
        self.geometry("480x720")
        self.minsize(400, 600)
        self.configure(fg_color=COLOR_BG)

        self.is_online = False
        self.is_muted = False
        self.pill_window = None
        self.mode = "text"          # "text" 文字模式 / "call" 通話模式（只能語音）
        self.is_listening = False   # 目前是否正在錄音辨識中

        self.brain = GeminiBrain(GEMINI_API_KEY, PROXY_BASE_URL, MODEL_NAME)
        self.speech = SpeechEngine()
        self.voice_input = VoiceInputEngine()

        self._build_ui()

        if self.brain.error:
            self._append_bubble(f"⚠️ {self.brain.error}", is_user=False)
        if self.speech.error:
            self._append_bubble(f"⚠️ 語音回覆功能未啟用：{self.speech.error}", is_user=False)
        if self.voice_input.error:
            self._append_bubble(f"⚠️ 通話模式（麥克風輸入）未啟用：{self.voice_input.error}", is_user=False)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

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

        # (B) 通話模式：不能打字，只能點擊麥克風說話
        self.call_input_bar = ctk.CTkFrame(self.input_container, fg_color=COLOR_PANEL, corner_radius=0)

        self.call_mic_status_label = ctk.CTkLabel(
            self.call_input_bar, text="點擊下方麥克風開始說話",
            font=ctk.CTkFont(size=12), text_color=COLOR_STANDBY,
        )
        self.call_mic_status_label.pack(pady=(10, 4))

        self.call_mic_btn = ctk.CTkButton(
            self.call_input_bar, text="🎤", width=64, height=64, corner_radius=32,
            fg_color=COLOR_ACCENT, hover_color="#3f8ae0",
            font=ctk.CTkFont(size=22),
            command=self._start_listening,
        )
        self.call_mic_btn.pack(pady=(0, 12))

        # 預設顯示文字模式列
        self.text_input_bar.pack(side="top", fill="x")

        # ---- 底部通話控制列 ----
        control_bar = ctk.CTkFrame(self, fg_color=COLOR_PANEL, corner_radius=0, height=64)
        control_bar.pack(side="top", fill="x")

        # 注意：目前沒有語音辨識（輸入），此按鈕控制的是「語音輸出」開關——
        # 也就是鎮宇回覆時是否要用語音唸出來（文字輸入方式不受影響）。
        self.mic_btn = ctk.CTkButton(
            control_bar, text="🔊 語音回覆", width=110, height=40, corner_radius=20,
            fg_color="#21262d", hover_color="#30363d",
            command=self._toggle_mute,
        )
        self.mic_btn.pack(side="left", padx=14, pady=12)

        self.call_btn = ctk.CTkButton(
            control_bar, text="📞 接通", width=110, height=40, corner_radius=20,
            fg_color=COLOR_ONLINE, hover_color="#2ea043",
            command=self._toggle_call,
        )
        self.call_btn.pack(side="left", padx=6, pady=12, expand=True)

        self.cancel_shutdown_btn = ctk.CTkButton(
            control_bar, text="⏹ 取消關機", width=110, height=40, corner_radius=20,
            fg_color=COLOR_DANGER, hover_color="#c0392b",
            command=self._quick_cancel_shutdown,
        )
        self.cancel_shutdown_btn.pack(side="right", padx=14, pady=12)

        self._append_bubble(
            f"您好，我是 {ASSISTANT_NAME}。「💬 文字模式」可以像打字聊天一樣輸入訊息；"
            f"切換到「📞 通話模式」則不能打字，只能點擊麥克風說話，我也會用語音回覆您。",
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
    # 狀態切換
    # ------------------------------------------------------------------
    def _set_online(self, online: bool):
        self.is_online = online
        if online:
            self.status_label.configure(text="●  ONLINE", text_color=COLOR_ONLINE)
            self.call_state_label.configure(text="通話中", text_color=COLOR_ONLINE)
            self.call_btn.configure(
                text="🛑 掛斷", fg_color=COLOR_DANGER, hover_color="#c0392b",
            )
        else:
            self.status_label.configure(text="●  STANDBY", text_color=COLOR_STANDBY)
            self.call_state_label.configure(text="尚未接通", text_color=COLOR_STANDBY)
            self.call_btn.configure(
                text="📞 接通", fg_color=COLOR_ONLINE, hover_color="#2ea043",
            )
        if self.pill_window is not None:
            self.pill_window.set_status(online)

    def _toggle_call(self):
        self._set_online(not self.is_online)
        if self.is_online:
            self._append_bubble("通話已接通，請開始說話或輸入訊息。", is_user=False)
        else:
            self.speech.stop()
            self._append_bubble("通話已結束。", is_user=False)

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.mic_btn.configure(text="🔇 已靜音", fg_color=COLOR_DANGER, hover_color="#c0392b")
            self.speech.stop()  # 立即停止目前正在播放的語音
        else:
            self.mic_btn.configure(text="🔊 語音回覆", fg_color="#21262d", hover_color="#30363d")

    def _quick_cancel_shutdown(self):
        self._append_bubble("正在取消排程關機...", is_user=False)

        def worker():
            result = cancel_shutdown()
            self.after(0, lambda: self._append_bubble(result, is_user=False))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 模式切換：文字模式（打字） ／ 通話模式（只能靠麥克風）
    # ------------------------------------------------------------------
    def _on_mode_change(self, value: str):
        if "通話" in value:
            self.mode = "call"
            self.text_input_bar.pack_forget()
            self.call_input_bar.pack(side="top", fill="x")
            if not self.is_online:
                self._set_online(True)
            self._append_bubble("已切換到通話模式：無法打字，請點擊下方麥克風開始說話。", is_user=False)
        else:
            self.mode = "text"
            self.call_input_bar.pack_forget()
            self.text_input_bar.pack(side="top", fill="x")
            self._append_bubble("已切換到文字模式，可以直接輸入文字對話。", is_user=False)

    # ------------------------------------------------------------------
    # 訊息送出與 AI 呼叫（皆在背景執行緒，確保 GUI 不卡死）
    # ------------------------------------------------------------------
    def _on_send(self):
        user_text = self.entry.get().strip()
        if not user_text:
            return
        self.entry.delete(0, "end")
        self._send_text(user_text)

    def _send_text(self, user_text: str):
        """統一的送出邏輯：文字模式打字送出、通話模式語音辨識完成後都會呼叫這裡。"""
        if not user_text:
            return

        if not self.is_online:
            self._set_online(True)

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
                # 若目前在通話中且未靜音，將 AI 回覆用語音唸出來
                if self.is_online and not self.is_muted:
                    self.speech.speak(reply_text)

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 通話模式：麥克風語音輸入（STT）
    # ------------------------------------------------------------------
    def _start_listening(self):
        """點擊麥克風開始錄音辨識；主視窗與懸浮膠囊共用這個方法。"""
        if self.is_listening:
            return
        if not self.voice_input.available:
            self._append_bubble(f"⚠️ {self.voice_input.error}", is_user=False)
            return

        self.is_listening = True
        self.call_mic_btn.configure(state="disabled", fg_color=COLOR_DANGER, hover_color="#c0392b")
        self.call_mic_status_label.configure(text="🎧 聆聽中，請開始說話...")
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.set_mic_listening(True)

        def worker():
            text, err = None, None
            try:
                text = self.voice_input.listen_and_transcribe()
            except Exception as e:
                err = str(e)

            def update_ui():
                self.is_listening = False
                self.call_mic_btn.configure(
                    state="normal", fg_color=COLOR_ACCENT, hover_color="#3f8ae0"
                )
                self.call_mic_status_label.configure(text="點擊下方麥克風開始說話")
                if self.pill_window is not None and self.pill_window.winfo_exists():
                    self.pill_window.set_mic_listening(False)

                if text:
                    self._send_text(text)
                elif err:
                    self._append_bubble(f"⚠️ 語音辨識失敗：{err}", is_user=False)

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
                on_mic=self._start_listening,
            )
            self.pill_window.set_status(self.is_online)
        else:
            self.pill_window.deiconify()

    def _exit_pip_mode(self):
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.withdraw()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _pip_hangup(self):
        self._set_online(False)
        self._exit_pip_mode()

    def _on_close(self):
        if self.pill_window is not None and self.pill_window.winfo_exists():
            self.pill_window.destroy()
        try:
            browser_controller.close()
        except Exception:
            pass
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
