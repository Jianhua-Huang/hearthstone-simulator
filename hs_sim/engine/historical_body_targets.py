"""Own accepted conditions/targets for actual historical Battlecry invocations.

History payload provenance never becomes a present physical attachment or paid
play. Full state is activity proof only; closed receipts certify consistency.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json

from .automatic_targets import AutomaticTargetPartition, AutomaticTargetPreference, AutomaticTargetSelection
from .body_conditions import BodyPlayConditions
from .body_target_origin import canonical_json, require_audited_predicate
from .effects import Effect, _behavior, _integer
from .errors import IllegalAction, ResolutionError
from .model import CardType, GameState, PaidTargetObservation, TargetMode
from .serialization import _row, entity_from_dict, entity_to_dict, rng_from_json
from .rules import Ruleset


@dataclass(frozen=True)
class HistoricalBattlecryBinding:
    carrier_card_id: str
    profile_id: str
    declaration_card_ids: tuple[str, ...]
    origins: tuple[str, ...] = ('history', 'played_history')

    def __post_init__(self):
        _behavior(self.carrier_card_id); _behavior(self.profile_id)
        if (type(self.declaration_card_ids) is not tuple or not self.declaration_card_ids or
                len(set(self.declaration_card_ids)) != len(self.declaration_card_ids)):
            raise ValueError('Historical producer requires its complete registered declaration scope')
        for card in self.declaration_card_ids: _behavior(card)
        if (type(self.origins) is not tuple or not self.origins or len(set(self.origins)) != len(self.origins)
                or any(o not in ('history','played_history') for o in self.origins)):
            raise ValueError('Historical producer requires its own explicit history origins')


def validate_binding(registry, binding):
    if type(binding) is not HistoricalBattlecryBinding: raise ValueError('Expected historical source binding')
    binding.__post_init__(); profile = registry.body_target_profile(binding.profile_id)
    if (profile.origin,profile.acceptance_window) != ('historical_battlecry','historical_invocation'):
        raise ValueError('Historical binding requires its own profile and invocation window')
    if registry.card(binding.carrier_card_id).kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO):
        raise ValueError('Historical Battlecry requires a character or weapon carrier')
    from .body_targets import body_target_contract
    for card in binding.declaration_card_ids:
        contract = body_target_contract(registry,card,'battlecry')
        require_audited_predicate(registry,contract.target_rule)


def authority(registry, request):
    binding = registry.historical_battlecry_binding(request.card_id,request.historical_profile_id)
    validate_binding(registry,binding)
    if request.origin not in binding.origins or request.payload.card_id not in binding.declaration_card_ids:
        raise IllegalAction('Historical body exceeds its registered source or declaration scope')
    profile = registry.body_target_profile(binding.profile_id)
    if profile.selection != request.targeting:
        raise IllegalAction('Historical request changed its registered target selection policy')
    return binding


@dataclass(frozen=True)
class HistoricalTargetSelection:
    partition: AutomaticTargetPartition
    targeting: str
    requested_target_id: int | None
    target_id: int | None
    failure: str | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        from .targeting import effect_policies
        from .whole_card_history import rng_state
        from .indirect_body_targets import explicit_result
        if type(self.partition) is not AutomaticTargetPartition: raise ValueError('Historical target lost its complete original domain')
        self.partition.__post_init__(); effect_policies(self.targeting,self.requested_target_id,'player')
        if self.partition.preference is not AutomaticTargetPreference.ANY:
            raise ValueError('Historical producer cannot borrow another automatic target preference')
        if self.targeting == 'random':
            AutomaticTargetSelection(self.partition,self.target_id,self.failure,self.rng_before,self.rng_after).__post_init__()
        else:
            rng_state(self.rng_before); rng_state(self.rng_after)
            target,failure = explicit_result(self.partition,self.requested_target_id)
            if (target,failure,self.rng_before) != (self.target_id,self.failure,self.rng_after):
                raise ValueError('Historical explicit selection changed its request or RNG')


@dataclass(frozen=True)
class HistoricalBodyReceipt:
    id: int
    record_id: int
    request: object
    source_json: str
    next_entity_id: int
    next_attachment_id: int
    turn: int
    action: int
    owner_turn_id: int
    before_play_id: int
    combo_play_ids: tuple[int, ...]
    conditions: BodyPlayConditions
    selection: HistoricalTargetSelection
    observation: PaidTargetObservation | None
    completed: bool = False
    interrupted: bool = False

    def __post_init__(self):
        from .battlecry_sources import BeginIndirectBattlecry
        if type(self.request) is not BeginIndirectBattlecry: raise ValueError('Historical receipt lost its exact original request')
        self.request.__post_init__()
        if self.request.historical_profile_id is None or self.request.historical_body_id is not None:
            raise ValueError('Historical receipt requires its original unbound producer request')
        for name in ('id','record_id','next_entity_id','next_attachment_id','turn','owner_turn_id','before_play_id'):
            _integer(getattr(self,name),'historical '+name,1)
        _integer(self.action,'historical action',0)
        if type(self.source_json) is not str: raise ValueError('Historical source requires canonical Entity JSON')
        if type(self.conditions) is not BodyPlayConditions or type(self.selection) is not HistoricalTargetSelection:
            raise ValueError('Historical invocation lost its typed original conditions or target')
        self.conditions.__post_init__(); self.selection.__post_init__()
        if (type(self.combo_play_ids) is not tuple or self.combo_play_ids != tuple(sorted(set(self.combo_play_ids))) or
                any(type(i) is not int or not 0 < i < self.before_play_id for i in self.combo_play_ids) or
                self.conditions.combo != bool(self.combo_play_ids) or
                any((self.conditions.outcast,self.conditions.finale,self.conditions.quickdraw))):
            raise ValueError('Historical conditions cannot invent hand position or payment')
        if self.observation is not None:
            if type(self.observation) is not PaidTargetObservation: raise ValueError('Historical player input lost its original DTO')
            from .player_target_inputs import decode
            decode(self.observation,require_active_player=False)
        if (type(self.completed) is not bool or type(self.interrupted) is not bool or self.completed and self.interrupted):
            raise ValueError('Historical invocation completion flags disagree')


@dataclass(frozen=True)
class HistoricalBodyProof:
    before_state: GameState
    rules: Ruleset
    receipt: HistoricalBodyReceipt
    sequence: object | None = None

    def __post_init__(self):
        if type(self.before_state) is not GameState or type(self.rules) is not Ruleset or type(self.receipt) is not HistoricalBodyReceipt:
            raise ValueError('Historical invocation lost its full original proof')
        self.rules.__post_init__(); self.receipt.__post_init__()
        if self.receipt.completed or self.receipt.interrupted:
            raise ValueError('Historical activity proof cannot borrow a settled receipt')
        if self.sequence is not None:
            from .battlecry_sequences import ContinueBattlecrySequence
            if type(self.sequence) is not ContinueBattlecrySequence:
                raise ValueError('Historical sequence lost its original captured carrier proof')
            self.sequence.__post_init__()


@dataclass(frozen=True)
class FinishHistoricalBody(Effect):
    proof: HistoricalBodyProof

    def __post_init__(self):
        if type(self.proof) is not HistoricalBodyProof: raise ValueError('Historical Finish requires its original invocation proof')
        self.proof.__post_init__()


CONTROL = (FinishHistoricalBody,)


def receipt_for(state, record):
    identity = record.historical_body_id
    if type(identity) is not int or not 1 <= identity <= len(state.historical_body_invocations):
        raise ValueError('Historical Battlecry lost its own accepted invocation')
    receipt = state.historical_body_invocations[identity-1]
    if type(receipt) is not HistoricalBodyReceipt or receipt.id != identity or receipt.record_id != record.id:
        raise ValueError('Historical Battlecry borrowed another original invocation')
    return receipt


def inputs(state, registry, request):
    source = deepcopy(state.entities[request.source_id]); source.controller = request.player_id
    definition = registry.card(request.payload.card_id)
    from .play_history import played_cards
    prior = tuple(p.id for p in played_cards(state,request.player_id,turn=state.turn))
    crystals = state.players[request.player_id].max_mana
    conditions = BodyPlayConditions(bool(prior),False,False,False,
        definition.manathirst is not None and crystals >= definition.manathirst,crystals,definition.manathirst)
    from .spell_casts import effective_definition
    return source,effective_definition(definition,asdict(conditions)),conditions,prior


def partition(state, registry, source, definition, observation, request):
    from .player_target_inputs import factory
    from .targeting import accepts_target,target_spec
    context=factory(observation,require_active_player=False) if observation is not None else None
    spec=target_spec(definition)
    excluded = (source.id,) if request.exclude_source_target else ()
    legal=tuple(i for i in sorted(state.entities) if i not in excluded and accepts_target(
        state,registry,source,definition,i,context_factory=context,automatic=True)) if spec is not None else ()
    enemy=tuple(i for i in legal if state.entities[i].controller != source.controller)
    return AutomaticTargetPartition(source.id,source.controller,definition.id,AutomaticTargetPreference.ANY,
        spec.mode if spec is not None else None,excluded,legal,enemy,legal)


def bound_request(receipt):
    return replace(receipt.request,targeting='explicit',target_id=receipt.selection.target_id,
        historical_body_id=receipt.id)


def sequence_request(state, registry, work):
    from .battlecry_sequences import validate_sequence,source_allows
    from .battlecry_sources import BeginIndirectBattlecry
    validate_sequence(state,registry,work)
    if len(work.started_ids) >= len(work.order) or not source_allows(state,work.spec,work.card_id,work.source_epoch):
        raise ValueError('Historical sequence cannot authorize an exhausted or unavailable attempt')
    spec=work.spec; candidate=work.candidates[work.order[len(work.started_ids)]]
    player=state.entities[spec.source_id].controller if spec.policy.controller == 'current' else spec.player_id
    return BeginIndirectBattlecry(spec.source_id,player,work.card_id,candidate.payload,'played_history',
        caster_id=spec.source_id,choices=spec.choices,history_play_id=candidate.play_id,
        history_player_id=spec.player_id,controller_policy=spec.policy.controller,
        exclude_source_target=spec.policy.exclude_source_target,historical_profile_id=spec.profile_id)


def accept(r, request, sequence=None):
    authority(r.registry,request)
    from .battlecry_sources import validate_start, carrier_card, begin
    validate_start(r.state,r.registry,request)
    if (sequence is None and request.card_id != carrier_card(r.state,r.registry,request.source_id) or
            sequence is not None and request != sequence_request(r.state,r.registry,sequence)):
        raise ResolutionError('Historical producer lost its actual carrier identity')
    source,definition,conditions,prior = inputs(r.state,r.registry,request)
    observation = None
    if r.registry.target_visibility(definition.target_rule) == 'player':
        from .player_target_inputs import capture,validate_full_state
        observation=capture(r.game,r.state,source)
        validate_full_state(r.state,r.registry,source,observation,require_active_player=False)
    before=deepcopy(r.state); domain=partition(before,r.registry,source,definition,observation,request)
    rng_before=r.game._rng.getstate()
    if request.targeting == 'random':
        target=r.game._rng.choice(domain.selection_ids) if domain.selection_ids else None
        failure='no_target' if not domain.selection_ids and domain.mode is TargetMode.REQUIRED else None
    else:
        from .indirect_body_targets import explicit_result
        target,failure=explicit_result(domain,request.target_id)
    selection=HistoricalTargetSelection(domain,request.targeting,request.target_id,target,failure,rng_before,r.game._rng.getstate())
    from .owner_turns import current_owner_turn
    receipt=HistoricalBodyReceipt(len(before.historical_body_invocations)+1,len(before.battlecry_history)+1,request,
        canonical_json(entity_to_dict(before.entities[source.id])),before.next_entity_id,before.next_attachment_id,
        before.turn,before.action_number,current_owner_turn(before).id,len(before.play_history)+1,prior,conditions,selection,observation)
    proof=HistoricalBodyProof(before,r.rules,receipt,sequence); validate_proof(proof,r.registry)
    r.state.historical_body_invocations.append(receipt)
    return (*begin(r,bound_request(receipt)),FinishHistoricalBody(proof))


def accepted_start(state, request):
    if request.historical_body_id is None or request.historical_body_id > len(state.historical_body_invocations):
        raise ValueError('Historical start lost its actual accepted target producer')
    receipt=state.historical_body_invocations[request.historical_body_id-1]
    if receipt.completed or receipt.interrupted or receipt.record_id != len(state.battlecry_history)+1 or bound_request(receipt) != request:
        raise ValueError('Historical start differs from its original accepted invocation')
    return receipt


def validate_receipt(state, registry, receipt):
    receipt.__post_init__(); request=receipt.request; authority(registry,request)
    # Current controller is checked only at the original acceptance window.
    from .battlecry_sources import validate_payload, historical_record
    validate_payload(state,registry,request.source_id,request.card_id,request.payload,request.caster_id)
    if request.history_id is not None:
        original=historical_record(state,request.history_id,request.history_player_id)
        if original.id >= receipt.record_id or original.payload != request.payload: raise ValueError('Historical receipt changed activation provenance')
    else:
        from .played_battlecries import validate_played_payload
        original=validate_played_payload(state,request.history_play_id,request.history_player_id,request.payload)
        if original.id >= receipt.before_play_id or original.action > receipt.action: raise ValueError('Historical receipt changed committed provenance')
    source=entity_from_dict(json.loads(receipt.source_json))
    if (canonical_json(entity_to_dict(source)) != receipt.source_json or source.id != request.source_id or
            registry.card(source.card_id).kind != source.kind or
            source.id >= receipt.next_entity_id or receipt.next_entity_id > state.next_entity_id or
            receipt.next_attachment_id > state.next_attachment_id or
            any(a.id >= receipt.next_attachment_id for a in (*source.abilities,*source.enchantments))):
        raise ValueError('Historical receipt changed its canonical original physical source')
    attachments=(*source.abilities,*source.enchantments)
    if len({a.id for a in attachments}) != len(attachments): raise ValueError('Historical source reused attachment identities')
    for item in attachments: item.__post_init__()
    from .allocation_facts import SourceAllocationFact,validate_allocation
    validate_allocation(state,registry,SourceAllocationFact.capture(state,source))
    if not 1 <= receipt.owner_turn_id <= len(state.owner_turn_history): raise ValueError('Historical receipt lost its original owner interval')
    interval=state.owner_turn_history[receipt.owner_turn_id-1]
    if (interval.turn != receipt.turn or receipt.action < interval.start_action or
            interval.closed_action is not None and receipt.action > interval.closed_action or
            receipt.turn > state.turn or receipt.action > state.action_number or receipt.before_play_id > len(state.play_history)+1):
        raise ValueError('Historical receipt changed its original invocation window')
    from .play_history import played_cards
    prior=tuple(p.id for p in played_cards(state,request.player_id,turn=receipt.turn,before_id=receipt.before_play_id))
    if prior != receipt.combo_play_ids or receipt.conditions.manathirst_threshold != registry.card(request.payload.card_id).manathirst:
        raise ValueError('Historical receipt changed its own declaration condition or complete prior plays')
    domain=receipt.selection.partition
    from .spell_casts import effective_definition
    from .targeting import target_spec
    definition=effective_definition(registry.card(request.payload.card_id),asdict(receipt.conditions))
    spec=target_spec(definition)
    if (domain.mode != (spec.mode if spec is not None else None) or
            (registry.target_visibility(definition.target_rule) == 'player') != (receipt.observation is not None) or
            any(i >= receipt.next_entity_id for i in (*domain.excluded_ids,*domain.legal_ids))):
        raise ValueError('Historical receipt changed its own target mode, visibility or allocation')
    if ((domain.source_id,domain.source_controller,domain.definition_id) != (request.source_id,request.player_id,request.payload.card_id) or
            domain.excluded_ids != ((request.source_id,) if request.exclude_source_target else ()) or
            (receipt.selection.targeting,receipt.selection.requested_target_id) != (request.targeting,request.target_id)):
        raise ValueError('Historical receipt changed its own target identity or source policy')
    if receipt.observation is not None:
        from .player_target_inputs import decode
        observed=decode(receipt.observation,require_active_player=False)
        if (observed['viewer'],observed['turn']) != (request.player_id,receipt.turn):
            raise ValueError('Historical receipt borrowed another executor observation window')
        if any(i not in state.entities or i >= receipt.next_entity_id for i,_ in receipt.observation.references):
            raise ValueError('Historical player reference exceeds its original physical universe')


def validate_record(state, registry, record):
    receipt=receipt_for(state,record); validate_receipt(state,registry,receipt); request=bound_request(receipt)
    names=('source_id','player_id','card_id','payload','origin','caster_id','history_id','history_play_id',
        'history_player_id','controller_policy','exclude_source_target','choices','historical_body_id')
    if (any(getattr(record,key) != getattr(request,key) for key in names) or
            (record.turn,record.action,record.target_id,record.failure) !=
            (receipt.turn,receipt.action,receipt.selection.target_id,receipt.selection.failure)):
        raise ValueError('Historical actual record changed its complete accepted identity')


def validate_proof(proof, registry):
    proof.__post_init__(); before=proof.before_state; receipt=proof.receipt; request=receipt.request
    validate_receipt(before,registry,receipt)
    from .battlecry_sources import validate_start,carrier_card
    validate_start(before,registry,request)
    from .owner_turns import current_owner_turn
    if ((receipt.id,receipt.record_id,receipt.turn,receipt.action,receipt.owner_turn_id,receipt.before_play_id,
            receipt.next_entity_id,receipt.next_attachment_id) !=
            (len(before.historical_body_invocations)+1,len(before.battlecry_history)+1,before.turn,before.action_number,
                current_owner_turn(before).id,len(before.play_history)+1,before.next_entity_id,before.next_attachment_id) or
            proof.sequence is None and request.card_id != carrier_card(before,registry,request.source_id) or
            proof.sequence is not None and request != sequence_request(before,registry,proof.sequence) or
            receipt.source_json != canonical_json(entity_to_dict(before.entities[request.source_id]))):
        raise ValueError('Historical proof lost its full original actual invocation')
    source,definition,conditions,prior=inputs(before,registry,request)
    if (conditions,prior) != (receipt.conditions,receipt.combo_play_ids): raise ValueError('Historical proof changed its original conditions')
    needs=registry.target_visibility(definition.target_rule) == 'player'
    if needs != (receipt.observation is not None): raise ValueError('Historical proof changed its original target visibility')
    if needs:
        from .player_target_inputs import validate_full_state
        validate_full_state(before,registry,source,receipt.observation,require_active_player=False)
    if partition(before,registry,source,definition,receipt.observation,request) != receipt.selection.partition:
        raise ValueError('Historical proof changed its complete original target domain')


def finish(r, effect):
    effect.__post_init__(); validate_proof(effect.proof,r.registry)
    receipt=effect.proof.receipt; current=r.state.historical_body_invocations[receipt.id-1]
    if current != receipt or not r.state.battlecry_history[receipt.record_id-1].completed:
        raise ResolutionError('Historical Finish lost its original invocation or actual completion')
    r.state.historical_body_invocations[receipt.id-1]=replace(receipt,completed=True)


def validate_history(state, registry):
    if type(state.historical_body_invocations) is not list: raise ValueError('Historical invocations require an ordered list')
    used=set(); prior=0
    for identity,receipt in enumerate(state.historical_body_invocations,1):
        if type(receipt) is not HistoricalBodyReceipt or receipt.id != identity or receipt.record_id <= prior:
            raise ValueError('Historical invocations changed their allocation order')
        validate_receipt(state,registry,receipt)
        if receipt.record_id > len(state.battlecry_history): raise ValueError('Historical invocation lost its actual record')
        record=state.battlecry_history[receipt.record_id-1]
        if record.historical_body_id != identity: raise ValueError('Historical invocation borrowed another actual record')
        validate_record(state,registry,record)
        if (receipt.completed and not record.completed or receipt.interrupted and state.status == 'playing' or
                record.interrupted and not receipt.interrupted):
            raise ValueError('Historical invocation changed its completion or interruption')
        used.add(record.id); prior=record.id
    if used != {b.id for b in state.battlecry_history if b.historical_body_id is not None}:
        raise ValueError('Historical records lost their complete invocation receipts')


def validate_boundary(game):
    state=game._state; queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    markers=[w for w in queue if type(w) is FinishHistoricalBody]
    pending=[row for row in state.historical_body_invocations if not row.completed and not row.interrupted]
    if len(markers) != len(pending) or {w.proof.receipt.id for w in markers} != {r.id for r in pending}:
        raise ValueError('Historical pending invocations lost their unique complete Finish proofs')
    from .battlecries import FinishBattlecry
    for marker in markers:
        validate_proof(marker.proof,game.registry); receipt=marker.proof.receipt
        if state.historical_body_invocations[receipt.id-1] != receipt:
            raise ValueError('Historical Finish proof changed its original accepted receipt')
        record=state.battlecry_history[receipt.record_id-1]; end=FinishBattlecry(record.id)
        if not record.completed and (end not in queue or queue.index(end) >= queue.index(marker)):
            raise ValueError('Historical proof must follow its actual Battlecry completion')
        if record.parent_id is not None:
            parent=FinishBattlecry(record.parent_id)
            if parent not in queue or queue.index(marker) >= queue.index(parent):
                raise ValueError('Historical invocation proof must finish before its parent')
        if marker.proof.sequence is not None:
            from .battlecry_sequences import FinishSequenceAttempt
            closer=FinishSequenceAttempt(marker.proof.sequence,receipt.record_id)
            if closer not in queue or queue.index(marker) >= queue.index(closer):
                raise ValueError('Historical invocation must retain its own complete outer sequence attempt')


def validate_terminal_queue(r, queue):
    from types import SimpleNamespace
    validate_boundary(SimpleNamespace(_state=r.state,registry=r.registry,
        _frame=SimpleNamespace(prefix=(),continuation=tuple(queue))))


def interrupt(state):
    state.historical_body_invocations=[replace(row,interrupted=True) if not row.completed and not row.interrupted else row
        for row in state.historical_body_invocations]


def receipt_from_dict(value):
    from .battlecry_sources import BeginIndirectBattlecry
    from .model import BattlecryPayload
    from .indirect_body_targets import array
    row=_row(value,HistoricalBodyReceipt); request=_row(row['request'],BeginIndirectBattlecry)
    request['payload']=BattlecryPayload(**_row(request['payload'],BattlecryPayload)); row['request']=BeginIndirectBattlecry(**request)
    row['conditions']=BodyPlayConditions(**_row(row['conditions'],BodyPlayConditions))
    row['combo_play_ids']=tuple(array(row['combo_play_ids']))
    selected=_row(row['selection'],HistoricalTargetSelection); part=_row(selected['partition'],AutomaticTargetPartition)
    part['preference']=AutomaticTargetPreference(part['preference']); part['mode']=TargetMode(part['mode']) if part['mode'] is not None else None
    for key in ('excluded_ids','legal_ids','enemy_ids','selection_ids'): part[key]=tuple(array(part[key]))
    selected['partition']=AutomaticTargetPartition(**part)
    for key in ('rng_before','rng_after'): selected[key]=rng_from_json(selected[key])
    row['selection']=HistoricalTargetSelection(**selected)
    if row['observation'] is not None:
        observed=_row(row['observation'],PaidTargetObservation)
        observed['references']=tuple(tuple(array(item)) for item in array(observed['references']))
        row['observation']=PaidTargetObservation(**observed)
    return HistoricalBodyReceipt(**row)


def register(mechanics):
    for payload in (HistoricalBattlecryBinding,HistoricalTargetSelection,HistoricalBodyReceipt,HistoricalBodyProof):
        mechanics.register_payload_type(payload)
    mechanics.register(FinishHistoricalBody,finish)
