# M5-13d-02l-05b：自然结束重复必要代表

2026-10-03。本增量已通过内部验收。运行版本为 `prototype-v100` / `core-effects-v100`、snapshot schema97，代表包 `representative-m5-v61`。内核、schema及观察51、命令7、外层replay1保持；仅新增两条真实记录，302记录/303定义/14个choice-only。R-145是必要代表的本地profile，依赖[R-144公共机制](m5-end-turn-repeats.md)，两者尚未国服校准。

## 两条独立代表

| 独立记录 | 本地资料 | 当前代表声明 |
| --- | --- | --- |
| `ICC_901`，dbf45309，达卡莱附魔师 | 3费1/5，中立史诗随从；原文“你的回合结束效果会触发两次。”，AURA=1 | 印刷 `EndTurnRepeatSpec(2, 'all')`，活场上随从贡献；无另加结束trigger或安装战吼 |
| `CATA_480`，dbf123691，沙怒光环 | 3费圣骑士稀有法术，SPELL_SCHOOL=5对应神圣；原文“你的随从的回合结束效果会触发两次。持续@回合。” | `ongoing_effect_id='m5.sandfury_aura'`，普通法术安装玩家objective；`duration=3`、owner `turn_ended`、`EndTurnRepeatSpec(2, 'minion')` |

两条canonical原始记录hash分别为：

- `ICC_901`：`070a2203d4bc37018eb158552c443b69698282fe69f0c7970d1d8c57efa45a6d`。
- `CATA_480`：`97a07ad8a9f0cb55fc0cef49192ef58b74e527bd0043c013996b402900cb5d15`。

完整原文、tags、source_events及null均在[不可变前置审计](../outputs/v104-end-turn-representatives-pre-audit.json)保存；20条catalog.raw逐项等于冻结提取记录，带canonical hash。这20条是审计证据，不是新增20卡或正式池分母。CATA原文保留`@`；QUEST_PROGRESS_TOTAL和TAG_SCRIPT_DATA_NUM_1各为3，只支持本地duration3候选，不能写成已核实的官方动态文本或国服计时。

`CORE_ICC_901`（dbf95696）、`ICC_901e`（dbf52777）、战棋普通/金色记录及`TIME_064`/`TIME_064e`保持独立，未增加适配。CORE的858数值引用不合并身份；同名、同文、后缀不能证明附魔安装关系。冻结来源中未发现`CATA_480e`/`CATA_480t`，没有合成原始记录或dbf ID；字段扫描也不证明完整来源图。原300条完整台账行，包括notes/evidence，保持历史内容，不覆盖M0的baseline_*或已冻结来源inventories。

## 复用来源、范围与生命周期

ICC使用现有印刷能力及独立附件身份；来源须是主体捕获控制者的活场上随从。死亡、沉默、回手、变形或转控改变后续自然接受的有效来源；本批已经冻结的完整计划不缩减。复制沿用新的实体/能力ID，不能按卡名合并来源。

CATA共享普通法术的费用、反制、完成事件和玩家操作。成功载荷通过既有`AddPlayerEffect`建立所属玩家的独立实例；本体进入墓地不撤销实例，来源后来变化也不转移所属玩家。反制支付费用而不安装，满区手动操作在支付前拒绝，效果式安装失败不产生幽灵来源。永久/期限、公开展示和恢复复用[玩家效果契约](m4-player-effects.md)。

`all`匹配该玩家已经显式分类的自然结束主体，`minion`按物理随从载体匹配。随从上来自法术的结束能力仍属随从主体；源自随从的玩家效果主体仍属玩家效果。载体card_id、附件来源与玩家实例source_card_id分别保存。普通`turn_ended`监听、倒数/到期、进度、休眠时钟、临时法力、解冻及下一回合流程不因此重复。

场上和玩家来源采用既有完整max计划；两个“两次”来源仍为两次，并保留全部较小/相等贡献者。同载体多声明、同卡多个玩家实例继续保存独立身份。Paladin Aura标签本身不证明独占、替换、双实例、共享容量或全部特殊来源规则；当前沿用通用objective独立实例与容量政策，属于R-145的partial profile。

广义all范围、来源资格、max合并及跨主体特殊规则仍是内部政策。两个真实随从场景通过也不能单独认证所有武器、技能、休眠、玩家效果或对手回合载体的官方行为。

## 本地期限及原窗口

CATA采用三个所属玩家自然回合结束，含正常施放回合结束；对手结束不扣己方余量。真实自然边界前固定旧实例ID及期望remaining，全部已接受结束载荷与旧反应完成后只扣一次。剩余1仍贡献本批完整重复，然后先移除实例、发布原到期事件；新建/替换实例不被旧冻结tick误扣。开始倒数公共规格仍沿其原owner开始时钟，不因代表卡另建计时系统。

