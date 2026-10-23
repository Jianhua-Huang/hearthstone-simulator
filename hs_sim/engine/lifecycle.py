"""Entity-local attachment operations shared by effects and lifecycle changes."""
from dataclasses import replace

from .model import AbilityInstance, CardType, Enchantment, Keyword, DormancyState, Zone, PrintedAttackPolicyDeclaration
from .stats import enchantment_stats
from .costs import local_cost


def attachment_id(state):
    result = state.next_attachment_id
    state.next_attachment_id += 1
    return result


def active_abilities(entity, kind):
    eligible = entity.active
    if kind in ('dormant_trigger', 'board_full_awaken'):
        eligible = entity.dormancy is not None and not entity.starship_building
    elif kind in ('on_play', 'battlecry', 'combo') and entity.dormancy is not None:
        eligible = not entity.starship_building
    return tuple(a for a in entity.abilities if a.kind == kind and not a.consumed) if eligible else ()


def initialize_dormancy(state, entity, definition, *, turns_override=None):
    if turns_override is not None:
        from .effects import _integer
        _integer(turns_override, 'entry dormant turns', 1)
        if entity.zone != Zone.BOARD or entity.kind != CardType.MINION:
            raise ValueError('Entry dormancy requires a newly allocated board minion')
        if definition.permanent_dormancy:
            raise ValueError('Timed entry cannot override a permanent dormant carrier')
    entity.dormancy = None
    turns = definition.dormant_turns if turns_override is None else turns_override
    if entity.zone == Zone.BOARD and turns != 0:
        entity.dormancy = DormancyState(attachment_id(state), turns,
                                       state.turn, definition.permanent_dormancy if turns_override is None else False)
    refresh_entity(entity)


def local_keywords(entity):
    """Attachment/weapon flags without any cached external or conditional aura."""
    keywords = {a.keyword for a in active_abilities(entity,'keyword')} | entity.weapon_keywords
    keywords |= {a.limited_trigger.keyword for a in active_abilities(entity,'limited_trigger')
                 if a.limited_trigger.keyword is not None}
    keywords |= {a.hand_progress.keyword for a in active_abilities(entity,'hand_progress')
                 if a.hand_progress.keyword is not None}
    if entity.damage > 0:
        keywords |= {a.keyword_aura.keyword for a in active_abilities(entity,'keyword_aura')
                     if a.keyword_aura.condition == 'self_damaged'}
    return keywords


def refresh_entity(entity):
    """Rebuild caches; never accumulate derived values into permanent state."""
    attack, health = enchantment_stats(entity)
    entity.attack_bonus = attack - entity.base_attack
    entity.health_bonus = health - entity.base_health
    entity.cost_modifier = local_cost(entity)[0] - entity.base_cost
    entity.keywords = (local_keywords(entity) | entity.aura_keywords | entity.hand_aura_keywords |
                       entity.conditional_keywords)


def remove_attachments(entity, *, enchantment_predicate, ability_predicate):
    old_health, old_max = entity.health, entity.max_health
    entity.enchantments = [e for e in entity.enchantments if not enchantment_predicate(e)]
    from .prepare import attachments_removed
    attachments_removed(entity)
    entity.abilities = [a for a in entity.abilities if not ability_predicate(a)]
    refresh_entity(entity)
    # Prototype-v2 removal contract: lowering maximum health clamps remaining
    # health, rather than subtracting the removed bonus a second time.
    if entity.max_health < old_max:
        entity.damage = max(0, entity.max_health - old_health)


