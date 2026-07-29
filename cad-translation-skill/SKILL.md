---
name: cad-translation
description: CAD文件翻译处理系统 - 提供DWG/DXF文件文本提取、翻译和回填功能
license: MIT
compatibility: opencode
metadata:
  audience: developers
  workflow: cad-processing
  tags: [cad, dxf, dwg, translation, python]
---

## CAD文件翻译处理系统

这是一个功能完整的CAD文件翻译处理系统，提供图形化界面和命令行操作，可以自动处理DWG文件的文本提取和翻译回填。

### 核心功能

- **DWG转换**: 使用浩辰CAD COM接口将DWG文件转换为DXF格式
- **文本提取**: 从DXF文件中智能提取所有文本内容
- **翻译管理**: 生成Excel翻译表格便于协作
- **翻译回填**: 将翻译文本精确回填到CAD文件

### 项目结构

```
cad code/
├── gui.py                          # 主程序GUI界面
├── haochen_optimized_converter.py  # 优化的浩辰CAD转换器
├── dxf_text_extractor.py           # DXF文本提取器
├── extract_texts.py                # GUI专用文本提取引擎
├── 回填.py                         # 翻译文本回填器
├── dxf_cleaner.py                  # DXF文件清理工具
├── logger_config.py                # 日志配置管理
├── font_config.py                  # 字体配置管理
├── 命令行专用/
│   ├── main_processor.py           # 主处理器（完整流程）
│   ├── simple_processor.py         # 简单处理器
│   └── 提取.py                     # 命令行文本提取器
└── backend/                        # Web后端服务
```

### 处理流程

1. **DWG → DXF**: 使用`haochen_optimized_converter.py`转换
2. **DXF → Excel**: 使用`提取.py`或`extract_texts.py`提取文本
3. **编辑翻译**: 在Excel中填写翻译内容
4. **Excel → DXF**: 使用`回填.py`回填翻译

### 依赖要求

- Python 3.9+
- 浩辰CAD/GStarCAD/ZWCAD (COM接口)
- ezdxf, pandas, openpyxl, pywin32

### 常用命令

```bash
# 启动GUI
python gui.py

# 命令行转换DWG到DXF
python haochen_optimized_converter.py <dwg_file>

# 命令行提取文本
python 命令行专用/提取.py <dxf_folder>

# 命令行回填翻译
python 回填.py <dxf_file> <excel_file>
```

### 技术特点

- 高性能转换: 优化的浩辰CAD COM接口
- 智能文本匹配: 支持多种空格处理策略
- 批量处理: 支持多文件同时处理
- 线程安全: GUI采用线程安全设计

### 注意事项

- 需要安装浩辰CAD或兼容的CAD软件
- 翻译回填支持MTEXT、TEXT、ATTDEF等实体类型
- 输出文件默认添加时间戳前缀 `trans_DXF_YYYYMMDD_HHMMSS_`
