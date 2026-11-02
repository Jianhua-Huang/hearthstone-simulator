"""Independent, explicitly partial checks derived from the two printed decks.

This is a host auditor, not a bot input or a replacement rules interpreter.
An observed component is never certification of the complete card.
"""
from collections import Counter

INTRINSIC = {
    'CATA_722': {'taunt'}, 'CATA_565': {'taunt'}, 'CORE_GIL_531': {'taunt'},
    'CORE_CFM_790': {'taunt'}, 'JAIL_912': {'taunt'},
    'CATA_153': {'rush', 'windfury'},
}
HERALD = {'CATA_722', 'CATA_565', 'CATA_497', 'CATA_561'}
DESTROY = {'CORE_EX1_197': 'high', 'END_028': 'low', 'CAP_805': 'all', 'TIME_890': 'all'}
DISCOVERY = {'CORE_GIL_836', 'BE_870', 'TIME_432'}
DRAW = {'CATA_568': 2, 'BE_221': 1}


def facts(game):
    """Read a compact detached host-only boundary; do not encode proof payloads."""
    s = game._state
    entities = {}
    for eid, e in s.entities.items():
        entities[eid] = {'id': eid, 'card_id': e.card_id, 'kind': game.registry.card(e.card_id).kind.value,
            'owner': e.owner, 'controller': e.controller, 'zone': e.zone.value,
            'attack': e.attack, 'health': e.health, 'max_health': e.max_health,
            'armor': e.armor, 'keywords': [k.value for k in e.keywords],
            'silenced': e.silenced, 'dormant': bool(e.dormancy)}
    pending = s.pending_choice
    return {'turn': s.turn, 'active': s.active_player, 'status': s.status,
        'pending': None if pending is None else {'purpose': pending.purpose.value,
            'minimum': pending.min_count, 'maximum': pending.max_count},
        'entities': entities, 'players': {p: {'hero': v.hero_id, 'board': list(v.board),
            'hand': list(v.hand), 'deck': list(v.deck), 'mana': v.mana,
            'max_mana': v.max_mana, 'weapon': v.weapon_id,
            'overload': v.overload_owed} for p, v in s.players.items()}}


def compact_events(events):
    return [{'sequence': e.sequence, 'kind': e.kind, 'player_id': e.player_id,
             'source_id': e.source_id, 'target_id': e.target_id, 'amount': e.amount}
            for e in events]


