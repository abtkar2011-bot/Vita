@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Fatin (فطن)... the app will open in your browser.
python -m streamlit run app.py
pause
