"""Player accounts, independent of card definitions and individual behaviors."""
from dataclasses import dataclass, fields

from .effects import (GainTemporaryMana, RefreshMana, ChangeManaCrystals, DestroyAllManaCrystals, SetManaCap,
                      Overload, UnlockOverload, GainResource, SpendResource)
from .errors import ResolutionError
from .model import ArmorLossResult, CardType, CorpseSpendRecord, Event, ManaConsumptionRecord, Resource, _int


def armor_loss_result(event):
    if event is None:
        return None
    if type(event) is not Event:
        raise ValueError('Armor loss result requires an Event')
    if event.kind not in ('armor_loss_resolved','armor_lost'):
        return None
    data=dict(event.data)
    if len(event.data)!=1 or set(data)!={'result'}:
        raise ValueError('Armor loss requires its complete immutable result')
    raw=data['result']
    if type(raw) is not tuple or any(type(x)is not tuple or len(x)!=2 or type(x[0])is not str for x in raw):
        raise ValueError('Armor loss result requires immutable fields')
    values=dict(raw)
    if len(values)!=len(raw) or set(values)!={f.name for f in fields(ArmorLossResult)}:
        raise ValueError('Armor loss result lost or duplicated original fields')
    result=ArmorLossResult(**values)
    if (event.player_id,event.target_id,event.amount)!=(result.player_id,result.hero_id,result.actual):
        raise ValueError('Armor event differs from its account result')
    if event.kind=='armor_lost' and not result.actual:
        raise ValueError('Zero loss cannot publish a positive armor-loss fact')
    return result


def lose_armor(r,effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r,effect.source_id)
    if effect.on_result is not None: r.registry.behavior(effect.on_result)
    hero=r.state.entities[r.player(effect.player_id).hero_id]
    if hero.kind != CardType.HERO:
        raise ResolutionError('Armor loss requires the currently installed Hero account')
    actual=hero.armor if effect.amount is None else min(hero.armor,effect.amount)
    result=ArmorLossResult(effect.player_id,hero.id,effect.amount,hero.armor,hero.armor-actual,actual)
    hero.armor=result.after
    event=r.emit('armor_loss_resolved',source_id=effect.source_id,target_id=hero.id,player_id=effect.player_id,amount=actual,result=result.payload())
    if actual:
        r.emit('armor_lost',source_id=effect.source_id,target_id=hero.id,player_id=effect.player_id,amount=actual,result=result.payload())
    return [] if effect.on_result is None else [r.call(effect.on_result,effect.source_id,effect.player_id,target_id=hero.id,event=event)]


def validate_armor_loss_events(state,events):
    for i,event in enumerate(events):
        result=armor_loss_result(event)
        if result is None: continue
        hero=state.entities.get(result.hero_id)
        if hero is None or hero.kind != CardType.HERO or hero.owner != result.player_id:
            raise ValueError('Armor loss borrowed an unknown or different Hero account')
        if event.source_id is not None and event.source_id not in state.entities:
            raise ValueError('Armor loss references an unknown physical source')
        if event.kind=='armor_loss_resolved' and result.actual:
            if i+1>=len(events) or events[i+1].kind!='armor_lost' or armor_loss_result(events[i+1])!=result:
                raise ValueError('Positive armor result lost its immediate loss fact')
        if event.kind=='armor_lost':
            if not i or events[i-1].kind!='armor_loss_resolved' or armor_loss_result(events[i-1])!=result:
                raise ValueError('Armor loss fact lost its complete original result')
            old=events[i-1]
            if (old.source_id,old.action)!=(event.source_id,event.action):
                raise ValueError('Armor loss events changed their original source/action')


def mana_balance(player):
    return player.max_mana - player.mana_spent - player.overload_locked + player.temporary_mana


def refresh_mana(player):
    player.mana = max(0, mana_balance(player))


@dataclass(frozen=True)
class ManaSpendProjection:
    temporary_mana: int
    mana_spent: int
    mana: int


def project_mana_spend(player, amount):
    temporary = min(player.temporary_mana, amount)
    temporary_mana = player.temporary_mana - temporary
    mana_spent = player.mana_spent + amount - temporary
    mana = max(0, player.max_mana - mana_spent - player.overload_locked + temporary_mana)
    return ManaSpendProjection(temporary_mana, mana_spent, mana)


