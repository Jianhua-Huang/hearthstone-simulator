# M5-13d-03d-02a 历史归属、载体生命周期与转控

v84在[有上限序列](m5-battlecry-sequences.md)上增加显式来源政策，45项专项、4309项全量与68示例通过。没有新增真实卡牌。原型政策归R-125，不能直接宣称沙德沃克已适配或通过国服校准。

## 原出牌玩家与执行玩家

`BattlecryRecord.history_player_id`记录历史来源属于谁：`played_history`对应原PlayRecord玩家，`history`对应被复制的实际BattlecryRecord执行玩家。手牌和物理effect来源必须为None。`player_id`仍是本次激活的执行玩家。历史声明验证使用history_player_id；资源、目标关系、条件和玩家选择使用本次执行玩家。

新增`controller_policy=captured|current`记录选择执行玩家的政策。普通历史重复保持captured，历史所属玩家必须与执行玩家相同；current只开放给出牌历史主体来源，开始时必须匹配载体现任控制者。过去的current激活不能拿如今的控制者反查，因为后续可能再次转控。恢复使用保存的来源归属和接受记录，并校验序列政策一致性；可信宿主快照仍不是带签名的真实对局认证。

例如P1曾打出的护甲战吼，在序列中载体转给P2后，可以产生`history_player_id=1, player_id=2`的子激活。候选仍是P1接受时的历史，不能重查为P2的卡池。此子激活本身则属于P2的实际激活历史，之后P2重复它时，新的history来源归属为2。没有付款、提交或额外出牌。

## 可组合的来源政策

`RepeatPlayedBattlecrySequence(..., policy=BattlecrySequencePolicy(...))`默认保持v83行为。

| 字段 | 契约 |
| --- | --- |
| source=captured | 接受后继续，不因离场、变形、休眠或转控重选主体 |
| source=in_play | 下次尝试前要求活跃、未致死且仍在对应随从/英雄/武器区域 |
| source=same_incarnation | 除in_play外，要求zone_epoch与接受时相同，当前卡面等于捕获载体卡面；变回同一张卡也不恢复旧资格 |
| controller=captured | 每次执行仍使用序列的原玩家 |
| controller=current | 每次子战吼开始前读取现任控制者，保持原历史候选和历史归属 |
| stop_on_silence | 独立选择是否在下一次尝试前因沉默停止；默认false |
| exclude_source_target | 原声明目标域之外，再排除载体自己的实体ID；其他副本不被排除 |

source检查在序列接受前和每次子激活之前进行。已接受的子激活仍完成自己的主体；例如开始监听将来源杀死，不撤销本次已经接受的主体，但会阻止下次。子主体中休眠后又醒来，在下一检查点已经恢复活跃，则可继续；这不是“曾休眠过就永久停止”的政策。转控不改变zone_epoch，因此same_incarnation可以与current共同使用。

同样，开始监听或主体中的转控不会改变本次已捕获玩家、目标和已生成效果。后续尝试使用新玩家。卡牌回调应明确使用context.player_id表达执行方；context.source.controller仍是该上下文快照中的物理控制者，二者不强制混同。

规则停止不制造失败子记录、不重新抽样、不消耗剩余名额，也不制造终局；当前已执行的效果保留。引擎预算耗尽仍是错误与当前操作回滚。目标排除只缩小声明域：REQUIRED域为空得到no_target，IF_AVAILABLE域为空允许无目标主体；不会放宽声明中的原有限制。

## 保存与验证

BattlecryRecord新增history_player_id、controller_policy与exclude_source_target；续接保存same_incarnation使用的source_epoch。新字段进入严格的记录/帧校验：历史归属缺失、伪造归属、默认captured下跨玩家执行、原手牌来源附带历史玩家、源epoch缺失/未来/布尔值、目标政策与序列不一致或排除载体后却指向自身，均拒绝恢复。

暂停时来源已经失效仍允许恢复正在执行的主体；完成后按保存政策停止。转控后的P2选择可以经P2受限接口继续；P1只知道选择归P2。玩家观察与日志不公开原始候选、history_player_id、controller_policy或source_epoch。

因为持久记录布局改变，规则/效果84、快照schema81；旧1～80明确拒绝，要求对应原引擎。replay1、观察46、命令7和代表包45保持。普通默认序列、鹦鹉/伯尔纳等已有行为应保持，不能通过改变默认规则满足新来源需求。

## 验收与后续

[45项专项](../tests/test_m5_sequence_lifecycle.py)覆盖转控后目标/护甲/手动与自动选择、历史查询、转控再转回、开始监听捕获边界、死亡/回手/同名变形/沉默/休眠与唤醒、武器损坏/英雄替换、铜须重复、两类回溯、嵌套序列、恢复拒绝、回滚及信息隔离。

[组合示例](../examples/battlecry_source_lifecycle.py)用合成牌先保存P1四份历史，然后转给P2、由P2选择获得护甲，随后回手并停止剩余主体；保存恢复与全回放一致。样例用来验证公共表达能力，不是正式沙德沃克规则证明。

下一项13d-03d-02b继续[具体来源政策审计](m5-shudderwock-policy-audit.md)，先确认限额后续修订、自身排除/抽样及生命周期的证据等级，再接入必要真实代表。R-124/R-125、其他机制缺口、M0完整池、M6校准与M7批量适配均未完成。

最终内部证据：45专项（4.358秒）、404既有战吼回归、4309全量（631.590秒）、70代表检查、68示例和CLI通过；64个既有摘要共同结果字段不变，见[比较报告](../outputs/v84-example-count-check.json)。
