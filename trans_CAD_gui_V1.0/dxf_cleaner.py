#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXF文件清理工具
用于修复DXF文件中的无效数据，特别是SEQEND实体的layer属性问题

作者: AI Assistant
日期: 2024
"""

import ezdxf
import re
from pathlib import Path
import shutil
import os

def clean_layer_name(layer_name):
    """
    清理图层名称，移除无效字符
    
    Args:
        layer_name: 原始图层名称
        
    Returns:
        清理后的图层名称
    """
    if not layer_name or not isinstance(layer_name, str):
        return "0"  # 默认图层
    
    # 移除非ASCII字符和问号
    cleaned = re.sub(r'[^\w\-_.]', '', layer_name)
    
    # 如果清理后为空或只包含无效字符，使用默认图层
    if not cleaned or cleaned.isspace():
        return "0"
    
    # 确保图层名不以数字开头（DXF规范）
    if cleaned[0].isdigit():
        cleaned = "Layer_" + cleaned
    
    # 限制长度（DXF图层名最大255字符）
    return cleaned[:255]

def fix_seqend_entities(doc):
    """
    修复SEQEND实体的无效属性
    
    Args:
        doc: ezdxf文档对象
        
    Returns:
        修复的实体数量
    """
    fixed_count = 0
    
    # 遍历所有布局（模型空间和图纸空间）
    for layout in doc.layouts:
        for entity in layout:
            if entity.dxftype() == 'SEQEND':
                try:
                    # 检查并修复layer属性
                    if hasattr(entity.dxf, 'layer'):
                        original_layer = entity.dxf.layer
                        cleaned_layer = clean_layer_name(original_layer)
                        
                        if original_layer != cleaned_layer:
                            print(f"修复SEQEND实体图层: '{original_layer}' -> '{cleaned_layer}'")
                            entity.dxf.layer = cleaned_layer
                            fixed_count += 1
                            
                    # 确保SEQEND实体有必要的属性
                    if not hasattr(entity.dxf, 'layer') or not entity.dxf.layer:
                        entity.dxf.layer = "0"
                        fixed_count += 1
                        
                except Exception as e:
                    print(f"修复SEQEND实体时出错: {e}")
                    # 尝试设置默认值
                    try:
                        entity.dxf.layer = "0"
                        fixed_count += 1
                    except:
                        pass
    
    return fixed_count

def fix_all_entities(doc):
    """
    修复所有实体的无效图层属性
    
    Args:
        doc: ezdxf文档对象
        
    Returns:
        修复的实体数量
    """
    fixed_count = 0
    
    # 遍历所有布局
    for layout in doc.layouts:
        for entity in layout:
            try:
                if hasattr(entity.dxf, 'layer'):
                    original_layer = entity.dxf.layer
                    cleaned_layer = clean_layer_name(original_layer)
                    
                    if original_layer != cleaned_layer:
                        print(f"修复{entity.dxftype()}实体图层: '{original_layer}' -> '{cleaned_layer}'")
                        entity.dxf.layer = cleaned_layer
                        fixed_count += 1
                        
            except Exception as e:
                print(f"修复{entity.dxftype()}实体时出错: {e}")
                # 尝试设置默认图层
                try:
                    if hasattr(entity.dxf, 'layer'):
                        entity.dxf.layer = "0"
                        fixed_count += 1
                except:
                    pass
    
    return fixed_count

def clean_dxf_file(input_path, output_path=None, backup=True):
    """
    清理DXF文件中的无效数据
    
    Args:
        input_path: 输入DXF文件路径
        output_path: 输出文件路径（如果为None，则覆盖原文件）
        backup: 是否创建备份文件
        
    Returns:
        (success, message): 成功标志和消息
    """
    input_path = Path(input_path)
    
    if not input_path.exists():
        return False, f"文件不存在: {input_path}"
    
    # 创建备份
    if backup:
        backup_path = input_path.with_suffix(input_path.suffix + '.backup')
        try:
            shutil.copy2(input_path, backup_path)
            print(f"已创建备份文件: {backup_path}")
        except Exception as e:
            print(f"创建备份失败: {e}")
    
    try:
        # 首先尝试文本级别的清理
        print(f"正在预处理文件: {input_path}")
        temp_path = input_path.with_suffix('.temp.dxf')
        
        # 读取文件内容并清理无效字符
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 清理无效的图层名称
        import re
        # 使用正则表达式直接替换包含无效字符的图层名称
        # 查找包含问号、特殊字符等无效字符的图层名称模式
        
        def clean_invalid_layers(text):
            # 模式1: 数字+问号的组合
            pattern1 = r'([0-9]+\?+[^\n\r]*?)'
            
            def replace_numeric_invalid(match):
                original = match.group(1)
                digit_match = re.match(r'(\d+)', original)
                if digit_match:
                    digit = digit_match.group(1)
                    if digit == '0':
                        return '0'
                    else:
                        return f'Layer_{digit}'
                return '0'
            
            text = re.sub(pattern1, replace_numeric_invalid, text)
            
            # 模式2: 包含问号和特殊字符的复杂图层名称
            pattern2 = r'([^\n\r]*\?+[^\n\r]*-[^\n\r]*?)'
            
            def replace_complex_invalid(match):
                original = match.group(1)
                # 尝试提取有意义的部分
                if 'NPT' in original:
                    return 'NPT_Layer'
                elif any(char.isdigit() for char in original):
                    # 提取第一个数字
                    digit_match = re.search(r'(\d+)', original)
                    if digit_match:
                        return f'Layer_{digit_match.group(1)}'
                return 'Unknown_Layer'
            
            text = re.sub(pattern2, replace_complex_invalid, text)
            
            # 模式3: 任何包含问号的字符串
            pattern3 = r'([^\n\r]*\?+[^\n\r]*?)'
            
            def replace_any_invalid(match):
                original = match.group(1)
                # 如果包含数字，使用数字
                digit_match = re.search(r'(\d+)', original)
                if digit_match:
                    digit = digit_match.group(1)
                    if digit == '0':
                        return '0'
                    else:
                        return f'Layer_{digit}'
                # 如果包含字母，尝试保留
                alpha_match = re.search(r'([A-Za-z]+)', original)
                if alpha_match:
                    return f'{alpha_match.group(1)}_Layer'
                return 'Default_Layer'
            
            text = re.sub(pattern3, replace_any_invalid, text)
            
            return text
        
        # 清理所有无效的图层名称
        original_content = content
        content = clean_invalid_layers(content)
        
        if content != original_content:
            print("已清理文件中的无效图层名称")
        
        # 写入临时文件
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 读取清理后的DXF文件
        print(f"正在读取清理后的文件: {temp_path}")
        doc = ezdxf.readfile(temp_path)
        
        # 修复SEQEND实体
        seqend_fixed = fix_seqend_entities(doc)
        
        # 修复所有实体的图层属性
        all_fixed = fix_all_entities(doc)
        
        # 删除临时文件
        if temp_path.exists():
            temp_path.unlink()
        
        # 确保默认图层存在
        if "0" not in doc.layers:
            doc.layers.add("0")
        
        # 保存文件
        output_file = output_path if output_path else input_path
        print(f"正在保存文件: {output_file}")
        doc.saveas(output_file)
        
        message = f"文件清理完成！修复了 {seqend_fixed} 个SEQEND实体，{all_fixed} 个实体的图层属性。"
        return True, message
        
    except ezdxf.DXFStructureError as e:
        return False, f"DXF文件结构错误: {e}"
    except ezdxf.lldxf.const.DXFValueError as e:
        return False, f"DXF文件包含无效数据: {e}"
    except Exception as e:
        return False, f"处理文件时发生错误: {e}"

def clean_directory(directory_path, pattern="*.dxf"):
    """
    清理目录中的所有DXF文件
    
    Args:
        directory_path: 目录路径
        pattern: 文件匹配模式
    """
    directory = Path(directory_path)
    
    if not directory.exists():
        print(f"目录不存在: {directory}")
        return
    
    # 查找所有DXF文件
    dxf_files = list(directory.glob(pattern)) + list(directory.glob(pattern.upper()))
    
    if not dxf_files:
        print(f"在目录 {directory} 中未找到DXF文件")
        return
    
    print(f"找到 {len(dxf_files)} 个DXF文件")
    
    success_count = 0
    for dxf_file in dxf_files:
        print(f"\n处理文件: {dxf_file.name}")
        success, message = clean_dxf_file(dxf_file)
        
        if success:
            success_count += 1
            print(f"✓ {message}")
        else:
            print(f"✗ {message}")
    
    print(f"\n处理完成！成功清理 {success_count}/{len(dxf_files)} 个文件")

def main():
    """
    主函数 - 命令行界面
    """
    import sys
    
    if len(sys.argv) > 1:
        # 命令行模式
        file_path = sys.argv[1]
        if Path(file_path).is_file():
            success, message = clean_dxf_file(file_path)
            print(message)
            sys.exit(0 if success else 1)
        elif Path(file_path).is_dir():
            clean_directory(file_path)
            sys.exit(0)
        else:
            print(f"文件或目录不存在: {file_path}")
            sys.exit(1)
    else:
        # 交互模式
        print("DXF文件清理工具")
        print("=" * 50)
        
        current_dir = Path(".")
        dxf_files = list(current_dir.glob("*.dxf")) + list(current_dir.glob("*.DXF"))
        
        if dxf_files:
            print(f"在当前目录找到 {len(dxf_files)} 个DXF文件:")
            for i, dxf_file in enumerate(dxf_files, 1):
                print(f"  {i}. {dxf_file.name}")
            
            choice = input("\n选择操作:\n1. 清理所有DXF文件\n2. 清理指定文件\n3. 退出\n请输入选择 (1-3): ")
            
            if choice == "1":
                clean_directory(current_dir)
            elif choice == "2":
                try:
                    file_num = int(input("请输入文件编号: ")) - 1
                    if 0 <= file_num < len(dxf_files):
                        success, message = clean_dxf_file(dxf_files[file_num])
                        print(message)
                    else:
                        print("无效的文件编号")
                except ValueError:
                    print("请输入有效的数字")
            elif choice == "3":
                print("退出程序")
            else:
                print("无效的选择")
        else:
            print("当前目录中未找到DXF文件")
            file_path = input("请输入DXF文件路径（或按回车退出）: ").strip()
            if file_path:
                success, message = clean_dxf_file(file_path)
                print(message)

if __name__ == "__main__":
    main()