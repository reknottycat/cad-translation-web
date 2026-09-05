---
title: 双语翻译自动判断规则
impact: HIGH
impactDescription: 决定每条文字保留还是翻译，直接影响最终图纸语言结果
tags: [cad, dxf, translation, bilingual, russian]
---

# 双语翻译自动判断规则

当目标语言为俄文、图纸文字同时混有中英文时，逐条文本按下述**推荐自动判断
逻辑**决定 KEEP（保留）还是 TRANSLATE_TO_RUSSIAN（译成俄文），不要盲目全译。

## 自动判断逻辑

~~~
目标语言 = Russian

IF 文本已是俄文:
    KEEP

ELIF 文本是中文:
    TRANSLATE_TO_RUSSIAN

ELIF 文本是英文:
    IF 用户要求保留英俄双语:
        KEEP
    ELSE:
        IF 是人名 / 型号 / 位号 / 标准 / 编号 / 单位:
            KEEP
        ELSE:
            TRANSLATE_TO_RUSSIAN

ELSE:
    KEEP
~~~

要点：
- 中文文本（Chinese-only）优先全部译成俄文。
- 英文仅在用户要求统一俄文且不属于受保护类别时才翻译。
- 人名、型号、位号、标准、编码、单位等标识符一律保留，不做翻译。

## 混合字符串处理

对形如 `XV-101 Solenoid Valve` 的混合字符串：

- 先**保护**其中的型号/位号等标识符 `XV-101`；
- 只**翻译**描述性文字 `Solenoid Valve` → `Электромагнитный клапан`；
- 合并得到 `XV-101 Электромагнитный клапан`。

不要翻译受保护的人名/型号/位号/标准/编码/单位。

## Agent 标准双语工作流

~~~
DWG
↓
DWG → DXF
↓
提取全部 TEXT / MTEXT / ATTRIB / ATTDEF / BLOCK
↓
语言识别
↓
建立已有术语表
↓
识别中文-only
↓
中文 → 俄文
↓
回填 apply
↓
验证中文残留 = 0
↓
判断用户是否要求统一俄文
├─ 否 → 完成
└─ 是
    ↓
    提取 English-only
    ↓
    排除人名 / 型号 / 位号 / 标准 / 编码 / 单位
    ↓
    English → Russian
    ↓
    回填 apply
    ↓
    英文残留分类检查
    ↓
    CAD 版式检查
    ↓
    最终 DXF（见 03-translation-backfill.md 交付约定，不再回转 DWG）
~~~

上述判断与工作流是 Agent 决定“保留 vs 翻译”的操作指引；实际的提取、语言
识别、回填等步骤仍复用 backend/app 现有实现（text_extractor.py、
translation_service 等），不绕过项目主流程。
