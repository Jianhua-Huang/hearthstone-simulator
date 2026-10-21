"""R-133: repeat attachments belong to one physical spell, frozen on hand play.

They do not grant player budgets or board auras. Explicit current copies inherit
independent attachments; physical storage moves retain them unless reset=True.
Automatic casts and history recasts do not use this hand-play-only property.
"""
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

from .effects import Effect, _integer, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import AbilityInstance, CardType, GameState, SpellRepeatSpec, SpellSchool, Zone
from .allocation_facts import SourceAllocationFact, validate_allocation
from .arcane_dragon_providers import NativeRepeatPlan
from .pools import PoolQuery
from .rules import Ruleset
from .zones import CardReference, reference_entity, reference_value


@dataclass(frozen=True)
class GrantCardSpellRepeat(Effect):
    card: CardReference
    casts: int = 2
    source_id: int | None = None
    expires_turn: int | None = None
    automatic: bool = False

    def __post_init__(self):
        reference_value(self.card)
        _integer(self.casts, 'card spell casts', 2)
        _source(self.source_id)
        if self.expires_turn is not None: _integer(self.expires_turn, 'card spell expiry', 1)
        if type(self.automatic) is not bool or self.automatic and (self.casts != 2 or self.source_id is None):
            raise ValueError('All-CAST card grants currently require two casts and their original source')


@dataclass(frozen=True)
class RemoveCardSpellRepeat(Effect):
    card: CardReference
    ability_id: int
    source_id: int | None = None

    def __post_init__(self):
        reference_value(self.card)
        _integer(self.ability_id, 'card spell attachment', 1)
        _source(self.source_id)


def target(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, getattr(effect, 'expires_turn', None))
    if r.registry.card(effect.card.card_id).kind != CardType.SPELL:
        raise ResolutionError('Card spell repetition requires a stored spell')
    return reference_entity(r, effect.card)


def attach(state, entity, casts, source_id=None, expires_turn=None, *, automatic=False):
    if type(automatic) is not bool or automatic and (casts != 2 or source_id is None):
        raise ValueError('All-CAST card attachment requires two casts and its original source')
    ability = AbilityInstance(attachment_id(state), 'card_cast_repeat' if automatic else 'card_spell_repeat',
        source_id=source_id, expires_turn=expires_turn,
        spell_repeat=SpellRepeatSpec(casts, class_mode='any'))
    entity.abilities.append(ability)
    return ability


def grant(r, effect):
    entity = target(r, effect)
    if entity is None: return
    ability = attach(r.state, entity, effect.casts, effect.source_id, effect.expires_turn, automatic=effect.automatic)
    r.emit('card_spell_repeat_added', target_id=entity.id, source_id=effect.source_id,
        player_id=entity.controller, amount=effect.casts, ability_id=ability.id)


def remove(r, effect):
    entity = target(r, effect)
    if entity is None: return
    ability = next((a for a in entity.abilities if a.kind in ('card_spell_repeat','card_cast_repeat') and a.id==effect.ability_id), None)
    if ability is None: return
    entity.abilities.remove(ability)
    r.emit('card_spell_repeat_removed', target_id=entity.id, source_id=effect.source_id,
        player_id=entity.controller, amount=ability.spell_repeat.casts, ability_id=ability.id)


def capture(entity):
    return tuple(a for a in entity.abilities if a.kind in ('card_spell_repeat','card_cast_repeat'))


def execution_count(play):
    return max((a.spell_repeat.casts for a in play.card_spell_repeats), default=1)


def public_repeats(entity):
    return [dict(casts=a.spell_repeat.casts, expires_turn=a.expires_turn) for a in capture(entity)]


def validate_history(state):
    """A capture can outlive its attachment; an existing identity cannot mutate."""
    plays = [p for p in state.play_history if p.card_spell_repeats]
    if not plays: return
    live, unrelated = _live_materials(state)
    captured = {}
    for play in plays:
        for a in play.card_spell_repeats:
            if (a.id>=state.next_attachment_id or a.id in unrelated or
                    a.source_id is not None and a.source_id not in state.entities or
                    a.expires_turn is not None and a.expires_turn<play.turn):
                raise ValueError('Invalid captured card spell attachment')
            value = (play.source_id,a)
            if a.id in live and live[a.id]!=value or a.id in captured and captured[a.id]!=value:
                raise ValueError('Card spell capture identity or content changed')
            captured[a.id] = value
        repeat = next((x for x in state.spell_repeats if x.play_id==play.id), None)
        if repeat is not None and repeat.casts<execution_count(play):
            raise ValueError('Spell repetition lost a captured card contribution')
        if play.completed and not play.countered and repeat is None:
            raise ValueError('Accepted card spell repeat requires a repetition record')


def register(mechanics):
    mechanics.register(GrantCardSpellRepeat, grant)
    mechanics.register(RemoveCardSpellRepeat, remove)
    mechanics.register(DrawMatchingSpellRepeat, draw_matching)
    for kind in (CardCastRepeatPlan, CardCastRepeatProof): mechanics.register_payload_type(kind)


@dataclass(frozen=True)
class DrawMatchingSpellRepeat(Effect):
    player_id: int
    query: PoolQuery
    source_id: int
    school: SpellSchool

    def __post_init__(self):
        from .effects import _player
        _player(self.player_id); _integer(self.source_id, 'drawn repeat source', 1)
        if type(self.query) is not PoolQuery or self.query.kinds != (CardType.SPELL,) or type(self.school) is not SpellSchool:
            raise ValueError('Drawn repeat grant requires its complete spell query and explicit school')
        self.query.__post_init__()

    def validate_in_state(self, state):
        self.__post_init__()
        if self.source_id not in state.entities: raise ValueError('Drawn repeat grant has an unknown original source')


