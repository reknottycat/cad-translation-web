# Frontend API Spec

本文记录当前活跃 Web 工作台与后端的请求契约。后端路由定义仍是唯一可信源：[BACKEND_API_SPEC.md](./BACKEND_API_SPEC.md)。

## 活跃页面

`frontend/src/App.tsx` 直接渲染 `TranslationWorkbenchPage`。当前没有注册 `/gateway` 等多页面路由；模型配置是工作台侧栏的一部分。

前端默认使用 `/api`，可通过 `VITE_API_BASE_URL` 覆盖，例如：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

## 认证

开启 Admin Guard 时，工作台保存管理令牌，`frontend/src/services/api.ts` 的共享客户端为受保护的 JSON 请求、文件上传和 Blob 下载统一发送 `X-Admin-Token`。认证失败会保留已加载的本地状态，并给出对应资源的重试入口。

## 配置加载

工作台独立请求：

- `GET /api/translation/config`
- `GET /api/translation/providers`
- `GET /api/translation/languages`

三项请求互不依赖。一项失败不会阻止其他项显示；服务商请求失败时使用内置显示预设并明确显示错误，不能把回退预设当成服务端已保存状态。

`runtime.provider_profiles` 按服务商 ID 返回非密钥配置，包含 `format`、`base_url`、`model` 及模型参数。

`runtime.provider_credentials` 只返回状态：

```json
{
  "openai": {
    "configured": true,
    "source": "config",
    "masked": "sk-a...9xyz"
  }
}
```

响应不返回 `api_key` 或 `provider_api_keys` 的真实值。

## 保存配置

`POST /api/translation/config` 使用密钥三态：

| 请求字段 | 行为 |
| --- | --- |
| 省略 `api_key` | 保持当前服务商已存密钥 |
| 非空 `api_key` | 替换当前服务商密钥 |
| `clear_api_key: true` | 删除当前服务商已存密钥 |

空字符串按“未修改”处理。`api_key` 和 `clear_api_key: true` 不能同时使用。

同一请求可保存有序 `fallback_models` 和完整 `provider_profiles`。备用项引用服务商已存凭据，配置摘要仍不返回密钥。

自定义服务商使用 `POST /api/translation/providers/custom`。请求包含显示名、Base URL、默认模型和 `api_format`；ID 可省略并由服务端生成。服务端拒绝内置 ID 或现有自定义 ID 冲突，并在成功响应的 `preset.id` 返回最终 ID。

连接测试使用 `POST /api/translation/test-connection`。同步上游 I/O 在后端线程池执行，不阻塞 FastAPI 事件循环。

## CAD 后台任务

完整上传：

```text
POST /api/cad/upload
```

multipart 表单必须包含 `background=true`。成功返回 HTTP 202，正文包含：

```json
{"success": true, "data": {"task_id": "...", "status": "queued"}}
```

工作台随后轮询 `GET /api/cad/tasks/{task_id}`。终态为 `done`、`partial`、`error` 或 `cancelled`；`partial` 必须在 UI 中保持为部分完成，不能显示为完全成功。

恢复历史任务时发送 `POST /api/cad/tasks/{task_id}/resume`，正文为 `{"background": true}`。由后端继承任务原来的目标语言、插入方式和字体参数，避免当前表单设置覆盖历史任务。改变目标语言需要重新开始任务。

历史任务使用：

```text
GET /api/cad/tasks?limit=100&offset=0&updated_after=<unix-seconds>
```

首次加载逐页读取到 `total`；后续按 `updated_after` 合并变化。前端保证同一时刻只有一个历史列表请求，页面隐藏时从 3 秒降为 15 秒轮询，重新可见时立即刷新。

下载统一走共享认证客户端：

- `GET /api/cad/download/{task_id}/{file_type}`
- `POST /api/cad/download-package`

支持的 `file_type` 由后端路由约束，工作台使用 `excel`、`translated_cad` 和 `log`。
