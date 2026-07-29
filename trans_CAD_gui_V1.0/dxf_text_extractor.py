#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DXF文本提取引擎 - 模块化架构
功能：从DXF文件中提取文本内容，采用模块化设计
作者：CAD翻译工具团队
版本：2.0
"""

import os
import sys
import logging
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

try:
    import ezdxf
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFEntity
except ImportError:
    print("错误：未安装ezdxf库，请运行: pip install ezdxf")
    sys.exit(1)

try:
    import pandas as pd
except ImportError:
    print("错误：未安装pandas库，请运行: pip install pandas")
    sys.exit(1)

# 确保日志目录存在
os.makedirs('logs', exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/text_extraction.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ExtractionMethod(Enum):
    """文本提取方法枚举"""
    MODEL_SPACE = "model_space"
    PAPER_SPACE = "paper_space"
    BLOCK_DEFINITIONS = "block_definitions"
    DXF_TAGS = "dxf_tags"
    EXTENDED_DATA = "extended_data"


@dataclass
class ExtractionResult:
    """提取结果数据类"""
    texts: List[str]
    method: ExtractionMethod
    file_path: str
    success: bool
    error_message: Optional[str] = None


class TextExtractor(ABC):
    """文本提取器抽象基类"""
    
    @abstractmethod
    def extract(self, doc: Drawing, file_path: str) -> ExtractionResult:
        """提取文本的抽象方法"""
        pass


class ModelSpaceExtractor(TextExtractor):
    """模型空间文本提取器"""
    
    def extract(self, doc: Drawing, file_path: str) -> ExtractionResult:
        """从模型空间提取文本"""
        texts = []
        try:
            msp = doc.modelspace()
            # 提取TEXT实体
            for entity in msp.query('TEXT'):
                if hasattr(entity, 'dxf') and hasattr(entity.dxf, 'text'):
                    text = entity.dxf.text.strip()
                    if text:
                        texts.append(text)
            
            # 提取MTEXT实体
            for entity in msp.query('MTEXT'):
                if hasattr(entity, 'text'):
                    text = entity.text.strip()
                    if text:
                        texts.append(text)
            
            # 提取INSERT实体的属性
            for entity in msp.query('INSERT'):
                if hasattr(entity, 'attribs'):
                    for attrib in entity.attribs:
                        if hasattr(attrib, 'dxf') and hasattr(attrib.dxf, 'text'):
                            text = attrib.dxf.text.strip()
                            if text:
                                texts.append(text)
            
            return ExtractionResult(
                texts=texts,
                method=ExtractionMethod.MODEL_SPACE,
                file_path=file_path,
                success=True
            )
        except Exception as e:
            logger.warning(f"模型空间提取失败 {file_path}: {e}")
            return ExtractionResult(
                texts=[],
                method=ExtractionMethod.MODEL_SPACE,
                file_path=file_path,
                success=False,
                error_message=str(e)
            )


class PaperSpaceExtractor(TextExtractor):
    """图纸空间文本提取器"""
    
    def extract(self, doc: Drawing, file_path: str) -> ExtractionResult:
        """从图纸空间提取文本"""
        texts = []
        try:
            for layout in doc.layouts:
                if layout.name.startswith('*Paper_Space'):
                    # 提取TEXT和MTEXT实体
                    for entity in layout.query('TEXT MTEXT'):
                        text = self._extract_text_from_entity(entity)
                        if text:
                            texts.append(text)
                    
                    # 提取INSERT实体的属性
                    for entity in layout.query('INSERT'):
                        if hasattr(entity, 'attribs'):
                            for attrib in entity.attribs:
                                text = self._extract_text_from_entity(attrib)
                                if text:
                                    texts.append(text)
            
            return ExtractionResult(
                texts=texts,
                method=ExtractionMethod.PAPER_SPACE,
                file_path=file_path,
                success=True
            )
        except Exception as e:
            logger.warning(f"图纸空间提取失败 {file_path}: {e}")
            return ExtractionResult(
                texts=[],
                method=ExtractionMethod.PAPER_SPACE,
                file_path=file_path,
                success=False,
                error_message=str(e)
            )
    
    def _extract_text_from_entity(self, entity: DXFEntity) -> Optional[str]:
        """从实体中提取文本"""
        try:
            if hasattr(entity, 'dxf') and hasattr(entity.dxf, 'text'):
                return entity.dxf.text.strip()
            elif hasattr(entity, 'text'):
                return entity.text.strip()
        except:
            pass
        return None


class BlockDefinitionExtractor(TextExtractor):
    """块定义文本提取器"""
    
    def extract(self, doc: Drawing, file_path: str) -> ExtractionResult:
        """从块定义提取文本"""
        texts = []
        try:
            for block in doc.blocks:
                # 提取TEXT和MTEXT实体
                for entity in block.query('TEXT MTEXT'):
                    if hasattr(entity, 'dxf') and hasattr(entity.dxf, 'text'):
                        text = entity.dxf.text.strip()
                        if text:
                            texts.append(text)
                    elif hasattr(entity, 'text'):
                        text = entity.text.strip()
                        if text:
                            texts.append(text)
            
            return ExtractionResult(
                texts=texts,
                method=ExtractionMethod.BLOCK_DEFINITIONS,
                file_path=file_path,
                success=True
            )
        except Exception as e:
            logger.warning(f"块定义提取失败 {file_path}: {e}")
            return ExtractionResult(
                texts=[],
                method=ExtractionMethod.BLOCK_DEFINITIONS,
                file_path=file_path,
                success=False,
                error_message=str(e)
            )


class DXFTagExtractor(TextExtractor):
    """DXF标签文本提取器"""
    
    def extract(self, doc: Drawing, file_path: str) -> ExtractionResult:
        """从DXF标签提取文本"""
        texts = []
        try:
            # 遍历所有实体的DXF标签
            for entity in doc.modelspace():
                if hasattr(entity, 'dxf'):
                    for attr_name in dir(entity.dxf):
                        if not attr_name.startswith('_'):
                            try:
                                value = getattr(entity.dxf, attr_name)
                                if isinstance(value, str) and value.strip():
                                    # 过滤掉明显不是文本内容的值
                                    if not self._is_technical_value(value):
                                        texts.append(value.strip())
                            except:
                                continue
            
            return ExtractionResult(
                texts=texts,
                method=ExtractionMethod.DXF_TAGS,
                file_path=file_path,
                success=True
            )
        except Exception as e:
            logger.warning(f"DXF标签提取失败 {file_path}: {e}")
            return ExtractionResult(
                texts=[],
                method=ExtractionMethod.DXF_TAGS,
                file_path=file_path,
                success=False,
                error_message=str(e)
            )
    
    def _is_technical_value(self, value: str) -> bool:
        """判断是否为技术值（非文本内容）"""
        # 首先检查是否可能是有意义的文本
        if self._is_meaningful_text(value):
            return False
            
        # 过滤掉数字、坐标、图层名、句柄等技术值
        technical_patterns = [
            lambda x: x.replace('.', '').replace('-', '').replace(',', '').isdigit(),  # 纯数字
            lambda x: len(x) < 2,  # 太短的字符串
            lambda x: x.upper() in ['BYLAYER', 'BYBLOCK', 'CONTINUOUS'],  # CAD关键字
            lambda x: self._is_handle_value(x),  # 句柄值
            lambda x: len(x) > 100,  # 过长的字符串可能是技术数据
            lambda x: self._is_layer_name(x),  # 图层名
            lambda x: self._is_short_hex(x),  # 短的十六进制值
            lambda x: self._is_cad_entity_type(x),  # CAD实体类型名称
        ]
        return any(pattern(value) for pattern in technical_patterns)
    
    def _is_handle_value(self, value: str) -> bool:
        """判断是否为句柄值"""
        # 句柄值通常是十六进制字符串，长度在3-8位之间
        if len(value) < 3 or len(value) > 8:
            return False
        try:
            # 尝试将其解析为十六进制数
            int(value, 16)
            # 如果成功解析且包含字母，很可能是句柄
            return any(c.isalpha() for c in value.upper())
        except ValueError:
            return False
    
    def _is_layer_name(self, value: str) -> bool:
        """判断是否为图层名"""
        value_lower = value.lower()
        
        # 常见的图层名模式
        layer_patterns = [
            'layer',
            'default',
            'defpoints',
            'dimension',
            'text',
            'hatch',
            'viewport'
        ]
        
        # 检查是否包含图层关键词
        if any(pattern in value_lower for pattern in layer_patterns):
            return True
            
        # 检查是否符合图层命名模式：Layer_数字 或 数字开头
        import re
        layer_name_patterns = [
            r'^layer[_-]?\d+$',  # Layer_0, Layer-1, Layer01等
            r'^\d+$',           # 纯数字图层名
            r'^[0-9]+[a-z]*$',  # 数字开头可能带字母的图层名
        ]
        
        return any(re.match(pattern, value_lower) for pattern in layer_name_patterns)
    
    def _is_short_hex(self, value: str) -> bool:
        """判断是否为短的十六进制值"""
        if len(value) > 4:  # 只检查4个字符以下的短字符串
            return False
        try:
            int(value, 16)
            return True
        except ValueError:
            return False
    
    def _is_meaningful_text(self, value: str) -> bool:
        """判断是否为有意义的文本内容"""
        # 首先检查是否为技术性名称（图层名、实体类型等）
        if self._is_layer_name(value) or self._is_cad_entity_type(value):
            return False
            
        # 包含中文字符的文本
        if any('\u4e00' <= char <= '\u9fff' for char in value):
            return True
            
        # 包含多个单词的英文文本（用空格分隔）
        if ' ' in value.strip() and len(value.split()) >= 2:
            return True
            
        # 包含常见标点符号的文本
        punctuation_marks = ['.', ',', '!', '?', ':', ';', '(', ')', '[', ']']
        if any(mark in value for mark in punctuation_marks) and len(value) > 3:
            return True
            
        # 长度适中且包含字母的文本，但排除下划线分隔的技术名称
        if (4 <= len(value) <= 50 and any(c.isalpha() for c in value) and 
            not value.isupper() and '_' not in value):
            return True
            
        return False
    
    def _is_cad_entity_type(self, value: str) -> bool:
        """判断是否为CAD实体类型名称"""
        cad_entity_types = [
            'LINE', 'CIRCLE', 'ARC', 'POLYLINE', 'LWPOLYLINE', 'SPLINE',
            'ELLIPSE', 'POINT', 'BLOCK', 'INSERT', 'TEXT', 'MTEXT',
            'DIMENSION', 'LEADER', 'HATCH', 'SOLID', 'TRACE', '3DFACE',
            'VIEWPORT', 'XLINE', 'RAY', 'REGION', 'BODY', 'ACAD_PROXY_ENTITY',
            'MESH', 'SURFACE', 'PLANESURFACE', 'EXTRUDEDSURFACE',
            'REVOLVEDSURFACE', 'SWEPTSURFACE', 'LOFTEDSURFACE',
            'NURBS', 'HELIX', 'WIPEOUT', 'IMAGE', 'UNDERLAY'
        ]
        return value.upper() in cad_entity_types


class TextFilter:
    """文本过滤器"""
    
    def __init__(self, min_length: int = 1, max_length: int = 1000):
        self.min_length = min_length
        self.max_length = max_length
        self.exclude_patterns = {
            'STANDARD', 'BYLAYER', 'BYBLOCK', 'CONTINUOUS',
            '0', '1', '2', '3', '4', '5', '6', '7', '8', '9'
        }
    
    def filter_texts(self, texts: List[str]) -> List[str]:
        """过滤文本列表"""
        filtered = []
        for text in texts:
            if self._is_valid_text(text):
                cleaned = self._clean_text(text)
                if cleaned:
                    filtered.append(cleaned)
        return filtered
    
    def _is_valid_text(self, text: str) -> bool:
        """判断文本是否有效"""
        if not text or len(text) < self.min_length or len(text) > self.max_length:
            return False
        
        # 排除特定模式
        if text.upper() in self.exclude_patterns:
            return False
        
        # 排除纯数字
        if text.replace('.', '').replace('-', '').isdigit():
            return False
        
        return True
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        # 移除前后空白
        cleaned = text.strip()
        
        # 移除特殊字符
        cleaned = cleaned.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        
        # 合并多个空格
        while '  ' in cleaned:
            cleaned = cleaned.replace('  ', ' ')
        
        return cleaned


class ExcelExporter:
    """Excel导出器"""
    
    def export_to_excel(self, texts: List[str], output_path: str) -> bool:
        """导出文本到Excel文件"""
        try:
            # 创建DataFrame
            df = pd.DataFrame({
                '序号': range(1, len(texts) + 1),
                '原文': texts,
                '译文': [''] * len(texts)  # 空的译文列
            })
            
            # 保存到Excel
            df.to_excel(output_path, index=False, engine='openpyxl')
            logger.info(f"成功导出 {len(texts)} 条文本到 {output_path}")
            return True
        except Exception as e:
            logger.error(f"导出Excel失败: {e}")
            return False


class TextExtractionEngine:
    """文本提取引擎主类"""
    
    def __init__(self):
        self.extractors = {
            ExtractionMethod.MODEL_SPACE: ModelSpaceExtractor(),
            ExtractionMethod.PAPER_SPACE: PaperSpaceExtractor(),
            ExtractionMethod.BLOCK_DEFINITIONS: BlockDefinitionExtractor(),
            ExtractionMethod.DXF_TAGS: DXFTagExtractor()
        }
        self.text_filter = TextFilter()
        self.excel_exporter = ExcelExporter()
    
    def extract_from_file(self, file_path: str) -> List[str]:
        """从单个DXF文件提取文本"""
        try:
            # 读取DXF文件
            doc = ezdxf.readfile(file_path)
            all_texts = set()  # 使用集合去重
            
            # 使用所有提取器提取文本
            for method, extractor in self.extractors.items():
                result = extractor.extract(doc, file_path)
                if result.success:
                    all_texts.update(result.texts)
                    logger.debug(f"{method.value} 提取到 {len(result.texts)} 条文本")
            
            # 过滤和清理文本
            filtered_texts = self.text_filter.filter_texts(list(all_texts))
            
            logger.info(f"从 {file_path} 提取到 {len(filtered_texts)} 条有效文本")
            return sorted(filtered_texts)  # 排序返回
            
        except ezdxf.DXFStructureError as e:
            logger.warning(f"DXF结构错误 {file_path}: {e}")
            # 尝试修复并重新读取
            return self._try_repair_and_extract(file_path)
        except Exception as e:
            logger.error(f"提取文本失败 {file_path}: {e}")
            return []
    
    def _try_repair_and_extract(self, file_path: str) -> List[str]:
        """尝试修复DXF文件并重新提取"""
        try:
            logger.info(f"尝试修复DXF文件: {file_path}")
            doc = ezdxf.recover.readfile(file_path)
            
            all_texts = set()
            for method, extractor in self.extractors.items():
                result = extractor.extract(doc, file_path)
                if result.success:
                    all_texts.update(result.texts)
            
            filtered_texts = self.text_filter.filter_texts(list(all_texts))
            logger.info(f"修复后提取到 {len(filtered_texts)} 条有效文本")
            return sorted(filtered_texts)
            
        except Exception as e:
            logger.error(f"修复失败 {file_path}: {e}")
            return []
    
    def extract_from_directory(self, directory_path: str) -> List[str]:
        """从目录中的所有DXF文件提取文本"""
        directory = Path(directory_path)
        if not directory.exists():
            logger.error(f"目录不存在: {directory_path}")
            return []
        
        all_texts = set()
        dxf_files = list(directory.glob('**/*.dxf'))  # 递归搜索所有子目录
        
        if not dxf_files:
            logger.warning(f"目录及其子目录中没有找到DXF文件: {directory_path}")
            return []
        
        logger.info(f"找到 {len(dxf_files)} 个DXF文件")
        
        for dxf_file in dxf_files:
            texts = self.extract_from_file(str(dxf_file))
            all_texts.update(texts)
        
        final_texts = sorted(list(all_texts))
        logger.info(f"总共提取到 {len(final_texts)} 条唯一文本")
        return final_texts
    
    def process_and_export(self, input_path: str, output_path: str) -> bool:
        """处理输入路径并导出到Excel"""
        input_path_obj = Path(input_path)
        
        if input_path_obj.is_file() and input_path_obj.suffix.lower() == '.dxf':
            # 处理单个文件
            texts = self.extract_from_file(input_path)
        elif input_path_obj.is_dir():
            # 处理目录
            texts = self.extract_from_directory(input_path)
        else:
            logger.error(f"无效的输入路径: {input_path}")
            return False
        
        if not texts:
            logger.warning("没有提取到任何文本")
            return False
        
        # 导出到Excel
        return self.excel_exporter.export_to_excel(texts, output_path)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='DXF文本提取引擎')
    parser.add_argument('input_path', help='输入DXF文件或目录路径')
    parser.add_argument('-o', '--output', default='extracted_texts.xlsx', help='输出Excel文件路径')
    parser.add_argument('-v', '--verbose', action='store_true', help='详细输出')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 确保日志目录存在
    os.makedirs('logs', exist_ok=True)
    
    # 创建提取引擎并处理
    engine = TextExtractionEngine()
    success = engine.process_and_export(args.input_path, args.output)
    
    if success:
        print(f"✅ 文本提取完成！结果已保存到: {args.output}")
    else:
        print("❌ 文本提取失败！")
        sys.exit(1)


if __name__ == '__main__':
    main()