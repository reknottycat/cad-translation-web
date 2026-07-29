# 现代化架构说明

## 目标

- 统一翻译接口，支持多厂商模型与自定义 OpenAI-compatible endpoint。
- 保留历史调用路径，避免一次性重构带来的回归风险。
- 提供可扩展配置与打包发布能力。

## 架构总览

1. `backend/app/services/llm/translation_service.py`
- 统一翻译引擎。
- 单文本翻译、批量 JSON 翻译、Excel 翻译。
- 内置 provider 预设和 runtime summary。

2. `backend/app/services/alibaba_ai_translation_service.py`
- 兼容层。
- 旧引用不改代码也能走新引擎。

3. `backend/app/routers/translation.py`
- 暴露现代化 API：
- `/api/translation/text`
- `/api/translation/batch`
- `/api/translation/excel`
- `/api/translation/config`
- `/api/translation/providers`

## 数据流

1. 前端提交文本/Excel。
2. 路由调用统一引擎。
3. 统一引擎根据 `TRANSLATION_PROVIDER + LLM_*` 选择 endpoint/model。
4. 返回翻译结果 + 统计信息。

## 兼容性策略

- 保留原文件名与原全局实例变量（`alibaba_ai_translation_service`）。
- API 返回结构保持原有字段，新增字段放在 `config/providers` 接口中。

## 已识别风险

- 部分 CAD 路径仍对 DWG 需要转换器支持。
- 历史文件存在编码混杂（UTF-8/GBK），建议逐步清洗。
- 前后端仍有少量历史文案与旧流程并存。

## 下一步建议

1. 引入 `converter_backend=com|oda|dxf_only` 配置，完善 DWG 兜底。
2. 在前端新增 provider/model/base_url 表单并调用 `/api/translation/config`。
3. 把 legacy 脚本迁移到 `legacy/` 目录并保留兼容入口。
