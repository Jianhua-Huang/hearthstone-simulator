"""Original-window voluntary hero attack facts, separate from opportunity counters."""
from dataclasses import fields, is_dataclass, replace
from .model import (CardType, GameState, HeroAttackIdentity, HeroAttackDeclarationFact,
    HeroAttackDeliveryReceipt, HeroAttackReference, HeroAttackCombatFact,
    HeroAttackTerminalFact, HeroAttackRecord, HeroAttackQuery)
from .owner_turns import current_owner_turn
from .errors import ResolutionError


def record(state, record_id):
    if type(record_id) is not int or record_id < 1:
        raise ValueError('Invalid hero attack record ID')
    value = next((a for a in state.hero_attack_history if a.declaration.identity.record_id == record_id), None)
    if value is None: raise ValueError('Unknown original hero attack record')
    return value


def update(state, old, **values):
    new = replace(old, **values); new.__post_init__()
    state.hero_attack_history[state.hero_attack_history.index(old)] = new
    return new


def declare(r, window):
    source = r.state.entities[window.source_id]
    if source.kind != CardType.HERO: return
    owner = current_owner_turn(r.state)
    if (window.forced or window.combat_relation != 'opponent' or window.player_id != owner.player_id
            or source.id != r.state.players[window.player_id].hero_id):
        raise ResolutionError('Hero declaration requires the real active voluntary hero window')
    identity = HeroAttackIdentity(window.id, window.id, window.player_id, source.id,
        source.card_id, source.zone_epoch, window.target_id, r.state.turn, owner.id, r.root_action_number)
    r.state.hero_attack_history.append(HeroAttackRecord(HeroAttackDeclarationFact(
        identity, r.state.action_number, len(r.game._events))))


def delivery(r, window):
    if r.state.entities[window.source_id].kind != CardType.HERO: return None
    old = record(r.state, window.id); identity = old.declaration.identity
    if (old.delivery is not None or old.terminal is not None or
            (window.player_id, window.source_id, window.forced, window.combat_relation) !=
            (identity.player_id, identity.physical_hero_id, False, 'opponent')):
        raise ResolutionError('Hero attack delivery lost its unique original window')
    receipt = HeroAttackDeliveryReceipt(identity, r.state.action_number, len(r.game._events), window.target_id)
    update(r.state, old, delivery=receipt)
    return HeroAttackReference(identity, receipt)


def require_link(state, attacker_id, defender_id, forced, relation, link, *, accepted=False):
    attacker = state.entities.get(attacker_id)
    if link is None:
        if attacker is not None and attacker.kind == CardType.HERO:
            raise ResolutionError('Bare hero combat lacks its original voluntary delivery')
        return None
    if type(link) is not HeroAttackReference:
        raise ResolutionError('Expected exact hero attack reference')
    link.__post_init__()
    old = record(state, link.identity.record_id)
    if (attacker is None or attacker.kind != CardType.HERO or
            old.declaration.identity != link.identity or old.delivery != link.delivery or
            old.terminal is not None or old.combat is not None and not accepted or
            (attacker_id, defender_id, forced, relation) !=
            (link.identity.physical_hero_id, link.delivery.target_id, False, 'opponent')):
        raise ResolutionError('Foreign, duplicated or unsupported hero combat reference')
    return old


def cancel(r, effect, reason):
    old = require_link(r.state,effect.attacker_id,effect.defender_id,effect.forced,
                       effect.combat_relation,effect.hero_attack)
    if old is not None:
        update(r.state,old,terminal=HeroAttackTerminalFact(old.declaration.identity,r.state.action_number,
            len(r.game._events),'cancelled',reason,'delivery_pending'))


def accept(r, combat):
    if combat is None: return
    old = require_link(r.state,combat.attacker_id,combat.defender_id,False,combat.combat_relation,combat.hero_attack)
    if old is None: return
    a,d = (r.state.entities[i] for i in (combat.attacker_id,combat.defender_id))
    fact = HeroAttackCombatFact(old.declaration.identity,r.state.action_number,len(r.game._events),
        old.delivery,a.controller,a.card_id,d.id,d.controller,d.card_id,combat.weapon_id)
    new=update(r.state,old,combat=fact)
    from .weapon_wear import accept as accept_wear
    accept_wear(r,new)


def complete(r, combat):
    old = require_link(r.state,combat.attacker_id,combat.defender_id,False,combat.combat_relation,
                       combat.hero_attack,accepted=True)
    if old is None: return
    if old.combat is None or old.combat.weapon_id != combat.weapon_id:
        raise ResolutionError('Hero intrinsic finish has no original accepted exchange')
    update(r.state,old,terminal=HeroAttackTerminalFact(old.declaration.identity,r.state.action_number,
        len(r.game._events),'completed','intrinsic_finish','combat_accepted'))