def install_printed(state, entity, definition, registry=None, *, append=False, exclude_keywords=()):
    if not append:
        entity.abilities = []
        entity.galakrond_invocations = None
    def add(kind, **fields):
        if kind=='keyword' and fields.get('keyword')==Keyword.DIVINE_SHIELD:
            fields['divine_shield_hits']=max((a.divine_shield_hits for a in entity.abilities
                if a.kind=='keyword'and a.keyword==Keyword.DIVINE_SHIELD and not a.consumed),default=0)
        entity.abilities.append(AbilityInstance(
            attachment_id(state), kind, source_id=entity.id, origin='printed', **fields))
    for keyword in definition.keywords:
        if keyword not in exclude_keywords and keyword not in (Keyword.SPELLBURST, Keyword.FRENZY, Keyword.CORRUPT, Keyword.INFUSE):
            spec = next((s for s in definition.timed_keywords if s.keyword == keyword), None)
            fields = {'reborn_policy': definition.reborn_policy} if keyword == Keyword.REBORN else {}
            add('keyword', keyword=keyword, timed_keyword=spec, **fields)
    if definition.spell_damage:
        add('spell_damage', spell_damage=definition.spell_damage, spell_damage_schools=definition.spell_damage_schools,
            native_condition=definition.native_condition if definition.native_condition is not None and definition.native_condition.kind=='self_damaged'else None)
    if registry is not None:
        from .corpse_gains import declaration_ids as corpse_gain_declarations
        for native_id in corpse_gain_declarations(registry,definition.id):
            add('corpse_gain', corpse_gain_card_id=native_id)
    if registry is not None and definition.id in registry.turn_draw_profiles:
        add('turn_draw_suppression',turn_draw_card_id=definition.id)
    if registry is not None and definition.id in registry.native_producer_quantity_profiles:
        add('native_producer_quantity',native_producer_quantity_card_id=definition.id)
    if registry is not None and definition.id in registry.native_stat_gain_profiles:
        add('native_stat_gain',native_stat_gain_card_id=definition.id)
    if registry is not None and definition.id in registry.random_target_cards:
        add('random_targets')
    if registry is not None and definition.id in registry.rotating_discovery_class_profiles:
        from .rotating_discovery_classes import initial_class
        add('class_discovery',class_discovery_card_id=definition.id,discovery_class=initial_class(state,entity.controller))
    if registry is not None and definition.id in registry.colossal_reserve_profiles:
        add('colossal_reserve',colossal_reserve_card_id=definition.id,colossal_remaining=len(definition.colossal))
    if registry is not None and definition.id in registry.remaining_mana_numbers_profiles:
        add('remaining_mana_numbers',remaining_mana_card_id=definition.id)
    if definition.cleave:
        add('cleave')
    if definition.on_play:
        add('on_play', behavior_id=definition.on_play)
    if definition.on_discard:
        add('on_discard', behavior_id=definition.on_discard)
    if definition.on_destroyed:
        add('on_destroyed', behavior_id=definition.on_destroyed)
    if definition.combo:
        add('combo', behavior_id=definition.combo, combo_card_id=definition.id)
    if definition.battlecry:
        add('battlecry', behavior_id=definition.battlecry, battlecry_card_id=definition.id)
    if definition.on_use:
        add('on_use', behavior_id=definition.on_use)
    for spec in definition.activated_abilities:
        add('activated', activation=spec)
    for spec in definition.limited_triggers:
        add('limited_trigger', limited_trigger=spec, uses_remaining=spec.uses,
            trigger_turn=state.turn if spec.reset == 'turn' else None)
    if definition.hand_progress is not None:
        add('hand_progress', hand_progress=definition.hand_progress)
    if definition.defining_hand_source is not None and entity.zone in (Zone.HAND, Zone.DECK):
        add('defining_hand_source', hand_progress=definition.defining_hand_source, defining_card_id=definition.id)
    if registry is not None and definition.id in registry.spell_mirror_ids and entity.zone == Zone.HAND:
        from .model import SpellMirrorBinding
        add('spell_mirror',spell_mirror=SpellMirrorBinding(definition.id))
    if definition.hand_mirror is not None and entity.zone == Zone.HAND:
        from .model import HandMirrorBinding
        add('hand_mirror',hand_mirror=HandMirrorBinding(definition.id,entity.controller))
    if definition.on_awaken:
        add('on_awaken', behavior_id=definition.on_awaken)
    if definition.dormant_board_full:
        add('board_full_awaken')
    for trigger in definition.dormant_triggers:
        add('dormant_trigger', event=trigger.event, behavior_id=trigger.behavior_id,
            end_turn=trigger.end_turn)
    if definition.on_launch:
        add('on_launch', behavior_id=definition.on_launch)
    if definition.deathrattle:
        from .model import DeathrattleMemory
        add('deathrattle', behavior_id=definition.deathrattle, deathrattle_card_id=definition.id,
            deathrattle_memory=DeathrattleMemory(definition.native_deathrattle) if definition.native_deathrattle is not None else None)
    for trigger in definition.triggers:
        add('trigger', event=trigger.event, behavior_id=trigger.behavior_id,
            end_turn=trigger.end_turn)
    for aura in definition.auras:
        add('aura', attack=aura.attack, health=aura.health, include_self=aura.include_self,
            adjacent_only=aura.adjacent_only, aura_target=aura.target, aura_condition=aura.condition,
            aura_tribes_any=aura.tribes_any, aura_card_ids=aura.card_ids)
    for spec in definition.cost_auras:
        add('cost_aura', cost_aura=spec,
            native_condition=definition.native_condition if definition.native_condition is not None and definition.native_condition.kind in('controller_hand_at_most','controller_other_dragon')else None)
    if definition.native_condition is not None and definition.native_condition.kind == 'transform_destination_plus_two':
        add('transform_replacement', native_condition=definition.native_condition)
    for spec in definition.keyword_auras:
        add('keyword_aura', keyword_aura=spec)
    for index, spec in enumerate(definition.attack_policies):
        add('attack_policy', attack_policy=spec,
            attack_policy_declaration=PrintedAttackPolicyDeclaration(definition.id, index))
    for spec in definition.deathrattle_repeats:
        add('deathrattle_repeat', deathrattle_repeat=spec)
    for spec in definition.battlecry_repeats:
        add('battlecry_repeat', battlecry_repeat=spec)
    for spec in definition.combo_repeats:
        add('combo_repeat', combo_repeat=spec)
    for spec in definition.spell_repeats:
        add('spell_repeat', spell_repeat=spec)
    for spec in definition.hero_power_repeats:
        add('hero_power_repeat', hero_power_repeat=spec)
    if definition.hero_power_use_aura is not None:
        add('hero_power_use_aura', hero_power_use_aura=definition.hero_power_use_aura)
    for spec in definition.end_turn_repeats:
        add('end_turn_repeat', end_turn_repeat=spec)
    if definition.choose_both:
        add('choose_both')
    if definition.retain_rewind_outcomes:
        add('rewind_retention')
    for spec in definition.summon_quantities:
        add('summon_quantity',summon_quantity=spec)
    for spec in definition.health_loss_floors:
        add('health_loss_floor', health_loss_floor=spec)
    from .model import PrintedWeaponWearDeclaration
    for index,spec in enumerate(definition.weapon_wear_policies):
        add('weapon_wear_policy',weapon_wear_policy=spec,weapon_wear_declaration=PrintedWeaponWearDeclaration(definition.id,index))
    for spec in definition.health_loss_replacements:
        add('health_loss_replacement', health_loss_replacement=spec)
    if definition.deck_sacrifice is not None:
        add('deck_sacrifice', deck_sacrifice=definition.deck_sacrifice)
    for rule in definition.health_rules:
        add('health_rule', health_rule=rule)
    for spec in definition.stat_relations:
        add('stat_relation', stat_relation=spec)
    from .timed_keywords import arm
    arm(state, entity)
    refresh_entity(entity)


