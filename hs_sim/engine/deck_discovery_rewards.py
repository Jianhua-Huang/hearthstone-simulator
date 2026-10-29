"""Finite real rewards on the selected original physical own-deck card."""
from .model import CardType, SpellSchool, Zone
from .pools import PoolQuery


def validate_request(request):
    reward = request.selected_reward
    if reward is None:
        return
    if type(reward) is not str or reward not in ('arcane_spell_damage', 'copy_with_spell_damage', 'heal_hero_by_local_cost'):
        raise ValueError('Unknown selected original deck reward')
    query = PoolQuery(kinds=(CardType.SPELL,)) if reward == 'arcane_spell_damage' else PoolQuery()
    if reward == 'heal_hero_by_local_cost': query = PoolQuery(kinds=(CardType.MINION,))
    if (request.source_id is None or request.player_id != request.owner_id or request.zone != Zone.DECK or
            request.operation != 'take' or request.distinct != 'entity' or request.discovery is not True or
            type(request.sample_size) is not int or request.sample_size != 3 or request.query != query or
            request.cost is not None or request.destroy_unchosen):
        raise ValueError('Selected deck reward requires its finite original discovery profile')


def selected_work(r, request, selected):
    """Accept rewards once, before the original ordinary delivery and reactions."""
    validate_request(request)
    from .zones import CopyCard, reference_entity
    entity = reference_entity(r, selected)
    if entity is None:
        return (), ()
    if request.selected_reward == 'heal_hero_by_local_cost':
        from .costs import local_cost
        from .effects import Heal
        from .model import HealingKind
        amount = local_cost(entity)[0]
        return (), (Heal(r.state.players[request.player_id].hero_id, amount, request.source_id, HealingKind.SPELL),)
    if request.selected_reward == 'arcane_spell_damage' and r.registry.card(entity.card_id).spell_school == SpellSchool.ARCANE:
        from .stored_spell_damage import GrantStoredSpellDamage
        return (GrantStoredSpellDamage(selected, 1, request.source_id),), ()
    if request.selected_reward == 'copy_with_spell_damage':
        from .health_rules import spell_bonus
        if spell_bonus(r.state, request.player_id, r.registry) > 0:
            from .copy_materials import CapturedCardCopyMaterial
            material = CapturedCardCopyMaterial.capture(r.state, entity)
            return (), (CopyCard(material, request.player_id, mode='current', source_id=request.source_id),)
    return (), ()
