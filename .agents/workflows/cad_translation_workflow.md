---
name: cad_translation_pipeline
description: CAD文件翻译完整工作流 - 将DWG/DXF文件从提取到回填的完整流程
version: "1.0"
steps:
  - id: convert
    function: dwg_converter
    enabled: true
    description: 将 DWG 文件转换为 DXF（如果已是 DXF 则跳过）

  - id: extract
    function: text_extractor
    enabled: true
    description: 从 DXF 文件提取文本实体并输出到 Excel

  - id: translate
    function: translator
    enabled: true
    description: 调用 AI 翻译服务将 Excel 中的原文翻译为目标语言

  - id: apply
    function: text_applier
    enabled: true
    description: 将翻译结果回填到 DXF 文件（支持替换模式和追加模式）
---

# CAD 翻译工作流

本工作流描述 CAD 文件翻译的完整执行流程。主程序读取此文件后，按照 `steps` 顺序依次执行对应功能。

## Context 变量说明

工作流运行时，每个步骤都会读取并可能更新以下 Context 变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `input_file` | str | 输入文件完整路径（DWG 或 DXF）|
| `task_dir` | str | 任务工作目录路径 |
| `dxf_file` | str | 当前 DXF 文件路径（convert 步骤更新）|
| `excel_file` | str | 提取的 Excel 文件路径（extract 步骤更新）|
| `translation_map` | dict | 原文->译文映射（translate 步骤更新）|
| `output_file` | str | 输出 DXF 文件路径（apply 步骤更新）|
| `target_language` | str | 目标语言代码（默认 "en"）|
| `translation_mode` | str | 翻译模式："replace" 或 "add"（默认 "replace"）|
| `font_name` | str | 输出字体名称（默认 "Times New Roman"）|
| `font_size_reduction` | int | 字号缩小量（默认 2）|
| `converter_backend` | str | DWG 转换后端（默认 "dxf_only"）|

## 步骤说明

### 1. convert（DWG 转换）
- **输入**: `input_file`, `task_dir`, `converter_backend`
- **输出**: 更新 `dxf_file` 为转换后的 DXF 路径
- **跳过条件**: 输入文件已是 DXF 格式

### 2. extract（文本提取）
- **输入**: `dxf_file`, `task_dir`
- **输出**: 更新 `excel_file` 为提取结果 Excel 路径

### 3. translate（文本翻译）
- **输入**: `excel_file`, `target_language`
- **输出**: 更新 `translation_map`（原文->译文）

### 4. apply（翻译回填）
- **输入**: `dxf_file`, `task_dir`, `translation_map`, `translation_mode`, `font_name`, `font_size_reduction`
- **输出**: 更新 `output_file` 为最终 DXF 路径
