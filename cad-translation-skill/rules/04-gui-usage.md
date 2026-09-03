---
title: Web、CLI 与遗留 GUI 规则
impact: MEDIUM
impactDescription: 入口说明必须指向当前维护的运行方式
tags: [web, cli, gui, usage]
---

# Web、CLI 与遗留 GUI 规则

当前主入口是 Web：

~~~powershell
cd backend
python run_server.py

cd frontend
npm run dev
~~~

当前 CLI 入口是：

~~~powershell
cd agent-harness
python -m pip install -e .
cad-translate --help
cad-translate doctor
~~~

trans_CAD_gui_V1.0/ 是遗留桌面实现；不要再使用 python gui.py、
根目录 haochen_optimized_converter.py 或根目录 回填.py 作为当前安装说明。

内网多人使用时，任务锁和唯一目录可减少覆盖冲突，但系统仍是单租户，
没有按用户的数据隔离；ADMIN_API_TOKEN 保护的是整个实例。
