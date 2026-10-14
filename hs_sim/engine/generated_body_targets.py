"""Connected generated whole-card targeting at the real post-install window.

Each physical declaration has its own condition and target. Repetition/result
groups reuse those selections; this module grants no paid or indirect origin.
Compact original operands are host-only and do not authenticate unsigned saves.
"""
from copy import deepcopy
from dataclasses import dataclass, replace
import json
from types import SimpleNamespace

from .automatic_targets import (AutomaticTargetPartition, AutomaticTargetPreference,
    AutomaticTargetSelection, automatic_target_partition)
from .body_conditions import BodyPlayConditions
from .body_grants import BodyReference
from .body_targets import BodyTargetReference, body_target_declarations
from .body_target_authority import body_target_authority
from .body_target_origin import (canonical_json, capture_origin, entity_fact,
    origin_from_dict, require_audited_predicate)
from .effects import _behavior, _integer, _source
from .errors import IllegalAction, ResolutionError
from .lifecycle import active_abilities
from .model import (BattlecryPayload,ComboPayload,CardType, Entity, GameState, PaidBodyTargetOrigin, TargetMode,
    TargetSpec, Zone)
from .serialization import canonical_hash, entity_from_dict, entity_to_dict
from .spell_casts import effective_definition
from .targeting import accepts_target

KINDS = (CardType.MINION, CardType.WEAPON, CardType.LOCATION, CardType.HERO)


@dataclass(frozen=True)
class GeneratedWholeTargetBinding:
    carrier_card_id: str
    profile_id: str
    mode: str = 'body_only'
    targeting: TargetSpec | None = None
    target_rule: str = 'any_entity'
    target_condition: str | None = None
    manathirst_threshold: int | None = None

    def __post_init__(self):
        for value in (self.carrier_card_id,self.profile_id,self.target_rule): _behavior(value)
        if type(self.mode) is not str or self.mode not in ('body_only','preserve_root','explicit_root'):
            raise ValueError('Unknown generated ordinary/body target policy')
        if self.targeting is not None:
            if type(self.targeting) is not TargetSpec: raise ValueError('Generated root requires its exact target domain')
            self.targeting.__post_init__()
        if self.target_condition is not None and self.target_condition not in ('combo','outcast','finale','quickdraw','manathirst'):
            raise ValueError('Unknown generated root condition')
        if self.manathirst_threshold is not None: _integer(self.manathirst_threshold,'generated root threshold',1)
        if self.mode != 'explicit_root' and (self.targeting is not None or self.target_rule != 'any_entity' or
                self.target_condition is not None or self.manathirst_threshold is not None):
            raise ValueError('Only explicit generated roots can override declarations')
        if self.target_condition is not None and self.targeting is None:
            raise ValueError('Conditional generated root requires targeting')
        if (self.target_condition == 'manathirst') != (self.manathirst_threshold is not None):
            raise ValueError('Generated explicit root requires its own exact threshold')


def validate_binding(registry, binding):
    if type(binding) is not GeneratedWholeTargetBinding: raise ValueError('Expected exact generated source binding')
    binding.__post_init__()
    profile = registry.body_target_profile(binding.profile_id)
    if (profile.origin,profile.acceptance_window) != ('generated_whole','generated_acceptance'):
        raise ValueError('Generated source requires its own post-install target profile')
    card = registry.card(binding.carrier_card_id)
    if card.kind not in KINDS or not card.hand_playable:
        raise ValueError('Generated source requires a playable physical card')
    if card.choose_one is not None and binding.mode != 'preserve_root':
        raise ValueError('Generated Choose One keeps its own branch target domain through preserve_root')
    if binding.mode == 'body_only' and (card.on_play is not None or card.choose_one is not None):
        raise ValueError('Generated body-only policy cannot erase ordinary text')
    if binding.mode == 'explicit_root' and (card.on_play is None or card.choose_one is not None):
        raise ValueError('Generated explicit root requires an ordinary on-play declaration')
    registry.target_rule(binding.target_rule)


