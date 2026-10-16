# 原出牌随从的关键词奖励

本契约说明真实出牌监听如何复用原事实和关键词执行器。实际进度、验收证据、差异和下一项只在[项目状态](project-status.md)与[机制台账](mechanism-backlog.md)维护。

[完整固定源](../data/cards/played-minion-keywords-v1.json)与[适配](../hs_sim/cards/played_minion_keyword_cards.py)分别表达黑市监管者的亡语随从突袭、梦缚迅猛龙的随从额外效果。原card_played事件必须对应完整、已完成的PlayRecord，玩家及物理来源匹配。效果召唤、对手出牌、法术/技能和监听者自身这次出牌不进入本地配方。亡语资格取原submitted_cost.quote.quote_input.abilities，不能按后来变形后的牌名重新判断。

原随从以本次真实动作内首条对应SuccessfulSummonRecord绑定首次实际入场，再用BoardPresenceReference辨认连续战场驻留。后续同驻留变形可以改变卡面；离场再入场不能只凭相同entity_id重新获得旧奖励。奖励主体先返回带原play_id的InvokeBehavior，真正执行时按当前局面解析原驻留，再委托GrantCapturedKeyword或GrantRandomBonusEffects。这样早于该奖励执行的其他反应也受原驻留约束，而非只检查战吼结束时的旧状态。

原监听者是奖励归因来源，原被使用牌是续接的物理来源，两者不能混淆。具名续接使用已有严格play_id/来源校验，未增加GameState字段、公共请求类型或随机算法。额外效果仍由公共模块选择完整当前可用关键词；原突袭、攻击许可、沉默、随机、健康和死亡负责实际行为。既有[额外效果契约](m4-bonus-effects.md)中的构筑政策不因这两张卡扩大为战棋规则。

磁力合并等未核实的接收形态保持显式UnsupportedDefinitionError，不任意奖励合并来源、宿主或裁掉真实候选。自身入场排除、原提交亡语资格、转化与反应的准确窗口仍需相应国服证据；配方内部验证不替代这些校准或正式标准池完整性。其他真实来源按需核实，不能从接口推演组合待办。
