"""Finite native Deathrattle growth and original-draw links; ordinary executors own effects."""
from dataclasses import dataclass,replace
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,DeathrattleMemory,NativeDeathrattleSpec,RememberedDraw,RememberedDormancy,RememberedDiscovery,Zone
from .sacrifice import MinionReference,reference_value,same_instance,live_minion
from .zones import CardReference,DiscardCard,discard_card


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
    for link in memory.dormancies:validate_dormancy_link(state,registry,link)
    from .discovery_memory import validate_link as validate_discovery_link
    for link in memory.discoveries:validate_discovery_link(state,registry,link)
    for discard_id in memory.discard_ids:
        if discard_id > len(state.discard_history):raise ValueError('Remembered discard exceeds original history')
        row=state.discard_history[discard_id-1]
        from .discard_history import validate_base_copy
        validate_base_copy(state,registry,row)
        if (row.source is None or row.source.kind!=CardType.MINION or row.source.zone!=Zone.BOARD or
                registry.card(row.source.card_id).native_deathrattle!=memory.spec):
            raise ValueError('Remembered discard lost its original native source declaration')


def validate_carrier(state,registry,card_id,kind,abilities,components=()):
    for ability in abilities:
        memory=getattr(ability,'deathrattle_memory',None)
        if memory is None:continue
        inherited=ability.deathrattle_inherited_from is not None
        if kind!=CardType.MINION or components or not inherited and registry.card(card_id).native_deathrattle!=memory.spec:
            raise ValueError('Native Deathrattle memory borrowed an unsupported carrier')
        if inherited:
            from .deathrattle_inheritance import validate_ability as validate_inherited
            validate_inherited(state,registry,ability)
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


@dataclass(frozen=True)
class DiscardForDeathrattle(Effect):
    """Commit an original hand discard to original native attachments before notification."""
    card: CardReference
    reference: MinionReference
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.card) is not CardReference:raise ValueError('Native discard requires an original physical hand card')
        self.card.__post_init__();reference_value(self.reference)
        if self.card.zone!=Zone.HAND:raise ValueError('Native discard linkage requires HAND')
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids))!=len(self.ability_ids):
            raise ValueError('Native discard requires immutable distinct original ability identities')
        for value in self.ability_ids:_integer(value,'original discard-link ability',1)

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_reference(state,self.reference,self.ability_ids)
        entity=state.entities.get(self.card.entity_id)
        if entity is None or self.card.zone_epoch>entity.zone_epoch:
            raise ValueError('Native discard borrowed an unknown or future original card')
        if registry.card(self.reference.card_id).kind!=CardType.MINION or not registry.card(self.card.card_id).hand_playable:
            raise ValueError('Native discard requires a minion source and playable stored card')


def discard_for_memory(r,effect):
    effect.validate_in_state(r.state,r.registry)
    return discard_card(r,DiscardCard(effect.card,effect.reference.entity_id),deathrattle_memory=effect)


def remember_discard(r,effect,row):
    if type(effect) is not DiscardForDeathrattle:raise ResolutionError('Expected actual native discard request')
    effect.validate_in_state(r.state,r.registry);ref=effect.reference;card=effect.card
    if (row.card.entity_id,row.card.controller,row.card.card_id,row.card.zone_epoch)!=(
            card.entity_id,card.player_id,card.card_id,card.zone_epoch):
        raise ResolutionError('Native discard memory borrowed a different successful physical operation')
    source=same_instance(r.state,ref)
    if source is None:return
    if row.source is None or (
            row.source.entity_id,row.source.controller,row.source.card_id,row.source.zone_epoch,row.source.entered_order)!=(
            ref.entity_id,ref.player_id,ref.card_id,ref.zone_epoch,ref.entered_order):
        raise ResolutionError('Native discard memory borrowed a different original source residence')
    replacements={}
    for ability in source.abilities:
        if ability.id not in effect.ability_ids:continue
        validate_ability(r.state,r.registry,ability);memory=ability.deathrattle_memory
        if memory is None or memory.spec.kind!='discard_link':
            raise ResolutionError('Original discard-link ability changed its native profile')
        replacements[ability.id]=replace(ability,deathrattle_memory=replace(memory,discard_ids=(*memory.discard_ids,row.id)))
    source.abilities=[replacements.get(a.id,a)for a in source.abilities]


def validate_reference(state,reference,ability_ids):
    reference_value(reference);entity=state.entities.get(reference.entity_id)
    if (entity is None or reference.zone_epoch>entity.zone_epoch or reference.entered_order>=state.next_order or
            any(value>=state.next_attachment_id for value in ability_ids)):
        raise ResolutionError('Native memory request borrowed unknown or future original allocation')