def spend_mana(player, amount):
    result = project_mana_spend(player, amount)
    player.temporary_mana = result.temporary_mana
    player.mana_spent = result.mana_spent
    player.mana = result.mana


def mana_consumption_from_dict(value):
    if type(value) is not dict or set(value)!={f.name for f in fields(ManaConsumptionRecord)}:
        raise ValueError('Mana consumption requires its complete original fields')
    row=dict(value)
    if row['source_kind'] is not None: row['source_kind']=CardType(row['source_kind'])
    return ManaConsumptionRecord(**row)


def mana_consumption_result(event):
    if event is None: return None
    if type(event) is not Event: raise ValueError('Mana consumption requires an Event')
    if event.kind not in ('mana_consumption_resolved','mana_consumed'): return None
    if len(event.data)!=1 or event.data[0][0]!='result':
        raise ValueError('Mana consumption event lost its complete original result')
    raw=event.data[0][1]
    if type(raw) is not tuple or any(type(x) is not tuple or len(x)!=2 or type(x[0]) is not str for x in raw):
        raise ValueError('Mana consumption requires immutable result fields')
    values=dict(raw)
    if len(values)!=len(raw): raise ValueError('Mana consumption duplicated result fields')
    row=mana_consumption_from_dict(values)
    if (event.source_id,event.player_id,event.action,event.amount,event.target_id)!=(row.source_id,row.player_id,row.action,row.actual,None):
        raise ValueError('Mana consumption envelope differs from its original debit')
    if event.kind=='mana_consumed' and not row.actual:
        raise ValueError('Zero consumption cannot publish a positive mana fact')
    return row


def consume_mana(r,effect):
    from .zones import source_exists
    from .spell_casts import active_cast
    effect.__post_init__(); source_exists(r,effect.source_id)
    if effect.on_result is not None: r.registry.behavior(effect.on_result)
    player=r.player(effect.player_id); source=r.state.entities.get(effect.source_id)
    casts=() if source is None else tuple(c for p in (1,2) if (c:=active_cast(r.state,source.id,p)) is not None and c.payload_started)
    cast=max(casts,key=lambda c:c.id) if casts else None
    actual=player.mana if effect.amount is None else min(player.mana,effect.amount)
    projected=project_mana_spend(player,actual)
    row=ManaConsumptionRecord(len(r.state.mana_consumption_history)+1,player.id,r.state.turn,r.state.action_number,
        effect.amount,actual,player.mana,projected.mana,player.max_mana,player.overload_locked,
        player.temporary_mana,projected.temporary_mana,player.mana_spent,projected.mana_spent,effect.source_id,
        cast.card_id if cast is not None else source.card_id if source is not None else None,
        CardType.SPELL if cast is not None else source.kind if source is not None else None,
        cast.player_id if cast is not None else source.controller if source is not None else None,
        cast.id if cast is not None else None)
    spend_mana(player,actual)
    r.state.mana_consumption_history.append(row)
    from .spell_mana_freeze import note_payment as note_spell_mana_freeze, publish_progress as publish_freeze_progress
    note_spell_mana_freeze(r.state,row,'consume')
    from .held_mana import note_consumption
    note_consumption(r.state,row)
    event=r.emit('mana_consumption_resolved',source_id=effect.source_id,player_id=player.id,amount=actual,result=row.payload())
    if actual: r.emit('mana_consumed',source_id=effect.source_id,player_id=player.id,amount=actual,result=row.payload())
    r.emit('mana_changed',source_id=effect.source_id,player_id=player.id,amount=-actual,
        operation='SpendMana',available=player.mana,maximum=player.max_mana,temporary=player.temporary_mana,
        locked=player.overload_locked,owed=player.overload_owed)
    publish_freeze_progress(r,row,'consume')
    if effect.source_growth is not None:
        from .sacrifice import BuffCapturedMinion
        return [BuffCapturedMinion(effect.source_growth,actual,actual,effect.source_id)] if actual else []
    return [] if effect.on_result is None else [r.call(effect.on_result,effect.source_id,player.id,event=event)]


