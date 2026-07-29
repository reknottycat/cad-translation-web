# CAD文件翻译处理Web系统 - 前端

## 项目概述

这是一个专业的CAD文件翻译处理Web系统的前端应用，基于React + TypeScript + Vite构建，为用户提供直观的CAD文件上传、处理和翻译界面。

## 技术栈

- **框架**: React 18
- **语言**: TypeScript
- **构建工具**: Vite
- **样式**: Tailwind CSS
- **HTTP客户端**: Axios
- **状态管理**: React Context API (可选)
- **代码规范**: ESLint + Prettier

## 项目结构

```
frontend/
├── src/
│   ├── components/            # 通用组件
│   │   ├── CADWorkflow.tsx   # CAD处理工作流组件
│   │   └── Layout.tsx        # 布局组件
│   ├── pages/                 # 页面组件
│   │   ├── HomePage.tsx      # 首页
│   │   ├── ModelGatewayPage.tsx  # 模型网关页面
│   │   ├── ProjectsPage.tsx  # 项目管理页面
│   │   └── TranslationPage.tsx  # 翻译页面
│   ├── services/              # 服务
│   │   └── api.ts            # API接口封装
│   ├── App.tsx                # 应用根组件
│   ├── main.tsx               # 应用入口
│   └── index.css              # 全局样式
├── package.json               # 项目配置
├── vite.config.ts             # Vite配置
├── tsconfig.json              # TypeScript配置
└── README.md                  # 项目说明
```

## 安装和运行

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 配置API地址

在 `src/services/api.ts` 中配置后端API地址：

```typescript
// src/services/api.ts
const API_BASE_URL = 'http://localhost:8000'; // 后端服务地址
```

### 3. 启动开发服务器

```bash
npm run dev
```

### 4. 构建生产版本

```bash
npm run build
```

### 5. 预览生产版本

```bash
npm run preview
```

## 核心功能

### 1. 项目管理
- 创建和管理CAD翻译项目
- 查看项目详情和状态
- 项目文件管理

### 2. 文件上传
- 支持DWG/DXF文件上传
- 批量文件上传
- 文件格式验证

### 3. CAD处理
- 启动CAD文件处理流程
- 实时查看处理进度
- 下载处理结果

### 4. 翻译功能
- 文本内容提取和翻译
- 翻译结果管理
- 多语言支持

## 页面说明

### 首页 (HomePage)
- 系统概览
- 快速开始指南
- 功能入口

### 项目管理页面 (ProjectsPage)
- 项目列表
- 项目创建和编辑
- 项目状态跟踪

### 翻译页面 (TranslationPage)
- 文本翻译界面
- 翻译历史记录
- 翻译结果预览

### 模型网关页面 (ModelGatewayPage)
- 模型管理
- 网关配置
- 系统集成

## API 集成

前端通过 `src/services/api.ts` 与后端API进行通信，主要接口包括：

- **项目管理**: `/api/projects`
- **文件管理**: `/api/files`
- **翻译服务**: `/api/translate`
- **健康检查**: `/api/health`

## 开发指南

### 代码规范
- 使用TypeScript类型定义
- 遵循ESLint规则
- 组件命名采用PascalCase
- 变量和函数命名采用camelCase

### 组件开发
- 组件应具有单一职责
- 使用Props进行数据传递
- 合理使用React Hooks
- 组件样式使用Tailwind CSS

### 性能优化
- 组件懒加载
- 合理使用useMemo和useCallback
- 避免不必要的重新渲染
- 图片和资源优化

## 故障排除

### 常见问题

1. **API连接失败**
   - 检查后端服务是否运行
   - 验证API_BASE_URL配置
   - 检查网络连接

2. **文件上传失败**
   - 检查文件大小限制
   - 验证文件格式是否支持
   - 检查后端上传目录权限

3. **页面加载缓慢**
   - 检查网络速度
   - 优化组件渲染
   - 考虑使用代码分割

4. **样式问题**
   - 确保Tailwind CSS配置正确
   - 检查CSS类名拼写
   - 清除浏览器缓存

## 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 创建Pull Request

## 许可证

MIT License