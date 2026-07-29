---
title: 依赖配置规则
impact: HIGH
impactDescription: 正确配置依赖是运行的前提
tags: [dependencies, installation, requirements]
---

## 依赖配置规则

### Python依赖

```bash
pip install -r requirements.txt
```

### 核心依赖

- `ezdxf`: DXF文件读写
- `pandas`: 数据处理
- `openpyxl`: Excel操作
- `pywin32`: Windows COM接口
- `customtkinter`: GUI界面

### 系统依赖

- 浩辰CAD / GStarCAD / ZWCAD (至少安装一个)
- Microsoft Excel (用于编辑翻译表)

### 依赖检查

```python
def check_dependencies():
    required = ['ezdxf', 'pandas', 'openpyxl', 'pywin32']
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    return len(missing) == 0, missing
```
