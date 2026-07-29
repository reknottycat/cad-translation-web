import os
import pandas as pd
import ezdxf
import re
from pathlib import Path
from datetime import datetime
from logger_config import get_logger

# 初始化日志记录器
logger = get_logger("dxf_backfill")

def smart_translate(text, translation_map):
    """
    智能翻译函数，支持多种空格处理策略
    
    Args:
        text: 要翻译的文本
        translation_map: 翻译映射表
    
    Returns:
        tuple: (翻译结果, 使用的方法) 或 (None, 原因) 表示跳过
    """
    if not text or not isinstance(text, str):
        return None, '无效文本'
    
    # 首先尝试直接匹配
    if text in translation_map:
        translated = translation_map[text]
        # 检查翻译是否为空
        if not translated or not translated.strip():
            return None, '翻译为空'
        return translated, '直接匹配'
    
    # 定义标准化方法
    normalization_methods = [
        ('移除空格', lambda x: re.sub(r'\s+', '', x)),
        ('单空格', lambda x: re.sub(r'\s+', ' ', x.strip())),
        ('去首尾空格', lambda x: x.strip())
    ]
    
    # 尝试各种标准化方法
    for method_name, method_func in normalization_methods:
        normalized_text = method_func(text)
        
        # 在翻译映射表中查找标准化后的文本
        for original, translated in translation_map.items():
            if method_func(original) == normalized_text:
                # 检查翻译是否为空
                if not translated or not translated.strip():
                    return None, '翻译为空'
                logger.debug(f"智能翻译匹配: '{text}' -> '{translated}' (通过{method_name}匹配'{original}')")
                return translated, f'{method_name}匹配({original})'
    
    return None, '未找到匹配'

def load_translation_map(excel_path):
    """从Excel加载翻译映射表"""
    logger.info(f"开始加载翻译映射表: {excel_path}")
    try:
        df = pd.read_excel(excel_path)
        logger.info(f"Excel文件读取成功，共 {len(df)} 行数据")
        
        # 创建翻译映射，过滤掉空翻译
        translation_map = {}
        for _, row in df.iterrows():
            # 智能检测列索引，支持不同的Excel格式
            if len(row) >= 3:
                # 3列格式：可能是序号、原文、译文
                original = str(row.iloc[1]).strip()  # 原文（第2列）
                translated = row.iloc[2]  # 译文（第3列）
            elif len(row) >= 2:
                # 2列格式：原文、译文
                original = str(row.iloc[0]).strip()  # 原文（第1列）
                translated = row.iloc[1]  # 译文（第2列）
            else:
                logger.warning(f"跳过格式不正确的行: {row.values}")
                continue
            
            # 检查翻译是否有效（不为空、不为NaN、不为None等无效值）
            if pd.notna(translated):
                translated_str = str(translated).strip()
                # 检查是否为有效翻译（不为空且不是常见的无效值）
                invalid_values = ['', 'nan', 'none', 'null', 'n/a', 'na']
                if translated_str and translated_str.lower() not in invalid_values:
                    translation_map[original] = translated_str
                else:
                    logger.debug(f"跳过无效翻译: '{original}' -> '{translated}'")
            else:
                logger.debug(f"跳过空翻译: '{original}' -> '{translated}'")
        
        logger.info(f"翻译映射表加载成功，共 {len(translation_map)} 条有效翻译映射")
        return translation_map
    except FileNotFoundError:
        logger.error(f"翻译文件 '{excel_path}' 未找到")
        print(f"错误：翻译文件 '{excel_path}' 未找到。")
        return {}
    except Exception as e:
        logger.error(f"读取Excel文件时出错: {str(e)}")
        print(f"读取Excel文件时出错: {e}")
        return {}

