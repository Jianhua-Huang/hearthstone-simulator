"""Shared current Dragon qualification and finite native automatic-repeat plans."""
from copy import deepcopy
from dataclasses import dataclass
from .effects import _player
from .model import (AbilityInstance,CardType,CostQuoteFact,Enchantment,RecipientMetadataFilter,RepeatMatchSpec,
    RepeatSourceEligibility,SpellRepeatSpec,SpellSchool,Zone)
from .allocation_facts import SourceAllocationFact,validate_allocation

PROFILE='repeat.witness.current_tribes'
DRAGONS=RepeatSourceEligibility(PROFILE,('dragon',),True)
ARCANE=SpellRepeatSpec(2,class_mode='any',match=RepeatMatchSpec(
    recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)),source_eligibility=DRAGONS))


def other_dragons(state,registry,player_id,carrier_id):
    from .repeat_source_conditions import qualifying_repeat_witnesses
    return qualifying_repeat_witnesses(state,registry,player_id=player_id,carrier_id=carrier_id,eligibility=DRAGONS)


def provider_kind(spec):
    if spec==ARCANE:return 'arcane'
    if spec is not None and spec.match is not None and spec.match.recipient_cost is not None and spec.match.recipient_cost.basis=='cast_quote':return 'cost'
    return None


@dataclass(frozen=True)
class NativeRepeatWitness:
    source: SourceAllocationFact
    changes: tuple[Enchantment,...]
    def __post_init__(self):
        if type(self.source)is not SourceAllocationFact:raise ValueError('Native repeat requires original witness allocation')
        self.source.__post_init__()
        if (self.source.kind,self.source.zone)!=(CardType.MINION,Zone.BOARD):raise ValueError('Native repeat witness must be an original board minion')
        from .model import _tribe_changes
        if type(self.changes)is not tuple or any(type(e)is not Enchantment or e.tribe_change is None for e in self.changes):raise ValueError('Native repeat requires complete frozen tribe changes')
        _tribe_changes(self.changes)


@dataclass(frozen=True)
class NativeRepeatProvider:
    source: SourceAllocationFact
    ability: AbilityInstance
    witnesses: tuple[NativeRepeatWitness,...] = ()
    def __post_init__(self):
        if type(self.source)is not SourceAllocationFact or type(self.ability)is not AbilityInstance:raise ValueError('Native repeat requires original provider allocation and ability')
        self.source.__post_init__();self.ability.__post_init__()
        kind=provider_kind(self.ability.spell_repeat)
        if (self.source.kind,self.source.zone)!=(CardType.MINION,Zone.BOARD)or self.ability.kind!='spell_repeat'or self.ability.consumed or kind is None:raise ValueError('Unknown native automatic repeat provider')
        if type(self.witnesses)is not tuple or (kind=='arcane')!=bool(self.witnesses):raise ValueError('Native repeat witness inventory differs from its real provider')
        ids=[]
        for witness in self.witnesses:
            if type(witness)is not NativeRepeatWitness:raise ValueError('Native repeat requires typed witnesses')
            witness.__post_init__();ids.append(witness.source.entity_id)
            if witness.source.controller!=self.source.controller or witness.source.entity_id==self.source.entity_id:raise ValueError('Native repeat requires another originally controlled Dragon')
        if len(ids)!=len(set(ids)):raise ValueError('Native repeat duplicated a witness')


@dataclass(frozen=True)
class NativeRepeatPlan:
    source: SourceAllocationFact
    player_id: int
    providers: tuple[NativeRepeatProvider,...]
    cost: CostQuoteFact | None = None
    def __post_init__(self):
        _player(self.player_id)
        if type(self.source)is not SourceAllocationFact:raise ValueError('Native repeat requires its original physical spell')
        self.source.__post_init__()
        if self.source.kind!=CardType.SPELL:raise ValueError('Native repeat requires a spell')
        if type(self.providers)is not tuple or not self.providers:raise ValueError('Native repeat requires a nonempty frozen provider set')
        need_cost=False
        for provider in self.providers:
            if type(provider)is not NativeRepeatProvider:raise ValueError('Native repeat requires typed providers')
            provider.__post_init__()
            if provider.source.controller!=self.player_id:raise ValueError('Native repeat borrowed an opponent provider')
            need_cost|=provider_kind(provider.ability.spell_repeat)=='cost'
        if need_cost!=(self.cost is not None):raise ValueError('Native repeat cost proof differs from its actual providers')
        if self.cost is not None:
            self.cost.__post_init__();value=self.cost.quote_input
            if self.cost.amount!=1 or(value.source_id,value.player_id,value.card_id)!=(self.source.entity_id,self.player_id,self.source.card_id):raise ValueError('Native repeat borrowed another original one-cost quote')


