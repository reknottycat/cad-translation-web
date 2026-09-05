# 多模型服务商与运行时配置

服务商预设的实际列表由 `GET /api/translation/providers` 返回；不要在文档中复制可能变化的模型清单。内置定义位于 `backend/app/services/llm/providers.py`。

## Provider profile

每个服务商使用独立 profile，至少包含：

- `format`：`openai_compatible`、`anthropic`、`google`、`ollama` 或 `lmstudio`
- `base_url`
- `model`
- `reasoning_enabled`
- `timeout_seconds`
- `temperature`
- `max_tokens`

profile 保存在运行时配置的 `llm.provider_profiles` 中。切换服务商时加载目标 profile；没有 profile 时才使用该预设默认值。Custom 也有独立空白 profile，不继承前一个服务商的地址、模型或密钥。

## 凭据边界

凭据保存在 `llm.provider_api_keys` 及兼容的 primary 配置中，但公共配置摘要不会返回真实值。前端只读取每个服务商的 `configured`、`source` 和 `masked` 状态。

保存契约：

- 省略 `api_key`：保持原值。
- 发送非空 `api_key`：替换选中服务商的值。
- 发送 `clear_api_key: true`：删除选中服务商的已存值。
- 发送空 `api_key`：按省略处理，避免普通设置修改误删密钥。

环境变量仍可提供凭据。状态中的 `source` 反映运行时实际命中的来源；删除配置文件中的密钥后，如果环境仍提供该服务商凭据，`configured` 仍会为 true。

## 自定义服务商

`POST /api/translation/providers/custom` 接受 Unicode 显示名，并允许省略 ID。服务端生成稳定、安全的 ID，显示名不参与 URL 路径解析。请求必须显式保存 `api_format`，服务端拒绝不支持的协议、内置 ID 冲突和已有自定义 ID 冲突。

成功响应返回完整 `preset`，前端使用 `preset.id` 选择新服务商。自定义服务商文件只保存非密钥预设；凭据继续走统一运行时配置。

## 备用模型

`fallback_models` 是有序数组。工作台允许添加、删除、排序和编辑每项的服务商、协议、Base URL、模型和推理选项。运行时按数组顺序尝试，并在任务进度与最终状态中记录实际命中的服务商和模型。

备用项默认使用对应服务商已保存的凭据。配置读取不会为了编辑备用模型而回传密钥。

## 高级字段

| 字段 | 含义 |
| --- | --- |
| `retry_count` | 单次请求失败后的重试次数；总尝试次数为该值加一 |
| `rpm` | 每分钟请求上限 |
| `tpm` | 每分钟 Token 上限，支持 `120k` 等简写 |
| `extra_body` | 追加到上游请求体的 JSON 对象文本 |
| `use_system_proxy` | 是否使用系统代理环境；关闭时共享 transport 设置 `trust_env=false` |
| `batch_json` | 是否使用批量 JSON 协议 |

连接测试和实际翻译复用同一传输配置。连接测试是对当前端点与凭据的即时检查，不代表供应商配额、计费状态或后续请求一定成功。
