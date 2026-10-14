# 本局本人英雄技能使用次数的独立费用输入

实际执行、内部验证和下一项以[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)为准。本契约只定义一个有限基础输入，不代表U53整族、当前正式卡池或国服规则已验收。

## 声明与已有历史

普通手牌随从声明`CardDefinition.player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()`，默认None；profile固定为`cost.player-hero-power-count-v1`。非普通随从、未知profile及同时声明其他数量公式明确拒绝。

唯一必要真实代表为[AT_120冰霜巨人完整本地记录](../data/support/player-hero-power-count-cost-basics.json)，10费8/8，canonical pin=`f273dea38f98d7cd4d3d41021f04ac2bd3da97632700d0c6cdd1e205c71c79b6`。隔离注册表声明此输入，生产代表包不扩大。官方[2015年技能主题介绍](https://hearthstone.blizzard.com/en-gb/news/19819221/the-grand-tournament-hero-powers-7-23-2015)提及其与技能使用的关系；该历史文章不证明当前国服精确窗口或来源归属。

`player_hero_power_count_costs.py`读取原`hero_power_history`，使用原完整历史校验，不新建玩家计数、第二份事件日志或持牌进度。卡牌获取前、换过技能前和较早回合的实际使用均保留；当前技能每回合使用次数或单实体uses_this_turn不能代替本局历史。

## 有限计数政策

每个实际payer、origin=manual且无failure的原激活根贡献1；原手动付款/接受记录存在即计入，主体在等待选择、尚未完成或后被终局中断不撤回。完成与中断属于后来进度，不是此profile的数量操作数。一次技能使用无论费用多少、支付账户是什么，都只贡献一次；0费用同样是真实使用。

effect激活、自动无目标/非法目标/被动失败不增加手动数量。原前缀仍完整保存这些行；被动卡面必须与passive失败身份匹配，不能冒作手动使用。对手技能、法术及随从出牌不增加本人数量。失败手动动作按既有事务回滚，不留根。

技能替换、刷新、次数额度变化和回合重置沿既有模块；报价重新读取真实本局前缀，没有减费缓存或事件监听。未结手动根的精确计数时点、各效果来源归属、额外技能及特殊来源仍需按真实卡和M6国服校准，此profile不能被当作全部“使用技能”卡文的已认证口径。

## 纯报价与原依据

每次原手动根减1、最低零，位于base后及原条件/本地/外部层前。物理和生成报价共享payer历史；不创建实体、分配ID、消费RNG或修改印刷10费。现有费用显示、合法枚举、验证及付款共用公共报价管线。

`PlayerHeroPowerCountCostFact`保存声明、payer、分配上界、原hero_power_history_length游标、完整有序`PlayerHeroPowerCountCostRow`、数量及before/after。行冻结真实root/source/player/card/turn/action/origin、原激活方/父根、费用/支付类型、原实体及玩家使用时钟、失败结果。完整游标与行数、连续有序ID、时间线、来源分配和数量金额必须相符；所有原卡面及被动资格都校验，未计入行和零数量不短路未知内容。

`IntrinsicCostStageFact.player_hero_powers`必须显式为事实或None，绑定payer/base/原接受时间窗。物理来源不能晚于原分配上界。实际付款沿原完整手牌接受证明重新捕获真实原前缀；付款完成待选、后来使用技能或替换技能不重写已付金额、不重复扣款。

紧凑历史绑定同一完整原物理激活前缀，按冻结原数量重算；完成/中断可以正常推进，原身份、来源、支付及失败结果不变。不会用今天的增长历史替代原报价。它不认证未签名存档的外部来源，也不证明协同重写全部历史的真实性。

## 生命周期、保存与玩家接口

普通印刷复制、沉默、回手及重新获取沿既有生命周期；重新报价读取当前本局历史，印刷费用保留。场上/牌库的费用查询只是出牌假设，不写入实体base_cost。特殊复制政策按真实来源与M6核对。

首次落地为`prototype-v186`、`core-effects-v180`、schema175，拒旧1～174；观察74/命令11/replay1、modular-v1/fabled-v2保持。新增默认定义叶`player_hero_power_count_cost=None`及每个固有阶段显式`player_hero_powers`改变指纹与严格保存格式，不自动补旧字段。无新Entity/Player字段、玩法事件或外部动作。

玩家看到本人实际价格；原物理激活行、分配上界及付款证明只供内核验证，不输出到玩家接口。对手手牌身份与价格继续隐藏。

## 剩余范围

精确窗口/效果归属、费用层顺序和特殊复制尚未国服校准；其他真实历史公式与实际资源投入需逐项核对并优先复用既有事实。本契约没有任意公式或组合矩阵。U53整族、H2/M0/M6/M7及整个基础目标保持开放。

当前共享费用API为prototype-v190/core-effects-v184/schema179，拒旧1～178。新增[本局实际法术法力费用](m3-player-spell-mana-costs.md)复用原物理出牌/付款，不改变本契约自身资格；精确CN仍待校准。
