"""Player spell budgets captured once at hand commitment (R-131).

Board auras retain their later payload-acceptance window. Explicit finite school
policies also enter the existing automatic CAST acceptance. Receipts retain the
hero class used for eligibility, independently of subsequent hero replacement.
"""
from dataclasses import asdict, dataclass, replace
import json

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import (CardClass, CardType, SpellRepeatModifier, SpellRepeatSpec, SpellPolicyReceipt,
    validate_automatic_spell_budget)

MATERIAL = '_spell_modifier_material'
AUTOMATIC_CAST = '_automatic_cast_id'


@dataclass(frozen=True)
class AddSpellRepeatModifier(Effect):
    player_id: int
    spec: SpellRepeatSpec = SpellRepeatSpec(class_mode='any')
    source_id: int | None = None
    uses: int | None = None
    expires_turn: int | None = None
    automatic: bool = False

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.spec) is not SpellRepeatSpec:
            raise ValueError('Player spell modifier requires SpellRepeatSpec')
        self.spec.__post_init__()
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player spell policies cannot require a physical board carrier')
        if self.uses is not None: _integer(self.uses, 'spell modifier uses', 1)
        if self.expires_turn is not None: _integer(self.expires_turn, 'spell modifier expiry', 1)
        validate_automatic_spell_budget(self.spec, self.source_id, self.uses, self.expires_turn, self.automatic)


@dataclass(frozen=True)
class RemoveSpellRepeatModifier(Effect):
    player_id: int
    modifier_id: int

    def __post_init__(self):
        _player(self.player_id); _integer(self.modifier_id, 'spell modifier', 1)


def matches(spec, definition, hero_class, *, submitted_cost=None, cost_facts=None):
    from .repeat_matching import repeat_matches
    return repeat_matches(spec, definition, hero_class, submitted_cost=submitted_cost, cost_facts=cost_facts)


def public_modifier(modifier, *, uses_remaining=None, consumed=False):
    from .repeat_matching import repeat_match_public_to_dict
    return dict(casts=modifier.spec.casts, class_mode=modifier.spec.class_mode,
        match=repeat_match_public_to_dict(modifier.spec.match),
        uses_remaining=uses_remaining if consumed else modifier.uses_remaining,
        expires_turn=modifier.expires_turn)


