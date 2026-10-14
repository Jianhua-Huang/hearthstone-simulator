# 独立存储卡销毁与本牌主体

本增量补上真实手牌销毁及已离区卡牌的原生“被摧毁时”主体，复用区域与解释器，不增加第二套触发、死亡或施法执行器。实际执行和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

```python
DestroyStoredCard(card_reference, source_id=None, reveal=True, on_destroy=())
DestroyDeckCard(card_reference, source_id=None, reveal=True, on_destroy=())
CardDefinition(..., on_destroyed="registered.behavior")
```

`DestroyStoredCard`只接受捕获的HAND/DECK物理卡；原有`DestroyDeckCard`保持仅DECK的输入限制，两者共用处理器。执行前检查来源、完整允许列表续接和原引用。实体控制者、区域、当前卡面或epoch改变后，旧请求跳过；离区返回亦失效。未知定义或来源明确报错，整个动作回滚。

成功销毁保留实体ID、原owner和当前controller，将原实体移入墓地并推进epoch。它自身不产生弃牌、抽牌、施法、场上死亡、亡语、复生、残骸或星舰材料。主体随后执行Draw等正常效果时，这些效果仍产生各自正常事实。普通Destroy、DiscardCard和RemoveFromGame保持原有含义。

成功事件分别为`card_destroyed_in_hand`和`card_destroyed_in_deck`。私有封套保存原五字段CardReference、owner、原牌型、实际turn与reveal；Event保存实际sequence/action和来源。`destruction_result(event)`重建冻结的`CardDestructionRecord`；可信规则回调通过`context.destruction`读取，玩家接口不输出该收据。

`on_destroyed`安装一份普通印刷能力，使用现有附件ID、当前复制、印刷重建和变形生命周期；不提供动态授予入口。原生主体在成功移区和发布时从离区实体接受，保存独立RuleContext；主体执行者为该物理卡及其当时controller，不继承销毁者的cast/play/discard等根。当前复制沿原复制政策保留能力来源，执行者仍是复制后的实体，不能将来源溯源字段误当执行者ID。

队列顺序暂定为原事件监听、原生本牌主体、调用者`on_destroy`续接。已接受的主体保留原上下文；后续实际效果通过普通解释器使用实时状态。挂起恢复校验原卡面能力、独立上下文、移区后的原身份及实际事件；实时执行亦绑定原事件。完整快照和回放仍属全知内部数据，未签名存档的来源真实性不由这些结构校验认证。

`reveal=True`只公开被销毁目标，隐藏其他手牌/牌库候选和顺序；`False`只让controller记住牌面，对方可见移除事件和手牌/牌库数量变化。新公开事件使观察版本升为player-view-v82，命令12/replay1保持。内核prototype-v280/core-effects-v274、schema246拒绝旧1～245；未使用on_destroyed的注册表指纹保持。

必要代表仅[固定本地WW_441锅炉燃料](../data/support/stored-destruction-basics.json)的使用、弃掉和显式存储销毁三入口，统一Draw(2)。SC_408完整条件/最低费选择与WW_044t伤害主体未接入，AT_022原文作为弃牌不等于销毁的负证据。[官方Ghost索引](https://hearthstone.blizzard.com/en-us/cards/112912-ghost?set=the-great-dark-beyond)支持存在手牌销毁；[28.2.3历史公告](https://hearthstone.blizzard.com/en-us/news/24033779)支持淤泥桶包含被摧毁触发，不证明当前国服精确窗口。

后续[B153溢出契约](m3-native-overflow-body.md)已接通原存储迁移、新建、暂存取回和墓地材料失败交付的本牌主体；保留原card_burned通知并保存实际前态，不由同名通知自动推定。没有已支持原始profile的native burn仍明确报错回滚，场上满手回手沿独立普通死亡。准确原生溢出窗口、全部来源和国服语义仍需核对，不以锅炉燃料实验宣称整族或全生命周期官方一致。

[专项](../tests/test_stored_destruction_basics.py)覆盖物理身份、HAND/DECK和五牌型、来源/控制归属、三必要入口、重复和失效引用、复制/变形、两类等待恢复、动作/选择回滚、严格声明/事件及玩家隔离。实际通过数量与失败记录见[本批证据](../outputs/stored-destruction-basics-20261012/verification.json)。其他旧检查及阶段全量未执行，不从专项或代表定义数量推定最新正式版本完整支持。
