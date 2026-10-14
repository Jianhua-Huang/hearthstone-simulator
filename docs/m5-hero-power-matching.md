# M5-13d-02m-01-B2-04：英雄技能持续来源条件与完整根证明

2026-10-04，内核 `prototype-v109` / `core-effects-v109`，snapshot schema106。已内部验收，证据见[验收收据](../outputs/v114-verification.json)，未国服校准；R-155 是依赖 R-142/R-151 的本地组合契约。实际执行结果与下一项只见[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。观察54、命令7、外层replay1与代表内容64保持，无新增真实卡。

## 声明与实际对象

`HeroPowerRepeatSpec(repetitions=2, match=None)` 在末尾增加独立的 `HeroPowerRepeatMatchSpec(source_eligibility=None)`。条件复用 `RepeatSourceEligibility` 与注册表的不可变见证资格 profile：

```python
HeroPowerRepeatSpec(3, HeroPowerRepeatMatchSpec(RepeatSourceEligibility(
    'repeat.witness.controlled', tribes_any=('beast',), exclude_carrier=True)))
```

来源仍是实际场上随从的 `hero_power_repeat` 附件，要求活跃、存活、未消费；条件中的 another 排除这个物理载体 ID。见证按 profile 的休眠、建造星舰、doomed 和正生命政策以及当前卡面印刷种族查询，完整遍历不能用首个命中隐藏后项必需元数据缺失。见证资格不改变来源贡献资格。

接收对象已有 `HeroPowerRecord.source_id/card_id/player_id`，指向实际选中的已安装技能实体，包括额外安装的技能；不是玩家英雄、技能目标、触发者或来源随从。本族没有接收种族或物理 self 的证据，不额外保存重复的接收对象。没有开放玩家效果来源、费用依据、每主体匹配或额外一次的加法政策。

全部私有声明必须显式包含 match 或 null。注册、授予、当前及死亡附件、原上下文、FrameCodec 和历史计划均校验完整声明与已注册 profile。授予在 stale 退出前验证声明；未知条件不得静默成为无条件。schema1～105 要求对应原引擎，没有隐式补字段。

## 单一接受窗与执行

成功根在原支付及手动用途扣减后、started 事件前，冻结全部 `on_use` 与匹配来源，次数取完整来源的最大设值；全 false 为明确单位计划。失败根不查询来源条件。一次手动根仍只支付和扣用途一次，effect 根不占手动用途。

接受后来源或见证的沉默、变形、转控、死亡、移除和新增不改变当前计划。每个实际新根重新捕获；额外主体及保留结果继续读取新的执行局面，但不重新接受次数或能力。默认 active 技能必须声明非空 `on_use`；成功空或多主体结构由既有自定义安装 dispatcher 验证，与默认公共可达范围分开。

支付的 `mana_spent` 普通事件上下文可能仍看到 append 后的默认 root，实际反应在 begin 返回后才运行；它不是接受证明。不能按 action 相同、record 存在或 payload 非空猜测先后。手动 bare 原证明精确核对两个用途为 before+1，effect 原证明为 before；后续 refresh/回合重置不受这个原窗断言约束。

## 原证明、来源身份与结束边界

沿用 `FinishHeroPower` 的完整 bare context。计划接受时间不变；该 context 在同步 `payload()` 安装普通 batch/captures 或 retained outcome 后保存，此时开始反应与主体尚未执行。这个既有完成证明因此同时绑定完整原根及其已安装执行身份，防止整组删除 retained 记录后降级成普通根；不重捕获计划，不新增事件、玩法检查点或用途。

共享 `repeat_provenance` 先检查原始全局附件 ID，再建立目录，并保存跨族收据的路径、族、物理载体、完整值和玩家/规格位置。HP 原证明绑定所有原来源，包括 false 和非贡献附件；允许合法移除、整载体转控、新 ID 分配及单调消费，拒绝同 ID 改完整声明、搬到另一载体或冒用其他族。死亡记录中的 HP 附件只参与历史身份核对，不能成为已离场的 live 贡献来源。

原 HP 根、完整 payload batch/captures、死亡和 retained outcome 前缀保持身份与单调执行进度。后接受的跨族引用必须与原完整附件相容，玩家效果的存续实例及多次亡语捕获保持单调 owner clock。历史仅检查紧凑声明和身份，不用当前见证重判过去。

共享 typed 原窗目录区分 HP root 与 payload batch，尤其区分保留回溯后来安装的 batch。只有外族的完整接受标记已存在于本根原状态且值相容，才允许较早窗口缺少本根。法术两原窗本来在其收据安装前保存，因此从各自原状态纯重算收据；结束整批原证明也在batch安装前保存，其完整marker取typed完成控制件上的batch。普通监听上下文不参加这个分类。

等待选择、实际 popped 控制窗口、根 closing 和 terminal 清队列前均进行只读绑定。完整历史及 ordinary/retained 控制跨度在中断前检查，不能依赖清队列后的不变量补救。`FinishHeroPower` 继续是普通效果，保留原完成事件及玩法检查点；主体 Invoke/Finish 继续是透明控制工作。公共解释器预算、事务回滚、快照、克隆和回放保持。

这是未签名保存文件的结构与关系校验，不提供外部来源认证。活动全状态、来源条件、见证与内部 ID 不进入玩家 DTO。

## 验收范围与保留工作

必要合成验证覆盖 profile、another、完整未知元数据、全 false/max、生命周期、manual/effect/additional、成功空/多主体、自定义及默认入口边界、嵌套、普通/保留回溯、完整来源篡改、closing/terminal、所有 waiting 恢复、独立注册表回放和玩家隔离。场景准备、测试执行和最终验收分别记录，设计不算通过。

其他重复族/轴、动态主体交付、固定多轮 producer、M0 正式补丁与合法卡池、M6 国服校准、M7 批量卡牌及完整目标仍未完成。
