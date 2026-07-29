import os
import pandas as pd
import ezdxf
from pathlib import Path
from collections import defaultdict

# 导入日志功能
try:
    from logger_config import get_logger
except ImportError:
    import logging
    def get_logger(name):
        return logging.getLogger(name)

# 初始化日志记录器
logger = get_logger("dxf_extractor")

def extract_text_from_dxf(file_path):
    """从DXF文件中提取文本 - 使用更全面的方法"""
    logger.info(f"开始从DXF文件提取文本: {file_path}")
    texts = set()  # 使用集合避免重复
    
    try:
        # 读取DXF文件
        logger.info(f"正在读取DXF文件: {file_path}")
        doc = ezdxf.readfile(file_path)
        logger.info(f"DXF文档版本: {doc.dxfversion}")
        print(f"DXF文档版本: {doc.dxfversion}")
        
        # 方法1: 检查所有空间（模型空间和图纸空间）
        logger.info("开始检查模型空间")
        print("\n=== 检查模型空间 ===")
        msp = doc.modelspace()
        model_texts = extract_texts_from_layout(msp, "模型空间")
        texts.update(model_texts)
        logger.info(f"从模型空间提取到 {len(model_texts)} 条文本")
        
        # 检查所有图纸空间
        logger.info("开始检查图纸空间")
        print("\n=== 检查图纸空间 ===")
        layout_count = 0
        for layout_name in doc.layout_names():
            if layout_name != 'Model':
                layout = doc.layouts.get(layout_name)
                if layout:
                    logger.info(f"检查图纸空间: {layout_name}")
                    print(f"检查图纸空间: {layout_name}")
                    layout_texts = extract_texts_from_layout(layout, layout_name)
                    texts.update(layout_texts)
                    logger.info(f"从图纸空间 {layout_name} 提取到 {len(layout_texts)} 条文本")
                    layout_count += 1
        logger.info(f"总共检查了 {layout_count} 个图纸空间")
        
        # 方法2: 检查所有块定义
        logger.info("开始检查所有块定义")
        print("\n=== 检查所有块定义 ===")
        block_count = 0
        for block in doc.blocks:
            logger.info(f"检查块: {block.name}")
            print(f"检查块: {block.name}")
            block_texts = extract_texts_from_layout(block, f"块-{block.name}")
            texts.update(block_texts)
            logger.info(f"从块 {block.name} 提取到 {len(block_texts)} 条文本")
            block_count += 1
        logger.info(f"总共检查了 {block_count} 个块定义")
        
        # 方法3: 使用底层DXF标签搜索
        logger.info("开始使用底层DXF标签搜索文本")
        print("\n=== 使用底层DXF标签搜索文本 ===")
        tag_texts = search_text_in_dxf_tags(doc)
        texts.update(tag_texts)
        logger.info(f"通过DXF标签搜索提取到 {len(tag_texts)} 条文本")
        
        # 方法4: 检查实体的扩展数据
        logger.info("开始检查实体的扩展数据")
        print("\n=== 检查扩展数据 ===")
        xdata_texts = extract_texts_from_xdata(doc)
        texts.update(xdata_texts)
        logger.info(f"从扩展数据提取到 {len(xdata_texts)} 条文本")
        
        # 方法5: 深度检查POLYLINE实体的所有属性
        if len(texts) == 0:
            logger.warning("前面的方法未提取到文本，开始深度检查POLYLINE实体")
            print("\n=== 深度检查POLYLINE实体属性 ===")
            polyline_texts = deep_analyze_polylines(doc)
            texts.update(polyline_texts)
            logger.info(f"深度检查POLYLINE实体提取到 {len(polyline_texts)} 条文本")
        
        # 过滤和清理文本
        logger.info("开始过滤和清理提取的文本")
        filtered_texts = []
        for text in texts:
            text = text.strip()
            # 过滤掉纯数字、单个字符、图层名等
            if (len(text) > 1 and 
                not text.isdigit() and 
                not text.startswith('Layer_') and
                not text.startswith('*') and
                text not in ['0', '1', 'CONTINUOUS', 'BYLAYER', 'BYBLOCK']):
                filtered_texts.append(text)
        
        logger.info(f"总共提取到 {len(texts)} 条原始文本")
        logger.info(f"过滤后剩余 {len(filtered_texts)} 条有效文本")
        print(f"\n总共提取到 {len(texts)} 条原始文本")
        print(f"过滤后剩余 {len(filtered_texts)} 条有效文本")
        
        return filtered_texts
    
    except IOError as e:
        logger.error(f"无法读取文件: {file_path} - {str(e)}")
        print(f"无法读取文件: {file_path}")
        return []
    except ezdxf.DXFStructureError as e:
        logger.error(f"无效或损坏的DXF文件: {file_path} - {str(e)}")
        print(f"无效或损坏的DXF文件: {file_path}")
        return []
    except ezdxf.lldxf.const.DXFValueError as e:
        logger.error(f"DXF文件包含无效数据: {file_path} - {str(e)}")
        print(f"DXF文件包含无效数据: {file_path} - {str(e)}")
        logger.info("正在尝试修复DXF文件...")
        print("正在尝试修复DXF文件...")
        
        # 尝试使用清理工具修复文件
        try:
            logger.info("尝试导入DXF清理工具")
            from dxf_cleaner import clean_dxf_file
            logger.info("开始修复DXF文件")
            success, message = clean_dxf_file(file_path, backup=True)
            
            if success:
                logger.info(f"文件修复成功: {message}")
                print(f"文件修复成功: {message}")
                logger.info("正在重新尝试读取修复后的文件")
                print("正在重新尝试读取文件...")
                
                # 重新尝试读取修复后的文件
                try:
                    doc = ezdxf.readfile(file_path)
                    logger.info("文件修复后读取成功！")
                    print("文件修复后读取成功！")
                    
                    # 重新执行文本提取逻辑
                    texts = set()  # 重新初始化文本集合
                    
                    # 方法1: 检查所有空间（模型空间和图纸空间）
                    logger.info("开始检查模型空间")
                    print("\n=== 检查模型空间 ===")
                    msp = doc.modelspace()
                    model_texts = extract_texts_from_layout(msp, "模型空间")
                    texts.update(model_texts)
                    logger.info(f"从模型空间提取到 {len(model_texts)} 条文本")
                    
                    # 检查所有图纸空间
                    logger.info("开始检查图纸空间")
                    print("\n=== 检查图纸空间 ===")
                    layout_count = 0
                    for layout_name in doc.layout_names():
                        if layout_name != 'Model':
                            layout = doc.layouts.get(layout_name)
                            if layout:
                                logger.info(f"检查图纸空间: {layout_name}")
                                print(f"检查图纸空间: {layout_name}")
                                layout_texts = extract_texts_from_layout(layout, layout_name)
                                texts.update(layout_texts)
                                logger.info(f"从图纸空间 {layout_name} 提取到 {len(layout_texts)} 条文本")
                                layout_count += 1
                    logger.info(f"总共检查了 {layout_count} 个图纸空间")
                    
                    # 方法2: 检查所有块定义
                    logger.info("开始检查所有块定义")
                    print("\n=== 检查所有块定义 ===")
                    block_count = 0
                    for block in doc.blocks:
                        logger.info(f"检查块: {block.name}")
                        print(f"检查块: {block.name}")
                        block_texts = extract_texts_from_layout(block, f"块-{block.name}")
                        texts.update(block_texts)
                        logger.info(f"从块 {block.name} 提取到 {len(block_texts)} 条文本")
                        block_count += 1
                    logger.info(f"总共检查了 {block_count} 个块定义")
                    
                    # 方法3: 使用底层DXF标签搜索
                    logger.info("开始使用底层DXF标签搜索文本")
                    print("\n=== 使用底层DXF标签搜索文本 ===")
                    tag_texts = search_text_in_dxf_tags(doc)
                    texts.update(tag_texts)
                    logger.info(f"通过DXF标签搜索提取到 {len(tag_texts)} 条文本")
                    
                    # 方法4: 检查实体的扩展数据
                    logger.info("开始检查实体的扩展数据")
                    print("\n=== 检查扩展数据 ===")
                    xdata_texts = extract_texts_from_xdata(doc)
                    texts.update(xdata_texts)
                    logger.info(f"从扩展数据提取到 {len(xdata_texts)} 条文本")
                    
                    # 方法5: 深度检查POLYLINE实体的所有属性
                    if len(texts) == 0:
                        logger.warning("前面的方法未提取到文本，开始深度检查POLYLINE实体")
                        print("\n=== 深度检查POLYLINE实体属性 ===")
                        polyline_texts = deep_analyze_polylines(doc)
                        texts.update(polyline_texts)
                        logger.info(f"深度检查POLYLINE实体提取到 {len(polyline_texts)} 条文本")
                    
                    # 过滤和清理文本
                    logger.info("开始过滤和清理提取的文本")
                    filtered_texts = []
                    for text in texts:
                        text = text.strip()
                        # 过滤掉纯数字、单个字符、图层名等
                        if (len(text) > 1 and 
                            not text.isdigit() and 
                            not text.startswith('Layer_') and
                            not text.startswith('*') and
                            text not in ['0', '1', 'CONTINUOUS', 'BYLAYER', 'BYBLOCK']):
                            filtered_texts.append(text)
                    
                    logger.info(f"总共提取到 {len(texts)} 条原始文本")
                    logger.info(f"过滤后剩余 {len(filtered_texts)} 条有效文本")
                    print(f"\n总共提取到 {len(texts)} 条原始文本")
                    print(f"过滤后剩余 {len(filtered_texts)} 条有效文本")
                    
                    return filtered_texts
                    
                except Exception as retry_e:
                    logger.error(f"修复后仍无法读取文件: {retry_e}")
                    print(f"修复后仍无法读取文件: {retry_e}")
                    return []
            else:
                logger.error(f"文件修复失败: {message}")
                print(f"文件修复失败: {message}")
                return []
                
        except ImportError as ie:
            logger.error(f"无法导入DXF清理工具: {str(ie)}")
            print("无法导入DXF清理工具，请确保dxf_cleaner.py文件存在")
            return []
        except Exception as clean_e:
            logger.error(f"修复文件时发生错误: {clean_e}")
            print(f"修复文件时发生错误: {clean_e}")
            return []
    except Exception as e:
        logger.error(f"处理DXF文件时发生未知错误: {file_path} - {str(e)}")
        print(f"处理DXF文件时发生未知错误: {file_path} - {str(e)}")
        return []

