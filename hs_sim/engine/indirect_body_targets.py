"""Connected indirect Battlecry bodies, with source and invocation windows.

The producer freezes physical bodies once. Each actual invocation separately
accepts conditions, the complete target partition and one RNG decision. Only
pending interpreter proofs keep a full before-state; settled history is compact.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import json

from .automatic_targets import (AutomaticTargetPartition, AutomaticTargetPreference,
    AutomaticTargetSelection)
from .body_conditions import BodyPlayConditions
from .body_grants import BodyReference
from .body_target_authority import body_target_authority
from .body_target_origin import canonical_json, require_audited_predicate
from .body_targets import BodyTargetReference, body_target_declarations
from .effects import Effect, _behavior, _integer, _player, _source
from .errors import IllegalAction, ResolutionError, ResolutionLimitExceeded
from .model import BattlecryPayload, CardType, GameState, PaidTargetObservation, TargetMode, Zone
from .rules import Ruleset
from .serialization import _row, entity_from_dict, entity_to_dict, rng_from_json
from .targeting import accepts_target, effect_policies, target_spec


@dataclass(frozen=True)
class IndirectBattlecryBinding:
    carrier_card_id: str
    profile_id: str

    def __post_init__(self):
        _behavior(self.carrier_card_id); _behavior(self.profile_id)


def validate_binding(registry, binding):
    if type(binding) is not IndirectBattlecryBinding:
        raise ValueError('Expected exact typed indirect Battlecry binding')
    binding.__post_init__()
    profile = registry.body_target_profile(binding.profile_id)
    if (profile.origin, profile.acceptance_window) != ('indirect_battlecry', 'indirect_invocation'):
        raise ValueError('Indirect Battlecry binding requires its own origin and invocation window')
    if registry.card(binding.carrier_card_id).kind != CardType.MINION:
        raise ValueError('TriggerBattlecry requires a physical minion carrier')


def connected_carrier(registry, card_id):
    return any(card == card_id for card, _ in (
        *registry.body_root_target_bindings, *registry.indirect_battlecry_bindings,
        *registry.generated_whole_target_bindings))


def require_legacy_paid_scope(registry, source):
    """Moving/copying a grant never turns indirect authorization into payment."""
    from .lifecycle import active_abilities
    if any(card == source.card_id for card,_ in (*registry.indirect_battlecry_bindings,
            *registry.generated_whole_target_bindings)) and any(
            a.origin == 'granted' for family in ('battlecry','combo') for a in active_abilities(source,family)):
        raise IllegalAction('Nonpaid body grants require their own connected paid target producer')


def authorities(state, registry, entity, profile_id):
    binding = registry.indirect_battlecry_binding(entity.card_id, profile_id)
    validate_binding(registry, binding)
    if entity.kind is not CardType.MINION or entity.zone != Zone.BOARD or not entity.active or entity.doomed or entity.health <= 0:
        raise ValueError('Indirect body source requires its real active board minion')
    result = tuple(body_target_authority(state, registry, declaration.reference, profile_id)
        for declaration in body_target_declarations(state, registry, BodyReference.capture(entity), profile_id)
        if declaration.reference.family == 'battlecry')
    for authority in result:
        require_audited_predicate(registry, authority.declaration.contract.target_rule)
    return result


def grant_authority(state, registry, entity, ability):
    """Only the connected board Battlecry route can authorize these grants."""
    if entity.zone != Zone.BOARD or ability.kind != 'battlecry': return ()
    proposed = replace(entity, abilities=[*entity.abilities, ability])
    prospective = replace(state, entities={**state.entities, entity.id: proposed})
    complete = []
    for card, profile_id in registry.indirect_battlecry_bindings:
        if card != entity.card_id: continue
        try:
            rows = authorities(prospective, registry, proposed, profile_id)
        except (ValueError, IllegalAction):
            continue
        if any(row.declaration.reference.ability_id == ability.id for row in rows):
            complete.append(profile_id)
    return tuple(complete)


@dataclass(frozen=True)
class IndirectBodyOrigin:
    binding: IndirectBattlecryBinding
    source_json: str
    bodies: tuple[BodyTargetReference, ...]
    next_entity_id: int
    next_attachment_id: int
    turn: int
    action: int
    issuer_id: int | None
    targeting: str
    requested_target_id: int | None
    choices: str

    def __post_init__(self):
        if type(self.binding) is not IndirectBattlecryBinding:
            raise ValueError('Indirect body origin lost its connected source binding')
        self.binding.__post_init__()
        if type(self.source_json) is not str: raise ValueError('Indirect body source requires canonical Entity JSON')
        if type(self.bodies) is not tuple or any(type(b) is not BodyTargetReference for b in self.bodies):
            raise ValueError('Indirect body source requires its complete immutable physical vector')
        for body in self.bodies:
            body.__post_init__()
            if body.family != 'battlecry': raise ValueError('Indirect producer cannot borrow Combo bodies')
        if len({b.ability_id for b in self.bodies}) != len(self.bodies):
            raise ValueError('Indirect producer duplicated a physical body')
        for name in ('next_entity_id','next_attachment_id','turn'):
            _integer(getattr(self,name),name,1)
        _integer(self.action,'indirect source action',0); _source(self.issuer_id)
        effect_policies(self.targeting,self.requested_target_id,self.choices)


@dataclass(frozen=True)
class IndirectTargetSelection:
    partition: AutomaticTargetPartition
    targeting: str
    requested_target_id: int | None
    target_id: int | None
    failure: str | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.partition) is not AutomaticTargetPartition:
            raise ValueError('Indirect target lost its complete original partition')
        self.partition.__post_init__()
        effect_policies(self.targeting,self.requested_target_id,'player')
        if self.partition.preference is not AutomaticTargetPreference.ANY or self.partition.excluded_ids:
            raise ValueError('Connected indirect origin uses the complete unpreferred automatic domain')
        if self.targeting == 'random':
            AutomaticTargetSelection(self.partition,self.target_id,self.failure,self.rng_before,self.rng_after).__post_init__()
        else:
            from .whole_card_history import rng_state
            rng_state(self.rng_before); rng_state(self.rng_after)
            target, failure = explicit_result(self.partition,self.requested_target_id)
            if (self.target_id,self.failure,self.rng_after) != (target,failure,self.rng_before):
                raise ValueError('Explicit indirect target changed its request or consumed RNG')


def explicit_result(partition, target_id):
    if partition.mode is None:
        return None,None
    if target_id is not None:
        return (target_id,None) if target_id in partition.legal_ids else (None,'invalid_target')
    failure = 'no_target' if (partition.mode is TargetMode.REQUIRED or
        partition.mode is TargetMode.IF_AVAILABLE and partition.legal_ids) else None
    return None,failure


@dataclass(frozen=True)
class IndirectInvocationReceipt:
    root_id: int
    slot: int
    record_id: int
    source_id: int
    player_id: int
    card_id: str
    payload: BattlecryPayload
    conditions: BodyPlayConditions
    before_play_id: int
    combo_play_ids: tuple[int, ...]
    turn: int
    action: int
    selection: IndirectTargetSelection
    observation: PaidTargetObservation | None

    def __post_init__(self):
        for name in ('root_id','record_id','source_id','before_play_id','turn'):
            _integer(getattr(self,name),name,1)
        for name in ('slot','action'): _integer(getattr(self,name),name,0)
        _player(self.player_id); _behavior(self.card_id)
        for value, cls in ((self.payload,BattlecryPayload),(self.conditions,BodyPlayConditions),
                           (self.selection,IndirectTargetSelection)):
            if type(value) is not cls: raise ValueError('Indirect invocation lost its typed original input')
            value.__post_init__()
        if (type(self.combo_play_ids) is not tuple or
                self.combo_play_ids != tuple(sorted(set(self.combo_play_ids)))):
            raise ValueError('Indirect Combo condition requires its ordered paid prefix')
        for identity in self.combo_play_ids: _integer(identity,'indirect prerequisite play',1)
        if (any(i >= self.before_play_id for i in self.combo_play_ids) or
                self.conditions.combo != bool(self.combo_play_ids) or
                any((self.conditions.outcast,self.conditions.finale,self.conditions.quickdraw))):
            raise ValueError('Indirect conditions cannot invent a hand position or payment')
        if self.observation is not None:
            if type(self.observation) is not PaidTargetObservation:
                raise ValueError('Indirect player input requires its exact observation type')
            from .player_target_inputs import decode
            decode(self.observation)


@dataclass(frozen=True)
class IndirectBodySequence:
    id: int
    origin: IndirectBodyOrigin
    cursor: int = 0
    receipts: tuple[IndirectInvocationReceipt, ...] = ()
    active_battlecry_id: int | None = None
    finished: bool = False
    interrupted: bool = False

    def __post_init__(self):
        _integer(self.id,'indirect body root',1); _integer(self.cursor,'indirect body cursor',0)
        if type(self.origin) is not IndirectBodyOrigin: raise ValueError('Indirect sequence lost its original producer')
        self.origin.__post_init__(); _source(self.active_battlecry_id)
        if type(self.receipts) is not tuple or any(type(r) is not IndirectInvocationReceipt for r in self.receipts):
            raise ValueError('Indirect sequence lost its ordered actual invocations')
        for index, receipt in enumerate(self.receipts):
            receipt.__post_init__()
            if (receipt.root_id,receipt.slot) != (self.id,index):
                raise ValueError('Indirect sequence reordered or borrowed an invocation')
        if self.cursor != len(self.receipts) or self.cursor > len(self.origin.bodies):
            raise ValueError('Indirect sequence abandoned or extended its accepted body vector')
        if (type(self.finished) is not bool or type(self.interrupted) is not bool or
                self.finished and self.interrupted or
                self.finished and (self.cursor != len(self.origin.bodies) or self.active_battlecry_id is not None) or
                self.active_battlecry_id is not None and (not self.receipts or
                    self.receipts[-1].record_id != self.active_battlecry_id)):
            raise ValueError('Indirect sequence progress lost its unique completion')


@dataclass(frozen=True)
class IndirectInvocationProof:
    before_state: GameState
    rules: Ruleset
    receipt: IndirectInvocationReceipt

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.receipt) is not IndirectInvocationReceipt):
            raise ValueError('Indirect invocation proof lost its actual original window')
        self.rules.__post_init__(); self.receipt.__post_init__()


@dataclass(frozen=True)
class AdvanceIndirectBodies(Effect):
    accepted: IndirectBodySequence


@dataclass(frozen=True)
class FinishIndirectBodies(Effect):
    accepted: IndirectBodySequence


@dataclass(frozen=True)
class FinishIndirectInvocation(Effect):
    proof: IndirectInvocationProof


CONTROL = (AdvanceIndirectBodies,FinishIndirectBodies,FinishIndirectInvocation)


def root_for(state, root_id):
    _integer(root_id,'indirect root',1)
    if root_id > len(state.indirect_body_sequences): raise ValueError('Unknown actual indirect body root')
    return state.indirect_body_sequences[root_id-1]


def put(state, root):
    root.__post_init__(); state.indirect_body_sequences[root.id-1] = root


def source_origin(origin, registry):
    origin.__post_init__(); validate_binding(registry,origin.binding)
    source = entity_from_dict(json.loads(origin.source_json))
    if canonical_json(entity_to_dict(source)) != origin.source_json:
        raise ValueError('Indirect original source requires exact canonical Entity JSON')
    if (source.card_id != origin.binding.carrier_card_id or source.id >= origin.next_entity_id or
            any(a.id >= origin.next_attachment_id for a in (*source.abilities,*source.enchantments))):
        raise ValueError('Indirect original source exceeds its physical allocation')
    identities = tuple(a.id for a in (*source.abilities,*source.enchantments))
    if len(set(identities)) != len(identities) or any(type(i) is not int or i < 1 for i in identities):
        raise ValueError('Indirect original source has invalid or duplicate attachment identities')
    profile = registry.body_target_profile(origin.binding.profile_id)
    if profile.selection != origin.targeting: raise ValueError('Indirect selection borrowed another producer policy')
    from types import SimpleNamespace
    probe = SimpleNamespace(entities={source.id:source})
    refs = tuple(row.declaration.reference for row in authorities(probe,registry,source,origin.binding.profile_id))
    if refs != origin.bodies: raise ValueError('Indirect producer changed its complete physical body vector')
    return source


def start(r, request, entity):
    rows = authorities(r.state,r.registry,entity,request.profile_id)
    if len(rows) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Complete indirect body vector exceeds resolution budget')
    origin = IndirectBodyOrigin(r.registry.indirect_battlecry_binding(entity.card_id,request.profile_id),
        canonical_json(entity_to_dict(entity)),tuple(a.declaration.reference for a in rows),
        r.state.next_entity_id,r.state.next_attachment_id,r.state.turn,r.state.action_number,
        request.source_id,request.targeting,request.target_id,request.choices)
    source_origin(origin,r.registry)
    root = IndirectBodySequence(len(r.state.indirect_body_sequences)+1,origin)
    r.state.indirect_body_sequences.append(root)
    return (AdvanceIndirectBodies(root),FinishIndirectBodies(root))


def anchor(state, registry, accepted):
    if type(accepted) is not IndirectBodySequence: raise ValueError('Indirect control requires its accepted root')
    accepted.__post_init__(); source_origin(accepted.origin,registry)
    if accepted.cursor or accepted.receipts or accepted.active_battlecry_id or accepted.finished or accepted.interrupted:
        raise ValueError('Indirect control anchor cannot be rewritten as later progress')
    current = root_for(state,accepted.id)
    if replace(current,cursor=0,receipts=(),active_battlecry_id=None,finished=False,interrupted=False) != accepted:
        raise ValueError('Indirect control lost its original complete source acceptance')
    return current


def inputs(state, registry, root, slot):
    ref = root.origin.bodies[slot]; source = deepcopy(state.entities[ref.carrier.entity_id])
    source.controller = ref.carrier.player_id
    definition = registry.card(ref.declaration_card_id)
    from .play_history import played_cards
    prior = tuple(p.id for p in played_cards(state,source.controller,turn=state.turn))
    crystals = state.players[source.controller].max_mana
    conditions = BodyPlayConditions(bool(prior),False,False,False,
        definition.manathirst is not None and crystals >= definition.manathirst,crystals,definition.manathirst)
    from .spell_casts import effective_definition
    effective = effective_definition(definition,asdict(conditions))
    return source,effective,conditions,prior


def partition(state, registry, source, definition, observation):
    from .player_target_inputs import factory
    context = factory(observation) if observation is not None else None
    spec = target_spec(definition)
    legal = tuple(i for i in sorted(state.entities) if accepts_target(state,registry,source,definition,i,
        context_factory=context,automatic=True)) if spec is not None else ()
    enemy = tuple(i for i in legal if state.entities[i].controller != source.controller)
    return AutomaticTargetPartition(source.id,source.controller,definition.id,AutomaticTargetPreference.ANY,
        spec.mode if spec is not None else None,(),legal,enemy,legal)


def advance(r, effect):
    root = anchor(r.state,r.registry,effect.accepted)
    if root.finished or root.interrupted or root.active_battlecry_id is not None:
        raise ResolutionError('Indirect producer cannot begin another body before the current one finishes')
    if root.cursor == len(root.origin.bodies): return ()
    source,definition,conditions,prior = inputs(r.state,r.registry,root,root.cursor)
    observation = None
    if r.registry.target_visibility(definition.target_rule) == 'player':
        from .player_target_inputs import capture,validate_full_state
        observation = capture(r.game,r.state,source)
        validate_full_state(r.state,r.registry,source,observation)
    before = deepcopy(r.state); domain = partition(before,r.registry,source,definition,observation)
    rng_before = r.game._rng.getstate()
    if root.origin.targeting == 'random':
        target = r.game._rng.choice(domain.selection_ids) if domain.selection_ids else None
        failure = 'no_target' if not domain.selection_ids and domain.mode is TargetMode.REQUIRED else None
    else:
        target,failure = explicit_result(domain,root.origin.requested_target_id)
    selection = IndirectTargetSelection(domain,root.origin.targeting,root.origin.requested_target_id,
        target,failure,rng_before,r.game._rng.getstate())
    ref = root.origin.bodies[root.cursor]
    receipt = IndirectInvocationReceipt(root.id,root.cursor,len(before.battlecry_history)+1,
        source.id,source.controller,ref.carrier.card_id,BattlecryPayload(ref.ability_id,ref.behavior_id,ref.declaration_card_id),
        conditions,len(before.play_history)+1,prior,before.turn,before.action_number,selection,observation)
    put(r.state,replace(root,cursor=root.cursor+1,receipts=(*root.receipts,receipt),active_battlecry_id=receipt.record_id))
    from .battlecry_sources import BeginIndirectBattlecry
    request = BeginIndirectBattlecry(source.id,source.controller,ref.carrier.card_id,receipt.payload,
        caster_id=root.origin.issuer_id,target_id=target,targeting='explicit',choices=root.origin.choices,
        indirect_body_id=root.id)
    proof = IndirectInvocationProof(before,r.rules,receipt)
    # Beginning is a real effect checkpoint. Its start listeners must precede
    # ResolveIndirectBattlecry, exactly as on the existing indirect path.
    return (request,FinishIndirectInvocation(proof),AdvanceIndirectBodies(effect.accepted))


def accepted_start(state, request):
    root = root_for(state,request.indirect_body_id)
    if root.finished or root.interrupted or root.active_battlecry_id != len(state.battlecry_history)+1:
        raise ValueError('Indirect invocation lacks its unique pending actual identity')
    receipt = root.receipts[-1]
    if (request.source_id,request.player_id,request.card_id,request.payload,request.target_id,request.caster_id,request.choices) != (
            receipt.source_id,receipt.player_id,receipt.card_id,receipt.payload,receipt.selection.target_id,
            root.origin.issuer_id,root.origin.choices):
        raise ValueError('Indirect invocation differs from its original accepted body or target')
    return receipt


def receipt_for(state, record):
    root = root_for(state,record.indirect_body_id)
    matches = [r for r in root.receipts if r.record_id == record.id]
    if len(matches) != 1: raise ValueError('Indirect body lost its unique actual accepted invocation')
    return matches[0]


def validate_record(state, registry, record):
    root = root_for(state,record.indirect_body_id); receipt = receipt_for(state,record)
    ref = root.origin.bodies[receipt.slot]
    if (record.source_id,record.player_id,record.card_id,record.payload,record.turn,record.action,
            record.target_id,record.failure,record.caster_id,record.choices) != (
            ref.carrier.entity_id,ref.carrier.player_id,ref.carrier.card_id,receipt.payload,receipt.turn,receipt.action,
            receipt.selection.target_id,receipt.selection.failure,root.origin.issuer_id,root.origin.choices):
        raise ValueError('Actual indirect Battlecry changed its complete original invocation')


def validate_proof(proof, registry):
    proof.__post_init__(); before = proof.before_state; receipt = proof.receipt
    root = root_for(before,receipt.root_id); source_origin(root.origin,registry)
    if (root.cursor != receipt.slot or root.active_battlecry_id is not None or root.finished or root.interrupted or
            receipt.record_id != len(before.battlecry_history)+1 or
            (receipt.turn,receipt.action) != (before.turn,before.action_number)):
        raise ValueError('Indirect proof lost its real next invocation window')
    source,definition,conditions,prior = inputs(before,registry,root,receipt.slot)
    if (receipt.conditions,receipt.combo_play_ids,receipt.before_play_id) != (conditions,prior,len(before.play_history)+1):
        raise ValueError('Indirect proof changed its original declaration-specific conditions')
    needs_observation = registry.target_visibility(definition.target_rule) == 'player'
    if needs_observation != (receipt.observation is not None):
        raise ValueError('Indirect proof changed its original target visibility')
    if needs_observation:
        from .player_target_inputs import validate_full_state
        validate_full_state(before,registry,source,receipt.observation)
    if partition(before,registry,source,definition,receipt.observation) != receipt.selection.partition:
        raise ValueError('Indirect target differs from its complete original invocation partition')
    if (receipt.selection.targeting,receipt.selection.requested_target_id) != (root.origin.targeting,root.origin.requested_target_id):
        raise ValueError('Indirect target borrowed another selection policy')


def finish_invocation(r, effect):
    validate_proof(effect.proof,r.registry)
    receipt = effect.proof.receipt; root = root_for(r.state,receipt.root_id)
    if root.active_battlecry_id != receipt.record_id or root.receipts[-1] != receipt:
        raise ResolutionError('Indirect invocation Finish lost its original active body')
    record = r.state.battlecry_history[receipt.record_id-1]
    validate_record(r.state,r.registry,record)
    if not record.completed or record.interrupted:
        raise ResolutionError('Indirect invocation cannot finish before its real Battlecry')
    put(r.state,replace(root,active_battlecry_id=None))


def finish(r, effect):
    root = anchor(r.state,r.registry,effect.accepted)
    if root.finished or root.interrupted or root.active_battlecry_id is not None or root.cursor != len(root.origin.bodies):
        raise ResolutionError('Indirect producer Finish abandoned its complete accepted bodies')
    put(r.state,replace(root,finished=True))


def validate_history(state, registry):
    if type(state.indirect_body_sequences) is not list:
        raise ValueError('Indirect body history requires a list')
    used = set(); previous = (0,0)
    from .play_history import played_cards
    for index,root in enumerate(state.indirect_body_sequences,1):
        if type(root) is not IndirectBodySequence: raise ValueError('Indirect body history requires typed sequences')
        root.__post_init__(); source = source_origin(root.origin,registry)
        if (root.id != index or source.id not in state.entities or root.origin.next_entity_id > state.next_entity_id or
                root.origin.next_attachment_id > state.next_attachment_id or
                not previous <= (root.origin.turn,root.origin.action) <= (state.turn,state.action_number) or
                root.origin.issuer_id is not None and root.origin.issuer_id not in state.entities or
                root.interrupted and state.status == 'playing'):
            raise ValueError('Indirect body producer exceeds its actual physical chronology')
        previous = root.origin.turn,root.origin.action
        actual = tuple(b.id for b in state.battlecry_history if b.indirect_body_id == root.id)
        if actual != tuple(r.record_id for r in root.receipts):
            raise ValueError('Indirect producer erased, invented or reordered its actual Battlecries')
        for receipt in root.receipts:
            ref = root.origin.bodies[receipt.slot]
            expected_payload = BattlecryPayload(ref.ability_id,ref.behavior_id,ref.declaration_card_id)
            conditions = receipt.conditions
            prior = tuple(p.id for p in played_cards(state,source.controller,turn=receipt.turn,before_id=receipt.before_play_id))
            if (receipt.payload != expected_payload or receipt.before_play_id > len(state.play_history)+1 or
                    (receipt.source_id,receipt.player_id,receipt.card_id) !=
                        (ref.carrier.entity_id,ref.carrier.player_id,ref.carrier.card_id) or
                    prior != receipt.combo_play_ids or
                    conditions.manathirst_threshold != registry.card(ref.declaration_card_id).manathirst or
                    (receipt.selection.partition.source_id,receipt.selection.partition.source_controller,
                        receipt.selection.partition.definition_id) != (source.id,source.controller,ref.declaration_card_id) or
                    any(i not in state.entities for i in receipt.selection.partition.legal_ids) or
                    (receipt.selection.targeting,receipt.selection.requested_target_id) !=
                        (root.origin.targeting,root.origin.requested_target_id) or receipt.record_id in used or
                    not (root.origin.turn,root.origin.action) <= (receipt.turn,receipt.action) <= (state.turn,state.action_number)):
                raise ValueError('Indirect receipt lost its original payload, condition prefix or target source')
            from .spell_casts import effective_definition
            definition = effective_definition(registry.card(ref.declaration_card_id),asdict(conditions))
            spec = target_spec(definition)
            if receipt.selection.partition.mode != (spec.mode if spec is not None else None):
                raise ValueError('Indirect receipt changed its declaration-specific target activation')
            needs_observation = registry.target_visibility(definition.target_rule) == 'player'
            if needs_observation != (receipt.observation is not None):
                raise ValueError('Indirect receipt changed its original predicate visibility')
            if needs_observation:
                from .player_target_inputs import decode
                observation = decode(receipt.observation)
                if (observation['viewer'],observation['turn']) != (receipt.player_id,receipt.turn):
                    raise ValueError('Indirect receipt borrowed another player observation window')
                if any(i not in state.entities for i,_ in receipt.observation.references):
                    raise ValueError('Indirect original observation references an unknown physical entity')
            used.add(receipt.record_id)
            record = state.battlecry_history[receipt.record_id-1]; validate_record(state,registry,record)
            if record.id != root.active_battlecry_id and not (record.completed or root.interrupted and record.interrupted):
                raise ValueError('Indirect producer abandoned an actual body before completion')
        if not root.finished and not root.interrupted and state.status != 'playing':
            raise ValueError('Terminal game cannot retain an active indirect producer')
    if used != {b.id for b in state.battlecry_history if b.indirect_body_id is not None}:
        raise ValueError('Indirect Battlecry borrowed an absent producer')


def validate_boundary(game):
    state = game._state; registry = game.registry
    queue = (*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    pending = [r for r in state.indirect_body_sequences if not r.finished and not r.interrupted]
    ends = [w for w in queue if type(w) is FinishIndirectBodies]
    advances = [w for w in queue if type(w) is AdvanceIndirectBodies]
    if (len(ends) != len(pending) or len(advances) != len(pending) or
            sorted(w.accepted.id for w in ends) != [r.id for r in pending] or
            sorted(w.accepted.id for w in advances) != [r.id for r in pending]):
        raise ValueError('Indirect body progress lost its complete producer continuation')
    proofs = [w.proof for w in queue if type(w) is FinishIndirectInvocation]
    if sorted(p.receipt.record_id for p in proofs) != sorted(r.active_battlecry_id for r in pending if r.active_battlecry_id is not None):
        raise ValueError('Indirect active bodies lost or duplicated their original invocation proof')
    for work in (*ends,*advances): anchor(state,registry,work.accepted)
    for root in pending:
        end = next(w for w in ends if w.accepted.id == root.id)
        onward = next(w for w in advances if w.accepted.id == root.id)
        if queue.index(onward) >= queue.index(end): raise ValueError('Indirect next body must precede producer Finish')
    from .battlecries import FinishBattlecry
    for proof in proofs:
        validate_proof(proof,registry)
        root = root_for(state,proof.receipt.root_id)
        if root.receipts[-1] != proof.receipt: raise ValueError('Indirect pending proof borrowed a different original input')
        marker = FinishIndirectInvocation(proof)
        onward = next(w for w in advances if w.accepted.id == root.id)
        if queue.index(marker) >= queue.index(onward): raise ValueError('Indirect invocation must finish before its next body')
        record = state.battlecry_history[proof.receipt.record_id-1]
        closer = FinishBattlecry(record.id)
        if not record.completed and (closer not in queue or queue.index(closer) >= queue.index(marker)):
            raise ValueError('Indirect proof cannot finish before its accepted Battlecry')


def interrupt(state):
    for root in tuple(state.indirect_body_sequences):
        if not root.finished and not root.interrupted:
            put(state,replace(root,interrupted=True,active_battlecry_id=None))


def validate_terminal_queue(r, queue):
    from types import SimpleNamespace
    validate_boundary(SimpleNamespace(_state=r.state,registry=r.registry,
        _frame=SimpleNamespace(prefix=(),continuation=tuple(queue))))


def array(value):
    if type(value) is not list: raise ValueError('Indirect body wire arrays require JSON lists')
    return value


def reference_from_dict(value):
    row = _row(value,BodyTargetReference)
    carrier = _row(row['carrier'],BodyReference); carrier['zone'] = Zone(carrier['zone'])
    row['carrier'] = BodyReference(**carrier)
    return BodyTargetReference(**row)


def selection_from_dict(value):
    row = _row(value,IndirectTargetSelection)
    part = _row(row['partition'],AutomaticTargetPartition)
    part['preference'] = AutomaticTargetPreference(part['preference'])
    part['mode'] = TargetMode(part['mode']) if part['mode'] is not None else None
    for key in ('excluded_ids','legal_ids','enemy_ids','selection_ids'): part[key] = tuple(array(part[key]))
    row['partition'] = AutomaticTargetPartition(**part)
    for key in ('rng_before','rng_after'): row[key] = rng_from_json(row[key])
    return IndirectTargetSelection(**row)


def receipt_from_dict(value):
    row = _row(value,IndirectInvocationReceipt)
    row['payload'] = BattlecryPayload(**_row(row['payload'],BattlecryPayload))
    row['conditions'] = BodyPlayConditions(**_row(row['conditions'],BodyPlayConditions))
    row['combo_play_ids'] = tuple(array(row['combo_play_ids']))
    row['selection'] = selection_from_dict(row['selection'])
    if row['observation'] is not None:
        observed = _row(row['observation'],PaidTargetObservation)
        observed['references'] = tuple(tuple(array(item)) for item in array(observed['references']))
        row['observation'] = PaidTargetObservation(**observed)
    return IndirectInvocationReceipt(**row)


def sequence_from_dict(value):
    row = _row(value,IndirectBodySequence); origin = _row(row['origin'],IndirectBodyOrigin)
    origin['binding'] = IndirectBattlecryBinding(**_row(origin['binding'],IndirectBattlecryBinding))
    origin['bodies'] = tuple(reference_from_dict(ref) for ref in array(origin['bodies']))
    row['origin'] = IndirectBodyOrigin(**origin)
    row['receipts'] = tuple(receipt_from_dict(ref) for ref in array(row['receipts']))
    return IndirectBodySequence(**row)


def register(mechanics):
    for payload in (IndirectBattlecryBinding,IndirectBodyOrigin,IndirectTargetSelection,
            IndirectInvocationReceipt,IndirectBodySequence,IndirectInvocationProof,
            BodyTargetReference,BodyPlayConditions,AutomaticTargetPartition,AutomaticTargetPreference):
        if payload not in mechanics.payload_types:
            mechanics.register_payload_type(payload)
    mechanics.register(AdvanceIndirectBodies,advance)
    mechanics.register(FinishIndirectBodies,finish)
    mechanics.register(FinishIndirectInvocation,finish_invocation)
