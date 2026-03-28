---
name: openclaw_came_alive
description: |
  让 OpenClaw 在系统空闲时，以更像"脑内残响"的方式偶尔主动冒出一句短的后念，
  产生"像活人一样仍然存在"的感觉。
  激活入口（自然语言或多语言）：
    - 中文：开启活人感、启用活人感、打开活人感
    - 英文：turn on alive mode, enable alive mode, activate came_alive
  仅用于 OpenClaw，不用于其他 Agent。
  使用时机：每次 heartbeat 时检查并执行。
---

# openclaw_came_alive

目标不是"随机发一句话"，也不是"按数字配额吐句子"。
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

不要保存"候选句子"，只保存最近仍有余味的 1~3 个轻痕迹。

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

heartbeat 不负责"强行发消息"，只负责问一句：

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

当前版本先不对外暴露任何"人格档位"或"频率档位"。

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
> 不要在 trace 池为空时提前退出--context 检查后才能判断是否值得生成痕迹。

1. **先跑 state precheck**
   - 用 `scripts/manage_state.py precheck`
   - 若返回 disabled / cooldown active，则立即退出
   - **若只有 no_live_traces，继续执行**（进入步骤 4-5，尝试从上下文生成痕迹）

2. **再判断当前是否适合主动冒泡**
   - 确认当前没有 active task
   - 确认最近一个 heartbeat 周期内没有新的用户消息
   - 若明显属于安静/休息时段，默认更克制
   - **注意**：「更克制」不代表可以提前跳过后续步骤；走完 came_alive 全流程后再决定是否发送，是唯一正确路径

3. **定位真实用户会话**
   - 不要把 heartbeat 会话当成最终投递目标
   - 先通过 `sessions_list` 找到最近真实聊天会话（direct chat / 主会话）
   - 后续读取上下文、发送消息，都以那个真实会话为准

4. **读取上下文（近因 + 关联）**
   - 读取目标会话最近一小段消息即可，不做全量回溯
   - 默认看最近 3-8 条、最近一次 user ↔ assistant 往返、最近一个明确主题、最近一个尚有余味的点、当前主要语言、当前气氛
   - 额外挑 1-3 条**可联想的旧片段**（可来自昨天/前几天），用于“跨时间联想”而不是机械追溯
   - 优先近因，但不锁死近因：更近的片段默认权重更高；较旧片段只有在和当前点强关联时才会被重新点亮

5. **从上下文提取或更新 trace**
   - 只有确实有"没完全散掉"的点时，才写入 trace
   - 用 `scripts/manage_state.py upsert-trace` 更新 trace 池
   - 不要为了"保持活着"硬造 trace
   - **trace theme 必须是人类可理解的话题**：应该是"用户问的某个问题"、"某个有趣的观点"、"某个想补充的点"，而不是"delivery guard 改动"、"mark-sent 验证逻辑"这类实现层描述
   - 如果上下文里的"余味"本质是技术实现细节而非可分享的个人感想，不写入 trace

6. **让 state 选择当前最值得说的 trace（同时存入完整发射记录）**
   - 用 `scripts/manage_state.py choose-trace`，带上这次决策的完整上下文：
     ```bash
     python3 scripts/manage_state.py choose-trace \
       --state <state_path> \
       --quietness <当前安静指数> \
       --association-snippet "<近期片段1>" \
       --association-snippet "<近期片段2>" \
       --association-snippet "<可联想旧片段>" \
       --source-snippet "<最终保留给发射记录的片段1>" \
       --source-snippet "<最终保留给发射记录的片段2>" \
       --relation-mode "<grounded|random_unrelated>" \
       --concrete-topic "<这句话在说哪个具体话题/对象>" \
       --why-chosen "<为什么这个 trace 此刻值得说>"
     ```
   - `--association-snippet` 用来喂给选择器做联想打分（可混合近期片段 + 旧片段）
   - `--source-snippet` 用来沉淀发射记录（便于回溯这条后念来自哪里）
   - `--relation-mode` 仅允许两种：
     - `grounded`：这句后念要依托 source context，可引用真实共享片段
     - `random_unrelated`：允许与当前上下文轻微离题/无关，用于保留自然随机性
   - `--concrete-topic` 填写人类可读的具体话题，如"用户提到的某个工具/观点/决定"
   - `--why-chosen` 填写选择理由，如"这个点仍有补充冲动且新上下文重新点亮"
   - 选择器会对候选 trace 做**软加权**：`基础冲动 × 相对新近度 + 跨片段联想强度`；近的更容易被选中，旧的只有在强关联时才翻上来
   - 若没有 trace 超过当前表达阈值，则不发
   - **choose-trace 会在 state 里自动写入 `last_sent_emission`**，包含所有传入的上下文、关联命中与 `relation_mode`；后续 `mark-sent` 会在发送成功后补填 `sent_text` 和 `sent_at_ts`

