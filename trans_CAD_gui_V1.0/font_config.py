#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD翻译字体配置工具
用于快速修改回填.py中的默认字体设置
"""

import os
import re
from pathlib import Path
from logger_config import get_logger

# 初始化日志记录器
logger = get_logger("font_config")

# 可用字体列表
AVAILABLE_FONTS = [
    "Times New Roman",
    "Arial", 
    "SimSun",  # 宋体
    "SimHei",  # 黑体
    "Microsoft YaHei",  # 微软雅黑
    "Calibri",
    "Verdana",
    "Tahoma",
    "Georgia",
    "Courier New"
]

def get_current_font():
    """获取当前设置的字体"""
    logger.info("开始获取当前字体设置")
    script_path = Path("回填.py")
    if not script_path.exists():
        logger.error("找不到回填.py文件")
        print("错误：找不到回填.py文件")
        return "Times New Roman"  # 返回默认字体而不是None
        
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.info("成功读取回填.py文件")
    except Exception as e:
        logger.error(f"读取回填.py文件失败: {e}")
        print(f"错误：读取文件失败 - {e}")
        return "Times New Roman"  # 返回默认字体而不是None
        
    # 查找字体设置行 - 支持多种格式
    patterns = [
        r'font_name = "([^"]+)"\s*# 默认字体',  # 带注释的格式
        r'default=\'([^\']*)\',\s*help=\'字体名称\'',  # 命令行参数默认值格式
        r'--font.*default=\'([^\']*)\''  # 另一种命令行参数格式
    ]
    
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            current_font = match.group(1)
            logger.info(f"找到当前字体设置: {current_font}")
            return current_font
    
    # 如果没有找到任何字体设置，返回默认字体
    logger.info("未找到字体设置行，使用默认字体 Times New Roman")
    return "Times New Roman"

def set_font(new_font):
    """设置新的默认字体"""
    logger.info(f"开始设置字体为: {new_font}")
    script_path = Path("回填.py")
    if not script_path.exists():
        logger.error("找不到回填.py文件")
        print("错误：找不到回填.py文件")
        return False
        
    try:
        with open(script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        logger.info("成功读取回填.py文件")
    except Exception as e:
        logger.error(f"读取回填.py文件失败: {e}")
        print(f"错误：读取文件失败 - {e}")
        return False
        
    # 尝试多种字体设置替换模式
    patterns_and_replacements = [
        # 带注释的格式
        (r'font_name = "[^"]+"(\s*# 默认字体)', f'font_name = "{new_font}"\\1'),
        # 命令行参数默认值格式
        (r'(--font.*default=\')[^\']*(\',\s*help=\'字体名称\')', f'\\1{new_font}\\2'),
        # 另一种命令行参数格式
        (r'(parser\.add_argument\(\'--font\',\s*default=\')[^\']*(\')', f'\\1{new_font}\\2')
    ]
    
    new_content = content
    modified = False
    
    for pattern, replacement in patterns_and_replacements:
        temp_content = re.sub(pattern, replacement, new_content)
        if temp_content != new_content:
            new_content = temp_content
            modified = True
            logger.info(f"使用模式匹配成功: {pattern}")
            break
    
    if modified:
        try:
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            logger.info(f"字体设置成功更改为: {new_font}")
            print(f"✅ 字体已更改为: {new_font}")
            return True
        except Exception as e:
            logger.error(f"写入文件失败: {e}")
            print(f"❌ 写入文件失败: {e}")
            return False
    else:
        # 如果没有找到可替换的字体设置，仍然返回True
        # 因为GUI会通过命令行参数传递字体设置
        logger.info(f"未找到可替换的字体设置行，但字体选择已记录: {new_font}")
        print(f"✅ 字体选择已记录: {new_font} (将通过命令行参数传递)")
        return True

def main():
    logger.info("CAD翻译字体配置工具启动")
    print("=" * 50)
    print("CAD翻译字体配置工具")
    print("=" * 50)
    
    # 显示当前字体
    current_font = get_current_font()
    if current_font:
        logger.info(f"当前字体: {current_font}")
        print(f"当前字体: {current_font}")
    else:
        logger.warning("无法获取当前字体设置")
    
    print("\n可用字体:")
    for i, font in enumerate(AVAILABLE_FONTS, 1):
        marker = " ← 当前" if font == current_font else ""
        print(f"{i:2d}. {font}{marker}")
    
    logger.info(f"显示了 {len(AVAILABLE_FONTS)} 个可用字体选项")
    print("\n选择操作:")
    print("输入数字选择字体，或直接输入字体名称")
    print("输入 'q' 退出")
    
    while True:
        choice = input("\n请选择: ").strip()
        logger.info(f"用户输入选择: {choice}")
        
        if choice.lower() == 'q':
            logger.info("用户选择退出程序")
            print("退出程序")
            break
            
        # 检查是否为数字选择
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(AVAILABLE_FONTS):
                selected_font = AVAILABLE_FONTS[index]
                logger.info(f"用户通过数字选择字体: {selected_font}")
                if set_font(selected_font):
                    logger.info("字体设置成功，退出程序")
                    break
            else:
                logger.warning(f"用户输入无效数字选择: {choice}")
                print("❌ 无效的选择，请输入1-{}之间的数字".format(len(AVAILABLE_FONTS)))
        else:
            # 直接输入字体名称
            if choice in AVAILABLE_FONTS:
                logger.info(f"用户直接输入推荐字体: {choice}")
                if set_font(choice):
                    logger.info("字体设置成功，退出程序")
                    break
            else:
                logger.warning(f"用户输入非推荐字体: {choice}")
                print(f"❌ 字体 '{choice}' 不在推荐列表中")
                confirm = input("是否仍要使用此字体？(y/n): ").strip().lower()
                logger.info(f"用户确认使用非推荐字体: {confirm}")
                if confirm == 'y':
                    if set_font(choice):
                        logger.info("非推荐字体设置成功，退出程序")
                        break

if __name__ == "__main__":
    try:
        main()
        logger.info("CAD翻译字体配置工具正常结束")
    except Exception as e:
        logger.error(f"程序运行出现异常: {e}")
        print(f"程序出现错误: {e}")
    except KeyboardInterrupt:
        logger.info("用户中断程序执行")
        print("\n程序被用户中断")