def install_base(state, entity, definition, registry, components=(), *, entry_herald_count=None):
    """Install an instance's printed base, including its immutable composition."""
    from .crafted_faces import PREFIX as crafted_prefix,install as install_crafted
    if definition.id.startswith(crafted_prefix):
        install_crafted(state,entity,definition,registry,components)
        return
    if bool(definition.starship_for) != bool(components):
        raise ValueError('A Starship body requires components; ordinary cards cannot contain them')
    entity.components = components
    entity.herald_rank = None
    entity.base_attack, entity.base_health = definition.attack, definition.health
    install_printed(state, entity, definition, registry)
    for card_id in components:
        part = registry.card(card_id)
        if part.kind != CardType.MINION or part.starship_for or part.id.startswith(crafted_prefix):
            raise ValueError('Starship components must be non-composite minion definitions')
        entity.base_attack += part.attack
        entity.base_health += part.health
        install_printed(state, entity, part, registry, append=True, exclude_keywords=(Keyword.STARSHIP_PIECE,))
    from .herald import initialize_instance
    initialize_instance(state, entity, definition, count=entry_herald_count)
    from .jade import initialize_instance as initialize_jade
    initialize_jade(entity, registry)
    from .minion_base_programs import apply_to_entity as apply_minion_base_program
    apply_minion_base_program(state,registry,entity)
    from .named_minion_boons import apply_to_entity as apply_named_boons
    apply_named_boons(state,registry,entity)
    refresh_entity(entity)


