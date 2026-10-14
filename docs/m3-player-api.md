# M3 受限玩家操作接口

本页原批次运行时 `prototype-v75` / `core-effects-v75`，snapshot schema 74；观察 DTO 为 `player-view-v44`，命令协议为 `player-actions-v7`。本批完成 M3-03a-02 的原型接口验收，不代表全部正式卡牌或隐藏区域操作已支持。观察记录基础见 [信息契约](m3-information.md)，下一项与总体目标见 [项目状态](project-status.md)。

## 1. 宿主绑定座位，策略只接收 JSON

```python
port = game.for_player(1)  # 由受信任宿主决定座位
listing = port.legal_actions()
if listing['error'] is None and listing['actions']:
    reply = port.submit({
        'revision': listing['revision'],
        'action': listing['actions'][0],
    })
    assert reply['accepted']
```

`observe()` 返回 `version/revision/observation`；`legal_actions()` 在此基础上返回完整可枚举动作列表和 `error`。只在普通行动时受当前行动权限制；playing边界的非主动方仍有本人认输命令，详见[独立认输契约](m3-logical-concession.md)。`events(after=cursor)` 仍使用该座位的过滤日志与游标。

`submit()` 只接受 `revision/action` 两个字段。成功返回最新观察、修订值、`accepted: true`、`error: null` 及本次操作新产生的玩家日志。失败返回 `accepted: false`、固定错误码和空事件列表，不返回异常原文、全知摘要或原始 `ActionResult`。

命令中没有可改写的玩家 ID，演员由 Port 的固定座位决定；猜测内核实体 ID、伪造对手手牌来源、给命令追加座位字段均拒绝。Port 本身仍是宿主 Python 对象，不能作为进程沙箱或联网认证。只将返回的 JSON DTO 交给策略/客户端；连接、对局及座位的授权绑定由外部宿主负责。原有 `Game.state/legal_actions/apply/snapshot` 等全知接口继续用于测试与宿主回放。

## 2. 玩家动作格式

| 操作 | `action` 对象 |
| --- | --- |
| 出牌 | `{"type":"play_card","card":"e5","target":null,"position":0}` |
| 磁力出牌 | 同一出牌动作增加可选 `"magnetic_target":"e8"`；由位置决定宿主，独立登场为 `null`，不一致的提示会拒绝 |
| 手牌操作 | `{"type":"use_hand_action","card":"e5","action_id":"forge"}` |
| 星舰发射 | `{"type":"launch_starship","starship":"e8"}` |
| 地标使用 | `{"type":"use_location","location":"e8","target":null}` |
| 随从能力 | `{"type":"use_minion_ability","minion":"e7","ability_id":"TTN_903t3","target":null}` |
| 技能 | `{"type":"use_hero_power","power":"e2","target":"e8"}` |
| 攻击 | `{"type":"attack","attacker":"e7","defender":"e8"}` |
| 结束回合 | `{"type":"end_turn"}` |
| 认输 | `{"type":"concede"}` |
| 交互物 | `{"type":"use_interactable","object":"e8","card":"e5"}` |
| 提交选择 | `{"type":"select_choice","choice":"c1","options":["o1"]}` |

`e...` 是本座位观察到的实体句柄；`c.../o...` 是本座位当前选择/选项句柄，均不等于内核 ID。出牌的 `target/position`、技能、地标及随从能力的 `target` 可省略，按 `None` 处理。未知字段、布尔位置、重复或未知选项、非当前手牌/技能来源明确拒绝；地标来源必须为己方在场地标。洗回牌库退休的句柄即使配上新的修订值也不能使用。

选择可以属于非当前回合玩家。此时只有选择方得到选择动作；另一座位仍可独立认输。恢复后的同一观察仍得到相同句柄和修订值，可继续提交并重算宿主回放。

交易/锻造的独立费用、可见条件与形态保留见 [额外手牌动作](m3-hand-actions.md)。直接提交手牌动作不执行该卡普通出牌的目标条件；自己的观察显示动作描述，敌方牌背不显示。

## 3. 修订值与事务

`revision` 是当前玩家观察 DTO 的规范化 SHA-256，不包含全知状态、隐藏牌序或 RNG。两个对该玩家完全相同的观察有相同修订值，不能用它来猜测不同暗牌状态。它是过期观察检测值，不是秘密凭证，也不是跨对局唯一 ID；命令必须始终在所属宿主对局/座位通道提交。

可见状态或玩家事件游标改变后，旧修订值返回 `stale_observation`。通过检查后，句柄转换为宿主 Action，复用原有 `Game.validate/apply` 的费用、目标、攻击、选择和事务规则；没有第二套会产生不同结算结果的出牌器。

