# 阴谋成长与圣契持续减费的基础表达

本文分别说明两项独立行为如何复用已有能力，不新增两者之间的组合规则。运行身份保持`prototype-v166` / `core-effects-v166`，schema161、观察71/命令10/replay1。执行位置与下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。

## 阴谋：持牌回合成长

必要代表是DAL_008砰砰博士的阴谋：4费、初始获得1点护甲、留在手牌时逐回合成长。既有`HandProgressSpec`已能表达，不需要另立阴谋状态或结算器：

```python
HandProgressSpec(
    'event', 1, on_complete='scheme.noop', repeat=True,
    event='turn_ended', condition_id='scheme.owner.end',
)
```

注册条件只接受事件玩家等于持牌控制者；完成回调为空，真实主体读取`1 + progress_ability(source).progress_completions`，通过普通`GainArmor`执行。每个本人结束事件推进一次完成次数，当前阶段值归零，印刷卡面保持；对方结束不推进。两玩家及不同物理手牌分别保存自己的次数，后加入的牌没有历史补记。

普通手牌进度生命周期直接复用[原契约](m5-hand-progress.md)：current复制保存已得次数，base复制新建从1起；不重置移至牌库保留计数，但牌库不监听结束事件，重新入手才继续；正常重置按当前定义重装。已有能力身份和见证控制重复消费，不增加新附件类型。真实自动施放实验只验证`CastSpell`新建的阴谋使用基础1点，未把它扩大为全部历史/存储物理牌来源的官方政策。

进度写回后沿原解释器继续。用明确公共探针验证回调等待、独立注册表恢复、clone及回放，没有给真实阴谋新增选择主体。非法非布尔条件使结束动作完整回滚。控制者可见已有进度摘要，对手不能获得私有手牌成长、见证或能力ID。

[官方暗影崛起介绍](https://hearthstone.blizzard.com/en-us/news/22927025/join-us-for-the-rise-of-shadows)支持阴谋持牌成长的方向，未证明精确开始/结束窗口。[公开Upgradable说明](https://hearthstone.wiki.gg/wiki/Upgradable)用于调查结束阶段。本文本人结束、复制/重置及自动新建窗口是内部执行政策，仍待M6国服校准。

## 圣契：玩家持有的持续费用修正

必要来源为BT_020奥尔多侍从（1费1/3，战吼减1）与BT_026奥尔多真理追寻者（5费4/6嘲讽，战吼减2）。行为只返回既有公共效果：

```python
AddCostModifier(
    ctx.player_id,
    CostSpec(delta=-discount, minimum=0, card_ids=family_ids),
    source_id=ctx.source_id,
)
```

不设置次数或到期，所以修正属于玩家，匹配支付不会消费；两个来源分别新增修正并叠加。原来源死亡或沉默不撤销已完成战吼。未来创建的合格牌也沿报价层得到减费，无须逐张写实体费用附魔。两个玩家独立；`Entity.cost`仍为本地成本，实际出牌使用报价并正常支付，支付失败及晚期异常沿原事务回滚。

实验类别明确限定为注册表中的BT_024希望圣契及YOP_011t已腐蚀的正义圣契，分别验证法术和武器均可匹配。这里不是完整圣契池，也不新建基于卡名的规则；名字含Libram的非成员探针不享受减费。本地调查甚至存在HERO_04ax Libram Aponi英雄，证明直接字符串匹配不适合作为运行时资格。原始数字标签1546的语义、完整正式类别及目标版本资格仍由M0核实。真实卡按需接入时向准确类别清单加入ID即可，未知定义不会作为白板或被静默删池。

希望圣契的普通主体复用治疗及召唤：恢复8生命、召唤8/8嘲讽圣盾守护者。[官方卡页](https://hearthstone.blizzard.com/en-gb/cards/56554-libram-of-hope/)支持该主体。YOP_011t仅作为必要的既有武器形态验证7费、5攻3耐久及印刷吸血；没有适配其基础形态的腐蚀过程或新增组合。奥尔多来源及两成员的卡文以完整本地原始行固定，精准费用排序、资格池及官方窗口尚未国服校准。

玩家观察复用现有费用DTO，只给本人可查询的手牌报价，不暴露私有修正ID、全知状态或对手隐藏费用。`Game.quote_cost`要求当前行动玩家的手牌或技能；验证玩家独立时先自然结束回合，再查询新行动玩家。持续修正的等待恢复也用独立公共探针验证，只安装一次，不为真实奥尔多卡添加等待效果。

## 证据与范围

[六条完整raw/pin](../data/support/scheme-libram-basics.json)固定DAL_008、BT_020、BT_026、BT_024、BT_024t及YOP_011t，PIN为`1debdcff7624e6b935476f22a42e71997ce845dcab4f76f80998cb47adbe97ad`。原本地名字/数字标签调查见[前审](../outputs/scheme-libram-basics-20261009/family-preaudit.json)，不是完整合法可达池认证。场景为隔离机制实验，不声称混合职业牌组合法；其他种族/生成元信息、全类别卡牌及复杂卡牌主体没有因此获得完整适配。

实际执行依据[保存报告](../outputs/scheme-libram-basics-20261009/verification.json)及[逐方法证据](../outputs/scheme-libram-basics-20261009/accepted-evidence.json)。内核、已有测试及生产代表/合成包全部保持原字节，仅新增隔离专项与证据文档；因此没有新增机制版本、快照字段或重复公共模块。两类测试分别验自己的行为，没有建立阴谋与圣契的组合矩阵。内部表达验证不能替代M0正式池、M6国服校准、M7批量接卡或U32整族验收。