def reset_to_definition(state, entity, definition, registry=None, *, components=None, preserve_jade=False, preserve_cthun=False, preserve_weapon_spell=False):
    bases=[e for e in entity.enchantments if e.minion_base_stats is not None] if entity.card_id==definition.id else []
    jade_size = entity.jade_size if preserve_jade and entity.card_id == definition.id else None
    from .carved_spells import weapon_material,restore_weapon_material
    weapon_spell=weapon_material(entity)if preserve_weapon_spell and entity.card_id==definition.id else None
    ritual = [e for e in entity.enchantments if e.cthun_ritual is not None] if preserve_cthun and entity.card_id == definition.id else []
    ritual_abilities = [a for a in entity.abilities if a.cthun_ritual is not None] if preserve_cthun and entity.card_id == definition.id else []
    if components is None:
        components = entity.components if entity.card_id == definition.id else ()
    entity.card_id = definition.id
    entity.kind = definition.kind
    entity.location_cooldown = 0
    entity.base_attack = definition.attack
    entity.base_health = definition.health
    entity.base_cost = definition.cost
    entity.damage = entity.armor = entity.aura_attack = entity.aura_health = 0
    entity.frozen_until_owner_turn = None
    entity.spell_mana_freeze = None
    entity.durability = definition.durability
    entity.weapon_attack = entity.uses_this_turn = 0
    entity.weapon_keywords = set()
    entity.aura_keywords = set()
    entity.hand_aura_keywords = set()
    entity.conditional_keywords = set()
    entity.conditional_attack = 0
    entity.conditional_health = 0
    entity.use_limit = definition.uses_per_turn
    entity.corpse_value = (int(definition.kind == 'minion') if definition.corpse_value is None
                           else definition.corpse_value)
    entity.attacks_this_turn = 0
    entity.old_god_free_used = False
    entity.doomed = entity.silenced = False
    entity.death_cause = None
    entity.starship_building = False
    entity.enchantments = bases
    entity.hand_lifetime = None
    entity.choose_branch = None
    entity.preparation = None
    entity.location_lock = None
    install_base(state, entity, definition, registry, components)
    entity.enchantments.extend(ritual)
    entity.abilities.extend(ritual_abilities)
    if preserve_cthun:
        from .cthun import catch_up_on_reset
        catch_up_on_reset(state, registry, entity)
    if jade_size is not None:
        from .jade import imprint
        imprint(entity, jade_size)
    restore_weapon_material(entity,weapon_spell)
    initialize_dormancy(state, entity, definition)


def consume_keyword(entity, keyword):
    """One shield/reborn event consumes all currently active copies of the flag."""
    entity.abilities = [replace(a, consumed=True) if a.kind == 'keyword' and a.keyword == keyword
                        and not a.consumed else a for a in entity.abilities]
    refresh_entity(entity)


