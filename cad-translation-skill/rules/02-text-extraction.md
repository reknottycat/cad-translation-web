---
title: DXF 文本提取规则
impact: HIGH
impactDescription: 文本提取是翻译流程的核心步骤
tags: [cad, dxf, text, extraction, excel]
---

# 文本提取规则

主实现是 backend/app/functions/text_extractor.py，Web 接口是
/api/cad/extract，CLI 接口是：

~~~powershell
cad-translate pipeline extract -i drawing.dxf
~~~

DWG 先经过配置的转换后端生成 DXF，再提取 TEXT、MTEXT、ATTDEF 等文本到
任务隔离的 Excel。输出目录和 task.json 由 backend 的设置与 CLI store
统一管理；不要在 CLI 中复制一套提取实现或把临时 task.json 写到任务树外。
