# 原结果驱动的玩家追加伤害

放出巨虫TLC_631与格里什巨虫TLC_631t按[完整三行与四份双语主面](../data/cards/damage-quest-reward-v1.json)接入；TLC_631e仅保存附魔原证据，没有可执行白板定义。[官方33.0.3](https://hearthstone.blizzard.com/en-us/news/24224212)将任务从15次改为12次，[官方33.2](https://hearthstone.blizzard.com/en-gb/news/24223019)明确奖励也在对手回合生效。固定37.0来源一致；精确国服窗口仍待M6，[来源边界](../outputs/card-integration-20261014/k274-damage-quest/rule-sources-01.json)保留主面与推断的区别。

任务组合原QuestSpec、AdvanceQuest与AddToHand。条件只读真实health_resolved：最终DAMAGE、实际damage_dealt恰为2、原来源控制者为本人、原目标是敌方角色，任务另要求原活跃玩家为本人。按原batch_id/packet_index见证计一次，不用请求量、施法次数或累计伤害量代替。护甲承伤计入，圣盾/免疫/零量及治疗不计；未知正伤害归属明确报错，已知系统疲劳不冒充本人卡牌来源。

奖励战吼用原AddPlayerEffect的显式健康来源捕获安装persistent实例，来源死亡、沉默、转控及回手不移动受益方或取消已安装效果。每个实际接受实例对原2伤给出一个独立普通PlayerEffectDamage，继续委托原settle_health_batch；不造第二次施法或付款，不另写数值、护甲、死亡或吸血执行器。额外包沿原逻辑玩家伤害规则，不继承入射包的法伤或吸血，普通健康数值/转换政策保持旧实现。

## 逻辑来源与原目标

新增不可变PlayerHealthOrigin(player_id, instance_id, spec_id)。健康准备时从原完整PlayerEffect建立标记，原物理来源的卡面/实体/驻留归因仍保存；HealthResult增加一个可选player_origin字段，普通物理来源为None。不能只看来源卡名或实体ID识别追加包：格里什自己的真实2攻战斗也能触发奖励，其逻辑输出必须被区分。

奖励按同一程序族排除自己的逻辑输出，包含其他同族实例的输出；多个已接受实例各自对原包追加一次。原PlayerEffectDamage增加可选original_target_result冻结元组，要求匹配实际原damage_history，拒绝同程序族有界请求直接响应自己的结果；普通无此参数的旧调用保持原行为。

派发时核原目标的类型、区域、zone_epoch和entered_order。目标死亡或同ID离场再入场不改投新身体，不通过后来卡名重建原目标；已接受源实例继续复用原来源验证与退休政策。原结果与新来源都沿原选择边界、失败回滚、恢复、clone和回放保存。

保存严格检查逻辑来源字段、分配上界、已知程序及当前仍存在实例的原绑定；已退役实例不提供额外的历史来源认证。原健康事件/历史完整性检查继续存在，无签名存档的整体联合改写不具有外部来源真实性保证。标记和原目标材料不进入玩家观察、合法动作或玩家日志。

独立追加包、精确后结算反应窗口、同族实例叠加、原目标控制/换面窗口及追加包数值来源政策是明确本地契约，论坛报告不作为开发者时序认证。上述官方补丁只支持已说明的门槛与双方回合修复，不能认证全部交互。

只新增1种payload，已有Effect类型清单保持；HealthResult/PreparedHealth/PlayerEffectDamage各增加一个可选字段，全部既有字段保持，model.py中的既有类保持，没有增加GameState字段或账本。core552/schema446拒绝旧1～445；观察99、命令12、回放1保持。实际进度和验证仅在[项目状态](project-status.md)及[机制台账](mechanism-backlog.md)维护。
