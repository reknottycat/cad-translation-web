# SCALE 发布与打包

本项目现在把 `scale_release` 定义为最终用户可运行的交付包，而不是源码镜像。

## 产物

- 输出目录：`scale_release/`
- 压缩文件：`scale_release.zip`

## 交付包内容

- `backend/` 运行所需代码
- `frontend/dist/` 已构建的静态前端
- `tools/` 运行所需工具
- `docs/modern/` 精简文档
- `start_delivery.bat` 双击启动入口
- `requirements.txt`

## 不再包含

- `frontend/src`
- `frontend/node_modules`
- `agent-harness`
- 测试、缓存、数据库、`.env`
- 历史交付材料和开发期辅助文件

## 打包方式

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale.ps1
```

脚本会先构建前端，再生成新的 `scale_release/` 和 `scale_release.zip`。

## 启动方式

最终用户在交付目录中双击：

```bat
start_delivery.bat
```

启动器会：

- 在 `cmd` 中显示交付根目录、后端入口路径、前端静态目录路径和访问地址
- 以单进程模式启动后端
- 由后端直接托管前端静态页
- 自动打开浏览器到 `http://127.0.0.1:8000/`
