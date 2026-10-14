# B09b：实际过载增量

原 `mana_changed.amount` 表示当下可用法力变化，不能表示新增待锁水晶。例如 `Overload(1, 2)` 通常使待锁量增加2，可用法力变化却是0。本项在既有[资源模块](../hs_sim/engine/resources.py)补充事实，没有新增账户、进度模块或结算器。

## 接口与窗口

实际执行 `Overload` 后，保持原账目和 `mana_changed`，再为正增量发布 `overload_added`：`player_id` 为受影响玩家，`amount` 为本次新增量，内部数据保存 `pending_before / pending_after`。此前待锁8、本次增加1时，金额是1，账目从8到9，不能记成9。

初始化已有过载、回合开始转锁、解锁、恢复法力、改变水晶、临时法力及零量过载不产生该事实。候选沿原解释器捕获、排队和执行，卡牌直接订阅 `HandProgressSpec('event', 3, next_form, event='overload_added', condition_id=owner_condition, amount_basis='event_amount', upgrade_cost_policy='clear_local')`；不反推旧余额，不在闭包存进度。原 `mana_changed` 之后的窗口为明确内部政策，待M6国服校准。

双方玩家日志只给玩家和正整数金额，不给前后账目载荷、实体身份或隐藏手牌收据。信息导入拒绝零、负、布尔金额、缺少玩家及额外实体身份。当前运行时 `prototype-v166 / core-effects-v166`，schema161拒绝旧1～160；玩家观察71，命令10及replay1保持。

## 必要代表与范围

[完整4条原始记录](../data/support/overload-facts.json)固定蓝宝石三形态与闪电箭。官方[蓝宝石卡文](https://hearthstone.blizzard.com/en-gb/cards/43331-lesser-sapphire-spellstone/)说明累计过载3水晶；一次事件一级、超额丢弃和升级费用细则沿用[数值进度契约](m3-spellstone-progress.md)的内部政策，未国服校准。

隔离代表直接复用持牌数值进度。三个闪电箭产生三次1水晶事实；其过载/伤害顺序沿用已有代表。蓝宝石费用、友方随从目标及1/2/3复制主体用现有效果表达，验证普通实体上的必要行为，不认证全部复制窗口或复杂主体交互。生产代表与合成包不扩大。

实际测试和下一项仅在[项目状态](project-status.md)与[机制清单](mechanism-backlog.md)维护。其他法术石的资格与共同施法事实、阴谋、圣契、M0正式池、M6及M7仍开放。

当前共享API为prototype-v189/core-effects-v183/schema178，拒旧1～177；观察74/命令11/replay1保持。[本局实际过载量](m3-player-overload-costs.md)在原正增量发布处保存完整不可变历史供纯数量查询，不改变Overload执行、原事件数据/顺序或本契约的持牌进度资格；精确发布窗口与CN仍待校准。
