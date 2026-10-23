# M3 发现与随机生成候选池

本页描述 M3-03b-01 静态版本池基础与实验代表卡；当前运行时版本见[项目状态](project-status.md)。[区域操作](m3-zones.md)及[能力条件筛选](m5-ability-filters.md)已接入，完整国服正式池仍未冻结。底层代码见 [pools.py](../hs_sim/engine/pools.py)。

## 三种数据各自负责什么

| 数据 | 职责 | 不代表什么 |
| --- | --- | --- |
| `DeckPolicy` | 校验构筑模式、卡组数量、职业、符文、禁限及合法 ID | 不决定一张牌能否被生成 |
| `PoolCard` / `PoolDefinition` | 描述生成候选的印刷元数据、成员、权重、排除与版本 | 元数据存在不表示行为已经实现 |
| `Registry.cards` | 可执行定义、行为及其依赖 | 不能用它自动裁剪正式候选池 |

候选元数据允许先于可执行定义存在。过滤依据池声明、`PoolQuery` 与显式 `GenerationPolicy`；随后对**全部合格候选**检查可执行定义，再去重与抽样。只要有一个合格候选未实现，本次动作明确报错并回滚，即使随机数本可能不抽中它。已实现别名也不能遮蔽同身份的未实现候选。没有根据覆盖率重抽或删牌的降级路径。

注册表在开局冻结，两个池表只读，定义及成员为不可变值。候选元数据、池版本、成员、权重、排除和完整性声明进入注册表指纹；更换它们后原存档不能直接恢复。Python 行为函数体仍不进入指纹，语义修改继续要求提升内容/机制版本。

## 绑定目标和模式

池按 `(id, target_id, mode)` 注册，同族池可以分别提供 experimental、standard、wild 清单，没有跨模式或目标版本回退。`PoolDefinition.version` 固定该份名单的版本；同键重复注册明确拒绝。

`Game.from_decks` 从构筑策略派生 `GenerationContext(target_id, mode)`。从场景测试时须显式提供该上下文；未提供的场景仍可执行其他机制，调用池效果则报错。上下文进入克隆、快照和摘要；恢复构筑对局时必须与构筑策略一致。

standard/wild 池要求显式 `complete=True`。这只是受信任宿主的输入声明，**不能代替 M0 的国服完整池审计**。目前代表包只注册 experimental 池，正式模式查询会明确失败。

## 过滤与抽样契约

`PoolQuery` 为可序列化值，不接受闭包或任意表达式。

| 条件 | 当前含义 |
| --- | --- |
| `kinds` | 印刷卡牌类型；空元组不限制 |
| `ability` | 显式当前/印刷能力条件；基础生成候选以 `PoolCard.battlecry` 判断，未知不能当成 false，见[能力筛选契约](m5-ability-filters.md) |
| `min_cost` / `max_cost` | 印刷费用的闭区间；不读取手牌减费或费用光环 |
| `collectible` | True/False 显式过滤；None 不限制，衍生物不会自动被删去 |
| `class_mode` | any；current 当前英雄职业；other 不含当前英雄职业；specified 与指定职业集合有交集 |
| `classes` / `include_neutral` | specified 才填写职业；中立牌由独立布尔值控制，默认允许 |
| `rarities` / `tribes_any` | 稀有度与任一种族匹配；需要的元数据未知则报错 |
| `spell_schools` / `keywords_all` | 印刷法术派系匹配，或具备全部列出的印刷关键词 |
| `exclude_card_ids` | 显式排除 ID 及已声明的同生成身份别名 |
| `exclude_source` | 执行效果时按来源实体当前牌 ID 排除及其生成身份；要求存在来源 |

current/other 读取执行时英雄定义的职业，英雄替换后随之变化；不使用开局职业作为永久替代。缺少英雄职业、非标准中立英雄或多职业英雄当前明确拒绝。other 对多职业卡要求其职业集合不含当前职业，中立仍由 `include_neutral` 控制。特殊职业、符文与单卡例外尚需后续扩展及 M6 校准。

生成去重使用显式 `PoolCard.identity`，默认牌 ID；不自动套用构筑 `deck_identity`。同池别名必须具有相同过滤元数据及权重，否则冻结时拒绝。合格成员按牌 ID 排序，检查全部行为后，每个身份保留字典序首个 ID；排除一个已知身份会排除其全部别名。

`PoolMember.weight` 是正整数，默认 1。抽样使用对局独有 RNG 的整数区间，无隐藏职业权重。发现不放回，同身份不会重复展示；普通生成可声明放回或不放回。不放回数量超过可用身份时取全部可用身份；空池不消耗 RNG、不弹出选择，后续效果继续。每次抽样都遵循此版本算法，不承诺复现官方服务器 RNG。

