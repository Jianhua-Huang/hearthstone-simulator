# 原物理招募的成功主体续接

共享CardSummonDelivery的一次续接字段也支持[原归因战场复制](m3-copy-followups-hidden-pairs.md)。招募与复制按各自原材料、控制指令及事件独立验收，不能相互借用followup_started。这里的物理招募入口与既有行为保持。

血色招募者JAIL_516从牌库召唤两个费用不超过2的随从并授予突袭；着魔的动物术师DINO_131亡语招募野兽并授予吸血；摩拉格JAIL_906招募恶魔并授予召唤摩拉格的亡语。完整固定卡面保存在[配方](../data/cards/recruit-followup-effects-v1.json)，不能以招募已实现代替后续主体。执行结果、差异与下一项仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 有限入口与原接受事实

`SummonFromZone(..., cause=SummonCause.capture(context), on_summon=behavior_id)`在原区域召唤入口增加可选成功续接。原`SummonStoredCard`同样承接该声明；没有cause时拒绝非空续接，不从最近的牌库/场面/历史猜执行者。空池和满场仍校验已声明回调，未知行为明确失败。

原producer按当前印刷查询选择物理候选；选中的`SummonStoredCard`、`RecruitEntryMaterial.on_summon`和原父请求保持同一声明。`CardSummonDelivery`保留实际进入的实体、controller、卡面、zone_epoch与entered_order，并增加布尔`followup_started`。额外数量复制各有自己的delivery，失败场位没有回调；不对巨型附属物或反应中无关生成体执行此声明。

## 单次续接与当前内部窗口

成功主体完成入场、巨型扩展及入场反应后，原队列执行`ContinueRecruitedMinion(root_id, index, beneficiary, behavior_id)`。该工作从原delivery构造MinionReference，核对原选中材料和行为，先将单次接受标记置为true并保存私有接受事件，再调用原注册行为。来源是原cause中的卡牌实体，目标是本delivery，执行玩家是原接收者。

死亡、休眠、变形、转控、回手或离场再入场导致原存活引用失效时，续接记为已处理并跳过；不重新寻找同名牌或最后场位。原回调自己产生的普通选择沿既有解释器保存，接受标记保留，恢复不会重新领取回调。精确授予发生于入场反应之后，以及失效主体的跳过政策，均是明确内部规则，仍须国服校准。

每个实际成功delivery处理续接后才推进下一个额外副本；该原物理招募根完成所有额外副本后，父producer才重新查询下一张牌。空池、满场、未知元数据、实际RNG权重和来源生命周期保持原规则，没有新的招募选择器或数量账本。

## 保存与边界校验

活跃队列必须按原进度保留一次待处理续接、需要时的下一delivery以及Finish。缺失、重复、错序、借用另一实体/进入生命周期/行为或向玩家选择分支注入控制工作均拒绝。完成根不能仍欠成功delivery的续接。单次接受事件和各delivery布尔标记必须逐项对应；它们只证明内部一致性，不认证未签名存档的外部来源。

请求、材料、实际delivery和继续帧使用公共typed codec；选择前完整边界同时绑定原历史和原控制尾。失败动作及失败选择沿原事务回滚。私有候选、接受事件、followup_started、请求行为和继续工作不提供给玩家，公开授予仍沿原关键词/亡语事件投影。

保存布局的实际delivery新增字段，因此schema267拒绝旧1～266；core-effects-v310保护新的指令与接受语义。没有新GameState/Player顶层字段，观察85、命令12、replay1及prototype-v302保持。旧引擎与历史证据保留，不给旧记录自动补false后认证为当前数据。

本入口限于已有原物理招募主体系；任意生成池、复活或其他来源自己的后续机制继续沿各自契约，不预先扩展为所有来源的组合矩阵。真实卡不能表达时再确定最小需求。