def copy_attachments(state, source, destination, *, rebind_printed=False):
    if any(a.kind == 'defining_hand_source' for a in source.abilities):
        from .errors import ResolutionError
        raise ResolutionError('Copying a defining hand source requires an explicit supported lifecycle policy')
    destination.hand_lifetime = source.hand_lifetime
    destination.choose_branch = source.choose_branch if source.card_id == destination.card_id else None
    destination.herald_rank = source.herald_rank
    destination.jade_size = source.jade_size if source.card_id == destination.card_id else None
    # Physical control returns belong to this resident, never to a new copy.
    copied = tuple(e for e in source.enchantments if e.control_return_player_id is None)
    if not any(e.minion_base_stats is not None for e in copied):
        copied=(*tuple(e for e in destination.enchantments if e.minion_base_stats is not None),*copied)
    enchantment_ids = {e.id: attachment_id(state) for e in copied}
    destination.enchantments = [replace(e, id=enchantment_ids[e.id]) for e in copied]
    from .prepare import copy_state
    copy_state(source, destination, enchantment_ids)
    # Keep allocation order; local references are rewritten only after all IDs exist.
    ability_ids = {a.id: attachment_id(state) for a in source.abilities}
    destination.abilities = []
    for ability in source.abilities:
        permit = ability.printed_attack_permit
        if permit is not None:
            permit = replace(permit, permitted_ability_id=ability_ids.get(
                permit.permitted_ability_id, permit.permitted_ability_id))
        if ability.kind in ('hand_mirror','spell_mirror') and destination.zone!=Zone.HAND:continue
        native_self=ability.kind in ('hand_mirror','spell_mirror')or ability.origin=='printed'and ability.reborn_policy is not None
        rebound_source=destination.id if native_self or rebind_printed and ability.origin=='printed'and ability.source_id==source.id else ability.source_id
        destination.abilities.append(replace(ability, id=ability_ids[ability.id], source_id=rebound_source, printed_attack_permit=permit))
    destination.silenced = source.silenced
    from .timed_keywords import arm
    arm(state, destination)
    refresh_entity(destination)


def restore_reborn_enchantments(state, record, destination):
    """Restore frozen grants on a fresh printed body via the existing copier.

    Native usage starts fresh; granted usage and deadlines stay frozen. A
    physical control-return attachment never binds to the new board residence.
    """
    printed = [replace(a, source_id=record.entity_id if a.source_id == destination.id else a.source_id)
               for a in destination.abilities]
    grants = []
    for ability in record.abilities:
        if ability.origin == 'printed':
            continue
        permit = ability.printed_attack_permit
        if permit is not None:
            old = next((a for a in record.abilities if a.id == permit.permitted_ability_id), None)
            # An absent native row remains inert; do not rematch a removed row.
            if old is not None:
                new = next((a for a in printed if a.kind == old.kind and
                            a.attack_policy_declaration == old.attack_policy_declaration), None)
                if new is None:
                    raise ValueError('Reborn material lost its native attack restriction')
                permit = replace(permit, permitted_ability_id=new.id)
        grants.append(replace(ability, printed_attack_permit=permit))
    material = replace(destination, id=record.entity_id,
                       abilities=[*printed, *grants], enchantments=list(record.enchantments))
    copy_attachments(state, material, destination, rebind_printed=True)


def renew_hand_progress(state, entity, *, previous_zone=None, hand_transfer=False):
    """Renew queued witnesses; a native shifter retires when its hand stay ends."""
    entity.abilities = [replace(a, id=attachment_id(state), progress_value=0,
                        progress_completions=0, progress_keys=(), progress_units=(), consumed=False)
                        if hand_transfer and a.kind == 'defining_hand_source' else
                        replace(a, id=attachment_id(state)) if a.kind in
                        ('hand_progress', 'defining_hand_source') else a
                        for a in entity.abilities if a.kind != 'defining_hand_source' or
                        entity.zone in (Zone.HAND, Zone.DECK) and previous_zone != Zone.HAND or
                        hand_transfer and entity.zone == Zone.HAND]
    entity.abilities=[a for a in entity.abilities if a.kind not in ('hand_mirror','spell_mirror')or entity.zone==Zone.HAND]


def apply_summon_stats(state, entity, spec, *, source_id=None, label='summon_stats'):
    from .model import validate_summon_stats
    validate_summon_stats(spec)
    if spec is None: return
    entity.enchantments.append(Enchantment(attachment_id(state), source_id=entity.id if source_id is None else source_id,
        set_attack=spec.attack, set_health=spec.health, label=label))
    if spec.health is not None: entity.damage = 0
    refresh_entity(entity)


def advance_location_printed(state, entity, definition):
    """One location face policy: keep physical usage and every valid dynamic row."""
    if entity.kind != CardType.LOCATION or definition.kind != CardType.LOCATION:
        raise ValueError('Location printed replacement requires location types')
    entity.abilities = [a for a in entity.abilities if a.origin != 'printed']
    entity.card_id = definition.id
    entity.base_cost = definition.cost
    entity.zone_epoch += 1
    install_printed(state, entity, definition, append=True)
