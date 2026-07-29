#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD翻译工具 - 日志配置模块
提供统一的日志配置和管理功能
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler


class LoggerConfig:
    """日志配置管理类"""
    
    def __init__(self, log_dir="logs", max_file_size=10*1024*1024, backup_count=5):
        """
        初始化日志配置
        
        Args:
            log_dir: 日志文件目录
            max_file_size: 单个日志文件最大大小（字节）
            backup_count: 保留的备份文件数量
        """
        self.log_dir = log_dir
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self._ensure_log_directory()
        
    def _ensure_log_directory(self):
        """确保日志目录存在"""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
    
    def setup_logger(self, name="cad_translator", level=logging.INFO):
        """
        设置并返回配置好的日志记录器
        
        Args:
            name: 日志记录器名称
            level: 日志级别
            
        Returns:
            logging.Logger: 配置好的日志记录器
        """
        logger = logging.getLogger(name)
        
        # 避免重复添加处理器
        if logger.handlers:
            return logger
            
        logger.setLevel(level)
        
        # 创建日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 文件处理器 - 使用轮转日志
        log_file = os.path.join(self.log_dir, f"{name}.log")
        file_handler = RotatingFileHandler(
            log_file, 
            maxBytes=self.max_file_size,
            backupCount=self.backup_count,
            encoding='utf-8-sig'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)  # 控制台只显示警告及以上级别
        console_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        
        # 添加处理器到日志记录器
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
    
    def get_logger(self, name="cad_translator"):
        """
        获取已配置的日志记录器
        
        Args:
            name: 日志记录器名称
            
        Returns:
            logging.Logger: 日志记录器
        """
        return logging.getLogger(name)


# 全局日志配置实例
_logger_config = LoggerConfig()

# 便捷函数
def get_logger(name="cad_translator", level=logging.INFO):
    """
    获取配置好的日志记录器的便捷函数
    
    Args:
        name: 日志记录器名称
        level: 日志级别
        
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    return _logger_config.setup_logger(name, level)


def log_function_call(func):
    """
    装饰器：自动记录函数调用
    
    Args:
        func: 被装饰的函数
        
    Returns:
        function: 装饰后的函数
    """
    def wrapper(*args, **kwargs):
        logger = get_logger()
        logger.debug(f"调用函数: {func.__name__}, 参数: args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"函数 {func.__name__} 执行成功")
            return result
        except Exception as e:
            logger.error(f"函数 {func.__name__} 执行失败: {str(e)}")
            raise
    return wrapper


if __name__ == "__main__":
    # 测试日志配置
    logger = get_logger("test_logger")
    
    logger.debug("这是调试信息")
    logger.info("这是信息日志")
    logger.warning("这是警告信息")
    logger.error("这是错误信息")
    logger.critical("这是严重错误信息")
    
    print(f"日志文件已创建在: {os.path.abspath('logs')}")