def capture(r,entity,player_id):
    from .lifecycle import active_abilities
    from .repeat_matching import validate_repeat_cost_declaration
    from .repeat_source_conditions import validate_source_declaration
    from .tribes import tribe_changes
    providers=[]
    for eid in r.player(player_id).board:
        holder=r.state.entities[eid]
        if holder.kind!=CardType.MINION or not holder.active or holder.doomed or holder.health<=0:continue
        for ability in active_abilities(holder,'spell_repeat'):
            kind=provider_kind(ability.spell_repeat)
            if kind is None:continue
            validate_repeat_cost_declaration(r.registry,ability.spell_repeat);validate_source_declaration(r.registry,ability.spell_repeat)
            witnesses=()
            if kind=='arcane':
                if r.registry.card(entity.card_id).spell_school!=SpellSchool.ARCANE:continue
                ids=other_dragons(r.state,r.registry,player_id,eid)
                if not ids:continue
                witnesses=tuple(NativeRepeatWitness(SourceAllocationFact.capture(r.state,r.state.entities[i]),tuple(tribe_changes(r.state.entities[i])))for i in ids)
            providers.append(NativeRepeatProvider(SourceAllocationFact.capture(r.state,holder),ability,witnesses))
    if not providers:return None
    cost=None
    if any(provider_kind(p.ability.spell_repeat)=='cost'for p in providers):
        from .costs import capture_cost_input,capture_quote_fact
        quoted=deepcopy(entity);quoted.controller=player_id;cost=capture_quote_fact(r.state,r.registry,capture_cost_input(quoted))
        if cost.amount!=1:
            providers=[p for p in providers if provider_kind(p.ability.spell_repeat)!='cost'];cost=None
    if not providers:return None
    return NativeRepeatPlan(SourceAllocationFact.capture(r.state,entity),player_id,tuple(providers),cost)


def validate_plan(state,registry,plan,*,closed=False):
    from .repeat_matching import validate_cost_quote_fact,validate_repeat_cost_declaration
    from .repeat_source_conditions import validate_source_declaration
    from .tribes import tribe_state_for
    plan.__post_init__();validate_allocation(state,registry,plan.source,closed=closed)
    if plan.cost is not None:validate_cost_quote_fact(registry,plan.cost)
    for provider in plan.providers:
        validate_allocation(state,registry,provider.source,closed=closed)
        validate_repeat_cost_declaration(registry,provider.ability.spell_repeat);validate_source_declaration(registry,provider.ability.spell_repeat)
        if provider.ability.id>=state.next_attachment_id:raise ValueError('Native repeat borrowed a future ability')
        if provider_kind(provider.ability.spell_repeat)=='arcane'and registry.card(plan.source.card_id).spell_school!=SpellSchool.ARCANE:raise ValueError('Native Arcane provider changed its original spell school')
        for witness in provider.witnesses:
            validate_allocation(state,registry,witness.source,closed=closed)
            if any(e.id>=state.next_attachment_id for e in witness.changes):raise ValueError('Native repeat borrowed future tribe changes')
            tribes=tribe_state_for(registry,witness.source.card_id,witness.changes,basis='current')
            if tribes is None or not tribes.matches_any(('dragon',)):raise ValueError('Native repeat witness was not an original current Dragon')


def register_payloads(mechanics):
    for kind in (NativeRepeatWitness,NativeRepeatProvider,NativeRepeatPlan):mechanics.register_payload_type(kind)
