"""Incremental constructed content; this package does not certify a formal pool."""

from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.representative import build_registry as build_representative_registry
from .metadata import metadata_from_record, validate_race_pin
from hs_sim.targets import TargetValidationError, canonical_digest


CONTENT_VERSION = "constructed-cn37-preview-v104"
BATCH_PATH = Path(__file__).resolve().parents[2] / "data/cards/keyword-minions-v1.json"
# Assigned from the reviewed, complete records; runtime never interprets text.
BATCH_HASH = "bbc6595dd309cb5017576d675e597181c8fcd0d55eec386a648c85fedc79262e"
SUPPORTED_KEYWORDS = frozenset((
    Keyword.TAUNT, Keyword.DIVINE_SHIELD, Keyword.CHARGE, Keyword.RUSH,
    Keyword.WINDFURY, Keyword.POISONOUS, Keyword.LIFESTEAL, Keyword.STEALTH,
    Keyword.REBORN, Keyword.ELUSIVE,
))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError("Constructed card batch differs from its pinned reviewed records")
    return data


def register_keyword_minions(registry):
    """Install only finite reviewed recipes, preserving explicit core identities."""
    for row in load_batch()["cards"]:
        raw, recipe = row["record"], row["recipe"]
        if raw["type"] != "MINION" or raw["collectible"] is not True:
            raise TargetValidationError("Keyword batch requires collectible minion records")
        if canonical_digest(raw) != row["record_sha256"]:
            raise TargetValidationError("Reviewed card record differs from its pinned identity")
        keywords = tuple(Keyword(value) for value in recipe["keywords"])
        if set(keywords) - SUPPORTED_KEYWORDS or len(set(keywords)) != len(keywords):
            raise TargetValidationError("Unsupported or duplicate ordinary keyword recipe")
        for field in ("cost", "attack", "health"):
            if type(recipe[field]) is not int or recipe[field] < (1 if field == "health" else 0):
                raise TargetValidationError("Reviewed printed stats must be explicit integers")
            if raw[field] != recipe[field] and not (
                field == "cost" and raw[field] is None and recipe[field] == 0
                and raw["id"] in ("CORE_CS2_231", "CORE_ICC_023")
            ):
                raise TargetValidationError("Recipe stats differ from reviewed printed values")
        metadata = replace(metadata_from_record(raw), deck_identity=recipe["deck_identity"])
        definition = CardDefinition(
            raw["id"], raw["name"], CardType.MINION,
            cost=recipe["cost"], attack=recipe["attack"], health=recipe["health"],
            keywords=keywords, metadata=metadata,
        )
        registry.register_card(definition)
        # Eligibility metadata is available, but no partial formal pool is built.
        registry.register_pool_card(PoolCard.from_definition(definition))