7. **生成 candidate**
   - 依据：当前最强 trace + 最近很小一段上下文 + **目标用户的 SOUL/风格**（不是 agent 自己的 SOUL.md）+ 当前语言
   - **风格锚定**：生成的句子必须像目标用户自己会说的话，不要求每句都有显式判断或评价，允许陈述、疑问（反问）、轻微跑题等多种自然句式
   - **允许小概率离题随机性**：默认以 `grounded` 为主；在需要保留“人味随机”时，可小概率（建议约 10%-25%）使用 `random_unrelated`，让句子不必紧贴当前上下文。
   - **离题不等于伪记忆**：`random_unrelated` 模式里，句子可以无关当前话题，但**禁止**伪装成“我们刚聊过/你刚说过”的共享记忆；尤其禁止捏造未出现过的“你那句‘…’”。
   - **trace theme 引用精度**：选中的 trace theme 必须有足够上下文支撑，生成时须让读者（目标用户）能大致明白"这是在说哪件事"；允许轻微模糊，但禁止"刚才你说的那个点还挺有意思的"这类读者完全不知所指的句子
   - **第一可读性优先于残响感**：如果同一 trace 有两种说法——一个更"像残响/未完成"但读者初次读到时不知所云，另一个稍完整但立刻能理解——**选后者**。后念的价值在于"发自内心"，不在于"故意残缺"；宁可稍微完整，不要让读者第一遍读不懂
   - **结论去重 / 已知事实降权（以提示为主，不是硬规则）**：生成前先做两步心里检查：
     1) 这句是不是只在复读“对方已经知道的结论或事实”？
     2) 如果是，它有没有新增价值（新关联、新角度、当下情绪变化、未说尽的尾巴）？
     若两步都给不出新增价值，就把这句降权到不发送；不要靠代码硬拦，优先靠生成提示自我约束。
   - **长度服从当下冲动，不默认短句**：弱冲动可以很短；中等冲动一句自然展开；强冲动可到两三句或更长。优化目标是“此刻自然会这么说”，不是“越短越好”。
   - 原则：如果能自然地说出一句完整、可理解、像目标用户会说的话，就说；说不出来就不说
   - **禁止在候选句子里出现以下内容**（生成时主动回避，过不了质量门禁）：
     - 提及内部工具名字：delivery guard、mark-sent、trace、impulse、cooldown、heartbeat、活人感
     - 描述实现细节：验证消息、检查、确认、技术、实现、机制
     - 描述发送时机：发之前、发送前、发送后
     - 以"这次 XXX 改得值/改动"开头的技术总结句式
     - 任何听起来像内部状态报告或技术 changelog 的话
     - **指代模糊**：凡包含"那个点"、"这个事"、"刚才那个"等指示性词且无上下文支撑的句子，都须能在生成时回溯到具体内容，否则不得发送
     - **伪共享记忆 / 伪引用**：凡出现"你那句"、"你刚才说过"、"我们之前聊过"这类共享记忆口吻，或引用引号内话语（如“…”/‘…’），都必须能在 `source_snippet` 中找到对应依据；找不到即判定为 fabricated memory，禁止发送
     - **泄露内部对象名**：凡涉及内部定时任务 / 搜索管线 / filter 步骤的对象（如 `scheduled_task_*`、`search_pipeline_*`、`filter_step_*`、原始 tag/label/ID 等），必须先翻译为用户视角可理解的描述，再写入候选句；禁止直接将内部对象名当作已共享的上下文信息使用
     - **过度完整/过度工整**：禁止结构上过于完美对称的句子（如"X，Y，Z"三段并列、"虽然X，但Y"过于对仗的对比句式、以"值得想想/值得研究"收尾的完整结论句）；后念应带有自然的不完整感——像是话说到一半又想起另一个点，而不是写好了一个完整答案；宁可轻微残缺，不要过度抛光
   - **生成示例指导**：后念应该是"我刚才想到……"、"对了那个……"、"其实我觉得……"这类自然的个人感想，而不是"这次 delivery guard 改得值"这种工程进度汇报。风格应接近目标用户的自然说话感，不强制每句都有"我觉得/认为/判断"

