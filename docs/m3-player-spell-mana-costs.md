# 本局用于法术的实际法力消耗：独立费用输入

现行原法术投入量在下述付款基础上，另合并[直接法力消耗](m2-mana-consumption.md)的完整不可变前缀：来源SPELL且实际消耗者同原行动玩家的主体实际单位计入。消费与原付款各一次，0价手牌根自身贡献0但其主体可贡献实际量；没有手牌付款的自动/重复主体不增加付款部分，实际SpendMana仍可贡献。PlayerSpellManaCostFact追加consumption_rows与consumption_history_length，原付款历史和新资源历史分别冻结；恢复及后续法力增长不回写旧量。原有限付款契约保留，精确CN归属仍待校准。

实际执行、内部验证和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。本契约定义有限基础能力，不代表U53整族、正式卡池或国服规则已验收。

## 声明与原始依据

普通手牌随从声明`CardDefinition.player_spell_mana_cost=PlayerSpellManaCostSpec()`，默认None；profile固定为`cost.player-spell-mana-v1`。非普通随从、未知profile和同时声明其他数量公式明确拒绝。

仅隔离适配[TSC_829纳迦巨人完整本地记录](../data/support/player-spell-mana-cost-basics.json)，20费8/8；canonical pin为`1078263ea7525701589b668e95cfbd63f4ae1048d4cdefa5228f1b08d832398c`。生产代表包没有扩张。[官方卡牌库](https://hearthstone.blizzard.com/en-us/cards/71949-naga-giant)的搜索索引卡文与本地记录一致；实际打开只有JavaScript页面壳，不能作为精确当前国服执行时点的证据。

## 有限消耗口径

`player_spell_mana_costs.py`读取原`play_history`，仅本人、原类型SPELL、原支付账户MANA的已提交物理出牌根贡献法力消耗。数量取该根原`mana_before-mana_after`，并要求与原实际支付`cost`一致。使用原`submitted_cost`绑定付款人、物理来源、费用和账户；在内核中记录追加于`pay_quote`完成资源写入之后。并非对任意当前余额求差，也不从`mana_spent`事件或费用用途收据猜测支付。

同名卡的两个物理付款各自计入；一个原根只贡献一次。0费法术为真实出牌，但贡献0法力。卡牌获得前的消耗、此前回合的消耗均保留；临时法力同样是实际法力，后续恢复或获得法力不会抹掉原消耗。折扣和加费按原支付金额，不能拿印刷费用代替。

生命、护甲、尸体等替代账户不计入；随从、武器、地标、英雄及英雄技能消耗不是法术消耗。没有付款的自动施法和重复主体没有新增物理出牌根，不增加此数量。失败动作沿原事务回滚，不留付款根。

本地profile将已付款的反制根及等待选择、尚未完成的法术根计入，后来完成或中断不撤回原付款。精确反制、未结、特殊退款或特殊支付归属仍待M6国服校准；当前不会凭缺少正式证据虚构退款操作或额外来源。其他“本局施法次数”卡文沿自身既有profile，不能与法力投入数量互换。

## 公共报价与保存

金额为`max(0, base_cost-quantity)`，进入原固有阶段，在已有条件、本地附件和外部费用层之前。实际payer的物理、生成、玩家显示、合法操作、验证和付款共用原报价；纯查询不创建实体、分配ID、消耗RNG或修改印刷费用。没有新的玩家累计字段、实体缓存、事件、操作或第二套付款流程。

`PlayerSpellManaCostFact`冻结声明、实际payer、实体分配上界、完整`play_history_length`游标、有序`PlayerSpellManaCostRow`、数量及before/after。每行保存原root/source/player/card/kind/turn/action、原cost/payment、原法力两端、原hand_entry身份与获取回合。包含未计入行，所有原卡面都校验；未知非候选不能被零数量短路。

行必须是严格类型的不可变值；连续ID、严格递增动作、非递减回合、原分配上界、账户扣款、获取时钟、原完整游标和数量金额必须一致。`IntrinsicCostStageFact.player_spell_mana`为必需显式叶，值为事实或None，绑定payer/base/原历史游标和时点。物理报价来源必须早于原分配上界。

实际原窗口验证重取原支付输入；紧凑历史比较已保留的完整原物理付款前缀，允许后续新增支付及原主体完成，不按今天的累计量重价。原付款证明和快照验证继续负责完整资源与结算收据；此数量读取只检查所需原身份和付款结构，不重新执行主体、恢复过去的完整局面或递归调用报价。紧凑前缀不提供未签名存档的来源认证。

选择中断、恢复、克隆、回放和异常回滚沿共享解释器。复制、沉默及回手之后按当前普通印刷身份重新报价；局内付款历史属于玩家，不跟卡牌附件走。特殊复制/来源仍按真实卡需求后置。玩家仅看到最终费用，原历史前缀与对手隐藏手牌不交给玩家。

## 协议与边界

本项引入版本为`prototype-v187 / core-effects-v181 / schema176`，拒绝旧1～175；观察74、命令11、replay1保持。注册表新增默认`player_spell_mana_cost=None`，完整保存新增显式`player_spell_mana`，指纹和schema随之改变，不静默补旧字段。未知policy或wire叶明确拒绝。

这是“按原法术实际法力支付减费”的一个有限输入。任意公式、过载累计、死亡数量、种族召唤等其他输入不会自动获得支持；费用层顺序、特殊复制、特殊账户来源、完整正式池及国服精确时点仍开放。当前独立基础目标不开发跨机制组合矩阵。

当前共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[死亡随从次数费用](m3-minion-death-costs.md)复用原死亡记录/查询，不改变本契约的原付款归属；精确CN仍待校准。