def validate_mana_consumption_history(state,registry=None):
    if type(state.mana_consumption_history) is not list:
        raise ValueError('Mana consumption requires its complete original history')
    last_turn=last_action=0
    for index,row in enumerate(state.mana_consumption_history,1):
        if type(row) is not ManaConsumptionRecord: raise ValueError('Mana consumption requires immutable original facts')
        row.__post_init__()
        if row.id!=index or not last_turn<=row.turn<=state.turn or not last_action<=row.action<=state.action_number:
            raise ValueError('Mana consumption lost original allocation/chronology')
        if row.source_id is not None:
            if row.source_id not in state.entities or row.source_id>=state.next_entity_id:
                raise ValueError('Mana consumption borrowed an unknown/future source')
            if registry is not None and registry.card(row.source_card_id).kind!=row.source_kind:
                raise ValueError('Mana consumption changed its original source type')
        if row.cast_id is not None:
            if row.cast_id>len(state.cast_history): raise ValueError('Mana consumption borrowed a future cast')
            cast=state.cast_history[row.cast_id-1]
            if (cast.source_id,cast.card_id,cast.player_id)!=(row.source_id,row.source_card_id,row.source_player_id) or not cast.payload_started:
                raise ValueError('Mana consumption changed its original physical cast attribution')
            if cast.turn>row.turn or cast.action>row.action:
                raise ValueError('Mana consumption borrowed a later physical cast')
        last_turn,last_action=row.turn,row.action


def validate_mana_consumption_events(state,events):
    resolved=[]
    for index,event in enumerate(events):
        row=mana_consumption_result(event)
        if row is None: continue
        if row.id>len(state.mana_consumption_history) or state.mana_consumption_history[row.id-1]!=row:
            raise ValueError('Mana event differs from its complete retained consumption fact')
        if event.kind=='mana_consumed':
            if not index or events[index-1].kind!='mana_consumption_resolved' or mana_consumption_result(events[index-1])!=row:
                raise ValueError('Positive mana fact lost its immediate complete result')
            continue
        resolved.append(row)
        if row.actual and (index+1>=len(events) or events[index+1].kind!='mana_consumed' or mana_consumption_result(events[index+1])!=row):
            raise ValueError('Positive mana result lost its immediate consumption fact')
        next_index=index+1+bool(row.actual)
        if next_index>=len(events): raise ValueError('Mana result lost its account change event')
        changed=events[next_index]; data=dict(changed.data)
        if (changed.kind,changed.action,changed.player_id,changed.source_id,changed.amount,changed.target_id)!=('mana_changed',row.action,row.player_id,row.source_id,-row.actual,None):
            raise ValueError('Mana result differs from its account change envelope')
        if (set(data)!={'operation','available','maximum','temporary','locked','owed'}
                or len(changed.data)!=len(data) or type(data['owed']) is not int or data['owed']<0
                or any(type(data[key]) is not int for key in ('available','maximum','temporary','locked'))
                or (data['operation'],data['available'],data['maximum'],data['temporary'],data['locked'])!=
                    ('SpendMana',row.mana_after,row.max_mana,row.temporary_after,row.overload_locked)):
            raise ValueError('Mana change differs from its original account endpoints')
    if tuple(resolved)!=tuple(state.mana_consumption_history):
        raise ValueError('Mana event history lost/duplicated an original consumption')


def begin_mana_turn(player):
    player.max_mana = min(player.mana_cap, player.max_mana + 1)
    player.mana_spent = player.temporary_mana = 0
    player.overload_locked, player.overload_owed = player.overload_owed, 0
    refresh_mana(player)



def change_crystals(player, new_max, filled):
    change = new_max - player.max_mana
    if change >= 0:
        player.max_mana = new_max
        if not filled:
            player.mana_spent += change
    else:
        # Remove empty crystals first, then clamp permanent available mana.
        player.max_mana = new_max
        player.mana_spent = max(0, player.mana_spent + change)
    refresh_mana(player)