def draw_matching(r, effect):
    from .draw_casts import draw_one
    from .zones import zone_candidates, source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    candidates = zone_candidates(r, effect.player_id, Zone.DECK, effect.query, effect.player_id, effect.source_id)
    if not candidates: return ()
    card = r.game._rng.choice(candidates)
    entity = reference_entity(r, card)
    if r.registry.card(entity.card_id).spell_school == effect.school:
        # Use the original pre-draw window, including cast-when-drawn carriers.
        grant(r, GrantCardSpellRepeat(card, 2, effect.source_id, automatic=True))
    return draw_one(r, effect.player_id, card=card, source_id=effect.source_id)


@dataclass(frozen=True)
class CardCastRepeatPlan:
    source: SourceAllocationFact
    player_id: int
    grants: tuple[AbilityInstance, ...]
    attachment_limit: int
    native: NativeRepeatPlan | None = None

    def __post_init__(self):
        from .effects import _player
        _player(self.player_id); _integer(self.attachment_limit, 'original repeat attachment frontier', 1)
        if type(self.source) is not SourceAllocationFact or self.source.kind != CardType.SPELL:
            raise ValueError('Card CAST repetition requires its original physical spell')
        self.source.__post_init__()
        if type(self.grants) is not tuple or not self.grants:
            raise ValueError('Card CAST repetition requires its complete nonempty original grant inventory')
        previous = 0
        for grant in self.grants:
            if type(grant) is not AbilityInstance or grant.kind != 'card_cast_repeat':
                raise ValueError('Automatic card repetition cannot borrow a hand-only property')
            grant.__post_init__()
            if not previous < grant.id < self.attachment_limit:
                raise ValueError('Card repetition requires unique original attachment order')
            previous = grant.id
        if self.native is not None:
            if type(self.native) is not NativeRepeatPlan:
                raise ValueError('Card repetition requires the existing typed native contribution')
            self.native.__post_init__()
            if (self.native.source, self.native.player_id) != (self.source, self.player_id):
                raise ValueError('Card and native repetition borrowed different acceptance windows')


@dataclass(frozen=True)
class CardCastRepeatProof:
    before_state: GameState
    rules: Ruleset
    plan: CardCastRepeatPlan

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.plan) is not CardCastRepeatPlan):
            raise ValueError('Card repetition lost its complete original acceptance window')
        self.rules.__post_init__(); self.plan.__post_init__()


def _card_plan(state, entity, player_id, native):
    from .lifecycle import active_abilities
    grants = tuple(sorted(active_abilities(entity, 'card_cast_repeat'), key=lambda a:a.id))
    if not grants: return None
    if any(a.expires_turn is not None and a.expires_turn < state.turn for a in grants):
        raise ValueError('Automatic card repeat cannot accept an already expired property')
    return CardCastRepeatPlan(SourceAllocationFact.capture(state, entity), player_id, grants,
        state.next_attachment_id, native)


def capture_automatic(r, entity, player_id, native):
    plan = _card_plan(r.state, entity, player_id, native)
    return None if plan is None else CardCastRepeatProof(deepcopy(r.state), r.rules, plan)


def _live_materials(state):
    live = {a.id:(entity.id,a) for entity in state.entities.values() for a in entity.abilities}
    unrelated = {a.id for entity in state.entities.values() for a in entity.enchantments}
    for player in state.players.values():
        unrelated.update(a.id for a in (*player.cost_modifiers,*player.player_effects,
            *player.battlecry_modifiers,*player.combo_modifiers,*player.spell_modifiers,*player.choose_both_modifiers))
    return live, unrelated


def validate_automatic_proof(proof, registry):
    from .arcane_dragon_providers import capture as capture_native
    proof.__post_init__(); state = deepcopy(proof.before_state)
    entity = state.entities.get(proof.plan.source.entity_id)
    if entity is None or state.status != 'playing':
        raise ValueError('Card repetition lost its actual pre-CAST source window')
    probe = SimpleNamespace(state=state, registry=registry, rules=proof.rules,
        player=lambda pid:state.players[pid], game=SimpleNamespace(ruleset=proof.rules))
    native = capture_native(probe, entity, proof.plan.player_id)
    if _card_plan(state, entity, proof.plan.player_id, native) != proof.plan:
        raise ValueError('Card repetition changed its complete original grants or native contributors')


def validate_automatic_plan(state, registry, plan, *, closed=False):
    plan.__post_init__(); validate_allocation(state, registry, plan.source, closed=closed)
    if plan.attachment_limit > state.next_attachment_id:
        raise ValueError('Card repetition borrowed a future attachment frontier')
    live, unrelated = _live_materials(state)
    for grant in plan.grants:
        # Removed/expired accepted properties remain part of the frozen plan.
        if grant.source_id not in state.entities:
            raise ValueError('Card repetition has an unknown original grant source')
        if grant.id in unrelated or grant.id in live and live[grant.id] != (plan.source.entity_id, grant):
            raise ValueError('Card repetition borrowed another physical attachment or changed its material')
    if plan.native is not None:
        from .arcane_dragon_providers import validate_plan
        validate_plan(state, registry, plan.native, closed=closed)
