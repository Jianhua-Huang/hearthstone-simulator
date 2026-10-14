# 随从创建时的普通数值与关键词授予

国服资料片说明将不同赐福绑定到不同发现随从，并列出数值、基础关键词和满血保附魔复生的真实结果。[国服说明](https://hs.blizzard.cn/news/24179067/)。这些牌到手时需要带有自己的修改。原 `AddToHand` 已在首个入手事件前安装费用；在其后执行普通存储授予，会留下可被入手触发观察到的未修正阶段。此入口复用原创建安装层，表达普通数值和必要关键词的原子安装。

实际执行、验证结果与下一项仅在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。完整黑暗之赐成对发现、资格、结果池和国服校准仍需独立证据。

## 公共声明

原 [AddToHand](../hs_sim/engine/effects.py) 增加末尾可选字段 `minion_grant`。 原[AddToDeck](../hs_sim/engine/zones.py)也接受同一声明，直接创建在牌库且在创建/入库事件前安装，见[牌库创建契约](m3-deck-creation-grants.md)。它只接受不可变 [CreatedMinionGrant](../hs_sim/engine/card_creation.py)，也可从 `hs_sim.engine` 导入：

```python
from hs_sim.engine import CreatedMinionGrant, Keyword
from hs_sim.engine.effects import AddToHand

def plate_up_recipe(ctx):
    return (AddToHand(ctx.player_id, 'CS2_120', ctx.source_id,
        minion_grant=CreatedMinionGrant(health=4, keywords=(Keyword.TAUNT,))),)
```

载荷字段：

| 字段 | 含义 |
| --- | --- |
| `attack` / `health` | 严格整数的普通加减数值，复用原附魔层；默认0 |
| `keywords` | 无重复的不可变关键词元组；当前仅真实赐福所需的嘲讽、圣盾、冲锋、风怒、复生、吸血、扰魔 |
| `reborn_policy` | 默认None；与复生一同声明时可使用原 `full_health_enchantments` 返回政策 |
| `identity` | 默认None；可选创建授予身份，保存在原附魔名称中；关键词单独授予也能留下零数值身份附魔，见[成对发现契约](m3-paired-discovery.md) |

空声明、布尔/浮点数值、未知关键词、错误复生政策及任意战吼/亡语/触发程序均明确拒绝。其他原存储授予接口保持原范围。只有随从能携带本声明；费用沿原 `AddToHand.cost` 独立表达，原来源ID提供全部新附件的来源。

## 原子安装与生命周期

原 [create_hand_card](../hs_sim/engine/opening.py) 先验证定义、来源、费用和创建声明，再决定手牌或烧毁的物理实体。原 `card_creation.install` 安装一个普通数值附魔及每个关键词的独立 `AbilityInstance`，使用原单调附件分配器并刷新派生值。完成后才发出 `card_created` 和 `card_added_to_hand`／`card_burned`；不另发后续存储授予事件。第一个创建/入手/烧毁观察者收到完整的修改后材料。

满手结果同样先有完整附魔，再沿原烧毁事件处理；它不会因此获得成功入手记录或自然死亡记录。普通同名牌、既有手牌及其他玩家的牌不受影响，不通过预测下一个实体ID寻找新牌。

安装后的能力和数值都是原附件，没有额外持久账户或新执行器。当前复制、基础复制、手牌/牌库移动、沉默、回手重置及正常战斗由原生命周期处理；满血复生沿 [既有返回契约](m2-full-health-reborn.md)。原事务保证创建后的观察者异常也撤销新实体、附件、付款与随机状态。

## 挂起与信息边界

`CreatedMinionGrant` 注册为原帧编码器允许的不可变载荷。等待前尚未创建的 `AddToHand` 选项保存完整声明；等待后既有新牌保留完整材料，恢复不重复创建或付款。原边界遍历检查全部待选分支的载体，不能因为某分支尚未被选择而藏入不兼容声明。帧中的字段、类型和来源严格校验；重新哈希不能绕过检查。

玩家仅看到原可见手牌属性和关键词，不获得 `minion_grant`、附件ID、内部帧或对方手牌内容。公开烧毁仍按原可见性政策处理。引入时为 `prototype-v257` / `core-effects-v251` / schema227，拒绝1～226；观察76、命令12、replay1保持。

## 真实依据与未覆盖范围

[完整原行pin](../data/support/creation-minion-grants-basics.json) 保存四种必要隔离配方：起床怒气、衣甲厚实、回荡恐怖、法力值/攻击力减少，以及对应附魔、淡水鳄、冰风雪人和狡诈拷问者来源证据。冰风雪人用于负攻击与原减费的真实载体；必要配方只验证普通创建安装。狡诈拷问者要求发现传说随从，没有在此被接成使用普通随从的小池来源；赐福描述也没有被注册成可出牌法术。

现有抽样与选项可承载绑定信息，但完整发现必须保留原发现候选校验、选择归属、交付事实和收据。普通 `EFFECT` 选择不能冒充完整原生发现。此字段当前只接原 `AddToHand`，未扩大到所有生成入口；其他赐福主体、印刷/当前资格、成对绑定与发现归属、当前12描述的正式生效池继续开放，全部原行保留，不删除未实现结果。创建/入手/烧毁精确窗口及完整来源仍待国服校准。
