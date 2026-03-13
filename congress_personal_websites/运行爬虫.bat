@echo off
chcp 65001 >nul

REM 美国众议院议员网站爬虫
REM 这个批处理文件会安装依赖并运行爬虫脚本

echo 美国众议院议员网站爬虫
echo ====================================

REM 检查Python是否安装
echo 检查Python环境...
python --version
if %errorlevel% neq 0 (
    echo 错误: 未找到Python。请先安装Python 3.8或更高版本。
    echo 请访问 https://www.python.org/downloads/ 下载安装
    pause
    exit /b 1
)

echo 正在安装依赖包...
python -m pip install requests beautifulsoup4 pandas openpyxl
if %errorlevel% neq 0 (
    echo 错误: 依赖包安装失败。请检查网络连接。
    pause
    exit /b 1
)
echo 依赖包安装完成！

echo 正在运行爬虫脚本...
python house_reps_scraper.py
if %errorlevel% neq 0 (
    echo 错误: 脚本运行失败。
    pause
    exit /b 1
)

echo ====================================
echo 爬虫运行完成！
echo 请查看当前目录下的文件：
dir /b
echo.
echo 按任意键退出...
pause >nul
