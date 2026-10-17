# 本局实际过载水晶量：独立历史与费用输入

后续真实回溯来源复用有效事件时间线退役舍弃尝试的诊断过载；原正增量与事件对仍严格核对，见[预算召唤及回溯契约](m3-mana-worth-summons.md)。下文原始声明和历史版本说明保持。

实际执行、内部验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本契约定义一项基础资源历史与一个有限费用输入，不代表U53整族、正式池或国服规则已验收。

## 真实增量与公共历史

原[资源模块](../hs_sim/engine/resources.py)继续执行`Overload`、改变待锁账户，并依次发布原`mana_changed`和`overload_added`。本项不改变资源计算或事件数据；在后一个事件构造完成、普通监听者捕获之前，由私有提交入口追加不可变`OverloadRecord`。只有已实际执行的正增量形成记录，不能仅发送同名事件冒充过载。

新增`GameState.overload_history`与`next_overload_id`，没有玩家累计缓存。每行保存连续ID、实际受影响玩家、原turn/action、原owner_turn_id、两个原事件序号、实际amount和pending_before/after。原水晶量满足`pending_after-pending_before=amount>0`；同一回合或动作可以有多次实际执行，按水晶量相加，不按法术或事件个数计量。

`overload_history.py`复用原owner回合区间，校验原回合/动作及事件游标范围。正增量事件必须与原较早的`mana_changed(operation='Overload')`配对，payer/action/owed一致；恢复时核对完整已提交增量事件目录和全部原事件对。事件玩家与原pending两端必须为严格int，布尔或浮点即使数值相等也拒绝。第一回合之前没有owner区间时保留显式0身份，不能借用后来区间。后续完成或关闭原回合不改写记录。

`overloaded_crystals(state, player_id)`是纯引擎查询，只返回该玩家原amount之和；不分配ID、消费随机或改变账目。它不是将全知state提供给玩家的新接口。

初始化场景已有的待锁或已锁量不构造虚假历史；后续实际增加2时只记2，不把原8记成10。回合转锁、解锁、清除待锁、恢复/获得法力、改变水晶和0量过载都不增加历史，解锁也不抹去曾发生的过载。临时法力或当前法力容量不替代过载量；原资源执行允许的超容量过载仍按实际正增量保留。失败动作及待选后的异常沿原事务回滚。

本地政策在`overload_added`发布处提交，所以原`mana_changed`捕获视图尚未包含本次增量，后一个事件的视图包含它；两者沿原解释器保存各自视图。精确国服可见时点与特殊来源仍待M6校准，本项不提前改变原事件顺序。

## 有限费用声明

普通手牌随从声明`CardDefinition.player_overload_cost=PlayerOverloadCostSpec()`，默认None；profile固定`cost.player-overload-v1`。实际payer本局每过载一水晶减一费，金额`max(0, base_cost-quantity)`；对手过载不增加本人的量，获取卡牌之前和此前回合的历史保留。未知profile、非普通随从和同时声明其他数量公式明确拒绝。

必要适配仅ICC_090雪怒巨人11费8/8与原EX1_238闪电箭，后者复用原过载/伤害入口，伤害明确为SPELL。CORE_ICC_090只作为独立原始证据，不另接执行卡面。[三条完整本地记录](../data/support/player-overload-cost-basics.json)canonical pin为`fec42fdcb534241f1595ac609ee409f0180c5837ed2ad6ff5c07714ec2bad369`；原粗体标签完整保留。生产代表包范围不扩大，本地记录不证明精确当前国服规则。

反制后没有实际执行过载的牌不贡献水晶量；已经执行且等待选择的原增量保留。这与已支付的法术费用或原出牌次数是不同输入，不能相互代替。

## 共享报价、原依据与恢复

`player_overload_costs.py`读取已有真实过载历史，数量进入原固有阶段，在原条件、本地附件和外部费用层前。物理、生成、玩家显示、合法操作和付款共用原报价；不写实体费用缓存，也不重演法术或资源主体。

`PlayerOverloadCostFact`直接冻结完整有序`OverloadRecord`元组，包含对手等未计入记录，保存原payer/turn/action、实体及过载分配上界、完整游标、数量和before/after。`IntrinsicCostStageFact.player_overload`为必需显式叶，绑定原payer/base和原回合/动作边界；物理来源不能借未来分配ID。即使总数量或价格相同，也不能删改原记录、替换原事件、换成别的pending两端或重写原窗口。

完整原窗口重取真实输入；紧凑历史绑定保留的完整原前缀，允许后来新增过载或推进回合，原价格按冻结量计算。原付款、选择、保存和回放管线继续负责整体结算。记录与事件的一致性检查不提供未签名存档的来源认证。

普通印刷复制、沉默和回手后，卡面仍按当前玩家本局历史报价；历史属于对局中的玩家，没有安装在被定价随从上。特殊复制或来源按真实卡需求后置。选择恢复、clone、回放和异常回滚复用原解释器。玩家日志保持只公开玩家及正整数增量；原两端账户、事件关联、完整内部历史、付款证明和对手隐藏手牌不交给玩家。

## 协议与限制

本项引入版本`prototype-v189 / core-effects-v183 / schema178`，拒绝旧1～177；观察74、命令11、replay1保持。注册表新增默认`player_overload_cost=None`，完整保存新增过载历史、分配游标与显式`player_overload`；指纹和schema随之变化，不静默补旧字段。没有新Entity/Player字段、玩法事件或外部动作。

这是实际过载水晶量的基础历史和一个有限减费输入。精确发布窗口、费用层顺序、特殊来源/复制、正式池及国服校准仍开放；其他资源累计量、任意公式或跨机制组合不会自动得到支持。

当前共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[本局原职业出牌数量](m3-player-played-class-costs.md)复用原手牌根与完整冻结卡面，不改变本契约实际过载量、事件顺序或原提交窗口；精确CN仍待校准。