def mana_effect(r, effect):
    player = r.player(effect.player_id)
    before = player.mana
    owed_before = player.overload_owed
    if isinstance(effect, GainTemporaryMana):
        # The cap constrains crystal growth, not this independent account.
        player.temporary_mana += effect.amount
    elif isinstance(effect, RefreshMana):
        player.mana_spent = max(0, player.mana_spent - effect.amount)
    elif isinstance(effect, ChangeManaCrystals):
        change_crystals(player, max(0, min(player.mana_cap, player.max_mana + effect.amount)), effect.filled)
    elif isinstance(effect, DestroyAllManaCrystals):
        change_crystals(player, 0, False)
    elif isinstance(effect, SetManaCap):
        player.mana_cap = effect.amount
        change_crystals(player, min(player.max_mana, player.mana_cap), False)
    elif isinstance(effect, Overload):
        player.overload_owed += effect.amount
    elif isinstance(effect, UnlockOverload):
        player.overload_locked = 0
        if effect.clear_pending:
            player.overload_owed = 0
    else:
        raise ResolutionError('Unsupported mana operation')
    refresh_mana(player)
    mana_event = r.emit('mana_changed', player_id=player.id, amount=player.mana - before,
           operation=type(effect).__name__, available=player.mana, maximum=player.max_mana,
           temporary=player.temporary_mana, locked=player.overload_locked, owed=player.overload_owed)
    if isinstance(effect, Overload) and player.overload_owed > owed_before:
        r.emit('overload_added', _overload_commit=mana_event, player_id=player.id, amount=player.overload_owed - owed_before,
               pending_before=owed_before, pending_after=player.overload_owed)


def resource_effect(r, effect):
    player = r.player(effect.player_id)
    if isinstance(effect, SpendResource) and effect.requires_board_space:
        effect.__post_init__()
        from .summon_quantities import validate_cause
        validate_cause(r.state, r.registry, effect.on_success[0].cause)
        from .summon_quantities import SummonByCard
        if type(effect.on_success[0]) is SummonByCard:
            request = effect.on_success[0]
            source = r.registry.card(request.cause.source.card_id)
            target = r.registry.card(request.materials[0].card_id)
            if source.interactable is not None or target.kind != CardType.MINION or target.interactable is not None:
                raise ResolutionError('Fixed corpse gate requires ordinary source and target minions')
        if len(player.board) >= r.rules.max_board:
            return ()
    if isinstance(effect, GainResource):
        from .corpse_gains import gain_amount
        amount = gain_amount(r.state, r.registry, player.id, effect.amount)
        player.resources[effect.resource] += amount
        r.emit('resource_gained', player_id=player.id, amount=amount, resource=effect.resource.value)
        return
    if player.resources[effect.resource] < effect.amount:
        if effect.required:
            raise ResolutionError(f'Insufficient {effect.resource} at resource payment')
        r.emit('resource_payment_skipped', player_id=player.id, resource=effect.resource.value, required=effect.amount)
        return effect.on_failure
    before = player.resources[effect.resource]
    player.resources[effect.resource] -= effect.amount
    row = commit_corpse_spend(r.state, player.id, before, effect.amount, 'fixed')
    from .assemble_corpse_prefixes import bind_success as bind_paid_battlecry
    success=bind_paid_battlecry(r.state,r.registry,effect,row)
    r.emit('resource_spent', player_id=player.id, amount=effect.amount,
           resource=effect.resource.value, _corpse_spend_record=row)
    return success


def prepare_corpse_spend(state, player_id, before, amount, origin, source_id=None, operation_id=None):
    """Pure operand also used by the original shared payment projection."""
    source = None if source_id is None else state.entities.get(source_id)
    if source_id is not None and source is None:
        raise ValueError('Corpse debit has an unknown physical source')
    return CorpseSpendRecord(len(state.corpse_spend_history) + 1, player_id,
        state.turn, state.action_number, origin, amount, before, before - amount,
        source_id, source.card_id if source is not None else None, operation_id)


def commit_corpse_spend(state, player_id, before, amount, origin, source_id=None, operation_id=None):
    """Bookkeeping after the existing debit; never debit or execute reactions."""
    row = prepare_corpse_spend(state, player_id, before, amount, origin, source_id, operation_id)
    if state.players[player_id].resources[Resource.CORPSES] != row.balance_after:
        raise ValueError('Corpse debit record differs from the original numeric commit')
    state.corpse_spend_history.append(row)
    return row