def evaluate(card_id, source_id, actor, native, before, after, events, registry):
    """Check only exercised clauses. Ambiguous complex outcomes need review."""
    checks = []
    def check(clause, condition, evidence, *, hard=False):
        checks.append({'clause': clause, 'status': 'pass' if condition else ('fail' if hard else 'needs_review'),
                       'card_id': evidence.get('source_card',card_id),
                       'evidence': evidence, 'scope': 'component_only'})
    def kinds(kind, player=None):
        return [e for e in events if e['kind'] == kind and (player is None or e['player_id'] == player)]
    def source_events(kind):
        return [e for e in kinds(kind) if e['source_id'] == source_id]
    be, ae = before['entities'], after['entities']
    played = getattr(native, 'entity_id', None) == source_id and type(native).__name__ == 'PlayCard'
    countered = any(e['kind'] in ('spell_countered', 'minion_countered') for e in events)
    if played and not countered:
        for keyword in sorted(INTRINSIC.get(card_id, ())):
            # Printed intrinsic text is checked against the definition. Auras and
            # immediate silence may legitimately change the resulting entity.
            actual = {k.value for k in registry.card(card_id).keywords}
            check('印刷固有关键词：' + keyword, keyword in actual, {'definition_keywords': sorted(actual)}, hard=True)
        if card_id in HERALD:
            n = len(source_events('heralded'))
            check('出牌触发兆示', n >= 1, {'herald_events': n})
        if card_id == 'CATA_561':
            new = [e for i,e in ae.items() if i not in be and e['card_id'] == 'CATA_561t']
            check('获取两张幼体风灵', len(new) >= 2, {'new_breezlings': len(new)})
        if card_id in DISCOVERY:
            pending = after.get('pending')
            picked = kinds('pool_discovery_picked')
            check('进入发现选择或完成发现', bool(pending or picked), {'pending': pending, 'picked_events': len(picked)})
        if card_id == 'BE_114':
            pending = after.get('pending')
            check('进入拼装选择', bool(pending and pending['purpose'] == 'assemble'), {'pending': pending})
        if card_id in DRAW:
            expected = min(DRAW[card_id], len(before['players'][actor]['deck']))
            observed = len(kinds('card_drawn', actor)) + len(kinds('card_burned', actor))
            check('抽牌数量（含满手烧牌）', observed >= expected,
                  {'minimum_expected': expected, 'observed_draw_or_burn': observed, 'empty_deck_not_certified': expected < DRAW[card_id]})
        if card_id in DESTROY:
            mode = DESTROY[card_id]
            victims = [i for p in (1,2) for i in before['players'][p]['board']
                       if be[i]['kind']=='minion' and not be[i]['dormant'] and i != source_id and
                       (mode == 'all' or mode == 'high' and be[i]['attack'] >= 5 or mode == 'low' and be[i]['attack'] <= 4)]
            died = {e['target_id'] or e['source_id'] for e in kinds('minion_died')}
            check('消灭描述范围内的原随从', set(victims) <= died,
                  {'expected_original_victims': victims, 'missing_death_events': sorted(set(victims)-died)})
        if card_id == 'END_028':
            delta = after['players'][actor]['overload'] - before['players'][actor]['overload']
            check('过载2', delta >= 2, {'overload_delta': delta})
        if card_id == 'EDR_970':
            check('灌注英雄技能', bool(source_events('imbued')), {'imbue_events': len(source_events('imbued'))})
        if card_id == 'CORE_GIL_531':
            new = [e for i,e in ae.items() if i not in be and e['owner'] == actor and e['kind'] == 'spell']
            check('生成法术', bool(new), {'new_spell_count': len(new), 'class_and_full_pool_require_review': True})
        if card_id == 'CORE_CFM_790':
            hand = set(before['players'][3-actor]['hand'])
            eligible = {i for i in hand if be[i]['kind'] == 'minion'}
            summoned = {e['target_id'] or e['source_id'] for e in kinds('minion_summoned', 3-actor)}
            if eligible and len(before['players'][3-actor]['board']) < 7:
                check('从对手手牌召唤随从', bool(eligible & summoned), {'eligible_count': len(eligible), 'from_hand_summoned': sorted(eligible & summoned)})
        if card_id in ('BE_778', 'BE_014', 'CATA_190h'):
            checks.append({'clause': '技能/灾变选择与后续主体', 'status': 'needs_review',
                           'card_id':card_id,'scope': 'component_only', 'evidence': {'pending': after.get('pending'), 'event_kinds': sorted({e['kind'] for e in events})}})
    # Trigger observations include both decks, independently of the played root.
    died = {e['target_id'] or e['source_id'] for e in kinds('minion_died')}
    for eid in died & be.keys():
        entity = be[eid]
        if entity['silenced']: continue
        owner = entity['controller']
        if entity['card_id'] == 'CORE_EX1_012':
            n = len(kinds('card_drawn', owner)) + len(kinds('card_burned', owner))
            if before['players'][owner]['deck']:
                check('萨尔诺斯亡语抽牌', n >= 1, {'source_card': entity['card_id'], 'draw_or_burn': n})
        if entity['card_id'] in ('JAIL_912', 'TIME_EVENT_300'):
            n = len(kinds('minion_summoned', owner))
            check('亡语召唤随从', n >= 1, {'source_card': entity['card_id'], 'summons': n, 'stats_and_healing_require_review': True})
    if before['active'] != after['active']:
        incoming = after['active']
        doom = [i for i in before['players'][incoming]['board'] if be[i]['card_id'] == 'CORE_NEW1_021' and not be[i]['silenced'] and not be[i]['dormant']]
        if doom:
            expected = {i for p in (1,2) for i in before['players'][p]['board'] if be[i]['kind']=='minion' and not be[i]['dormant']}
            check('末日预言者回合开始清场', expected <= died, {'source_card':'CORE_NEW1_021','sources': doom, 'missing_death_events': sorted(expected-died)})
    if type(native).__name__ == 'Attack':
        weapon = before['players'][actor]['weapon']
        if getattr(native, 'attacker_id', None) == before['players'][actor]['hero'] and weapon and be[weapon]['card_id'] == 'BE_349':
            new = [e for i,e in ae.items() if i not in be and e['card_id'] == 'BE_349t']
            minimum = min(2, 7-len(before['players'][actor]['board']))
            check('附眼战槌英雄攻击后召唤', len(new) >= minimum, {'source_card':'BE_349','new_tokens': len(new), 'minimum_from_initial_slots': minimum})
    return checks


def summary(rows):
    return dict(Counter(c['status'] for row in rows for c in row.get('effect_checks', ())))
