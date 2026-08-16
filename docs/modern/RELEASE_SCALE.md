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

---

## 便携 EXE 交付包（scale_release_exe/）

在 `scale_release/`（需 Python 的运行时包）基础上，`scale_release_exe/` 是**自带 Python 运行时**的单机便携版本，目标机器无需预装 Python。

### 产物

- 输出目录：`scale_release_exe/`
- 入口：`launcher.exe`（PyInstaller onedir 打包）
- 内部：`_internal/` 包含 Python 运行时与收集的依赖库；`runtime_payload.zip` 内嵌后端源码 + 前端构建产物 + 工具

### 打包方式

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_scale_exe.ps1
```

脚本会先构建前端，再调用 PyInstaller 将 `release_exe/launcher.py` 打成 `launcher.exe`，并把 `backend/`、`frontend/dist/`、`tools/` 打包为 `runtime_payload.zip` 内嵌。

所需文件：

- `release_exe/launcher.py` — PyInstaller 入口，负责解压负载、启动后端、打开浏览器。
- `release_exe/pyinstaller_manifest.py` — 输出 PyInstaller 的 hidden-import / collect-* 清单。

### 启动方式

双击 `launcher.exe`：

- 将内嵌负载解压到 `%TEMP%/cad-translation-web/`
- 以单进程模式启动后端，并自动打开浏览器到 `http://127.0.0.1:<PORT>/`（端口被占用时自动换端口）
- 关闭命令行窗口即退出，退出后自动清理临时解压目录

### 在 CNB 上自动构建

- 打 `v*` Tag 时，`release-exe` 流水线会在 **Windows 自托管 Runner**（节点标签含 `windows`）上生成 EXE 并挂到同一 Tag 的 Release 附件。
- 也可在「流水线 → Web 触发」手动点击「生成 Windows EXE」（`manual-exe`）构建。
- 未接入 Windows 节点时，本机仍可用上方 PowerShell 命令生成。