def extract_texts_from_layout(layout, layout_name):
    """从布局中提取文本"""
    texts = set()
    entity_count = len(layout)
    print(f"  {layout_name} 包含 {entity_count} 个实体")
    
    # 统计实体类型
    entity_types = {}
    for entity in layout:
        entity_type = entity.dxftype()
        entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
    print(f"  实体类型: {entity_types}")
    
    # 提取所有类型的文本实体
    text_types = ['TEXT', 'MTEXT', 'ATTDEF', 'ATTRIB']
    for text_type in text_types:
        entities = layout.query(text_type)
        print(f"  找到 {len(entities)} 个 {text_type} 实体")
        for entity in entities:
            text_content = extract_text_from_entity(entity)
            if text_content:
                texts.add(text_content)
                print(f"    提取: {text_content}")
    
    # 检查INSERT实体（块引用）中的属性
    inserts = layout.query('INSERT')
    print(f"  找到 {len(inserts)} 个 INSERT 实体")
    for insert in inserts:
        if hasattr(insert, 'attribs'):
            for attrib in insert.attribs:
                text_content = extract_text_from_entity(attrib)
                if text_content:
                    texts.add(text_content)
                    print(f"    从INSERT属性提取: {text_content}")
    
    return texts


def deep_analyze_polylines(doc):
    """深度分析POLYLINE实体，寻找可能的文本信息"""
    texts = set()
    
    try:
        msp = doc.modelspace()
        polylines = list(msp.query('POLYLINE'))
        print(f"  分析 {len(polylines)} 个POLYLINE实体")
        
        # 检查前20个POLYLINE实体的详细信息
        for i, polyline in enumerate(polylines[:20]):
            print(f"\n  POLYLINE #{i+1}:")
            
            # 检查所有DXF属性
            try:
                all_attrs = polyline.dxf.all_existing_dxf_attribs()
                print(f"    DXF属性: {all_attrs}")
                
                for attr_name in all_attrs:
                    try:
                        attr_value = getattr(polyline.dxf, attr_name)
                        print(f"    {attr_name}: {attr_value} (类型: {type(attr_value)})")
                        
                        # 检查字符串类型的属性
                        if isinstance(attr_value, str) and len(attr_value.strip()) > 0:
                            clean_value = attr_value.strip()
                            if (len(clean_value) > 1 and 
                                not clean_value.isdigit() and 
                                clean_value not in ['0', '1', 'CONTINUOUS', 'BYLAYER']):
                                texts.add(clean_value)
                                print(f"      -> 提取文本: {clean_value}")
                    except Exception as e:
                        print(f"    获取属性 {attr_name} 时出错: {e}")
            except Exception as e:
                print(f"    获取DXF属性时出错: {e}")
            
            # 检查顶点信息
            try:
                if hasattr(polyline, 'vertices'):
                    vertices = polyline.vertices
                    if callable(vertices):
                        vertices = list(vertices())
                    print(f"    顶点数量: {len(vertices)}")
                    
                    # 检查前3个顶点
                    for j, vertex in enumerate(vertices[:3]):
                        print(f"    顶点 #{j+1}:")
                        try:
                            if hasattr(vertex, 'dxf'):
                                vertex_attrs = vertex.dxf.all_existing_dxf_attribs()
                                for attr_name in vertex_attrs:
                                    try:
                                        attr_value = getattr(vertex.dxf, attr_name)
                                        if isinstance(attr_value, str) and len(attr_value.strip()) > 0:
                                            clean_value = attr_value.strip()
                                            if (len(clean_value) > 1 and 
                                                not clean_value.isdigit() and 
                                                clean_value not in ['0', '1']):
                                                texts.add(clean_value)
                                                print(f"        -> 从顶点提取文本: {clean_value}")
                                    except:
                                        pass
                        except Exception as e:
                            print(f"      检查顶点属性时出错: {e}")
            except Exception as e:
                print(f"    检查顶点时出错: {e}")
            
            # 检查实体的原始DXF标签
            try:
                if hasattr(polyline, 'tags'):
                    print(f"    检查原始DXF标签...")
                    for tag in polyline.tags:
                        if isinstance(tag.value, str) and len(tag.value.strip()) > 0:
                            clean_value = tag.value.strip()
                            if (len(clean_value) > 1 and 
                                not clean_value.isdigit() and 
                                clean_value not in ['0', '1', 'POLYLINE', 'CONTINUOUS']):
                                texts.add(clean_value)
                                print(f"      -> 从标签 {tag.code} 提取文本: {clean_value}")
            except Exception as e:
                print(f"    检查DXF标签时出错: {e}")
            
            if i >= 4:  # 只详细检查前5个，避免输出过多
                print(f"  ... (还有 {len(polylines) - 5} 个POLYLINE实体未详细显示)")
                break
        
        # 如果还是没找到文本，尝试检查文档的其他部分
        if len(texts) == 0:
            print("\n  尝试检查文档头部和其他部分...")
            try:
                # 检查文档头部信息
                if hasattr(doc, 'header'):
                    print(f"    文档头部变量数量: {len(doc.header)}")
                    for var_name, var_value in doc.header.items():
                        if isinstance(var_value, str) and len(var_value.strip()) > 2:
                            clean_value = var_value.strip()
                            if not clean_value.isdigit():
                                texts.add(clean_value)
                                print(f"      -> 从头部变量 {var_name} 提取: {clean_value}")
            except Exception as e:
                print(f"    检查文档头部时出错: {e}")
    
    except Exception as e:
        print(f"  深度分析时出错: {e}")
    
    return texts


