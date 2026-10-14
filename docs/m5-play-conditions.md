# M5-04：额外出牌条件与手牌获取历史

当前 `prototype-v75` / `core-effects-v75`，snapshot schema 74，`representative-m5-v38`、`player-view-v44`。这批建立压轴、法力渴求、快枪手的公共条件与六张代表卡；正式卡池、特殊动态费用、非手牌施放和国服精确时序仍未完成。

## 冻结条件，不从行为结束后的状态推测

`PlayRecord` 继续保存原出牌身份、费用与位置，新增 `mana_before`、`mana_after`、`mana_crystals`、`hand_entry_id`、`hand_entry_turn` 和 `manathirst_threshold`。提交前用同一权威报价预测此次支付后的法力，之后支付/出牌反应不会重写这些事实。

| 查询 | 当前公共语义 |
| --- | --- |
| `context.play.finale` | 此次支付后可用法力为零；零费牌在零法力时满足 |
| `context.play.manathirst` | 提交时永久晶体数达到该定义的门槛；不额外支付门槛值 |
| `context.play.quickdraw` | 该实体最近一次成功进入当前手牌的全局回合等于出牌回合 |
| `context.play.mana_crystals` | 当时永久晶体数量，可供多门槛行为分别比较 |

压轴计算包含可用临时法力、已支付法力和过载锁定的影响。支付生命/护甲/尸体不会扣法力，因此该类支付只在当时已无可用法力时满足当前压轴条件。法力渴求包含用过和锁定的永久晶体，不包含硬币提供的临时法力。即时补法力、增加晶体等反应发生在冻结之后，不追认或撤销本次条件。

上述精确冻结窗口、零费与替代支付规则由 **R-063** 跟踪。官方关键词介绍支持基本方向，但尚未证明这些边界全部符合国服目标版本。

## 成功进入手牌的独立历史

`GameState.hand_entries` 保存不可变 `HandEntryRecord`：单调 ID、实体、控制者、当时卡名、全局回合、根动作号、区域修订、原区域及进入原因。`Entity.hand_entry_id` 指向该实体最近一次记录；出牌冻结对应记录 ID 和回合。卡牌之后换形、回手或易主不会改写旧历史。

公共创建和移区路径写入记录，卡牌行为不自行标记快枪手。`hand_history.enter_hand` 是内核生命周期助手；正常扩展应调用既有生成、抽取、复制、回手或移动效果。

| 来源或操作 | 是否新增获取记录 |
| --- | --- |
| 正常抽牌、定向抽取、成功生成到手牌 | 是；记录实际回合 |
| 复制到手牌，基础或当前状态复制 | 是；新实体获得自己的记录，原卡不刷新 |
| 回手、从牌库移回、转交另一玩家手牌 | 是；按最终手牌控制者记录 |
| 手牌中改费、增益、重排、腐蚀/注能升级、锻造 | 否；没有重新进入手牌 |
| 将手牌移动到原手牌 | 否；保持原记录 |
| 交易 | 交易来源进入牌库不增加；实际抽到的牌增加 |
| 满手烧牌、生成失败烧毁、疲劳 | 否；没有成功获取 |
| 初始场景手牌 | 记为 turn 0，表示场景开始前已持有 |
| 构筑起手发牌、换牌替换与硬币 | 记为 turn 0；不会因第一回合而自动满足快枪手 |
| 开局完成后的第一回合抽牌 | 记为 turn 1，满足当回合条件 |

对手回合获得的牌记录对手所在的全局回合；到了自己的下一回合不会继续满足。升级保留获取历史，即使牌面和区域引用修订改变；真正离开再回到手牌则新增记录。**R-064** 跟踪起手、获取、换形及特殊复制的正式例外。

这里记录的是成功的手牌获取，不是全部抽牌尝试、生成来源树或公开事件历史。它不能代替未来“每当抽牌”、从其他区域施放等独立契约。

## 声明、目标与玩家入口

```python
from hs_sim.engine import CardDefinition, CardType, Keyword

card = CardDefinition(
    'example.thirst', '示例', CardType.SPELL,
    cost=1, keywords=(Keyword.MANATHIRST,), manathirst=8,
    on_play='registered.behavior',
)
# registered.behavior 通过 context.play.manathirst 选择公共效果。
```

MANATHIRST 关键词必须配合正整数 `CardDefinition.manathirst` 门槛；不允许布尔值、负数或只加裸标记。`GrantKeyword` 不用于动态授予这些出牌机制，强制开启条件需要另建契约。

