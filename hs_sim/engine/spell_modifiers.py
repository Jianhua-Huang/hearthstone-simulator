"""Player spell budgets captured once at hand commitment (R-131).

Board auras retain their later payload-acceptance window. Automatic casts do not
enter this contract. Receipts survive consumed/removed policies and retain the
hero class used for eligibility, independently of subsequent hero replacement.
"""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import attachment_id
from .model import CardClass, CardType, SpellRepeatModifier, SpellRepeatSpec, SpellPolicyReceipt


@dataclass(frozen=True)
class AddSpellRepeatModifier(Effect):
    player_id: int
    spec: SpellRepeatSpec = SpellRepeatSpec(class_mode='any')
    source_id: int | None = None
    uses: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        if type(self.spec) is not SpellRepeatSpec:
            raise ValueError('Player spell modifier requires SpellRepeatSpec')
        self.spec.__post_init__()
        if self.spec.match is not None and self.spec.match.source_eligibility is not None:
            raise ValueError('Player spell policies cannot require a physical board carrier')
        if self.uses is not None: _integer(self.uses, 'spell modifier uses', 1)
        if self.expires_turn is not None: _integer(self.expires_turn, 'spell modifier expiry', 1)


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


def emit_change(r, kind, player_id, modifier, *, uses_remaining=None, play_id=None):
    r.emit(kind, player_id=player_id, modifier_id=modifier.id, policy_source_id=modifier.source_id,
        play_id=play_id, **public_modifier(modifier, uses_remaining=uses_remaining,
            consumed=kind=='spell_modifier_used'))


def add(r, effect):
    from .resolver import validate_attachment_source
    effect.__post_init__()
    from .repeat_matching import validate_repeat_cost_declaration
    validate_repeat_cost_declaration(r.registry, effect.spec)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    source = r.state.entities.get(effect.source_id)
    modifier = SpellRepeatModifier(attachment_id(r.state), effect.spec, effect.source_id,
        source.card_id if source else None, r.state.turn, effect.uses, effect.expires_turn)
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