def build_registry():
    validate_race_pin()
    from .conditional_health_cards import load_batch as load_conditional_health_batch
    known_unrarified = tuple(row['record']['id'] for row in load_conditional_health_batch()['known_unrarified_legacy'])
    from .basic_hero_roles import representative_initial_bindings
    registry = build_representative_registry(version=CONTENT_VERSION, known_unrarified_ids=known_unrarified,
        initial_hero_power_bindings=representative_initial_bindings(),defer_validation=True)
    from .demon_zone_cards import register_demon_zone_cards
    register_demon_zone_cards(registry)
    from .hand_mirror_cards import register_hand_mirror_cards
    register_hand_mirror_cards(registry)
    register_keyword_minions(registry)
    from .health_cards import register_health_cards
    register_health_cards(registry)
    from .economy_cards import register_economy_cards
    register_economy_cards(registry)
    from .utility_cards import register_utility_cards
    register_utility_cards(registry)
    from .conditional_cards import register_conditional_cards
    register_conditional_cards(registry)
    from .zone_cards import register_zone_cards
    register_zone_cards(registry)
    from .recruit_cards import register_recruit_cards
    register_recruit_cards(registry)
    from .recruit_followup_cards import register_recruit_followup_cards
    register_recruit_followup_cards(registry)
    from .presence_cost_cards import register_presence_cost_cards
    register_presence_cost_cards(registry)
    from .next_cost_cards import register_next_cost_cards
    register_next_cost_cards(registry)
    from .quantity_cost_cards import register_quantity_cost_cards
    register_quantity_cost_cards(registry)
    from .return_hand_cards import register_return_hand_cards
    register_return_hand_cards(registry)
    from .core_secret_cards import register_core_secret_cards
    register_core_secret_cards(registry)
    from .excess_secret_cards import register_excess_secret_cards
    register_excess_secret_cards(registry)
    from .reactive_secret_cards import register_reactive_secret_cards
    register_reactive_secret_cards(registry)
    from .infinite_secret_cards import register_infinite_secret_cards
    register_infinite_secret_cards(registry)
    from .health_followup_cards import register_health_followup_cards
    register_health_followup_cards(registry)
    from .native_followup_cards import register_native_followup_cards
    register_native_followup_cards(registry)
    from .health_sequence_cards import register_health_sequence_cards
    register_health_sequence_cards(registry)
    from .spell_target_cards import register_spell_target_cards
    register_spell_target_cards(registry)
    from .health_resource_cards import register_health_resource_cards
    register_health_resource_cards(registry)
    from .health_beneficiary_cards import register_health_beneficiary_cards
    register_health_beneficiary_cards(registry)
    from .original_material_cards import register_original_material_cards
    register_original_material_cards(registry)
    from .conditional_health_cards import register_conditional_health_cards
    register_conditional_health_cards(registry)
    from .spell_sequence_cards import register_spell_sequence_cards
    register_spell_sequence_cards(registry)
    from .stat_draw_cards import register_stat_draw_cards
    register_stat_draw_cards(registry)
    from .native_end_cards import register_native_end_cards
    register_native_end_cards(registry)
    from .basic_trigger_cards import register_basic_trigger_cards
    register_basic_trigger_cards(registry)
    from .death_followup_cards import register_death_followup_cards
    register_death_followup_cards(registry)
    from .simple_battlecry_cards import register_simple_battlecry_cards
    register_simple_battlecry_cards(registry)
    from .conditional_battlecry_cards import register_conditional_battlecry_cards
    register_conditional_battlecry_cards(registry)
    from .targeted_battlecry_cards import register_targeted_battlecry_cards
    register_targeted_battlecry_cards(registry)
    from .persistent_economy_cards import register_persistent_economy_cards
    register_persistent_economy_cards(registry)
    from .player_period_cards import register_player_period_cards
    register_player_period_cards(registry)
    from .qualified_next_cards import register_qualified_next_cards
    register_qualified_next_cards(registry)
    from .static_provider_cards import register_static_provider_cards
    register_static_provider_cards(registry)
    from .reactive_growth_cards import register_reactive_growth_cards
    register_reactive_growth_cards(registry)
    from .trigger_source_cards import register_trigger_source_cards
    register_trigger_source_cards(registry)
    from .attack_followup_cards import register_attack_followup_cards
    register_attack_followup_cards(registry)
    from .physical_zone_cards import register_physical_zone_cards
    register_physical_zone_cards(registry)
    from .history_recovery_cards import register_history_recovery_cards
    register_history_recovery_cards(registry)
    from .native_random_damage_cards import register_native_random_damage_cards
    register_native_random_damage_cards(registry)
    from .native_weapon_turn_draw_cards import register_native_weapon_turn_draw_cards
    register_native_weapon_turn_draw_cards(registry)
    from .fixed_companion_cards import register_fixed_companion_cards
    register_fixed_companion_cards(registry)
    from .granted_deathrattle_cards import register_granted_deathrattle_cards
    register_granted_deathrattle_cards(registry)
    from .physical_draw_cards import register_physical_draw_cards
    register_physical_draw_cards(registry)
    from .draw_retention_cards import register_draw_retention_cards
    register_draw_retention_cards(registry)
    from .held_draw_cards import register_held_draw_cards
    register_held_draw_cards(registry)
    from .six_cost_native_cards import register_six_cost_native_cards
    register_six_cost_native_cards(registry)
    from .deck_history_native_cards import register_deck_history_native_cards
    register_deck_history_native_cards(registry)
    from .shuffle_native_cards import register_shuffle_native_cards
    register_shuffle_native_cards(registry)
    from .summon_beneficiary_cards import register_summon_beneficiary_cards
    register_summon_beneficiary_cards(registry)
    from .entry_native_cards import register_entry_native_cards
    register_entry_native_cards(registry)
    from .beast_trigger_native_cards import register_beast_trigger_native_cards
    register_beast_trigger_native_cards(registry)
    from .stored_growth_native_cards import register_stored_growth_native_cards
    register_stored_growth_native_cards(registry)
    from .native_reborn_fire_draw_cards import register_native_reborn_fire_draw_cards
    register_native_reborn_fire_draw_cards(registry)
    from .renferal_native_cards import register_renferal_native_cards
    register_renferal_native_cards(registry)
    from .mirrex_native_cards import register_mirrex_native_cards
    register_mirrex_native_cards(registry)
    from .one_cost_basic_cards import register_one_cost_basic_cards
    register_one_cost_basic_cards(registry)
    from .native_conditional_cards import register_native_conditional_cards
    register_native_conditional_cards(registry)
    from .basic_hero_roles import register_basic_hero_roles
    register_basic_hero_roles(registry)
    from .played_minion_keyword_cards import register_played_minion_keyword_cards
    register_played_minion_keyword_cards(registry)
    from .full_board_dormancy_cards import register_full_board_dormancy_cards
    register_full_board_dormancy_cards(registry)
    from .native_deathrattle_memory_cards import register_native_deathrattle_memory_cards
    register_native_deathrattle_memory_cards(registry)
    from .kindred_murloc_cards import register_kindred_murloc_cards
    register_kindred_murloc_cards(registry)
    from .self_target_spell_cards import register_self_target_spell_cards
    register_self_target_spell_cards(registry)
    from .next_play_price_cards import register_next_play_price_cards
    register_next_play_price_cards(registry)
    from .fixed_shuffle_followup_cards import register_fixed_shuffle_followup_cards
    register_fixed_shuffle_followup_cards(registry)
    from .imp_entry_followup_cards import register_imp_entry_followup_cards
    register_imp_entry_followup_cards(registry)
    from .kindred_component_cards import register_kindred_component_cards
    register_kindred_component_cards(registry)
    from .numeric_resource_cards import register_numeric_resource_cards
    register_numeric_resource_cards(registry)
    from .temporal_effect_cards import register_temporal_effect_cards
    register_temporal_effect_cards(registry)
    from .corpse_summon_cards import register_corpse_summon_cards
    register_corpse_summon_cards(registry)
    from .corpse_trigger_choice_cards import register_corpse_trigger_choice_cards
    register_corpse_trigger_choice_cards(registry)
    from .corpse_consumer_native_cards import register_corpse_consumer_native_cards
    register_corpse_consumer_native_cards(registry)
    from .hero_corpse_rescue_cards import register_hero_corpse_rescue_cards
    register_hero_corpse_rescue_cards(registry)
    from .blood_rune_native_cards import register_blood_rune_native_cards
    register_blood_rune_native_cards(registry)
    from .undead_native_cards import register_undead_native_cards
    register_undead_native_cards(registry)
    from .undead_resource_native_cards import register_undead_resource_native_cards
    register_undead_resource_native_cards(registry)
    from .five_cost_native_cards import register_five_cost_native_cards
    register_five_cost_native_cards(registry)
    from .kindred_hand_bonus_cards import register_kindred_hand_bonus_cards
    register_kindred_hand_bonus_cards(registry)
    from .public_effect_consumer_cards import register_public_effect_consumer_cards
    register_public_effect_consumer_cards(registry)
    from .conditional_consumer_cards import register_conditional_consumer_cards
    register_conditional_consumer_cards(registry)
    from .native_health_attack_provider_cards import register_native_health_attack_provider_cards
    register_native_health_attack_provider_cards(registry)
    from .fixed_named_followup_cards import register_fixed_named_followup_cards
    register_fixed_named_followup_cards(registry)
    from .stored_dark_gift_source import register_stored_dark_gift_source
    register_stored_dark_gift_source(registry)
    from .dragon_native_effect_cards import register_dragon_native_effect_cards
    register_dragon_native_effect_cards(registry)
    from .parallel_trial_p01_cards import register_parallel_trial_p01_cards
    register_parallel_trial_p01_cards(registry)
    from .native_draw_followup_cards import register_native_draw_followup_cards
    register_native_draw_followup_cards(registry)
    from .simple_followup_p02_cards import register_simple_followup_p02_cards
    register_simple_followup_p02_cards(registry)
    from .native_discard_rewind_cards import register_native_discard_rewind_cards
    register_native_discard_rewind_cards(registry)
    from .simple_choice_p03_cards import register_simple_choice_p03_cards
    register_simple_choice_p03_cards(registry)
    from .native_weapon_choice_cards import register_native_weapon_choice_cards
    register_native_weapon_choice_cards(registry)
    from .simple_fixed_p04_cards import register_simple_fixed_p04_cards
    register_simple_fixed_p04_cards(registry)
    from .random_minion_keyword_cards import register_random_minion_keyword_cards
    register_random_minion_keyword_cards(registry)
    from .current_stored_tribe_cards import register_current_stored_tribe_cards
    register_current_stored_tribe_cards(registry)
    from .simple_native_p05_cards import register_simple_native_p05_cards
    register_simple_native_p05_cards(registry)
    registry.validate()
    return registry