`target_condition` 在原 combo/outcast 外新增 finale/manathirst/quickdraw，需有对应印刷关键词与目标声明。`play_definition` 统一供合法性、枚举、玩家命令及法术改目标使用：不满足则无条件目标，满足则遵守原 REQUIRED / IF_AVAILABLE / OPTIONAL 策略。已有基础目标不能通过此字段随意删除；例如补水始终需要治疗目标，日斑巨龙则只在快枪手时选择伤害目标。

`preplay_conditions(state, entity, registry)` 返回全部五类条件；旧两参数查询仅保留无需报价/定义即可计算的连击、流放、快枪手。完整玩家观察始终使用注册表，控制者手牌新增 `play_conditions` 布尔字段。对手手牌即使身份曾揭示也不会获得这些私有条件；完整获取历史、内部 ID、费用快照均不直接暴露。

## 恢复与验证

schema 74 保存获取历史及冻结条件，明确拒绝旧 1～71。恢复检查历史类型、回合/动作顺序、实体和区域修订、最新记录指针、出牌关联及门槛定义；重新计算摘要不能绕过结构校验。历史本身不是服务端签名，不宣称能认证任意重写后仍自洽的完整游戏。

等待选择的继续帧保存原 PlayRecord；之后的法力变化不能改写选择回调读取的条件。生成后请求选择可保存新获取记录，恢复后继续在同回合使用。异常回滚包含获取历史、指针、实体分配和资源。当前玩家命令 v6（新增磁力位置提示），外层 replay schema 1。

| 代表卡 | 覆盖点 |
| --- | --- |
| ETC_325 音乐治疗师 | 压轴获得吸血与突袭组合 |
| JAM_017 突破邪火 | 零费法术授予突袭，压轴额外 +1/+1；战士/恶魔猎手双职业 |
| RLK_843 奥术箭 | 法力渴求 8，2/3 点法术伤害分支 |
| RLK_518 银月城哨兵 | 法力渴求 8，+2/+2 与圣盾 |
| WW_434 日斑巨龙 | 快枪手条件目标、6 点伤害/吸血与交易 |
| WW_823 补水 | 治疗后在快枪手时刷新两个法力水晶 |

全部来自同一冻结本地源并固定逐条哈希，零费缺省、龙种族与双职业掩码分别核对。仍标为 partial；例如脱水的快枪手动态费用、不同施放来源以及完整条件卡池不由这六张自动代表。

50 项专项覆盖资源边界、获取生命周期、起手/换牌、选择恢复、反制、玩家接口、回滚和篡改载荷。`examples.extra_play_conditions` 使用八次玩家命令：幽灵视觉从左侧流放抽到两张快枪手牌，补水刷新法力，日斑巨龙伤害，再用硬币调节压轴与法力渴求；中途保存和完整回放一致。这是混合职业机制场景，不是正式合法卡组。

```powershell
python -m unittest discover -s tests -p test_m5_play_conditions.py -q
python -m examples.extra_play_conditions
python -m hs_sim replay outputs/extra-conditions-replay.json --card-set representative
```

基础规则来源：[压轴官方介绍](https://news.blizzard.com/en-gb/article/23935243/o-festival-das-lendas-ja-comecou)、[法力渴求官方介绍](https://news.blizzard.com/en-us/article/23885940/march-of-the-lich-king-is-now-live)、[快枪手官方介绍](https://news.blizzard.com/en-gb/article/24008695/showdown-in-the-badlands-is-now-live)。这三篇介绍未证明全部精确窗口，R-063/R-064 继续保留到国服 M6。

M5-05 [磁力合体与附件归属](m5-magnetic.md) 已内部验收；下一项按 [依赖盘点](m5-inventory.md) 推进 M5-11 回溯结果选择与重算；奥妮克希亚生命损失替换已内部验收；关键词光环/艾萨拉已内部验收；死亡之翼与奥卓克希昂已在 [b-03a](m5-deathwing.md) 内部验收。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为extra_play_conditions.py：8动作/48事件；play_conditions.py：5动作/30事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。


## 原生手动资格的独立前置

可被储存并不等于可从手牌手动打出。原生manual_playable声明在上述报价/条件和主体执行之前维护手动资格，付款证明绑定原始卡面；hand_playable仍用于物理区域结构。见[原生资格契约](m3-manual-play-eligibility.md)。这不定义自动CAST或完整殒命暗影的复制主体。