def translate_text_entity(owner, entity, translation_map, font_name="Times New Roman", replace_mode=False, font_size_reduction=4):
    """
    翻译单个文本实体 (TEXT, MTEXT, ATTDEF, ATTRIB)。
    owner: 实体所在的容器 (模型空间 msp 或 块定义 block)。
    entity: 要翻译的文本实体。
    translation_map: 翻译字典。
    font_name: 翻译文本使用的字体名称，默认为Times New Roman。
    replace_mode: 是否替换原文本（True）还是在下方添加翻译（False）。
    font_size_reduction: 字体大小减少量，默认减少4个单位。
    """
    try:
        # 统一文本提取方式，支持更多实体类型
        original_text = None
        entity_type = entity.dxftype()
        
        if entity_type == 'TEXT':
            original_text = entity.dxf.text
        elif entity_type == 'MTEXT':
            # 统一MTEXT读取方式，优先使用dxf.text确保兼容性
            try:
                original_text = entity.dxf.text
            except (AttributeError, KeyError):
                # 备用方案：使用entity.text
                original_text = entity.text
        elif entity_type in ['ATTDEF', 'ATTRIB']:
            # 支持属性定义和属性值实体
            if hasattr(entity.dxf, 'text'):
                original_text = entity.dxf.text
            elif hasattr(entity.dxf, 'tag'):
                original_text = entity.dxf.tag
            elif hasattr(entity.dxf, 'prompt'):
                original_text = entity.dxf.prompt
        else:
            logger.debug(f"不支持的实体类型: {entity_type}")
            return
            
        # 检查是否成功提取到文本
        if not original_text:
            logger.debug(f"无法从{entity_type}实体提取文本")
            return
            
    except Exception as e:
        logger.error(f"提取文本时出错: {str(e)}")
        return

    logger.debug(f"处理文本实体: '{original_text}'")
    
    # 使用智能翻译功能
    translated_text, match_method = smart_translate(original_text.strip(), translation_map)
    
    # 检查翻译是否有效（None表示跳过）
    if translated_text is None:
        logger.debug(f"跳过翻译: '{original_text}' (原因: {match_method})")
        return
    
    # 记录翻译成功信息
    if match_method != '直接匹配':
        logger.info(f"智能翻译成功: '{original_text}' -> '{translated_text}' ({match_method})")
    
    logger.debug(f"找到有效翻译: '{original_text}' -> '{translated_text}'")

    # 获取原文本高度（添加错误处理）
    try:
        if entity_type == 'MTEXT':
            height = entity.dxf.char_height
        elif entity_type in ['TEXT', 'ATTDEF', 'ATTRIB']:
            height = entity.dxf.height if hasattr(entity.dxf, 'height') else 2.5  # 默认高度
        else:
            height = 2.5  # 默认高度
    except (AttributeError, KeyError):
        height = 2.5  # 默认高度
        logger.debug(f"无法获取{entity_type}实体高度，使用默认值")
    
    if replace_mode:
        # 替换模式：直接修改原文本
        try:
            if entity_type == 'TEXT':
                entity.dxf.text = translated_text
                # 调整字体大小
                if hasattr(entity.dxf, 'height'):
                    entity.dxf.height = max(1, height - font_size_reduction)
            elif entity_type == 'MTEXT':
                # 统一MTEXT文本设置方式
                try:
                    entity.dxf.text = translated_text
                except (AttributeError, KeyError):
                    entity.text = translated_text
                # 调整字体大小
                if hasattr(entity.dxf, 'char_height'):
                    entity.dxf.char_height = max(1, height - font_size_reduction)
            elif entity_type in ['ATTDEF', 'ATTRIB']:
                # 处理属性实体
                if hasattr(entity.dxf, 'text'):
                    entity.dxf.text = translated_text
                elif hasattr(entity.dxf, 'tag'):
                    entity.dxf.tag = translated_text
                # 调整字体大小
                if hasattr(entity.dxf, 'height'):
                    entity.dxf.height = max(1, height - font_size_reduction)
            
            # 尝试设置字体样式
            try:
                doc = owner.doc if hasattr(owner, 'doc') else owner.drawing
                style_name = f"TranslationStyle_{font_name.replace(' ', '_')}"
                
                if style_name not in doc.styles:
                    style = doc.styles.add(style_name, font=font_name)
                    style.dxf.bigfont = ""
                
                entity.dxf.style = style_name
            except Exception as e:
                print(f"警告：无法设置字体样式 {font_name}: {e}")
                
        except Exception as e:
            logger.error(f"替换文本失败: {str(e)}")
            print(f"警告：替换文本失败: {e}")
        return
    
    # 添加模式：在原文本下方添加翻译
    try:
        offset_y = -height * 1.2  # 向下偏移

        # 根据实体类型获取插入点和其他属性
        insert_point = None
        layer = None
        rotation = 0
        
        try:
            if entity_type in ['TEXT', 'MTEXT']:
                insert_point = entity.dxf.insert
            elif entity_type in ['ATTDEF', 'ATTRIB']:
                # 属性实体可能使用不同的位置属性
                if hasattr(entity.dxf, 'insert'):
                    insert_point = entity.dxf.insert
                elif hasattr(entity.dxf, 'align_point'):
                    insert_point = entity.dxf.align_point
                else:
                    # 使用默认位置
                    insert_point = (0, 0, 0)
                    
            # 获取图层信息
            layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else '0'
            
            # 获取旋转角度
            rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0
            
        except (AttributeError, KeyError) as e:
            logger.debug(f"获取{entity_type}实体属性时出错: {str(e)}，使用默认值")
            insert_point = (0, 0, 0)
            layer = '0'
            rotation = 0

        # 继承原始属性并设置字体
        attribs = {
            'text': translated_text,
            'insert': insert_point,
            'char_height': max(1, height - font_size_reduction),  # 减少指定的字体大小
            'layer': layer,
            'rotation': rotation,
            'color': 1  # 红色以示区别
        }
        
    except Exception as e:
        logger.error(f"准备添加翻译文本时出错: {str(e)}")
        return
    
    # 创建或获取字体样式
    try:
        # 尝试创建新的文本样式
        doc = owner.doc if hasattr(owner, 'doc') else owner.drawing
        style_name = f"TranslationStyle_{font_name.replace(' ', '_')}"
        
        # 检查样式是否已存在
        if style_name not in doc.styles:
            # 使用正确的ezdxf API创建文本样式
            style = doc.styles.add(style_name, font=font_name)
            # 可选：设置其他样式属性
            style.dxf.bigfont = ""  # 清空大字体
        
        attribs['style'] = style_name
    except Exception as e:
        # 如果创建样式失败，使用默认样式
        logger.warning(f"无法创建字体样式 {font_name}，使用默认样式: {str(e)}")
        print(f"警告：无法创建字体样式 {font_name}，使用默认样式: {e}")
        try:
            attribs['style'] = entity.dxf.style if hasattr(entity.dxf, 'style') else 'Standard'
        except (AttributeError, KeyError):
            attribs['style'] = 'Standard'
    
    # 根据旋转角度调整偏移量，以确保始终在视觉上的"下方"
    try:
        import math
        rotation_rad = rotation * (math.pi / 180.0)
        dx = offset_y * math.sin(rotation_rad)
        dy = offset_y * math.cos(rotation_rad)
        
        # 计算新的插入点
        new_x = insert_point[0] + dx
        new_y = insert_point[1] + dy
        new_z = insert_point[2] if len(insert_point) > 2 else 0
        
        attribs['insert'] = (new_x, new_y, new_z)
        
    except Exception as e:
        logger.error(f"计算偏移位置时出错: {str(e)}")
        # 使用简单的向下偏移作为备选方案
        attribs['insert'] = (insert_point[0], insert_point[1] + offset_y, insert_point[2] if len(insert_point) > 2 else 0)

    # 在正确的容器（owner）中添加新文本
    try:
        # 统一使用MTEXT添加翻译文本，因为它支持更好的格式化
        owner.add_mtext(translated_text, dxfattribs=attribs)
        logger.debug(f"成功添加翻译文本: '{translated_text}'")
    except Exception as e:
        logger.error(f"添加翻译文本失败: {str(e)}")
        # 尝试使用TEXT作为备选方案
        try:
            # 移除MTEXT特有的属性
            text_attribs = attribs.copy()
            if 'char_height' in text_attribs:
                text_attribs['height'] = text_attribs.pop('char_height')
            owner.add_text(translated_text, dxfattribs=text_attribs)
            logger.debug(f"使用TEXT备选方案成功添加翻译文本: '{translated_text}'")
        except Exception as e2:
            logger.error(f"TEXT备选方案也失败: {str(e2)}")
            print(f"警告：无法添加翻译文本: {translated_text}")

