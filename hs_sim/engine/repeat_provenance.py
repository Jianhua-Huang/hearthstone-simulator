"""Shared raw attachment inventory and typed repeat-source provenance.

Chronology and original acceptance windows belong to their family validators.
This module checks complete immutable identities without querying witnesses.
"""
from dataclasses import dataclass, replace
from .effects import _integer
from .model import AbilityInstance, DeathrattlePlayerContributor


def checked_live_attachments(state):
    """Build the global catalogue only after checking every raw ID for duplicates.

    This intentionally does not require stable-state invariants: terminal work
    can still own unsettled rows before interruption is recorded.
    """
    entries = []
    identities = set()
    def add(kind, carrier_id, item, identity=None):
        identity = item.id if identity is None else identity
        _integer(identity, 'Global attachment ID', 1)
        if identity in identities:
            raise ValueError('Duplicate global attachment ID in repeat source catalogue')
        identities.add(identity)
        entries.append((identity, (kind, carrier_id, item)))
    for entity in state.entities.values():
        for kind, collection in (('ability', entity.abilities), ('enchantment', entity.enchantments)):
            for item in collection:
                add(kind, entity.id, item)
        if entity.secret_instance_id is not None:
            add('secret_instance', entity.id, entity.secret_instance_id, entity.secret_instance_id)
        if entity.quest_progress is not None:
            add('quest_progress', entity.id, entity.quest_progress)
        if entity.dormancy is not None:
            add('dormancy', entity.id, entity.dormancy)
    for player in state.players.values():
        for kind in ('cost_modifiers', 'battlecry_modifiers', 'combo_modifiers',
                     'spell_modifiers', 'choose_both_modifiers', 'player_effects'):
            for item in getattr(player, kind):
                add(kind, player.id, item)
    return dict(entries)



@dataclass(frozen=True)
class _SourceReference:
    path: tuple
    family: str
    identity: int
    carrier: int | None = None
    value: object = None
    owner: int | None = None
    spec_index: int | None = None
    spec: object = None



def accepted_repeat_source_references(state):
    """Enumerate exact acceptance slots, including later fields on old roots.

ID-only BC/Combo plans retain their typed family. Their original complete
declaration is supplied by the corresponding original attachment inventory;
full contributor receipts retain their own complete immutable source values.
"""
    result = {}

    def add(path, family, identity, *, carrier=None, value=None, owner=None,
            spec_index=None, spec=None):
        if type(identity) is not int or not 0 < identity < state.next_attachment_id:
            raise ValueError('Accepted repeat source has an invalid global attachment identity')
        key = (*path, family, identity, spec_index)
        if key in result:
            raise ValueError('Duplicate accepted repeat source slot')
        result[key] = _SourceReference(tuple(path), family, identity, carrier,
                                      value, owner, spec_index, spec)

    def ids(path, family, plan, owner):
        if plan is None:
            return
        for index, identity in enumerate(plan.contributors):
            # A non-finite player policy is not in consumable_ids either.
            # Keep the logical non-consumable role until the genuine original
            # attachment inventory supplies its physical family.
            typed = family + '_modifiers' if identity in plan.consumable_ids else 'nonconsumable:' + family
            add((*path, index), typed, identity, owner=owner)

    def ability(path, family, source, owner=None):
        add(path, 'ability:' + family, source.ability.id,
            carrier=source.carrier_id, value=source.ability, owner=owner)

    def quote(path, fact):
        for index, source in enumerate(fact.contributions):
            if source.enchantment is not None:
                add((*path, index), 'enchantment', source.enchantment.id,
                    carrier=source.carrier_id, value=source.enchantment, owner=source.player_id)
            elif source.modifier is not None:
                add((*path, index), 'cost_modifiers', source.modifier.id,
                    value=source.modifier, owner=source.player_id)
            else:
                add((*path, index), 'ability:cost_aura', source.ability.id,
                    carrier=source.carrier_id, value=source.ability, owner=source.player_id)

    for play in state.play_history:
        base = ('play', play.id)
        if play.submitted_cost is not None:
            quote((*base, 'submitted_cost'), play.submitted_cost.quote)
        for phase in ('spell_submission', 'spell_payload'):
            receipt = getattr(play, phase)
            if receipt is not None and receipt.cost_facts is not None:
                for index, fact in enumerate(receipt.cost_facts.window_quotes):
                    quote((*base, phase, 'cost_quote', index), fact)
        if play.battlecry_acceptance is not None:
            ids((*base, 'battlecry_activation'), 'battlecry', play.battlecry_acceptance.plan,
                play.battlecry_acceptance.player_id)
        if play.combo_acceptance is not None:
            ids((*base, 'combo_activation'), 'combo', play.combo_acceptance.plan, play.player_id)
        if play.spell_submission is not None:
            for index, modifier in enumerate(play.spell_submission.modifiers):
                add((*base, 'spell_submission', index), 'spell_modifiers', modifier.id,
                    value=modifier, owner=play.player_id)
        if play.spell_payload is not None:
            for index, source in enumerate(play.spell_payload.contributors):
                ability((*base, 'spell_payload', index), 'spell_repeat', source, play.player_id)
        for index, source in enumerate(play.card_spell_repeats):
            add((*base, 'card_spell', index), 'ability:card_spell_repeat', source.id,
                carrier=play.source_id, value=source, owner=play.player_id)
    for receipt in state.combo_policy_receipts:
        for index, modifier in enumerate(receipt.modifiers):
            from .combo_modifiers import receipt_player_id
            owner = receipt_player_id(state, receipt)
            add(('combo_policy', receipt.id, receipt.phase, index), 'combo_modifiers',
                modifier.id, value=modifier, owner=owner)
    for receipt in state.battlecry_policy_uses:
        for index, modifier in enumerate(receipt.modifiers):
            add(('battlecry_policy_use', receipt.id, index), 'battlecry_modifiers', modifier.id,
                value=modifier, owner=receipt.player_id)
    for child in state.whole_card_replay_ledger.children:
        progress = child.physical
        accepted = None if progress is None else progress.battlecry_repeat_acceptance
        if accepted is not None:
            ids(('generated_battlecry', child.id), 'battlecry', accepted.plan, progress.player_id)
    for receipt in state.spell_policy_receipts:
        for index, modifier in enumerate(receipt.modifiers):
            owner = state.play_history[receipt.play_id - 1].player_id
            add(('spell_policy', receipt.id, index), 'spell_modifiers', modifier.id,
                value=modifier, owner=owner)
    for receipt in state.cost_use_history:
        modifiers = {modifier.id: modifier for modifier in receipt.player_modifiers}
        for index, identity in enumerate(receipt.modifier_ids):
            value = modifiers.get(identity)
            add(('cost_use', receipt.id, index), 'cost_modifiers' if value is not None else 'ability:cost_aura',
                identity, value=value, owner=receipt.player_id)
    for family in ('battlecry', 'combo'):
        for batch in getattr(state, family + '_batches'):
            ids((family + '_batch', batch.id), family, batch.plan, batch.player_id)
    for power in state.hero_power_history:
        for index, source in enumerate(power.repeat_plan.contributors):
            ability(('power', power.id, index), 'hero_power_repeat', source, power.player_id)
    for batch in state.end_turn_batches:
        for slot, plan in enumerate(batch.plans):
            for index, source in enumerate(plan.contributors):
                path = ('end_turn', batch.id, slot, index)
                if source.ability is not None:
                    ability(path, 'end_turn_repeat', source, source.player_id)
                else:
                    add(path, 'player_effects', source.player_effect.id,
                        value=source.player_effect, owner=source.player_id,
                        spec_index=source.spec_index, spec=source.spec)
    for batch in state.deathrattle_batches:
        for slot, payload in enumerate(batch.payloads):
            for index, source in enumerate(payload.plan.contributors):
                path = ('deathrattle', batch.id, slot, index)
                if type(source) is DeathrattlePlayerContributor:
                    add(path, 'player_effects', source.instance.id, value=source.instance,
                        owner=source.player_id, spec_index=source.spec_index, spec=source.spec)
                else:
                    ability(path, 'deathrattle_repeat', source, source.player_id)
    return result



