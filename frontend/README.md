# CAD 翻译 Web 前端

当前前端是 React 18、TypeScript 和 Vite 构建的单页工作台。应用入口 `src/App.tsx` 直接渲染 `TranslationWorkbenchPage`；模型配置、CAD 上传、任务状态、日志和下载都在该工作台完成。

## 开发

```powershell
cd frontend
npm ci
npm run dev
```

前端 `package-lock.json` 纳入版本管理；本地与 CNB 使用 `npm ci` 进行可复现安装。修改依赖后同步提交 `package.json` 和锁文件。

默认 API 前缀为 `/api`。需要连接其他后端时设置：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api
```

验证命令：

```powershell
npm test
npm run lint
npm run build
```

## 运行行为

- 配置、服务商和语言列表独立加载；单项失败会显示原因和重试操作，不会清空其他已加载数据。
- Admin Guard 开启时，在工作台填写管理令牌。共享 Axios 客户端为 JSON、上传和 Blob 下载统一添加 `X-Admin-Token`。
- API Key 是只写字段。配置摘要只返回 `configured`、`source` 和掩码；留空保存保持现有密钥，只有“删除已存密钥”会显式清除。
- 每个服务商分别记忆协议、Base URL、模型和推理参数；初次加载与保存后显示后端实际生效的配置，历史 profile 仅用于切换服务商。备用模型按显示顺序执行。
- 完整 CAD 上传使用后台任务协议：上传成功后取得 `task_id`，工作台轮询单任务直到完成、部分完成、失败或停止。
- 历史任务按页加载并使用更新时间增量刷新。轮询请求不会重叠，页面隐藏时降低频率。

## 代码结构

`src/pages/TranslationWorkbenchPage.tsx` 负责工作流编排。模型配置、任务历史、页面数据类型、侧栏和工作区分别位于 `src/pages/workbench/`。所有活跃模块保持在项目规定的 800 行以内。

后端接口契约见 [Frontend API Spec](../docs/modern/FRONTEND_API_SPEC.md)。服务商配置说明见 [LLM Providers](../docs/modern/LLM_PROVIDERS.md)。
