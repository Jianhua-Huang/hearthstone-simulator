# 起始套牌法术派系条件

`DeckSpellSchoolCondition(spell_school=SpellSchool.SHADOW, scope='starting')` 表示指定玩家原始构筑套牌中的每张法术牌都属于给定派系。声明冻结，仅接受现有 `SpellSchool` 枚举；字符串、布尔、空值、任意表达式和 current 范围拒绝。原 `DeckCondition` 两字段、原费用排除声明和各自查询主体保持，新声明也交给原 `matches_deck_condition` 和 `CheckDeckCondition`。

## 事实与子集

只读取有构筑开局记录、由 `MatchSetup` 绑定的 `original_deck`，不从场景、当前牌库或起手猜原套牌。无开局事实时抛出 `UnknownDeckFacts`，不能降为假或真。原开局校验仍核对恢复时的构筑设置、原卡组及捕获上下文。

每个原始条目先查验已知卡牌定义，再只将 `CardType.SPELL` 交给原 `PoolQuery(kinds=(SPELL,), spell_schools=(school,))`。非施法牌被排除；已知法术的 `spell_school=None` 是无派系法术，判为不匹配。类型和派系查询不要求无关职业或构筑身份元信息，原其他条件的元信息守卫保持。必须完整查验所有定义，不能因早先已出现异派系法术而跳过后面的未知条目。

空法术子集按全称条件为真。这是本实现明确的内部政策，准确国服空法术结果仍需 M6 校准。官方[黑暗主教本尼迪塔斯卡库](https://hearthstone.blizzard.com/en-us/cards/64443-darkbishop-benedictus?set=standard&textFilter=dunkelbisch)的索引文字可确认对战开始时的法术派系要求；它未明确给出空子集或其他开局工作相对顺序，不能据此宣称这些边界已官方验证。

普通换牌、硬币、抽牌、洗入、清空牌库、当前换面和费用修改不重写原构筑事实。查询不修改用途、RNG、动作、事件或历史。宿主可明确查询任一玩家；全知原牌库、条件声明和结算帧不能进入玩家接口。

## 执行与必要代表

原 `CheckDeckCondition` 在轮到执行时选择一次分支，随后由公共解释器负责选择、恢复、克隆、回放、继续、检查点和事务回滚。开局等待及普通出牌等待都沿用原流程，没有新生产模块、状态字段、动作、事件、效果或执行器。

隔离代表只有完整原始 SW_448「黑暗主教本尼迪塔斯」和其精确关联 dbf 1622 的 EX1_625t「心灵尖刺」。前者原 5 费 5/6 牧师传说，无种族标签、无战吼；按原 `before_deal` 开局挂钩返回条件分支，命中后用原 `ReplaceHeroPower` 安装后者。后者原 2 费，按原目标选择及 `Damage` 造成 2 点伤害，保留原费用支付与技能使用限制。普通打出、沉默或回手不重新执行开局挂钩，也不撤销已替换的技能；没有额外暗影形态升级或永久来源监听。

完整原始行及 PIN 在 `data/support/starting-deck-spell-school-basics.json`。CORE_SW_448 仅作原始证据，没有可执行适配。实验构筑使用完整 30 槽和明确合成英雄、初始技能及背景牌；这不扩展生产代表包或正式卡池。

引入时 prototype-v237/core-effects-v231。新增冻结 payload 只有 spell_school/scope 两字段并显式注册；原持久结构、schema215、旧 1～214 拒绝、观察74、命令11、replay1 保持。处理器签名改变，旧快照仍需原规则与处理器。精确国服开局窗口、空法术及形态政策尚未校准，实际验证与下一项只在 [项目状态](project-status.md) 和 [机制清单](mechanism-backlog.md) 维护。