## 公共效果和挂起恢复

```python
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolQuery

def discover_three_cost(ctx):
    return [DiscoverFromPool(
        ctx.player_id, 'representative.generation',
        PoolQuery(min_cost=3, max_cost=3, collectible=True,
                  class_mode='current', exclude_source=True),
        source_id=ctx.source_id,
    )]

def random_minion(ctx):
    from hs_sim.engine import CardType
    return [GenerateFromPool(ctx.player_id, 'representative.generation',
        PoolQuery(kinds=(CardType.MINION,)), destination='board')]
```

这些是依赖已注册池和上下文的行为片段。默认 `DiscoverFromPool.count=3`，抽样后将少量选项交给已有 `RequestChoice`；每个选项保存带类型的选择分支，默认选择后通过 `AddToHand` 获得。选择前不创建卡牌实体，选择后创建新实体；满手遵循现有烧牌规则。候选总池可大于 `max_choice_options`，限制应用于展示选项数，不截断候选总池。

`GenerateFromPool.count=1`、`replacement=True`、`destination='hand'` 为默认值，也支持 board 和 deck。先校验所有合格候选能进入目的区域，再抽样整批，最后通过 `AddToHand` / `Summon` / `AddToDeck` 逐个执行。因此牌加入手牌触发另一次选择时，已抽好的后续牌保存在结算帧中，恢复后不再抽样。hand/deck 目前支持随从/法术/武器，board 只允许随从；其他类型明确拒绝，满场复用召唤失败规则。生成到牌库使用 position 指定 top/bottom/random 或整数间隙；插入位置在执行该次加入时解析，详见区域契约。

失败回滚到最近已提交边界，包含实体 ID、状态、RNG、事件及玩家知识。发现已经挂起后，选择分支失败会保留该次已提交选项；不会回滚到更早出牌前再抽一次。连续候选查询和生成效果也可进入允许类型的帧编码。

选项只发送给选择者，对手只看到有人正在选择。生成入手的身份沿用 `AddToHand` 的私有规则，烧牌公开沿用现有原型契约。玩家提交只使用 `PlayerPort` 句柄；宿主快照/完整回放包含秘密，不能给玩家当观察数据。可见性及具体触发窗口仍待 M6。

## 代表卡、证据与可运行示例

宝石甲虫 `LOE_029` 的本地记录已固定 SHA256：`c8454eb4877eff9470fd5cbf34e6b712fa3cf69ba025c4d43dc7e61d26d64aac`。手写战吼使用三费、可收藏、当前职业加中立过滤。`representative-m5-v38` 中 `GENERATION_SAMPLE_IDS` 明列 15 条样本，池版本为 `representative-generation-v1`、`complete=False`；不是从当前实现集合自动生成的正式池。新增卡仍为 partial / internally_tested，当前代表记录共 269 条。狐人恶棍仍未注册，其特殊分支和完整池没有被本批冒充完成。

历史一手证据用于解释基础选择：官方 [探险者协会介绍](https://news.blizzard.com/en-us/article/19932699/join-the-league-of-explorers-on-november-12) 描述从三个职业可用候选中选择；[2019-09-10 更新](https://hearthstone.blizzard.com/en-us/news/23097372) 取消随机发现池的职业权重加成；[18.0.1 官方热修帖](https://us.forums.blizzard.com/en/hearthstone/t/1801-server-hotfix/39314) 描述随机生成/发现排除自身，同时明确牌库内另一张暗影视界属于例外。这些不是当前国服完整候选名单或官方校准记录，因此排除由效果显式声明，不能一刀切套用于未来区域内选择。

```powershell
python -m examples.discover_from_pool
python -m unittest discover -s tests -p test_m3_pools.py -q
```

[示例](../examples/discover_from_pool.py) 通过玩家 DTO 出牌和选择，保存等待快照及完整回放，恢复后选择同一张牌并验证另一分支。固定 seed 29 的样本候选依次为 `EX1_019`、`CS2_117`、`CS2_122`；选择首项后两次动作、8 条原始事件，摘要为 `b9c271118e7239c6e9590d1c1af109d08892ae4faeff11d158a8a89b4a9fd8b9`。对手仍只看到未知手牌。

[41 项生成测试](../tests/test_m3_pools.py) 覆盖目标/模式、元数据、别名/权重/排除、未知实现、容量、私有选项、触发中断、恢复/回放、预算和失败回滚。全量验证记录在项目状态。M3-03b-02 区域操作与区域内候选已内部验收，[M3-03c 手牌操作及跨层对局](m3-hand-actions.md) 也已内部验收，星舰基础链路已内部验收，地标通用入口与星港已内部验收，英雄牌/雷诺发射历史已内部验收，一般休眠与唤醒已内部验收，泰坦能力也已内部验收，任务/任务线进度也已内部验收，持续目标与玩家长期效果也已内部验收，奥秘与打断窗口已内部验收，M5-01 初始依赖盘点、出牌历史/连击/流放已内部验收，M5-02 法术迸发/暴怒与有限次触发已内部验收，M5-03 存储升级、手牌进度/腐蚀/注能已内部验收，M5-04 额外出牌条件已内部验收，M5-05 磁力已内部验收，M5-06 巨型已内部验收，M5-07a 兆示基础已内部验收，M5-07b-01 相邻光环/生成费用及三职业代表已内部验收，M5-07b-02 术士相邻牺牲已内部验收，M5-07b-03a 死亡之翼/奥卓克希昂已内部验收，M5-07b-03b-01 古加尔牌库销毁已内部验收，M5-07b-03b-02 关键词光环/艾萨拉已内部验收，M5-07b-03b-03 奥拉基尔已内部验收，M5-07b-03b-04 希奈丝特拉已内部验收，M5-07b-03b-05 奥妮克希亚已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)；正式完整池与国服部署证据继续由 M0/M3-02b/M6/M7 跟踪。

