# 永久复制手牌的独立表达

本页描述用现有公共原语表达一个永久替换来源。实际执行、验收和下一项只在[项目状态](project-status.md)及[机制清单](mechanism-backlog.md)维护。内核、存档与玩家协议保持原版本；这个表达没有新增状态或模块。

## 真实来源

必要来源是 GIL_198 窃魂者阿扎莉娜：战吼将自己的手牌替换为对手手牌的复制。[完整本地原始记录](../data/support/permanent-hand-basics.json)保留全部字段、原记录哈希和固定总 pin；费用、身材、职业、稀有度与种族从该记录核对。可执行声明仅在[隔离代表专项](../tests/test_permanent_hand_basics.py)注册，生产代表包保持原代码。

[官方介绍](https://hearthstone.blizzard.com/en-us/news/22819075)确认阿扎莉娜获得对手手牌的复制，[官方卡库](https://hearthstone.blizzard.com/pt-br/cards/46874-azalina-soulthief/)检索卡文确认替换方向。这些证据未规定所有当前国服复制材料或结算窗口，不能作为完成 M6 的依据。

## 表达与区域职责

```python
held = tuple(CardReference.capture(c.state.entities[eid])
    for eid in c.state.players[c.player_id].hand)
other = tuple(CardReference.capture(c.state.entities[eid])
    for eid in c.state.players[3 - c.player_id].hand)
return (RemoveFromGame(held, c.source_id),) + tuple(
    CopyCard(ref, c.player_id, source_id=c.source_id) for ref in other)
```

出牌管线已把阿扎莉娜放入战场并支付普通费用，战吼捕获的是剩余手牌。两组引用按当时实际手牌顺序捕获，重复卡面仍是不同物理实体；对手原牌保留原位置、归属和获取记录。

原组使用[非死亡移除](m3-nondeath-removal.md)整批进入私有 SETASIDE。原手牌先腾出容量，再执行普通复制；这不产生弃牌、死亡、烧牌、抽牌或疲劳。空原组没有虚构移除事件；空对手手牌仍可移除自己的原组。当前表达没有延后取回，也不创建 TemporaryHandReplacement。

每个 CopyCard 使用既有 current 模式，新实体属于接收方，保存原物理来源并获得独立附件 ID 和新手牌获取；它使用[普通区域复制](m3-zones.md)的材料与引用守卫。没有为这个来源增加任意能力授予、合成卡面或额外复制政策。

## 接受窗口与生命周期

原组移除是整批完成后才发布事件；复制沿用每一个普通效果的检查点。第一个复制事件暂停时，仅第一张新牌已存在，其余捕获引用由解释器等待队列保留。整个复制组不宣称是原子提交。

捕获的引用仍受 controller、区域、卡面和 epoch 守卫约束。反应造成离区或换面时保留原 CopyCard 的失效行为，不能追踪后来的新驻留；没有根据这个有限代表擅改全局复制时序。

永久复制牌不会在本人结束或下一本人开始被清理，后来正常取得的牌也保留。原实体不再自动取回；来源死亡没有取回义务。已打出的复制随从沿正常战场生命周期保留，复制的普通法术仍可正常支付和执行。终局也不会创建临时手牌记录。

解释器复用现有事务、选择续接和帧白名单。原组移除后或首张复制后真实待选，可以用独立注册表恢复、clone 及完整动作回放；晚错误整体回滚付款、原组、新实体、信息与随机状态。

## 玩家信息与校准边界

持有方正常看到取得的复制卡面。双方 DTO 不公开 SETASIDE、原物理 ID、复制 origin 或私有捕获队列。移除事件只保留原非死亡移除的最小投影：本人知道自己的原卡面，未知对手原牌不因移除揭示；先前确实已知的卡面可作为历史事实保留，但原可操作句柄退役。读取玩家视图和日志不改变状态。

当前 current 材料、整批原组移除政策、一次捕获与逐张复制的精确优先级仍待国服校准。这里只验证必要永久复制来源；随机或固定替换主体、完整生成池及全手互换的真实构筑来源仍须逐项核对，U37 保持 partial。不得凭旧附魔文本或其他模式数据制造新的组合机制。
