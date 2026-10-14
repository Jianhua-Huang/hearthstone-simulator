# 永久法力水晶阈值的固有费用条件

实际执行、验收和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

`IntrinsicCostSpec(set_to=0, condition='permanent_mana_at_least', mana_crystals=7, history_profile_id='mana.permanent-crystals-v1')`在原固有费用层表达沼泽射线的七水晶免费条件。只允许一个普通物理法术的固定设费条件，不叠加其他固有公式或创建新卡面。未知条件、缺阈值和非法类型明确拒绝。

`PermanentManaMatch(player_id, turn, action, maximum, threshold)`冻结实际付款者报价时的永久最大水晶数；`matched`由两数比较派生。可用法力、临时法力及水晶是否已用不替代永久最大数。这沿用已有渴求/等级机制的资源依据；精确国服边界仍待校准。

条件先于局部费用附魔和外部费用操作。原窗口校验重新捕获真实状态；紧凑历史重算使用保存的原资源数，允许以后合法增减水晶，不改写已接受金额，也不认证未签名存档来源。原费用使用收据保留同一个条件，并与手牌提交证明比较，不能只保留金额而删去原条件。

支付、主体、选择、失败回滚、恢复、回放与玩家信息继续使用原解释器。玩家只见最终费用；原条件和付款证明不进入玩家观察。没有新增State/Entity/Player字段、账户、计数器或费用执行器。

[完整本地raw/pin](../data/support/mana-threshold-cost-basics.json)只接BT_134沼泽射线必要隔离代表，3费对随从造成3点法术伤害。它不是正式完整池或国服实测依据，不批量接其他卡牌或拓展组合。

新增声明字段、冻结条件类型和费用收据字段使当前格式为prototype-v291/core-effects-v288/schema255；旧1～254需要原引擎，没有隐式迁移。观察84/命令12/replay1保持。当前增量仍以两台账实际终态为准。