以上duration3、含施放结束、末次先执行再到期是本地profile，沿用已有雪落墓地等内部owner时钟契约，尚未CN校准。官方持续回合文字和标签数值不足以证明精确消费顺序。

代表声明复用自然主体的旧混合监听槽位。首次普通载荷保留原捕获局面，有限次首次保留旧消费后局面，英雄技能首次保留旧安装身份守卫；额外位置实际开始才取新局面。首次守卫只发生一次，失败整组skip；成功后不会为额外执行再次消费有限用途或重查技能槽。分类有限次`guard_event`及private IDs的真实事件绑定、HP挂起阶段门禁、完整`FinishEndTurnBatch`接受证明保持R-144实现依赖，不宣称因此取得官方时序证据。

Invoke/Finish等诊断控制不增加玩法检查点或自然游戏事件。最后额外或尾普通监听等待选择时，完整主体/计划证明仍持续到owner时钟前；保存、恢复、clone与回放保留同一位置和旧tick。终局、工程预算和原子回滚仍走公共层，全知计划、附件ID与private guard数据不进入玩家观察。

## 验证证据与下一项

2026-10-03，34专项、1176相关回归、5377全量及88示例内部通过；专项26.699秒、相关回归526.388秒、全量1808.916秒，M5共4129、M4共503。旧摘要共同动作/事件/物理结果字段不变；全新代表注册表原生恢复/回放及hs_sim CLI通过，均为内部证据。 见[验收摘要](../outputs/v104-verification.json)、[全量](../outputs/v104-full-tests.txt)、[示例比较](../outputs/v104-example-count-check.json)。上一批公共机制实际内部验收为83专项、887相关回归、5343全量及87示例，见[v103验收](../outputs/v103-verification.json)；其合成原生模块CLI与本批代表注册表CLI保持独立。

本批专项入口为`tests/test_m5_end_turn_representatives.py`。日志约定为`outputs/v104-end-turn-representative-tests.txt`、`outputs/v104-end-turn-representative-regression.txt`、`outputs/v104-full-tests.txt`、`outputs/v104-examples-run.txt`与`outputs/v104-example-count-check.json`。close只从实际终态日志及显式数量/native hash登记，不以stage或预审代替通过。

专项已覆盖真卡pins/费用/公开根、真实BOT_107两来源max组合、独立来源控制、第三次来源死亡后冻结extra、CATA最后owner时钟、物理minion与all范围，以及必要合成选择的恢复/回放、守卫和信息边界。BOT是对所有其他活跃角色造成1点伤害，包括双方英雄及友方Drakkari。原生示例使用全新代表注册表恢复/回放并以`python -m hs_sim replay <file> --card-set representative`复核，实际摘要已登记。它包含7次真实自然结束与7次BOT主体执行；CATA公共时钟发布2次`ticked`和1次`expired`，最后移除沿用原到期事件，不另加第三个`ticked`。双方英雄最终各23生命，Drakkari有1次真实死亡。

下一项 **M5-13d-02l-05c：主动/异阶段结束能力公共入口**，保留明确主体scope；`TIME_064`四类混合声明更后。R-145代表profile不表示Paladin Aura全规则、完整来源图、正式池、L05或整个结束族完成；M0正式池、M6国服校准及M7批量卡牌仍未完成。

[05c只读来源审计](../outputs/v105-end-turn-activation-pre-audit.json)及[独立复核](../outputs/v105-root-audit-check.json)保留本批收尾前的历史观察；1159条完整raw与147项依赖复核不表示主动机制已实现。下一项将主体选择范围与重复来源范围分开，记录真实调用origin/issuer/cause，复用主体owner与伤害来源，验证同回合多根、嵌套及异阶段入口；主动执行不制造自然结束事件或推进所属时钟。灵感之槌窄profile及尚缺证据的真实非战棋phase来源不能代替公共范围验收。

原生摘要 `a89ee90f224f0969890498b31a43e8756372c429b41dbcbd7a1a15fb7d9c5009`，9动作/74事件，全新representative Registry恢复与回放内部通过；命令 `python -m hs_sim replay outputs/end-turn-representatives-replay.json --card-set representative` 的[CLI日志](../outputs/v104-end-turn-representatives-cli.txt)通过。上一批合成示例的模块CLI保持独立历史证据。

更新：02l-05c主动与异阶段结束能力公共入口已内部验收，91专项、1094相关回归、5468全量及89示例内部通过，见[公共入口契约](m5-end-turn-activations.md)。自然原混合槽位、守卫/收据与owner时钟保持；内核101/schema98、代表包61，无新真实卡。下一项05d主动producer资格/选择政策与必要CATA_472代表；固定多轮与TIME_064混合后置，R-146未CN校准，L05未整族完成。
