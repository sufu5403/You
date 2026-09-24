# 鎮宇 · 桌面智慧助理

現代化科技風格的 Windows 桌面個人智慧助理。**文字模式**與**通話模式**是完全分開的兩套系統：
文字模式是純打字問答；通話模式改用 **Gemini Live API** 做真正的即時雙向語音對話（不是「錄音轉文字→問AI→轉語音」拼接出來的假通話）。
另外具備螢幕懸浮膠囊（PiP）、系統控制、瀏覽器自動化、電腦層級滑鼠鍵盤自動化能力。

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
- 頂部狀態列：連線狀態燈（● STANDBY / ● 連線中 / ● ONLINE）＋「🗗 懸浮小窗」
- **模式切換**（完全獨立的兩套系統，互不干擾）：
  - 💬 **文字模式**：純打字問答，`GeminiBrain`（`generateContent` + Function Calling），不會有任何語音播放
  - 📞 **通話模式**：`GeminiLiveController`（Gemini Live API），開啟後直接說話即可，
    不用手動按著麥克風，模型有原生語音活動偵測（VAD），你隨時可以插話打斷它
- 聊天氣泡（使用者靠右藍底／AI 靠左深灰底，自動換行；通話模式的逐字稿也會顯示成氣泡）
- **懸浮膠囊（PiP）**：無邊框、永遠置頂、可拖曳，內含狀態燈、還原鍵、掛斷鍵、麥克風靜音切換鍵
- 底部只有一個「🆕 新對話」按鈕：清空對話紀錄、若在通話中會一併掛斷。
  沒有專屬的「取消關機」按鈕——想取消關機，直接跟鎮宇說或打字說「取消關機」就好

### AI 對話（文字模式）
- `google-genai` SDK，模型 `gemini-3.6-flash`
- System Instruction 動態帶入目前系統時間，供精準換算關機時間
- 支援反代中繼站（`PROXY_BASE_URL`）
- 多輪 Function Calling（最多連續 5 輪）

### 即時語音通話（通話模式，Gemini Live）
- 模型：`gemini-3.1-flash-live-preview`（Google 最新的 Audio-to-Audio 即時語音模型）
- 麥克風收音即時串流給模型、模型語音回覆即時串流播放，走 `pyaudio` 全雙工音訊
- 原生語音活動偵測（VAD）與可隨時打斷（barge-in），不用手動按著說話
- 開啟 `input_audio_transcription` / `output_audio_transcription`，
  雙方說的話都會轉成文字顯示在聊天氣泡中，方便回顧
- 通話中一樣能觸發所有 Function Calling 工具（例如語音說「30分鐘後關機」）

### 系統控制
- 指定時間 / 倒數分鐘關機、取消關機（無專屬按鈕，用說的或打字即可）
- 開啟瀏覽器（系統預設）、開啟應用程式（含中文別名，一律先跳出提示訊息再執行）

### 瀏覽器自動化（Selenium）
- 開啟獨立可控的 Chrome 視窗
- 讀取頁面內容摘要、點擊元素、輸入文字、按 Enter、捲動頁面、關閉瀏覽器

### 電腦層級自動化（pyautogui，不限瀏覽器）
- 滑鼠移動、點擊（左/右/中鍵、單擊/雙擊）、滾輪捲動
- 鍵盤輸入文字（含中文，透過剪貼簿貼上）、單鍵按下、組合鍵（如 `ctrl+c`、`alt+tab`）
- 螢幕解析度查詢、截圖存檔
- 是否需要彈窗二次確認由 `REQUIRE_ACTION_CONFIRMATION` 設定控制（見下方「設定」章節）

---

## 安裝

```bash
pip install customtkinter google-genai selenium webdriver-manager pyautogui pyperclip pyaudio
```

若 Windows 上 `pyaudio` 直接安裝失敗：

```bash
pip install pipwin
pipwin install pyaudio
```

> 只想先看介面、不想裝齊所有依賴？只裝 `customtkinter` 也能啟動，
> 未安裝的功能（AI / 通話模式 / 瀏覽器自動化 / 電腦層級自動化）會顯示提示訊息，不會讓程式崩潰。

---

## 設定

打開 `ai_assistant.py`，修改檔案上方「使用者設定區」：

```python
GEMINI_API_KEY = "你的 Gemini API Key"
PROXY_BASE_URL = ""              # 若使用反代中繼站才填，留空則用官方端點
MODEL_NAME = "gemini-3.6-flash"
ASSISTANT_NAME = "鎮宇"
REQUIRE_ACTION_CONFIRMATION = True   # 電腦層級滑鼠/鍵盤操作是否需要彈窗確認，見下方說明
```

### 關於 `REQUIRE_ACTION_CONFIRMATION`

- `True`（預設）：滑鼠移動/點擊、鍵盤輸入/組合鍵執行前會跳出確認視窗，需按「✅ 允許執行」才會真的動作。
- `False`：不再跳出確認視窗，直接執行，只在聊天視窗留下一則「ℹ️ 正在執行：xxx」的提示訊息讓你知情，**不會等你回應**。

> 關閉確認後，鎮宇對滑鼠鍵盤的操作將完全不等你同意就執行，請自行評估風險。
> 開啟應用程式（`open_app`）不受此開關影響，一律會先跳出「ℹ️ 即將開啟應用程式：xxx」的提示訊息再實際開啟。

### 關於通話模式所用的模型

`GeminiLiveController` 內的 `LIVE_MODEL_NAME`（目前為 `"gemini-3.1-flash-live-preview"`）是獨立於
`MODEL_NAME` 的設定，因為 Live（即時語音）跟一般文字生成用的不是同一個模型系列。
Google 這塊更新較快，如果之後遇到「模型已下架」的錯誤，需要另外更新這個常數。

