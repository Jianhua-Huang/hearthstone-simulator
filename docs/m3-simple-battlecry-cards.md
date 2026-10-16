# 原生战吼的属性、目标、抽牌与灌注

本页为接入契约，实际进度、验证证据与下一项仅在[项目状态](project-status.md)和[机制清单](mechanism-backlog.md)登记。完整源行与显式配方在[simple-battlecry数据](../data/cards/simple-battlecry-effects-v1.json)。卡牌使用原CardDefinition.battlecry，普通召唤不执行战吼，不增第二套入场或触发执行器。

血帆袭击者从实际装备槽读取当前武器攻击，用Buff增加本体攻击，不采用英雄额外攻击或消耗其次数；无武器不增加。暴虐食尸鬼在主体执行时取当前双方其他普通随从，交一次MINION_ABILITY DamageBatch，排除自身和英雄，不添加法伤。野蛮先锋读取执行者当前英雄攻击，对原敌随从目标交MINION_ABILITY Damage；无目标不生成伤害。上述当前查询通过命名InvokeBehavior续接，保留原source/player/target/play身份。

野蛮先锋声明enemy/MINION/BOARD，冰川裂片声明enemy/HERO或MINION。两者都用TargetMode.IF_AVAILABLE，使正常无目标入场与已有目标时必须选择沿原目标预检和玩家枚举；不是把战吼的可选目标规则改成法术必需目标。冰川裂片交原Freeze，冻结和解冻时钟继续由内核维护，不能冻结友方角色。

女巫森林灰熊读取当前对手物理手牌数量，调用带负health的Buff，表示失去当前/上限属性；不是Damage，不触发受伤或伤害归因。沉默还原与后续死亡由原数值/附魔机制处理，不在卡牌中维护减血或手牌数量缓存。

奇异训犬师用DrawMatching的MINION/beast原物理牌库过滤、random选择、空匹配skip，然后Imbue；无匹配或空牌库仍执行灌注。随机沿已有区域抽取流程，其通知和可等待反应在实际抽牌处，不另增random_choice事件；实际抽中实体和原RNG状态随快照/回放保持。月翼信使和振翅守卫分别保留印刷吸血、嘲讽/圣盾，战吼只组合原Imbue，按实际执行者当前英雄职业成长，不用印刷职业覆盖当前英雄。

`python -B -X utf8 -m examples.card_simple_battlecries`经玩家命令展示八根主体、真实武器/英雄攻击区别、冰冻、同时伤害、生命属性、物理抽牌、三次灌注及月翼信使致命战斗后的吸血。全部稳定位置独立恢复/克隆/回放；混合职业30法力场景不认证正式套牌。源记录与内部测试不能替代精确国服的条件/主体读取、伤害/生命属性、过滤抽样、灌注及冻结窗口校准，正式卡池/热修状态仍由M0/M6维护。