7b. **防重复检查（anti-repeat）**
   - 在候选句子进入质量门禁之前，先用 `manage_state.py check-repeat` 检查是否与最近发送内容过于相似
   - 调用方式：
     ```bash
     python3 scripts/manage_state.py check-repeat \
       --state /Users/zhangyu/.openclaw/workspace/memory/openclaw_came_alive_state.json \
       --candidate-text "刚生成的候选句子" \
       --theme "<当前 trace theme>"
     ```
   - 若返回 `"repeat": true`，**不得发送**，整个流程以静默退出（不发消息，不 mark-sent）
   - 若返回 `"repeat": false`，继续进入步骤 8（质量门禁）
   - 防重复逻辑：相同 theme 且文字重合度 ≥ 60%（短句用 40%）；相同 theme 且完全相同句子（任何长度）；追踪最近 5 条发送记录


8. **过轻门禁**
   - 用 `scripts/quality_gate.py` 做轻门禁（废话淘汰 + 伪共享记忆防护）
   - 质量门禁调用时显式带上关系模式与可用 source：
     ```bash
     python3 scripts/quality_gate.py "<candidate>" \
       --relation-mode "<grounded|random_unrelated>" \
       --source-snippet "<source片段1>" \
       --source-snippet "<source片段2>"
     ```
   - `random_unrelated` 下若出现“你那句/你刚才说过/我们聊过”或引号引用，会被直接拦截
   - 不做多层机械审核
   - 保留表达自由，只消灭废话

9. **显式投递到真实用户会话（必须用 deliver.py）**
   - **必须**通过 `scripts/deliver.py` 发送，这条是代码级强制，不是可选项：
     ```bash
     python3 scripts/deliver.py \
       --text "生成好的候选句子" \
       --chat-id <目标 chat_id（来自 sessions_list 或已知用户 Telegram ID）> \
       --bot-token <Telegram bot token（来自 openclaw.json channels.telegram.botToken）> \
       --state /Users/zhangyu/.openclaw/workspace/memory/openclaw_came_alive_state.json
     ```
   - `deliver.py` 会：
     1. 调用 Telegram `sendMessage` API
     2. 检查返回的 `message_id`（无 message_id → mark-failed，不 mark-sent）
     3. 用 `getMessage` 轮询验证消息已进入目标会话（最多 3 次，1s/2s/3s 间隔）
     4. **只有 sendMessage 成功才 mark-sent**；失败（网络、token、权限等）→ mark-failed
   - **禁止**绕过 deliver.py 直接调用 `message(action=send)` 或 `sessions_send` 来投递 came_alive 消息
   - 如果 deliver.py 因任何原因不可用，整个流程应以 mark-failed 退出，不应手动 mark-sent

10. **成功/失败后更新 state**
    - **mark-sent 由 deliver.py 在发送成功后自动调用，禁止单独再调用**
    - 如果 deliver.py 失败，其内部已调用 mark-failed，不需要再处理
    - inspect 可查看最终状态：`scripts/manage_state.py inspect --state <state_path>`

## trace 写入原则

只有在最近对话里确实出现"余味"时才写入 trace。

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
- 只是为了"保持活着"硬记一笔

## 后念应当是什么

后念应当是一个自然冒出的表达（可一句，也可更长）：
- 来自近期对话残留信号的自然念头
- 符合 agent 本身风格
- 长度服从当下冲动（短促/展开都可以）
- 不要求回复
- 不依赖"下半句稍后再说"
- **带有自然的不完整感**：像话说到一半被勾起另一个点，或像没来得及整理清楚就冒出来的那种感觉；不要太像"写完了一个完整答案"，宁可轻微残缺或不对称，也不要过度抛光

允许的类型：
1. **补充型**：刚才某个点，后来又想到一个补充
2. **修正型**：刚才某个判断，后来觉得要修一下
3. **延伸型**：刚才的话题里还有一个自然延伸点
4. **轻微跑题型**：不完全接着刚才的话题，但看得出是 agent 自然联想到的完整想法
5. **随机离题型（低概率）**：允许偶尔和当前上下文无直接关系的念头（`random_unrelated`），但必须是当下自发想法，且不能伪装成“之前共同说过/聊过”的记忆

## 轻门禁：只做废话淘汰

命中任一项都**不得发送**：

- 纯语气词
- 半截话
- 故作神秘
- 钓对方追问
- 完全脱离上下文且不可理解
- 伪共享记忆（把未出现过的对话/引语说成“你刚说过/我们聊过”）
- 明显像模板句库
- 明显保留旧 canned 风味的句子

原则：
**保留表达自由，只消灭废话。**

## 语言与风格

- **语言**：跟随当前目标会话的主要语言，不强制中文
- **视角**：以 agent 自己的角度说，不模仿用户
- **风格**：符合 `SOUL.md`，优先自然、克制、具体
- **长度**：可短可长，跟当下冲动和语气走；短句和长句都可以，关键是像“那一刻自然会说出来”的版本，而不是为了简短去压扁内容

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
