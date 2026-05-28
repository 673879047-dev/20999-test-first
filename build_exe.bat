@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在安装打包依赖...
pip install pyinstaller -q

echo 正在打包 20999 上位机...
python -m PyInstaller --noconfirm --clean ^
  --onefile ^
  --windowed ^
  --name "20999上位机" ^
  --add-data "protocol_catalog.json;." ^
  --hidden-import gb20999 ^
  --hidden-import gb20999.app ^
  --hidden-import gb20999.protocol ^
  --hidden-import gb20999.udp_comm ^
  --hidden-import gb20999.result_view ^
  main.py

if %ERRORLEVEL% NEQ 0 (
    echo 打包失败
    pause
    exit /b 1
)

echo.
echo 打包完成: dist\20999上位机.exe
echo 可将 dist\20999上位机.exe 单独复制到其他电脑运行
pause
