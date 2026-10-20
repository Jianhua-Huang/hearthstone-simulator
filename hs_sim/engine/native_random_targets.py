"""Native random-target domains, separate from ordinary automatic targeting.

These pure host plans are preparation for actual activation consumers. They do
not dispatch actions, rewrite accepted histories or expose hidden candidates.
Attack replacement ignores voluntary Taunt/Stealth and attacker restrictions;
that inherited replacement policy still awaits CN calibration.
"""
from copy import deepcopy
from dataclasses import dataclass
from random import Random

from .allocation_facts import SourceAllocationFact
from .effects import _integer, _player, _source
from .lifecycle import active_abilities
from .model import CardType, TargetMode, Zone


def validate_source_card(registry, card_id):
    card = registry.card(card_id)
    if card.kind != CardType.MINION or card.choice_only or card.starship_for:
        raise ValueError('Native random targets require an ordinary minion declaration')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    markers = tuple(a for a in abilities if a.kind == 'random_targets')
    if not markers: return
    if kind != CardType.MINION or not set((card_id, *components)) & registry.random_target_cards:
        raise ValueError('Random target marker borrowed an undeclared physical minion')
    for marker in markers: marker.__post_init__()


@dataclass(frozen=True)
class RandomTargetCarrier:
    source: SourceAllocationFact
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact: raise ValueError('Typed random-target source required')
        self.source.__post_init__()
        if self.source.kind != CardType.MINION or self.source.zone != Zone.BOARD:
            raise ValueError('Random target policy requires an actual battlefield minion')
        if type(self.ability_ids) is not tuple or not self.ability_ids or self.ability_ids != tuple(sorted(set(self.ability_ids))):
            raise ValueError('Complete ordered native marker identities required')
        for value in self.ability_ids: _integer(value, 'random target marker', 1)


def current_sources(state, registry):
    if not registry.random_target_cards: return ()
    result = []
    for entity in sorted(state.entities.values(), key=lambda e:(e.entered_order, e.id)):
        if (entity.kind != CardType.MINION or entity.zone != Zone.BOARD or
                not entity.active or entity.silenced or entity.health <= 0 or entity.doomed): continue
        markers = active_abilities(entity, 'random_targets')
        if not markers: continue
        validate_carrier(registry, entity.card_id, entity.kind, markers, entity.components)
        result.append(RandomTargetCarrier(SourceAllocationFact.capture(state, entity), tuple(sorted(a.id for a in markers))))
    return tuple(result)


@dataclass(frozen=True)
class NativeTargetPartition:
    source: SourceAllocationFact
    player_id: int
    origin: str
    definition_digest: str
    submitted_target_id: int | None
    mode: TargetMode | None
    carriers: tuple[RandomTargetCarrier, ...]
    candidates: tuple[SourceAllocationFact, ...]
    applied: bool
    window_id: int | None = None

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact: raise ValueError('Native target partition requires its actual source')
        self.source.__post_init__(); _player(self.player_id); _source(self.submitted_target_id)
        if self.origin not in ('manual_card','battlecry','combo','hero_power','minion_ability','location','hand_action','attack','on_play'):
            raise ValueError('Unknown native target activation origin')
        if type(self.definition_digest) is not str or not self.definition_digest: raise ValueError('Effective target contract digest required')
        if self.mode is not None and type(self.mode) is not TargetMode: raise ValueError('Typed target mode required')
        if type(self.applied) is not bool: raise ValueError('Explicit native target applicability required')
        for rows, cls in ((self.carriers,RandomTargetCarrier),(self.candidates,SourceAllocationFact)):
            if type(rows) is not tuple or any(type(x) is not cls for x in rows): raise ValueError('Immutable complete native target domain required')
            for row in rows: row.__post_init__()
        if len({x.source.entity_id for x in self.carriers}) != len(self.carriers): raise ValueError('Duplicate physical random-target source')
        ids = self.target_ids
        if ids != tuple(sorted(set(ids))): raise ValueError('Native target candidates must be complete, unique and ordered')
        if self.applied and (not self.carriers or self.submitted_target_id is None or self.mode is None):
            raise ValueError('Native random replacement requires an originally targeted activation')
        if not self.applied and self.candidates: raise ValueError('Inactive native policy cannot create candidates')
        if self.origin == 'attack':
            _integer(self.window_id,'original proposed attack window',1)
            if any(x.controller == self.player_id or x.kind not in (CardType.MINION,CardType.HERO) or
                    x.zone not in (Zone.BOARD,Zone.HERO) for x in self.candidates):
                raise ValueError('Attack redirection borrowed a friendly or non-character target')
        elif self.window_id is not None: raise ValueError('Ordinary target domains cannot borrow an attack window')

    @property
    def target_ids(self): return tuple(x.entity_id for x in self.candidates)