def emit_change(r, kind, player_id, modifier, *, uses_remaining=None, play_id=None, automatic_cast_id=None):
    private = {}
    if modifier.automatic and kind == 'spell_modifier_added':
        private[MATERIAL] = json.dumps(asdict(modifier), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if automatic_cast_id is not None: private[AUTOMATIC_CAST] = automatic_cast_id
    r.emit(kind, player_id=player_id, modifier_id=modifier.id, policy_source_id=modifier.source_id,
        play_id=play_id, **public_modifier(modifier, uses_remaining=uses_remaining,
            consumed=kind=='spell_modifier_used'), **private)


def add(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    from .repeat_matching import validate_repeat_cost_declaration
    validate_repeat_cost_declaration(r.registry, effect.spec)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    source = r.state.entities.get(effect.source_id)
    modifier = SpellRepeatModifier(attachment_id(r.state), effect.spec, effect.source_id,
        source.card_id if source else None, r.state.turn, effect.uses, effect.expires_turn, effect.automatic)
    r.player(effect.player_id).spell_modifiers.append(modifier)
    emit_change(r, 'spell_modifier_added', effect.player_id, modifier)


def remove(r, effect):
    player = r.player(effect.player_id)
    modifier = next((m for m in player.spell_modifiers if m.id==effect.modifier_id), None)
    if modifier is None: return
    player.spell_modifiers.remove(modifier)
    emit_change(r, 'spell_modifier_removed', player.id, modifier)


def captured_modifiers(state, play_id):
    return tuple(m for receipt in state.spell_policy_receipts if receipt.play_id==play_id
        for m in receipt.modifiers)


def capture(r, play):
    if play.kind != CardType.SPELL: return
    if any(x.play_id==play.id for x in r.state.spell_policy_receipts):
        raise ResolutionError('Spell policies were already captured for this play')
    player = r.player(play.player_id)
    if play.spell_submission is None:
        raise ResolutionError('Spell policy consumption requires its already accepted submission facts')
    modifiers = play.spell_submission.modifiers
    current = {m.id: m for m in player.spell_modifiers}
    if any(current.get(m.id) != m for m in modifiers):
        raise ResolutionError('Accepted Spell policies changed before their one actual consumption')
    if not modifiers: return
    r.state.spell_policy_receipts.append(SpellPolicyReceipt(len(r.state.spell_policy_receipts)+1,
        play.id, play.spell_submission.hero_class, modifiers))
    ids = {m.id for m in modifiers if m.uses_remaining is not None}
    updated, changes = [], []
    for m in player.spell_modifiers:
        if m.id not in ids:
            updated.append(m)
            continue
        remaining = m.uses_remaining-1
        if remaining: updated.append(replace(m, uses_remaining=remaining))
        changes.append((m, remaining))
    player.spell_modifiers = updated
    for m, remaining in changes:
        emit_change(r, 'spell_modifier_used', player.id, m, uses_remaining=remaining, play_id=play.id)


def validate_receipts(state, registry):
    from .play_history import play_record
    if type(state.spell_policy_receipts) is not list: raise ValueError('Spell receipts require a list')
    unrelated_ids = {a.id for e in state.entities.values() for a in (*e.abilities,*e.enchantments)} if state.spell_policy_receipts else set()
    for p in state.players.values():
        unrelated_ids.update(m.id for m in (*p.cost_modifiers,*p.battlecry_modifiers,*p.combo_modifiers,*p.choose_both_modifiers,*p.player_effects))
    previous, captured = 0, {}
    for index, receipt in enumerate(state.spell_policy_receipts, 1):
        if type(receipt) is not SpellPolicyReceipt: raise ValueError('Invalid spell receipt')
        receipt.__post_init__()
        play = play_record(state, receipt.play_id)
        if receipt.id!=index or play.id<=previous or play.kind!=CardType.SPELL:
            raise ValueError('Invalid spell receipt identity, order or play')
        for m in receipt.modifiers:
            if (m.id>=state.next_attachment_id or m.id in unrelated_ids or m.created_turn>play.turn or
                    m.expires_turn is not None and m.expires_turn<play.turn or
                    m.source_id is not None and m.source_id not in state.entities or
                    not matches(m.spec, registry.card(play.card_id), receipt.hero_class,
                        submitted_cost=play.submitted_cost, cost_facts=play.spell_submission.cost_facts)):
                raise ValueError('Invalid captured spell policy')
            if m.source_card_id is not None: registry.card(m.source_card_id)
            if m.id in captured:
                owner, old = captured[m.id]
                if (owner!=play.player_id or old.uses_remaining==1 or
                        m!=replace(old, uses_remaining=None if old.uses_remaining is None else old.uses_remaining-1)):
                    raise ValueError('Spell receipts disagree on remaining uses or owner')
            captured[m.id] = (play.player_id, m)
        repeat = next((x for x in state.spell_repeats if x.play_id==play.id), None)
        if repeat is not None and repeat.casts<max(m.spec.casts for m in receipt.modifiers):
            raise ValueError('Spell repeat count differs from captured policies')
        if play.completed and not play.countered and repeat is None:
            raise ValueError('Accepted spell policies require a repetition record')
        previous = play.id
    for player in state.players.values():
        for m in player.spell_modifiers:
            if m.id not in captured: continue
            owner, old = captured[m.id]
            if (owner!=player.id or old.uses_remaining==1 or
                    m!=replace(old, uses_remaining=None if old.uses_remaining is None else old.uses_remaining-1)):
                raise ValueError('Live spell policy differs from its last captured use')


def consume_automatic(r, cast_id, modifiers):
    """Accept all matching one-use budgets once, before ordinary automatic payload."""
    if not modifiers: return
    row = r.state.cast_history[cast_id-1]
    player = r.player(row.player_id)
    current = {m.id:m for m in player.spell_modifiers}
    if any(not m.automatic or current.get(m.id) != m for m in modifiers):
        raise ResolutionError('Automatic spell policy changed before its original consumption')
    ids = {m.id for m in modifiers}
    player.spell_modifiers = [m for m in player.spell_modifiers if m.id not in ids]
    for m in modifiers:
        emit_change(r, 'spell_modifier_used', player.id, m, uses_remaining=0, automatic_cast_id=cast_id)


def validate_automatic_usage(game, plans):
    """Bind the one-use inventory to actual manual or automatic consumption.

    This is structural history validation, not authentication of unsigned saves.
    It also preserves unspent schools and explicit removals across suspension.
    """
    from .card_spell_repeats import CardCastRepeatPlan
    from .hero_health_history import effective_events
    from .play_history import play_record
    from .serialization import _spell_modifier_from_dict
    state, registry = game._state, game.registry
    expected = {}
    def claim(player_id, modifier, play_id=None, cast_id=None):
        if modifier.id in expected:
            raise ValueError('One-use spell policy was consumed by more than one original cast')
        expected[modifier.id] = (player_id, modifier, play_id, cast_id)
    for receipt in state.spell_policy_receipts:
        pid = play_record(state, receipt.play_id).player_id
        for m in receipt.modifiers:
            if m.automatic: claim(pid, m, play_id=receipt.play_id)
    for cast_id, work in plans.items():
        if type(work.plan) is CardCastRepeatPlan:
            for m in work.plan.player_modifiers: claim(work.plan.player_id, m, cast_id=cast_id)
    active, added, spent, checked_plays = {}, {}, set(), set()
    def check_inventory(pid, card_id, modifiers):
        eligible = tuple(m for owner,m in active.values() if owner == pid and
            matches(m.spec, registry.card(card_id), None))
        if eligible != tuple(modifiers):
            raise ValueError('Automatic spell policy lost a matching original school contribution')
    for event in effective_events(game._events):
        data = dict(event.data); mid = data.get('modifier_id')
        if event.kind == 'spell_cast_started':
            row = state.cast_history[data['cast_id']-1]
            if row.origin in ('effect','draw','history') and row.failure is None:
                work = plans.get(row.id)
                modifiers = work.plan.player_modifiers if work is not None and type(work.plan) is CardCastRepeatPlan else ()
                check_inventory(row.player_id, row.card_id, modifiers)
        if MATERIAL in data:
            if event.kind != 'spell_modifier_added' or type(data[MATERIAL]) is not str:
                raise ValueError('Automatic spell policy lost its original addition event')
            m = _spell_modifier_from_dict(json.loads(data[MATERIAL]))
            if (not m.automatic or mid != m.id or mid in added or event.player_id not in (1,2) or
                    m.id >= state.next_attachment_id or m.source_id not in state.entities or m.created_turn > state.turn):
                raise ValueError('Automatic spell policy has an invalid original allocation')
            registry.card(m.source_card_id)
            added[mid] = active[mid] = (event.player_id, m)
            expected_data = dict(modifier_id=mid, policy_source_id=m.source_id, play_id=None,
                **public_modifier(m), **{MATERIAL:data[MATERIAL]})
        elif event.kind in ('spell_modifier_used', 'spell_modifier_removed', 'spell_modifier_expired') and mid in added:
            if mid not in active:
                raise ValueError('Automatic spell policy was already retired')
            use = expected.get(mid)
            if event.kind == 'spell_modifier_used' and use is not None and use[2] is not None and use[2] not in checked_plays:
                play = play_record(state, use[2])
                modifiers = next(x.modifiers for x in state.spell_policy_receipts if x.play_id == play.id)
                check_inventory(play.player_id, play.card_id, tuple(m for m in modifiers if m.automatic))
                checked_plays.add(play.id)
            pid, m = active.pop(mid)
            expected_data = dict(modifier_id=mid, policy_source_id=m.source_id, play_id=None,
                **public_modifier(m))
            if event.kind == 'spell_modifier_used':
                use = expected.get(mid)
                if use is None or use[:2] != (pid, m):
                    raise ValueError('Automatic spell policy use has no exact original acceptance')
                _, _, play_id, cast_id = use
                expected_data.update(play_id=play_id, uses_remaining=0)
                if cast_id is not None: expected_data[AUTOMATIC_CAST] = cast_id
                spent.add(mid)
            elif event.kind == 'spell_modifier_expired':
                owner = next((row for row in reversed(state.owner_turn_history)
                    if row.start_event < event.sequence), None)
                if (mid in expected or m.expires_turn is None or owner is None or
                        owner.turn != m.expires_turn or owner.end_event is None or
                        owner.end_event >= event.sequence):
                    raise ValueError('Automatic spell policy expiry lost its actual original turn end')
            elif event.kind != 'spell_modifier_removed' or mid in expected:
                raise ValueError('Automatic spell policy cannot expire or replace a consumed original use')
            if event.player_id != pid:
                raise ValueError('Automatic spell policy changed its original owner')
        elif event.kind == 'spell_modifier_expired' and mid in added:
            raise ValueError('Automatic spell policy cannot expire an already retired original use')
        elif AUTOMATIC_CAST in data:
            raise ValueError('Automatic spell policy consumption has no original addition')
        else: continue
        if (data != expected_data or event.source_id is not None or event.target_id is not None or event.amount != 0):
            raise ValueError('Automatic spell policy event changed its exact original material or use')
    current = {m.id:(p.id,m) for p in state.players.values() for m in p.spell_modifiers if m.automatic}
    if current != active or spent != set(expected):
        raise ValueError('Automatic spell policies lost an unspent school or an original use witness')


def expire(r, turn):
    expired = []
    for player in r.state.players.values():
        keep = []
        for modifier in player.spell_modifiers:
            if modifier.expires_turn is not None and modifier.expires_turn<=turn:
                expired.append((player.id, modifier))
            else: keep.append(modifier)
        player.spell_modifiers = keep
    for player_id, modifier in expired: emit_change(r, 'spell_modifier_expired', player_id, modifier)
    return bool(expired)


def register(mechanics):
    mechanics.register(AddSpellRepeatModifier, add)
    mechanics.register(RemoveSpellRepeatModifier, remove)
