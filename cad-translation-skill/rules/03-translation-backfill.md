---
title: 翻译与回填规则
impact: HIGH
impactDescription: 翻译和回填决定最终交付图纸内容
tags: [cad, dxf, translation, backfill]
---

# 翻译与回填规则

Excel 翻译可以由当前 Agent 在已授权会话中处理有限内容，也可以由 Web、
Celery 或 CLI 调用项目 LLM provider。前者使用 Agent 当前会话能力，不因
启用 Skill 而要求 API Key；后者除非使用本地/免 Key 后端，仍需要项目运行时
配置的认证。

CLI 分步入口：

~~~powershell
cad-translate pipeline translate-excel -i texts.xlsx
cad-translate pipeline apply -i drawing.dxf -e texts_translated.xlsx
~~~

回填使用 replace 或 add 模式，输出写入唯一任务目录。保留原始文件、任务
元数据和日志；API Key 不得进入 Excel、task.json、日志、Git 或发布包。
