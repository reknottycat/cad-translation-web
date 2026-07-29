#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXF文本提取脚本 - 生产环境版本
使用新的模块化DXF文本提取引擎

作者: AI Assistant
日期: 2024
"""

import sys
import os
from pathlib import Path
import argparse
from typing import Optional

# 添加当前目录到Python路径
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

try:
    from dxf_text_extractor import (
        TextExtractionEngine,
        ModelSpaceExtractor,
        PaperSpaceExtractor,
        BlockDefinitionExtractor,
        DXFTagExtractor,
        TextFilter,
        ExcelExporter
    )
    from logger_config import get_logger
except ImportError as e:
    print(f"导入模块失败: {e}")
    print("请确保dxf_text_extractor.py和logger_config.py文件存在")
    sys.exit(1)

def main():
    """主函数 - 提取当前目录下所有DXF文件的文本并导出到Excel"""
    # 初始化日志
    logger = get_logger("extract_texts")
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='提取DXF文件中的文本内容')
    parser.add_argument('--directory', '-d', type=str, default='.', 
                       help='要处理的目录路径（默认为当前目录）')
    parser.add_argument('--output', '-o', type=str, default='extracted_texts.xlsx',
                       help='输出Excel文件名（默认为extracted_texts.xlsx）')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='显示详细日志信息')
    
    args = parser.parse_args()
    
    # 设置工作目录
    work_dir = Path(args.directory).resolve()
    if not work_dir.exists():
        logger.error(f"目录不存在: {work_dir}")
        print(f"错误：目录不存在 - {work_dir}")
        return 1
    
    logger.info(f"开始处理目录: {work_dir}")
    print(f"正在处理目录: {work_dir}")
    
    try:
        # 创建文本提取引擎
        engine = TextExtractionEngine()
        
        # 查找DXF文件（包括子目录）
        dxf_files = list(work_dir.glob('**/*.dxf'))  # 递归搜索所有子目录
        if not dxf_files:
            logger.warning(f"在目录 {work_dir} 及其子目录中未找到DXF文件")
            print("警告：未找到DXF文件")
            return 0
        
        logger.info(f"找到 {len(dxf_files)} 个DXF文件")
        print(f"找到 {len(dxf_files)} 个DXF文件")
        
        # 处理目录中的所有DXF文件
        result = engine.extract_from_directory(str(work_dir))
        
        if result:
            # 导出到Excel
            output_path = work_dir / args.output
            success = engine.excel_exporter.export_to_excel(result, str(output_path))
            
            if success:
                logger.info(f"文本提取完成，结果已保存到: {output_path}")
                print(f"[成功] 提取完成！结果已保存到: {output_path}")
                print(f"[成功] 共提取到 {len(result)} 条文本")
                return 0
            else:
                logger.error("导出Excel文件失败")
                print("[错误] 导出Excel文件失败")
                return 1
        else:
            logger.warning("未提取到任何文本内容")
            print("警告：未提取到任何文本内容")
            return 0
            
    except Exception as e:
        logger.error(f"处理过程中发生错误: {e}")
        print(f"[错误] {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())