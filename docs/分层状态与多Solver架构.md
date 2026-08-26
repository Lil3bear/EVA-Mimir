# 分层状态与多 Solver 架构

## 目标

不同题目、不同 run、同一题的不同 Solver attempt 必须默认隔离；难题仍允许多个 Solver 协作，但协作必须通过可审计、可验证的证据提案完成。

## 作用域

```text
全局 Skills（只读）
└── benchmark task
    └── challenge
        ├── shared/              Observer 批准后的事实与提案
        └── attempts/
            ├── aggressive/      私有 Memory、Ideas、history、control
            └── steady/          私有 Memory、Ideas、history、control
```

- Solver 的 `memory_add` 和 `idea_add` 默认写入当前 attempt 私有目录。
- Solver 的 `memory_list` 只能读取自己的私有状态和 shared 已批准事实。
- Observer 可以审阅当前题目的各 attempt，但不得把一个 attempt 的原始看板直接注入另一个 Solver。
- `memory_share` 只创建 proposal；Observer 必须验证后调用 `memory_promote`，事实才进入 shared。

## 协作原则

1. 原始思考、失败流水、未验证凭据不共享。
2. 共享对象必须是单条、可复现、带来源的证据。
3. Observer 负责分配互斥假设、审阅 proposal、批准事实和调度预算。
4. 多 Flag 题用 stage ledger 管理阶段和剩余 flag，不用复制整段对话。
5. 任何共享建议都必须带 challenge、attempt、state version 和过期边界。

## 兼容策略

旧的 `challenge/memory` 和 `challenge/ideas` 目录只作为迁移期间的 legacy read-only 状态；新 attempt 不再向其中写入。任务身份变化时会清理 `shared/`、attempts 和 legacy 恢复状态。