def extract_text_from_entity(entity):
    """从单个实体中提取文本"""
    try:
        if hasattr(entity, 'dxf'):
            # 检查text属性
            if hasattr(entity.dxf, 'text'):
                return entity.dxf.text.strip()
            # 检查tag属性（用于ATTDEF）
            elif hasattr(entity.dxf, 'tag'):
                return entity.dxf.tag.strip()
            # 检查prompt属性（用于ATTDEF）
            elif hasattr(entity.dxf, 'prompt'):
                return entity.dxf.prompt.strip()
    except:
        pass
    return None


def search_text_in_dxf_tags(doc):
    """在DXF标签中搜索文本"""
    texts = set()
    
    try:
        # 遍历DXF文档的所有标签
        for section_name in ['ENTITIES', 'BLOCKS']:
            if hasattr(doc, 'entitydb'):
                for handle, entity in doc.entitydb.items():
                    try:
                        # 检查实体的DXF标签
                        if hasattr(entity, 'tags'):
                            for tag in entity.tags:
                                if tag.code in [1, 3, 7, 8]:  # 常见的文本相关标签代码
                                    if isinstance(tag.value, str) and len(tag.value.strip()) > 0:
                                        texts.add(tag.value.strip())
                                        print(f"  从标签 {tag.code} 提取: {tag.value.strip()}")
                    except:
                        continue
    except Exception as e:
        print(f"  搜索DXF标签时出错: {e}")
    
    return texts