def translate_dwg(dwg_path, translation_map, font_name="Times New Roman", replace_mode=False, font_size_reduction=4):
    """翻译整个DWG/DXF文件"""
    logger.info(f"开始翻译DWG/DXF文件: {dwg_path}")
    logger.info(f"翻译设置 - 字体: {font_name}, 替换模式: {replace_mode}, 字体大小减少: {font_size_reduction}")
    
    try:
        doc = ezdxf.readfile(dwg_path)
        logger.info(f"DXF文件读取成功: {dwg_path}")
    except IOError:
        logger.error(f"无法读取文件: {dwg_path}")
        print(f"无法读取文件: {dwg_path}")
        return None
    except ezdxf.DXFStructureError:
        logger.error(f"DXF文件结构错误: {dwg_path}")
        print(f"DXF文件结构错误: {dwg_path}")
        return None
    except ezdxf.lldxf.const.DXFValueError as e:
        logger.error(f"DXF文件包含无效数据: {dwg_path} - {str(e)}")
        print(f"DXF文件包含无效数据: {dwg_path} - {str(e)}")
        logger.info("正在尝试修复DXF文件...")
        print("正在尝试修复DXF文件...")
        
        # 尝试使用清理工具修复文件
        try:
            from dxf_cleaner import clean_dxf_file
            success, message = clean_dxf_file(dwg_path, backup=True)
            
            if success:
                logger.info(f"文件修复成功: {message}")
                print(f"文件修复成功: {message}")
                logger.info("正在重新尝试读取文件...")
                print("正在重新尝试读取文件...")
                
                # 重新尝试读取修复后的文件
                try:
                    doc = ezdxf.readfile(dwg_path)
                    logger.info("文件修复后读取成功！")
                    print("文件修复后读取成功！")
                except Exception as retry_e:
                    logger.error(f"修复后仍无法读取文件: {retry_e}")
                    print(f"修复后仍无法读取文件: {retry_e}")
                    return None
            else:
                logger.error(f"文件修复失败: {message}")
                print(f"文件修复失败: {message}")
                return None
                
        except ImportError:
            logger.error("无法导入DXF清理工具，请确保dxf_cleaner.py文件存在")
            print("无法导入DXF清理工具，请确保dxf_cleaner.py文件存在")
            return None
        except Exception as clean_e:
            logger.error(f"修复文件时发生错误: {clean_e}")
            print(f"修复文件时发生错误: {clean_e}")
            return None
    except Exception as e:
        logger.error(f"处理DXF文件时发生未知错误: {dwg_path} - {str(e)}")
        print(f"处理DXF文件时发生未知错误: {dwg_path} - {str(e)}")
        return None

    msp = doc.modelspace()
    logger.info("开始翻译模型空间中的文本")

    # 翻译模型空间中的文本
    text_entities = list(msp.query('TEXT MTEXT'))
    logger.info(f"模型空间中找到 {len(text_entities)} 个文本实体")
    
    translated_count = 0
    for entity in text_entities:
        original_count = translated_count
        translate_text_entity(msp, entity, translation_map, font_name, replace_mode, font_size_reduction)
        # 简单检查是否进行了翻译（根据实体类型使用正确的属性）
        if entity.dxftype() == 'TEXT':
            original_text = entity.dxf.text
        elif entity.dxftype() == 'MTEXT':
            original_text = entity.text
        else:
            continue
            
        if original_text.strip() in translation_map:
            translated_count += 1
    
    logger.info(f"模型空间翻译完成，共翻译 {translated_count} 个文本实体")

    # 3. 修复块内文本的翻译
    logger.info("开始翻译块定义中的文本")
    block_count = 0
    block_text_count = 0
    
    # 遍历块定义 (Block Definitions)
    for block in doc.blocks:
        # 不处理模型空间和图纸空间这些特殊的块
        # 使用正确的ezdxf 1.4.2 API
        if not block.block.is_layout_block:
            block_count += 1
            block_texts = list(block.query('TEXT MTEXT'))
            block_text_count += len(block_texts)
            
            if block_texts:
                logger.debug(f"块 '{block.name}' 中找到 {len(block_texts)} 个文本实体")
            
            for entity in block_texts:
                # 将 block 作为 owner 传入
                translate_text_entity(block, entity, translation_map, font_name, replace_mode, font_size_reduction)
    
    logger.info(f"块定义翻译完成，共检查 {block_count} 个块，包含 {block_text_count} 个文本实体")
    logger.info(f"DXF文件翻译完成: {dwg_path}")
    return doc

