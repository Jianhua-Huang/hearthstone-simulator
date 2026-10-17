# 时光流汇、原发现结果与手牌复制

TIME_436、TIME_436t1、TIME_436t2的完整原行、六张严格双语官网主面和真实父子关联保存在[data包](../data/cards/native-timeway-locations-v1.json)。过去形态按印刷费用至少5、可收藏随从与公共dragon/ALL匹配随机召唤；现在和未来形态发现并召唤相同费用/种族范围，复用原current职业加中立查询。前两形态在主体完成后推进原地标，未来形态额外获得原选中卡的复制。

生成与发现仍使用宿主GenerationContext、完整constructed.cards资格及原公共生产者；未知合格内容明确失败，不删池。真实LOCATION的SummonCause为card_effect，无虚构施法或战吼。LocationFaceReference在主体前捕获，原使用递减耐久、冷却、末次死亡与主体、升级失效均沿既有地标生命周期；新同名地标不能接收旧升级。

有限新增声明为DiscoverFromPool.copy_selected_to_hand=True。仅支持一次、三个选项、after_each、原来源归因的普通可收藏随从场上发现，默认False；不与赠礼、属性设值、冻结、费用或手牌复制召唤等独立配方混用。旧gift_copy_to_hand要求真实赠礼池，summon_copy_stats则是先入手再复制到场，均不代替本入口。

CopyDiscoveredCardToHand(producer_id,index)在原SummonByCard请求及入场反应完成后核验原父子关系、原因和完整ChoiceResult。复制材料是原选中基础卡配方，不能扫描后来场上、手牌或同名实体；入场后的增益、变形、死亡及转控不重绑定复制源。原场上交付因满场失败仍保留选择并获取复制，满手则沿普通创建烧牌。原请求的数量额外体不额外生成手牌。

上述“基础配方、全部入场反应之后、满场仍复制”是当前明确本地政策，官网卡面没有证明其精确时序；职业/隐式生成资格也沿既有待校准政策。补充官方公开说明仅确认过去/现在/未来地标主题（[官方扩展介绍](https://news.blizzard.com/en-gb/article/24245210/across-the-timeways-is-now-live)），不能据此认证这些边界或国服37.0热修。M0正式池、M6国服校准和实际可达完整性独立开放。

DiscoverySummonRecord.copy_acceptances保存接受索引的有序前缀，discovery_summon_copy_started私有完整事件绑定已完成的原子请求。等待队列必须保留唯一应有复制控制，完成生产者须已接受全部应有复制；选择不能注入控制。记录接受与调用已有create_hand_card在同一步完成，普通创建反应、终局、异常回滚、回溯、独立reader恢复和回放由原解释器负责。内部请求、接受和完整历史不投影给玩家，普通新手牌只按原信息规则可见。

新增一个请求字段、一个既有记录字段和一个Effect，无新增GameState/实体字段或payload类型。core444/schema362拒绝旧1～361；观察92、命令12、replay1保持。实际验证结果和后续事项仅维护在项目状态及机制台账。
