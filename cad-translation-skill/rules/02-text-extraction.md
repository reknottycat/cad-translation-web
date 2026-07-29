---
title: DXF文本提取规则
impact: HIGH
impactDescription: 文本提取是翻译流程的核心步骤
tags: [cad, dxf, text, extraction, excel]
---

## DXF文本提取规则

从DXF文件中提取文本内容并生成Excel翻译表格。

### 核心模块

- `dxf_text_extractor.py`: 通用DXF文本提取器
- `extract_texts.py`: GUI专用文本提取引擎
- `命令行专用/提取.py`: 命令行文本提取器

### 支持的实体类型

- MTEXT: 多行文本
- TEXT: 单行文本
- ATTDEF: 属性定义
- ATTRIB: 属性

### 关键代码模式

```python
import ezdxf
from openpyxl import Workbook

def extract_texts_from_dxf(dxf_path):
    doc = ezdxf.readfile(dxf_path)
    texts = []
    
    # 提取MTEXT
    for mtext in doc.modelspace().query('MTEXT'):
        texts.append(mtext.text)
    
    # 提取TEXT
    for text in doc.modelspace().query('TEXT'):
        texts.append(text.dxf.text)
    
    return texts
```

### 输出格式

生成Excel文件 `extracted_texts.xlsx`，包含列：
- 原文 (Original)
- 译文 (Translation)

### 注意事项

- 使用ezdxf库读取DXF文件
- 处理空文本和特殊字符
- 支持递归搜索子目录中的DXF文件
