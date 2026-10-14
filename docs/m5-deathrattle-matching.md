# M5-13d-02m-01-B2-03：亡语接收对象与持续来源条件

本文规定本批公共接口及一致性边界。实施位置与实际测试证据只维护在[项目状态](project-status.md)和[机制工作清单](mechanism-backlog.md)。R-154为本地原型政策，仍需国服校准；本契约不能证明正式卡池或亡语整族已覆盖。

## 接收对象、接受窗口与逐项计划

`DeathrattleRecipient(carrier_id, card_id, kind)`表示实际承载本组亡语的物理实体及原接受卡面，不是亡语声明者、授予者、组件或触发者。它是纯查询操作数；持久事实复用既有`DeathrattleCapture`三字段，不增加第二份接收对象账本。

自然入口绑定实际`DeathRecord`，在同批死亡全部移出后的既有窗口读取来源；武器替换仍在新武器安装后的原窗口接受旧武器亡语。主动入口绑定原live载体及其完整有效能力集。两种窗口保持各自的原局面，不能合并为致死前窗口。每项能力的首次回调保留原接受视图，额外重复和后续主动轮次读取新局面，但不重算已接受计划。

`DeathrattleRepeatSpec`末尾增加`match=None`，其`DeathrattleRepeatMatchSpec`包含`recipient_metadata`和`source_eligibility`。种族过滤使用`DeathrattleRecipientMetadataFilter(basis='accepted_carrier_face_printed', tribes_any=())`，取原接受卡面印刷种族；非空种族对武器/地标为false，需要的未知元数据明确拒绝。

匹配相交原有kind、物理self、逐能力printed/granted origin和种族。每项payload保存全部匹配来源并取max，强弱及同值来源均保留。主动`trigger_count`与来源重复次数分开，排列保持trigger→ability→repeat。无匹配来源仍为一次且保留整组原证明；没有亡语能力不创建空batch。

计划接口为`capture_plan(state, registry, player_id, recipient, ability, death=None)`及`validate_plan(state, registry, plan, player_id, turn, recipient, ability, death=None)`。原接受视图重新查询完整计划；紧凑历史仅校验冻结种族、声明及身份，不重判后来的条件见证。

## live来源、死亡self与玩家来源

外部来源仍限活跃、未消费、非doomed且正生命的场上随从。来源完整声明/profile先验证，再完整查询条件，最后与其他匹配项相交；其他项为false不能隐藏未知profile或所需元数据。`exclude_carrier`排除实际次数来源的物理ID。

既有`qualifying_repeat_witnesses`继续要求所属玩家的live BOARD随从。新`qualifying_deathrattle_self_witnesses`独立认证原state内的DeathRecord、冻结MINION/BOARD卡面、已经移出的实体，以及死亡记录中的未消费self声明和完全相同条件，再读取同一原post-removal board。不可放宽live wrapper以接纳死亡来源。同批已离场者不能作见证；主动live self在普通presence政策下可作自身见证。

所有DR次数来源载体限MINION，包括冻结DeathRecord里的friendly但未匹配声明；武器/地标作为接收者合法不意味着它们可以安装次数来源。注册、动态授予、恢复及冻结记录统一执行完整声明/profile校验，动态授予不能先因目标stale而跳过校验。

PlayerEffect只允许friendly接收匹配，不能使用物理self或source_eligibility；donor身份只是provenance。其既有owner时钟保持，不按payload、trigger或repeat消费次数。一个玩家效果可合法同时声明DR与EndTurn，并保留各spec_index。静态owner、规格和来源身份不变，剩余期限只允许既有时钟推进或合法移除。

## 原证明、身份与后续接受

保留`hs_sim.engine.deathrattles.FinishDeathrattleBatch`的原字段和qualified wire类型。完整能力集、逐payload计划、预分配capture span、位置和唯一Finish贯穿整个批次。原DeathRecord/batch/capture前缀不可改写，执行进度仅单调前进；合法Rewind恢复整份对应状态和队列。

原与当前全局附件扫描必须先拒绝重复ID，不依赖会覆盖字典条目的旧inventory helper。绑定两方所有区域及inactive/consumed/false DR来源和源独立PlayerEffect。旧ID不能换family、物理载体或完整静态声明，消费只能单调变化；合法来源移除不要求它仍存在，合法转控不重判原owner或见证。

后续接受引用保存明确路径/阶段、typed family、ID和已有完整静态来源值；比较接受字段变化，不能仅查新增PlayRecord ID。同一已提交PlayRecord后来填入BC/Combo/Spell窗口也属于后接受。覆盖DR逐payload、BC/Combo根与批次、玩家政策收据、spell/card-spell、技能计划及EndTurnBatch的嵌套plans。只检查次数来源，不能把主体或grant provenance引用误当来源。来源转控后的新board接受允许新owner；物理carrier ID和完整Ability保持，PlayerEffect的owner保持不变。已移除来源留下的后接受证据仍受身份校验。

共享queue validator同时用于waiting边界、批次关闭和terminal丢队列之前。terminal检查原playing接受证明、完整span和位置，允许尚未执行主体，不先对未标中断的terminal state运行完整稳定不变量。原透明控制工作仍计工程预算，不新增玩法事件、RNG操作、死亡或光环检查点。

英雄技能的`FinishHeroPower.context`是独立全根原接受窗，使用`record_id`绑定；不能因仍有或已无`InvokeHeroPowerPayload`而跳过此根窗口。它复用外来原窗的waiting、实际pop前及terminal检查。较早的技能根可以自然先于亡语组接受，按既有历史身份判断其先后，不要求较早根的原状态包含后来才创建的组。默认公共入口的成功技能仍有有效on_use主体；成功空主体的既有测试扩展与公共动态能力交付范围须分别登记，不能用非法active卡定义声称可达。

## 验证与保留范围

验证需覆盖两种卡面窗口、逐payload origin/max、同批移除、self/another/presence、未知元数据、玩家多规格/时钟、全false/全局ID/后接受及已删除来源、所有waiting独立恢复/clone/replay、terminal裁剪、事务/预算/异常/两类Rewind、武器/地标/磁力/星舰和玩家隔离。设计场景不算执行通过，实际结果见两份台账。

本批不扩真实卡池。EDR_531e的文本不能认证父卡动态交付；其余族、费用/主体/周期/+1/CAST、动态主体交付、固定多轮producer、同动作付费嵌套及M0正式版本/完整池、M6国服校准、M7批量接卡继续按长期路线保留。