def manual_partition(r, source, definition, submitted_target_id, *, player_id=None, origin='manual_card'):
    """Manual selectable protection and declared friendly/enemy/type predicates.

Unlike automatic spell casting, this cannot select an otherwise unselectable
elusive/stealthed/immune enemy. The caller owns the actual acceptance window.
"""
    from dataclasses import asdict
    from hs_sim.targets import canonical_digest
    from .model import CardDefinition
    from .targeting import accepts_target, effective_target_spec, effect_target_context
    if type(definition) is not CardDefinition or source is not r.state.entities.get(source.id):
        raise ValueError('Native targets require a current physical source and effective definition')
    r.registry.card(definition.id)
    player_id = source.controller if player_id is None else player_id
    _player(player_id); _source(submitted_target_id)
    if submitted_target_id is not None and submitted_target_id not in r.state.entities:
        raise ValueError('Native targets borrowed an unknown submitted target')
    actor = deepcopy(source); actor.controller = player_id
    spec = effective_target_spec(r.state,r.registry,actor,definition)
    carriers = current_sources(r.state,r.registry)
    applied = bool(carriers and submitted_target_id is not None and spec is not None)
    if r.registry.target_visibility(definition.target_rule)=='player':
        from .player_target_inputs import live_factory
        context=live_factory(r,actor)
    else:
        context=effect_target_context(r,actor)
    ids = tuple(i for i in sorted(r.state.entities) if applied and accepts_target(r.state,r.registry,
        actor,definition,i,context_factory=context,automatic=False))
    return NativeTargetPartition(SourceAllocationFact.capture(r.state,source),player_id,origin,
        canonical_digest(asdict(definition)),submitted_target_id,None if spec is None else spec.mode,
        carriers,tuple(SourceAllocationFact.capture(r.state,r.state.entities[i])for i in ids),applied)


def attack_partition(r, window):
    """Replacement after a real declaration; never make an illegal attack legal."""
    from .interrupts import find_window, attack_live
    from .model import ActionWindow
    if type(window) is not ActionWindow or window.kind != 'attack' or find_window(r.state,window.id) != window:
        raise ValueError('Native attack policy requires its actual open proposed attack')
    source = r.state.entities[window.source_id]
    carriers = current_sources(r.state,r.registry)
    applied = bool(carriers and attack_live(r.state,window))
    candidates = tuple(SourceAllocationFact.capture(r.state,entity)for _,entity in sorted(r.state.entities.items())
        if applied and entity.controller != source.controller and entity.is_character and
        entity.zone in (Zone.BOARD,Zone.HERO) and entity.active and entity.health > 0 and not entity.doomed)
    return NativeTargetPartition(SourceAllocationFact.capture(r.state,source),source.controller,'attack',
        'native.proposed-attack.opponent-characters.v1',window.target_id,TargetMode.REQUIRED,
        carriers,candidates,applied,window.id)


@dataclass(frozen=True)
class NativeTargetSelection:
    partition: NativeTargetPartition
    target_id: int | None
    failure: str | None
    rng_before: tuple
    rng_after: tuple

    def __post_init__(self):
        if type(self.partition) is not NativeTargetPartition: raise ValueError('Native target selection lost its complete domain')
        self.partition.__post_init__(); _source(self.target_id)
        from .model import validate_end_turn_rng
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        rng = Random(); rng.setstate(self.rng_before)
        target,failure = _sample(rng,self.partition)
        if (self.target_id,self.failure,self.rng_after) != (target,failure,rng.getstate()):
            raise ValueError('Native target selection changed its original domain or random draw')


def _sample(rng, partition):
    if not partition.applied: return partition.submitted_target_id, None
    if partition.target_ids: return rng.choice(partition.target_ids), None
    return None, 'no_target'


def sample(rng, partition):
    """Explicit RNG operand; no Game mutation, event or activation is invented."""
    if type(rng) is not Random or type(partition) is not NativeTargetPartition:
        raise ValueError('Native target sampling requires its explicit RNG and typed domain')
    partition.__post_init__(); before=rng.getstate();target,failure=_sample(rng,partition)
    return NativeTargetSelection(partition,target,failure,before,rng.getstate())
