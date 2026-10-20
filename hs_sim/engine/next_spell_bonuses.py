"""One native pending spell owns both its price reduction and scoped damage.

Paid hand admission reserves the whole program before commitment reactions.
Automatic casts reserve it only after obtaining a legal target, before start
reactions. The existing payment projection uses the same pure paid commit.
"""
from dataclasses import asdict,replace
import json

from .model import CardType,CostModifier,CostSpec,PlayerEffect

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


def install_origin(state,spec,player_id,source_id):
    rows=[b for b in state.battlecry_history if b.source_id==source_id and b.player_id==player_id and
        b.payload.card_id==spec.card_id and b.payload_started and not b.completed and not b.interrupted and b.failure is None]
    if len(rows)!=1:raise ValueError('Native spell bonus requires its actual original Battlecry')
    return rows[0].id


def note_install(r,instance,battlecry_id):
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
    if not(any(e.kind in(INSTALLED,CLAIMED,REMOVED)for e in game._events)or
           any(p.next_spell_bonus_effects for p in state.play_history)or any(c.next_spell_bonus_effects for c in state.cast_history)or
           any(registry.player_effect(e.spec_id).kind==KIND for p in state.players.values()for e in p.player_effects)):
        return
    from .hero_health_history import effective_events
    events=effective_events(game._events);installed={};claims={};removed={}
    for event in events:
        d=dict(event.data)
        if event.kind==INSTALLED:
            if set(d)!={'battlecry_id','effects_json'}:raise ValueError('Native spell bonus installation lost its complete receipt')
            raw=json.loads(d['effects_json'])
            from .serialization import player_effect_from_dict
            rows=tuple(player_effect_from_dict(x)for x in raw);validate_material(rows,state.turn)
            if len(rows)!=1:raise ValueError('Native spell bonus installation requires one original instance')
            e=rows[0];spec=registry.player_effect(e.spec_id)
            from .battlecries import battlecry_record
            b=battlecry_record(state,d['battlecry_id'])
            if(spec.kind!=KIND or e.source_card_id!=spec.card_id or e.source_id!=event.source_id or
                    (b.source_id,b.player_id,b.payload.card_id)!=(event.source_id,event.player_id,spec.card_id)or
                    not b.payload_started or b.failure is not None or e.id in installed):
                raise ValueError('Native spell bonus installation borrowed another original source')
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
