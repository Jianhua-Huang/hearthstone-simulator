# 固定国服37.0候选域的对局入口

`hs_sim.candidate_format.build_cn37_candidate_format()`把已有源说明、独立完整候选目录、构筑政策和普通生成库存绑定为一个可复现宿主对象。它用于当前已接入内容的完整候选实验，不是正式标准支持证书。实际进度、验证及下一项仍仅在[项目状态](project-status.md)和[机制台账](mechanism-backlog.md)维护。

## 来源和模式

入口读取已有`integration-target-cn37.json`中与源身份相关的语义字段：国服/37.0、适用格式、原补丁与扩展上线时间、源提交及构建、数据哈希和未闭合的正式状态。选定字段具有固定规范哈希；来源、阶段或完整声明变化必须重新核定绑定。历史登记计数和旧库存路径不参与源身份，不为运行入口维护第三份进度台账。

目录继续使用原完整BATCH及政策核验。目标ID、构筑政策ID和池版本绑定源语义、目录哈希、卡牌实现包版本及允许的物理牌身份。两者使用同一目标，模式明确为`experimental`。`DeckPolicy.pool_complete=False`保留正式合法性未知；`PoolDefinition.complete=True`只表示明确候选域的库存完整。不能将后者解释为正式卡池已经核定，`require_formal()`会明确拒绝。

当前固定阶段为国服补丁上线后、黑暗帝国扩展上线前。对象公开该阶段边界，不读取墙钟；已保存对局不会在恢复时按当前日期换池。新上线阶段需要另行冻结和核定，不能将134张预载提前视为当前合法，也不能将这一历史候选阶段冒充后续阶段的最新支持。

## 构筑和生成

构筑允许全部固定候选根，以及实际标准根的奇闻附属物理牌。附属物是否可加入仍由原`FabledSpec`及构筑校验决定，孤立附属物不能因出现在允许列表就变成可收藏根。原30张/40张规则、职业、符文、副本和侧板继续使用共享校验。缺失任意根的实现时明确失败，包括被普通随机排除但仍需正常构筑的根。

普通`constructed.cards`池保留完整候选根和原一身份一权重，不按实现覆盖裁减，也不把附属物塞入随机库存。原生硬禁令、奇闻、任务、来源家族及各卡查询继续沿原候选管线处理。标准卡包等具有独立资格或权重的域不由此推导，缺失域仍报错。

`match_setup()`返回正常`MatchSetup`，`new_game()`直接委托原`Game.from_decks`。原实体、洗牌、换牌、硬币、原牌表及`GenerationContext.starting_decks`由内核建立；格式对象本身不保存某一局的私有状态。宿主可以保留原始Game，玩家仍使用`game.for_player(seat)`，不能把完整快照或原牌表交给玩家。

```python
from hs_sim.candidate_format import build_cn37_candidate_format

candidate = build_cn37_candidate_format()
# deck1/deck2是完整DeckSpec；奇闻名额可先用原expand_fabled_cards展开。
game = candidate.new_game((deck1, deck2), seed=1, first_player=1)
player = game.for_player(1)
```

入口仅需已提交的项目数据；不需要原客户端、提取outputs或联网。旧`build_registry()`继续保持原无宿主候选池的默认行为。固定获取、物理库存、卡牌实现、默认代表包和玩家协议不由此改变。正式禁限、完整生成资格、热修集合、国服校准、实际可达闭合及阶段发布验收仍是原目标的必要门槛。