def selected_binding(registry, card_id, request):
    bound = any(card == card_id for card,_ in registry.generated_whole_target_bindings)
    if request.body_target_profile_id is None:
        from .indirect_body_targets import connected_carrier
        if bound or connected_carrier(registry,card_id):
            raise ResolutionError('Independent target carrier requires its own generated origin producer')
        return None
    binding = registry.generated_whole_target_binding(card_id,request.body_target_profile_id)
    validate_binding(registry,binding)
    profile = registry.body_target_profile(binding.profile_id)
    from .generated_combo_repeats import PROFILES
    if request.physical_profile not in PROFILES:
        raise ResolutionError('Independent generated bodies require an actual family identity profile')
    if profile.selection == 'random' and request.body_target_id is not None:
        raise ResolutionError('Random generated body policy cannot borrow an explicit target')
    return binding


def authorities(state, registry, source, binding):
    validate_binding(registry,binding)
    if source.card_id != binding.carrier_card_id or source.kind not in KINDS:
        raise ValueError('Generated carrier differs from its registered source')
    if binding.mode == 'body_only' and active_abilities(source,'on_play'):
        raise ValueError('Generated body-only policy cannot erase current ordinary text')
    rows = () if source.kind == CardType.LOCATION else tuple(body_target_authority(
        state,registry,d.reference,binding.profile_id) for d in body_target_declarations(
            state,registry,BodyReference.capture(source),binding.profile_id))
    for row in rows: require_audited_predicate(registry,row.declaration.contract.target_rule)
    return rows


def grant_authority(state, registry, entity, ability):
    if entity.zone not in (Zone.BOARD,Zone.WEAPON,Zone.HERO): return ()
    proposed = replace(entity,abilities=[*entity.abilities,ability])
    prospective = replace(state,entities={**state.entities,entity.id:proposed})
    result=[]
    for (card,profile),binding in registry.generated_whole_target_bindings.items():
        if card != entity.card_id: continue
        try: rows=authorities(prospective,registry,proposed,binding)
        except (ValueError,IllegalAction): continue
        if any(row.declaration.reference.ability_id==ability.id for row in rows): result.append(profile)
    return tuple(result)


def conditions(activation, threshold):
    return BodyPlayConditions(activation.combo,False,False,False,
        threshold is not None and activation.max_mana>=threshold,activation.max_mana,threshold)


def root_definition(registry, binding, activation, on_play, choose_one=None):
    card=registry.card(binding.carrier_card_id)
    from .generated_choose_one import definition as branch_definition
    card=branch_definition(registry,card,choose_one)
    if binding.mode=='body_only' or not on_play:
        return replace(card,requires_target=False,targeting=None,target_rule='any_entity',target_condition=None)
    if binding.mode=='explicit_root':
        card=replace(card,requires_target=False,targeting=binding.targeting,target_rule=binding.target_rule,
            target_condition=binding.target_condition,manathirst=binding.manathirst_threshold)
    return effective_definition(card,vars(conditions(activation,card.manathirst)))


def body_definition(registry, reference, fact):
    card=replace(registry.card(reference.declaration_card_id),kind=registry.card(reference.carrier.card_id).kind)
    if reference.family=='combo' and not fact.combo:
        return replace(card,requires_target=False,targeting=None,target_rule='any_entity',target_condition=None)
    return effective_definition(card,vars(fact))


def explicit_result(partition, target_id):
    if partition.mode is None: return None,None
    if target_id is not None:
        return (target_id,None) if target_id in partition.legal_ids else (None,'invalid_target')
    return None,('no_target' if partition.mode is TargetMode.REQUIRED or
        partition.mode is TargetMode.IF_AVAILABLE and partition.legal_ids else None)


@dataclass(frozen=True)
class GeneratedBodySelection:
    partition: AutomaticTargetPartition
    selection: str
    request_target_id: int | None
    target_id: int | None
    failure: str | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.partition) is not AutomaticTargetPartition: raise ValueError('Generated body lost its target partition')
        self.partition.__post_init__(); _source(self.request_target_id); _source(self.target_id)
        from .whole_card_history import rng_state
        rng_state(self.rng_before); rng_state(self.rng_after)
        if type(self.selection) is not str or self.selection not in ('random','explicit'):
            raise ValueError('Unknown generated body selection mode')
        if self.selection=='random':
            if self.request_target_id is not None: raise ValueError('Random body cannot carry an explicit request')
            AutomaticTargetSelection(self.partition,self.target_id,self.failure,self.rng_before,self.rng_after).__post_init__()
        else:
            expected=explicit_result(self.partition,self.request_target_id)
            if (self.target_id,self.failure)!=expected or self.rng_before!=self.rng_after:
                raise ValueError('Explicit generated target changed its request or RNG')