失败不消耗牌、资源、选择，也不保留曾在事务副本中发生的揭示、RNG 变化或过滤日志。回放继续保存宿主 Action 和完整摘要，玩家命令只是输入适配层。

## 4. 可见信息条件回调

旧回调默认使用 `RuleContext`，可读取整个局面，继续供受信任宿主实验使用。不能仅把其枚举结果的 ID 换成句柄后发送给玩家：真假结果或候选数量本身也可能暴露隐藏信息。

玩家可调用的自定义条件必须显式注册：

```python
registry.register_target_rule(
    'friendly-minion',
    lambda c: c.target['zone'] == 'board' and c.target['controller'] == c.player_id,
    visibility='player',
)
registry.register_use_rule(
    'first-power-this-turn',
    lambda c: c.observation['players'][c.player_id - 1]['hero_power_uses_this_turn'] == 0,
    visibility='player',
)
```

这些回调收到 `PlayerRuleContext(player_id, observation, source, target)`，全部为独立玩家 DTO 副本，没有 `state/source_id/target_id`、内核计数、RNG 或执行帧。技能使用条件的 target 为 `None`。手牌牌背的上下文只附带公开槽位所属玩家、区域及已有身份信息，不补入隐藏数值。

宿主校验和玩家提交执行的是同一回调及同一玩家上下文。返回值必须严格为 bool；异常或非法返回由玩家接口转换为固定错误码。修改上下文副本不会改动真实对局。回调依然是受信任代码，须保持纯函数，不得通过闭包捕获全知 Game 等外部可变状态。

内置 `any_character/any_entity/always` 是已审查的内核谓词，使用声明和公开区域事实；扩展不能注册为 `builtin` 来绕过检查。条件的 `visibility` 进入注册表指纹，语义改变仍须提升内容版本。真实代表包与合成包的自定义条件均已迁移，该原批次版本分别为 `representative-m5-v38` 和 `synthetic-mechanics-v3`；现行身份见[项目状态](project-status.md)。

观察 v2 补充当前卡牌类型、随从是否本回合入场、英雄技能回合累计次数及公共场地/手牌容量，让这些合法性条件有明确可见依据。

## 5. 目标域与明确不支持的情况

支持英雄、战场、武器、技能等公开区域，以及自己的手牌。自己的牌面和费用可供条件读取。

对手手牌可以按牌背选择，但 TargetSpec 的种类集合必须覆盖当前全部合法手牌种类（MINION/SPELL/WEAPON/LOCATION/HERO），条件须为内置谓词或 `visibility='player'`。这样不会先用真实隐藏类型过滤候选；玩家条件只根据其实际可见的牌背/已知信息判断。显式选择的牌背可出现在出牌/技能日志中，身份仍保持隐藏。

按隐藏类型筛选对手手牌，以及直接选牌库/墓地实体，当前返回 `unsupported_target_domain`。这些场景需要后续的揭示、候选选择或区域操作契约，不能悄悄删掉隐藏候选再声称完整枚举。旧全知条件返回 `unsupported_rule`，而不是用真实隐藏状态尝试执行该条件。

正常行动方手牌或技能中有不支持的声明时，`legal_actions()` 返回 `actions: null` 和错误码，明确表示未获得完整列表。仍可直接提交受支持的动作，例如结束回合；提交只检查实际来源的支持声明。等待选择时不检查无关手牌条件。

公开的错误码：

| 错误码 | 含义 |
| --- | --- |
| `invalid_action` | 格式、座位、句柄或正常规则不允许此操作 |
| `stale_observation` | 命令基于过期的玩家观察 |
| `unsupported_rule` | 来源使用尚未迁移的全知条件 |
| `unsupported_target_domain` | 目标域依赖尚未支持的隐藏信息操作 |
| `enumeration_limit` | 选择组合超过工程枚举预算，可按已显示选项直接提交 |
| `rule_error` | 枚举中的受信任条件异常或非法返回 |
| `resolution_failed` | 校验回调或结算失败；操作未提交 |

动作列表在投影后按玩家字段稳定排序，避免内核 ID 顺序暴露隐藏实体创建历史。信息隔离保证针对发送的 DTO 与声明支持的合法性路径；执行效果后公开出现的正常游戏结果仍会改变观察。

## 6. 验证与完整对局

```powershell
python -m unittest discover -s tests -p test_m3_player_api.py -v
python -m examples.play_as_players
python -m hs_sim replay outputs/players-complete-replay.json --card-set representative
```

