# 欧斯克的下个法术：同一原程序的费用与法伤

`TLC_452t2`是欧斯克的真实6费6/6战吼形态：下个法术减3费并具有法术伤害+3。该形态与原根的完整中英主面分别核验，主面数值也符合[33.0.3调整](https://news.blizzard.com/en-us/article/24224212/33-0-3-patch-notes)。本层仅接入这个必要分支，不注册尚未完成的`TLC_452`随机切换根，不把它建成主动泰坦按钮。

`PlayerEffectSpec(kind='next_spell_bonus', spell_damage=3, next_spell_cost_reduction=3)`是独立、无倒计时的原生程序。安装须对应真实已开始的原战吼；来源实体和原卡面归属分别保留，来源死亡或后续控制变化不会转移已给玩家的奖励。原`PlayerEffect.cost_modifier_id`绑定本人一项普通`CostModifier`；没有另加一份可独立漂移的减费。逻辑费用贡献允许原对手Aura的正向税与本人的负向奖励，反向所有权与完整原Spec分别校验。

付费手牌入口在原`prepare_play`冻结完整待用程序，普通报价/支付保持。共享`commit_play`把原程序及它的费用贡献一起移除；实际执行和纯支付投影调用相同写入。原`PlayRecord.next_spell_bonus_effects`保存原完整实例，原首次`SpellCastRecord`接过这份材料，出牌反应插入的自动施法不能抢走已保留的奖励。自动施法在取得合法目标后、开始通知前一次认领；无合法目标保留待用程序。零费用和非伤害法术仍按一次真实认领处理。

待用程序不向玩家提供常驻法术伤害。伤害及原随机分摊报价只读取当前实际CAST的已保留材料，旧`next_spell_damage`的当前回合期限、失败政策和专用字段保持。原新程序跨回合保留；当前本地政策为手牌已接受出牌即认领，包括后来被反制的出牌，重复施法仅首次实际CAST取得奖励。这些反制、自动施法接受窗与重复继承政策仍待当前国服M6，不把一致的内部测试当官方裁定。

原安装、实际付费/自动认领和显式移除有私有原材料证明，核实际战吼、玩家/来源、分配顺序和安装早于认领。活动程序、已认领记录及显式移除须完整覆盖原安装，不能裁掉整个待用程序或只留永久减费。快照、克隆、回放、错误操作回滚、等待恢复及玩家信息继续沿原管线；这些检查不认证未签名存档的来源。

只在原模型增加三个默认字段：`PlayerEffectSpec.next_spell_cost_reduction=0`、`PlayRecord.next_spell_bonus_effects=()`和`SpellCastRecord.next_spell_bonus_effects=()`；无新模型类、对局账户、效果类型或明确payload。旧Spec的零默认值不改变注册表指纹。协议core583/schema477、观察107、内容preview-v408，命令12/replay1保持。整卡手牌切换、两个其他缺失战吼及正式规则仍未完成；实际验收和下一项只在[项目状态](project-status.md)与[机制台账](mechanism-backlog.md)维护。
