"""Real finite cost conditions over original physical zones or casts."""
from dataclasses import replace
from .model import (CardType,CostPresenceMatch,CostPresenceRow,PRESENCE_COST_CONDITIONS,
    SpellSchool,Zone,Rarity,CONTROLLED_PLAY_ZONES)
from .player_spell_count_costs import row_for
from .tribes import tribe_changes,tribe_state_for


def dragon_row(row,registry):
    if row.kind != CardType.MINION:return False
    current=tribe_state_for(registry,row.card_id,row.tribe_changes)
    if current is None:
        from .registry import UnsupportedDefinitionError
        raise UnsupportedDefinitionError('Unknown current tribe set in original hand: '+row.card_id)
    return current.matches_any(('dragon',))


def aggregate(condition,player_id,turn,source_id,hand,boards,casts,registry,card_ids=()):
    if condition=='controlled_card':
        for cid in card_ids:
            if registry.card(cid).kind not in (CardType.MINION,CardType.LOCATION,CardType.WEAPON):
                raise ValueError('Named controlled price requires an actual resident minion, location or equipped weapon')
        return any(x.card_id in card_ids for x in boards[player_id-1])
    if condition=='hand_edge':
        return bool(hand and source_id is not None and source_id in (hand[0].entity_id,hand[-1].entity_id))
    if condition=='controlled_legendary':
        from .target_predicates import printed_rarity
        matches=tuple(printed_rarity(registry,x.card_id)==Rarity.LEGENDARY for x in boards[player_id-1])
        return any(matches)
    if condition=='hand_other_dragon':
        # Validate every physical row, including an excluded source and rows after a true result.
        matches=tuple(dragon_row(x,registry) for x in hand)
        return any(x.entity_id!=source_id and match for x,match in zip(hand,matches))
    if condition=='board_dormant_minion':
        return any(x.kind==CardType.MINION and x.dormant for board in boards for x in board)
    if condition=='board_no_minions':
        return not any(x.kind==CardType.MINION and registry.card(x.card_id).interactable is None
                       for board in boards for x in board)
    return {SpellSchool.HOLY,SpellSchool.SHADOW}<={x.spell_school for x in casts
        if x.player_id==player_id and x.turn==turn and x.payload_started and x.failure is None}


def capture_row(state,registry,eid,player_id,zone):
    entity=state.entities[eid];card=registry.card(entity.card_id)
    if (entity.id,entity.controller,entity.zone,entity.kind)!=(eid,player_id,zone,card.kind):
        raise ValueError('Presence price inventory differs from its original physical zone/type')
    return CostPresenceRow(eid,entity.card_id,player_id,entity.kind,zone,entity.zone_epoch,
        entity.entered_order,entity.dormancy is not None if zone==Zone.BOARD and entity.kind==CardType.MINION else False,tribe_changes(entity))


def capture(state,registry,player_id,condition,source_id=None,*,card_ids=()):
    if type(player_id)is not int or player_id not in (1,2) or condition not in PRESENCE_COST_CONDITIONS:
        raise ValueError('Unknown finite presence payer/condition')
    if source_id is not None and source_id not in state.entities:
        raise ValueError('Presence price has no original physical subject')
    hand=tuple(capture_row(state,registry,e,player_id,Zone.HAND) for e in state.players[player_id].hand
        ) if condition in ('hand_other_dragon','hand_edge') else ()
    boards=tuple(tuple(capture_row(state,registry,e,p,Zone.BOARD) for e in state.players[p].board)
        for p in (1,2)) if condition in ('board_dormant_minion','board_no_minions') else ((),())
    if condition in ('controlled_legendary','controlled_card'):
        player=state.players[player_id]
        ids=(player.hero_id,*player.board,*player.quests,*player.secrets,
             *((player.weapon_id,) if player.weapon_id is not None else ()),
             *((player.hero_power_id,) if player.hero_power_id is not None else ()))
        rows=tuple(capture_row(state,registry,e,player_id,state.entities[e].zone) for e in sorted(ids))
        if any(x.zone not in CONTROLLED_PLAY_ZONES for x in rows):
            raise ValueError('Controlled price borrowed a non-playing carrier')
        boards=(rows,()) if player_id==1 else ((),rows)
    casts=()
    if condition=='turn_holy_and_shadow':
        from .spell_casts import validate_history
        validate_history(state,registry)
        casts=tuple(row_for(x,registry) for x in state.cast_history)
    match=CostPresenceMatch(player_id,condition,state.turn,state.action_number,state.next_entity_id,
        state.next_attachment_id,source_id,aggregate(condition,player_id,state.turn,source_id,hand,boards,casts,registry,card_ids),
        hand,boards,casts,card_ids)
    validate_match(match,registry);return match


