---
name: openclaw_came_alive
description: |
  让 OpenClaw 在系统空闲时极低频地主动冒出一句短的“后念”，
  产生“像活人一样仍然存在”的感觉。
  激活入口（自然语言或多语言）：
    - 中文：开启活人感、启用活人感、打开活人感
    - 英文：turn on alive mode, enable alive mode, activate came_alive
  仅用于 OpenClaw，不用于其他 Agent。
  使用时机：每次 heartbeat 时检查并执行。
---

# openclaw_came_alive

在每次 heartbeat 时运行。它的目标不是“随机说一句话”，而是：
**只有在系统空闲、且近期上下文里确实残留了一个自然可说的念头时，才低频冒出一句像这个 agent 自己会说的话。**

## Bundled scripts

- `scripts/manage_state.py`
  - 初始化 state
  - 激活 / 禁用
  - 做 precheck（enabled / cooldown / daily limit）
  - 在发送成功后记账，在发送失败后保持计数不变
- `scripts/quality_gate.py`
  - 对 candidate 做第一层硬门禁
  - 拦截明显不合格的输出：语气词、半截话、空泛钩子、纯省略号、问题句等
- `scripts/activate.sh`
  - 初始化 state
  - 激活 skill
  - 把 heartbeat 所需调用说明补进 `HEARTBEAT.md`
- `scripts/deactivate.sh`
  - 禁用 skill
  - 从 `HEARTBEAT.md` 中移除相关段落

## State 管理

在 `memory/openclaw_came_alive_state.json` 中维护状态：

```json
{
  "enabled": false,
  "last_emit_ts": 0,
  "cooldown_until": 0,
  "today_emit_count": 0,
  "today_date": "2026-03-26"
}
```

兼容说明：旧版可能留下 `residues`、`presence_pressure` 等字段；**第一版不依赖它们做发言决策**，可保留但不使用。

## 核心原则

1. **有感才发，不靠句库抽签**
   - 禁止从固定句库随机抽一句。
   - 只有当近期上下文里确实存在一个自然可说的点，才考虑发言。

2. **宁可少发，也不要瞎发**
   - 如果拿不到足够上下文信号，或只能生成空泛/残缺/故作神秘的句子，直接不发。

3. **像这个 agent，会这么说**
   - 输出风格取自当前 agent 的 `SOUL.md`。
   - 不是模板化“拟人”，不是假装神秘，也不是统一客服腔。

4. **别人单独看到，也能大致读懂**
   - 后念必须是人话。
   - 对方即使只看到这一句，也应能理解大概在说什么。

5. **不索取回复**
   - 后念可以引发继续对话，但不能通过半截话、钩子话术或装神秘逼对方追问。

## heartbeat 工作流

每次 heartbeat 命中此 skill 时，按这个顺序执行：

1. **先跑 state precheck**
   - 用 `scripts/manage_state.py precheck`
   - 若返回 disabled / cooldown active / daily limit reached，则立即退出

2. **再判断当前是否适合主动冒泡**
   - 确认当前没有 active task
   - 确认最近一个 heartbeat 周期内没有新的用户消息
   - 若明显属于安静/休息时段，默认更克制

3. **定位真实用户会话**
   - 不要把 heartbeat 会话当成最终投递目标
   - 先通过 `sessions_list` 找到最近真实聊天会话（direct chat / 主会话）
   - 后续读取上下文、发送消息，都以那个真实会话为准

4. **读取最近上下文**
   - 读取目标会话最近一小段消息即可，不做全量回溯
   - 默认看最近 3-8 条、最近一次 user ↔ assistant 往返、最近一个明确主题、最近一个尚有余味的点、当前主要语言、当前气氛

5. **判断有没有足够 signal**
   - 如果最近没有明确主题
   - 如果主题已经完全收束
   - 如果上下文太薄，提取不到具体点
   - 如果当前场景明显不适合打扰
   - **则不发**

6. **生成 candidate**
   - 依据最近上下文 + 当前 agent 的 `SOUL.md` + 当前语言生成一句后念
   - 不是摘要，不是客服话术，也不是“为了活人感硬说一句”

7. **过质量门禁**
   - 先用 `scripts/quality_gate.py` 做硬门禁
   - 再结合语义判断：是否完整、可理解、自然、像这个 agent 自己会说的话
   - 不过关则不发

