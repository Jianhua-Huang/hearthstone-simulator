# 独立进化（Adapt）配方

进化复用现有结算能力，没有新增Effect处理器、关键词、持久状态或选择解释器。[公共配方](../hs_sim/engine/adapt.py)将真实十种结果组织为现有`RequestChoice(sample_size=3)`和普通附件效果；实际执行与下一项见[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。

## 依据与安装

[官方设计说明](https://news.blizzard.com/en-us/article/20659256/hearthside-chat-adapt-in-un-goro-with-dean-ayala)与[官方资料片介绍](https://news.blizzard.com/en-us/article/20584091/prepare-to-embark-on-a-journey-to-ungoro)说明从十种进化中随机提供三种，玩家选择一种增强随从；火山龙提供连续两次的真实来源。具体卡面与当前中文文本来自[固定完整raw/pin](../data/support/adapt-basics.json)，不据此认证当前国服正式补丁或合法池。

`register_adapt_options(registry)`在对局建立前显式安装十张choice-only选项牌及真正的1/1植物衍生物，另注册活性孢子的普通亡语行为。选项不是可入手/出牌的法术，不进入普通生成池。来源卡仍由各自适配负责；本项三张来源只在[专项隔离注册表](../tests/test_adapt_basics.py)验证，没有改动生产代表包。

```python
from hs_sim.engine import Registry
from hs_sim.engine.adapt import VERSION, adapt, register_adapt_options

registry = Registry('my-card-pack-' + VERSION)
register_adapt_options(registry)
registry.register_behavior('my_adapt', lambda ctx: adapt(ctx, (ctx.source_id,), registry))
```

行为闭包只引用将被对局冻结的静态注册表，不引用Game或外部局面。改变配方语义或来源适配须更新宿主`Registry.version`，不能依赖同名行为自动认证旧回放。既有内核版本和快照结构保持。

## 十种真实结果

| 选项 | 卡ID | 复用的公共能力 |
| --- | --- | --- |
| 烈焰利爪 | UNG_999t3 | Buff +3攻击 |
| 岩质甲壳 | UNG_999t4 | Buff +3生命，保留已有伤害 |
| 火山之力 | UNG_999t14 | Buff +1/+1 |
| 巨型体态 | UNG_999t6 | GrantKeyword 嘲讽 |
| 闪电之速 | UNG_999t7 | GrantKeyword 风怒 |
| 爆裂护盾 | UNG_999t8 | GrantKeyword 圣盾，沿原消费规则 |
| 毒液喷吐 | UNG_999t13 | GrantKeyword 剧毒 |
| 液态外膜 | UNG_999t5 | GrantKeyword 扰魔（ELUSIVE） |
| 氤氲迷雾 | UNG_999t10 | GrantKeyword 潜行及既有下一自身开始期限 |
| 活性孢子 | UNG_999t2 | GrantDeathrattle，死亡时两次普通Summon植物 |

`adapt(ctx, target_ids, registry)`接收准确、唯一、不可变的目标ID tuple，来源必须存在。目标资格只取当前捕获局面的活跃场上随从；空集合或没有合格随从时不请求选择、不耗RNG。来源负责选择自身、指定随从或群体，配方不扩展卡牌自己的目标权限。

所有选项、植物和亡语行为先验证，未知内容明确报错，不能通过采样或空场静默删除。配方本身不读取或修改RNG；公共选择实际执行时一次采样三个不同选项，正式等待边界保存原选项与RNG，恢复不重抽。

本地政策保持完整十种池，不因已有关键词排除结果。数值增益可叠加，重复圣盾仍沿已有同名旗标消费规则，不形成多层盾。每次实际进化各自请求一次新选择，不设置repeat_key或沿用上次结果；连续进化可再次选择同一种结果。

群体一次共享所选选项，各目标生成自己的普通附件；没有为每只随从另抽选项。目标集合沿来源原捕获视图，分支逐效果的光环/死亡检查点沿公共解释器。精确官方群体安装窗口及已有关键词的排除细节仍待国服校准，不将内部政策当作官方证明。

## 生命周期、恢复与信息

属性、关键词、潜行期限和亡语均是既有附件。沉默、当前/基础复制、回手、变形、关键词消费及到期沿现有生命周期；不增加一份独立“进化状态”。潜行文本的“你的下个回合”按本次行动方解释，再交给既有真实自身回合计时。活性孢子复用死亡位置和场位容量，植物是两张独立物理实体；只能容纳一只时另一只沿原召唤失败规则处理。

三张必要完整来源为UNG_001翼手龙宝宝（自身一次）、UNG_002火山龙（自身两次）和UNG_103生长孢子（友方群体一次）。保存恢复、clone及动作回放使用独立新注册表；付款只发生在原出牌，后续选择不重复支付或制造第二次使用历史。错误提交或选择后异常回滚到原等待边界，保留已提交付款与原抽样结果。

玩家只看到自己的进化选项，对手只见正在选择的玩家座位；结算后的普通场面属性沿原观察输出。没有输出捕获状态、内部附件或隐藏手牌。本项引入时为prototype-v158/core158、schema153、观察66/命令10/replay1；现行版本见[项目状态](project-status.md)。

这是独立固定结果配方。TLC_229t14等把选中进化授予未来随从的真实特殊来源，以及非构筑的随机自动进化来源，仍按具体卡需要补齐，不据此新增组合矩阵或宣称所有来源适配完成。正式卡池和国服校准继续按既定阶段推进。[实际证据](../outputs/adapt-basics-20261009/verification.json)保留首轮断言失败、受控修正与分批验证范围。
