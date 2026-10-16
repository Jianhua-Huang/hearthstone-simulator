# M3：物理卡牌与手动出牌资格

manual_requirement_error现在统一检查原HandPlayLock与原武器条件，Game、PlayFromHand和完整付款证明使用同一查询。锁定期间零费用也不能打出，第二次后续真实本人开始后恢复；自动CAST及独立手牌动作仍沿自身资格。零数值标记、复制/重置及保存见[契约](m3-draw-retention-limits.md)。

`CardDefinition.hand_playable` 保持原有结构含义：这种定义能成为手牌或牌库中的物理卡牌。`manual_playable: bool = True` 单独声明当前卡面是否允许从手牌手动打出。声明为 `False` 不阻止创建、抽取、持有、移动、复制或已有的手牌变形。

```python
from hs_sim.engine import CardDefinition, CardType

locked = CardDefinition(
    'diagnostic.locked', '诊断用不可手动打出的法术', CardType.SPELL,
    manual_playable=False,
)
```

这是公共资格声明的诊断示例，不是完整殒命暗影适配。实际卡牌的其他行为必须另外明确实现，不能只设置一个标签就把它当成白板法术注册。

## 隐式装备武器前置条件

`CardDefinition.requires_weapon: bool = False`声明手动打出时必须有本人当前有效武器，不增加玩家选择目标。注册表要求严格布尔值，True仅用于物理手牌卡；默认False在指纹中省略。共同查询`play_requirements.weapon_requirement_error`使用原`equipped_weapon`，只看当前控制者的原装备槽、正耐久和非doomed；零攻击武器也满足，不从英雄攻击力推测装备。

原手动校验在报价/支付前拒绝缺武器的来源，合法枚举通过相同校验过滤；解释器内部`PlayFromHand`使用同一门禁。原完整手牌支付证明从捕获的payment_state重新核验资格，不能把后来装备的武器补作原来的许可。付款接受后已有武器被反应消灭，不重新按新局面否定原付款；具体卡牌主体继续按执行时的武器决定是否有效。历史精简收据不增加未经来源认证的过去武器断言，仍不认证任意自洽重写的未签名历史。

持有、生成、复制和手牌换脸不由此门禁禁止；当前印刷定义控制下一次手动资格。`CastSpell`等自动效果施法保持原独立资格，不把手动条件塞入它们。该声明没有新实体缓存、资源账户或玩家DTO字段，存档由更新的mechanics签名及注册表身份保护。

真实需求来自致命药膏的隐式武器条件：固定卡面见[完整内容记录](../data/cards/conditional-effects-v1.json)，[Fireplace维护者的原始实现](https://raw.githubusercontent.com/jleclanche/fireplace/master/fireplace/cards/classic/rogue.py)声明该原版卡需要装备武器，[固定37.0客户端错误字符串](https://raw.githubusercontent.com/HearthSim/hsdata/be4ef28ef9bd9e613045d495138061ba31a6d2f9/Strings/zhCN/GAMEPLAY.txt)也保留REQ_WEAPON_EQUIPPED。外部实现与错误字符串仅支持基本需求，不代替国服当前逐卡资格和精确窗口校准；实际执行证据只在原两份台账维护。

手动 `PlayCard` 在报价、支付和主体执行前检查原始手牌实体的当前卡面。合法动作枚举同样排除它；解释器内部的手动手牌入口也有相同门禁。零费用、足够资源或一份合法报价都不能代替出牌资格。其他独立手牌动作沿用各自契约，本声明不决定它们是否可用。

原付款证明检查原始支付卡面；历史精简收据也保留这一检查。接受出牌后出现的新卡面不能倒改原来的资格证明。该检查适用于真实手牌法术和非法术付款根，不据此规定自动施放的规则。

资格由注册表的当前卡牌 ID 读取，不增加实体缓存、临时附魔或玩家资源。手牌变形后采用新卡面。`CopyCard(mode='base')` 及重置使用**当前卡牌 ID 的印刷定义**，不会恢复变形前的创建身份；普通当前复制继续复用既有区域与附件契约。默认 `True` 在注册表指纹中省略，以保持旧默认定义的身份；`False` 进入完整指纹。

本地完整原行见[原生资格证据](../data/support/manual-play-eligibility-basics.json)。两个可收藏殒命暗影卡面均具有 `LITERALLY_UNPLAYABLE=1`；官方[36.2修复](https://hearthstone.blizzard.com/en-us/news/24290432/36-2-patch-notes)和[36.4修复](https://hearthstone.blizzard.com/en-us/news/24293283/364-patch-notes)支持其不能在未有效变形时错误打出的基本方向。这里不据此宣称完整复制主体、自动 CAST、生成候选资格或国服精确时序已经验证。

全部314个本地同标签原行含大量佣兵、战棋和剧情来源，保留在[前审](../outputs/board-removal-scope-basics-20261012/next-work-audit.json)。没有批量把它们映射为构筑支持范围。

实体存储和复制继续遵循[区域契约](m3-zones.md)，玩家授权遵循[玩家接口](m3-player-api.md)。实际验收结果与下一项只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。
