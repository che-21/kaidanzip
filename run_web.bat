@echo off
REM MD2Short 웹 화면 실행 (더블클릭). 브라우저에서 http://localhost:8501 이 열립니다.
cd /d "%~dp0"
python -m uv run streamlit run webapp/app.py
pause
