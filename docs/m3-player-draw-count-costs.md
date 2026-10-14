# 实际抽牌数量的独立费用输入

实际执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约只定义一个真实需求的有限输入，不表示U53整族、正式池或准确国服已验收。

## 声明与来源

普通可从手牌打出的随从或法术通过`CardDefinition.player_draw_count_cost=PlayerDrawCountCostSpec()`声明，默认None。两个有限profile：默认`cost.player-physical-draw-count-v1`读取本人本局，`cost.player-physical-draw-count-turn-v1`读取本人当前全局回合；不提供任意表达式、双方或上一本人回合等未审profile。其他类型、非普通载体、叠加原条件/其他数量公式明确拒绝。

仅必要[TOY_530游乐巨人完整本地raw/pin](../data/support/player-draw-count-cost-basics.json)，25费8/8中立史诗机械，无额外主体或战吼；只在隔离验证注册表适配，不扩大生产代表包。支持文件canonical pin为`e88ccefe756362fd54d825806c8ef92495dfa3e9663665bfa69d238914ac0ee3`。[官方33.2](https://hearthstone.blizzard.com/en-us/news/24223019/33-2-patch-notes)仅证明历史20改25；匹配官方卡库实际打开只有导航，精确文本/数值取固定完整本地记录，不使用记忆中的旧数值。

必要普通法术[TTN_841势如破竹完整本地raw/pin](../data/support/player-draw-turn-spell-cost-basics.json)为5费稀有恶魔猎手法术，没有猜填学派或战吼；只声明本回合profile。支持文件canonical pin为`e3a8f09699ffd497480c9821e67752aef378338e65b6d9dc2f5e6dfa4fb768c1`。实际付款后主体只返回原`Buff(本人英雄, attack=4, expires_turn=当前turn)`，原附魔、攻击动作、到期及事务共享；原反制保留已付费用并跳过主体，完成后待选保留原报价，晚错误回滚原付款和增益。匹配[官方卡库](https://hearthstone.blizzard.com/en-us/cards/97477-momentum)实际读取只有导航，完整文本/数值取本地固定记录，当前CN仍待M0/M6。没有新增另一种英雄攻击、法术或费用执行器；本局随从和本回合随从/普通法术共用同一事实和公式。

## 复用原抽取事实

`player_draw_count_costs.py`直接读取原`draw_history`和`drawn_cards`，使用原完整抽取历史校验。获取定价卡前的真实抽牌同样有效；本局profile跨回合累计，本回合profile只筛原记录turn等于当前全局turn，不使用本人回合序号或持牌时长。实际payer决定数量，不跟随原被抽牌的owner或当前区域/控制者变化；对手回合中实际为本人抽牌也按该原全局turn计入。完整前缀保存此前回合、对手和疲劳等不计入行，不能删去这些行后冒称完整历史。

本地计数政策是原记录接受时，每次本人实际物理抽牌贡献1，包含`hand/burned/cast`；正常入手、烧牌、抽到施放及其每次真实补抽按各原记录计算。数量独立于后来的完成阶段或终局中断，不按卡名或物理实体去重，同一原实体合法再抽是另一次。`fatigue`没有物理牌，不贡献数量；过期目标/空库skip/零次请求不产生记录。普通移牌、复制、生成、起始发牌和换牌不计，首次及普通回合的原Draw计入。

这是内部政策，准确国服的烧牌/自动来源/接受可见窗和终局口径仍待M6，不将原记录支持的全部结果直接宣称为已校准规则。没有第二套抽牌账本、玩家累计缓存、抽牌事件或执行器；DrawRecord和原抽取管线保持原语义。

## 公共报价与完整冻结

金额为`max(0, base_cost-quantity)`，进入原固有阶段，再走原本地/外部费用层和最终下限。物理/生成/玩家显示/合法操作与一次真正付款共享；查询不创建实体、分配ID、消费RNG或写base_cost。普通印刷复制、沉默、回手和重新获取沿原生命周期，新报价读当前payer的原历史。特殊复制和来源按真实卡需求后置。

`PlayerDrawCountCostFact`保存原声明、payer、turn/action、实体分配上界、原施法/抽牌完整游标、完整有序DrawRecord元组、selected IDs、数量和before/after。原记录包含未计入行以及当时的phase、cast/parent/replacement链接和interrupted。校验连续有序ID、非递减时钟、原分配边界、已支持卡面、原抽到施放声明及完整双向补抽关系；选择与数量必须按完整行重算，相同金额也不能删除对手/疲劳行或替换原物理身份。

`IntrinsicCostStageFact.player_draws`必须显式保存事实或None，普通卡也必须保存None，绑定原payer/base/turn/action。字典保存共享原DrawRecord读取函数，typed帧沿现有冻结类型白名单与严格字段读取，不增加执行入口。

## 原窗口与合法后续推进

原报价窗口使用`validate_intrinsic_origin`从真实状态重取整个原事实，包含phase和链接；改变同一原窗口的完整捕获仍须拒绝。紧凑保留历史使用原完整前缀及完整当前抽取校验，绑定不变的身份、归属、结果、时钟、来源和声明，只允许原phase沿合法路径前进，原未分配cast/replacement链接可由真实续接补齐，已存在链接不可替换，已中断记录不能继续改写。

后来真实抽牌和合法阶段完成不重价已接受根。本回合profile在新全局turn用新窗口重新筛选，通常重置至未减费；原自然开始Draw按实际接受再减费。已接受事实仍绑定原turn与原数量，不拿当前turn重新筛旧根。完成后监听/抽牌触发/施法主体待选，snapshot/clone/独立注册表replay、异常回滚均复用原解释器。紧凑历史只能证明保留与合法推进，不提供未签名存档的原来源认证，也不能单独证明一份旧phase确实来自原窗口；它与精确原窗口重查是不同的检查。

## 协议和边界

该输入引入与扩展时为prototype-v215～v216/core-effects-v209～v210、schema202；现行prototype-v221/core-effects-v215、schema206拒绝旧1～205，共享State新增成功召唤历史见[成功召唤历史契约](m3-successful-summon-history.md)，成功召唤数量费用叶见[有限图腾费用契约](m3-player-summon-count-costs.md)，原护甲费用叶见[当前英雄护甲费用契约](m3-player-armor-costs.md)，本抽牌输入字段布局不变；观察74、命令11和replay1、modular-v1/fabled-v2及生产代表64/合成3保持。B59引入两冻结类型、一个默认None卡牌声明和一个显式固有阶段叶时改变注册表指纹及保存布局；旧保存不静默补字段。B60仅扩展原有限profile、记录筛选与普通Spell类型门槛，没有新字段/类型/模块或公式，schema202布局不变；旧规则/效果版本仍明确拒绝。

没有新GameState/Entity/Player字段、Effect、玩法事件类型、外部动作或支付/抽牌/生命周期执行器。玩家只看到允许公开的最终费用，完整抽取前缀、物理身份、游标及付款证明不投影给玩家。精确计数、费用层序、特殊来源、正式池和国服校准继续开放，当前不开发组合矩阵。
