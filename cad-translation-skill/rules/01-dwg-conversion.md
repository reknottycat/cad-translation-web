---
title: DWG 到 DXF 转换规则
impact: HIGH
impactDescription: 转换质量会直接影响后续文字提取和回填
tags: [cad, dwg, dxf, conversion, com]
---

# DWG 转换规则

主实现位于 backend/app/functions/dwg_converter.py，具体 COM bridge 位于
backend/app/services/autocad_converter.py 和
backend/app/services/haochen_optimized_converter.py。CLI 通过
agent-harness/cad_translate/bridge.py 复用它们，不要引用根目录历史转换脚本。

可用后端由配置决定：优先使用 AutoCAD COM、浩辰/GStarCAD 或中望/ZWCAD；
ODA File Converter 和 LibreDWG 仅作为备用。DXF 输入不需要 DWG 转换器。

AutoCAD/浩辰/中望 COM 只在运行后端的 Windows 主机上探测；注册 ProgID
不等于激活成功。保持发现、超时、专用 COM 进程和默认串行限制
CAD_COM_CONCURRENCY=1，不要声称会自动安装 CAD。

## 单向转换，翻译后不回转 DWG

DWG → DXF 是**单向**转换：它只用于让 ezdxf 能读取和编辑图纸文字。翻译并
回填完成后，交付物是 DXF。除非用户明确要求 DWG 输出，否则**不要**再调用
任何后端（COM、ODA File Converter、LibreDWG）把翻译后的 DXF 转回 DWG——
那是不必要的多余步骤。