def validate_history(state, registry=None, event_limit=None):
    if type(state.hero_attack_history) is not list: raise ValueError('Invalid hero attack history')
    ids=[]
    for value in state.hero_attack_history:
        if type(value) is not HeroAttackRecord: raise ValueError('Expected exact hero attack record')
        value.__post_init__(); identity=value.declaration.identity; ids.append(identity.record_id)
        if identity.window_id >= state.next_window_id or identity.root_action_number > state.action_number:
            raise ValueError('Future original hero attack window/action')
        if identity.physical_hero_id not in state.entities or identity.declared_target_id not in state.entities:
            raise ValueError('Unknown original hero attack physical participant')
        if (state.entities[identity.physical_hero_id].kind != CardType.HERO or
                state.entities[identity.physical_hero_id].owner != identity.player_id or
                identity.zone_epoch > state.entities[identity.physical_hero_id].zone_epoch):
            raise ValueError('Invalid original hero physical identity/epoch')
        if not 0 < identity.owner_turn_id <= len(state.owner_turn_history):
            raise ValueError('Unknown original hero attack owner interval')
        owner=state.owner_turn_history[identity.owner_turn_id-1]
        if (owner.id,owner.player_id,owner.turn) != (identity.owner_turn_id,identity.player_id,identity.turn):
            raise ValueError('Hero attack original owner identity mismatch')
        if registry is not None and registry.card(identity.hero_card_id).kind != CardType.HERO:
            raise ValueError('Original hero face is not a hero definition')
        moments=[value.declaration,*([value.delivery] if value.delivery else []),
                 *([value.combat] if value.combat else []),*([value.terminal] if value.terminal else [])]
        if any(m.action_number > state.action_number or m.action_number < identity.root_action_number or
               event_limit is not None and m.event_cursor > event_limit for m in moments):
            raise ValueError('Hero attack phase action/cursor is from the future')
        if any(a.action_number>b.action_number or a.event_cursor>b.event_cursor for a,b in zip(moments,moments[1:])):
            raise ValueError('Hero attack phase chronology regressed')
        if value.delivery and value.delivery.target_id not in state.entities:
            raise ValueError('Unknown actual hero attack delivery target')
        if value.combat:
            c=value.combat
            if c.defender_id != value.delivery.target_id or c.attacker_controller == c.defender_controller:
                raise ValueError('Hero combat differs from original opponent delivery')
            if registry is not None and (registry.card(c.attacker_card_id).kind != CardType.HERO or
                    registry.card(c.defender_card_id).kind not in (CardType.HERO,CardType.MINION)):
                raise ValueError('Invalid original accepted combat faces')
            if c.weapon_id is not None and (c.weapon_id not in state.entities or state.entities[c.weapon_id].kind != CardType.WEAPON):
                raise ValueError('Unknown original accepted hero weapon')
    if ids != sorted(set(ids)): raise ValueError('Hero attack record IDs must be unique and ordered')
    from .weapon_wear import validate_history as validate_wear
    validate_wear(state,registry,event_limit)


def validate_tails(state, work):
    from .interrupts import ResolveAttack
    from .resolver import CombatDamage
    from .effects import DamageBatch
    tails={}
    for item in work:
        if type(item) is ResolveAttack:
            window=next((w for w in state.action_windows if w.id==item.window_id),None)
            if window is not None and state.entities[window.source_id].kind==CardType.HERO:
                value=record(state,window.id); i=value.declaration.identity
                if value.delivery is not None or value.terminal is not None or (window.player_id,window.source_id,window.forced,window.combat_relation)!=(i.player_id,i.physical_hero_id,False,'opponent'):
                    raise ValueError('Hero declaration has a foreign original window tail')
                tails.setdefault(i.record_id,[]).append('declared')
        elif type(item) is CombatDamage or type(item) is DamageBatch and item.combat is not None:
            combat=item if type(item) is CombatDamage else item.combat
            value=require_link(state,combat.attacker_id,combat.defender_id,getattr(combat,'forced',False),
                               combat.combat_relation,combat.hero_attack)
            if value is not None: tails.setdefault(value.declaration.identity.record_id,[]).append('delivery_pending')
    for value in state.hero_attack_history:
        ident=value.declaration.identity
        expected=[] if value.terminal else ['declared' if value.delivery is None else 'delivery_pending']
        if value.combat is not None and value.terminal is None or tails.get(ident.record_id,[])!=expected:
            raise ValueError('Hero attack lost its unique original control tail')
        windows=[w for w in state.action_windows if w.id==ident.window_id]
        if bool(windows)!=(value.delivery is None and value.terminal is None):
            raise ValueError('Hero attack original window lifecycle mismatch')