[完整玩家对局示例](../examples/play_as_players.py) 的策略函数只接收当前座位的 JSON 观察和动作列表；完成换牌、出牌、攻击、技能与回合，宿主在终局后单独重算完整回放。它是固定演示策略，不表示战术质量或国服正式卡组合法性。

当前固定样例为 45 次动作、228 条原始事件，第 11 回合玩家 1 获胜，双方英雄 6 / -1 血；双方各有 184 条过滤事件、46 个观察边界。当前 v73 摘要为 `8d7d20a41036f3199c1bbb8f4bd9b8c5342b0702b7cb95381855869be39d3047`。双方各自的消息记录分别保存到 `outputs/player-api-1.json` / `outputs/player-api-2.json`；宿主全知回放保存在 `outputs/players-complete-replay.json`，不可作为玩家消息发送。

[36 项接口测试](../tests/test_m3_player_api.py) 覆盖隐藏状态不同但动作列表/修订值相同、乱序内核 ID、座位/输入/过期限制、暗牌目标、共享条件、错误清理、选择预算及恢复回放。全量验证结果维护在项目状态；静态池及手牌/牌库选择已接入，正式完整池仍待 M0/M6/M7，星舰基础链路已内部验收，地标通用入口与星港已内部验收，英雄牌/雷诺发射历史已内部验收，一般休眠与唤醒已内部验收，泰坦能力也已内部验收，任务/任务线进度也已内部验收，持续目标与玩家长期效果也已内部验收，奥秘与打断窗口已内部验收，M5-01 初始依赖盘点、出牌历史/连击/流放已内部验收，M5-02 法术迸发/暴怒与有限次触发已内部验收，M5-03 存储升级、手牌进度/腐蚀/注能已内部验收，M5-04 额外出牌条件已内部验收，M5-05 磁力已内部验收，M5-06 巨型已内部验收，M5-07a 兆示基础已内部验收，M5-07b-01 相邻光环/生成费用及三职业代表已内部验收，M5-07b-02 术士相邻牺牲已内部验收，M5-07b-03a 死亡之翼/奥卓克希昂已内部验收，M5-07b-03b-01 古加尔牌库销毁已内部验收，M5-07b-03b-02 关键词光环/艾萨拉已内部验收，M5-07b-03b-03 奥拉基尔已内部验收，M5-07b-03b-04 希奈丝特拉已内部验收，M5-07b-03b-05 奥妮克希亚已内部验收，M5-07c 兆示组合收尾与 M5-08 裂变普通法术公共子集已内部验收；M5-09a 印刷回响与临时手牌已内部验收；M5-09b/c 双生法术与微缩/巨化已有 44 项内部测试；M5-09d 动态回响/手牌关键词光环已有 55 项内部测试；M5-10a 招募/死亡历史复活已有 62 项内部测试；M5-10b 自动施法与独立历史已有 54 项内部测试；M5-10c 抽到时施放与抽取链已有 60 项内部测试；M5-10d 历史重施/历史发现与池内批量施法已有 68 项内部测试；M5-11a 回溯检查点通过 58 项专项；M5-11b 次数卡面与生命周期通过 45 项专项；M5-11c 保留多结果通过 55 项专项；多技能组合已内部验收，当前执行位置见 [项目状态](project-status.md)。

泰坦能力使用独立稳定 `ability_id`，不暴露附件 ID。玩家可见条件和隐藏目标域的限制也适用于随从能力；场上未用能力的声明进入枚举前检查，来源必须为己方在场随从。详见 [随从能力契约](m4-minion-abilities.md)。

M5-12d-01：主技能 `hero_power_id` 与有序 `additional_hero_power_ids` 分别保存；派生 `hero_power_ids` 供统一枚举，`AddHeroPower` 安装额外实体。手动动作、费用/次数、在位监听和观察/恢复处理所有已安装技能；刷新/替换/间接触发的空引用默认指主位；12d-02 已支持捕获引用的定向操作，见 [技能生命周期](m5-power-lifecycle.md)。见 [多技能契约与 R-107](m5-multiple-powers.md)。

v73复验：play_as_players.py 为 45 动作/230 事件。动作及其余摘要字段相对v72保持；事件增量来自独立战吼的开始/完成宿主记录，玩家过滤日志不新增这些事件。本页原批次的验收数字保留为历史；逐项比较见[示例核对](../outputs/v73-example-count-check.json)。

v76复验说明：上文原批次契约和验收数字保留为历史；当前运行结果为play_as_players.py：45动作/248事件。完整结果及摘要见[59示例日志](../outputs/v76-examples.txt)；随从承诺/入场阶段变化见[反制契约](m5-minion-counters.md)。