def validate_match(match,registry):
    if type(match)is not CostPresenceMatch:raise ValueError('Presence requires typed complete original operands')
    match.__post_init__()
    for row in (*match.hand,*match.boards[0],*match.boards[1]):
        if registry.card(row.card_id).kind!=row.kind:raise ValueError('Presence rewrote its original registered physical type')
    for row in match.cast_rows:
        card=registry.card(row.card_id)
        if card.kind!=CardType.SPELL or card.spell_school!=row.spell_school:
            raise ValueError('Presence rewrote a declared original cast school')
    if match.matched!=aggregate(match.condition,match.player_id,match.turn,match.source_id,
            match.hand,match.boards,match.cast_rows,registry,match.card_ids):
        raise ValueError('Presence rewrote its original aggregate')


def validate_prefix(match,state,registry):
    validate_match(match,registry)
    rows=(*match.hand,*match.boards[0],*match.boards[1])
    if match.next_entity_id>state.next_entity_id or match.next_attachment_id>state.next_attachment_id or any(
            row.entity_id not in state.entities for row in rows) or (
            match.source_id is not None and match.source_id not in state.entities):
        raise ValueError('Presence lost its original physical allocation prefix')
    if match.condition=='turn_holy_and_shadow':
        from .spell_casts import validate_history
        validate_history(state,registry)
        if len(match.cast_rows)>len(state.cast_history):raise ValueError('Presence lost its original cast prefix')
        for old,record in zip(match.cast_rows,state.cast_history):
            current=row_for(record,registry)
            if old.payload_started and not current.payload_started or replace(old,payload_started=current.payload_started)!=current:
                raise ValueError('Presence changed its original cast acceptance prefix')


ACCEPTED='controlled_card_cost_accepted'


def note_paid(r,play,fact):
    """Bind the complete compact inventory before its genuine physical payment."""
    if not fact.intrinsic.rules or fact.intrinsic.rules[0].condition!='controlled_card':return
    from dataclasses import asdict
    import json
    match=fact.intrinsic.condition_facts[0]
    r.emit(ACCEPTED,source_id=play.source_id,player_id=play.player_id,play_id=play.id,card_id=play.card_id,
        match_json=json.dumps(asdict(match),sort_keys=True,separators=(',',':')),_capture=False)


def validate_game(game):
    from dataclasses import asdict
    import json
    from .hero_health_history import effective_events
    expected={p.id:p for p in game._state.play_history if p.submitted_cost is not None and
        p.submitted_cost.quote.intrinsic.rules and p.submitted_cost.quote.intrinsic.rules[0].condition=='controlled_card'}
    seen=set()
    for event in effective_events(game._events):
        if event.kind!=ACCEPTED:continue
        data=dict(event.data)
        if set(data)!={'play_id','card_id','match_json'}or type(data['play_id'])is not int or data['play_id']in seen or data['play_id']not in expected:
            raise ValueError('Controlled-card price lost its unique original physical acceptance')
        play=expected[data['play_id']];match=play.submitted_cost.quote.intrinsic.condition_facts[0]
        if ((event.source_id,event.player_id,event.action,data['card_id'])!=(play.source_id,play.player_id,play.action,play.card_id)or
                json.loads(data['match_json'])!=json.loads(json.dumps(asdict(match)))):
            raise ValueError('Controlled-card price changed its complete original presence inventory')
        seen.add(play.id)
    if seen!=set(expected):raise ValueError('Controlled-card physical price acceptance was cropped')


def from_dict(value):
    from .serialization import _row,_list,_enchantment_from_dict
    from .model import PlayerSpellCountCostRow
    row=_row(value,CostPresenceMatch)
    row['card_ids']=tuple(_list(row['card_ids'],'original exact controlled card selectors'))
    def physical(value):
        r=_row(value,CostPresenceRow);r['kind']=CardType(r['kind']);r['zone']=Zone(r['zone'])
        r['tribe_changes']=tuple(_enchantment_from_dict(x) for x in _list(r['tribe_changes'],'original tribe attachments'))
        return CostPresenceRow(**r)
    row['hand']=tuple(physical(x) for x in _list(row['hand'],'original hand presence'))
    row['boards']=tuple(tuple(physical(x) for x in _list(board,'original board presence'))
        for board in _list(row['boards'],'complete original boards'))
    casts=[]
    for value in _list(row['cast_rows'],'original presence cast prefix'):
        r=_row(value,PlayerSpellCountCostRow);r['spell_school']=None if r['spell_school'] is None else SpellSchool(r['spell_school'])
        casts.append(PlayerSpellCountCostRow(**r))
    row['cast_rows']=tuple(casts);return CostPresenceMatch(**row)
