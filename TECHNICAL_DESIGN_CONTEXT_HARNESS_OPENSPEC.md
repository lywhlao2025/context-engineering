# Context-Harness-OpenSpec 融合技能技术文档（V2）

## 1. 文档定位

本文档定义 `context-harness-engineering` 技能的可发布技术方案（V2），对应当前实现特征：

- **单入口意图驱动**：用户仅需输入自然语言目标（如“我想完成XX功能”）。
- **固定三阶段流水线**：
  1) Context Engineering（先）
  2) OpenSpec Scope Definition（中）
  3) Harness Engineering（后）
- **风险闸门与失败透明**：包含 Stage 2.5 Scope Gate、Failure State Management、可复现验证证据。

---

## 2. 目标与非目标

## 2.1 目标
1. 降低用户操作门槛：从“多命令驱动”收敛为“单句意图驱动”。
2. 在棕地仓库中实现可持续改造：先建上下文，再定范围，最后编码与治理落地。
3. 建立可审计闭环：范围定义、实现证据、验证证据、风险输出完整可追溯。

## 2.2 非目标
1. 不要求用户显式执行 `/opsx:*` 命令。
2. 不追求一次性大重构，拒绝偏离 brownfield-first 的激进重写。
3. 不在验证失败时“伪完成”任务。

---

## 3. 设计原则

### 3.1 OpenSpec 原则吸收
- fluid not rigid
- iterative not waterfall
- easy not complex
- brownfield-first

### 3.2 架构治理原则
- **先上下文后规格**：无上下文不做范围定义。
- **先范围后编码**：无范围共识不做实现。
- **先验证后完成**：无验证通过不宣告完成。
- **策略可执行化**：政策文本必须映射为检查脚本/CI门禁。

---

## 4. 系统架构（三层协同）

## 4.1 Context Layer（外部上下文层）
职责：构建团队协作上下文与模块认知，形成后续 spec 与编码的基础事实。

关键目录：
```text
~/clawDir/team/projects/<project>/
├── skill.md
├── agents/
├── modules/
├── references/
└── .context-sync/state.json
```

## 4.2 Spec Layer（OpenSpec 变更层）
职责：把用户意图转为明确变更边界与验收标准。

关键目录：
```text
<repo>/openspec/
├── specs/                 # 当前行为事实（source of truth）
└── changes/<change>/      # 提议变更（proposal/specs/design/tasks）
```

## 4.3 Governance Layer（Harness 执行层）
职责：把实现落成可治理、可验证、可持续的工程结果。

关键能力：
- repo-local artifacts 补齐
- executable checks
- CI gate 一致化
- 失败可复现与最小重试单元

---

## 5. 单入口交互协议

## 5.1 用户输入协议
允许输入：
- `我想完成XX功能`
- `请实现X能力`
- `实现/改造某功能并保证质量`

禁止依赖用户输入：
- `/opsx:propose`、`/opsx:apply` 等命令式流程。

## 5.2 触发防护（Trigger Guardrails）
仅当意图包含**功能交付或代码变更**时触发本技能。

不触发场景：
- 纯问答
- 非技术闲聊
- 无仓库影响任务

意图不清时：仅允许 1 个澄清问题后再执行。

---

## 6. 内部流水线定义（固定顺序）

## Stage 1 — Context Engineering（Foundation First）

### 输入
- `project`
- `repo`（本地代码目录）
- `target_root`（可选，默认 `~/clawDir/team`）

### 执行
```bash
python3 scripts/init_context_project.py --project <project> --code-dir <repo> [--target-root <root>]
python3 scripts/sync_context_project.py --project <project> --code-dir <repo> [--target-root <root>]
```

### 输出
- 模块/入口/Agent 路由认知
- 当前约束与上下文基线
- 可用于后续 OpenSpec 范围定义的事实基础

---

## Stage 2 — OpenSpec Scope Definition

### 目标
把用户意图映射为行为优先的变更范围与验收条件。

### 约束
- `openspec/specs/` 代表当前行为事实。
- `openspec/changes/<change>/` 代表变更增量。
- 规格必须 behavior-first，避免 implementation-first。

### 产物
- proposal
- specs（delta）
- design
- tasks

---

## Stage 2.5 — Scope Gate（风险闸门）

### 风险级别
- **Low-risk**：可自动进入实现。
- **Medium/High-risk**：需显式确认后再进入实现。

### 高风险判定示例
- 数据迁移
- schema 变更
- 鉴权/支付链路
- destructive operations

### 规则
未确认高风险范围，不得自动编码实现。

---

## Stage 3 — Harness Engineering（Implementation + Governance）

### 目标
按已确认范围进行编码改造并完成治理闭环。

### 最小治理结果（强制）
1. 无“仅政策声明、无可执行约束”的假治理。
2. 至少执行：`lint`、`tests`、`type/build`（或项目等价命令）。
3. CI 对 push/PR 覆盖与本地同等关键检查。
4. 关键引用/契约不过期。
5. 最终报告必须附命令与结果证据。

---

## 7. 输出契约（用户可见）

每次执行后必须输出 4 段：
1. **Scope summary**：in-scope / out-of-scope
2. **Implementation evidence**：变更文件/模块 + 关键改动意图
3. **Verification evidence**：执行命令 + pass/fail + CI 状态
4. **Risks & next retry scope**：风险、阻塞、最小重试范围

---

## 8. 失败处理与状态管理