def _static_compatible(family, old, new):
    if family == 'ability':
        return (type(new) is AbilityInstance and
                replace(new, consumed=old.consumed) == old and
                not (old.consumed and not new.consumed))
    if family == 'player_effects':
        return (type(new) is type(old) and
                replace(new, remaining_turns=old.remaining_turns) == old and
                (old.remaining_turns is None and new.remaining_turns is None or
                 old.remaining_turns is not None and new.remaining_turns is not None and
                 new.remaining_turns <= old.remaining_turns))
    if family in ('cost_modifiers', 'battlecry_modifiers', 'combo_modifiers', 'spell_modifiers'):
        return (type(new) is type(old) and replace(new, uses_remaining=old.uses_remaining) == old and
                (old.uses_remaining is None and new.uses_remaining is None or
                 old.uses_remaining is not None and new.uses_remaining is not None and
                 new.uses_remaining <= old.uses_remaining))
    return new == old



def _reference_matches(item, reference, registry):
    family, carrier, value = item
    expected = 'ability:' + value.kind if family == 'ability' else family
    role_families = {
        'nonconsumable:battlecry': ('ability:battlecry_repeat', 'battlecry_modifiers'),
        'nonconsumable:combo': ('ability:combo_repeat', 'combo_modifiers'),
    }
    if reference.family in role_families:
        if expected not in role_families[reference.family]:
            return False
        if family in ('battlecry_modifiers', 'combo_modifiers') and value.uses_remaining is not None:
            return False
    elif expected != reference.family:
        return False
    elif (reference.value is None and family in ('battlecry_modifiers', 'combo_modifiers')
            and value.uses_remaining is None):
        # An ID-only *_modifiers slot denotes a genuinely finite plan source.
        return False
    if family in ('ability', 'enchantment'):
        if reference.carrier is not None and reference.carrier != carrier:
            return False
        # A board source may legally change control between two acceptances.
    elif reference.owner is not None and reference.owner != carrier:
        return False
    if reference.value is not None and not _static_compatible(family, value, reference.value):
        return False
    if family == 'player_effects':
        declaration = registry.player_effect(value.spec_id)
        specifications = (declaration.deathrattle_repeats if reference.path[0] == 'deathrattle'
                          else declaration.end_turn_repeats)
        if (reference.spec_index is None or reference.spec_index >= len(specifications) or
                specifications[reference.spec_index] != reference.spec):
            return False
    return True

