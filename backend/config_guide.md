# 腾讯云开发AI+配置指南

## 📋 配置步骤

### 1. 获取腾讯云API密钥

#### 方法一：通过腾讯云控制台
1. 访问 [腾讯云控制台](https://console.cloud.tencent.com/)
2. 登录您的腾讯云账号
3. 点击右上角头像 → 访问管理 → API密钥管理
4. 创建密钥或查看现有密钥
5. 复制 `SecretId` 和 `SecretKey`

#### 方法二：通过腾讯云开发控制台
1. 访问 [腾讯云开发控制台](https://console.cloud.tencent.com/tcb)
2. 选择或创建一个环境
3. 进入环境设置 → API密钥
4. 获取相关密钥信息

### 2. 配置环境变量

编辑 `backend/.env` 文件，填入您的密钥信息：

```bash
# 腾讯云开发AI+（混元模型）配置
HUNYUAN_SECRET_ID=您的SecretId
HUNYUAN_SECRET_KEY=您的SecretKey
HUNYUAN_MODEL=hunyuan-lite
HUNYUAN_REGION=ap-beijing
```

### 3. 可选：配置DeepSeek模型

如果您想使用DeepSeek模型作为备选：

1. 访问 [DeepSeek官网](https://www.deepseek.com/)
2. 注册账号并获取API密钥
3. 在 `.env` 文件中配置：

```bash
# DeepSeek模型配置
DEEPSEEK_API_KEY=您的DeepSeek_API密钥
DEEPSEEK_MODEL=deepseek-chat
```

## 🔧 模型选择说明

### 混元模型版本
- `hunyuan-lite`: 轻量版，速度快，成本低
- `hunyuan-standard`: 标准版，平衡性能和成本
- `hunyuan-pro`: 专业版，最高质量，成本较高

### 推荐配置
- **开发测试**: 使用 `hunyuan-lite`
- **生产环境**: 使用 `hunyuan-standard` 或 `hunyuan-pro`

## 🚀 验证配置

配置完成后，运行以下命令验证：

```bash
cd backend
python config_validator.py
```

## 💡 注意事项

1. **安全性**: 请勿将 `.env` 文件提交到版本控制系统
2. **权限**: 确保API密钥有足够的权限访问AI服务
3. **配额**: 注意API调用配额和计费情况
4. **网络**: 确保服务器能访问腾讯云API

## 🔍 故障排除

### 常见问题

1. **认证失败**
   - 检查SecretId和SecretKey是否正确
   - 确认密钥是否已激活

2. **权限不足**
   - 确保账号有AI服务的使用权限
   - 检查是否开通了相关服务

3. **网络问题**
   - 检查网络连接
   - 确认防火墙设置

4. **配额超限**
   - 检查API调用配额
   - 查看计费情况

## 📞 获取帮助

如果遇到问题，可以：
1. 查看腾讯云开发文档
2. 联系腾讯云技术支持
3. 在项目中提交Issue