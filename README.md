# 鎮宇 · 桌面智慧助理

現代化科技風格的 Windows 桌面個人智慧助理，具備文字/語音雙模式對話、螢幕懸浮膠囊（PiP）、
系統控制與瀏覽器自動化能力，AI 大腦使用 Google `gemini-3.6-flash`。

---

## 目錄

- [功能總覽](#功能總覽)
- [安裝](#安裝)
- [設定](#設定)
- [執行](#執行)
- [使用說明](#使用說明)
- [工具（Function Calling）清單](#工具function-calling清單)
- [已知限制](#已知限制)
- [打包成 .exe](#打包成-exe)

---

## 功能總覽

### 介面
- 深色科技風（customtkinter `dark` + `blue`）
- 頂部狀態列：連線狀態燈（● STANDBY / ● ONLINE）＋「🗗 懸浮小窗」
- **模式切換**：
  - 💬 文字模式：像 ChatGPT 一樣打字對話
  - 📞 通話模式：隱藏輸入框，只能點麥克風說話
- 聊天氣泡（使用者靠右藍底／AI 靠左深灰底，自動換行）
- **懸浮膠囊（PiP）**：無邊框、永遠置頂、可拖曳，內含狀態燈、還原鍵、掛斷鍵、麥克風鍵

### AI 對話
- `google-genai` SDK，模型 `gemini-3.6-flash`
- System Instruction 動態帶入目前系統時間，供精準換算關機時間
- 支援反代中繼站（`PROXY_BASE_URL`）
- 多輪 Function Calling（最多連續 5 輪）

### 語音
- **TTS**（`pyttsx3`，離線）：AI 回覆可自動語音播放
- **STT**（`SpeechRecognition` + Google 線上辨識，`zh-TW`）：通話模式錄音轉文字

### 系統控制
- 指定時間 / 倒數分鐘關機、取消關機
- 開啟瀏覽器（系統預設）、開啟應用程式（含中文別名）

### 瀏覽器自動化（Selenium）
- 開啟獨立可控的 Chrome 視窗
- 讀取頁面內容摘要、點擊元素、輸入文字、按 Enter、捲動頁面、關閉瀏覽器

### 電腦層級自動化（pyautogui，不限瀏覽器）
- 滑鼠移動、點擊（左/右/中鍵、單擊/雙擊）、滾輪捲動
- 鍵盤輸入文字（含中文，透過剪貼簿貼上）、單鍵按下、組合鍵（如 `ctrl+c`、`alt+tab`）
- 螢幕解析度查詢、截圖存檔
- **每次滑鼠/鍵盤操作前都會跳出確認視窗**，需使用者按「允許」才會真的執行，
  拒絕或 30 秒未回應一律視為取消；另外保留 pyautogui 內建的安全機制——
  滑鼠移到螢幕左上角 (0,0) 可強制中斷自動化

---

## 安裝

```bash
pip install customtkinter google-genai pyttsx3 SpeechRecognition pyaudio selenium webdriver-manager pyautogui pyperclip
```

若 Windows 上 `pyaudio` 直接安裝失敗：

```bash
pip install pipwin
pipwin install pyaudio
```

> 只想先看介面、不想裝齊所有依賴？只裝 `customtkinter` 也能啟動，
> 未安裝的功能（AI / TTS / STT / 瀏覽器自動化）會顯示提示訊息，不會讓程式崩潰。

---

## 設定

打開 `ai_assistant.py`，修改檔案上方「使用者設定區」：

```python
GEMINI_API_KEY = "你的 Gemini API Key"
PROXY_BASE_URL = ""              # 若使用反代中繼站才填，留空則用官方端點
MODEL_NAME = "gemini-3.6-flash"
ASSISTANT_NAME = "鎮宇"
```

---

## 執行

```bash
python ai_assistant.py
```

---

## 使用說明

| 操作 | 說明 |
|---|---|
| 💬 文字模式 | 直接在輸入框打字，Enter 或按「送出」 |
| 📞 通話模式 | 點擊大顆麥克風按鈕開始說話，停頓約 0.8 秒自動結束並送出 |
| 🗗 懸浮小窗 | 主視窗縮成右下角圓角膠囊，可拖曳；膠囊上也有麥克風鍵可直接說話 |
| 🔊 語音回覆 | 切換 AI 回覆是否要用語音唸出來（不影響文字顯示） |
| ⏹ 取消關機 | 快速呼叫 `cancel_shutdown`，不用打字 |

**範例指令：**
- 「30 分鐘後幫我關機」
- 「晚上 11 點關機」
- 「取消關機」
- 「幫我開瀏覽器搜尋台北天氣」
- 「開記事本」
- 「幫我到 Google 搜尋 XXX，然後點第一個結果」（瀏覽器自動化）

---

## 工具（Function Calling）清單

| 工具 | 功能 |
|---|---|
| `schedule_shutdown(target_time_str)` | 指定時間關機（HH:MM，24 小時制） |
| `shutdown_in_minutes(minutes)` | N 分鐘後關機 |
| `cancel_shutdown()` | 取消排程關機 |
| `open_browser(url_or_keyword)` | 系統預設瀏覽器開網址或搜尋 |
| `open_app(app_name)` | 開啟 Windows 應用程式 |
| `browser_navigate(url_or_keyword)` | 開啟/導覽自動化瀏覽器 |
| `browser_get_page_summary()` | 讀取頁面標題／網址／內容摘要 |
| `browser_click(text)` | 點擊包含指定文字的元素 |
| `browser_type_text(value, field_hint)` | 在輸入欄位填文字 |
| `browser_press_enter()` | 模擬按 Enter |
| `browser_scroll(direction)` | 上下捲動頁面 |
| `browser_close()` | 關閉自動化瀏覽器 |

`open_browser` 與 `browser_navigate` 系列的差異：前者只是用系統預設瀏覽器開一個新分頁；
後者啟動一個程式完全掌控、可被持續操作（點擊/輸入/捲動）的獨立 Chrome 視窗。

| 工具 | 功能 | 需確認 |
|---|---|---|
| `get_screen_size()` | 取得螢幕解析度 | 否 |
| `take_screenshot()` | 截圖存檔 | 否 |
| `mouse_move(x, y)` | 移動滑鼠到指定座標 | 是 |
| `mouse_click(x, y, button, double)` | 滑鼠點擊 | 是 |
| `mouse_scroll(amount)` | 滾輪捲動 | 是 |
| `keyboard_type(text)` | 輸入文字到目前作用中視窗 | 是 |
| `keyboard_press(key)` | 按下單一按鍵 | 是 |
| `keyboard_hotkey(keys)` | 組合鍵，如 `ctrl+c` | 是 |

「電腦層級」的滑鼠/鍵盤工具會作用在**目前作用中的任何視窗**，不限瀏覽器；
凡標記「需確認」的操作，執行前都會跳出彈窗，需使用者按「允許」才會真的執行。

---

## 已知限制

- 語音辨識走 Google 線上服務，需要網路連線
- 瀏覽器自動化沒有額外二次確認機制，請避免請它操作涉及刪除／付款／轉帳的頁面
- 電腦層級滑鼠/鍵盤操作雖然有彈窗確認，但一旦按下「允許」，操作範圍就是**當下整台電腦的作用中視窗**，請留意確認視窗上顯示的內容是否符合你的預期
- 沒有檔案讀寫、軟體安裝移除、系統設定變更等能力
- 遇到 reCAPTCHA / Cloudflare 等防機器人機制的網站，瀏覽器自動化可能會被擋下
- pyautogui 的座標操作是「盲操作」（沒有畫面辨識能力），AI 並不能真正「看到」螢幕內容，下座標前建議先用 `take_screenshot()` 讓使用者自行確認畫面狀態

---

## 打包成 .exe

```bash
pyinstaller --noconsole --onefile --collect-all customtkinter ai_assistant.py
```

打包後的執行檔在 `dist/ai_assistant.exe`。
