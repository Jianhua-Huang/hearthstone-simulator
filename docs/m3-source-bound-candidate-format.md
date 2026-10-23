# 固定国服37.0候选域的对局入口

`hs_sim.candidate_format.build_cn37_candidate_format()`把已有源说明、独立完整候选目录、构筑政策和普通生成库存绑定为一个可复现宿主对象。它用于当前已接入内容的完整候选实验，不是正式标准支持证书。实际进度、验证及下一项仍仅在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护。

## 来源和模式

入口读取已有`integration-target-cn37.json`中与源身份相关的语义字段：国服/37.0、适用格式、原补丁与扩展上线时间、源提交及构建、数据哈希和未闭合的正式状态。选定字段具有固定规范哈希；来源、阶段或完整声明变化必须重新核定绑定。历史登记计数和旧库存路径不参与源身份，不为运行入口维护第三份进度台账。

目录继续使用原完整BATCH及政策核验。目标ID、构筑政策ID和池版本绑定源语义、目录哈希、卡牌实现包版本及允许的物理牌身份。两者使用同一目标，模式明确为`experimental`。`DeckPolicy.pool_complete=False`保留正式合法性未知；`PoolDefinition.complete=True`只表示明确候选域的库存完整。不能将后者解释为正式卡池已经核定，`require_formal()`会明确拒绝。

当前固定阶段为国服补丁上线后、黑暗帝国扩展上线前。对象公开该阶段边界，不读取墙钟；已保存对局不会在恢复时按当前日期换池。新上线阶段需要另行冻结和核定，不能将134张预载提前视为当前合法，也不能将这一历史候选阶段冒充后续阶段的最新支持。

## 构筑和生成

构筑允许全部固定候选根，以及实际标准根的奇闻附属物理牌。附属物是否可加入仍由原`FabledSpec`及构筑校验决定，孤立附属物不能因出现在允许列表就变成可收藏根。原30张/40张规则、职业、符文、副本和侧板继续使用共享校验。缺失任意根的实现时明确失败，包括被普通随机排除但仍需正常构筑的根。

普通`constructed.cards`池保留完整候选根和原一身份一权重；`constructed.minions`按同一完整原目录的`MINION`类型投影，保留全部729个随从身份和相同权重。两域均不按实现覆盖裁减，也不把附属物塞入随机库存。原生硬禁令、奇闻、任务、来源家族及各卡查询继续沿原候选管线处理。

随从域服务于卡拉赞的两次印刷8费召唤、艾雅实际药水的随机恶魔和卡扎库斯庭审的三个印刷3费随从；各自原查询、支付、召唤归因、反应、等待与恢复保持。域成员及标识进入格式v2的来源绑定，恢复不能借同名池替换旧库存。这个投影不产生新的正式资格证书；过去卡牌、过去法术和标准卡包等具有独立资格或权重的域不由此推导，缺失域仍报错。

`match_setup()`返回正常`MatchSetup`，`new_game()`直接委托原`Game.from_decks`。原实体、洗牌、换牌、硬币、原牌表及`GenerationContext.starting_decks`由内核建立；格式对象本身不保存某一局的私有状态。宿主可以保留原始Game，玩家仍使用`game.for_player(seat)`，不能把完整快照或原牌表交给玩家。

```python
from hs_sim.candidate_format import build_cn37_candidate_format

candidate = build_cn37_candidate_format()
# deck1/deck2是完整DeckSpec；奇闻名额可先用原expand_fabled_cards展开。
game = candidate.new_game((deck1, deck2), seed=1, first_player=1)
player = game.for_player(1)
```

入口仅需已提交的项目数据；不需要原客户端、提取outputs或联网。旧`build_registry()`继续保持原无宿主候选池的默认行为。固定获取、物理库存、卡牌实现、默认代表包和玩家协议不由此改变。正式禁限、完整生成资格、热修集合、国服校准、实际可达闭合及阶段发布验收仍是原目标的必要门槛。


## 上线后的候选入口与观察性禁用政策

`hs_sim.launch_candidate_format.build_cn37_launch_candidate_format()`是独立的上线后实验入口。原`build_cn37_candidate_format()`继续表示扩展上线前的历史阶段，不按当前日期换池。新入口复用原1188份完整候选记录，以固定37.0源的134份完整记录增量构成1322身份；两份目录不按执行覆盖裁减。普通卡牌域覆盖同一完整清单，随从域只按独立印刷类型投影。

新数据固定三项缺省零数值的双语完整官网主面，并为原始布尔标签缺失的两项印刷关键词保存明确的双语主面依据。共享编译器可显式接收已审核记录与证据；无参路径仍执行原历史目录及其原证据核验。新原始记录中的OLD_GOD等实际标签保留，不能由已实现定义反推未知候选的查询资格。

该实验入口明确采用2026-10-23观察到的国际官方标准禁用清单：DINO_402、TIME_030、TLC_817。它们只进入原`DeckPolicy.banned_card_ids`，不从候选库存、记录或普通生成池删除；已有任务等原生随机禁令仍独立执行。此处没有认证国服禁用的生效时点或完整集合，`cn_bans_verified=False`、`formal_pool_complete=False`及`require_formal()`的拒绝保持。应把这项显式实验政策与正式国服合法性分开理解。

`effective_from`为此固定观察的接受点，`ban_observed_at`保留同一时刻；`expansion_launched_at`单列源说明中的国服扩展上线边界，`effective_until=None`不表示已经证明未来一直有效。入口不读取墙钟或联网；目录、观察、内容版本、构筑允许/禁用集合及两个完整域进入新目标绑定。来源变化需新绑定，不能无声改变保存的对局。

已知牌组可以通过原`Game.from_decks`正常创建；`unimplemented_root_card_ids`公开独立的实现缺口。缺失执行定义的根仍保留独立PoolCard及完整库存位置，绝不创建可出牌的占位白板。实际牌组请求该根由原构筑校验拒绝；查询遇到合格未知成员由原候选管线在抽样前拒绝，正常事务负责回滚付款和RNG。完整候选域不等于完整执行覆盖或正式生成资格。

新宿主仅补缺少的独立元数据和两个显式库存，不改默认构筑注册表、旧来源政策或战斗内核。快照、换牌、原牌表、玩家隔离、恢复和回放复用原Game/DeckPolicy/GenerationContext；旧入口与新入口的目标及注册指纹不同，不能交叉恢复。

```python
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format

candidate = build_cn37_launch_candidate_format()
print(candidate.unimplemented_root_card_ids)
# decks为两个完整DeckSpec；此入口始终为experimental。
game = candidate.new_game(decks, seed=1, first_player=1)
player = game.for_player(1)
```

本入口只绑定普通卡牌和随从域。过去卡牌、过去法术、标准卡包等域必须分别确定成员、年代/身份与适用权重，不能从这两个普通域或组牌禁用列表推导。缺失域继续明确报错；标准卡实际需要的跨系列内容仍属于目标内依赖，不能因所属狂野系列略去。
