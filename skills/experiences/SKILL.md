---
name: experiences
description: 通用的验证与复盘原则。只在当前证据命中对应信号时加载，不包含题号、答案或历史解题链。
---

# 通用验证经验 Skill

## 使用方式

观察到多服务拓扑、验证码会话或 Redis 业务备份等明确证据时，加载 `case-notes.md`。只使用抽象方法，所有结论必须在当前题目重新验证；不得把历史题号、地址、凭据或攻击链写入经验库。

## 路由

| 证据 | 加载 reference |
|---|---|
| 同主机多服务、验证码 Cookie、Redis 业务备份、ComfyUI-Manager | `case-notes.md` |
