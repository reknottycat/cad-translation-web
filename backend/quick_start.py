#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD文件翻译处理Web系统 - 快速启动脚本
Quick start script for CAD File Translation Web System
"""

import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path

def print_banner():
    """打印启动横幅"""
    print("=" * 70)
    print("  CAD文件翻译处理Web系统 - 快速启动")
    print("  CAD File Translation Web System - Quick Start")
    print("=" * 70)

def check_redis():
    """检查Redis是否运行"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        return True
    except:
        return False

def start_redis_if_needed():
    """如果需要，启动Redis"""
    if not check_redis():
        print("⚠️  Redis未运行，尝试启动...")
        
        # 尝试不同的Redis启动方式
        redis_commands = [
            ["redis-server"],
            ["redis-server.exe"],
            ["docker", "run", "-d", "-p", "6379:6379", "redis:alpine"]
        ]
        
        for cmd in redis_commands:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
                if check_redis():
                    print("✅ Redis启动成功")
                    return True
            except:
                continue
        
        print("❌ 无法自动启动Redis，请手动启动:")
        print("   - 直接启动: redis-server")
        print("   - Docker: docker run -d -p 6379:6379 redis:alpine")
        return False
    else:
        print("✅ Redis已运行")
        return True

def install_dependencies():
    """安装依赖"""
    print("📦 检查并安装依赖...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ 依赖安装完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 依赖安装失败: {e}")
        return False

def create_directories():
    """创建必要目录"""
    directories = ["uploads", "outputs", "static", "logs"]
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
    print("✅ 工作目录创建完成")

def start_services():
    """启动服务"""
    print("\n🚀 启动服务...")
    
    # 启动FastAPI服务器
    print("启动Web服务器...")
    server_process = subprocess.Popen([
        sys.executable, "run_server.py"
    ])
    
    # 等待服务器启动
    time.sleep(3)
    
    # 启动Celery Worker
    print("启动任务处理器...")
    celery_process = subprocess.Popen([
        sys.executable, "run_celery.py"
    ])
    
    # 等待服务启动
    time.sleep(2)
    
    print("\n✅ 服务启动完成!")
    print("=" * 50)
    print("🌐 Web服务: http://localhost:8000")
    print("📚 API文档: http://localhost:8000/docs")
    print("🔍 健康检查: http://localhost:8000/api/health")
    print("=" * 50)
    
    # 打开浏览器
    try:
        webbrowser.open("http://localhost:8000/docs")
        print("🌐 已在浏览器中打开API文档")
    except:
        print("💡 请手动打开浏览器访问: http://localhost:8000/docs")
    
    print("\n⚠️  按 Ctrl+C 停止所有服务")
    
    try:
        # 等待用户中断
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 正在停止服务...")
        
        # 停止进程
        server_process.terminate()
        celery_process.terminate()
        
        # 等待进程结束
        server_process.wait(timeout=5)
        celery_process.wait(timeout=5)
        
        print("✅ 所有服务已停止")

def main():
    """主函数"""
    print_banner()
    
    # 切换到backend目录
    backend_dir = Path(__file__).parent
    os.chdir(backend_dir)
    
    print("📋 快速启动检查清单:")
    
    # 1. 安装依赖
    if not install_dependencies():
        return False
    
    # 2. 创建目录
    create_directories()
    
    # 3. 检查Redis
    if not start_redis_if_needed():
        print("\n❌ Redis服务未运行，某些功能可能无法正常工作")
        response = input("是否继续启动? (y/N): ")
        if response.lower() != 'y':
            return False
    
    # 4. 启动服务
    start_services()
    
    return True

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 再见!")
    except Exception as e:
        print(f"\n❌ 启动失败: {str(e)}")
        sys.exit(1)