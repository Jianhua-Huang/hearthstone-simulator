# 普通数值与关键词赐福的配方

本页保留历史七配方实验；当前正式十配方及特殊主体见[黑暗之赐公共接口](m3-dark-gifts.md)，实际结果以最新台账为准。

休憩饱足、梦境行者和鹰身人之爪分别要求+2/+2与扰魔、冲锋、圣盾与风怒。这些都是已有关键词和普通数值的创建配方，复用[原创建授予](m3-created-minion-grants.md)和[成对发现](m3-paired-discovery.md)，不需要新的机制模块。[国服资料片说明](https://hs.blizzard.cn/news/24179067/)列出这些真实结果。

实际验证、执行位置和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

| 真实描述 | 原声明 |
| --- | --- |
| EDR_100t1 休憩饱足 | `CreatedMinionGrant(attack=2, health=2, keywords=(Keyword.ELUSIVE,))` |
| EDR_100t6 梦境行者 | `CreatedMinionGrant(keywords=(Keyword.CHARGE,))` |
| EDR_100t13 鹰身人之爪 | `CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD, Keyword.WINDFURY))` |

不可变配方保留原名称与ID，由原发现流程采样、冻结预览、接受实际所选结果，再交给原`AddToHand`安装。扰魔沿原法术目标限制；普通攻击仍能命中。冲锋沿原攻击准备和次数规则，不额外付款或执行战吼。鹰身人之爪沿普通圣盾单次消费和风怒两次攻击上限；它不是承受三次伤害的特殊圣盾。

原创建身份、同名隔离、复制/重置、选择恢复、回放、随机与付款、事务以及玩家接口继续由原模块负责。本配方没有增加效果程序、通用授予接口、实体字段或跨机制组合。整个关键词后续需要的特殊主体不能因此默认为已实现。

[完整原行pin](../data/support/dark-gift-keyword-recipes.json)保留原33行与全部12个本地描述。独立受限实验包含七个可执行配方；其余五个描述仍保留且明确拒绝：抽两牌亡语、使用时召唤2/2复制、自身战吼两次、+4/+5置于牌库顶、承受三次伤害的圣盾。受限库存和实验来源不能冒充当前正式国服结果池、完整标准/狂野发现池或完整黑暗之赐。

原[疯狂生物实验](../tests/test_dark_gift_keyword_recipes.py)只采用真实2费1/1、战吼发现印刷3费可收藏随从及显式小池。测试中的定向伤害法术是基础关键词诊断，不是另一张真实卡牌的支持声明。三个新配方与七配方库存都使用原`prototype-v258` / `core-effects-v252` / schema228；观察76、命令12、replay1不变。国服精确资格、随机分布、预览和时序仍待集中校准。
