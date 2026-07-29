---
title: 翻译回填规则
impact: HIGH
impactDescription: 将翻译文本回填到DXF文件的核心功能
tags: [cad, dxf, translation, backfill]
---

## 翻译回填规则

将Excel翻译表格中的译文回填到DXF文件。

### 核心模块

- `回填.py`: 翻译文本回填器

### 支持的实体类型

- MTEXT: 多行文本
- TEXT: 单行文本
- ATTDEF: 属性定义
- ATTRIB: 属性

### 关键代码模式

```python
import ezdxf

def translate_dxf(input_dxf, output_dxf, translation_map):
    doc = ezdxf.readfile(input_dxf)
    
    for mtext in doc.modelspace().query('MTEXT'):
        original = mtext.text
        if original in translation_map:
            mtext.text = translation_map[original]
    
    doc.saveas(output_dxf)
```

### 智能翻译匹配

支持多种空格处理策略：
- 移除所有空格
- 标准化为单空格
- 去除首尾空格

### 输出文件

翻译后的文件添加前缀：`trans_DXF_YYYYMMDD_HHMMSS_`
