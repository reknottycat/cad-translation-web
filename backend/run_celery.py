#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD文件翻译处理Web系统 - Celery Worker启动脚本
Celery Worker startup script for CAD File Translation Web System
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.celery_app import celery_app

def main():
    """启动Celery Worker"""
    print("=" * 60)
    print("CAD文件翻译处理Web系统 - Celery Worker")
    print("=" * 60)
    print("启动后台任务处理器...")
    print("按 Ctrl+C 停止")
    print("=" * 60)
    
    # 启动Celery Worker
    celery_app.worker_main([
        'worker',
        '--loglevel=info',
        '--concurrency=2',  # 并发数
        '--pool=threads',   # 使用线程池
        '--queues=default,cad_processing',  # 监听的队列
    ])

if __name__ == "__main__":
    main()