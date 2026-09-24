Python 從零開始安裝

如果電腦目前完全沒有 Python，可以使用以下 CMD 指令從零開始安裝。

1. 安裝 Python

開啟 Windows CMD，輸入：

winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements


安裝完成後，關閉 CMD，再重新開啟 CMD。

2. 更新 pip

重新開啟 CMD 後輸入：

py -m pip install --upgrade pip

3. 安裝需要的 Python 套件
py -m pip install customtkinter google-genai selenium webdriver-manager pyautogui pyperclip pyaudio

4. 一行全部完成

如果想一次執行：

winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements && py -m pip install --upgrade pip && py -m pip install customtkinter google-genai selenium webdriver-manager pyautogui pyperclip pyaudio


注意：如果完全沒有 Python，建議使用「分三步執行」的方法。

Python 安裝完成後需要重新開啟 CMD，否則可能出現找不到 py 的問題。
