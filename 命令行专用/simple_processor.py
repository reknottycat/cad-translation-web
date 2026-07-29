#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版CAD文件翻译处理脚本

适用于以下情况：
1. 无法安装ODA File Converter
2. 已经有DXF文件
3. 需要手动转换DWG文件

作者: AI Assistant
日期: 2024
"""

import os
import sys
from pathlib import Path
import subprocess
from logger_config import get_logger

# 初始化日志记录器
logger = get_logger("simple_processor")

def print_banner():
    """打印程序横幅"""
    print("="*60)
    print("        简化版CAD文件翻译处理系统")
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
            logger.debug(f"依赖库 {module} 检查通过")
            print(f"✓ {module}")
        except ImportError:
            logger.warning(f"依赖库 {module} 缺失")
            print(f"✗ {module} (缺失)")
            missing_modules.append(module)
    
    if missing_modules:
        logger.error(f"缺少依赖库: {missing_modules}")
        print(f"\n缺少以下依赖库: {', '.join(missing_modules)}")
        print("请运行以下命令安装:")
        print(f"pip install {' '.join(missing_modules)}")
        return False, missing_modules
    
    logger.info("所有依赖库检查完成")
    print("✓ 所有依赖库已安装")
    return True, []

def check_files():
    """检查文件情况"""
    logger.info("开始检查文件")
    print("\n检查文件...")
    
    # 检查DXF文件
    dxf_files = list(Path('.').glob('*.dxf')) + list(Path('.').glob('*.DXF'))
    dwg_files = list(Path('.').glob('*.dwg')) + list(Path('.').glob('*.DWG'))
    
    logger.debug(f"扫描到 {len(dxf_files)} 个DXF文件，{len(dwg_files)} 个DWG文件")
    
    if dxf_files:
        logger.info(f"找到 {len(dxf_files)} 个DXF文件")
        print(f"✓ 找到 {len(dxf_files)} 个DXF文件:")
        for dxf in dxf_files[:5]:  # 只显示前5个
            print(f"  - {dxf.name}")
        if len(dxf_files) > 5:
            print(f"  ... 还有 {len(dxf_files) - 5} 个文件")
        return True, 'dxf'
    elif dwg_files:
        logger.info(f"找到 {len(dwg_files)} 个DWG文件")
        print(f"✓ 找到 {len(dwg_files)} 个DWG文件:")
        for dwg in dwg_files[:5]:  # 只显示前5个
            print(f"  - {dwg.name}")
        if len(dwg_files) > 5:
            print(f"  ... 还有 {len(dwg_files) - 5} 个文件")
        return True, 'dwg'
    else:
        logger.warning("未找到DXF或DWG文件")
        print("✗ 未找到DXF或DWG文件")
        return False, None

def provide_dwg_conversion_guide():
    """提供DWG转换指导"""
    print("\n" + "="*60)
    print("           DWG文件转换指导")
    print("="*60)
    print()
    print("由于您有DWG文件但没有自动转换工具，请选择以下方法之一:")
    print()
    print("方法1: 使用免费的在线转换工具")
    print("  - 访问: https://convertio.co/dwg-dxf/")
    print("  - 或者: https://www.zamzar.com/convert/dwg-to-dxf/")
    print("  - 上传DWG文件，下载转换后的DXF文件")
    print("  - 将DXF文件放在当前目录中")
    print()
    print("方法2: 使用AutoCAD或兼容软件")
    print("  - 打开DWG文件")
    print("  - 另存为DXF格式")
    print("  - 将DXF文件放在当前目录中")
    print()
    print("方法3: 安装ODA File Converter (推荐)")
    print("  - 下载: https://www.opendesign.com/guestfiles/oda_file_converter")
    print("  - 安装后运行 main_processor.py 获得完整功能")
    print()
    print("转换完成后，请重新运行此脚本。")

def run_script(script_name, description):
    """运行指定的Python脚本"""
    logger.info(f"准备运行脚本: {script_name}")
    script_path = Path(script_name)
    
    if not script_path.exists():
        logger.error(f"脚本文件不存在: {script_name}")
        print(f"✗ 错误: 脚本文件 {script_name} 不存在")
        return False
    
    logger.info(f"开始执行: {description}")
    print(f"\n{description}...")
    print(f"运行脚本: {script_name}")
    print("-" * 40)
    
    try:
        # 使用subprocess运行脚本
        logger.debug(f"执行命令: {sys.executable} {script_name}")
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
            logger.error(f"脚本执行失败: {script_name}，退出码: {result.returncode}")
            print("-" * 40)
            print(f"✗ {description}失败 (退出码: {result.returncode})")
            return False
            
    except Exception as e:
        logger.error(f"运行脚本时出错: {script_name}，错误: {e}")
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

def main():
    """主函数"""
    logger.info("简化版CAD文件翻译处理系统启动")
    print_banner()
    
    # 检查依赖
    if not check_dependencies():
        logger.error("依赖检查失败，程序退出")
        input("\n按回车键退出...")
        return
    
    print()
    
    # 检查文件
    has_files, file_type = check_files()
    if not has_files:
        logger.error("未找到可处理的文件")
        print("\n请确保当前目录中有DXF或DWG文件。")
        input("按回车键退出...")
        return
    
    # 如果只有DWG文件，提供转换指导
    if file_type == 'dwg':
        logger.info("检测到DWG文件，提供转换指导")
        provide_dwg_conversion_guide()
        input("\n按回车键退出...")
        return
    
    # 检查必要的脚本
    logger.info("检查必要的脚本文件")
    required_scripts = ['提取.py', '回填.py']
    for script in required_scripts:
        if not Path(script).exists():
            logger.error(f"缺少脚本文件: {script}")
            print(f"✗ 缺少脚本文件: {script}")
            input("按回车键退出...")
            return
    
    logger.info("开始CAD文件翻译处理流程")
    print("\n" + "="*60)
    print("           开始处理流程")
    print("="*60)
    
    # 步骤1: 提取文本
    if not run_script('提取.py', '步骤1: 从DXF文件中提取文本'):
        logger.error("文本提取步骤失败")
        print("\n文本提取失败，请检查错误信息。")
        input("按回车键退出...")
        return
    
    # 步骤2: 等待翻译
    if not wait_for_translation():
        logger.error("翻译等待步骤失败")
        print("\n无法继续，请检查Excel文件。")
        input("按回车键退出...")
        return
    
    # 步骤3: 回填翻译
    if not run_script('回填.py', '步骤3: 回填翻译到DXF文件'):
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
        print("\n程序被用户中断")
    except Exception as e:
        logger.error(f"程序运行异常: {e}", exc_info=True)
        print(f"\n程序运行出错: {e}")
        input("按回车键退出...")
    finally:
        logger.info("简化版CAD文件翻译处理系统退出")