def validate_dormancy_link(state,registry,link):
    if type(link) is not RememberedDormancy:
        raise ValueError('Expected a complete original captive and dormancy interval')
    link.__post_init__()
    if not 1 <= link.battlecry_id <= len(state.battlecry_history):
        raise ValueError('Remembered dormancy lost its original Battlecry')
    row = state.battlecry_history[link.battlecry_id-1]
    spec = registry.card(row.payload.card_id).native_deathrattle
    target = state.entities.get(link.entity_id)
    if (row.id != link.battlecry_id or row.target_id != link.entity_id or
            not row.payload_started or row.failure is not None or
            spec is None or spec.kind != 'dormancy_link' or target is None or
            registry.card(link.card_id).kind != CardType.MINION or
            link.zone_epoch > target.zone_epoch or link.entered_order >= state.next_order or
            link.dormancy_id >= state.next_attachment_id):
        raise ValueError('Remembered dormancy changed its actual original target or allocation')
    return row


@dataclass(frozen=True)
class ImprisonForDeathrattle(Effect):
    battlecry_id: int
    target: MinionReference
    reference: MinionReference | None
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        _integer(self.battlecry_id,'actual imprisonment Battlecry',1)
        reference_value(self.target)
        if self.reference is not None: reference_value(self.reference)
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Imprisonment requires original unique memory abilities')
        for value in self.ability_ids: _integer(value,'original captive-memory ability',1)
        if self.reference is None and self.ability_ids:
            raise ValueError('A departed carrier cannot claim a later memory attachment')

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if not 1 <= self.battlecry_id <= len(state.battlecry_history):
            raise ValueError('Imprisonment lost its actual Battlecry')
        row = state.battlecry_history[self.battlecry_id-1]
        spec = registry.card(row.payload.card_id).native_deathrattle
        if (row.id != self.battlecry_id or row.completed or row.interrupted or
                not row.payload_started or row.failure is not None or row.target_id != self.target.entity_id or
                spec is None or spec.kind != 'dormancy_link' or
                self.reference is not None and self.reference.entity_id != row.source_id):
            raise ValueError('Imprisonment changed its original active body or target')
        validate_reference(state,self.target,())
        if self.reference is not None: validate_reference(state,self.reference,self.ability_ids)
        return row


def imprison(r,effect):
    row = effect.validate_in_state(r.state,r.registry)
    if live_minion(r.state,effect.target) is None:
        r.stale(effect,effect.target.entity_id);return ()
    from .dormancy import MakeDormant,make_dormant
    return make_dormant(r,MakeDormant(effect.target.entity_id,10000,row.source_id),deathrattle_memory=effect)


def remember_dormancy(r,effect,entity):
    effect.validate_in_state(r.state,r.registry)
    ref = effect.target
    if same_instance(r.state,ref) is not entity or entity.dormancy is None:
        raise ValueError('Imprisonment lost the actual committed target interval')
    link = RememberedDormancy(effect.battlecry_id,entity.id,ref.player_id,ref.card_id,
        ref.zone_epoch,ref.entered_order,entity.dormancy.id)
    validate_dormancy_link(r.state,r.registry,link)
    source = None if effect.reference is None else same_instance(r.state,effect.reference)
    if source is None: return
    replacements = {}
    for ability in source.abilities:
        if ability.id not in effect.ability_ids: continue
        validate_ability(r.state,r.registry,ability)
        memory = ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'dormancy_link':
            raise ResolutionError('Original captive-memory ability changed its native profile')
        replacements[ability.id] = replace(ability,deathrattle_memory=replace(memory,
            dormancies=(*memory.dormancies,link)))
    source.abilities = [replacements.get(a.id,a) for a in source.abilities]


@dataclass(frozen=True)
class AwakenRememberedDormancy(Effect):
    deathrattle_id: int
    captive: RememberedDormancy

    def __post_init__(self):
        _integer(self.deathrattle_id,'actual captive release Deathrattle',1)
        if type(self.captive) is not RememberedDormancy:
            raise ValueError('Awakening requires its original typed captive')
        self.captive.__post_init__()

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_dormancy_link(state,registry,self.captive)
        from .deathrattles import record
        row = record(state,self.deathrattle_id)
        memory = row.capture.ability.deathrattle_memory
        if (row.execution_order is None or row.completed or row.interrupted or memory is None or
                memory.spec.kind != 'dormancy_link' or self.captive not in memory.dormancies):
            raise ValueError('Captive awakening lost its actual frozen active Deathrattle')
        return row


def awaken_remembered(r,effect):
    row = effect.validate_in_state(r.state,r.registry)
    link = effect.captive
    from .dormancy import AwakenCapturedMinion
    ref = MinionReference(link.entity_id,link.player_id,link.card_id,link.zone_epoch,link.entered_order)
    return (AwakenCapturedMinion(ref,link.dormancy_id,row.capture.carrier_id),)


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
    for typ,handler in ((GrowDeathrattleSummon,grow),(DrawForDeathrattle,draw),(DiscardRememberedDraw,discard),
                        (DiscardForDeathrattle,discard_for_memory),
                        (ImprisonForDeathrattle,imprison),(AwakenRememberedDormancy,awaken_remembered)):
        mechanics.register(typ,handler)
    for typ in (NativeDeathrattleSpec,RememberedDraw,RememberedDormancy,RememberedDiscovery,DeathrattleMemory):mechanics.register_payload_type(typ)
