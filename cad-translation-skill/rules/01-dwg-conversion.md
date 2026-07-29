---
title: DWG到DXF转换规则
impact: HIGH
impactDescription: 转换是整个翻译流程的第一步，失败会导致后续流程无法进行
tags: [cad, dwg, dxf, conversion, com]
---

## DWG到DXF转换规则

使用浩辰CAD COM接口进行DWG到DXF转换。

### 核心模块

- `haochen_optimized_converter.py`: 优化的浩辰CAD转换器

### 转换流程

1. 通过COM接口启动浩辰CAD
2. 打开DWG文件
3. 另存为DXF格式（AutoCAD 2000）
4. 关闭文件释放资源

### 关键代码模式

```python
import win32com.client
import os

def convert_dwg_to_dxf(dwg_path, output_dir):
    cad = win32com.client.Dispatch("GstarCAD.Application")
    doc = cad.Documents.Open(dwg_path)
    dxf_path = os.path.join(output_dir, os.path.basename(dwg_path).replace('.dwg', '.dxf'))
    doc.SaveAs(dxf_path, 12)  # 12 = AutoCAD 2000 DXF
    doc.Close()
    cad.Quit()
```

### 注意事项

- 需要浩辰CAD、GStarCAD或ZWCAD安装
- 使用AutoCAD 2000格式(12)兼容性最好
- 转换后记得关闭CAD释放资源