def extract_texts_from_xdata(doc):
    """从扩展数据中提取文本"""
    texts = set()
    
    try:
        # 检查所有实体的扩展数据
        for layout_name in ['Model'] + list(doc.layout_names()):
            if layout_name == 'Model':
                layout = doc.modelspace()
            else:
                layout = doc.layouts.get(layout_name)
                if not layout:
                    continue
            
            for entity in layout:
                try:
                    if hasattr(entity, 'get_xdata'):
                        xdata = entity.get_xdata()
                        if xdata:
                            for app_name, data in xdata.items():
                                for item in data:
                                    if isinstance(item, tuple) and len(item) >= 2:
                                        if isinstance(item[1], str) and len(item[1].strip()) > 0:
                                            texts.add(item[1].strip())
                                            print(f"  从扩展数据提取: {item[1].strip()}")
                except:
                    continue
    except Exception as e:
        print(f"  提取扩展数据时出错: {e}")
    
    return texts

def process_directory(directory):
    """处理目录，提取所有DXF文件中的唯一文本。"""
    logger.info(f"开始处理目录: {directory}")
    all_unique_texts = set()
    file_count = 0
    
    for root, dirs, files in os.walk(directory):
        for name in files:
            # 使用 .lower() 兼容 .DXF 和 .dxf
            if name.lower().endswith('.dxf'):
                file_path = Path(root) / name
                file_count += 1
                logger.info(f"正在处理第 {file_count} 个文件: {file_path}")
                print(f"正在处理: {file_path}")
                texts = extract_text_from_dxf(file_path)
                all_unique_texts.update(texts) # 使用set.update来自动处理重复项
                logger.info(f"文件 {file_path} 处理完成，提取到 {len(texts)} 条文本")

    logger.info(f"目录处理完成，共处理 {file_count} 个DXF文件，提取到 {len(all_unique_texts)} 条唯一文本")
    return sorted(list(all_unique_texts))

