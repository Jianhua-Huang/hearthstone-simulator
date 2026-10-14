# 套牌之外出牌：开局物理身份与独立费用输入

实际执行、内部验证及下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。本契约复用原开局与出牌事实，定义一个有限基础输入，不代表完整动态费用、正式卡池或国服校准已经完成。

## 有限声明与必要来源

普通物理随从复用已有声明：

```python
player_played_class_cost=PlayerPlayedClassCostSpec(
    card_class=None,
    profile_id='cost.player-played-outside-starting-deck-v1',
)
```

该 profile 固定按实际付款者、本局原物理手牌根和原起始牌库实体筛选，必须显式 `card_class=None`。旧职业和本回合全牌型 profile 保留各自政策。未知 profile、错误类型、非普通随从、选择专用定义、星舰载体以及同时声明另一固有公式均拒绝；不提供任意表达式或组合接口。

必要隔离来源是 [DRG_109 法力巨人完整本地 raw/pin](../data/support/player-nonstarter-play-cost-basics.json)：8 费 8/8 法师史诗元素，没有战吼、亡语或其他主体。canonical pin 为 `b79085b1e2a0a88adfc73b0d19f317c3e5e4532ecddd7e10cb0a193bbdb6e47f`。适配只在必要验证注册表，生产代表包和正式生成池不扩大。[官方卡页](https://hearthstone.blizzard.com/en-us/cards/54909-mana-giant/)返回导航壳，没有提供精确来源判定或国服时序证据。

## 原起始身份与纯关系

`starting_deck_identity(state)` 返回原 `OpeningState.original_entities` 和两方 `PlayerState.original_deck` 的完整不可变配对。检查两方组、实体与卡面等长、全局唯一物理 ID、各组原分配顺序、分配上界及原实体 owner；当前区域、控制者和变形后的卡面不改写开局身份。换牌沿原开局实现处理，不重建起始集合。

`played_outside_starting_deck(state, player_id, before_id=None)` 复用 `played_cards` 的参数校验和原 `PlayRecord`，按冻结提交卡面的 `source_id` 是否在该实际付款者的原实体组中筛选。比较的是物理实例，不是卡名集合、当前牌库、当前卡面、生成上下文或复制来源指针。

生成的同名牌、普通复制以及生成后洗入并抽出的牌都有自己的新实体 ID。原牌回手后再次使用仍保留原 ID。同一原牌变形后的身份与另一玩家原牌转移后的归属，当前采用物理实体及实际付款者关系；这是明确的本地政策，仍需国服证据校准。

只有卡名列表的 `Scenario` 没有完整原开局物理记录，明确抛出 `UnsupportedDefinitionError`，即使当前出牌历史为空也不猜测为零。查询不分配 ID、不消费 RNG、不修改实体或台账。没有第二开局、创建历史或玩家累计缓存。

## 原出牌根与费用层

`player_played_class_costs.py` 继续验证完整原 `play_history` 的付款收据、冻结卡面和手牌获取。每个本人符合物理关系的手牌出牌根贡献 1，五种可从手牌打出的卡牌类型共享该资格。普通召唤、自动施法、技能、获取、交易和锻造本身不增加手牌根；执行它们的原手牌根仍沿既有出牌政策处理。

获取法力巨人前的历史和跨回合历史保留。原已付款根在 `card_committed` 之前存在，反制根和待结算根按既有本地出牌政策计入，失败动作由原事务回滚。本牌费用在自己的新根追加前捕获，不能给自己的这次付款减费。

固有阶段仍计算 `max(0, base_cost - quantity)`，数量不因费用降至零而截断。其后再沿原本地、外部修正及最终下限；物理、生成、玩家显示、合法操作与付款读取同一输入。生命等替代账户不改物理关系，原付款只执行一次。

## 完整原事实与恢复

已有 `PlayerPlayedClassCostFact` 末尾增加显式 nullable 的 `starting_entities` 与 `starting_cards`。新 profile 必须保存两方完整原实体与卡面配对，不能只保存匹配行或本人牌库；旧职业/本回合 profile 必须保存两项 None。

原完整有序行、实际付款者、turn/action、获取身份、分配上界、历史游标、selected_ids、quantity 和 before/after 保留。冻结事实由同一个纯物理关系重算选择，原卡面必须为注册表中的已知手牌定义。原窗口重取整份事实，金额相同不能代替身份一致。

紧凑保留检查完整原出牌行是当前合法历史的精确前缀，并且原开局配对与当前原记录完全一致；另一玩家未匹配的起始尾项也不能删除。后来合法出牌、获取、回合变化或原主体完成不重算已接受金额。保留校验不独立认证一份自洽较早前缀来自某次真实报价，也不提供未签名存档的外部来源认证。

原字典 reader 严格要求两项字段，并把非空嵌套数组恢复为不可变元组。typed 帧复用原模型发现与 FrameCodec；真实承诺/完成后待选、独立注册表恢复、clone、回放和异常回滚沿原解释器。选择之后失败恢复到原待选边界，已经提交的原付款保持。

## 协议、玩家边界与保留范围

引入时 `prototype-v228/core-effects-v222/schema211`，拒绝旧 schema1～210、未来值、bool/非整数以及旧规则/效果签名；旧保存不自动补原配对。观察74、命令11、replay1及生产代表64/合成3保持。

没有新增生产模块、模型类型、GameState/PlayerState/Entity/OpeningState/PlayRecord/CardDefinition/固有阶段字段、Effect、事件或动作。只有原 spec 的有限 profile、原冻结事实两项操作数、四个纯函数及原字典 reader 扩展；原开局、区域、报价、付款和 FrameCodec 执行器共享。

玩家可见自己的合法最终费用，不能取得任一方私有起始组、完整冻结前缀、内部物理分配或付款证明。精确来源身份、变形/跨玩家转移、承诺/反制/退款、费用层顺序、特殊来源和当前国服规则继续开放；不展开组合矩阵或批量接卡。
