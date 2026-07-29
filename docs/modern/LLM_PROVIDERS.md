# 多模型厂商与配置模板

更新日期：2026-03-06（已做官方页面核验）

说明：以下均按 OpenAI-compatible 方式组织。免费额度/试用政策随时间变化，请以官方控制台为准。

## 推荐统一字段

- `TRANSLATION_PROVIDER`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

## 预置厂商（已内置到后端）

1. OpenAI
- base_url: `https://api.openai.com/v1`
- key env: `OPENAI_API_KEY`

2. OpenRouter
- base_url: `https://openrouter.ai/api/v1`
- key env: `OPENROUTER_API_KEY`
- 备注：常有社区免费模型

3. Alibaba DashScope (Qwen)
- base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- key env: `LLM_API_KEY`

4. DeepSeek
- base_url: `https://api.deepseek.com/v1`
- key env: `DEEPSEEK_API_KEY`

5. Groq
- base_url: `https://api.groq.com/openai/v1`
- key env: `GROQ_API_KEY`
- 备注：通常有一定免费额度

6. MiniMax
- base_url: `https://api.minimax.chat/v1`
- key env: `MINIMAX_API_KEY`

7. Zhipu GLM
- base_url: `https://open.bigmodel.cn/api/paas/v4`
- key env: `ZHIPU_API_KEY`

8. Moonshot (Kimi)
- base_url: `https://api.moonshot.cn/v1`
- key env: `MOONSHOT_API_KEY`

9. SiliconFlow
- base_url: `https://api.siliconflow.cn/v1`
- key env: `SILICONFLOW_API_KEY`
- 备注：常见开源模型托管与活动额度

10. Together AI
- base_url: `https://api.together.xyz/v1`
- key env: `TOGETHER_API_KEY`

11. Custom OpenAI-compatible
- base_url: 你自己的网关地址
- key env: `LLM_API_KEY`
- 适合接入企业内部网关或第三方聚合服务

## 免费/低成本实践建议

1. 开发联调优先用低成本模型（如 7B/8B instruct）。
2. 生产翻译按文本长度分层路由：短句走快模，关键术语走强模。
3. 开启缓存：相同术语不重复请求。
4. 先批量再单条重试，减少请求成本。

## 2026-03-06 核验结论（会随时间变化）

1. OpenRouter
- 存在 `openrouter/free` 路由与免费模型，但速率限制较低，不适合生产高并发。
- 参考：官方 FAQ 与 free router 文档。

2. Groq
- 文档页面可见 Free Plan Limits（免费计划限额），适合开发联调。
- 参考：Groq rate limits 文档。

3. Together AI
- 官方支持文档显示：当前平台接入通常需要最少 $5 预充值，不再默认提供注册免费 credits。
- 参考：Together support 文档（2025-10 更新）。

4. MiniMax
- 官网定价页显示“注册可获取免费额度”；但具体额度与活动期会变化。
- 参考：MiniMax pricing 页面。

5. SiliconFlow
- 官网强调按量计费，同时生态文档展示可接入和试用流程；免费试用通常依赖活动或合作客户端。
- 参考：SiliconFlow 官网与官方 user cases。
