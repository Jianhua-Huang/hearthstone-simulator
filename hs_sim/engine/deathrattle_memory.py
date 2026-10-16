"""Finite native Deathrattle growth and original-draw links; ordinary executors own effects."""
from dataclasses import dataclass,replace
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,DeathrattleMemory,NativeDeathrattleSpec,RememberedDraw,Zone
from .sacrifice import MinionReference,reference_value,same_instance,live_minion


def validate_link(state,link):
    if type(link)is not RememberedDraw:raise ValueError('Expected a typed remembered draw')
    link.__post_init__()
    from .draw_casts import draw_record
    from .hand_history import hand_entry
    draw=draw_record(state,link.draw_id);entry=hand_entry(state,link.hand_entry_id)
    if (draw.outcome!='hand'or(draw.entity_id,draw.source_id)!=(link.entity_id,link.source_id)or
            (entry.entity_id,entry.player_id,entry.card_id,entry.turn,entry.action,entry.reason)!=
            (link.entity_id,draw.player_id,draw.card_id,draw.turn,draw.action,'draw')or
            link.source_id not in state.entities):
        raise ValueError('Remembered draw differs from its original physical acquisition')
    return draw,entry


def validate_ability(state,registry,ability):
    memory=ability.deathrattle_memory
    if memory is None:return
    ability.__post_init__()
    if ability.deathrattle_card_id is None or registry.card(ability.deathrattle_card_id).native_deathrattle!=memory.spec:
        raise ValueError('Deathrattle memory differs from its printed declaration')
    for link in memory.draws:validate_link(state,link)


def validate_carrier(state,registry,card_id,kind,abilities,components=()):
    for ability in abilities:
        memory=getattr(ability,'deathrattle_memory',None)
        if memory is None:continue
        if kind!=CardType.MINION or components or registry.card(card_id).native_deathrattle!=memory.spec:
            raise ValueError('Native Deathrattle memory borrowed an unsupported carrier')
        validate_ability(state,registry,ability)


@dataclass(frozen=True)
class GrowDeathrattleSummon(Effect):
    reference: MinionReference
    ability_id: int
    def __post_init__(self):reference_value(self.reference);_integer(self.ability_id,'original Deathrattle ability',1)


@dataclass(frozen=True)
class DrawForDeathrattle(Effect):
    player_id: int
    reference: MinionReference
    ability_ids: tuple[int,...]
    def __post_init__(self):
        _player(self.player_id);reference_value(self.reference)
        if type(self.ability_ids)is not tuple or len(set(self.ability_ids))!=len(self.ability_ids):
            raise ValueError('Draw memory requires original unique ability identities')
        for value in self.ability_ids:_integer(value,'original draw-link Deathrattle ability',1)


@dataclass(frozen=True)
class DiscardRememberedDraw(Effect):
    deathrattle_id: int
    draw: RememberedDraw
    def __post_init__(self):
        _integer(self.deathrattle_id,'actual Deathrattle invocation',1)
        if type(self.draw)is not RememberedDraw:raise ValueError('Expected original physical draw linkage')
        self.draw.__post_init__()


def validate_reference(state,reference,ability_ids):
    reference_value(reference);entity=state.entities.get(reference.entity_id)
    if (entity is None or reference.zone_epoch>entity.zone_epoch or reference.entered_order>=state.next_order or
            any(value>=state.next_attachment_id for value in ability_ids)):
        raise ResolutionError('Native memory request borrowed unknown or future original allocation')


def grow(r,effect):
    effect.__post_init__();validate_reference(r.state,effect.reference,(effect.ability_id,))
    entity=live_minion(r.state,effect.reference)
    ability=None if entity is None else next((a for a in entity.abilities if a.id==effect.ability_id),None)
    if ability is None or ability.deathrattle_memory is None:
        r.stale(effect,effect.reference.entity_id);return ()
    validate_ability(r.state,r.registry,ability);memory=ability.deathrattle_memory
    if memory.spec.kind!='summon_growth':raise ResolutionError('Summon growth cannot modify draw linkage')
    updated=replace(ability,deathrattle_memory=replace(memory,growth_steps=memory.growth_steps+1))
    entity.abilities=[updated if a.id==ability.id else a for a in entity.abilities]
    r.emit('deathrattle_memory_updated',source_id=entity.id,target_id=entity.id)
    return ()


def validate_draw_request(r,effect):
    if type(effect)is not DrawForDeathrattle:raise ResolutionError('Expected typed native draw request')
    effect.__post_init__();validate_reference(r.state,effect.reference,effect.ability_ids)


def draw(r,effect):
    validate_draw_request(r,effect)
    from .draw_casts import draw_one
    return draw_one(r,effect.player_id,source_id=effect.reference.entity_id,deathrattle_memory=effect)


def remember_draw(r,effect,draw_id,entity):
    validate_draw_request(r,effect)
    if entity.zone!=Zone.HAND or entity.hand_entry_id is None:raise ResolutionError('Native draw link requires its actual hand delivery')
    link=RememberedDraw(draw_id,entity.id,entity.hand_entry_id,effect.reference.entity_id)
    validate_link(r.state,link)
    source=same_instance(r.state,effect.reference)
    if source is None:return
    replacements={}
    for ability in source.abilities:
        if ability.id not in effect.ability_ids:continue
        validate_ability(r.state,r.registry,ability);memory=ability.deathrattle_memory
        if memory is None or memory.spec.kind!='draw_link':raise ResolutionError('Original draw-link ability changed its native profile')
        replacements[ability.id]=replace(ability,deathrattle_memory=replace(memory,draws=(*memory.draws,link)))
    source.abilities=[replacements.get(a.id,a)for a in source.abilities]


def discard(r,effect):
    effect.__post_init__();_,entry=validate_link(r.state,effect.draw)
    from .deathrattles import record
    row=record(r.state,effect.deathrattle_id);memory=row.capture.ability.deathrattle_memory
    if (row.execution_order is None or row.completed or row.interrupted or memory is None or
            memory.spec.kind!='draw_link'or effect.draw not in memory.draws):
        raise ResolutionError('Remembered discard lost its actual active Deathrattle payload')
    entity=r.state.entities.get(effect.draw.entity_id)
    if entity is None or(entity.zone,entity.controller,entity.hand_entry_id)!=(Zone.HAND,entry.player_id,entry.id):return ()
    from .zones import CardReference,DiscardCard,discard_card
    return discard_card(r,DiscardCard(CardReference.capture(entity),row.capture.carrier_id))


def public_summons(entity):
    return[dict(card_id=a.deathrattle_memory.spec.card_id,
        attack=a.deathrattle_memory.spec.attack+a.deathrattle_memory.growth_steps,
        health=a.deathrattle_memory.spec.health+a.deathrattle_memory.growth_steps)
        for a in entity.abilities if a.kind=='deathrattle'and not a.consumed and a.deathrattle_memory is not None
        and a.deathrattle_memory.spec.kind=='summon_growth']


def register(mechanics):
    for typ,handler in ((GrowDeathrattleSummon,grow),(DrawForDeathrattle,draw),(DiscardRememberedDraw,discard)):
        mechanics.register(typ,handler)
    for typ in (NativeDeathrattleSpec,RememberedDraw,DeathrattleMemory):mechanics.register_payload_type(typ)