def corpse_spend_data(state, identity):
    if identity is None:
        return {}
    _int(identity, 'corpse debit event identity', 1)
    if identity > len(state.corpse_spend_history):
        raise ValueError('Corpse debit event borrowed a future record')
    row = state.corpse_spend_history[identity - 1]
    row.__post_init__()
    return {'corpse_spend': row.payload()}


def validate_corpse_spend_history(state, registry=None):
    if type(state.corpse_spend_history) is not list:
        raise ValueError('Corpse spending requires its complete original list')
    last_turn = last_action = 0
    for index, row in enumerate(state.corpse_spend_history, 1):
        if type(row) is not CorpseSpendRecord:
            raise ValueError('Corpse spending requires immutable original debit facts')
        row.__post_init__()
        if (row.id != index or not last_turn <= row.turn <= state.turn or
                not last_action <= row.action <= state.action_number):
            raise ValueError('Corpse spending changed its complete original chronology')
        if row.source_id is not None:
            if row.source_id not in state.entities or row.source_id >= state.next_entity_id:
                raise ValueError('Corpse spending borrowed an unknown/future physical source')
            if registry is not None:
                registry.card(row.source_card_id)
        if row.operation_id is not None and row.operation_id >= state.next_resource_operation_id:
            raise ValueError('Corpse spending borrowed a future capped operation')
        last_turn, last_action = row.turn, row.action


def corpse_spends(state, player_id, *, turn=None, before_id=None):
    """Host-only pure original debit rows; price queries never read event logs."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Corpse spending requires an actual player')
    if turn is not None:
        _int(turn, 'corpse query turn', 1)
    if before_id is not None:
        _int(before_id, 'corpse query original bound', 1)
    validate_corpse_spend_history(state)
    return tuple(row for row in state.corpse_spend_history if row.player_id == player_id and
                 (turn is None or row.turn == turn) and (before_id is None or row.id < before_id))


def spent_corpses(state, player_id, *, turn=None, before_id=None):
    """Actual resource units, including all original debit producers."""
    return sum(row.amount for row in corpse_spends(state, player_id, turn=turn, before_id=before_id))


def corpse_spend_from_event(event):
    data = dict(event.data)
    actual = event.kind == 'corpses_spent' or event.kind == 'resource_spent' and data.get('resource') == Resource.CORPSES.value
    if actual != ('corpse_spend' in data):
        raise ValueError('Actual corpse debit lost or invented its complete original envelope')
    if not actual:
        return None
    payload = data['corpse_spend']
    if (type(payload) is not tuple or any(type(pair) is not tuple or len(pair) != 2 or
            type(pair[0]) is not str for pair in payload)):
        raise ValueError('Corpse envelope requires immutable declared fields')
    values = dict(payload)
    if len(values) != len(payload) or set(values) != {field.name for field in fields(CorpseSpendRecord)}:
        raise ValueError('Corpse envelope lost its exact original fields')
    row = CorpseSpendRecord(**values)
    kind = 'corpses_spent' if row.origin == 'payment' else 'resource_spent'
    if (event.kind, event.player_id, event.source_id, event.action, event.amount) != (
            kind, row.player_id, row.source_id, row.action, row.amount):
        raise ValueError('Corpse envelope changed its original event debit')
    if row.origin == 'capped':
        from .resource_operations import resource_result
        result = resource_result(event)
        if result is None or (row.operation_id, row.player_id, row.turn, row.action, row.amount,
                row.balance_before, row.balance_after, row.source_id, row.source_card_id) != (
                result.operation_id, result.player_id, result.turn, result.action, result.actual_amount,
                result.balance_before, result.balance_after, result.source_id, result.source_card_id):
            raise ValueError('Corpse envelope differs from its original capped result')
    elif 'result' in data:
        raise ValueError('Non-capped corpse debit borrowed a capped result')
    return row


def validate_corpse_boundary(game):
    """Bind the full persistent inventory to effective original committed events."""
    validate_corpse_spend_history(game._state, game.registry)
    from .hero_health_history import effective_events
    rows = tuple(row for event in effective_events(game._events)
                 if (row := corpse_spend_from_event(event)) is not None)
    if rows != tuple(game._state.corpse_spend_history):
        raise ValueError('Corpse spending lost its complete original committed inventory')