@dataclass(frozen=True)
class GeneratedBodyTargetSlot:
    reference: BodyTargetReference
    conditions: BodyPlayConditions
    active: bool
    selected: GeneratedBodySelection

    def __post_init__(self):
        for value,cls in ((self.reference,BodyTargetReference),(self.conditions,BodyPlayConditions),(self.selected,GeneratedBodySelection)):
            if type(value) is not cls: raise ValueError('Generated slot requires exact typed source/condition/selection')
            value.__post_init__()
        if type(self.active) is not bool or self.active != (self.reference.family=='battlecry' or self.conditions.combo):
            raise ValueError('Generated slot activation differs from its family condition')


@dataclass(frozen=True)
class GeneratedBodyTargetAcceptance:
    binding: GeneratedWholeTargetBinding
    origin: PaidBodyTargetOrigin
    root: AutomaticTargetSelection
    slots: tuple[GeneratedBodyTargetSlot,...]

    def __post_init__(self):
        for value,cls in ((self.binding,GeneratedWholeTargetBinding),(self.origin,PaidBodyTargetOrigin),(self.root,AutomaticTargetSelection)):
            if type(value) is not cls: raise ValueError('Generated targets lost their complete original operands')
            value.__post_init__()
        if type(self.slots) is not tuple or any(type(s) is not GeneratedBodyTargetSlot for s in self.slots):
            raise ValueError('Generated target acceptance requires its complete ordered slots')
        rng=self.root.rng_after;identities=set()
        for slot in self.slots:
            slot.__post_init__()
            if slot.reference.ability_id in identities or slot.selected.rng_before!=rng:
                raise ValueError('Generated target slots duplicated identity or broke selection order')
            identities.add(slot.reference.ability_id);rng=slot.selected.rng_after


def partition(state,registry,source,definition,observation,preference):
    from .player_target_inputs import factory
    context=factory(observation,require_active_player=False) if observation is not None else None
    return automatic_target_partition(SimpleNamespace(state=state,registry=registry),source,definition,
        preference=preference,context_factory=context)


def capture(r,binding,activation,request):
    source=r.state.entities[activation.source.entity_id]
    on_play=tuple(a.behavior_id for a in active_abilities(source,'on_play'))
    rows=authorities(r.state,r.registry,source,binding)
    choose_one=r.state.whole_card_replay_ledger.children[activation.child_id-1].physical.choose_one
    definition=root_definition(r.registry,binding,activation,on_play,choose_one)
    require_audited_predicate(r.registry,definition.target_rule)
    specs=[(row.declaration.reference,conditions(activation,row.declaration.contract.manathirst_threshold)) for row in rows]
    needs_player=any(r.registry.target_visibility(d.target_rule)=='player' for d in
        (definition,*(body_definition(r.registry,ref,c) for ref,c in specs)))
    observation=None
    if needs_player:
        from .player_target_inputs import capture as capture_view,validate_full_state
        observation=capture_view(r.game,r.state,source)
        validate_full_state(r.state,r.registry,source,observation,require_active_player=False)
    from .serialization import state_to_dict
    origin=capture_origin(r.state,source,canonical_hash(state_to_dict(r.state)),observation)
    domain=partition(r.state,r.registry,source,definition,observation,request.target_preference)
    before=r.game._rng.getstate()
    target=r.game._rng.choice(domain.selection_ids) if domain.selection_ids else None
    failure='no_target' if not domain.selection_ids and domain.mode is TargetMode.REQUIRED else None
    root=AutomaticTargetSelection(domain,target,failure,before,r.game._rng.getstate())
    profile=r.registry.body_target_profile(binding.profile_id);slots=[]
    for ref,c in specs:
        definition=body_definition(r.registry,ref,c)
        domain=partition(r.state,r.registry,source,definition,observation,request.target_preference)
        before=r.game._rng.getstate()
        if profile.selection=='random':
            target=r.game._rng.choice(domain.selection_ids) if domain.selection_ids else None
            failure='no_target' if not domain.selection_ids and domain.mode is TargetMode.REQUIRED else None
        else: target,failure=explicit_result(domain,request.body_target_id)
        selected=GeneratedBodySelection(domain,profile.selection,request.body_target_id,target,failure,before,r.game._rng.getstate())
        slots.append(GeneratedBodyTargetSlot(ref,c,ref.family=='battlecry' or c.combo,selected))
    return root_definition(r.registry,binding,activation,on_play,choose_one),GeneratedBodyTargetAcceptance(binding,origin,root,tuple(slots))


