"""One native pending spell owns both its price reduction and scoped damage.

Paid hand admission reserves the whole program before commitment reactions.
Automatic casts reserve it only after obtaining a legal target, before start
reactions. The existing payment projection uses the same pure paid commit.
"""
from dataclasses import asdict,replace
import json

from .model import CardType,CostModifier,CostSpec,Event,PlayerEffect,Zone

KIND='next_spell_bonus'
INSTALLED='native_spell_bonus_installed'
CLAIMED='native_spell_bonus_claimed'
REMOVED='native_spell_bonus_removed'


def material_json(rows):
    return json.dumps([asdict(e)for e in rows],ensure_ascii=False,sort_keys=True,separators=(',',':'))


def validate_material(rows,turn):
    if rows==():return
    if type(rows)is not tuple or any(type(e)is not PlayerEffect for e in rows):
        raise ValueError('Next-spell bonus requires complete immutable original player effects')
    for e in rows:
        e.__post_init__()
        if e.created_turn>turn or e.remaining_turns is not None or e.cost_modifier_id is None:
            raise ValueError('Next-spell bonus lost its original persistent price binding')
        if any(getattr(e,k)is not None for k in('source_allocation','source_player_id','aura_duration_cast_id',
                'spell_aura_id','spell_aura_card_id','spell_aura_player_id','investigation','issued_spell_set'))or e.adaptations or e.aura_duration_grants:
            raise ValueError('Native spell bonus cannot borrow other player-effect material')
    if any(a.id>=b.id or a.entered_order>=b.entered_order for a,b in zip(rows,rows[1:])):
        raise ValueError('Next-spell bonus requires original unique acquisition order')


def expected_modifier(registry,instance):
    spec=registry.player_effect(instance.spec_id)
    if spec.kind!=KIND:raise ValueError('Expected the native paired spell bonus')
    return CostModifier(instance.cost_modifier_id,CostSpec(delta=-spec.next_spell_cost_reduction,
        card_types=(CardType.SPELL,)),instance.source_id,player_effect_id=instance.id)


def validate_binding(state,registry,player_id,instance):
    validate_material((instance,),state.turn)
    spec=registry.player_effect(instance.spec_id)
    if (spec.kind!=KIND or instance.source_card_id!=spec.card_id or instance.source_id not in state.entities or
            instance.id>=state.next_attachment_id or instance.cost_modifier_id>=state.next_attachment_id or instance.entered_order>=state.next_order):
        raise ValueError('Native spell bonus changed its original allocated source')
    rows=[m for m in state.players[player_id].cost_modifiers if m.id==instance.cost_modifier_id]
    if rows!=[expected_modifier(registry,instance)]:raise ValueError('Native spell bonus lost its exact ordinary price contribution')


def modifier_owner(state,registry,player_id,modifier):
    rows=[e for e in state.players[player_id].player_effects if e.id==modifier.player_effect_id]
    if not rows or registry.player_effect(rows[0].spec_id).kind!=KIND:return False
    if len(rows)!=1 or modifier!=expected_modifier(registry,rows[0]):raise ValueError('Native price contribution borrowed another program')
    return True


