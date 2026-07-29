@echo off

REM CAD翻译工具启动脚本
REM 此脚本用于启动CAD翻译GUI应用

chcp 65001 >nul

echo ====================================
echo 🚀 CAD文件翻译处理系统启动脚本
echo ====================================

REM 检查Python是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 错误：未找到Python，请先安装Python 3.8+
    echo 建议从 https://www.python.org/downloads/ 下载并安装
    pause
    exit /b 1
)

REM 检查依赖是否已安装
echo 🔍 检查依赖项...
pip list | findstr "ezdxf pandas openpyxl customtkinter" >nul
if %errorlevel% neq 0 (
    echo ⏳ 正在安装必要依赖...
    pip install ezdxf pandas openpyxl customtkinter
    if %errorlevel% neq 0 (
        echo ❌ 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
    echo ✅ 依赖安装成功
)

REM 启动GUI应用
echo 📡 启动CAD翻译工具...
python gui.py

REM 检查应用是否正常启动
if %errorlevel% neq 0 (
    echo ❌ 应用启动失败，请检查错误信息
    pause
    exit /b 1
)

echo 🎉 应用已成功启动
pause