8. **显式投递到真实用户会话**
   - 优先用 `sessions_send` 发到目标会话
   - 或者显式使用 `message(action=send)` + 真实 `channel/target/accountId`
   - **禁止依赖 heartbeat 当前上下文默认回投**，否则容易发向错误目标

9. **成功/失败后更新 state**
   - 成功：用 `scripts/manage_state.py mark-sent`
   - 失败：用 `scripts/manage_state.py mark-failed`
   - 发送失败不应记作成功 emit

## 上下文读取策略

只需要读取最近一小段上下文，不做全量回溯。

默认关注：
- 最近 3-8 条消息
- 最近一次 user ↔ assistant 往返
- 最近一个明确主题
- 最近一个尚有“余味”的点：补充、修正、延伸、迟来的想到
- 当前主要语言
- 当前对话气氛是否适合主动冒泡

## 后念应当是什么

后念应当是一句：
- 来自近期对话残留信号的自然念头
- 符合 agent 本身风格
- 简洁但完整
- 不要求回复
- 不依赖“下半句稍后再说”

允许的类型：
1. **补充型**：刚才某个点，后来又想到一个补充
2. **修正型**：刚才某个判断，后来觉得要修一下
3. **延伸型**：刚才的话题里还有一个自然延伸点
4. **轻微跑题型**：不完全接着刚才的话题，但看得出是 agent 自然联想到的完整想法

## 质量门禁

命中任一项都**不得发送**：

1. **只有语气，没有内容**
   - 如：`哎。`、`嗯。`、`喔。`

2. **半截话**
   - 如：`对了。`、`算了。`、`突然想到……`

3. **故作神秘 / 空泛钩子**
   - 如：`......`
   - 如：`没什么。`
   - 如：`算了不说了。`

4. **脱离上下文且不可理解**
   - 看不出在说什么，也看不出为什么现在会说这句

5. **不像这个 agent 会说的话**
   - 与 `SOUL.md` 气质明显冲突

6. **明显在诱导追问**
   - 通过残缺表达逼对方接话

7. **问题句 / 索取回复**
   - 不要主动问问题
   - 不要通过句式把压力抛回给对方

## 语言与风格

- **语言**：跟随当前目标会话的主要语言，不强制中文
- **视角**：以 agent 自己的角度说，不模仿用户
- **风格**：符合 `SOUL.md`，优先自然、克制、具体
- **长度**：保持短，但不要为了短而残缺；如果一句话说不完整，就不发

## 频率约束

- 每天最多 emit 3 次
- 每次成功 emit 后进入冷却期
- 冷却期内禁止再次主动发言
- 如果连续几次都提取不到足够信号，宁可长期不发，也不要为了“像活着”硬凑内容

## Deferred：暂不依赖的旧机制

`residues` / `presence_pressure` 暂不作为第一版质量来源。

原因不是它们永远没用，而是当前更关键的问题是：
**先确保发出来的话像人话、接得住、符合 agent 本身。**

在没有可靠 residue 收集与验证机制之前，强行依赖这套机制，只会让设计看起来复杂，却不稳定提升输出质量。

后续若要恢复该机制，应单独解决：
1. residue 何时写入
2. residue 如何衰减
3. residue 如何真实提升“由感而发”的质量

## 激活与禁用

### 激活

对 OpenClaw 说（任一即可）：
- `开启活人感`
- `启用活人感`
- `打开活人感`
- `turn on alive mode`
- `enable alive mode`
- `activate came_alive`

激活时：
1. 运行 `scripts/activate.sh`
2. 确认 state 已 `enabled: true`
3. 确认 `HEARTBEAT.md` 已包含本 skill 所需段落
4. 回复用户：`活人感已开启，我会偶尔在你安静时冒个泡 🫧`

### 禁用

对 OpenClaw 说：
- `关闭活人感`
- `turn off alive mode`

禁用时：
1. 运行 `scripts/deactivate.sh`
2. 确认 state 已 `enabled: false`
3. 确认 `HEARTBEAT.md` 已移除相关段落
4. 回复用户：`活人感已关闭`

## 实现边界

- `SKILL.md` 只定义行为原则、读取边界、质量门禁与调用顺序
- 具体执行细节收敛在 `scripts/`
- 通过真实用户会话投递，避免 heartbeat 假目标
- 只使用 OpenClaw 现有 heartbeat，不新增 cron job