def original_inputs(state,registry,accepted):
    accepted.__post_init__();validate_binding(registry,accepted.binding);origin=accepted.origin
    if registry.generated_whole_target_binding(accepted.binding.carrier_card_id,accepted.binding.profile_id)!=accepted.binding:
        raise ValueError('Generated source changed its registered ordinary/body separation authority')
    source=entity_from_dict(json.loads(origin.source_json))
    if canonical_json(entity_to_dict(source))!=origin.source_json or entity_fact(source) not in origin.entities:
        raise ValueError('Generated target source differs from its original canonical universe')
    if (not source.active or source.doomed or source.zone not in (Zone.BOARD,Zone.HERO,Zone.WEAPON) or
            source.kind in (CardType.MINION,CardType.HERO) and source.health<=0 or
            source.kind in (CardType.WEAPON,CardType.LOCATION) and source.durability<=0):
        raise ValueError('Generated acceptance requires its actual live installed original source')
    if origin.next_entity_id>state.next_entity_id or origin.next_attachment_id>state.next_attachment_id:
        raise ValueError('Generated target universe exceeds original allocation')
    if tuple(f.id for f in origin.entities)!=tuple(sorted(i for i in state.entities if i<origin.next_entity_id)):
        raise ValueError('Generated original target universe lost a physical identity')
    if (tuple(sorted(origin.hand))!=tuple(f.id for f in origin.entities if f.zone==Zone.HAND and f.controller==source.controller) or
            tuple(sorted(origin.board))!=tuple(f.id for f in origin.entities if f.zone==Zone.BOARD and f.controller==source.controller)):
        raise ValueError('Generated original player slots lost their complete physical membership')
    identities=[a.id for a in (*source.abilities,*source.enchantments)]
    if len(set(identities))!=len(identities) or any(i>=origin.next_attachment_id for i in identities):
        raise ValueError('Generated source lost its exact physical attachments')
    entities={f.id:Entity(f.id,f.card_id,f.owner,f.controller,f.zone,base_attack=f.attack,base_health=f.max_health,
        damage=f.damage,kind=f.kind,keywords=set(f.keywords),doomed=f.doomed,durability=f.durability,
        starship_building=not f.active,enchantments=list(f.tribe_changes)) for f in origin.entities}
    for f in origin.entities:
        if registry.card(f.card_id).kind!=f.kind: raise ValueError('Generated target fact has an unknown physical kind')
    entities[source.id]=source
    probe=GameState({},entities,active_player=source.controller,turn=origin.turn,action_number=origin.action,
        next_entity_id=origin.next_entity_id,next_attachment_id=origin.next_attachment_id)
    rows=authorities(probe,registry,source,accepted.binding)
    if tuple(row.declaration.reference for row in rows)!=tuple(s.reference for s in accepted.slots):
        raise ValueError('Generated acceptance changed its complete authorized physical vector')
    if origin.observation is not None:
        from .player_target_inputs import validate_origin
        validate_origin(registry,origin,source,require_active_player=False)
    return probe,source


