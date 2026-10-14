# M0：目标版本与代表卡基线

核查日期：2026-09-23。本页配合 [长期计划](roadmap.md) 和 [项目状态](project-status.md)，解释机器清单的来源、口径及维护方法。

## 已核实的事实

- 本地安装目录为 `D:\游戏\Hearthstone`，不存在 `.build.info`。从 `.product.db` 的长度限定 protobuf 字段路径 `4.1.7` 读取到完整字符串 **`36.6.0.251952`**；游戏 build 记为 **251952**。这是安装元数据所声明的客户端版本，不是服务器规则版本。
- 对本地 `Data/Win/dbf.unity3d` 和 `Hearthstone_Data/Managed/Assembly-CSharp.dll` 重新计算 SHA256，与已有提取 manifest 一致。清单同时保存 `.product.db`、提取 manifest 和 `cards.json` 的指纹。读取过程未启动客户端。
- `Hearthstone.exe` 的 `6000.3.11f1` 是 Unity 产品版本，不能拿来判断炉石补丁。
- 本地提取数据的 `zhCN` 是文本语言，不能据此推断玩家所在服务器地区。
- 官方 36.6 公告正文日期为 2026-09-15，包含构筑修复及后续资料片预告。预告和预加载不能直接计入已经上线的卡池。[官方公告](https://hearthstone.blizzard.com/en-us/news/24294373)
- 36.6.1 是官方声明于 2026-09-22 推送的**服务端热修**，其中也有构筑修复，涉及此前打出计数、休眠变形和受伤后的属性交互等。因此规则候选更新为 **36.6.1**，不把它当成本地 36.6.0.251952 的文件版本。[官方热修公告](https://us.forums.blizzard.com/en/hearthstone/t/3661-hotfix-patch/165846)
- 国服官网 2026-09-16 的 36.6 公告确认当日发布，包含传统对战修复。[国服 36.6 补丁说明](https://hs.blizzard.cn/news/24294373/index.html)
- 国服公告预告 36.6.1 酒馆更新于 9 月 23 日上线；这不能证明完整构筑热修也已部署，本次没有找到足以确认后者的国服逐项公告。[国服相关公告](https://hs.blizzard.cn/news/24302069/)

用户已确认最终验收地区为**国服（CN）**；这是目标选择，不是从客户端语言推断的部署事实。尚未确认：国服精确生效时间、完整构筑热修集合、标准/狂野合法池及可达内容。对应字段保存 `null` 或明确的未完成状态，并列入阻塞项。本次清单不声明支持最新正式补丁。


2026-09-24 补充 C-005：冻结的 `TIME_038` 原始文本写三次回溯，而 [国服 34.0 官方补丁](https://hs.blizzard.cn/news/24243857/) 已改为两次。当前有效覆盖、后续修订和衍生卡面映射仍待核实，原始文件和哈希保持不变，不按旧文本直接注册当前钟表先生。公共次数卡面机制由合成定义验证，见 [回溯卡面](m5-rewind-forms.md)。

## 两份机器清单

1. [目标 manifest](../data/targets/local-2026-09-23.json)：版本、文件来源、运行时审计起点、证据索引和缺口。
2. [机制与代表卡台账](../data/support/m1-representatives.json)：初始机制与后续增量的依赖关系，当前 100 类机制及 305 个真实卡牌/衍生物快照和双状态。

大型原始提取数据仍位于被忽略的 `data/extracted/`。上述两份小清单可随项目保存，加载与校验不依赖本机游戏或大型提取文件。文件来源中的绝对路径只是历史证据定位，不是运行时依赖；文件 SHA256 是完整性标识，不是发布方签名。

### 字段语义

| 字段 | 含义 |
| --- | --- |
| `target.rules.candidate_patch` | 正在核查的规则补丁；不代表已实现 |
| `target.rules.region/effective_at` | 规则地区与实际生效时间；`null` 表示未知 |
| `target.data.client_version/build` | 安装元数据声明的本地版本，不等同服务端热修 |
| `target.runtime.baseline_*` | M0 开始时审计的原型版本；后续代码升级不改变这个历史事实 |
| `target.extensions.current_runtime` | 当前开发版本的注解；实际兼容性仍由引擎快照/回放校验决定 |
| `support.coverage_kind` | 当前固定为 `representative_sample` |
| `support.full_pool_count` | 当前必须为 `null`；不能把 16 张样本或 36,022 条数据库记录当完整分母 |
| `card.data` | 提取文件中该条记录的原始内容，保留标签、文本、关联信息和未知/缺失数值 |
| `card.data_sha256` | 原始记录按稳定 JSON 排序编码后的 SHA256，用于发现快照变化 |
| `card.dependencies` | 所需机制 ID；非关键词文本的机制也必须登记 |
| `card.reachable_cards` | 已识别的衍生卡 ID；例如蛛魔之卵关联 `FP1_007t` |
| `card.mode_legality` | 按目标补丁核实后填写 `legal/illegal`；`null` 表示尚未判断 |
| `extensions` | 原样保存的注解；不能覆盖支持状态、版本或校验行为 |

Schema 1 **不允许声明完整支持**，只接受 `none/prototype_subset`。未来 M7/M8 完整验收需要升级 schema，引入经过审核的合法根卡与可达内容分母、构筑限制、生成池和校准门槛，不能通过修改一个字符串宣称完成。

未识别的 schema 字段报错，避免拼写错误被忽略；需要保留的未来注解放在 `extensions`。原始 `card.data` 本身是被哈希保护的来源快照，不会把其中的未知标签自动解释成机制。

### 实现与验证分别维护

| 维度 | 可选状态 | 说明 |
| --- | --- | --- |
| `implementation` | `not_started` | 已盘点，尚未接入执行 |
| | `partial` | 有可执行子集，已知范围差异仍保留 |
| | `implemented` | 台账所描述范围已实现；不自动代表官方一致 |
| `verification` | `unverified` | 没有相应执行验证记录 |
| | `internally_tested` | 内部用例通过，必须引用测试证据 |
| | `officially_calibrated` | 还必须引用明确的校准记录；官方简短机制说明不能单独满足此状态 |

实现完成的根卡不能引用未开始的机制或未完成的衍生物。所有证据、机制依赖和可达卡引用必须存在；机制依赖循环会被拒绝。状态校验只保证声明结构自洽，不能代替执行测试或人工审核证据是否足够。

## 第一批代表卡

这些是**本地 build 的具体记录**，不代表该 ID 在目标标准模式中可用。旧系列、核心系列和其他模式的相似 ID 不能自动合并。

| ID | 代表卡 | 验证目的 |
| --- | --- | --- |
| `CS2_182` | 冰风雪人 | 普通实体、属性、召唤与攻击 |
| `CS2_179` | 森金持盾卫士 | 印刷嘲讽及移除 |
| `CS2_029` | 火球术 | 定向伤害；完整行为还依赖 M2 法术伤害 |
| `CS2_009` | 野性印记 | 属性附魔与授予嘲讽；当前快照为 **+2/+3** |
| `EX1_332` | 沉默 | 移除可沉默状态 |
| `CS2_203` | 铁喙猫头鹰 | 战吼沉默及目标规则 |
| `EX1_581` | 闷棍 | 敌方随从回手与重置 |
| `EX1_096` | 战利品贮藏者 | 亡语抽牌及疲劳交互 |
| `FP1_007` | 蛛魔之卵 | 死亡后召唤与满场 |
| `FP1_007t` | 蛛魔 | 根卡可达的衍生物 |
| `CS2_122` | 团队领袖 | 光环来源失效与重新派生 |
| `ULD_205` | 夺烛木乃伊 | 单独复生 |
| `ULD_208` | 卡塔图防御者 | 复生、嘲讽与亡语治疗组合 |
| `CS2_188` | 叫嚣的中士 | 本回合攻击力附魔与到期 |
| `EX1_019` | 破碎残阳祭司 | 友方目标与永久属性附魔 |
| `EX1_012` | 血法师萨尔诺斯 | 明确保留 M2 法伤依赖，不能只做亡语就宣称完整 |

`ULD_209` 经核实是狐人恶棍，文本涉及发现，并不是简单复生随从；没有因为相邻 ID 而错误接入。`EX1_332.cost` 和 `FP1_007.attack` 在原始提取结果中为 `null`（缺省标签），快照原样保留；执行适配器如采用零缺省值，必须显式写出，不能在通用读取器中把所有未知值都转换为零。

复生的官方说明只确认首次死亡后以 1 点剩余生命返回。亡语排序、附魔重置和满场交互等仍需独立的契约与校准用例。[官方复生说明](https://news.blizzard.com/en-us/article/23076826/hearthstone-update-august-1-saviors-of-uldum)

## API 与维护

```python
from hs_sim.targets import load_baseline, summarize_baseline, validate_baseline

baseline = load_baseline()
validate_baseline(baseline.target, baseline.support)
print(summarize_baseline(baseline))
```

`load_baseline(target_path, support_path=None)` 可读其他目标文件；默认从目标文件相对位置加载 `support_file`。返回对象是普通 JSON 数据的独立副本，调用方可用于报告，不会触发导入卡牌、动态执行代码或下载文件。

每次完成一个增量：

1. 对照机制和卡牌记录更新实现状态及限制，未接入的效果仍明确拒绝。
2. 实际运行相关测试后再登记 `internal_tests` 证据；引用具体测试位置和本次验证结果。
3. 增加或修改代表卡时，从锁定源快照复制真实记录并重算 `data_sha256`；规则手写实现与来源数据分开。
4. 新规则证据区分“官方描述”和“具体校准记录”。不要因找到了一个官网链接就升级为 `officially_calibrated`。
5. 新目标补丁使用新 target ID 和相应快照，不覆盖旧来源；运行时语义升级继续遵守规则/内容/schema 版本契约。
6. 同步 [项目状态](project-status.md)，保留仍然阻止完整支持的缺口。

本增量验证：`python -m unittest discover -s tests -p test_targets.py -v`，**25 项通过**。测试使用小型内存/临时文件 fixture，覆盖引用缺失、依赖循环、快照篡改、非法完整声明、状态证据约束、JSON 重复键及未知字段语义。实际两份清单也已通过 API 校验。该结果验证的是清单管理功能，不是 16 张卡的战斗行为。

随后 M1 接入 15 张实验适配，M2 又加入血法师；又补充 4 张战斗状态、3 张属性运算和 9 张武器/技能/衍生物代表记录，并补充 6 条费用/资源及 8 条伤害/治疗记录；M3 又加入滋养、两个初始英雄、宝石甲虫及三张区域操作代表卡，又加入五条交易/锻造及升级形态记录，M4 又加入 35 条星舰/地标/英雄相关记录（含三个专用选择描述）、四条休眠记录、五条泰坦/能力/衍生物记录、七条任务/阶段/奖励记录、三条持续目标/咒符/长期效果记录、九条奥秘/衍生物记录、六条连击/流放记录及八条有限次触发记录，另有十四条腐蚀/注能形态和六条额外出牌条件代表，截至该阶段 282 条均为 partial / internally_tested。当时运行时注解为 prototype-v84 / core-effects-v84 / snapshot 81，历史 runtime 审计起点保持不变。旧卡原始数据与指纹未改动；新增记录取自同一已校验的源文件。整体验收结果与下一步统一见项目状态。

M2 新增代表：寒冰箭 CS2_024（冻结）、寒刃勇士 ICC_820（冲锋/吸血）、狼人渗透者 EX1_010（潜行）、暴风城勇士 CS2_222（攻击/生命光环）。来源仍为锁定本地 build；当前正式合法性未由这些样本推断。

M2 属性运算代表：心灵之火 CS1_129、神圣之灵 CS2_236、疯狂的炼金师 EX1_059。三条源记录均在核对完整 cards.json SHA256 后冻结；复杂属性顺序与受伤生命契约尚未官方校准。

M2-04 新增武器 CS2_106、CS2_082、FP1_021，基础技能 HERO_08bp、HERO_03bp、HERO_01bp、HERO_04bp、HERO_06bp，以及技能衍生物 CS2_101t。显式映射武器 HEALTH 为耐久；技能不是手牌。该批 32 条记录都只声明部分实现与内部测试。

M2-05 增加幸运币、激活、伺机待发、巫师学徒、闪电箭、吸血鬼之血六条实验记录。加入官方生命/护甲支付与尸体基础说明，证据范围见 [资源契约](m2-resources.md)；完整卡池分母、国服热修闭环和官方校准状态保持未完成。

M2-06 新增八条规则层代表记录，并明确七类法术派系映射；该历史批次运行时为 v8 / schema 8，共 46 条适配、33 类机制。源数据文件及新增单卡指纹已核对，全部卡牌保持 partial / internally_tested；详见 [伤害与治疗规则](m2-health-rules.md)。

M3-01/02 增加滋养、吉安娜和加尔鲁什初始英雄，代表包当时为 representative-m3-v2，共 49 条样本、35 类机制。构筑校验与完整普通开局已内部验收，新增职业/稀有度/符文等冻结元数据，但标准/狂野完整合法池仍未知。实验卡组不能反向成为正式合法池；见 [开局契约](m3-opening.md)。

M3-03a-01 增加独立的玩家观察/信息台账，目前跟踪 36 类机制；只读 DTO、显式手牌揭示与事件时点日志已内部测试。受限玩家动作随后由 M3-03a-02 完成原型验收，完整候选池继续由 M3 跟踪，见 [信息契约](m3-information.md)。完整正式卡池分母保持未知。

M3-03a-02 的可见条件回调与固定座位命令已内部验收；代表包因条件上下文迁移提升为 `representative-m3-v3`，合成包为 `synthetic-mechanics-v3`，49 条原始冻结记录及指纹不变。玩家 DTO 为 `player-view-v2`，命令协议为 `player-actions-v1`；完整实验对局已只用玩家 DTO 驱动，仍不提高为官方校准或完整池支持。

M3-03b-01 冻结宝石甲虫 `LOE_029` 的本地记录并接入实验发现，代表包为 `representative-m3-v4`，共 50 条样本。`representative-generation-v1` 明列 15 条库存，只注册 experimental；没有标准/狂野完整池声明。41 项生成池测试通过，新增三条历史官方发现规则证据，均不替代国服当前补丁校准；见 [生成池契约](m3-generation.md)。

M3-03b-02 新冻结暗影视界 UNG_029、亡者之牌 ICC_091、灵魂之火 EX1_308，代表包为 representative-m3-v5，共 53 条样本；新增区域机制台账后跟踪 37 类。44 项区域测试通过，观察协议为 player-view-v3，命令仍为 player-actions-v1。静态实验库存仍为 15 条，不扩成正式池；区域内选择只使用本局实体。官方时序、容量和特殊区域触发缺口继续保留，见 [区域操作契约](m3-zones.md)。


M3-03c 冻结厚重板甲 SW_094、独眼突击者 TTN_042/TTN_042t、风暴巨人 TTN_724/TTN_724t 五条记录，代表包 representative-m3-v6 共 58 条样本，新增 hand_actions 后跟踪 38 类机制。45 项手牌动作/跨层测试通过，命令协议提升至 player-actions-v2，观察为 player-view-v4，运行时 v15/schema 15。交易基础费用、随机插入及附魔保留和锻造基础费用有历史官方证据；国服当前补丁细粒度时序、可见性、特殊费用修正与完整池仍未完成验收。见 [手牌动作契约](m3-hand-actions.md)。

M4-01a 新增 12 条记录：四种真实星舰组件、七种原舰体及多职业战列巡航舰。代表包 representative-m4-v1 共 70 条记录；38 类机制中星舰从 not_started 改为 partial / internally_tested，仍无正式全池分母。运行时 prototype-v16 / core-effects-v16、snapshot 16、player-view-v5、player-actions-v3；baseline_* 历史起点不改。46 项星舰用例与 780 项全量回归通过。官方 FAQ 和 32.2 规则说明仅作历史依据，精细时序/回手费用仍待国服校准。


M4-01b-01 新增 13 条真实记录：SCV、四类人族发射衍生组件、陆战队员、回收地堡、超级电容器、大和炮、锁定、飞弹舱、震荡弹、引力置换器。当前 representative-m4-v2 共 83 条，全部保持 partial / internally_tested；完整池仍未知。运行时 prototype-v17 / core-effects-v17、snapshot 17、player-view-v6、player-actions-v3。原始 cards.json SHA256 及新增单条投影哈希均已校验；baseline_* 历史起点不变。新增 42 项测试，全量 822 项通过（42.772 秒）。32.0 解放者修复作为窄范围官方依据，整组延迟死亡属于暂定实现；31.6 酒馆升级从构筑要求中排除。下一项为埃索达协议。

M4-01b-03b 新冻结星港 SC_403 与赤红深渊 CORE_REV_990；前者可达五组件列表完整保留，后者验证定向地标能力。来源 cards.json SHA256 为 `fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`，两条投影 SHA256 分别为 `6ad33d818e5109a1d4a7322ddc19aed4e27ecb26ead3f47cef274e7f12362baf` 与 `8bda7b70ff39b83637d3a6f95d35c811642173a596de53fb0c4b1914f64cb815`。所有 91 条代表记录仍为 partial / internally_tested；新增 locations 后共 41 类机制，完整池分母仍未知。

当前运行时 v20/schema 20、representative-m4-v5、player-view-v7、player-actions-v4；baseline_* 历史字段及旧样本来源不变。新增 42 项地标测试，全量 940 项通过（56.766 秒），星港实例十一动作/63 事件且保存恢复、玩家命令、重算回放及 CLI 校验一致。官方地标基础/移除/场位/亡语证据已登记，但 R-037 精确时序仍为暂定契约；国服热修和正式合法池继续待核实。下一项为英雄牌入口、雷诺/强化剂与发射历史，见 [地标契约](m4-locations.md)。


M4-01b-02 新增埃索达 GDB_120 和三个协议 GDB_100a/b/c，共四条冻结记录；representative-m4-v3 合计 87 条，其中三个是 choice-only 描述，不能生成或打出。runtime 注解为 prototype-v18 / core-effects-v18 / snapshot 18，观察 player-view-v6、命令 player-actions-v3 保持；baseline_* 历史起点不变。43 项新增协议测试通过，全量 865 项通过（46.350 秒）。真实卡三个分支均以玩家指令完成、恢复并重算回放，攻击分支 CLI 回放通过。官方 31.0.3 只支持埃索达七费 6/8 的历史调整；协议时序、离场/变形和来源边界仍为 R-034，待国服 M6。下一项为铁鸦完整候选及发射历史。


M4-01b-03a 新冻结铁鸦 SC_403c 与升空 SC_410，代表包 representative-m4-v4 合计 89 条记录；新增 elusive / bonus_effects 两类台账，共 40 类。runtime 注解 prototype-v19 / core-effects-v19 / snapshot 19，拒绝旧 1～18，历史 baseline_* 保持。33 项专项与 898 项全量回归通过（46.944 秒），新真实卡五动作/42 事件示例恢复和 CLI 回放通过。公开目标规则、独立派系与完整五组件候选已接入；八种额外效果清单/边界和升空时序留待国服校准，星港/雷诺分别依赖地标/英雄牌公共入口。


M4-01b-03c 冻结吉姆·雷诺 SC_400 与强化剂 SC_400p，投影 SHA256 分别为 `d28f22a5e294c2e3b09ddbc1391c8575c660583b7ef0f9600888b4145f879602` 与 `2406578f407568782902972ed05dc7a18df04e1c59f7c6c667a64f4d23fc2313`。来源文件哈希再次核对为上述同一 cards.json，旧原始投影和 baseline_* 不变；新增可达链为雷诺 → 强化剂 → 已有陆战队员。全部 93 条仍为 partial / internally_tested，41 类机制与完整池缺口保持明确。

当前运行时 v21/schema 21、representative-m4-v6、player-view-v8、player-actions-v4。44 项英雄/历史专项与全量 984 项（54.085 秒）通过；雷诺示例七动作/48 事件，保存恢复、玩家命令与 CLI 回放一致。英雄牌历史官方基础和雷诺介绍证据已登记，R-038/R-039 精细行为仍待国服校准；下一项为一般休眠/唤醒，见 [英雄牌与历史契约](m4-heroes-history.md)。


### 2026-09-24 M4-02a 休眠记录与运行时

从同一已核验 cards.json（SHA256 `fd0a3412afa031504f0553210670d6c14ce02ca952819f7524514a8003b86c08`）冻结 BT_004、BT_156、BT_737、TSC_647，逐条投影哈希存入小型台账并由适配器锁定。97 条代表内容均 partial / internally_tested；新增 dormancy 后共 42 类机制（7 implemented / 35 partial）。当前运行时 v22/schema 22，representative-m4-v7、player-view-v9、player-actions-v4；历史 baseline_* 和来源原始字段不改写。

38 项休眠测试和全量 1,022 项（58.254 秒）通过，15 个示例重跑、休眠示例恢复/回放/CLI 核验通过。三个历史官方资料已登记，R-040/R-041 仍待国服校准，详见 [休眠契约](m4-dormancy.md)。下一项为泰坦等有限次主动能力，国服完整热修与正式池缺口不因本批完成而关闭。


### 2026-09-24 M4-02b 泰坦增量

从已核验的同一原始数据文件冻结 TTN_903、TTN_903t/t2/t3/t4 五条记录。代表包 representative-m4-v8 共 102 条，包含六条非物理描述，另有测试英雄；新增 minion_abilities 后共 43 类机制（7 implemented / 36 partial）。样本均 partial / internally_tested，完整池分母不变。运行时 v23/schema 23、player-view-v10、player-actions-v5；历史 baseline_* 与既有原始数据未改写。

54 项专项与全量 1,076 项（64.709 秒）通过，16 个示例重跑；艾欧娜尔 8 动作/35 事件，保存恢复、完整重算回放与 CLI 一致。官方 FAQ/开发者首帖作为规则方向证据登记，R-042/R-043 仍待国服校准；精确范围见 [随从能力契约](m4-minion-abilities.md)。下一项任务/任务线与长期进度。


### 2026-09-24 M4-03a 任务增量

同一已核验 cards.json 冻结 ULD_155/ULD_155p、SW_428/SW_428t/SW_428t2/SW_428t4、DRG_008 七条记录。representative-m4-v9 共 109 条真实记录（八条非物理描述），全部 partial / internally_tested；44 类机制（7 implemented / 37 partial）。当前运行时 v24/schema 24、player-view-v11、player-actions-v5；baseline_* 历史起点不变。

42 项任务测试及全量 1,118 项（72.095 秒）通过，17 个示例重跑，任务线 47 动作/233 事件、恢复/回放/CLI 一致。历史官方证据支持基本方向，R-044/R-045/R-046 仍待国服校准，见 [任务契约](m4-quests.md)。下一项持续目标与玩家长期效果，地区热修与完整池缺口继续保留。

## M4-03b 增量审计（2026-09-24）

同一已校验原始 cards.json 冻结丹巴达尔桥 AV_344、烈焰咒符 BAR_306、奥术师晨拥 SW_450t4 三条记录，逐条 SHA256 纳入适配器校验。代表包 representative-m4-v10 共 112 条真实记录/113 条注册定义，八条非物理描述；45 类机制（7 implemented / 38 partial），全部样本仍 partial / internally_tested，完整正式卡池分母仍未知。

当前运行时 prototype-v25 / core-effects-v25、snapshot 25、player-view-v12，命令 player-actions-v5、外层 replay 1 不变；baseline_* 历史起点保留。55 项专项及全量 1,173 项（77.845 秒）通过，18 个示例重跑。新例子 12 次操作/54 条事件，来源死亡后法伤仍影响咒符，保存恢复与逐步 CLI 回放一致；R-047/R-048/R-049 待国服校准，详见 [玩家效果契约](m4-player-effects.md)。下一项 M4-04 奥秘与打断窗口。

## M4-04 增量审计（2026-09-24）

从同一已校验原始 cards.json 冻结七个奥秘及两个衍生物，逐条 SHA256 进入适配器校验。代表包 representative-m4-v11：121 条真实记录/122 条注册定义、八条非物理描述；46 类机制（7 implemented / 39 partial），新奥秘机制与九条内容均内部验证，所有卡牌仍 partial，正式池分母未知。

运行时 prototype-v26 / core-effects-v26、snapshot 26、player-view-v13；命令 v5、外层 replay 1 保持，baseline_* 历史起点未改。64 项专项与全量 1,237 项（87.738 秒）通过，19 个示例重跑。新例子 9 操作/48 事件，保存恢复、完整重算和 CLI 回放一致。9.2 反制施法反应与早期奥秘回合规则等官方证据已登记；共享五位、实时检查、攻击/施法替换和隐藏表现仍须国服 M6 校准，见 [奥秘契约](m4-secrets.md)。下一项 M5-01 依赖盘点与历史/出牌条件设计。

## M5-01 增量审计（2026-09-24）

从同一已校验原始 cards.json 冻结六条连击/流放记录，原始哈希纳入代表包 representative-m5-v1；127 条真实记录/128 条定义、八条非物理描述；49 类机制（7 implemented / 42 partial），均内部验证，所有卡牌仍 partial。runtime 注解为 prototype-v27 / core-effects-v27、snapshot 27、player-view-v14；命令 v5、外层 replay 1、baseline_* 历史起点不变。

43 项条件/历史、11 项盘点测试与全量 1,291 项（92.246 秒）通过，20 个示例重跑；新场景 5 动作/23 事件，中途恢复与 CLI 回放一致。机器依赖计划和本地调查报告另列扩展引用，26 组机制族与 124 个未归类命名标签仍非正式合法池；原始 8,170 条 collectible 标记记录不构成分母。R-054/R-055 与模式/版本核查仍开放，详见 [历史契约](m5-play-history.md) 和 [机制盘点](m5-inventory.md)。下一项 M5-02 一次性触发。

## M5-02 增量审计（2026-09-24）

新增八条法术迸发/暴怒代表，固定源和旧样本哈希不变。representative-m5-v2 共 135 条真实记录/136 定义、八条非物理描述；52 类机制（7 implemented / 45 partial），全部内部验证，卡牌全部 partial。runtime 为 prototype-v28 / core-effects-v28、snapshot 28、player-view-v15，命令 v5 与外层 replay 1 保持。

60 项专项与全量 1,351 项（110.554 秒）通过，21 示例重跑；新组合通过玩家入口 5 动作/39 事件、存档恢复与 CLI 回放。官方介绍只支持基本语义，R-056～058 精确窗口和费用仍待校准，见 [有限次触发契约](m5-limited-triggers.md)。依赖报告重新生成，完整合法池分母仍未知；下一项 M5-03 手牌内进度/腐蚀/注能。

## M5-03a 增量审计（2026-09-24）

没有新增卡牌快照或改动原始哈希；真实代表仍 135 条/136 定义。新增存储升级机制跟踪，合计 53 类（7 implemented / 46 partial）。规则 prototype-v29 / core-effects-v29、snapshot 29、player-view-v16；代表包 representative-m5-v2、命令 v5、外层 replay 1 保持。39 项基础与全量 1,390 项（114.778 秒）通过，21 示例重跑及交易/锻造 CLI 验证。自动腐蚀/注能仍未接入，下一项 M5-03b，详见 [升级基础](m5-hand-upgrades.md)。

## M5-03b 增量审计（2026-09-24）

增加七组腐蚀/注能共十四条形态，来源仍为固定本地快照，逐条哈希已核对。当前 149 条真实记录/150 定义，56 类机制（7 implemented / 49 partial），均 internally_tested；正式池分母未知。prototype-v30 / core-effects-v30、snapshot 30、representative-m5-v3、player-view-v17，命令 v5/回放外层 1 不变。62 项专项与全量 1,452 项（121.354 秒）通过，22 示例通过。详见 [手牌进度契约](m5-hand-progress.md)，正式时序与特殊生命周期例外仍待国服 M6。

## M5-04 增量审计（2026-09-24）

新增六条压轴/法力渴求/快枪手代表，来源不变，逐条哈希已核对。当前 155 条真实记录/156 定义，60 类机制（7 implemented / 53 partial），均 internally_tested；完整池分母仍未知。prototype-v31 / core-effects-v31、snapshot 31、representative-m5-v4、player-view-v18，命令 v5/回放外层 1 不变。50 项专项、全量 1,502 项（132.264 秒）以及 23 示例通过；额外条件八步、构筑四步和交易/锻造完整对局 CLI 重算通过。详见 [额外条件与获取历史](m5-play-conditions.md)，正式窗口与特殊获取例外仍待国服 M6。

## M5-05 增量审计（2026-09-24）

新增八条磁力真实记录，固定源及逐条哈希保持可追踪。当前 163 条真实记录/164 定义、61 类机制（7 implemented / 54 partial），均 internally_tested；正式分母仍未知。prototype-v32 / core-effects-v32、snapshot 32、representative-m5-v5、player-view-v19、player-actions-v6。55 项专项、全量 1,560 项（144.153 秒）和 24 示例通过；磁力及既有完整对局 CLI 回放通过。详见 [磁力契约](m5-magnetic.md)，R-065/R-066 和国服校准未关闭。

## M5-06 增量审计（2026-09-24）

新增十三条巨型主体/附肢记录，固定数据源及逐条哈希继续使用。当前 176 条真实记录/177 定义、62 类机制（7 implemented / 55 partial），均 internally_tested；完整合法池分母仍未知。prototype-v33 / core-effects-v33、snapshot 33、representative-m5-v6、player-view-v20。52 项专项、全量 1,609 项（151.733 秒）及 25 示例通过；巨型/四步构筑/交易锻造 CLI 回放通过。见 [巨型契约](m5-colossal.md)。

国服 [“大地的裂变”正式上线](https://hs.blizzard.cn/news/24250357/index.html)确认 HERALD/SHATTER 为已上线构筑机制，分别列为兆示、裂变任务；该证据不代替当前目标补丁的卡牌数值、全部热修和合法池确认。正式窗口 R-067/R-068 继续待 M6。

M5-07a 审计：十二条兆示相关真实记录加入，共 188 条/189 定义；63 类机制（7 implemented / 56 partial），均 internally_tested。prototype-v34 / core-effects-v34、snapshot 34、representative-m5-v7、player-view-v21。53 项专项、全量 1,662 项与 26 个示例通过。战士/恶魔猎手分支与公共基础已内部验收，其余四职业、死亡之翼/奥卓克希昂以及国服精确规则仍待续；完整卡池分母仍 null。

M5-07b-01 审计：相邻光环、生成费用/期限及萨满/潜行者/死亡骑士十二条记录加入，共 200 条/201 定义；63 类机制均内部验证、真实卡全部 partial。prototype-v35 / core-effects-v35、snapshot 35、representative-m5-v8；玩家视图 v21、命令 v6 不变。42 项新增专项、全量 1,704 项及 27 示例通过。五职业士兵有实验适配；术士、死亡之翼/奥卓克希昂、相关主体特殊规则、正式生成池与国服精确窗口保留为后续。

M5-07b-02 审计：捕获随从引用、动态相邻牺牲/条件增益与术士四条记录加入，共 204 条/205 定义，六职业士兵均有实验适配。prototype-v36 / core-effects-v36、snapshot 36、representative-m5-v9；玩家视图 v21、命令 v6 保持。46 项新增专项、全量 1,750 项和 28 示例通过。古加尔主体牌库消灭替换、死亡之翼/奥卓克希昂与其他巨型主体特殊规则仍待续；正式池和国服集中校准未完成。


M5-07b-03a 同源冻结 CATA_190h/p/t10/t11/t12/t13/t14、CATA_497、EX1_563 九条记录，总计 213 条样本/214 定义，十二条 choice-only 描述；63 类机制仍 7 implemented / 56 partial，所有真实卡仍 partial / internally_tested。prototype-v37/core-effects-v37、snapshot 37、representative-m5-v10；45 项专项、全量 1,795 项与 29 示例通过。新增独立的两卡传说龙实验池；正式标准/狂野合法池仍未知，R-075/R-076 不宣称国服校准通过，见 [死亡之翼契约](m5-deathwing.md)。


M5-07b-03b-01 从相同冻结源加入 CATA_726 古加尔主体，总计 214 条样本/215 定义；63 类机制的 implemented/partial 分类未扩张。运行时 prototype-v38/core-effects-v38、snapshot 38、representative-m5-v11、player-view-v22。50 项专项、全量 1,845 项与 30 示例通过；牌库销毁独立于场上死亡，古加尔实时替换使用相同成功续接。新增两条官方历史修复来源，正式池分母与国服集中时序认证保持未知，见 [牌库销毁契约](m5-deck-destruction.md)。


## 2026-09-24：M5-07b-03b-02 关键词光环与艾萨拉

从同一冻结源新增艾萨拉 CATA_151，逐条哈希与元数据保留在机器清单中；215 条真实内容/216 定义，十二条 choice-only 描述，63 类机制（7 implemented / 56 partial），全部 internally_tested，真实卡均 partial。prototype-v39 / core-effects-v39、snapshot 39、representative-m5-v12；player-view-v22 与玩家命令 v6 不变。

47 项专项、全量 1,892 项（219.926 秒）及 31 示例通过，艾萨拉十一动作/54 事件且 CLI 回放通过。风怒、其他七种持续关键词、来源撤销与攻击次数交互使用公共光环附件；国服 R-079、其他巨型主体、正式池和集中校准未完成，见 [关键词光环契约](m5-keyword-auras.md)。


## 2026-09-24：M5-07b-03b-03 奥拉基尔与十费候选

同一冻结源新增 CATA_153、OG_141，原始记录和逐条哈希保存在机器台账；当前 217 条真实内容/218 定义、63 类机制（7 implemented / 56 partial），均 internally_tested，真实卡仍 partial。prototype-v40 / core-effects-v40、snapshot 40、representative-m5-v13，player-view-v22 与玩家命令 v6 不变。

38 项专项、全量 1,930 项（225.539 秒）与 32 示例通过；奥拉基尔五动作/32 事件且 CLI 回放通过。十四候选的新实验池是显式清单，不声明正式模式合法性或完整性；未知合格候选明确报错。R-080 与后续巨型主体、国服集中校准继续保留，详见 [奥拉基尔动态生成](m5-alakir.md)。


## 2026-09-24：M5-07b-03b-04 重复施放与希奈丝特拉内部验收

公共 `SpellRepeatSpec` / `SpellRepeatRecord` 区分一次支付/出牌和多遍效果，支持实时职业光环、冻结遍数、重复阶段死亡延迟、抉择选择缓存与独立发现；保存/恢复包含有类型的队列和选择状态。接入真实希奈丝特拉与已有两附肢，见 [机制契约](m5-spell-repeats.md)。

当前 **218 条真实样本/219 定义**，十二条 choice-only 描述；64 类机制（7 implemented / 57 partial），全部 internally_tested，真实卡仍 partial。prototype-v41 / core-effects-v41、snapshot 41（旧 1～40 拒绝）、representative-m5-v14；玩家观察 v22、命令 v6、外层 replay 1 保持。

56 项专项通过，全量 **1,986 项通过（236.113 秒）**，M5 机制 738 项、盘点另 11 项、M4 503 项；33 示例通过。希奈丝特拉示例六动作/33 事件，玩家接口、滋养等待选择恢复和回放一致，最终哈希 `69b374a9fa7575a0ea14abef26329b75bc40d7f93b45a13566ac9e8cdf1269b1`。实际日志 outputs/v41-regression.txt、outputs/v41-examples.txt。

R-081 保留精确国服窗口、自动施法/特殊重复和复杂目标变化；R-022 的提交前抉择调度继续保留。计划 v1.26 下一项 **M5-07b-03b-05 奥妮克希亚生命损失替换**，随后继续裂变；M5-07 整体未完成。


## 2026-09-24：M5-07b-03b-05 生命损失替换与奥妮克希亚内部验收

公共 `HealthLossReplacementSpec` 统一最终伤害扣血、生命支付和显式损失，资格查询与支付结算共用；上限增长保存为独立永久附魔，具备普通能力生命周期及类型化选择恢复。真实奥妮克希亚主体接入已有两个附肢和实验生成规则，见 [机制契约](m5-health-loss.md)。

当前 **219 条真实样本/220 定义**，十二条 choice-only 描述；65 类机制（7 implemented / 58 partial），全部 internally_tested，真实卡仍 partial。prototype-v42 / core-effects-v42、snapshot 42（旧 1～41 拒绝）、representative-m5-v15、player-view-v23；命令 v6、外层 replay 1 保持。

新增 58 项专项，全量 **2,044 项通过（248.896 秒）**，M5 机制 796 项、盘点另 11 项、M4 503 项；34 示例通过。奥妮克希亚示例八动作/45 事件，两个生成随从的生命支付、自己回合保护与对手回合正常伤害、保存/恢复/玩家动作回放一致；最终哈希 `9af322c8740c2f257943f8b42d0d9e6d098b47f664e0528d01b223fe272c3c35`。日志 outputs/v42-regression.txt、outputs/v42-examples.txt。

官方 35.0.3 的超剩余生命费用修复和 35.4 的生命增长识别修复已登记；R-082 保留国服窗口、名义伤害/吸血、增长保留缺失生命、特殊设值和次要种族等缺口。计划 v1.27 下一项 **M5-07c 兆示代表链路收尾验收与缺口归档**，公共门槛通过后进入裂变。M5-07 不提前整体验收，完整卡池与官方校准继续独立跟踪。


M5-11b 新增半稳定的传送门和时间之沙两条原始快照及实验适配；现有源文件与旧记录哈希保持不变。221 条真实样本/222 个定义，87 类机制（7 implemented / 80 partial），全部内部验证，真实卡仍 partial。运行时 prototype-v52 / core-effects-v52、snapshot 52、代表包 representative-m5-v17、观察 v31；命令 v6、replay 1 保持。45 项专项、全量 2,578 项（361.270 秒）、34 示例及 36 项台账检查通过。新增 C-005 登记钟表先生原始三次与国服 34.0 两次的冲突；当前卡面映射未确认，未把原始文本直接作为当前执行规则。详见 [次数卡面](m5-rewind-forms.md)。


M5-11c 新增米罗克 `END_036` 原始快照与有限实验适配；国服 34.4.2 的 3/6 改动与冻结数据一致。旧源哈希保持。当前 222 条真实样本/223 个注册定义，88 类机制（7 implemented / 81 partial），真实卡均 partial，验证均 internally_tested。prototype-v53 / core-effects-v53、snapshot 53、代表包 representative-m5-v18、观察 v32；命令 v6、外层 replay 1。55 项专项、全量 2,633 项（364.215 秒）、35 示例和 36 项台账检查通过。独立实验回溯职业牌池并非正式池；R-093、英雄技能回溯及 C-005 仍开放，见 [保留结果](m5-rewind-outcomes.md)。


M5-12a 新增四条必要探底代表原始记录和实验适配：TID_700、TID_703、TID_099、TID_003。源哈希保持。当前 226 条真实样本/227 个注册定义，89 类机制（7 implemented / 82 partial），真实卡均 partial，验证均 internally_tested。prototype-v54 / core-effects-v54、snapshot 54、代表包 representative-m5-v19、观察 v33；命令 v6、外层 replay 1。51 项专项、全量 2,684 项（375.023 秒）、36 示例和 36 项台账检查通过。R-094 与正式池未知保持，见 [探底契约](m5-dredge.md)。


M5-12b-01 新增六条必要来源/奖励/英雄代表记录：WW_001、WW_001t18、WW_001t5、WW_001t17、WW_001t23、HERO_03。源哈希保持。另有六个顶级宝藏仅登记为元数据，未计入适配支持。当前 232 条真实样本/233 个注册定义，90 类机制（7 implemented / 83 partial），真实卡均 partial，验证均 internally_tested。prototype-v55 / core-effects-v55、snapshot 55、代表包 representative-m5-v20、观察 v34；命令 v6、外层 replay 1。57 项专项、全量 2,741 项（381.825 秒）、37 示例、70 项代表卡检查和 36 项台账检查通过。R-095、完整奖励池及奖励公共依赖保持开放，见 [发掘契约](m5-excavate.md)。


M5-12b-02a 新增艾泽里特鼠 WW_001t26 的原始记录与实验适配；基础原始源和宝藏原始记录不变，宝藏清单说明改为独立引用动态适配台账。当前 233 条真实样本/234 个定义，90 类机制（7 implemented / 83 partial），真实卡 partial、验证 internally_tested；五个其他职业顶级奖励仅元数据。prototype-v56 / core-effects-v56、snapshot 56、代表包 representative-m5-v21、观察 v34、命令 v6、外层 replay 1。51 项专项、全量 2,792 项（386.023 秒）、38 示例、70 项代表卡和 36 项台账检查通过。R-096、剩余奖励依赖与正式池未知保持，见 [复活续接](m5-resurrection-followups.md)。


M5-12b-02b 新增艾泽里特鹰 WW_001t24、艾泽里特牛 WW_001t27 的原始记录与实验适配，基础原始源和宝藏记录不变。当前 235 条真实样本/236 个定义，90 类机制（7 implemented / 83 partial），真实卡 partial、验证 internally_tested；三个顶级职业奖励仅元数据。prototype-v57 / core-effects-v57、snapshot 57、representative-m5-v22、观察 v35、命令 v6、外层 replay 1。48 项专项、全量 2,840 项（391.110 秒）、39 示例和 36 项台账检查通过。R-097 与完整正式池未知保持，见[生成与发现](m5-discovery-delivery.md)。


M5-12b-02c 新增艾泽里特龙 DEEP_999t4、艾泽里特鱼人 DEEP_999t5 实验适配，冻结原始源和宝藏记录未变。当前 237 条真实记录/238 个定义、90 类机制（7 implemented / 83 partial），真实卡 partial、验证 internally_tested；术士奖励 WW_001t25 仍仅元数据。prototype-v58/core-effects-v58、snapshot58、representative-m5-v23、观察 v36、命令 v6、replay1。55 项专项、全量 2,895 项（400.553 秒）、40 示例及 36 项台账检查通过。R-098 和完整正式池未知保持，见 [跨区契约](m5-cross-zone.md)。


M5-12b-02d 新增艾泽里特蛇 WW_001t25 实验适配，原始数据及宝藏快照未改；七职业顶级奖励现均有显式适配，但完整正式池仍未知。当前 238 条真实记录/239 个定义、90 类机制（7 implemented / 83 partial），真实卡 partial、验证 internally_tested。prototype-v59/core-effects-v59、snapshot59、representative-m5-v24、观察 v37、命令 v6、replay1。48 项专项、全量 2,943 项（402.329 秒）、41 示例和 36 项台账检查通过。R-099 保留精确生命转移及保护交互的国服校准，见 [生命转移契约](m5-health-transfer.md)。


M5-12c-01 新增灌注来源、德鲁伊/法师技能及衍生物和基础德鲁伊英雄七条实验记录；八职业映射另存固定清单，六技能元数据缺口明确报错。245 条真实记录/246 个定义、91 类机制（7 implemented / 84 partial），真实卡 partial、验证 internally_tested。prototype-v60/core-effects-v60、snapshot60、representative-m5-v25、观察 v38、命令 v6、replay1。58 项专项、全量 3,001 项（418.618 秒）、42 示例和 36 项台账检查通过。R-100 保留精确成长与技能/魔像继承的国服校准；英雄技能回溯、被动监听及额外技能位置留 M5，见 [灌注契约](m5-imbue.md)。


M5-12c-02a 新增小精灵驾驭者 EDR_519，验证先灌注后间接触发技能；八职业映射快照保持，六技能仍为明确缺口。246 条真实记录/247 个定义、92 类机制（7 implemented / 85 partial），真实卡 partial、验证 internally_tested。prototype-v61/core-effects-v61、snapshot61、representative-m5-v26、观察 v39、命令 v6、replay1。50 项专项、全量 3,051 项（433.582 秒）、43 示例和 36 项台账检查通过。R-101 保留间接来源费用/次数、目标/选择及事件时序校准；技能回溯下一项实现，见 [技能激活契约](m5-power-activations.md)。


M5-12c-02b 新增 END_000p 青铜龙的祝福，验证英雄技能回溯、结果保留与灌注减费。247 条真实记录/248 个定义、92 类机制（7 implemented / 85 partial），真实卡 partial、验证 internally_tested。prototype-v62/core-effects-v62、snapshot62、representative-m5-v27、观察 v39、命令 v6、replay1。51 项专项、全量 3,102 项（426.155 秒）、44 示例和 36 项台账检查通过。五技能仍明确缺失；R-102 和正式生成池未闭环，见 [技能回溯契约](m5-power-rewind.md)。


M5-12c-03a 新增 END_003p 永恒龙的祝福与 HERO_11 机制场景身份，验证被动技能、安装监听和首张匹配条件；默认食尸鬼冲锋仍未适配。249 条真实记录/250 个定义、93 类机制（7 implemented / 86 partial），真实卡 partial、验证 internally_tested。prototype-v63/core-effects-v63、snapshot63、representative-m5-v28、观察 v40、命令 v6、replay1。54 项专项、全量 3,156 项（449.354 秒）、45 示例和 36 项台账检查通过。四技能仍明确缺失；R-103 和正式池未闭环，见 [被动技能契约](m5-passive-powers.md)。


M5-12c-03b 新增猎人/萨满灌注技能及两个基础英雄身份，默认初始技能仍未适配。253 条真实记录/254 个定义、93 类机制（7 implemented / 86 partial），真实卡 partial、验证 internally_tested。prototype-v64/core-effects-v64、snapshot64、representative-m5-v29、观察 v40、命令 v6、replay1。57 项专项、全量 3,213 项（451.828 秒）、46 示例和 36 项台账检查通过。剩余圣骑士/牧师两个灌注技能仍明确缺失；R-104 和正式池未闭环，见 [定向修改契约](m5-directed-modification.md)。


M5-12c-03c 新增圣骑士灌注技能、传送门、英雄身份和两个低费龙样本，默认援军技能仍未适配。258 条真实记录/259 个定义、93 类机制（7 implemented / 86 partial），真实卡 partial、验证 internally_tested。prototype-v65/core-effects-v65、snapshot65、representative-m5-v30、观察 v40、命令 v6、replay1。55 项专项、全量 3,268 项（469.457 秒）、47 示例、70 项代表卡和 36 项台账检查通过。七职业灌注适配，牧师技能仍明确缺失；R-105 和正式池未闭环，见 [传送门契约](m5-imbue-portals.md)。


M5-12c-03d 新增牧师灌注技能及英雄身份；默认次级治疗术仍缺适配。纠正 v65 的援军说明并补正 HERO_04 对既有 HERO_04bp 的默认绑定。260 条真实记录/261 个定义、93 类机制（7 implemented / 86 partial），真实卡 partial、验证 internally_tested。prototype-v66/core-effects-v66、snapshot66、representative-m5-v31、观察 v40、命令 v6、replay1。60 项专项、全量 3,328 项（477.651 秒）、48 示例、41 项池、70 项代表卡和 36 项台账检查通过。八个声明灌注技能已有实验适配；多技能位置、R-106 和正式池仍未完成，见 [契约](m5-pool-offers.md)。

M5-12d-01 多技能位置与玩家动作完成内部验收。prototype-v67/core-effects-v67、snapshot67、观察v41；代表包v31及260条真实记录保持，未新增适配。42项专项、全量3,370项（472.815秒）、49示例和36项台账检查通过。JAIL_446仅作冻结需求证据，数量/重复获得和定向来源规则保持未完成；R-107待国服校准，见[契约](m5-multiple-powers.md)。

M5-12d-02 定向技能生命周期完成内部验收。prototype-v68/core-effects-v68、snapshot68、观察v42；代表包v31及260条真实记录保持。48项专项、全量3,418项（470.005秒）、50示例和36项台账检查通过；无新增真实适配/官方证据。捕获引用、定向操作、原子安装费用和英雄替换策略见[契约](m5-power-lifecycle.md)，完整多技能组合及R-107/R-108国服规则仍未完成。

M5-12d-03 多技能组合内部验收：37项专项、全量3,455项（483.237秒）、51示例及36项台账检查通过。未修改内核、存档或真实适配，v68/schema68/观察v42/代表包v31保持；计划1.53接续M5-13a。R-102/R-107/R-108国服规则和正式来源仍有缺口，见[组合记录](m5-power-combinations.md)。

M5-13a-01 伤害/治疗结果条件内部验收：49项专项、全量3,504项（485.888秒）、52示例、70代表卡及36台账检查通过。v69/schema69/观察v42/代表包v32；新增三张必要代表，共263真实记录/264定义、97类机制。计划1.54，下一项13a-02死亡原因归因；AV_143仅作需求证据未适配，正式池和R-109国服时序未完成，见[契约](m5-health-outcomes.md)。

M5-13a-02 死亡归因内部验收：52项专项、最终全量3,556项（535.806秒）、53示例、70代表卡及36台账检查通过。v70/schema70/观察v42/代表包v33；新增血怒者科尔拉克，共264真实记录/265定义、98类机制。计划1.55接续13b激励；R-109/R-110和正式池仍未完成，见[契约](m5-death-attribution.md)。

M5-13b激励内部验收：55专项、最终全量3611项（507.728秒）、54示例、70代表卡及36台账检查通过。v71/schema70/观察42/代表包34；新增两张必要代表，共266真实记录/267定义、99机制。计划1.56接续13c抉择；R-111和正式池未闭环，见[契约](m5-inspire.md)。

M5-13c抉择公共子集内部验收：62专项、最终全量3673项（512.906秒）、55示例、56重复、70代表卡及36台账检查通过。v72/schema71/观察43/命令7/代表包35；新增三张必要代表，滋养迁移，共269真实记录/270定义、100机制。计划1.57接续13d战吼；特殊合并/来源、R-112和正式池仍未闭环，见[契约](m5-choose-one.md)。

M5-13d-01战吼身份内部验收：56专项、最终全量3729项（534.810秒）、56示例、70代表卡及36台账检查通过。v73/schema72/代表包36；观察43/命令7保持。44条既有代表迁移，未新增卡，269记录/270定义、100机制保持；组件声明来源单独保留。计划1.58接续13d-02重复/抑制，特殊来源和R-113未闭环，见[契约](m5-battlecries.md)。

M5-13d-02a场上战吼重复内部验收：47专项、3776全量（537.742秒）、57示例、70代表卡及36台账检查通过。v74/schema73/代表包37；新增铜须一张必要代表，270记录/271定义，机制数100保持。次数批次与回溯结果独立，计划1.59接续玩家次数政策；真正抑制/间接历史及R-114仍未闭环，见[契约](m5-battlecry-repeats.md)。

M5-13d-02b玩家战吼政策内部验收：55专项、3831全量（543.659秒）、58示例、70代表卡及36台账检查通过。v75/schema74/观察44/代表包38，命令7保持；新增低语元素和维尔纳尔之心，272记录/273定义，100机制。计划1.60接续抑制/整次出牌反制；历史来源及R-115未闭环，见[契约](m5-battlecry-modifiers.md)。

M5-13d-02c-01内部验收：43反制专项、3874全量（552.867秒）、59示例与36台账检查通过。新增异议MAW_006，273记录/274定义、100机制；运行时76/schema75/观察45/代表包39，命令7保持。国服窗口R-116与奥卡尼私有策略仍未闭环，见[公共窗口](m5-minion-counters.md)。

M5-13d-02c-02内部验收：51专项、3925全量（559.982秒）、60示例和70代表检查通过；新增奥卡尼及两个选择描述，276记录/277定义、14 choice-only，100机制仍partial口径。运行时77/schema76/观察46/代表包40，命令7保持；R-117秘密知识和重复选择规则未国服校准，见[公共契约](m5-counter-policies.md)。

M5-13d-02d内部验收：57专项、3982全量（577.944秒）、61示例和70代表检查通过；只加蛛网领主，277记录/278定义、14 choice-only。运行时78/schema77/代表包41，观察46/命令7不变；R-118身份/费用来源顺序未国服校准，见[公共契约](m5-battlecry-costs.md)。

M5-13d-02e内部验收：48专项、4030全量（592.732秒）、62示例和70代表检查通过；只加毒鳍龙，278记录/279定义、14 choice-only。运行时79/schema78/代表包42，观察46/命令7保持；R-119筛选身份/批次窗口未国服校准，见[公共契约](m5-ability-filters.md)。

M5-13d-03a内部验收：54专项、4084全量（595.704秒）和63示例通过；未增真实适配。运行时80/schema79/代表包42，观察46/命令7保持；R-120及正式历史卡牌政策未关闭，见[公共契约](m5-battlecry-sources.md)。

M5-13d-03b内部验收：56专项、4140全量（590.280秒）、64示例与CLI通过；只新增DED_509金刚鹦鹉，279记录/280定义、14 choice-only。运行时81/schema80/代表包43，观察46/命令7保持；R-121反制资格和原历史窗口为未国服校准的实验政策，见[契约](m5-played-battlecries.md)。

M5-13d-03c内部验收：31专项、4171全量、70代表检查、65示例及CLI通过。仅新增SW_115，280记录/281定义；代表包44，内核81/schema80保持。R-122未国服校准，见[组合契约](m5-triggered-battlecries.md)。

M5-13d-02f内部验收：45专项、4216全量、70代表检查、66示例及CLI通过。仅新增DEEP_020，281记录/282定义；规则/效果82、代表包45，schema80保持。R-123未国服校准，见[牌库条件契约](m5-deck-conditions.md)。

M5-13d-03d-01内部验收：48专项、4264全量、70代表检查及67示例通过；规则/效果83，代表包45、281记录/282定义和schema80保持。通用序列已实现，沙德沃克未适配，R-124未国服校准，见[契约](m5-battlecry-sequences.md)。

M5-13d-03d-02a内部验收：45专项、404既有战吼回归、4309全量、70代表检查、68示例及CLI通过。规则/效果84、schema81；代表包45及281记录/282定义保持。R-125未国服校准，见[来源契约](m5-sequence-lifecycle.md)。

M5-13d-03d-02b内部验收：38专项、4347全量、70代表检查、11清单检查、69示例及CLI通过。内核84/schema81保持，代表包46、282记录/283定义；新增GIL_820为R-126实验适配，见[契约](m5-shudderwock.md)。

M5-13d-02g-01内部验收：55专项、4402全量、70代表检查、11清单检查、70示例及CLI通过。内核85/schema82/代表包47，282记录/283定义保持；独立连击迁移两个既有代表，R-127待国服校准，见[契约](m5-combo-activations.md)。

M5-13d-02g-02内部验收：56专项、4458全量、71示例及原生代表CLI通过。内核86/schema83/观察47，代表包47及282记录/283定义保持；没有新增真实卡，连击次数与消费窗口R-128待国服校准，见[契约](m5-combo-repeats.md)。

M5-13d-02g-03a内部验收：53专项、4511全量、72示例及原生代表CLI通过。内核87/schema84/观察48，代表包47及282记录/283定义保持；临时关键词生命周期与期限R-129仍待国服校准，见[契约](m5-timed-keywords.md)。

M5-13d-02g-03b内部验收：38专项、4549全量、73示例及原生代表CLI通过。代表包48、286记录/287定义；内核87/schema84/观察48保持。新增四条必要来源/召唤组合记录与独立不完整实验池，R-130待国服校准，见[契约](m5-combo-sources.md)。

M5-13d-02h内部验收：玩家法术次数/期限/提交收据57专项、4606全量、74示例及原生CLI通过；内核88/schema85/观察49/代表包49，288记录/289定义。风潮/泰兰德为必要代表，R-131待国服校准，见[契约](m5-spell-modifiers.md)。

M5-13d-02i内部验收：持牌施法条件54专项、4660全量、75示例及原生CLI通过；内核89/schema86/观察50/代表包50，289记录/290定义。双弓积骇纳迦为必要代表，R-132待国服校准，见[契约](m5-held-spells.md)。

M5-13d-02j-01内部验收：特定法术重复附件与使用捕获54专项、4714全量、76示例及旧原生CLI通过；内核90/schema87/观察51，代表包50及289记录/290定义保持。没有新增真实卡，R-133待国服校准；生成时原子交付与来源实验池仍待补，见[契约](m5-card-spell-repeats.md)。

M5-13d-02j-02内部验收：生成/发现原子附加50专项、4764全量、77示例及旧原生CLI通过；内核91/schema88/观察51，代表包50及289记录/290定义保持。R-134待国服校准，JAIL来源与实验池未完成，见[契约](m5-creation-repeats.md)。

M5-13d-02j-03内部验收：来源组合39专项、4803全量、78示例及原生CLI通过；内核91/schema88/观察51保持，代表包51及293记录/294定义。436原始候选独立保留，6项实验池不完整，多职业解码修正吉德拉。R-135及正式池/国服上线待核实，见[契约](m5-card-spell-sources.md)。

M5-13d-02k-01内部验收：亡语身份/来源54专项、4857全量、79示例及原生CLI通过；内核92/schema89，代表包52，观察51/命令7保持，293记录/294定义不变。R-136保留原回调窗口，独立重复尚未实现，见[契约](m5-deathrattle-activations.md)。

M5-13d-02k-02内部验收：场上亡语次数44专项、4901全量、80示例及CLI通过；内核93/schema90、代表包53，观察51/命令7保持；新增男爵至294记录/295定义。原始及专项候选指纹不变。R-137、玩家期限/固定次数/自身范围及M0/M6/M7仍保留，见[契约](m5-deathrattle-repeats.md)。

M5-13d-02k-03内部验收：玩家亡语次数与期限46专项、4947全量、81示例及CLI通过；内核94/schema91、代表包54，观察51/命令7保持；新增雪落墓地至295记录/296定义。R-138、固定主动次数/自身范围及M0/M6/M7仍保留，见[契约](m5-deathrattle-player-effects.md)。

### 2026-10-03 02l-02当前运行时注解（内部通过）

当前开发注解为prototype-v97/core-effects-v97、snapshot94、representative-m5-v57，观察51/命令7/replay1；299条真实记录/300定义及100类机制（7 implemented/93 partial）保持，本批没有新增真实卡。根能力与主体身份已接入，70专项、505相关回归、5103全量及84示例内部通过，详见[契约](m5-power-payloads.md)。baseline_*和初始snapshot_schema=1继续记录M0历史审计起点，不能按当前版本覆盖。R-141与M0/M6/M7保持缺口。

### 2026-10-03 02l-03当前运行时注解（内部通过）

当前开发注解为prototype-v98/core-effects-v98、snapshot95、representative-m5-v58，观察51/命令7/replay1；300记录/301定义/14choice-only及100类机制（7 implemented/93 partial），只新增TOY_528伴唱机。74专项、505相关回归、5177全量及85示例内部通过，详见[契约](m5-power-repeats.md)。baseline_*与初始snapshot1继续保存M0历史；R-142及M0/M6/M7保持缺口。

### 2026-10-03 02l-04当前运行时注解（内部通过）

当前开发注解为prototype-v99/core-effects-v99、snapshot96、representative-m5-v59，观察51/命令7/replay1；300记录/301定义/14choice-only及100类机制（7 implemented/93 partial）保持，无新增真实卡。83专项、620相关回归、5260全量及86示例内部通过，详见[契约](m5-end-turns.md)。baseline_*及初始snapshot1保持M0历史；R-143及M0/M6/M7保留。

### 2026-10-03 02l-05a当前运行时注解（内部通过）

当前开发注解为prototype-v100/core-effects-v100、snapshot97、representative-m5-v60，观察51/命令7/replay1；300记录/301定义/14choice-only及100类机制（7 implemented/93 partial）保持，无新真卡。83专项、887相关回归、5343全量及87示例内部通过，详见[契约](m5-end-turn-repeats.md)。baseline_*及初始snapshot1保持M0历史；R-144及L05必要代表/主动/混合/M0/M6/M7保留。

### 2026-10-03 02l-05b当前代表包注解（内部通过）

prototype-v100/core-effects-v100、snapshot97及观察51/命令7/replay1保持，仅代表包变为representative-m5-v61；302记录/303定义/14choice-only，只新增独立ICC_901/CATA_480。旧300完整行和M0 baseline_*历史不覆盖，冻结inventories与前置审计20完整raw保持；34专项、1176相关回归、5377全量及88示例内部通过，详见[代表契约](m5-end-turn-representatives.md)。R-145与R-144待国服校准；下一项05c主动/异阶段，TIME_064混合更后，L05/M0/M6/M7未完成。

### 2026-10-03 02l-05c当前运行注解（内部通过）

prototype-v101/core-effects-v101、snapshot98拒旧1～97；representative-m5-v61、302完整原始记录/303定义/14choice-only、观察51/命令7/replay1保持，无新真实卡。302完整support行、M0 baseline_*、冻结inventories及1159条历史前审均保持；91专项、1094相关回归、5468全量及89示例内部通过，详见[公共入口契约](m5-end-turn-activations.md)。R-146待国服校准；下一项05d主体资格/选择政策与必要CATA_472代表，固定多轮及TIME_064混合继续保留，L05/M0/M6/M7未完成。

### 2026-10-03 M5-13d-02l-05d 公共候选与随机结束producer（内部验收）

公共纯结构候选查询与随机一次producer已内部验收。五类载体owner/selected范围、current/printed/active依据、休眠/存活/消费与presence政策由注册profile声明；不执行主体条件、每物理载体一个权重。随机选择与主体/完整max计划同窗接受，外层每次实际亡语各自抽选，内层额外结束执行保持原选择；空池保存空根且不消耗RNG。producer_mode、原request、完整有序候选、完整selected及MT19937前后状态进入历史与Finish证明；原窗口重算池/主体/计划、局部重演抽样，允许后续主体合法推动RNG，不提供未签名存档来源认证。仅新增CATA_472灵感之槌完整raw/pin实验适配，active/live/unconsumed友方随从及选中后的全部结束主体为R-147本地政策，待CN校准。内核102/schema99拒旧1～98，代表包62及303记录/304定义/14choice-only；观察51/命令7/replay1保持。旧302完整行、历史前审和M0/frozen inventories保持；L05/M0/M6/M7及长期目标未完成。05e四族混合重复声明、共享生命周期和独立接受窗口组合，必要TIME_064来源由公共机制表达；固定多轮producer政策继续保留M5，当前仅有战棋固定两轮证据，不能借此宣称构筑来源已完成。

02l-05d实际终态：81专项、1316相关回归、5549全量及90示例内部通过；专项23.619秒、相关588.131秒、全量1883.387秒。原生8动作/53事件/3随机根/4位置/4选择，真实Maul外层两次独立抽选；全部waiting恢复、回放及模块CLI通过，owner时钟[3,3]。旧86示例摘要共同行为字段保持；仅内部证据，R-147未CN校准。

### 2026-10-03 M5-13d-02l-05e 四族混合重复组合（内部验收）

四族混合重复公共组合已内部验收。同一载体四个独立附件共用生命周期，各族分别捕获自己的max计划、主体和执行身份，跨族不共享次数或用途；已接受计划保留，后接受根按新局面重新捕获。保留各族不同首次窗口、额外新局面、既有检查点/支付/用途/时钟；补齐战吼整次出牌接受收据、亡语单调分配计数及贯穿整批的原接受证明和重复来源身份校验，拒绝中途裁队列/缩次数和跨族附件ID冒充。选择恢复、回溯、异常回滚及玩家隔离复用公共解释器。仅新增TIME_064必要静态四声明，无自身战吼/亡语/结束主体；TIME_064e只作独立原始证据，没有可执行附魔适配。内核103/schema100拒绝旧1～99，观察51/命令7/replay1保持，代表包63，304完整记录/305定义/14choice-only。旧303完整行、历史前审与M0/frozen inventories保持。R-148为内部组合契约，依赖各族既有规则，未国服校准。下一项02m-01：条件/种族重复来源前审与公共匹配契约，先确定条件对象、印刷/当前依据和接受窗，再补必要机制；动态主体授予、固定多轮结束producer、特殊来源及M0正式池/M6国服校准/M7批量接卡继续保留，不能以本批归档宣称重复整族完成。

02l-05e实际终态：65公共专项、16代表专项、1611相关回归、5630全量及91示例内部通过；公共57.706秒、代表18.090秒、相关727.359秒、全量2009.161秒。旧87示例摘要共同行为字段保持，schema及摘要哈希变化另行登记；原生全部waiting恢复、独立注册表回放与模块CLI通过。仅内部证据，R-148未国服校准。

### 2026-10-03 M5-13d-02m-01-A1 法术学派公共匹配（内部验收）

M5-13d-02m-01-A1法术学派匹配及双窗口接受证明已内部验收。match与既有职业条件取交集，玩家提交与场上较晚窗口分别捕获全部匹配来源；单位/空/反制及FinishPlay后续接保持明确接受义务，嵌套真实出牌按有序帧义务关闭。完整状态仅存活动证明，历史保留紧凑收据；原提交目标绑定，较晚合法重定向保持。内核104/schema101/观察52，命令7/replay1及代表包63/304记录/305定义/14choice-only保持。本批未接代表卡，R-149未国服校准。下一项必要RLK_541 A2，再做持续条件/另一物理实体及逐族匹配；其他费用/主体/周期/+1/CAST轴与M0/M6/M7继续保留，不能宣称条件重复整族或最新正式池完整。

33专项、67信息/操作回归、892相关回归、5663全量及92示例内部通过；专项84.739秒、信息11.487秒、相关527.004秒、全量2274.395秒。原生合成6动作/37事件/6施法/2真实待选，max次数[3,1,2]、护甲8，waiting独立注册表恢复/clone/回放及模块CLI通过。88旧/89当前摘要的共同行为及字段保持；1129历史文件字节保留。较早schema99/core102的19新增字段及2控制清单经针对复核，前批迁移与A1变化分别登记。仅内部证据，R-149未国服校准。

完整合同见[法术学派与双窗口](m5-spell-match.md)，实际证据见[验收记录](../outputs/v108-verification.json)。

### 2026-10-04 M5-13d-02m-01-A2 必要法术学派代表

M5-13d-02m-01-A2必要RLK_541代表已内部验收。仅新增完整维萨鲁斯raw/PIN与奥术any总2的公共声明；旧304完整行、M0历史runtime及冻结inventories保持，公共内核没有新增分支。内核104/schema101/观察52/命令7/replay1不变，代表64及305记录/306定义/14choice-only。真实同职业奥术、非奥术/无学派、完整max来源、反制、离场、晚窗口、恢复/回放及玩家隔离已验证。R-150仍只覆盖真实付费手牌profile并依赖R-149，自动/effect/draw/history来源及CN/正式池未覆盖。下一项持续来源条件/另一实体B1，再做逐族匹配B2；其他费用/主体/周期/+1/CAST轴及M0/M6/M7继续保留。

合同见[必要代表验证](m5-spell-match-representatives.md)。

实际验收：[终态证据](../outputs/v109-verification.json)。15代表专项、770相关回归、5678全量及93示例内部通过；代表8.390秒、相关245.647秒、全量1177.607秒。原生10动作/49事件/7casts/2真实待选，次数[2,1,1,1,2]，每根仅支付一次；waiting独立注册表恢复/clone/回放与模块CLI一致。89旧/90当前摘要共同行为与字段保持，1265历史文件字节保留，历史v105存档与A1实际after逐字段比对，仅命名identity不同。只覆盖manual paid hand profile，R-150未国服校准，自动CAST与完整合法池未覆盖。

## M5-13d-02m-01-B1 历史运行契约

M5-13d-02m-01-B1持续来源条件与另一物理实体已内部验收。实际board spell_repeat在原较晚接受窗完整查询见证，再与职业/学派相交；显式profile区分presence，another排除实际carrier ID。两原窗口及当前存续来源静态身份绑定，包括全部false；历史不重判当前见证。内核105/schema102，观察52/命令7/replay1及代表64/305记录/306定义/14choice-only保持；没有新增真实卡。仅manual paid hand profile，R-151未国服校准。下一项B2-01战吼原接受对象与物理self/种族匹配公共契约，再按族推进；费用/主体/周期/+1/CAST、动态主体、固定多轮producer、M0/M6/M7继续保留。

接口见[持续来源条件](m5-repeat-source-conditions.md)，实际执行与证据只在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)维护。M0历史runtime保持；R-151仍为国服校准阻塞项。

## M5-13d-02m-01-B2-01 历史运行契约

B2-01验收时运行接口为prototype-v106/core-effects-v106、schema103及玩家观察53；命令7/replay1和代表包v64保持。战吼接收对象、物理self、原卡面种族及持续来源条件见[公共契约](m5-battlecry-matching.md)。实际执行与证据仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护；R-152待国服校准，M0历史runtime及冻结inventories保持，正式池与完整模拟器目标尚未完成。

## M5-13d-02m-01-B2-02 当前运行契约

当前代码接口为prototype-v107/core-effects-v107、schema104及玩家观察54；命令7/replay1和代表包v64保持。连击提交与实际接受对象、独立原证明、范围/种族/持续条件见[公共契约](m5-combo-matching.md)。R-153未国服校准；M0历史runtime及冻结inventories保持。实际验证结果仅在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。


## 2026-10-04 后续核查候选与开发注解（未锁定）

2026-10-04后续核查新增[国服补丁候选](../outputs/v114-M0-CN-patch-followup-candidate.json)、[根独立核对](../outputs/v114-root-M0-candidate-independent-check.json)及[两张卡完整raw/机制观察](../outputs/v114-cn-36-6-3-card-mechanism-observation.json)。[国服36.6.3公告](https://hs.blizzard.cn/news/24303864/index.html)明确2026-10-01上线及两项构筑数值调整；仅确认本公告，不证明完整国服热修集合、有效卡牌版本或标准/狂野合法池已锁定。36.6.2国际公告不代替国服生效时间。2026-09-23本地客户端/build/data、既有rules与M0历史runtime/frozen起点均保留；未新增卡牌适配或更新正式池。

B2-04内部验收后的target.extensions.current_runtime开发注解同步109/schema106，仅属posttested bookkeeping；runtime.baseline_*、rules、data及冻结来源不改。该注解不参与引擎规则/快照加载，不将后写JSON冒作S1行为输入。公共接口与验收状态只见[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)。
