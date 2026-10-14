# 本局永久英雄技能伤害加成

野火的独立基础复用原健康规则、命名行为阶段和英雄附件，不新增模块、关键词、玩家账户、协议或伤害管线。实现契约在本页，实际验收与下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。

## 真实定义与必要代表

[官方野火卡页](https://hearthstone.blizzard.com/en-us/cards/63062-wildfire/)说明其使己方英雄技能在本局对战中额外造成 1 点伤害。[官方 22.0.2 更新](https://hearthstone.blizzard.com/en-us/news/23758614/22-0-2-patch-notes)于 2021-12-20 明确将效果改为本局持续，并解释更换英雄技能后加成仍保留。早于此次改动的技能换槽失效政策不属于本实现目标；历史公告不能替代当前国服精确窗口校准。

必要隔离代表仅 `BAR_546` 野火与 `HERO_08bp` 火焰冲击。野火完整本地定义是法师史诗、1 费、火焰法术、无目标；火焰冲击是 2 费英雄技能，对一个合法角色造成 1 点普通英雄技能伤害。[完整原始证据包](../data/support/whole-game-hero-power-damage-basics.json)还保留 `BAR_546e` 与 `BAR_546e2` 两条附魔原行，仅作证据，不注册执行适配。

包 canonical PIN 为 `7d1c112214be84cd8737571e1be0ad489ff18d8fa4bcdcd3f67948466892eebf`；原始 36022 行卡库 SHA256 为 `fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`，固定来源为 36.6.0.251952/zhCN。本地卡文和附魔行不是当前正式池认证。

## 持续载体与公共表达

`BAR_546.on_play` 返回一个既有 `InvokeBehavior` 命名阶段。该阶段执行时读取 `state.players[player_id].hero_id`，再交付普通 `GrantHealthRule`：

```python
GrantHealthRule(current_hero_id,
    HealthRule(HealthFlow.DAMAGE, HealthOp.ADD, 1,
               source_relation='friendly',
               damage_kinds=(DamageKind.HERO_POWER,)),
    source_id=wildfire_entity_id)
```

`expires_turn` 保持 `None`。规则作为原 `AbilityInstance(kind='health_rule', origin='granted')` 安装在当前英雄上，保存来源野火的物理身份；法术已经进入墓地，不导致附件消失。每次真实成功执行各安装一个独立附件：一张野火令基础火焰冲击从 1 变为 2，两张变为 3。反制后的付费法术没有执行主体，因此不会安装附件。

当前英雄载体是原公共持久附件的一种用法，没有第二份英雄技能伤害计数或缓存。普通伤害报价沿 [原健康规则](m2-health-rules.md)，只匹配 DAMAGE、HERO_POWER 和相对于持有者当前控制者的友方来源；法术、战斗、疲劳、普通效果、随从能力和治疗不受影响。没有伤害主体的技能也不会凭加成产生一个伤害主体。

## 技能、英雄替换和本人区间

- `ReplaceHeroPower` 只更换技能槽，英雄载体不变；加成沿原规则对新技能的基础伤害报价。换成基础 2 点的诊断技能后伤害是 3，换回火焰冲击后是 2，不向技能复制额外附件。
- `ReplaceHero` 沿原 `copy_attachments` 保留所有非打印的持续附件，并分配新附件 ID；旧英雄进入墓地且不再提供规则。每次替换只产生一份当前有效加成，来源野火身份与无到期属性保留，没有将旧英雄也算作提供者。
- 回合开始和结束不消费或清除无到期附件。即使使用野火时尚无英雄技能槽，当前英雄仍可持有规则；后来正常安装技能时取得加成。

上述是本局效果的载体生命周期验证，不建立“野火＋英雄牌”等组合族。其他真实技能本体与英雄卡主体仍按相应来源实现。

## 等待、回放和玩家接口

在原 `card_committed` 等待时，法术已经支付 1 费但尚未交付规则；等待选择更换英雄后，命名阶段读取当前英雄，不把加成安装在已离场英雄上。在原 `ability_granted` 等待时，加成已经安装；等待选择更换英雄则沿原持续附件保留，恢复后只存在一个当前有效附件。两种等待的存档、独立注册表恢复、clone 和 replay 使用原解释器。

失败选择中先更换英雄再抛出异常，原事务回滚恢复英雄身份、附件、技能槽与 pending 状态。正常继续不重复安装、支付或伤害。公开玩家命令仍使用 revision/action 外壳；野火付 1 费，后续技能独立付 2 费。

内部规则、全知帧、来源哈希和对方隐藏卡牌不进入玩家 DTO。重算外层 hash 后，存档规则出现未知字段仍由原 typed 校验拒绝；未签名存档不认证外部来源。

[隔离专项](../tests/test_whole_game_hero_power_damage_basics.py)中的替换、反制、选择和失败来源只作公共路径诊断，不添加生产卡牌或新授予机制。运行身份保持 `prototype-v255` / `core-effects-v249`、schema 225 拒旧 1～224、Keyword 46、观察 76、命令 12、replay 1、生产代表包 64 和合成包 3。

精确国服接受/交付/替换窗口、所有实际来源与正式池仍开放。M0、M6、M7 和完整基础目标未因此完成。