def process_directory(directory, translation_map, output_folder, font_name="Times New Roman", replace_mode=False, font_size_reduction=4):
    """处理指定目录下的所有DXF文件"""
    logger.info(f"开始处理目录: {directory}")
    logger.info(f"输出目录: {output_folder}")
    
    processed_count = 0
    success_count = 0
    
    for root, dirs, files in os.walk(directory):
        # 避免进入输出文件夹
        if output_folder.name in dirs:
            dirs.remove(output_folder.name)
            logger.debug(f"跳过输出目录: {output_folder.name}")

        for name in files:
            if name.lower().endswith('.dxf'):
                file_path = Path(root) / name
                relative_path = file_path.relative_to(directory)
                # 在文件名前添加 'trans_DXF_' 前缀和时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name_without_ext = relative_path.stem
                ext = relative_path.suffix
                new_filename = f"trans_DXF_{timestamp}_{name_without_ext}{ext}"
                output_path = output_folder / relative_path.parent / new_filename
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                processed_count += 1
                logger.info(f"正在处理第 {processed_count} 个文件: {file_path}")
                print(f"正在处理: {file_path}")
                
                doc = translate_dwg(file_path, translation_map, font_name, replace_mode, font_size_reduction)
                if doc:
                    try:
                        doc.saveas(output_path)
                        success_count += 1
                        logger.info(f"文件保存成功: {output_path}")
                        print(f"已保存到: {output_path}")
                    except Exception as e:
                        logger.error(f"保存文件失败 {output_path}: {str(e)}")
                        print(f"保存文件失败 {output_path}: {e}")
                else:
                    logger.warning(f"文件翻译失败，跳过保存: {file_path}")
    
    logger.info(f"目录处理完成，共处理 {processed_count} 个DXF文件，成功 {success_count} 个")