def validate_boundary(game):
    validate_history(game._state,game.registry,len(game._events))
    frame=game._frame
    work=() if frame is None else (*frame.prefix,*frame.continuation)
    validate_tails(game._state,work)
    if frame is not None:
        from .interrupts import ResolveAttack
        from .resolver import CombatDamage
        from .effects import DamageBatch
        from .registry import RuleContext
        from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
        def walk(value, state, *, control_tail=False):
            if type(value) is GameState:
                # Captured event contexts can be inside the synchronous health
                # handler. They prove facts, not the live stable control queue.
                validate_history(value,game.registry,len(game._events))
                return
            if type(value) is PaidHandChoiceBoundaryProof:
                # The original request boundary owns its original state/work.
                # Its control tails are neither live tails nor offered effects.
                validate_history(value.state,game.registry,value.event.sequence)
                validate_tails(value.state,value.work)
                for item in value.work:walk(item,value.state,control_tail=True)
                return
            if type(value) is RuleContext:
                state=value.state
            if type(value) is HeroAttackReference:
                old=record(state,value.identity.record_id)
                if old.declaration.identity!=value.identity or old.delivery!=value.delivery:
                    raise ValueError('Foreign captured hero attack reference')
            if not control_tail and (type(value) is ResolveAttack and any(
                    h.declaration.identity.window_id==value.window_id for h in state.hero_attack_history) or
                    type(value) is CombatDamage and (value.hero_attack is not None or
                    state.entities.get(value.attacker_id) is not None and state.entities[value.attacker_id].kind==CardType.HERO) or
                    type(value) is DamageBatch and value.combat is not None and
                    (value.combat.hero_attack is not None or state.entities.get(value.combat.attacker_id) is not None and
                     state.entities[value.combat.attacker_id].kind==CardType.HERO)):
                raise ValueError('Hero attack control tail cannot be offered or nested')
            if is_dataclass(value):
                for field in fields(value):walk(getattr(value,field.name),state)
            elif type(value) in (tuple,list):
                for item in value:walk(item,state)
        for item in work:walk(item,game._state,control_tail=True)
        for field in fields(frame):
            if field.name not in ('prefix','continuation'):walk(getattr(frame,field.name),game._state)


def interrupt(r, queue):
    validate_tails(r.state,tuple(queue))
    for value in tuple(r.state.hero_attack_history):
        if value.terminal is None:
            update(r.state,value,terminal=HeroAttackTerminalFact(value.declaration.identity,r.state.action_number,
                len(r.game._events),'interrupted','game_terminal','declared' if value.delivery is None else 'delivery_pending'))


def hero_attacks(state, player_id, query):
    if type(state) is not GameState or type(query) is not HeroAttackQuery or type(player_id) is not int or player_id not in (1,2):
        raise ValueError('Hero attack history requires typed query/state/player')
    query.__post_init__(); validate_history(state)
    interval=current_owner_turn(state) if state.owner_turn_history else None
    if query.window!='match' and (interval is None or query.window=='owner_turn' and interval.player_id!=player_id):return ()
    return tuple(v for v in state.hero_attack_history if v.declaration.identity.player_id==player_id and
        (query.window=='match' or v.declaration.identity.owner_turn_id==interval.id) and
        (query.phase=='declared' or query.phase=='combat_accepted' and v.combat is not None or
         v.terminal is not None and v.terminal.outcome==query.phase))


def hero_attack_count(state, player_id, query=HeroAttackQuery()):
    return len(hero_attacks(state,player_id,query))


def record_from_dict(value):
    from .serialization import _row
    def build(kind,row):
        row=_row(row,kind)
        if 'identity' in row:row['identity']=HeroAttackIdentity(**_row(row['identity'],HeroAttackIdentity))
        if 'delivery' in row:row['delivery']=build(HeroAttackDeliveryReceipt,row['delivery'])
        return kind(**row)
    row=_row(value,HeroAttackRecord)
    for name,kind in (('declaration',HeroAttackDeclarationFact),('delivery',HeroAttackDeliveryReceipt),
                      ('combat',HeroAttackCombatFact),('terminal',HeroAttackTerminalFact)):
        if row[name] is not None:row[name]=build(kind,row[name])
    from .weapon_wear import from_dict as wear_from_dict
    from .model import WeaponWearInputs, WeaponWearReceipt
    for key,cls in (('wear_acceptance',WeaponWearInputs),('wear_receipt',WeaponWearReceipt)):
        if row[key] is not None:row[key]=wear_from_dict(cls,row[key])
    return HeroAttackRecord(**row)