## 8.1 失败透明
验证失败时禁止宣告完成，必须给出：
- Status: failed
- What passed
- What failed
- Risk
- Next action

## 8.2 Failure State Management
- 变更在隔离分支/worktree 内执行，验证通过前不合并。
- 失败后保留最小重试计划。
- 输出可复现证据：失败命令、错误签名、影响文件。

---

## 9. 一致性规则（跨层）

1. **Context ↔ OpenSpec 一致**
   - 若上下文文档与 specs/changes 冲突，先消解冲突再实现。

2. **OpenSpec ↔ Code 一致**
   - task 完成不等于完成；需验证通过。

3. **Policy ↔ Enforcement 一致**
   - 文档策略需对应脚本与 CI 门禁。

---

## 10. 资源与职责

## 10.1 scripts/
- `init_context_project.py`：初始化上下文骨架
- `sync_context_project.py`：上下文同步（Git incremental / non-Git full）
- `validate_harness_contract.py`：Agent 文档契约校验

## 10.2 references/
- `extraction-rules.md`
- `structure-rules.md`
- `output-templates.md`
- `delivery-checklist.md`
- `openspec-integration.md`

---

## 11. 质量门禁与验收

## 11.1 门禁
- Skill 结构校验通过（quick_validate）。
- 三阶段顺序未被破坏。
- 风险闸门可判定并阻断高风险自动实现。
- 失败场景可输出可复现证据。

## 11.2 DoD（Definition of Done）
满足以下条件才算完成：
1. 上下文已构建并可用于模块/Agent 路由。
2. OpenSpec 变更范围与验收边界明确。
3. Harness 改造执行且验证证据完整。
4. 输出四段契约完整，且无伪完成声明。

---

## 12. 典型执行示例

### 用户输入
`我想完成“用户可切换深色模式”功能。`

### 内部执行
1. Stage 1：构建上下文并识别主题系统、设置模块、持久化入口。
2. Stage 2：定义 dark mode 变更范围、验收标准、任务拆分。
3. Stage 2.5：评估风险（若涉及全局 token 大改可能升高风险并请求确认）。
4. Stage 3：编码 + 治理 + 校验 + CI。

### 用户输出
- Scope：做什么/不做什么
- Implementation：改了哪些文件、为何改
- Verification：执行了什么命令、结果如何
- Risks：剩余风险与下一步最小重试范围

---

## 13. 发布建议

当前 V2 方案已经具备发布条件，建议发布前执行：
1. 用一个小功能跑端到端演练（happy path）。
2. 用一个故障用例验证失败透明（failed path）。
3. 打包 skill 并做一次冷启动安装验证。

---

## 附录 A：简版架构图（ASCII）

```text
                         ┌──────────────────────────────┐
                         │            User              │
                         │      “我想完成XX功能”         │
                         └──────────────┬───────────────┘
                                        │ Natural-language intent
                                        ▼
                   ┌──────────────────────────────────────────────┐
                   │     context-harness-engineering Skill         │
                   │      (single entry, intent-driven)            │
                   └──────────────┬───────────────────────────────┘
                                  │
      ┌───────────────────────────┼───────────────────────────┐
      ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐           ┌────────────────┐
│ Stage 1       │          │ Stage 2       │           │ Stage 3         │
│ Context Eng   │ ───────▶ │ OpenSpec      │ ────────▶ │ Harness Eng     │
│ (build/sync)  │          │ (scope/spec)  │           │ (code+governance│
└──────┬────────┘          └──────┬────────┘           │ + checks + CI)  │
       │                           │                    └────────┬───────┘
       │                           │                             │
       │                  ┌────────▼────────┐                    │
       │                  │ Stage 2.5 Gate  │                    │
       │                  │ risk classify   │                    │
       │                  │ low:auto        │                    │
       │                  │ med/high:confirm│                    │
       │                  └─────────────────┘                    │
       │                                                         │
       └─────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌──────────────────────────────────┐
                    │ User-visible 4-part output       │
                    │ 1) Scope                         │
                    │ 2) Implementation evidence       │
                    │ 3) Verification evidence         │
                    │ 4) Risks / next retry scope      │
                    └──────────────────────────────────┘
```

---

## 附录 B：端到端时序图（ASCII）

```text
User                 Skill               Stage1(Context)      Stage2(OpenSpec)      Stage2.5(Gate)      Stage3(Harness)
 |                     |                        |                    |                    |                    |
 |-- "我想完成XX功能" -->|                        |                    |                    |                    |
 |                     |-- init/sync ---------->|                    |                    |                    |
 |                     |<-- context baseline ---|                    |                    |                    |
 |                     |--------------------------------------------->|                    |                    |
 |                     |<----------- proposal/spec/design/tasks ------|                    |                    |
 |                     |--------------------------------------------------------------->|                    |
 |                     |<------------------------- risk level --------------------------|                    |
 |                     |--(if med/high ask confirm)--> User                             |                    |
 |<-- confirm needed? -|                        |                    |                    |                    |
 |-- confirm ---------->|                        |                    |                    |                    |
 |                     |--------------------------------------------------------------------------------------->|
 |                     |<------------------ code changes + checks + CI results ------------------------------|
 |<-------------------- 4-part result (scope/impl/verify/risk) ----------------------------------------------|
```

### 失败分支（简化）

```text
Stage3 verify failed
  -> Skill returns Status=failed
  -> include failing command + error signature + impacted files
  -> provide smallest retry scope
  -> keep isolated branch/worktree; no merge
```