def validate(state,registry,progress,request=None,before=None):
    accepted=progress.body_targets
    if accepted is None: return
    original,source=original_inputs(state,registry,accepted)
    activation=progress.activation
    if activation is None or (source.id,source.card_id,source.kind,source.owner,source.controller,source.zone,source.zone_epoch,source.entered_order)!=(
            activation.source.entity_id,activation.source.card_id,activation.source.kind,activation.source.owner,activation.player_id,
            activation.source.zone,activation.source.zone_epoch,activation.source.entered_order) or (accepted.origin.turn,accepted.origin.action)!=(activation.turn,activation.action):
        raise ValueError('Generated target authority borrowed another activation/window')
    if accepted.root!=progress.selection: raise ValueError('Generated ordinary target changed its original separate selection')
    from .generated_combo_repeats import PROFILES
    if activation.profile_id not in PROFILES:
        raise ValueError('Generated target acceptance lacks actual family invocation identities')
    profile=registry.body_target_profile(accepted.binding.profile_id)
    if progress.battlecries!=tuple(BattlecryPayload(s.reference.ability_id,s.reference.behavior_id,s.reference.declaration_card_id)
            for s in accepted.slots if s.reference.family=='battlecry') or progress.combos!=tuple(
            ComboPayload(s.reference.ability_id,s.reference.behavior_id,s.reference.declaration_card_id)
            for s in accepted.slots if s.reference.family=='combo' and s.active):
        raise ValueError('Generated physical execution changed its complete accepted body payloads')
    if progress.on_play!=tuple(a.behavior_id for a in active_abilities(source,'on_play')):
        raise ValueError('Generated physical execution changed its original ordinary payload vector')
    if len({s.selected.request_target_id for s in accepted.slots})>1:
        raise ValueError('Generated slots borrowed different source requests')
    definitions=[root_definition(registry,accepted.binding,activation,progress.on_play,progress.choose_one)]
    for slot in accepted.slots:
        if slot.conditions!=conditions(activation,registry.card(slot.reference.declaration_card_id).manathirst):
            raise ValueError('Generated body rewrote its own original condition/threshold')
        if slot.selected.selection!=profile.selection: raise ValueError('Generated body borrowed another selection policy')
        definitions.append(body_definition(registry,slot.reference,slot.conditions))
    needs_player=any(registry.target_visibility(d.target_rule)=='player' for d in definitions)
    if needs_player!=(accepted.origin.observation is not None): raise ValueError('Generated original player input changed visibility')
    if needs_player:
        from .player_target_inputs import decode
        value=decode(accepted.origin.observation,require_active_player=False)
        own=value['players'][activation.player_id-1]
        if (own['max_mana']!=activation.max_mana or value['active_player']!=state.owner_turn_history[activation.owner_turn_id-1].player_id):
            raise ValueError('Generated player observation changed its actual condition crystals or owner turn')
        for p in value['players']:
            prior=[r for r in state.play_history[:activation.before_play_id-1] if r.player_id==p['id']]
            if (p['cards_played_total'],p['cards_played_this_turn'])!=(len(prior),sum(r.turn==activation.turn for r in prior)):
                raise ValueError('Generated player observation changed its original paid-history prefix')
    for definition,selection in zip(definitions,(accepted.root,*(s.selected for s in accepted.slots))):
        require_audited_predicate(registry,definition.target_rule)
        actual=partition(original,registry,source,definition,accepted.origin.observation,accepted.root.partition.preference)
        if actual!=selection.partition: raise ValueError('Generated body changed its original complete candidate domain')
    if request is not None:
        if (request.body_target_profile_id,request.target_preference)!=(accepted.binding.profile_id,accepted.root.partition.preference) or any(
                s.selected.request_target_id!=request.body_target_id for s in accepted.slots):
            raise ValueError('Generated body changed its actual source request')
    if before is not None:
        from .serialization import state_to_dict
        if (canonical_hash(state_to_dict(before))!=accepted.origin.original_state_hash or
                entity_to_dict(before.entities[source.id])!=entity_to_dict(source) or
                tuple(entity_fact(before.entities[i]) for i in sorted(before.entities))!=accepted.origin.entities):
            raise ValueError('Generated target operands differ from their complete original state')
        if accepted.origin.observation is not None:
            from .player_target_inputs import validate_full_state
            validate_full_state(before,registry,before.entities[source.id],accepted.origin.observation,require_active_player=False)


def slot_for(progress,payload,family):
    if progress.body_targets is None: return None
    row=next((s for s in progress.body_targets.slots if (s.reference.family,s.reference.ability_id)==(family,payload.ability_id)),None)
    if row is None or (row.reference.declaration_card_id,row.reference.behavior_id)!=(payload.card_id,payload.behavior_id) or not row.active:
        raise ValueError('Generated invocation lost its exact accepted physical target slot')
    return row


