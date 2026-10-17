# 单方牌库揭示与原费用结果

JAIL_379尖塔保安复用完整物理区域查询、原本地费用和非Spell随机分配伤害。完整原行和严格双语主面见[内容包](../data/cards/native-revealed-deck-spell-v1.json)。实际验收和下一项仅维护在原两份台账，不由一个代表认证正式标准卡池或国服规则。

`RevealRandomDeckCard(player_id, kind=CardType.SPELL, source_id=None, on_result=None, target_id=None)`仅接受真实随从/法术范围。有回调时需要原物理来源和已注册行为；target只供回调使用。完整本人DECK候选经zone_candidates核对，每张物理牌一个权重，同名副本不合并，先核全部本地费用再进行一次抽选。空池不消费RNG；不访问对方候选、不移动/抽取/洗牌，不支付或消费费用用途。

`deck_reveal_result(ctx.event)`返回不可变DeckRevealResult，其中选中牌复用既有JoustCard物理引用/本地费用材料，但不执行Joust或伪造另一方比较。费用沿已有local_cost，不把牌库对象伪装成手牌报价。本次结果保持原物理引用、卡面、owner、zone_epoch及原费用；后来抽走、转移或改费不重判接受的数值门槛，也不重新抽样。

回调继续由公共解释器执行。原事件、原玩家及其捕获状态中的实际牌库对象/费用须一致；恢复时拒绝未知/未来材料、损坏事件或已被改写的原上下文。完整存档和回放保留原结果及全局随机状态，异常沿原事务回滚。这里的关联校验用于拒绝内部不一致，不为任意重写完整未签名存档提供来源认证。

公开`deck_card_revealed.deck_reveal`仅包含类型、选中卡面、玩家及原费用，空结果为card=None。它没有牌库位置、实体/连续驻留编号、候选列表或随机状态；target始终为空。揭示不向Knowledge安装实体记忆，后来抽到的隐藏手牌不会因此自动被对手追踪。旧手牌展示与双方Joust继续各用自己的公开协议。

尖塔保安的原费用至少5时，交给RandomSplitDamage的既有NON_SPELL_PROFILE：5个单位、MINION_ABILITY、当前敌方随从范围，排除双方英雄，不接受Spell Damage增量；死亡、下一单位候选、护盾/吸血等继续由原伤害层处理。重复战吼各自揭示，间接实体仍使用其真实战吼身份，不造手牌付款。

本增量仅新增一个Effect，没有新GameState、实体或能力字段，payload类型清单保持。core442/schema360拒绝旧1～359；新公开事件形状使观察更新到92，命令12/replay1保持，默认代表定义和指纹保持。牌库本地费用、无洗牌政策、揭示/反应/奖励精确窗口及空揭示的可见性均属明确的本地政策，待国服校准；M0正式池、全部可达及阶段发布验收独立开放。