def main():
    import sys
    
    logger.info("DXF文本提取程序启动")
    
    # 检查是否提供了命令行参数
    if len(sys.argv) > 1:
        # 如果提供了参数，处理指定的文件或目录
        target_path = Path(sys.argv[1])
        logger.info(f"使用命令行参数指定的路径: {target_path}")
        
        if target_path.is_file() and target_path.suffix.lower() == '.dxf':
            # 处理单个DXF文件
            logger.info(f"开始处理单个DXF文件: {target_path}")
            print(f"正在处理单个文件: {target_path}")
            texts = extract_text_from_dxf(target_path)
            unique_texts = sorted(list(set(texts)))
            logger.info(f"单个文件处理完成，提取到 {len(unique_texts)} 条唯一文本")
        elif target_path.is_dir():
            # 处理目录
            logger.info(f"开始处理目录: {target_path}")
            print(f"正在处理目录: {target_path}")
            unique_texts = process_directory(target_path)
        else:
            logger.error(f"无效的路径: '{target_path}' 不是有效的DXF文件或目录")
            print(f"错误: '{target_path}' 不是有效的DXF文件或目录")
            return
    else:
        # 默认处理当前目录
        directory = Path('.')  # 当前目录
        logger.info(f"使用默认目录: {directory.absolute()}")
        unique_texts = process_directory(directory)

    if not unique_texts:
        logger.warning("没有找到任何文本")
        print("没有找到任何文本。")
        return

    # 将提取的唯一文本保存到Excel文件中
    logger.info("开始创建Excel文件")
    # 创建两列，第二列留空用于填写翻译
    df = pd.DataFrame({
        'Source Text': unique_texts,
        'Translated Text': [''] * len(unique_texts)
    })
    
    output_filename = 'extracted_texts_for_translation.xlsx'
    logger.info(f"正在保存Excel文件: {output_filename}")
    try:
        df.to_excel(output_filename, index=False)
        logger.info(f"Excel文件保存成功: {output_filename}")
        logger.info(f"处理完成！共提取到 {len(unique_texts)} 条不重复的文本")
        print("\n处理完成！")
        print(f"所有唯一的文本已提取并保存到 '{output_filename}'。")
        print(f"共提取到 {len(unique_texts)} 条不重复的文本。")
    except Exception as e:
        logger.error(f"保存Excel文件失败: {str(e)}")
        print(f"保存Excel文件时发生错误: {str(e)}")

if __name__ == "__main__":
    main()