def ability_event_json(event):
    from .serialization import event_to_dict
    return json.dumps(event_to_dict(event),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def validate_ability_origin(state,registry,events,spec,player_id,source_id,event,source,*,installation=None):
    """Bind one native program to its exact already accepted skill, not its live face."""
    from .allocation_facts import SourceAllocationFact,validate_allocation
    from .effects import _integer
    from .hero_health_history import effective_events
    if type(event)is not Event or type(source)is not SourceAllocationFact:
        raise ValueError('Native spell bonus requires typed original ability material')
    validate_allocation(state,registry,source)
    _integer(event.sequence,'native ability event sequence',1)
    _integer(event.action,'native ability action',0)
    data=dict(event.data)
    if (spec.kind!=KIND or event.kind!='minion_ability_started' or event.amount!=0 or
            set(data)!={'ability_id','ability_card_id'} or len(event.data)!=2 or
            (event.source_id,event.player_id)!=(source_id,player_id) or
            (source.entity_id,source.card_id,source.controller,source.kind,source.zone)!=
            (source_id,spec.card_id,player_id,CardType.MINION,Zone.BOARD)):
        raise ValueError('Native spell bonus changed its original skill source')
    native=registry.card(source.card_id)
    if not any((a.id,a.card_id,a.behavior_id)==(data['ability_id'],data['ability_card_id'],spec.id)
            for a in native.activated_abilities):
        raise ValueError('Native spell bonus borrowed another skill or program')
    original=effective_events(events)
    if [e for e in original if e.sequence==event.sequence]!=[event]:
        raise ValueError('Native spell bonus lost its actual original ability event')
    end=installation.sequence if installation is not None else max((e.sequence for e in events),default=0)+1
    action=installation.action if installation is not None else state.action_number
    # Resolving a real choice is a later command in the same accepted ability.
    # The original completion below, rather than command equality, closes it.
    if event.sequence>=end or event.action>action:
        raise ValueError('Native spell bonus installation precedes its original ability')
    if any(e.kind=='minion_ability_used' and event.sequence<e.sequence<end and
            (e.source_id,e.player_id,dict(e.data).get('ability_id'),dict(e.data).get('ability_card_id'))==
            (source_id,player_id,data['ability_id'],data['ability_card_id'])for e in original):
        raise ValueError('Native spell bonus cannot install after its original ability completed')


def install_origin(r,spec,player_id,source_id,ability_event=None,ability_source=None):
    if ability_event is not None:
        validate_ability_origin(r.state,r.registry,r.game._events,spec,player_id,source_id,ability_event,ability_source)
        encoded=ability_event_json(ability_event)
        from .hero_health_history import effective_events
        if any(e.kind==INSTALLED and dict(e.data).get('ability_event_json')==encoded
                for e in effective_events(r.game._events)):
            raise ValueError('Native spell bonus repeated the same original skill installation')
        return ability_event,ability_source
    rows=[b for b in r.state.battlecry_history if b.source_id==source_id and b.player_id==player_id and
        b.payload.card_id==spec.card_id and b.payload_started and not b.completed and not b.interrupted and b.failure is None]
    if len(rows)!=1:raise ValueError('Native spell bonus requires its actual original Battlecry')
    return rows[0].id


def note_install(r,instance,battlecry_id):
    if type(battlecry_id)is tuple:
        event,source=battlecry_id
        r.emit(INSTALLED,source_id=instance.source_id,player_id=event.player_id,
            ability_event_json=ability_event_json(event),
            ability_source_json=json.dumps(asdict(source),ensure_ascii=False,sort_keys=True,separators=(',',':')),
            effects_json=material_json((instance,)),_capture=False)
        return
    r.emit(INSTALLED,source_id=instance.source_id,player_id=r.state.battlecry_history[battlecry_id-1].player_id,
        battlecry_id=battlecry_id,effects_json=material_json((instance,)),_capture=False)


def note_removal(r,player_id,instance):
    r.emit(REMOVED,source_id=instance.source_id,player_id=player_id,effects_json=material_json((instance,)),_capture=False)


def pending(state,registry,player_id):
    rows=tuple(e for e in state.players[player_id].player_effects if registry.player_effect(e.spec_id).kind==KIND)
    for e in rows:validate_binding(state,registry,player_id,e)
    return rows


def capture_play(state,registry,source):
    return pending(state,registry,source.controller)if source.kind==CardType.SPELL else ()


def consume_state(state,player_id,rows):
    """One atomic write, shared by actual admission and pure payment replay."""
    if not rows:return
    validate_material(rows,state.turn);player=state.players[player_id]
    for e in rows:
        if [x for x in player.player_effects if x.id==e.id]!=[e]:raise ValueError('Native spell bonus no longer matches its reserved original instance')
        bound=[m for m in player.cost_modifiers if m.id==e.cost_modifier_id]
        if len(bound)!=1 or bound[0].player_effect_id!=e.id:raise ValueError('Native spell bonus lost its reserved original price contribution')
    ids={e.id for e in rows};mods={e.cost_modifier_id for e in rows}
    player.player_effects[:]=[e for e in player.player_effects if e.id not in ids]
    player.cost_modifiers[:]=[m for m in player.cost_modifiers if m.id not in mods]


def note_claim(r,record,origin):
    rows=record.next_spell_bonus_effects
    if not rows:return
    r.emit(CLAIMED,source_id=record.source_id,player_id=record.player_id,
        origin=origin,identity=record.id,effects_json=material_json(rows),_capture=False)
    from .player_effects import public_effect
    for e in rows:r.emit('player_effect_removed',source_id=e.source_id,player_id=record.player_id,**public_effect(r.registry,e))


def accept_automatic(r,record):
    if record.failure is not None:return record
    rows=pending(r.state,r.registry,record.player_id)
    if not rows:return record
    record=replace(record,next_spell_bonus_effects=rows);consume_state(r.state,record.player_id,rows)
    r.state.cast_history[record.id-1]=record;note_claim(r,record,'cast')
    return record


def validate_game(game):
    state,registry=game._state,game.registry
    from .player_effects import AddPlayerEffect
    from .summon_quantities import walk_work
    queued=tuple(e for e in walk_work(game._frame)if type(e)is AddPlayerEffect and e.ability_event is not None)
    if not(any(e.kind in(INSTALLED,CLAIMED,REMOVED)for e in game._events)or
           any(p.next_spell_bonus_effects for p in state.play_history)or any(c.next_spell_bonus_effects for c in state.cast_history)or
           any(registry.player_effect(e.spec_id).kind==KIND for p in state.players.values()for e in p.player_effects)or queued):
        return
    from .hero_health_history import effective_events
    events=effective_events(game._events);installed={};claims={};removed={};native_origins=set()
    for event in events:
        d=dict(event.data)
        if event.kind==INSTALLED:
            native=set(d)=={'ability_event_json','ability_source_json','effects_json'}
            if not native and set(d)!={'battlecry_id','effects_json'}:raise ValueError('Native spell bonus installation lost its complete receipt')
            raw=json.loads(d['effects_json'])
            from .serialization import player_effect_from_dict
            rows=tuple(player_effect_from_dict(x)for x in raw);validate_material(rows,state.turn)
            if len(rows)!=1:raise ValueError('Native spell bonus installation requires one original instance')
            e=rows[0];spec=registry.player_effect(e.spec_id)
            if(spec.kind!=KIND or e.source_card_id!=spec.card_id or e.source_id!=event.source_id or e.id in installed):
                raise ValueError('Native spell bonus installation borrowed another original source')
            if native:
                from .serialization import event_from_dict
                from .allocation_facts import allocation_from_dict
                origin=event_from_dict(json.loads(d['ability_event_json']))
                source=allocation_from_dict(json.loads(d['ability_source_json']))
                validate_ability_origin(state,registry,events,spec,event.player_id,event.source_id,origin,source,installation=event)
                if origin.sequence in native_origins:raise ValueError('Native spell bonus repeated its original skill receipt')
                native_origins.add(origin.sequence)
            else:
                from .battlecries import battlecry_record
                b=battlecry_record(state,d['battlecry_id'])
                if((b.source_id,b.player_id,b.payload.card_id)!=(event.source_id,event.player_id,spec.card_id)or
                        not b.payload_started or b.failure is not None):
                    raise ValueError('Native spell bonus installation borrowed another original Battlecry')
            installed[e.id]=(event,rows[0])
        elif event.kind==CLAIMED:
            if set(d)!={'origin','identity','effects_json'}or d['origin']not in('play','cast'):
                raise ValueError('Native spell bonus claim lost its exact original root')
            from .effects import _integer
            _integer(d['identity'],'native spell bonus original claim',1)
            key=(d['origin'],d['identity'])
            if key in claims:raise ValueError('Native spell bonus claimed the same original root twice')
            claims[key]=event
        elif event.kind==REMOVED:
            if set(d)!={'effects_json'}:raise ValueError('Native spell bonus removal lost its complete original material')
            from .serialization import player_effect_from_dict
            rows=tuple(player_effect_from_dict(x)for x in json.loads(d['effects_json']));validate_material(rows,state.turn)
            if len(rows)!=1 or rows[0].id in removed:raise ValueError('Native spell bonus removal repeated its original instance')
            removed[rows[0].id]=(event,rows[0])
    for effect in queued:
        effect.__post_init__()
        spec=registry.player_effect(effect.spec_id)
        validate_ability_origin(state,registry,events,spec,effect.player_id,effect.source_id,effect.ability_event,effect.ability_source)
        if effect.ability_event.sequence in native_origins:raise ValueError('Native spell bonus queued its original skill twice')
        native_origins.add(effect.ability_event.sequence)
    expected={};used={};live={e.id for p in state.players.values()for e in p.player_effects}
    def check_material(rows,player_id,turn):
        validate_material(rows,turn)
        for e in rows:
            spec=registry.player_effect(e.spec_id);mark=installed.get(e.id)
            expected_modifier(registry,e)
            if (spec.kind!=KIND or e.source_card_id!=spec.card_id or mark is None or mark[1]!=e or
                    mark[0].player_id!=player_id or e.source_id not in state.entities or
                    e.id>=state.next_attachment_id or e.cost_modifier_id>=state.next_attachment_id or e.entered_order>=state.next_order):
                raise ValueError('Native spell bonus changed its original installed material')
    def claim(record,origin):
        rows=record.next_spell_bonus_effects
        if not rows:return
        check_material(rows,record.player_id,record.turn)
        for e in rows:
            if e.id in live or e.id in used:raise ValueError('Native spell bonus reused an active or already claimed program')
            used[e.id]=(origin,record.id)
        key=(origin,record.id);expected[key]=(record.source_id,record.player_id,record.action,material_json(rows))
    for p in state.players.values():
        for e in p.player_effects:
            if registry.player_effect(e.spec_id).kind==KIND:
                validate_binding(state,registry,p.id,e);check_material((e,),p.id,state.turn)
    for play in state.play_history:claim(play,'play')
    for cast in state.cast_history:
        if cast.origin in('hand','repeat'):
            from .play_history import play_record
            play=play_record(state,cast.play_id)
            wanted=play.next_spell_bonus_effects if cast.iteration==1 else ()
            if cast.next_spell_bonus_effects!=wanted:raise ValueError('CAST lost its original paid spell bonus reservation')
        else:claim(cast,'cast')
    native_live={e.id for p in state.players.values()for e in p.player_effects if registry.player_effect(e.spec_id).kind==KIND}
    for identity,(event,e)in removed.items():
        check_material((e,),event.player_id,state.turn)
        if event.source_id!=e.source_id or identity in native_live or identity in used or installed[identity][0].sequence>=event.sequence:
            raise ValueError('Native spell bonus removal borrowed an active or claimed program')
    if set(installed)!=native_live|set(used)|set(removed):raise ValueError('Native spell bonus lost its whole original pending program')
    if claims.keys()!=expected.keys():raise ValueError('Native spell bonus lost its original claim or record material')
    for key,header in expected.items():
        event=claims[key]
        if(event.source_id,event.player_id,event.action,dict(event.data)['effects_json'])!=header:
            raise ValueError('Native spell bonus claim differs from its committed original root')
        record=state.play_history[key[1]-1]if key[0]=='play'else state.cast_history[key[1]-1]
        if any(installed[e.id][0].sequence>=event.sequence for e in record.next_spell_bonus_effects):
            raise ValueError('Native spell bonus claim precedes its original installation')