def target_for(progress,payload,family):
    row=slot_for(progress,payload,family)
    if row is not None: return row.selected.target_id
    return progress.selection.target_id


def failure_for(r,progress,payload,family):
    row=slot_for(progress,payload,family)
    if row is None: return None
    if row.selected.failure is not None: return row.selected.failure
    if row.selected.partition.mode is None or row.selected.target_id is None: return None
    source=deepcopy(r.state.entities[progress.source.entity_id]);source.controller=progress.player_id
    definition=body_definition(r.registry,row.reference,row.conditions)
    context=None
    if r.registry.target_visibility(definition.target_rule)=='player':
        from .player_target_inputs import live_factory
        context=live_factory(r,source)
    return None if accepts_target(r.state,r.registry,source,definition,row.selected.target_id,automatic=True,context_factory=context) else 'invalid_target'


def root_failure_for(r,progress):
    selected=progress.selection
    if selected.failure is not None: return selected.failure
    if selected.partition.mode is None or selected.target_id is None: return None
    source=deepcopy(r.state.entities[progress.source.entity_id]);source.controller=progress.player_id
    definition=root_definition(r.registry,progress.body_targets.binding,progress.activation,progress.on_play,progress.choose_one)
    context=None
    if r.registry.target_visibility(definition.target_rule)=='player':
        from .player_target_inputs import live_factory
        context=live_factory(r,source)
    return None if accepts_target(r.state,r.registry,source,definition,selected.target_id,automatic=True,context_factory=context) else 'invalid_target'


def validate_failure(progress,payload,family,failure):
    row=slot_for(progress,payload,family)
    if row is None:
        if family=='combo' and failure is not None: raise ValueError('Legacy generated Combo cannot invent independent target failure')
        return
    allowed={row.selected.failure} if row.selected.failure is not None or row.selected.target_id is None else {None,'invalid_target'}
    if failure not in allowed: raise ValueError('Generated target failure differs from its own accepted selection')


def acceptance_from_dict(value):
    from .serialization import _row,_list
    from .automatic_targets import selection_from_dict
    from .indirect_body_targets import reference_from_dict
    row=_row(value,GeneratedBodyTargetAcceptance);binding=_row(row['binding'],GeneratedWholeTargetBinding)
    if binding['targeting'] is not None:
        spec=_row(binding['targeting'],TargetSpec)
        spec['kinds']=tuple(CardType(v) for v in _list(spec['kinds'],'generated target kinds'))
        spec['zones']=tuple(Zone(v) for v in _list(spec['zones'],'generated target zones'))
        spec['mode']=TargetMode(spec['mode']);binding['targeting']=TargetSpec(**spec)
    row['binding']=GeneratedWholeTargetBinding(**binding);row['origin']=origin_from_dict(row['origin'])
    row['root']=selection_from_dict(row['root']);slots=[]
    def tuples(item): return tuple(tuples(v) for v in item) if type(item) is list else item
    for value in _list(row['slots'],'generated target slots'):
        slot=_row(value,GeneratedBodyTargetSlot);slot['reference']=reference_from_dict(slot['reference'])
        slot['conditions']=BodyPlayConditions(**_row(slot['conditions'],BodyPlayConditions))
        selection=_row(slot['selected'],GeneratedBodySelection);part=_row(selection['partition'],AutomaticTargetPartition)
        part['preference']=AutomaticTargetPreference(part['preference'])
        if part['mode'] is not None: part['mode']=TargetMode(part['mode'])
        for key in ('excluded_ids','legal_ids','enemy_ids','selection_ids'):
            part[key]=tuple(_list(part[key],'generated target partition'))
        selection['partition']=AutomaticTargetPartition(**part)
        for key in ('rng_before','rng_after'): selection[key]=tuples(_list(selection[key],'generated target RNG'))
        slot['selected']=GeneratedBodySelection(**selection);slots.append(GeneratedBodyTargetSlot(**slot))
    row['slots']=tuple(slots)
    return GeneratedBodyTargetAcceptance(**row)


def register(mechanics):
    for kind in (GeneratedWholeTargetBinding,GeneratedBodySelection,GeneratedBodyTargetSlot,GeneratedBodyTargetAcceptance):
        mechanics.register_payload_type(kind)
