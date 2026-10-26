# 本地标准卡包印刷清单

本地专用池宿主另行提供`constructed.standard_pack`，供既有`CORE_WON_145`具象炉石入口调用。此清单依据固定CN37启动候选及已保存的官方集合、赠送和职业系列说明制定本地资格政策，不认证当前国服正式可开包名单。版本对齐及规则边缘按用户要求暂缓。

## 完整来源与资格

[固定数据](../data/cards/standard-pack-printings-v1.json)保留1322张原标准候选的完整原行、逐条分类、原定义摘要和来源；既有标准合法性不变。其中核心集合289条、事件集合21条归入包外集合。六个扩展系列形成1012条原始印刷库存，15条普通赠送版本仍作为成员保留，显式列入`excluded_card_ids`；最终997条有资格，不能通过缺实现、抽到不方便的效果或普通生成限制继续缩小。

| 原CARD_SET | 集合 | 原始成员 | 本地排除 | 合格 |
| --- | --- | ---: | ---: | ---: |
| 1946 | 翡翠梦境 | 183 | 2 | 181 |
| 1952 | 安戈洛龟途 | 183 | 4 | 179 |
| 1957 | 穿越时间流 | 183 | 3 | 180 |
| 1980 | 大地的裂变 | 164 | 2 | 162 |
| 1988 | 逃离紫罗兰监狱 | 164 | 2 | 162 |
| 1994 | 黑暗帝国的统治 | 135 | 2 | 133 |

合格内容包含607随从、336法术、32武器、21地标及1英雄。每个原生成身份只出现一次。构筑的`metadata.deck_identity`与池的`generation_identity`是两种身份，前者不决定生成等价；核心重印的既有构筑别名和生成物理ID均保持。无显式构筑身份的旧回退也由完整定义摘要保全，不从CARD_SET猜出新别名，不通过多个印刷版增加权重。

## 普通赠送版本与外观版本

以下是本地普通版本排除表。`TIME_003`有直接不从扩展包掉落的官方说明；其余14条从独立普通赠送/奖励轨道推断为赠送专属，**仍是本地推断**。保存原始记录及证据，不将这个推断写成已取得的官方穷尽资格标签。

| 原ID | 牌名 | 排除依据 |
| --- | --- | --- |
| EDR_000 | 伊瑟拉，翡翠守护巨龙 | [登录及首包额外发放](https://hearthstone.blizzard.com/en-us/news/24179332/31-6-patch-notes) |
| EDR_844 | 纳拉雷克斯，龙群先锋 | [普通不可制作的奖励传奇](https://hearthstone.blizzard.com/en-us/news/24187142/into-the-emerald-dream-rewards-track-refresh) |
| TLC_106 | 末日使者安布拉 | [登录及首包额外发放](https://hearthstone.blizzard.com/en-us/news/24205006/32-4-patch-notes) |
| TLC_110 | 城市首脑埃舒 | [普通不可制作的奖励传奇](https://hearthstone.blizzard.com/en-us/news/24215170/the-lost-city-of-un-goro-rewards-track-refresh) |
| TLC_252 | 蚀解软泥怪 | [活动后首包额外发放](https://hearthstone.blizzard.com/en-us/news/24205006/32-4-patch-notes) |
| TLC_468 | 黏团焦油 | [商店赠送后首包额外发放](https://hearthstone.blizzard.com/en-us/news/24205006/32-4-patch-notes) |
| TIME_003 | 传送门卫士 | [普通与金色版本均明确不从包掉落](https://hearthstone.blizzard.com/en-us/news/24232759/33-6-patch-notes) |
| TIME_038 | 钟表先生克劳沃斯 | [登录及首包额外发放](https://hearthstone.blizzard.com/en-us/news/24232759/33-6-patch-notes) |
| TIME_064 | 时空领主戴欧斯 | [普通不可制作的奖励传奇](https://hearthstone.blizzard.com/en-us/news/24241547) |
| CATA_720 | 战争大师黑角 | [登录赠送](https://hearthstone.blizzard.com/en-us/news/24242740/34-6-patch-notes) |
| CATA_615 | 吉恩，咒厄国王 | [普通不可制作的奖励传奇](https://hearthstone.blizzard.com/en-us/news/24265937) |
| JAIL_407 | 大头目梵妮莎 | [登录及首包额外发放](https://hearthstone.blizzard.com/en-gb/news/24276661/escape-from-violet-hold-card-reveals-and-rewards-guide) |
| JAIL_850 | 典狱官玛维 | [普通不可制作的奖励传奇](https://news.blizzard.com/en-us/article/24286285/escape-from-violet-hold-rewards-track-refresh) |
| BE_036 | 纯净圣母 | [登录及首包额外发放](https://hearthstone.blizzard.com/en-us/news/24294373) |
| BE_055 | 阿扎达斯 | [普通不可制作的奖励传奇](https://news.blizzard.com/en-us/article/24309582/reign-of-the-black-empire-rewards-track-refresh) |

曾免费送过不代表普通版本不能开出。[31.6说明](https://hearthstone.blizzard.com/en-us/news/24179332/31-6-patch-notes)明确给EDR_105疯狂生物保留开包途径，因此它仍合格。只授予金色、异画或钻石版本的奖励，也不能据此排除同ID的普通版本。普通法术/随从的生成限制、起始牌组条件和构筑禁用继续各自负责自己的入口，不能替代卡包资格。

2026年职业系列不是独立的包外活动集。[大地的裂变职业系列说明](https://hearthstone.blizzard.com/en-us/news/24267730)和[逃离紫罗兰监狱职业系列说明](https://hearthstone.blizzard.com/en-us/news/24293282)均确认可从对应扩展包获得，且包含额外奖励卡。现有MEND/CAP合计58条原印刷全部保留。

## 绑定、执行和保存

[宿主清单v7](../data/cards/local-special-pool-bindings-v7.json)核数据文件哈希；运行时只读仓库内固定数据，不读取outputs或联网。注册阶段核完整1322行、原集合/分类和全部既有定义摘要。普通池、以前的专用池、过去来源视图及构筑政策保持。新目标和注册指纹区分旧存档；旧v6清单保留。

每个合格身份使用本地单位权重；既有`standard-pack-host-weights-v1`有放回接受五个有序occurrence，**没有稀有度保底、账号收藏、重复保护、外观抽样或商店计时器**。这不是对正式开包分布的声称。真实具象炉石的稀有度/槽位分布及额外隐藏排除仍未确认，保存在数据`uncertainties`中。

执行完全沿[原卡包契约](m3-standard-pack-playback.md)：随从召唤、法术自动CAST、武器/地标/英雄安装；不伪造额外手牌付款，不执行物理安装的战吼。接受时冻结完整997条有权重候选、五项顺序和随机证明；等待、来源生命周期、终局、回放和玩家信息边界共用旧内核。没有新增结算器、卡牌定义或模型字段。

全部身份有原生定义是接入前提，不等于重新穷举了997张牌的所有递归效果。未确认专用域、既有近似实现、争议拼装限制及显式未支持的后续路径保持原记录，不借新绑定清除。正式池、版本对应、国服边缘和卡包揭示信息窗口仍独立开放；实际验收和下一项只记原两份台账。
