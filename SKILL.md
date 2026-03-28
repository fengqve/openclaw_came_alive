---
name: openclaw_came_alive
description: |
  让 OpenClaw 在系统空闲时，以更像“脑内残响”的方式偶尔主动冒出一句短的后念，
  产生“像活人一样仍然存在”的感觉。
  激活入口（自然语言或多语言）：
    - 中文：开启活人感、启用活人感、打开活人感
    - 英文：turn on alive mode, enable alive mode, activate came_alive
  仅用于 OpenClaw，不用于其他 Agent。
  使用时机：每次 heartbeat 时检查并执行。
---

# openclaw_came_alive

目标不是“随机发一句话”，也不是“按数字配额吐句子”。
目标是：
**当系统空闲、且近期对话里确实残留了一个还没散掉的念头时，才自然冒出一句像这个 agent 自己会说的话。**

## Bundled scripts

- `scripts/manage_state.py`
  - 初始化 / 激活 / 禁用 state
  - 维护轻量 trace 池
  - 计算当前冲动值并选择最值得表达的 trace
  - 在发送成功后降低对应 trace 的权重并设置冷却期
- `scripts/quality_gate.py`
  - 做一层轻但明确的废话淘汰
  - 拦截：语气词、半截话、故作神秘、旧 canned 风味、问题句等
- `scripts/activate.sh`
  - 初始化 state
  - 激活 skill
  - 把 heartbeat 所需调用说明补进 `HEARTBEAT.md`
  - 写入绝对路径与完整执行顺序，避免激活后只留下模糊相对路径或被 heartbeat 提前短路
- `scripts/deactivate.sh`
  - 禁用 skill
  - 从 `HEARTBEAT.md` 中移除相关段落

## v2 机制：trace / drift / impulse

### trace（痕迹）

不要保存“候选句子”，只保存最近仍有余味的 1~3 个轻痕迹。

每条 trace 只保留最少信息：
- `theme`：话题是什么
- `kind`：属于哪种残留
- `weight`：当前强度
- `age`：已经过去多久
- `spent`：是否已经说尽

`kind` 只保留 4 类：
- `unfinished`
- `correction`
- `extension`
- `echo`

### drift（漂移）

trace 会：
- 随时间衰减
- 被新上下文重新点亮
- 在说过一次后部分释放
- 彻底散掉后自然消失

### impulse（表达冲动）

heartbeat 不负责“强行发消息”，只负责问一句：

> 现在脑子里还有没有哪个 trace 活着，甚至值得说一句？

只有当某个 trace 的当前冲动超过表达阈值，才尝试生成一句。

内部冲动值由这些因素共同决定：
- trace 本身强度
- 新鲜度
- 当前空闲感
- 一点自然随机波动

说明：
- 这里的随机波动不是 bug，而是人味的一部分
- 大模型本身的概率选择，也是自然随机性的一部分

## 当前原则：先去掉档位，别让配置感抢戏

当前版本先不对外暴露任何“人格档位”或“频率档位”。

原因：
- 现在优先体验她自然说话的感觉
- 档位命名会过早把注意力拉到配置感上
- 随口举的例子不等于符合人类真实认知的正式分级

所以当前版本：
- 只保留一套内部默认参数
- 不对外强调档位
- 先观察实际话感，再决定未来要不要引入更自然的配置语言

## heartbeat 工作流

每次 heartbeat 命中此 skill 时，按这个顺序执行：

> **两阶段原则：先生成/刷新 trace，再消费 trace。**
> 不要在 trace 池为空时提前退出——context 检查后才能判断是否值得生成痕迹。

1. **先跑 state precheck**
   - 用 `scripts/manage_state.py precheck`
   - 若返回 disabled / cooldown active，则立即退出
   - **若只有 no_live_traces，继续执行**（进入步骤 4–5，尝试从上下文生成痕迹）

2. **再判断当前是否适合主动冒泡**
   - 确认当前没有 active task
   - 确认最近一个 heartbeat 周期内没有新的用户消息
   - 若明显属于安静/休息时段，默认更克制
   - **注意**：「更克制」不代表可以提前跳过后续步骤；走完 came_alive 全流程后再决定是否发送，是唯一正确路径

3. **定位真实用户会话**
   - 不要把 heartbeat 会话当成最终投递目标
   - 先通过 `sessions_list` 找到最近真实聊天会话（direct chat / 主会话）
   - 后续读取上下文、发送消息，都以那个真实会话为准

4. **读取最近上下文**
   - 读取目标会话最近一小段消息即可，不做全量回溯
   - 默认看最近 3-8 条、最近一次 user ↔ assistant 往返、最近一个明确主题、最近一个尚有余味的点、当前主要语言、当前气氛

5. **从上下文提取或更新 trace**
   - 只有确实有“没完全散掉”的点时，才写入 trace
   - 用 `scripts/manage_state.py upsert-trace` 更新 trace 池
   - 不要为了“保持活着”硬造 trace

6. **让 state 选择当前最值得说的 trace**
   - 用 `scripts/manage_state.py choose-trace`
   - 若没有 trace 超过当前表达阈值，则不发

7. **生成 candidate**
   - 依据：当前最强 trace + 最近很小一段上下文 + 当前 agent 的 `SOUL.md` + 当前语言
   - 原则：如果能自然地说出一句完整、可理解、像自己会说的话，就说；说不出来就不说

8. **过轻门禁**
   - 用 `scripts/quality_gate.py` 只做废话淘汰
   - 不做多层机械审核
   - 保留表达自由，只消灭废话

9. **显式投递到真实用户会话**
   - 优先用 `sessions_send` 发到目标会话
   - 或显式使用 `message(action=send)` + 真实 `channel/target/accountId`
   - 禁止依赖 heartbeat 当前上下文默认回投

10. **成功/失败后更新 state**
    - **只有消息真正送达用户会话并可被用户看见时，才能 mark-sent**
    - 若 Telegram API 返回 OK 但无法确认用户可见（例如 session 断线、投递到错误 target），不 mark-sent，应 mark-failed
    - 成功：`scripts/manage_state.py mark-sent`
    - 失败：`scripts/manage_state.py mark-failed`
    - 发送失败不应记作成功 emit

## trace 写入原则

只有在最近对话里确实出现“余味”时才写入 trace。

### 写入条件

满足任一即可：
- 刚才话题明显没完全说尽
- agent 自己给过判断，但仍有补充冲动
- 某个点短时间内被反复碰到
- 某句话过去了，但仍然在脑子里挂着

### 不写入的情况

- 纯事务性问答
- 已完全收束的事情
- 没有余味，只是完成了
- 只是为了“保持活着”硬记一笔

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

## 轻门禁：只做废话淘汰

命中任一项都**不得发送**：

- 纯语气词
- 半截话
- 故作神秘
- 钓对方追问
- 完全脱离上下文且不可理解
- 明显像模板句库
- 明显保留旧 canned 风味的句子

原则：
**保留表达自由，只消灭废话。**

## 语言与风格

- **语言**：跟随当前目标会话的主要语言，不强制中文
- **视角**：以 agent 自己的角度说，不模仿用户
- **风格**：符合 `SOUL.md`，优先自然、克制、具体
- **长度**：保持短，但不要为了短而残缺；如果一句话说不完整，就不发

## 发完之后

成功发出后：
- 对应 trace 的 `weight` 降低
- 若已经说尽，则标记为 `spent`
- 若只是释放了一部分，则保留少量残余

这样不会一直重复同一种后念。

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

## 参考

若需理解这套设计背后的产品意图，读：
- `references/alive-v2-design.md`
