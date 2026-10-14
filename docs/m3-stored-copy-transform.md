# M3：现有存储卡牌变为当前物理复制

`TransformStoredIntoCopy(target, card, source_id=None)` 使用两个明确的 `CardReference`：接收者和物理复制来源，二者均须处于手牌或牌库。它保持接收者实体 ID、owner/controller、区域、槽位和获取记录，重置旧卡面及附件后复制来源当前材料。来源不移动、不消耗，也不会新建接收者。

```python
from hs_sim.engine import TransformStoredIntoCopy
from hs_sim.engine.zones import CardReference

effect = TransformStoredIntoCopy(
    CardReference.capture(recipient), CardReference.capture(physical_source), source_id,
)
```

引用捕获身份，材料在效果执行时读取；同一引用仍匹配的来源若先被修改，复制它当时的材料。任一引用已经离区、改卡面、转控或推进修订则沿原规则跳过。自我复制先冻结当前材料，再重置自己，不会先把复制内容清掉。

当前材料复用原 `CopyCard(mode='current')` 的字段与附件复制规则：本地基础属性、伤害、耐久、尸体值、附魔和能力及原进度/使用状态等；附件分配新 ID，原来源记录沿原复制政策保留，物理控制返回附魔继续排除。此公共操作没有新增特殊授予或任意保留接收者旧附魔的参数。复合材料目前明确报错，相关组合仍后置。

复制安装完成后才使用原 `stored_card_transformed` 通知与身份隐藏，反应不会看见未安装完的中间状态。它不产生创建、抽取、打出、施放或召唤；不自行抽随机数。待选帧登记新效果类型，恢复/克隆/回放/异常回滚与玩家隔离沿公共层。本项引入时规则/解释器身份为 `prototype-v264`/`core-effects-v258`；状态结构和schema232、玩家接口保持。

原新实体复制见[区域契约](m3-zones.md)，印刷重置见[普通存储变形](m3-stored-card-transform.md)。[完整必要证据](../data/support/stored-copy-transform-basics.json)与官方[12.0更新](https://hearthstone.blizzard.com/en-us/news/21964710)支持变色龙需要复制属性增益和减费的基本方向。原附件来源、特殊寿命及精确国服规则仍待校准；这一原语不等于完整变色龙、幻象或殒命暗影适配，也没有据此完成持续定义来源。

实际执行、差异和下一项只在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。

后续独立原生来源表示见[来源契约](m3-native-defining-hand-source.md)；带来源的当前复制/转手政策仍需具体真实来源证据。实际结果与下一项只在两台账维护。