M5-12b-02b 已扩展 `GenerationPolicy` 和多轮发现：可指定 `discoveries`、`delivery`、跨轮 `replacement`、目的区域及生成费用，见 [特殊资格、交付与 R-097](m5-discovery-delivery.md)。普通默认排除仍保留，正式池未知；这部分另有 48 项专项。

M5-12c-03c：`SummonFromPool` 在执行时验证版本池候选、检查场位再抽样，连续调用逐次重新检查场位。传送门复用物理洗入、抽到施放和玩家灌注累计，在施法行为中捕获费用查询；见 [R-105 契约](m5-imbue-portals.md)。

M5-12c-03d：`quote_generated_cost` 与实际手牌共用费用核心，`ChooseFromPools` 对各组独立抽样并冻结选择；`CreateTemporaryCard(cost=..., cost_expires_turn=...)` 在创建事件前装入期限与费用。支付能力不等于完整出牌合法性，见 [R-106 契约](m5-pool-offers.md)。

v73复验：discover_from_pool.py 为 2 动作/10 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为discover_from_pool.py：2动作/12事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 玛洛恩的具名荒野之神查询

EDR_888复用普通DiscoverFromPool与CostSpec。两份完整双语主面的childIds给出15个关联内容，其中11个可收藏传说随从恰好每职业一个，组成固定具名候选；其余四项关联原行也保留，不作为候选。查询用完整card_ids和任意职业政策，不把所有传说野兽当荒野之神，也不因缺失效果删去真实成员。资格清单不认证这些生成卡的全部效果或正式标准池。

条件沿既有imbue_count默认执行记录口径，在原战吼RuleContext中判断是否达到4次，达到后随原发现请求捕获设为1费配方；后来灌注不改写旧菜单，下一次实际战吼重新捕获。技能使用次数、当前技能卡面或等级不代替原记录。无技能职业的无效果记录仍沿R-100本地政策计入条件，其准确国服语义和精确捕获/交付窗继续待M6，见[灌注契约](m5-imbue.md)。


## K479 两组原生固定关键词衍生池

TTN_860无人机拆解器的八种火花机器人，以及WC_028集合石的八种冒险者，按[完整来源包](../data/cards/past-fixed-keyword-tokens-v1.json)的真实双语母面childIds和完整原行声明。八份火花磁力附魔通过原2787/853双向身份关联保留为证据；实际磁力由既有合体器构造属性/能力组，不注册ENCHANTMENT白板。子面没有独立官网校验，精确国服分布与时序仍待校准。

两种实际获取均使用原GenerateFromCandidates。完整具名列表不依赖GenerationContext或标准合法池，不为已实现覆盖裁候选；原执行器先校验全部可手持定义，再以既有均匀抽样产生普通AddToHand。满手仍选择并由同一工厂烧掉完整实体，副本不是发现。通用标准随机/发现池仍依独立PoolDefinition及M0审计，不能从这两份固定名单推定完成。

无人机保持普通机械战吼；八种火花为1/1磁力机械，原bonus、宿主种族及当前实体材料进入既有磁力/关键词生命周期。集合石保持0/2及本人自然结束声明，沿旧主体捕获、控制、重复和恢复机制取得2/2冒险者。奥术冒险者通过spell_damage声明原法伤1，鬼祟冒险者保留亡灵。集合石原缺ATK标签只依两完整母面0按共享工具窄printed-zero政策声明，不修改源行。

本次只增加卡牌/声明，core701/schema560和全部公共内核文件保持，内容v569。实际验收、差异和下一项仍仅维护在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)。


## K480 七种跟班与具名魂匣