---

## 執行

```bash
python ai_assistant.py
```

---

## 使用說明

| 操作 | 說明 |
|---|---|
| 💬 文字模式 | 直接在輸入框打字，Enter 或按「送出」，純文字回覆，不會有語音 |
| 📞 通話模式 | 切換後自動連線 Gemini Live，連上後直接開口說話即可，中途可隨時插話 |
| 麥克風選單 | 通話模式輸入列上方的下拉選單，可選擇要用哪一支麥克風收音（預設為系統預設麥克風）；**若通話已經在進行中，切換選項後需按「🛑 結束通話」再重新切回通話模式，設定才會套用** |
| 🎤 靜音麥克風 | 通話中暫停傳送你的聲音給模型（連線仍保持），適合暫時不想被收音時使用 |
| 🛑 結束通話 | 停止 Gemini Live 連線，自動切回文字模式 |
| 🗗 懸浮小窗 | 主視窗縮成右下角圓角膠囊，可拖曳；膠囊上也有靜音切換鍵、掛斷鍵 |
| 🆕 新對話 | 清空目前對話紀錄與畫面；若在通話中會一併掛斷 |

**範例指令（文字或語音皆可）：**
- 「30 分鐘後幫我關機」
- 「晚上 11 點關機」
- 「取消關機」（不需要按鈕，直接說或打字）
- 「幫我開瀏覽器搜尋台北天氣」
- 「開記事本」
- 「幫我到 Google 搜尋 XXX，然後點第一個結果」（瀏覽器自動化）

---

## 工具（Function Calling）清單

文字模式與通話模式共用同一套工具（定義於 `build_shared_tools()`）。

| 工具 | 功能 | 需確認 |
|---|---|---|
| `schedule_shutdown(target_time_str)` | 指定時間關機（HH:MM，24 小時制） | 否 |
| `shutdown_in_minutes(minutes)` | N 分鐘後關機 | 否 |
| `cancel_shutdown()` | 取消排程關機 | 否 |
| `open_browser(url_or_keyword)` | 系統預設瀏覽器開網址或搜尋 | 否 |
| `open_app(app_name)` | 開啟 Windows 應用程式 | 先發出提示訊息 |
| `browser_navigate(url_or_keyword)` | 開啟/導覽自動化瀏覽器 | 否 |
| `browser_get_page_summary()` | 讀取頁面標題／網址／內容摘要 | 否 |
| `browser_click(text)` | 點擊包含指定文字的元素 | 否 |
| `browser_type_text(value, field_hint)` | 在輸入欄位填文字 | 否 |
| `browser_press_enter()` | 模擬按 Enter | 否 |
| `browser_scroll(direction)` | 上下捲動頁面 | 否 |
| `browser_close()` | 關閉自動化瀏覽器 | 否 |
| `get_screen_size()` | 取得螢幕解析度 | 否 |
| `take_screenshot()` | 截圖存檔 | 否 |
| `mouse_move(x, y)` | 移動滑鼠到指定座標 | 依 `REQUIRE_ACTION_CONFIRMATION` |
| `mouse_click(x, y, button, double)` | 滑鼠點擊 | 依 `REQUIRE_ACTION_CONFIRMATION` |
| `mouse_scroll(amount)` | 滾輪捲動 | 依 `REQUIRE_ACTION_CONFIRMATION` |
| `keyboard_type(text)` | 輸入文字到目前作用中視窗 | 依 `REQUIRE_ACTION_CONFIRMATION` |
| `keyboard_press(key)` | 按下單一按鍵 | 依 `REQUIRE_ACTION_CONFIRMATION` |
| `keyboard_hotkey(keys)` | 組合鍵，如 `ctrl+c` | 依 `REQUIRE_ACTION_CONFIRMATION` |

`open_browser` 與 `browser_navigate` 系列的差異：前者只是用系統預設瀏覽器開一個新分頁；
後者啟動一個程式完全掌控、可被持續操作（點擊/輸入/捲動）的獨立 Chrome 視窗。

「電腦層級」的滑鼠/鍵盤工具會作用在**目前作用中的任何視窗**，不限瀏覽器。

---

## 已知限制

- **Gemini Live API 相對新、變動較快**：本程式的實作是依照 Google 官方文件的範例模式撰寫，
  尚未在真實麥克風/喇叭硬體上實測過，第一次執行若遇到 API 細節不符（例如回傳欄位命名微調），
  可能需要對照 Google 官方 Live API 文件（https://ai.google.dev/api/live）微調程式碼
- 通話模式需要網路連線（Gemini Live 走 WebSocket 串流）
- 瀏覽器自動化沒有額外二次確認機制，請避免請它操作涉及刪除／付款／轉帳的頁面
- 電腦層級滑鼠/鍵盤操作若關閉了 `REQUIRE_ACTION_CONFIRMATION`，操作範圍就是**當下整台電腦的作用中視窗**，請留意
- 沒有檔案讀寫、軟體安裝移除、系統設定變更等能力
- 遇到 reCAPTCHA / Cloudflare 等防機器人機制的網站，瀏覽器自動化可能會被擋下
- pyautogui 的座標操作是「盲操作」，AI 並不能真正「看到」螢幕內容，下座標前建議先用 `take_screenshot()` 讓使用者自行確認畫面狀態

---

## 打包成 .exe

```bash
pyinstaller --noconsole --onefile ^
  --collect-all customtkinter ^
  --collect-all selenium ^
  --collect-all webdriver_manager ^
  ai_assistant.py
```

打包後的執行檔在 `dist/ai_assistant.exe`。

> 目標電腦上仍需要：Google Chrome（瀏覽器自動化用）、網路連線、麥克風（通話模式用）。
