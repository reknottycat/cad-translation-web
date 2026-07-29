#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAD文件翻译处理主控制脚本

功能:
1. 将DWG文件转换为DXF文件
2. 从DXF文件中提取文本
3. 等待用户填写翻译
4. 将翻译回填到DXF文件中

作者: AI Assistant
日期: 2024
"""

import os
import sys
from pathlib import Path
import subprocess
import time
from logger_config import get_logger

# 初始化日志记录器
logger = get_logger("main_processor")

def print_banner():
    """打印程序横幅"""
    print("="*60)
    print("           CAD文件翻译处理系统")
    print("="*60)
    print()

def check_dependencies():
    """检查必要的依赖
    
    Returns:
        tuple: (bool, list) - (是否所有依赖都满足, 缺失的依赖列表)
    """
    logger.info("开始检查依赖库")
    print("检查依赖库...")
    
    required_modules = ['ezdxf', 'pandas', 'openpyxl']
    missing_modules = []
    
    for module in required_modules:
        try:
            __import__(module)
            logger.debug(f"依赖库检查通过: {module}")
            print(f"✓ {module}")
        except ImportError:
            logger.warning(f"依赖库缺失: {module}")
            print(f"✗ {module} (缺失)")
            missing_modules.append(module)
    
    if missing_modules:
        logger.error(f"缺少依赖库: {', '.join(missing_modules)}")
        print(f"\n缺少以下依赖库: {', '.join(missing_modules)}")
        print("请运行以下命令安装:")
        print(f"pip install {' '.join(missing_modules)}")
        return False, missing_modules
    
    logger.info("所有依赖库检查完成")
    print("✓ 所有依赖库已安装")
    return True, []

def run_script(script_name, description):
    """运行指定的Python脚本"""
    logger.info(f"准备运行脚本: {script_name} - {description}")
    script_path = Path(script_name)
    
    if not script_path.exists():
        logger.error(f"脚本文件不存在: {script_name}")
        print(f"✗ 错误: 脚本文件 {script_name} 不存在")
        return False
    
    print(f"\n{description}...")
    print(f"运行脚本: {script_name}")
    print("-" * 40)
    
    try:
        logger.debug(f"开始执行脚本: {script_name}")
        # 使用subprocess运行脚本
        result = subprocess.run([sys.executable, script_name], 
                              capture_output=False, 
                              text=True, 
                              cwd=Path.cwd())
        
        if result.returncode == 0:
            logger.info(f"脚本执行成功: {script_name}")
            print("-" * 40)
            print(f"✓ {description}完成")
            return True
        else:
            logger.error(f"脚本执行失败: {script_name}, 退出码: {result.returncode}")
            print("-" * 40)
            print(f"✗ {description}失败 (退出码: {result.returncode})")
            return False
            
    except Exception as e:
        logger.error(f"运行脚本时发生异常: {script_name}, 错误: {e}")
        print(f"✗ 运行脚本时出错: {e}")
        return False

def wait_for_translation():
    """等待用户完成翻译"""
    logger.info("开始等待用户完成翻译")
    print("\n" + "="*60)
    print("           请完成翻译工作")
    print("="*60)
    print()
    print("1. 请打开生成的Excel文件: extracted_texts_for_translation.xlsx")
    print("2. 在 'Translated Text' 列中填写对应的翻译")
    print("3. 保存Excel文件")
    print("4. 完成后按回车键继续...")
    print()
    
    # 检查Excel文件是否存在
    excel_file = Path("extracted_texts_for_translation.xlsx")
    logger.debug(f"检查Excel文件是否存在: {excel_file}")
    if excel_file.exists():
        logger.info(f"找到Excel翻译文件: {excel_file}")
        print(f"✓ 找到Excel文件: {excel_file}")
        
        # 尝试打开Excel文件
        try:
            if os.name == 'nt':  # Windows
                logger.debug("尝试自动打开Excel文件")
                os.startfile(str(excel_file))
                logger.info("成功自动打开Excel文件")
                print("✓ 已尝试打开Excel文件")
        except Exception as e:
            logger.warning(f"无法自动打开Excel文件: {e}")
            print(f"无法自动打开Excel文件: {e}")
            print(f"请手动打开: {excel_file.absolute()}")
    else:
        logger.error(f"未找到Excel翻译文件: {excel_file}")
        print(f"✗ 未找到Excel文件: {excel_file}")
        print("请确保文本提取步骤成功完成")
        return False
    
    logger.info("等待用户确认翻译完成")
    input("\n按回车键继续回填翻译...")
    logger.info("用户确认翻译完成，继续处理")
    return True

def check_files():
    """检查必要的文件"""
    logger.info("开始检查必要文件")
    print("\n检查文件...")
    
    # 检查DWG文件
    dwg_files = list(Path('.').glob('*.dwg')) + list(Path('.').glob('*.DWG'))
    if dwg_files:
        logger.info(f"找到 {len(dwg_files)} 个DWG文件")
        print(f"✓ 找到 {len(dwg_files)} 个DWG文件:")
        for dwg in dwg_files[:5]:  # 只显示前5个
            logger.debug(f"DWG文件: {dwg.name}")
            print(f"  - {dwg.name}")
        if len(dwg_files) > 5:
            print(f"  ... 还有 {len(dwg_files) - 5} 个文件")
    else:
        logger.error("未找到DWG文件")
        print("✗ 未找到DWG文件")
        return False
    
    # 检查脚本文件
    logger.info("检查必要的脚本文件")
    required_scripts = ['dwg_converter.py', '提取.py', '回填.py']
    for script in required_scripts:
        if Path(script).exists():
            logger.debug(f"脚本文件存在: {script}")
            print(f"✓ {script}")
        else:
            logger.error(f"脚本文件缺失: {script}")
            print(f"✗ {script} (缺失)")
            return False
    
    logger.info("所有必要文件检查完成")
    return True

def main():
    """主函数"""
    logger.info("CAD文件翻译处理系统启动")
    print_banner()
    
    # 检查依赖
    deps_ok, missing_deps = check_dependencies()
    if not deps_ok:
        logger.error(f"依赖检查失败，缺少: {missing_deps}")
        input("\n按回车键退出...")
        return
    
    print()
    
    # 检查文件
    if not check_files():
        logger.error("文件检查失败，程序退出")
        print("\n请确保所有必要的文件都存在于当前目录中。")
        input("按回车键退出...")
        return
    
    logger.info("开始CAD文件翻译处理流程")
    print("\n" + "="*60)
    print("           开始处理流程")
    print("="*60)
    
    # 步骤1: 转换DWG到DXF
    if not run_script('dwg_converter.py', '步骤1: 转换DWG文件到DXF格式'):
        logger.error("DWG转换步骤失败")
        print("\n转换失败，请检查错误信息。")
        input("按回车键退出...")
        return
    
    # 步骤2: 提取文本
    if not run_script('提取.py', '步骤2: 从DXF文件中提取文本'):
        logger.error("文本提取步骤失败")
        print("\n文本提取失败，请检查错误信息。")
        input("按回车键退出...")
        return
    
    # 步骤3: 等待翻译
    if not wait_for_translation():
        logger.error("翻译等待步骤失败")
        print("\n无法继续，请检查Excel文件。")
        input("按回车键退出...")
        return
    
    # 步骤4: 回填翻译
    if not run_script('回填.py', '步骤4: 回填翻译到DXF文件'):
        logger.error("翻译回填步骤失败")
        print("\n翻译回填失败，请检查错误信息。")
        input("按回车键退出...")
        return
    
    # 完成
    logger.info("CAD文件翻译处理流程完成")
    print("\n" + "="*60)
    print("           处理完成！")
    print("="*60)
    print()
    print("✓ 所有步骤已完成")
    print("✓ 翻译后的文件保存在 'translated_drawings' 文件夹中")
    print("✓ 原始文件保持不变")
    print()
    print("感谢使用CAD文件翻译处理系统！")
    
    input("\n按回车键退出...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("用户中断程序执行")
        print("\n\n用户中断操作。")
    except Exception as e:
        logger.error(f"程序运行异常: {e}", exc_info=True)
        print(f"\n\n程序出现错误: {e}")
        input("按回车键退出...")
    finally:
        logger.info("CAD文件翻译处理系统退出")