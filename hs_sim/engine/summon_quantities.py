"""Attributed card summons and resumable duplicate-selected-entry quantity plans.

The live attachment product, pre-entry material and sequential placement are
explicit local policies pending M6. Cause identity differs from summon material.
Compact original facts prove internal consistency, not unsigned origin truth.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .card_creation import CreatedMinionGrant, validate_pool_entry_grant, minion_grant_from_dict
from .effects import Effect, _behavior, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .lifecycle import attachment_id
from .entry_strength import AcceptedEntryStrength
from .copy_materials import CopyEntryMaterial
from .recruit_summons import RecruitEntryMaterial
from .resurrection_summons import ResurrectionEntryMaterial,ResurrectionEntryLink
from .model import AbilityInstance, CardType, DeathrattleMemory, GameState, Keyword, SummonQuantitySpec, SummonStats, Zone
from .replay_entry_material import PhysicalReplayEntryMaterial


@dataclass(frozen=True)
class SummonCause:
    source: SourceAllocationFact
    player_id: int
    turn: int
    action: int
    origin: str = 'card_effect'
    cast_id: int | None = None
    cast_card_id: str | None = None

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact: raise ValueError('Typed causing card required')
        self.source.__post_init__(); _player(self.player_id)
        _integer(self.turn,'summon cause turn',1); _integer(self.action,'summon cause action',0)
        if self.origin not in ('card_effect','spell_cast','hero_power'): raise ValueError('Unknown summon cause origin')
        _source(self.cast_id)
        if (self.cast_id is None)!=(self.cast_card_id is None): raise ValueError('Incomplete summon cast cause')
        if (self.origin=='spell_cast')!=(self.cast_id is not None): raise ValueError('Spell summon requires its actual cast')
        if self.cast_card_id is not None and (type(self.cast_card_id) is not str or not self.cast_card_id):
            raise ValueError('Unknown original summon cast face')

    @classmethod
    def capture(cls,context):
        cast=context.cast
        if cast is not None and (cast.source_id,cast.player_id)!=(context.source_id,context.player_id):
            cast=None
        power=context.power
        if power is not None and (power.source_id,power.player_id)!=(context.source_id,context.player_id):
            power=None
        return cls(SourceAllocationFact.capture(context.state,context.source),context.player_id,
            context.state.turn,context.state.action_number,
            'spell_cast' if cast is not None else 'hero_power' if power is not None else 'card_effect',
            cast.id if cast is not None else None,cast.card_id if cast is not None else None)


@dataclass(frozen=True)
class SummonEntryMaterial:
    card_id: str
    stats: SummonStats | None = None
    deathrattles: tuple[str,...] = ()
    keywords: tuple[Keyword,...] = ()
    dormant_turns: int | None = None
    on_summon: str | None = None
    entry_grant: CreatedMinionGrant | None = None
    deathrattle_memory: DeathrattleMemory | None = None

    def __post_init__(self):
        from .model import validate_summon_stats
        if self.deathrattle_memory is not None:
            if (type(self.deathrattle_memory) is not DeathrattleMemory or
                    self.deathrattle_memory.spec.kind != 'copy_summon' or self.deathrattle_memory.summon_copy is None
                    or any((self.stats, self.deathrattles, self.keywords, self.dormant_turns, self.on_summon, self.entry_grant))):
                raise ValueError('Seeded Deathrattle entry requires one plain original copy memory')
            self.deathrattle_memory.__post_init__()
        validate_pool_entry_grant(self.entry_grant)
        if self.entry_grant is not None and (self.stats is not None or self.deathrattles or
                self.keywords or self.dormant_turns is not None or self.on_summon is not None):
            raise ValueError('Pool entry Attack grant requires plain printed material')
        if self.dormant_turns is not None:
            _integer(self.dormant_turns, 'pre-entry dormant turns', 1)
            if self.stats is not None or self.deathrattles or self.keywords or self.on_summon is not None:
                raise ValueError('Forced dormant entry requires its plain printed minion material')
        if self.on_summon is not None:_behavior(self.on_summon)
        if type(self.card_id) is not str or not self.card_id: raise ValueError('Summon entry requires a card')
        validate_summon_stats(self.stats)
        if type(self.deathrattles) is not tuple or any(type(s) is not str or not s for s in self.deathrattles):
            raise ValueError('Pre-entry deathrattles require immutable behavior declarations')
        if type(self.keywords) is not tuple or any(type(k) is not Keyword for k in self.keywords):
            raise ValueError('Pre-entry keywords require immutable typed declarations')
        if any(k not in (Keyword.CHARGE,Keyword.RUSH,Keyword.WINDFURY,Keyword.TAUNT,Keyword.DIVINE_SHIELD,
                Keyword.POISONOUS,Keyword.LIFESTEAL,Keyword.IMMUNE,Keyword.STEALTH,Keyword.REBORN) for k in self.keywords):
            raise ValueError('Composite or contextual pre-entry keyword is unsupported')


@dataclass(frozen=True)
class PrisonEntryMaterial(SummonEntryMaterial):
    prison_death_id: int | None = None
    discard_id: int | None = None

    def __post_init__(self):
        super().__post_init__()
        if (self.prison_death_id is None) == (self.discard_id is None):
            raise ValueError('Prison entry requires exactly one original death or discard')
        _integer(self.prison_death_id if self.prison_death_id is not None else self.discard_id, 'Prison entry origin', 1)
        if any((self.stats, self.deathrattles, self.keywords, self.dormant_turns,
                self.on_summon, self.entry_grant, self.deathrattle_memory)):
            raise ValueError('Prison entry uses only its original printed body')


@dataclass(frozen=True)
class SummonByCard(Effect):
    player_id: int
    materials: tuple[SummonEntryMaterial|PrisonEntryMaterial|CopyEntryMaterial|RecruitEntryMaterial|ResurrectionEntryMaterial|PhysicalReplayEntryMaterial,...]
    cause: SummonCause
    selection: str = 'first'
    position: int | None = None
    weights: tuple[int,...] = ()
    pool_basis: object = None
    capacity: str = 'selection_requires_space'
    producer_link: object = None

    def __post_init__(self):
        _player(self.player_id)
        if type(self.cause) is not SummonCause: raise ValueError('Summon requires explicit card attribution')
        self.cause.__post_init__()
        if type(self.materials) is not tuple or (not self.materials and self.selection!='weighted') or any(type(x) not in (SummonEntryMaterial,PrisonEntryMaterial,CopyEntryMaterial,RecruitEntryMaterial,ResurrectionEntryMaterial,PhysicalReplayEntryMaterial) for x in self.materials):
            raise ValueError('Summon requires a complete ordered entry inventory')
        for x in self.materials: x.__post_init__()
        if len({x.card_id for x in self.materials})!=len(self.materials): raise ValueError('Duplicate summon candidate identity')
        if any(type(x)is CopyEntryMaterial for x in self.materials)and(len(self.materials)!=1 or self.selection!='first'or self.producer_link is not None or self.capacity!='selection_requires_space'):
            raise ValueError('Copy material requires its one original deterministic entry recipe')
        if any(type(x)is RecruitEntryMaterial for x in self.materials):
            from .recruit_summons import RecruitEntryLink
            if len(self.materials)!=1 or self.selection!='first'or self.capacity!='selection_requires_space'or self.producer_link is not None and type(self.producer_link)is not RecruitEntryLink:raise ValueError('Physical recruit material requires its one original first/extra recipe')
        if any(type(x)is ResurrectionEntryMaterial for x in self.materials):
            from .resurrection_summons import ResurrectionEntryLink
            if len(self.materials)!=1 or self.selection!='first'or self.capacity!='selection_requires_space'or self.producer_link is not None and type(self.producer_link)is not ResurrectionEntryLink:raise ValueError('Death material requires its one original entry recipe')
        if self.selection not in ('first','random','weighted'): raise ValueError('Unknown summon selection policy')
        if type(self.weights)is not tuple:raise ValueError('Typed ordered summon weights required')
        for weight in self.weights:_integer(weight,'summon candidate weight',1)
        if self.capacity not in ('selection_requires_space','preselected_attempt'):raise ValueError('Unknown summon capacity policy')
        if self.selection=='weighted':
            from .pool_summons import PoolSummonBasis
            if type(self.pool_basis)is not PoolSummonBasis or len(self.weights)!=len(self.materials):raise ValueError('Weighted summon requires complete original pool/weight rows')
            self.pool_basis.__post_init__()
        elif self.weights or self.pool_basis is not None:raise ValueError('Non-weighted summon cannot borrow pool weights')
        if self.producer_link is not None:
            from .pool_summons import PoolSummonEntryLink
            from .discovery_summons import DiscoverySummonEntryLink
            from .recruit_summons import RecruitEntryLink
            from .resurrection_summons import ResurrectionEntryLink
            from .ordered_summon_groups import GroupSummonEntryLink
            from .mana_worth_summons import ManaWorthEntryLink
            if type(self.producer_link)not in (PoolSummonEntryLink,DiscoverySummonEntryLink,RecruitEntryLink,ResurrectionEntryLink,GroupSummonEntryLink,ManaWorthEntryLink):raise ValueError('Typed original producer link required')
            self.producer_link.__post_init__()
        if self.capacity=='preselected_attempt'and(self.selection!='first'or len(self.materials)!=1 or self.producer_link is None):raise ValueError('Preselected attempt requires one linked original batch item')
        if self.position is not None: _integer(self.position,'summon position',0)


@dataclass(frozen=True)
class GrantSummonQuantity(Effect):
    target_id: int
    spec: SummonQuantitySpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id,'summon quantity carrier',1); _source(self.source_id)
        if type(self.spec) is not SummonQuantitySpec: raise ValueError('Typed summon quantity specification required')
        self.spec.__post_init__()
        if self.expires_turn is not None: _integer(self.expires_turn,'summon quantity expiry',1)


def validate_face(card):
    if (card.kind not in (CardType.HERO,CardType.MINION,CardType.WEAPON) or card.choice_only or card.starship_for or
            Keyword.MAGNETIC in card.keywords or Keyword.STARSHIP_PIECE in card.keywords):
        raise ValueError('Summon quantity requires an ordinary physical carrier')


def validate_material(registry,material,*,allow_colossal=False,allow_pool_entry=False):
    if type(material) is PrisonEntryMaterial:
        from .prison_playback import validate_entry_face
        validate_entry_face(registry, material); return
    if type(material) is PhysicalReplayEntryMaterial:
        from .replay_entry_material import validate_material as validate_primary_material
        validate_primary_material(registry, material); return
    if type(material)is ResurrectionEntryMaterial:
        from .resurrection_summons import validate_face
        validate_face(registry,material);return
    if type(material)is RecruitEntryMaterial:
        material.__post_init__()
        from .copy_materials import validate_material as validate_copy_material
        validate_copy_material(registry,material.copy);return
    if type(material)is CopyEntryMaterial:
        from .copy_materials import validate_material as validate_copy_material
        validate_copy_material(registry,material);return
    material.__post_init__(); card=registry.card(material.card_id)
    if material.deathrattle_memory is not None and card.native_deathrattle != material.deathrattle_memory.spec:
        raise ValueError('Seeded copy memory differs from its actual native minion declaration')
    if (card.kind!=CardType.MINION or card.choice_only or card.starship_for or card.colossal and not allow_colossal or
            not allow_pool_entry and (Keyword.MAGNETIC in card.keywords or Keyword.STARSHIP_PIECE in card.keywords)):
        raise ValueError('This entry profile requires an ordinary non-composite minion')
    # Random generation can select a printed Colossal (for example FIR_907 at
    # six mana selects CATA_139). Delivery already delegates each new body to
    # colossal.enter_minion; keep its ordinary plain recipe instead of pruning
    # the candidate or routing through a different stored/copy summon profile.
    if card.colossal and (material.stats is not None or material.deathrattles or
            material.dormant_turns is not None or material.on_summon is not None):
        raise ValueError('Attributed Colossal entry requires plain material or its supported pool keywords')
    if card.colossal:
        from .pools import validate_pool_entry_keywords
        validate_pool_entry_keywords(material.keywords)
    if material.dormant_turns is not None and card.permanent_dormancy:
        raise ValueError('Forced timed entry for a permanent dormant carrier is unsupported')
    for s in material.deathrattles: registry.behavior(s)
    if material.on_summon is not None:registry.behavior(material.on_summon)


def validate_cause(state,registry,cause,*,closed=False,original_cast_event=None):
    cause.__post_init__(); validate_allocation(state,registry,cause.source,closed=closed)
    if cause.turn>state.turn or cause.action>state.action_number: raise ValueError('Future summon cause')
    if cause.cast_id is not None:
        if original_cast_event is not None:
            from .spell_casts import accepted_fact_id
            event=original_cast_event
            if (not closed or accepted_fact_id(event)!=cause.cast_id or
                    (event.source_id,event.player_id)!=(cause.source.entity_id,cause.player_id) or
                    event.action>cause.action or
                    registry.card(cause.cast_card_id).kind!=CardType.SPELL):
                raise ValueError('Summon cause differs from its original accepted cast event')
            return
        cast=next((c for c in state.cast_history if c.id==cause.cast_id),None)
        if cast is None and closed:
            if cause.cast_id>=state.next_cast_id or registry.card(cause.cast_card_id).kind!=CardType.SPELL:
                raise ValueError('Unknown/future compact original summon cast')
            return
        if (cast is None or (cast.source_id,cast.player_id,cast.card_id)!=(cause.source.entity_id,cause.player_id,cause.cast_card_id)):
            raise ValueError('Summon cause differs from its actual cast')


def validate_grant(state,registry,effect):
    effect.__post_init__()
    e=state.entities.get(effect.target_id)
    if e is None or effect.source_id is not None and effect.source_id not in state.entities:
        raise ValueError('Unknown summon quantity reference')
    validate_face(registry.card(e.card_id))
    if e.components: raise ValueError('Composite summon quantity carrier is unsupported')
    if effect.expires_turn is not None and effect.expires_turn<state.turn: raise ValueError('Expired summon quantity grant')


def grant(r,effect):
    validate_grant(r.state,r.registry,effect); e=r.state.entities[effect.target_id]
    e.abilities.append(AbilityInstance(attachment_id(r.state),'summon_quantity',source_id=effect.source_id,
        summon_quantity=effect.spec,expires_turn=effect.expires_turn))
    r.emit('ability_granted',source_id=effect.source_id,target_id=e.id,ability_id=e.abilities[-1].id,ability_kind='summon_quantity')


@dataclass(frozen=True)
class SummonCarrierFact:
    carrier: SourceAllocationFact
    active: bool
    doomed: bool
    health: int
    durability: int
    abilities: tuple[AbilityInstance,...]

    def __post_init__(self):
        if type(self.carrier) is not SourceAllocationFact: raise ValueError('Typed summon carrier allocation required')
        self.carrier.__post_init__()
        if type(self.active) is not bool or type(self.doomed) is not bool: raise ValueError('Typed summon carrier presence required')
        _integer(self.health,'summon carrier health');_integer(self.durability,'summon carrier durability',0)
        if (type(self.abilities) is not tuple or not self.abilities or
                any(type(a) is not AbilityInstance or a.kind!='summon_quantity' for a in self.abilities) or
                len({a.id for a in self.abilities})!=len(self.abilities)):
            raise ValueError('Complete ordered summon carrier rows required')
        for a in self.abilities: a.__post_init__()


@dataclass(frozen=True)
class SummonQuantityDecision:
    carrier_id: int
    ability_id: int
    eligible: bool

    def __post_init__(self):
        _integer(self.carrier_id,'quantity decision carrier',1);_integer(self.ability_id,'quantity decision ability',1)
        if type(self.eligible) is not bool:raise ValueError('Quantity eligibility must be boolean')


def decisions(facts,cause,turn):
    rows=[];total=1
    for f in facts:
        live=(f.active and not f.doomed and
            ((f.carrier.kind==CardType.MINION and f.carrier.zone==Zone.BOARD and f.health>0) or
             (f.carrier.kind==CardType.HERO and f.carrier.zone==Zone.HERO and f.health>0) or
             (f.carrier.kind==CardType.WEAPON and f.carrier.zone==Zone.WEAPON and f.durability>0)))
        for a in f.abilities:
            spec=a.summon_quantity
            eligible=bool(live and not a.consumed and (a.expires_turn is None or a.expires_turn>=turn) and
                f.carrier.controller==cause.player_id and cause.source.kind in spec.source_kinds)
            rows.append(SummonQuantityDecision(f.carrier.entity_id,a.id,eligible))
            if eligible:total*=spec.factor
    return tuple(rows),total


@dataclass(frozen=True)
class SummonQuantityPlan:
    facts: tuple[SummonCarrierFact,...]
    decisions: tuple[SummonQuantityDecision,...]
    total: int
    turn: int
    action: int
    next_attachment_id: int

    def __post_init__(self):
        if type(self.facts) is not tuple or any(type(x) is not SummonCarrierFact for x in self.facts):raise ValueError('Typed quantity source facts required')
        if type(self.decisions) is not tuple or any(type(x) is not SummonQuantityDecision for x in self.decisions):raise ValueError('Typed quantity decisions required')
        for x in (*self.facts,*self.decisions):x.__post_init__()
        for n in ('total','turn','next_attachment_id'):_integer(getattr(self,n),'summon plan '+n,1)
        _integer(self.action,'summon plan action',0)
        if len({f.carrier.entity_id for f in self.facts})!=len(self.facts):raise ValueError('Duplicate quantity physical carrier')
        all_ids=[a.id for f in self.facts for a in f.abilities]
        if len(set(all_ids))!=len(all_ids) or any(i>=self.next_attachment_id for i in all_ids):raise ValueError('Foreign/future quantity attachment identity')


def capture_plan(state,cause):
    facts=[]
    for e in sorted(state.entities.values(),key=lambda e:e.id):
        rows=tuple(deepcopy(a)for a in e.abilities if a.kind=='summon_quantity')
        if rows:facts.append(SummonCarrierFact(SourceAllocationFact.capture(state,e),bool(e.active),e.doomed,e.health,e.durability,rows))
    rows,total=decisions(tuple(facts),cause,state.turn)
    return SummonQuantityPlan(tuple(facts),rows,total,state.turn,state.action_number,state.next_attachment_id)


@dataclass(frozen=True)
class CardSummonDelivery:
    index: int
    outcome: str
    entity: SourceAllocationFact | None = None
    followup_started: bool = False

    def __post_init__(self):
        if type(self.followup_started)is not bool:raise ValueError('Recruit followup acceptance requires bool')
        _integer(self.index,'summon delivery index',0)
        if self.outcome not in ('delivered','board_full'):raise ValueError('Unknown summon delivery outcome')
        if (self.outcome=='delivered')!=(self.entity is not None):raise ValueError('Incomplete actual summon delivery identity')
        if self.entity is not None:self.entity.__post_init__()
        if self.followup_started and self.entity is None:raise ValueError('Unsuccessful delivery cannot accept a followup')


@dataclass(frozen=True)
class CardSummonRecord:
    id: int
    event_cursor: int
    request: SummonByCard
    plan: SummonQuantityPlan
    selected: int | None
    rng_before: tuple
    rng_after: tuple
    deliveries: tuple[CardSummonDelivery,...] = ()
    status: str = 'active'
    entry_strength: AcceptedEntryStrength | None = None

    def __post_init__(self):
        _integer(self.id,'summon root',1)
        _integer(self.event_cursor,'summon original event cursor',0)
        if type(self.request) is not SummonByCard or type(self.plan) is not SummonQuantityPlan:raise ValueError('Typed card summon root required')
        self.request.__post_init__();self.plan.__post_init__()
        if self.entry_strength is not None:
            if type(self.entry_strength)is not AcceptedEntryStrength:raise ValueError('Typed selected entry-strength facts required')
            self.entry_strength.__post_init__()
        if self.selected is not None:_integer(self.selected,'selected summon material',0)
        if self.selected is not None and self.selected>=len(self.request.materials):raise ValueError('Unknown selected summon material')
        if type(self.deliveries) is not tuple or any(type(x) is not CardSummonDelivery for x in self.deliveries):raise ValueError('Typed actual delivery prefix required')
        for x in self.deliveries:x.__post_init__()
        if [x.index for x in self.deliveries]!=list(range(len(self.deliveries))) or len(self.deliveries)>self.plan.total:raise ValueError('Cropped/reordered summon delivery prefix')
        if self.selected is None and self.deliveries:raise ValueError('Unselected summon cannot deliver')
        material=None if self.selected is None else self.request.materials[self.selected]
        has_followup=type(material)in(RecruitEntryMaterial,CopyEntryMaterial,SummonEntryMaterial) and material.on_summon is not None
        if not has_followup and any(d.followup_started for d in self.deliveries):raise ValueError('Non-recruit delivery borrowed a followup acceptance')
        if has_followup and any(d.outcome=='delivered' and not d.followup_started for d in self.deliveries[:-1]):
            raise ValueError('Recruit advanced before the previous physical followup')
        if self.status not in ('active','completed','skipped','interrupted'):raise ValueError('Unknown summon root status')
        if self.status=='completed' and (self.selected is None or len(self.deliveries)!=self.plan.total):raise ValueError('Incomplete completed summon root')
        if self.status=='completed' and has_followup and any(d.outcome=='delivered' and not d.followup_started for d in self.deliveries):
            raise ValueError('Completed recruit lost a physical followup')
        if self.status=='skipped' and self.selected is not None:raise ValueError('Selected summon cannot skip')
        from .model import validate_end_turn_rng
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        local=Random();local.setstate(self.rng_before)
        expected=None if self.selected is None else select_material(local,self.request)
        if expected!=self.selected or local.getstate()!=self.rng_after:raise ValueError('Summon selection/RNG is inconsistent with original candidate order')


@dataclass(frozen=True)
class DeliverCardSummon(Effect):
    root_id: int
    index: int
    def __post_init__(self):_integer(self.root_id,'delivery summon root',1);_integer(self.index,'delivery index',0)


@dataclass(frozen=True)
class FinishCardSummon(Effect):
    root_id: int
    def __post_init__(self):_integer(self.root_id,'finish summon root',1)


def record(state,root_id):
    value=next((x for x in state.card_summon_history if x.id==root_id),None)
    if value is None:raise ResolutionError('Unknown actual card summon root')
    return value


def update(state,old,**changes):
    state.card_summon_history[state.card_summon_history.index(old)]=replace(old,**changes)


def select_material(rng,request):
    if request.selection=='random':return rng.randrange(len(request.materials))
    if request.selection=='weighted':
        from .pool_summons import choose_weighted
        return choose_weighted(rng,request.materials,request.weights)
    return 0


def validate_request(state,registry,request,*,closed=False,original_cast_event=None):
    validate_cause(state,registry,request.cause,closed=closed,original_cast_event=original_cast_event)
    from .pool_summons import PoolSummonEntryLink,validate_entry_recipe,validate_weighted_request
    pooled=request.selection=='weighted' or type(request.producer_link)is PoolSummonEntryLink
    if request.selection=='weighted':validate_weighted_request(state,registry,request,closed=closed)
    elif type(request.producer_link)is PoolSummonEntryLink:validate_entry_recipe(state,request,closed=closed)
    for material in request.materials:
        if type(material) is PrisonEntryMaterial:
            from .prison_playback import validate_entry
            validate_entry(state, registry, material)
        if type(material) is PhysicalReplayEntryMaterial:
            from .replay_entry_material import validate_scope
            validate_scope(state, registry, request, material)
        validate_material(registry,material,allow_colossal=type(material)is SummonEntryMaterial,allow_pool_entry=pooled)
        if type(material)is SummonEntryMaterial and material.entry_grant is not None and not pooled:
            raise ValueError('Pool entry Attack grant requires its complete original pool recipe')
        if type(material)is SummonEntryMaterial and material.deathrattle_memory is not None:
            from .deathrattle_memory import validate_copy_memory
            validate_copy_memory(state, registry, material.deathrattle_memory, closed=closed)
            if material.deathrattle_memory.summon_copy.origin.controller != request.cause.player_id:
                raise ValueError('Seeded copy memory lost its original friendly minion selection')
        if type(material)is CopyEntryMaterial:
            from .copy_materials import validate_scope as validate_copy_scope
            validate_copy_scope(state,registry,material,closed=closed)
            if material.profile=='discard_summon_copy' and (
                    request.player_id!=material.discard.player_id or
                    request.cause.player_id!=request.player_id or
                    (request.cause.turn,request.cause.action)!=(material.discard.turn,material.discard.action)):
                raise ValueError('Discard summon changed its original recipient or causing window')
            if material.minion_grant is not None and material.grant_source_id!=request.cause.source.entity_id:
                raise ValueError('Copy entry grant source differs from the original summon cause')
        elif type(material)is RecruitEntryMaterial:
            from .recruit_summons import validate_material as validate_recruit_material
            validate_recruit_material(state,registry,material,closed=closed)
            from .minion_hand_swaps import validate_recipe as validate_swap_recipe
            validate_swap_recipe(request,material)
        elif type(material)is ResurrectionEntryMaterial:
            from .resurrection_summons import validate_material as validate_death_material
            validate_death_material(state,registry,material,closed=closed)
    from .mana_worth_summons import ManaWorthEntryLink,validate_recipe as validate_budget_recipe
    if type(request.producer_link) is ManaWorthEntryLink:validate_budget_recipe(request)


def accept(r,effect):
    effect.__post_init__();validate_request(r.state,r.registry,effect)
    plan=capture_plan(r.state,effect.cause)
    if plan.total>r.rules.max_resolution_steps:raise ResolutionLimitExceeded('Summon quantity exceeds resolution budget')
    before=r.game._rng.getstate()
    from .minion_hand_swaps import entry_has_space
    selected=None if not effect.materials or effect.capacity=='selection_requires_space'and not entry_has_space(r,effect) else select_material(r.game._rng,effect)
    from .entry_strength import capture as capture_entry_strength
    root=CardSummonRecord(r.state.next_card_summon_id,len(r.game._events),effect,plan,selected,before,r.game._rng.getstate(),
        entry_strength=capture_entry_strength(r.state,r.registry,effect,selected))
    r.state.next_card_summon_id+=1;r.state.card_summon_history.append(root)
    r.emit('card_summon_accepted',source_id=effect.cause.source.entity_id,player_id=effect.player_id,amount=plan.total,root_id=root.id,root=root_json(root),_capture=False)
    return (DeliverCardSummon(root.id,0),FinishCardSummon(root.id))


def deliver(r,effect):
    root=record(r.state,effect.root_id)
    if root.status!='active' or effect.index!=len(root.deliveries):raise ResolutionError('Out-of-order card summon delivery')
    if pending_followup(root):raise ResolutionError('Extra delivery preceded original physical followup')
    if root.selected is None:
        if effect.index:raise ResolutionError('Skipped root has no extra deliveries')
        if root.request.materials and type(root.request.materials[0])is ResurrectionEntryMaterial:
            from .resurrection_summons import failed
            failed(r,root.request.materials[0],root.request.player_id)
        elif root.request.materials and type(root.request.materials[0])is RecruitEntryMaterial:pass
        elif root.request.materials and type(root.request.materials[0])is CopyEntryMaterial:
            material=root.request.materials[0]
            if material.profile in ('board_copy','discard_summon_copy'):r.emit('summon_failed',player_id=root.request.player_id,card_id=material.card_id,reason='board_full')
        else:r.emit('random_choice_skipped',source_id=root.request.cause.source.entity_id,reason='empty_pool'if not root.request.materials else 'board_full')
        return ()
    material=root.request.materials[root.selected];entity=None
    position=None if root.request.position is None else root.request.position+effect.index
    from .minion_hand_swaps import entry_has_space
    if not entry_has_space(r,root.request,effect.index):
        if type(material)is ResurrectionEntryMaterial:
            from .resurrection_summons import failed
            failed(r,material,root.request.player_id)
        else:r.emit('summon_failed',player_id=root.request.player_id,card_id=material.card_id,reason='board_full')
        result=CardSummonDelivery(effect.index,'board_full')
    else:
        if type(material)is RecruitEntryMaterial and effect.index==0:
            from .recruit_summons import first_body
            entity=first_body(r,material,root.request.player_id,position)
        elif type(material)is ResurrectionEntryMaterial:
            from .resurrection_summons import create_body
            entity=create_body(r,material,root.request.player_id,position)
        else:
            components=()
            if type(material)is CopyEntryMaterial:components=material.components
            if type(material)is RecruitEntryMaterial:components=material.copy.components
            if type(material) is PrisonEntryMaterial and material.discard_id is not None:
                components=r.state.discard_history[material.discard_id-1].components
            if type(material) is PhysicalReplayEntryMaterial:
                from .offered_card_execution import components_for_entry
                components=components_for_entry(r.state,r.registry,material)
            entity=r.create_entity(root.request.player_id,material.card_id,Zone.BOARD,position,components=components,
            entry_herald_count=None if root.entry_strength is None else root.entry_strength.count,
            entry_dormant_turns=material.dormant_turns if type(material)is SummonEntryMaterial else None)
        if type(material) is PhysicalReplayEntryMaterial:
            from .offered_card_execution import apply_entry
            apply_entry(r,material,entity)
            entity.origin_entity_id = root.request.cause.source.entity_id
            if effect.index == 0:
                from .adapt_memory import install_generated
                install_generated(r, root, entity)
        if type(material)is ResurrectionEntryMaterial:
            from .resurrection_summons import apply as apply_death_material
            apply_death_material(r,material,entity,root.id,effect.index)
        elif type(material)is RecruitEntryMaterial:
            if effect.index>0:
                from .copy_materials import apply as apply_copy_material
                apply_copy_material(r,material.copy,entity)
        elif type(material)is CopyEntryMaterial:
            from .copy_materials import apply as apply_copy_material
            apply_copy_material(r,material,entity)
        else:
            from .lifecycle import apply_summon_stats,refresh_entity
            apply_summon_stats(r.state,entity,material.stats)
            if type(material)is SummonEntryMaterial and material.deathrattle_memory is not None:
                entity.abilities = [replace(a, deathrattle_memory=material.deathrattle_memory)
                    if a.deathrattle_memory is not None and a.deathrattle_memory.spec == material.deathrattle_memory.spec else a
                    for a in entity.abilities]
            for behavior in material.deathrattles:
                entity.abilities.append(AbilityInstance(attachment_id(r.state),'deathrattle',source_id=root.request.cause.source.entity_id,
                    behavior_id=behavior,deathrattle_grant_card_id=root.request.cause.source.card_id))
            for keyword in material.keywords:
                entity.abilities.append(AbilityInstance(attachment_id(r.state),'keyword',source_id=root.request.cause.source.entity_id,keyword=keyword))
            if type(material)is SummonEntryMaterial and material.entry_grant is not None:
                from types import SimpleNamespace
                from .card_creation import install
                install(r.state,entity,SimpleNamespace(spell_repeat=None,minion_grant=material.entry_grant,
                    source_id=root.request.cause.source.entity_id),resolver=r)
            refresh_entity(entity);r.refresh_auras()
        if type(material) is PrisonEntryMaterial:
            from .prison_playback import seed_entry
            seed_entry(r, material, entity)
        result=CardSummonDelivery(effect.index,'delivered',SourceAllocationFact.capture(r.state,entity))
    update(r.state,root,deliveries=(*root.deliveries,result))
    continuation=()
    if entity is not None:
        if type(material)is ResurrectionEntryMaterial:
            from .resurrection_summons import enter as enter_death
            continuation=tuple(enter_death(r,material,entity))
        elif type(material)is RecruitEntryMaterial:
            from .colossal import enter_minion
            if effect.index==0 and material.swap_minion is not None:
                r.emit('card_returned',target_id=material.swap_minion.entity_id,player_id=material.reference.player_id)
            continuation=tuple(enter_minion(r,entity,'stored'))
            if material.on_summon is not None:
                from .recruit_summons import ContinueRecruitedMinion
                from .copy_followups import ContinueCopiedMinion
                from .sacrifice import MinionReference
                continuation=(*continuation,ContinueRecruitedMinion(root.id,effect.index,
                    MinionReference.capture(entity),material.on_summon))
        elif type(material)is CopyEntryMaterial:
            from .copy_materials import enter as enter_copy
            continuation=tuple(enter_copy(r,material,entity))
            if material.on_summon is not None:
                from .copy_followups import ContinueCopiedMinion
                from .sacrifice import MinionReference
                continuation=(*continuation,ContinueCopiedMinion(root.id,effect.index,MinionReference.capture(entity),material.on_summon))
        else:
            from .colossal import enter_minion
            continuation=tuple(enter_minion(r,entity,'summon'))
            if type(material)is SummonEntryMaterial and material.on_summon is not None:
                from .named_summon_followups import ContinueNamedMinion
                from .model import BoardPresenceReference
                continuation=(*continuation,ContinueNamedMinion(root.id,effect.index,
                    BoardPresenceReference.capture(r.state,entity.id),material.on_summon))
    if effect.index+1<root.plan.total:continuation=(*continuation,DeliverCardSummon(root.id,effect.index+1))
    return continuation


def finish(r,effect):
    root=record(r.state,effect.root_id)
    if root.status!='active' or root.selected is not None and len(root.deliveries)!=root.plan.total:raise ResolutionError('Incomplete card summon Finish')
    if pending_followup(root):raise ResolutionError('Recruit Finish preceded physical followup')
    closed=replace(root,status='skipped' if root.selected is None else 'completed')
    update(r.state,root,status=closed.status)
    emit_closed(r,closed)


def interrupt(r):
    for root in tuple(r.state.card_summon_history):
        if root.status=='active':
            closed=replace(root,status='interrupted')
            update(r.state,root,status=closed.status);emit_closed(r,closed)


def root_json(root):
    return json.dumps(asdict(root),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def emit_closed(r,root):
    r.emit('card_summon_finished',root_id=root.id,amount=len(root.deliveries),
        source_id=root.request.cause.source.entity_id,player_id=root.request.player_id,root=root_json(root),_capture=False)


def _has_quantity_source(state):
    return any(a.kind=='summon_quantity' and not a.consumed for e in state.entities.values() for a in e.abilities if e.active)


def card_summon(context,player_id,card_id,position=None,stats=None):
    """Explicit old card producer adapter, preserving its no-quantity path.

    The caller supplies the actual behavior context; never infer a causing
    card from the recipient, the current player or an observed trigger event.
    When legacy Summon would be ambiguous, use the existing attributed root.
    """
    from .effects import Summon
    ordinary=Summon(player_id,card_id,position,stats)
    if not _has_quantity_source(context.state):return ordinary
    return SummonByCard(player_id,(SummonEntryMaterial(card_id,stats),),SummonCause.capture(context),position=position)


def reject_ambiguous(r):
    if _has_quantity_source(r.state):
        raise ResolutionError('Unattributed summon with a quantity source is unsupported; use typed SummonByCard')


def validate_record(state,registry,root,*,closed=False,original_cast_event=None):
    root.__post_init__();validate_request(state,registry,root.request,closed=closed,original_cast_event=original_cast_event)
    from .entry_strength import validate as validate_entry_strength
    validate_entry_strength(state,registry,root,closed=closed)
    if root.request.producer_link is not None:
        from .pool_summons import PoolSummonEntryLink,validate_link as validate_pool_link
        from .discovery_summons import DiscoverySummonEntryLink,validate_link as validate_discovery_link
        from .ordered_summon_groups import GroupSummonEntryLink
        from .mana_worth_summons import ManaWorthEntryLink,validate_link as validate_budget_link
        if type(root.request.producer_link)is PoolSummonEntryLink:validate_pool_link(state,root,closed=closed)
        elif type(root.request.producer_link)is ManaWorthEntryLink:validate_budget_link(state,registry,root,closed=closed)
        elif type(root.request.producer_link)is DiscoverySummonEntryLink:validate_discovery_link(state,root,closed=closed)
        elif type(root.request.producer_link)is GroupSummonEntryLink:
            from .ordered_group_batches import validate_link as validate_group_link
            validate_group_link(state,root,closed=closed)
        elif type(root.request.producer_link)is ResurrectionEntryLink:
            from .resurrection_summons import validate_link as validate_death_link
            validate_death_link(state,root,closed=closed)
        else:
            from .recruit_summons import validate_link as validate_recruit_link
            validate_recruit_link(state,root,closed=closed)
    plan=root.plan
    for material in root.request.materials:
        if type(material)is ResurrectionEntryMaterial and(material.captured_turn,material.captured_action,material.next_attachment_id)!=(plan.turn,plan.action,plan.next_attachment_id):raise ValueError('Death material is not from actual entry acceptance window')
        copy_material=material.copy if type(material)is RecruitEntryMaterial else material
        if type(copy_material)is CopyEntryMaterial:
            if copy_material.profile in ('discard_summon_copy','remembered_copy','remembered_hand_copy'):
                if (copy_material.captured_turn>plan.turn or copy_material.captured_action>plan.action or
                        copy_material.next_attachment_id>plan.next_attachment_id):
                    raise ValueError('Original discarded material is newer than its summon acceptance')
            elif (copy_material.captured_turn,copy_material.captured_action,copy_material.next_attachment_id)!=(plan.turn,plan.action,plan.next_attachment_id):
                raise ValueError('Copy material is not from its actual entry acceptance window')
    if plan.turn>state.turn or plan.action>state.action_number or plan.next_attachment_id>state.next_attachment_id:raise ValueError('Future summon acceptance plan')
    if root.request.cause.turn>plan.turn or root.request.cause.action>plan.action:raise ValueError('Cause is newer than its accepted summon plan')
    if [f.carrier.entity_id for f in plan.facts]!=sorted(f.carrier.entity_id for f in plan.facts):raise ValueError('Reordered original summon carrier inventory')
    if not closed and root.status=='interrupted' and state.status=='playing':raise ValueError('Playing summon cannot be terminal interrupted')
    for f in plan.facts:
        validate_allocation(state,registry,f.carrier,closed=closed);validate_face(registry.card(f.carrier.card_id))
        for a in f.abilities:
            if a.source_id is not None and a.source_id>=f.carrier.next_entity_id:raise ValueError('Future quantity grant source')
            if a.origin=='printed' and (a.source_id!=f.carrier.entity_id or a.summon_quantity not in registry.card(f.carrier.card_id).summon_quantities):
                raise ValueError('Quantity original printed row does not match its registered face')
    expected,total=decisions(plan.facts,root.request.cause,plan.turn)
    if expected!=plan.decisions or total!=plan.total:raise ValueError('Quantity plan differs from complete original source facts')
    for d in root.deliveries:
        if d.entity is not None:
            validate_allocation(state,registry,d.entity,closed=closed)
            if type(root.request.materials[root.selected])is ResurrectionEntryMaterial:
                from .resurrection_summons import validate_delivery as validate_death_delivery
                validate_death_delivery(state,root.request.materials[root.selected],d,root.request.player_id,closed=closed)
            elif type(root.request.materials[root.selected])is RecruitEntryMaterial:
                from .recruit_summons import validate_delivery
                validate_delivery(root.request.materials[root.selected],d,root.request.player_id)
            elif (d.entity.card_id,d.entity.owner,d.entity.controller,d.entity.kind,d.entity.zone)!=(root.request.materials[root.selected].card_id,root.request.player_id,root.request.player_id,CardType.MINION,Zone.BOARD):
                raise ValueError('Summon result differs from selected entry and recipient')
    identities=[d.entity.entity_id for d in root.deliveries if d.entity is not None]
    if len(set(identities))!=len(identities):raise ValueError('Repeated physical summon delivery identity')


def validate_history(state,registry):
    _integer(state.next_card_summon_id,'next card summon id',1)
    if type(state.card_summon_history) is not list:raise ValueError('Card summon history must be a list')
    ids=[]
    for root in state.card_summon_history:
        if type(root) is not CardSummonRecord:raise ValueError('Typed card summon history required')
        validate_record(state,registry,root);ids.append(root.id)
    if ids!=sorted(set(ids)) or any(i>=state.next_card_summon_id for i in ids):raise ValueError('Unknown/future summon root allocator')
    for e in state.entities.values():
        rows=tuple(a for a in e.abilities if a.kind=='summon_quantity')
        if rows:
            validate_face(registry.card(e.card_id))
            if e.components:raise ValueError('Composite quantity carrier is unsupported')
            for a in rows:
                if a.origin=='printed' and (a.summon_quantity not in registry.card(e.card_id).summon_quantities or a.source_id!=e.id):
                    raise ValueError('Printed quantity source differs from current card')


def walk_work(value):
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    if type(value) in (GameState,RuleContext,PaidHandChoiceBoundaryProof):return
    if isinstance(value,Effect):yield value
    if is_dataclass(value):
        for f in fields(value):yield from walk_work(getattr(value,f.name))
    elif type(value) in (tuple,list):
        for x in value:yield from walk_work(x)


def reject_choice_control(options):
    from .recruit_summons import ContinueRecruitedMinion
    from .copy_followups import ContinueCopiedMinion
    from .named_summon_followups import ContinueNamedMinion
    from .mana_worth_summons import ContinueManaWorth
    if any(type(x) in (DeliverCardSummon,FinishCardSummon,ContinueRecruitedMinion,ContinueCopiedMinion,ContinueNamedMinion,ContinueManaWorth) for x in walk_work(options)):
        raise ValueError('Choice branches cannot inject summon control work')


def validate_frame_references(state,registry,value):
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item,scope,depth):
        if depth>FrameCodec.MAX_DEPTH:raise ValueError('Summon frame exceeds depth limit')
        from .mana_worth_summons import ContinueManaWorth,validate_control as validate_budget_control
        if type(item) is ContinueManaWorth:
            validate_budget_control(scope,registry,item);return
        if type(item) is SummonByCard:
            validate_request(scope,registry,item)
            return
        from .effects import CopyMinion
        from .summon_sources import CopyStoredMinion
        if type(item)in(CopyMinion,CopyStoredMinion)and item.cause is not None:
            from .copy_materials import validate_effect_scope
            validate_effect_scope(scope,registry,item);return
        if type(item) is GrantSummonQuantity:
            validate_grant(scope,registry,item);return
        from .recruit_summons import ContinueRecruitedMinion,followup_record
        from .copy_followups import ContinueCopiedMinion
        from .named_summon_followups import ContinueNamedMinion,followup_record as named_followup_record
        if type(item)is ContinueNamedMinion:
            child,delivery=named_followup_record(scope,registry,item)
            if child.status!='active' or delivery.followup_started:raise ValueError('Stale original named followup')
            return
        if type(item)is ContinueRecruitedMinion:
            child,delivery=followup_record(scope,registry,item)
            if child.status!='active' or delivery.followup_started:raise ValueError('Stale original physical followup')
            return
        if type(item) in (DeliverCardSummon,FinishCardSummon):
            if record(scope,item.root_id).status!='active':raise ValueError('Stale/injected summon control work')
            return
        if type(item) is RuleContext:
            for f in fields(item):
                if f.name!='state':visit(getattr(item,f.name),item.state,depth+1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            validate_queue(item.state,registry,item.work)
            visit(item.work,item.state,depth+1);return
        if type(item) is GameState:return
        if type(item) in (tuple,list):
            for child in item:visit(child,scope,depth+1)
        elif is_dataclass(item):
            for f in fields(item):visit(getattr(item,f.name),scope,depth+1)
    visit(value,state,0)


def pending_followup(root):
    if root.selected is None or not root.deliveries:return False
    material=root.request.materials[root.selected];delivery=root.deliveries[-1]
    return type(material)in(RecruitEntryMaterial,CopyEntryMaterial,SummonEntryMaterial) and material.on_summon is not None and (
        delivery.outcome=='delivered' and not delivery.followup_started)


def validate_queue(current,registry,queue):
    from .recruit_summons import ContinueRecruitedMinion,followup_record
    from .copy_followups import ContinueCopiedMinion
    from .named_summon_followups import ContinueNamedMinion,followup_record as named_followup_record
    control_types=(DeliverCardSummon,FinishCardSummon,ContinueRecruitedMinion,ContinueCopiedMinion,ContinueNamedMinion)
    work=list(walk_work(queue))
    from .mana_worth_summons import validate_queue as validate_budget_queue
    validate_budget_queue(current,registry,work)
    for item in work:
        if type(item) is SummonByCard:
            validate_request(current,registry,item)
        if type(item) is GrantSummonQuantity:validate_grant(current,registry,item)
        if type(item) in control_types:
            if record(current,item.root_id).status!='active':raise ValueError('Stale/injected summon control work')
    for root in current.card_summon_history:
        controls=[x for x in work if type(x) in control_types and x.root_id==root.id]
        if root.status!='active':
            if controls:raise ValueError('Completed summon retains control work')
            continue
        tail=[type(x) for x in controls]
        expected=[]
        if pending_followup(root):
            material=root.request.materials[root.selected]
            expected=[ContinueCopiedMinion if type(material)is CopyEntryMaterial else
                ContinueNamedMinion if type(material)is SummonEntryMaterial else ContinueRecruitedMinion]
        if root.selected is not None and len(root.deliveries)<root.plan.total:expected.append(DeliverCardSummon)
        expected.append(FinishCardSummon)
        if tail!=expected:raise ValueError('Incomplete/duplicated accepted summon continuation')
        for item in controls:
            if type(item)is ContinueNamedMinion:
                child,delivery=named_followup_record(current,registry,item)
                if delivery.index!=len(root.deliveries)-1 or delivery.followup_started:raise ValueError('Wrong original named followup continuation index')
            if type(item) is DeliverCardSummon and item.index!=len(root.deliveries):raise ValueError('Wrong accepted summon continuation index')
            if type(item)is ContinueRecruitedMinion:
                child,delivery=followup_record(current,registry,item)
                if delivery.index!=len(root.deliveries)-1 or delivery.followup_started:raise ValueError('Wrong original followup continuation index')
            if type(item)is ContinueCopiedMinion:
                from .copy_followups import followup_record as copy_followup_record
                child,delivery=copy_followup_record(current,registry,item)
                if delivery.index!=len(root.deliveries)-1 or delivery.followup_started:raise ValueError('Wrong original copy followup continuation index')


def validate_boundary(game):
    from .copy_followups import validate_followup_events
    validate_followup_events(game)
    from .recruit_summons import ContinueRecruitedMinion
    from .copy_followups import ContinueCopiedMinion
    from .named_summon_followups import ContinueNamedMinion
    from .mana_worth_summons import ContinueManaWorth
    current=game._state;frame=game._frame
    queue=(*frame.prefix,*frame.continuation) if frame is not None else ()
    validate_queue(current,game.registry,queue)
    if frame is not None:
        reject_choice_control(frame.options)
        validate_frame_references(current,game.registry,frame)
        original=frame.paid_hand_choice_boundary
        if current.card_summon_history!=original.state.card_summon_history:
            raise ValueError('Summon roots differ from their complete original choice boundary')
        controls=lambda work:tuple(x for x in work if type(x) in (DeliverCardSummon,FinishCardSummon,ContinueRecruitedMinion,ContinueCopiedMinion,ContinueNamedMinion,ContinueManaWorth))
        if controls(queue)!=controls(original.work):
            raise ValueError('Summon continuation differs from complete original owed work')


def validate_closed_events(game):
    """Outer committed log only; captured earlier states use their own scope.

    Compact receipts check internal consistency. They do not authenticate an
    unsigned source, a wholly replaced candidate pool or original cast facts
    deleted by a genuine later Retry.
    """
    state,registry,events=game._state,game.registry,game._events
    current={r.id:r for r in state.card_summon_history};accepted={};closed={};cast_events={}
    for event in events:
        if event.kind=='spell_cast_accepted':
            from .spell_casts import accepted_fact_id
            cast_events[(accepted_fact_id(event),event.source_id,event.player_id)]=event
        if event.kind not in ('card_summon_accepted','card_summon_finished'):continue
        data=dict(event.data)
        if set(data)!= {'root','root_id'} or type(data['root']) is not str:
            raise ValueError('Summon event requires a complete original compact receipt')
        root=from_dict(CardSummonRecord,json.loads(data['root']))
        cause=root.request.cause
        original_cast=cast_events.get((cause.cast_id,cause.source.entity_id,cause.player_id))if cause.cast_id is not None else None
        if cause.cast_id is not None and original_cast is None:
            raise ValueError('Summon receipt lost its original accepted cast event')
        if original_cast is not None and original_cast.sequence>root.event_cursor:
            raise ValueError('Summon borrowed a cast accepted after its original window')
        validate_record(state,registry,root,closed=True,original_cast_event=original_cast)
        if (data['root_id']!=root.id or root.id>=state.next_card_summon_id or
            (event.source_id,event.player_id)!=(root.request.cause.source.entity_id,root.request.player_id) or
            root.plan.action>event.action or root.event_cursor>=event.sequence):
            raise ValueError('Summon event differs from its original identity and event domain')
        if event.kind=='card_summon_accepted':
            if (root.id in accepted or root.status!='active' or root.deliveries or
                root.event_cursor!=event.sequence-1 or event.amount!=root.plan.total):
                raise ValueError('Changed/duplicated original summon acceptance')
            accepted[root.id]=root
        else:
            if (root.id not in accepted or root.id in closed or root.status=='active' or
                event.amount!=len(root.deliveries) or replace(root,deliveries=(),status='active')!=accepted[root.id]):
                raise ValueError('Closing summon differs from complete original acceptance')
            closed[root.id]=root
        if root.id not in current and not any(e.kind=='timeline_rewound' and e.sequence>event.sequence and
                type(dict(e.data).get('event_start')) is int and dict(e.data)['event_start']<=root.event_cursor for e in events):
            raise ValueError('Original summon disappeared without actual later Retry')
    if list(accepted)!=sorted(accepted):raise ValueError('Reordered summon acceptance identities')
    for root in current.values():
        if (root.id not in accepted or replace(root,deliveries=(),status='active')!=accepted[root.id] or
            root.status!='active' and closed.get(root.id)!=root or root.status=='active' and root.id in closed):
            raise ValueError('Current summon differs from its complete original event receipts')
    from .named_summon_followups import validate_events as validate_named_followup_events
    validate_named_followup_events(game,{**accepted,**closed,**current})
    from .mana_worth_summons import validate_events as validate_budget_events
    validate_budget_events(state,registry,{**accepted,**closed,**current})


def material_from_dict(value):
    if type(value) is dict and 'prison_death_id' in value:
        return from_dict(PrisonEntryMaterial, value)
    if type(value) is dict and value.get('profile') in ('whole_card_printed_primary_v1', 'whole_card_original_offer_primary_v1'):
        return from_dict(PhysicalReplayEntryMaterial, value)
    if 'death'in value:
        from .resurrection_summons import from_dict as death_from_dict
        return death_from_dict(ResurrectionEntryMaterial,value)
    if 'copy'in value:
        from .recruit_summons import from_dict as recruit_from_dict
        return recruit_from_dict(RecruitEntryMaterial,value)
    if 'profile'in value:
        from .copy_materials import from_dict as copy_from_dict
        return copy_from_dict(CopyEntryMaterial,value)
    return from_dict(SummonEntryMaterial,value)


def from_dict(cls,value):
    from .serialization import _row,_ability_from_dict
    row=_row(value,cls)
    if cls is SummonQuantitySpec:row['source_kinds']=tuple(CardType(k)for k in row['source_kinds'])
    elif cls is SummonCause:row['source']=allocation_from_dict(row['source'])
    elif cls in (SummonEntryMaterial, PrisonEntryMaterial):
        row['stats']=None if row['stats'] is None else SummonStats(**_row(row['stats'],SummonStats))
        row['deathrattles']=tuple(row['deathrattles']);row['keywords']=tuple(Keyword(k)for k in row['keywords'])
        row['entry_grant']=minion_grant_from_dict(row['entry_grant'])
        if row['deathrattle_memory'] is not None:
            from .serialization import deathrattle_memory_from_dict
            row['deathrattle_memory'] = deathrattle_memory_from_dict(row['deathrattle_memory'])
    elif cls is SummonByCard:
        row['cause']=from_dict(SummonCause,row['cause']);row['materials']=tuple(material_from_dict(x)for x in row['materials'])
        row['weights']=tuple(row['weights'])
        from .pool_summons import PoolSummonBasis,PoolSummonEntryLink,from_dict as pool_from_dict
        row['pool_basis']=None if row['pool_basis']is None else pool_from_dict(PoolSummonBasis,row['pool_basis'])
        if row['producer_link']is not None:
            if set(row['producer_link'])=={'budget','remaining','previous_root_id'}:
                from .mana_worth_summons import ManaWorthEntryLink
                row['producer_link']=ManaWorthEntryLink(**row['producer_link'])
            elif set(row['producer_link'])=={'group_id','index'}:
                from .ordered_summon_groups import GroupSummonEntryLink,from_dict as group_from_dict
                row['producer_link']=group_from_dict(GroupSummonEntryLink,row['producer_link'])
            elif set(row['producer_link'])=={'batch_id','index'}:row['producer_link']=pool_from_dict(PoolSummonEntryLink,row['producer_link'])
            elif set(row['producer_link'])=={'resurrection_batch_id','index'}:
                from .resurrection_summons import ResurrectionEntryLink,from_dict as death_from_dict
                row['producer_link']=death_from_dict(ResurrectionEntryLink,row['producer_link'])
            elif set(row['producer_link'])=={'recruit_id','index'}:
                from .recruit_summons import RecruitEntryLink,from_dict as recruit_from_dict
                row['producer_link']=recruit_from_dict(RecruitEntryLink,row['producer_link'])
            else:
                from .discovery_summons import DiscoverySummonEntryLink,from_dict as discovery_from_dict
                row['producer_link']=discovery_from_dict(DiscoverySummonEntryLink,row['producer_link'])
    elif cls is SummonCarrierFact:
        row['carrier']=allocation_from_dict(row['carrier']);row['abilities']=tuple(_ability_from_dict(x)for x in row['abilities'])
    elif cls is SummonQuantityPlan:
        row['facts']=tuple(from_dict(SummonCarrierFact,x)for x in row['facts']);row['decisions']=tuple(from_dict(SummonQuantityDecision,x)for x in row['decisions'])
    elif cls is CardSummonDelivery:row['entity']=allocation_from_dict(row['entity'])
    elif cls is CardSummonRecord:
        from .serialization import end_turn_rng_from_json
        row['request']=from_dict(SummonByCard,row['request']);row['plan']=from_dict(SummonQuantityPlan,row['plan'])
        from .entry_strength import from_dict as entry_strength_from_dict
        row['entry_strength']=entry_strength_from_dict(row['entry_strength'])
        row['deliveries']=tuple(from_dict(CardSummonDelivery,x)for x in row['deliveries'])
        row['rng_before']=end_turn_rng_from_json(row['rng_before']);row['rng_after']=end_turn_rng_from_json(row['rng_after'])
    return cls(**row)


def rows_from_dict(value):
    if type(value['card_summon_history']) is not list:raise ValueError('Card summon history must be a list')
    value['card_summon_history']=[from_dict(CardSummonRecord,x)for x in value['card_summon_history']]


def register(mechanics):
    for cls in (AcceptedEntryStrength,SummonCause,SummonEntryMaterial,PrisonEntryMaterial,PhysicalReplayEntryMaterial,SummonCarrierFact,SummonQuantityDecision,SummonQuantityPlan,CardSummonDelivery,CardSummonRecord):
        mechanics.register_payload_type(cls)
    for kind,handler in ((SummonByCard,accept),(GrantSummonQuantity,grant),(DeliverCardSummon,deliver),(FinishCardSummon,finish)):
        mechanics.register(kind,handler)
    from .named_summon_followups import register as register_named_followups
    register_named_followups(mechanics)