def main():
    import argparse
    
    # 添加命令行参数解析
    parser = argparse.ArgumentParser(description='DXF文本回填程序')
    parser.add_argument('--font', default='Times New Roman', help='字体名称')
    parser.add_argument('--mode', choices=['replace', 'add'], default='replace', help='翻译模式：replace(替换原文) 或 add(在下方添加翻译)')
    parser.add_argument('--font-size-reduction', type=int, default=4, help='字体大小减少的数值')
    
    args = parser.parse_args()
    
    logger.info("DXF文本回填程序启动")
    
    # 字体设置 - 支持命令行参数
    available_fonts = [
        "Times New Roman",
        "Arial",
        "SimSun",  # 宋体
        "SimHei",  # 黑体
        "Microsoft YaHei",  # 微软雅黑
        "Calibri",
        "Verdana"
    ]
    
    font_name = args.font  # 从命令行参数获取字体
    
    # 翻译模式设置 - 支持命令行参数
    replace_mode = (args.mode == 'replace')  # True: 替换原文, False: 在下方添加翻译
    font_size_reduction = args.font_size_reduction  # 从命令行参数获取字体大小减少值
    
    logger.info(f"程序配置 - 字体: {font_name}, 替换模式: {replace_mode}, 字体大小减少: {font_size_reduction}")
    
    print(f"当前使用字体: {font_name}")
    print(f"可用字体选项: {', '.join(available_fonts)}")
    print("提示: 如需更改字体，请修改代码中的 font_name 变量")
    print("-" * 50)
    print(f"翻译模式: {'替换原文' if replace_mode else '在下方添加翻译'}")
    if replace_mode:
        print(f"字体大小调整: 比原文小 {font_size_reduction} 号")
    print("提示: 如需更改翻译模式，请修改代码中的 replace_mode 变量")
    print("-" * 50)
    
    # 使用标准翻译文件名
    translation_files = ['extracted_texts.xlsx']
    translation_map = None
    
    logger.info(f"开始查找翻译文件，候选文件: {translation_files}")
    
    for filename in translation_files:
        if Path(filename).exists():
            logger.info(f"找到翻译文件: {filename}")
            print(f"找到翻译文件: {filename}")
            translation_map = load_translation_map(filename)
            if translation_map:
                logger.info(f"翻译文件加载成功: {filename}")
                break
    
    if not translation_map:
        logger.error("翻译映射表为空或加载失败")
        print("翻译映射表为空或加载失败。")
        print("请确保以下文件之一存在并包含翻译数据:")
        for filename in translation_files:
            print(f"  - {filename}")
        return
        
    source_folder = Path('.')  # 当前目录
    output_folder = Path('translated_drawings')
    output_folder.mkdir(exist_ok=True)
    
    logger.info(f"开始处理，源目录: {source_folder.absolute()}, 输出目录: {output_folder.absolute()}")
    
    process_directory(source_folder, translation_map, output_folder, font_name, replace_mode, font_size_reduction)
    
    logger.info("DXF文本回填程序处理完成")
    print("处理完成！")

if __name__ == "__main__":
    main()