[完整配方](../data/cards/past-lackey-prime-v1.json)保留两母卡、七跟班、终极魂匣及两个证据对象的12完整原行和22完整双语主面。DAL_433的完整childIds包含七个MARK_OF_EVIL随从和另一个获取跟班的转校生；只有前七项构成固定随机配方。MARK_OF_EVIL通过共享元数据解析为lackey子类型，1359只作为提供者原证据，不等同成员。固定名单按原GenerateFromCandidates验证全部定义、统一抽样与普通入手/烧牌，不拿全局注册表补名单或按覆盖率裁剪。

每种跟班继续组合公共效果：无面用constructed.cards二费可收藏随从查询和原召唤原因，效果召唤不执行被召唤者战吼；狗头人用MINION_ABILITY伤害而非法术；地精/泰坦分别普通Buff与GrantKeyword；女巫捕获原MinionReference并沿TransformMinionFromPool的印刷费用+1政策；虚灵和龙族用当前英雄职业、可收藏及相应法术/龙条件的原发现菜单。空池、未知合格候选、原目标、选择/交付、容量、重复和私有信息仍归原执行器。这里的配方不是完整正式constructed池或CN抽样分布认证。

淤泥吞食者的过载仅为普通手动on_play效果，与可重复战吼获取分离；普通效果和真实闪回召唤均不执行这两入口。灵魂之匣亡语只复用recruit_cards.shuffle和语义洗牌/AddToDeck，按原死亡控制者生成新的具名Prime；不回用死者物理ID或复制所有旧附件。Prime的实际关键词与有限条件见[回合契约](m2-controller-turn-keyword-auras.md#k480-对手回合的本体扰魔)。

DRG_303仍是完整来源证据，不是本批可执行牌。当前标准候选根没有迦拉克隆资格组，原普通生成按不可变起始牌组先排除不合格祈求牌，再要求所有合格候选有完整定义；不是用已实现名单缩池。此范围判断不证明所有具名/跨卡来源不可达，也不认证M0正式池，实际审查和后续只在原台账维护。


## K481 永久成长与青玉展品

[完整配方](../data/cards/past-persistent-minion-rewards-v1.json)保存BAR_031、TSC_653、TOY_803三主卡及两份原附魔证据；三主卡的六份完整双语官网面与源记录一致。原文分别描述永久+2/+1的暴怒新复制、永久+2/+2的牌库底后继和本局同族+1/+1再洗入两个新体，不能共用一套全局成长计数。

迅猛龙用原LimitedTriggerSpec.frenzy，存活首次实际承伤后执行一次；同一原体不重复、致死不触发，后继新体获得自己的原限定触发。掠食鱼用普通原亡语，额外亡语各自生成同样原成长值的一份新复制；不是把同一身体的下一份重复提前算成新一代。两者由[物理永久属性](m3-zones.md#k481-原物理复制的永久印刷属性)冻结来源并调用原基础复制器；原语义随机洗牌与bottom位置分开，底部放置不消耗插入RNG或伪造洗牌任务信用。实际死亡控制者决定接收方，来源复制/转授仍以原完整材料为准。

青玉展品直接组合AddPlayerEffect及PlayerAuraSpec(1,1,(TOY_803,),scope='controlled_minion_cards')，再使用原具名语义洗牌放入两张展品。每次真实亡语安装独立持久实例，HAND/DECK/PLAY/BOARD及后来生成者按当前控制者的旧公共族规则计算；复制不携带旧控制者的光环缓存，转控重新计算。它不使用JadeGolem计数或永久物理层，也不为每张牌复制一个独立属性解释器。

两份原附魔只作完整证据，不注册成可执行牌。复制材料范围、普通族作用/沉默政策、原接受/发布窗口及当前国服一致性仍单独登记；这些配方不认证全部生成域或标准环境完成。


## K482 原实体入库与原伤害目标变形

CFM_095鼬鼠挖掘工的亡语把原实体移入对手牌库；VAC_958进化融合怪把原实体带当前本地附魔移入本人牌库。它们使用[同一有限原物理写入器](m3-master-dusk-dead-shuffles.md#k482-原物理随从的有限接收牌库与附魔保留)，不按卡ID造新副本，不把一次重复亡语变成多份原实体。归属、容量、重置、随机信用、附件材料和等待恢复共用公共机制；融合怪保留真实ALL种族。

BT_731传染孢子只消费本体实际`damage_dealt`且数量为正的原事件，对仍存活/活跃的原随从接收者捕获`MinionReference`，交`TransformCapturedMinion`变成真实BT_731。来源随后死亡不追加“必须存活”条件，先前反应已改变目标驻留则原引用跳过；英雄、无实际伤害与已致死目标不换面。双方伤害、支付、死亡与变形仍由原执行器负责，精确CN时序待校准。
