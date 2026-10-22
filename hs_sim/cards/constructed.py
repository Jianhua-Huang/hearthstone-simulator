"""Incremental constructed content; this package does not certify a formal pool."""

from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.representative import build_registry as build_representative_registry
from .metadata import metadata_from_record, validate_race_pin
from hs_sim.targets import TargetValidationError, canonical_digest


CONTENT_VERSION = "constructed-cn37-preview-v494"
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
    from .constructed_metadata_catalog import metadata_overrides,register_reviewed_pool_metadata
    registry = build_representative_registry(version=CONTENT_VERSION, known_unrarified_ids=known_unrarified,
        initial_hero_power_bindings=representative_initial_bindings(),defer_validation=True,
        metadata_overrides=metadata_overrides())
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
    from .discard_derived_stat_cards import register_discard_derived_stat_cards
    register_discard_derived_stat_cards(registry)
    from .simple_timing_p06_cards import register_simple_timing_p06_cards
    register_simple_timing_p06_cards(registry)
    from .native_timed_grant_cards import register_native_timed_grant_cards
    register_native_timed_grant_cards(registry)
    from .simple_temporal_p07_cards import register_simple_temporal_p07_cards
    register_simple_temporal_p07_cards(registry)
    from .stored_spell_bonus_cards import register_stored_spell_bonus_cards
    register_stored_spell_bonus_cards(registry)
    from .created_spell_bonus_cards import register_created_spell_bonus_cards
    register_created_spell_bonus_cards(registry)
    from .simple_herald_p08_cards import register_simple_herald_p08_cards
    register_simple_herald_p08_cards(registry)
    from .non_spell_split_cards import register_non_spell_split_cards
    register_non_spell_split_cards(registry)
    from .simple_reactive_p09_cards import register_simple_reactive_p09_cards
    register_simple_reactive_p09_cards(registry)
    from .captured_attack_grant_cards import register_captured_attack_grant_cards
    register_captured_attack_grant_cards(registry)
    from .simple_conditional_p10_cards import register_simple_conditional_p10_cards
    register_simple_conditional_p10_cards(registry)
    from .played_school_target_cards import register_played_school_target_cards
    register_played_school_target_cards(registry)
    from .simple_native_p11_cards import register_simple_native_p11_cards
    register_simple_native_p11_cards(registry)
    from .native_discard_memory_cards import register_native_discard_memory_cards
    register_native_discard_memory_cards(registry)
    from .simple_followup_p12_cards import register_simple_followup_p12_cards
    register_simple_followup_p12_cards(registry)
    from .native_shred_treant_cards import register_native_shred_treant_cards
    register_native_shred_treant_cards(registry)
    from .simple_followup_p13_cards import register_simple_followup_p13_cards
    register_simple_followup_p13_cards(registry)
    from .native_combat_copy_cards import register_native_combat_copy_cards
    register_native_combat_copy_cards(registry)
    from .simple_followup_p14_cards import register_simple_followup_p14_cards
    register_simple_followup_p14_cards(registry)
    from .native_cast_target_cards import register_native_cast_target_cards
    register_native_cast_target_cards(registry)
    from .simple_followup_p15_cards import register_simple_followup_p15_cards
    register_simple_followup_p15_cards(registry)
    from .simple_followup_p16_cards import register_simple_followup_p16_cards
    register_simple_followup_p16_cards(registry)
    from .complex_dream_cards import register_complex_dream_cards
    register_complex_dream_cards(registry)
    from .simple_followup_p17_cards import register_simple_followup_p17_cards
    register_simple_followup_p17_cards(registry)
    from .fixed_dream_source import register_fixed_dream_source
    register_fixed_dream_source(registry)
    from .simple_followup_p18_cards import register_simple_followup_p18_cards
    register_simple_followup_p18_cards(registry)
    from .native_kindred_target_cards import register_native_kindred_target_cards
    register_native_kindred_target_cards(registry)
    from .simple_followup_p19_cards import register_simple_followup_p19_cards
    register_simple_followup_p19_cards(registry)
    from .native_kindred_destruction_cards import register_native_kindred_destruction_cards
    register_native_kindred_destruction_cards(registry)
    from .simple_followup_p20_cards import register_simple_followup_p20_cards
    register_simple_followup_p20_cards(registry)
    from .simple_followup_p21_cards import register_simple_followup_p21_cards
    register_simple_followup_p21_cards(registry)
    from .deathrattle_inheritance_cards import register_deathrattle_inheritance_cards
    register_deathrattle_inheritance_cards(registry)
    from .simple_followup_p22_cards import register_simple_followup_p22_cards
    register_simple_followup_p22_cards(registry)
    from .native_killer_transform_cards import register_native_killer_transform_cards
    register_native_killer_transform_cards(registry)
    from .simple_followup_p23_cards import register_simple_followup_p23_cards
    register_simple_followup_p23_cards(registry)
    from .combined_shatter_generation_cards import register_combined_shatter_generation_cards
    register_combined_shatter_generation_cards(registry)
    from .simple_followup_p24_cards import register_simple_followup_p24_cards
    register_simple_followup_p24_cards(registry)
    from .simple_followup_p25_cards import register_simple_followup_p25_cards
    register_simple_followup_p25_cards(registry)
    from .simple_followup_p26_cards import register_simple_followup_p26_cards
    register_simple_followup_p26_cards(registry)
    from .simple_followup_p27_cards import register_simple_followup_p27_cards
    register_simple_followup_p27_cards(registry)
    from .discovery_cost_heal_cards import register_discovery_cost_heal_cards
    register_discovery_cost_heal_cards(registry)
    from .simple_followup_p28_cards import register_simple_followup_p28_cards
    register_simple_followup_p28_cards(registry)
    from .conditional_pool_consumer_cards import register_conditional_pool_consumer_cards
    register_conditional_pool_consumer_cards(registry)
    from .simple_followup_p29_cards import register_simple_followup_p29_cards
    register_simple_followup_p29_cards(registry)
    from .discovery_summon_freeze_cards import register_discovery_summon_freeze_cards
    register_discovery_summon_freeze_cards(registry)
    from .simple_followup_p30_cards import register_simple_followup_p30_cards
    register_simple_followup_p30_cards(registry)
    from .discovered_minion_copy_cards import register_discovered_minion_copy_cards
    register_discovered_minion_copy_cards(registry)
    from .simple_followup_p31_cards import register_simple_followup_p31_cards
    register_simple_followup_p31_cards(registry)
    from .discovered_minion_grant_cards import register_discovered_minion_grant_cards
    register_discovered_minion_grant_cards(registry)
    from .simple_followup_p32_cards import register_simple_followup_p32_cards
    register_simple_followup_p32_cards(registry)
    from .temporary_pool_minion_cards import register_temporary_pool_minion_cards
    register_temporary_pool_minion_cards(registry)
    from .pool_entry_keyword_cards import register_pool_entry_keyword_cards
    register_pool_entry_keyword_cards(registry)
    from .simple_followup_p33_cards import register_simple_followup_p33_cards
    register_simple_followup_p33_cards(registry)
    from .random_silence_destruction_cards import register_random_silence_destruction_cards
    register_random_silence_destruction_cards(registry)
    from .simple_followup_p34_cards import register_simple_followup_p34_cards
    register_simple_followup_p34_cards(registry)
    from .generated_minion_stat_cards import register_generated_minion_stat_cards
    register_generated_minion_stat_cards(registry)
    from .simple_followup_p35_cards import register_simple_followup_p35_cards
    register_simple_followup_p35_cards(registry)
    from .native_dark_gift_generation_cards import register_native_dark_gift_generation_cards
    register_native_dark_gift_generation_cards(registry)
    from .simple_followup_p36_cards import register_simple_followup_p36_cards
    register_simple_followup_p36_cards(registry)
    from .kindred_dark_gift_cards import register_kindred_dark_gift_cards
    register_kindred_dark_gift_cards(registry)
    from .simple_followup_p37_cards import register_simple_followup_p37_cards
    register_simple_followup_p37_cards(registry)
    from .native_ability_discovery_cards import register_native_ability_discovery_cards
    register_native_ability_discovery_cards(registry)
    from .simple_followup_p38_cards import register_simple_followup_p38_cards
    register_simple_followup_p38_cards(registry)
    from .native_dreadseed_cards import register_native_dreadseed_cards
    register_native_dreadseed_cards(registry)
    from .simple_followup_p39_cards import register_simple_followup_p39_cards
    register_simple_followup_p39_cards(registry)
    from .native_smoke_discovery_cards import register_native_smoke_discovery_cards
    register_native_smoke_discovery_cards(registry)
    from .simple_followup_p40_cards import register_simple_followup_p40_cards
    register_simple_followup_p40_cards(registry)
    from .native_gift_copy_cards import register_native_gift_copy_cards
    register_native_gift_copy_cards(registry)
    from .simple_followup_p41_cards import register_simple_followup_p41_cards
    register_simple_followup_p41_cards(registry)
    from .pool_entry_dormancy_cards import register_pool_entry_dormancy_cards
    register_pool_entry_dormancy_cards(registry)
    from .simple_followup_p42_cards import register_simple_followup_p42_cards
    register_simple_followup_p42_cards(registry)
    from .printed_outcast_study_cards import register_printed_outcast_study_cards
    register_printed_outcast_study_cards(registry)
    from .simple_followup_p43_cards import register_simple_followup_p43_cards
    register_simple_followup_p43_cards(registry)
    from .cosmic_manifestation_cards import register_cosmic_manifestation_cards
    register_cosmic_manifestation_cards(registry)
    from .hero_outcast_immunity_cards import register_hero_outcast_immunity_cards
    register_hero_outcast_immunity_cards(registry)
    from .simple_followup_p45_cards import register_simple_followup_p45_cards
    register_simple_followup_p45_cards(registry)
    from .native_outcast_summon_cards import register_native_outcast_summon_cards
    register_native_outcast_summon_cards(registry)
    from .simple_followup_p46_cards import register_simple_followup_p46_cards
    register_simple_followup_p46_cards(registry)
    from .native_corpse_spell_summon_cards import register_native_corpse_spell_summon_cards
    register_native_corpse_spell_summon_cards(registry)
    from .simple_followup_p47_cards import register_simple_followup_p47_cards
    register_simple_followup_p47_cards(registry)
    from .native_paladin_aura_cards import register_native_paladin_aura_cards
    register_native_paladin_aura_cards(registry)
    from .simple_followup_p48_cards import register_simple_followup_p48_cards
    register_simple_followup_p48_cards(registry)
    from .played_quest_target_cards import register_played_quest_target_cards
    register_played_quest_target_cards(registry)
    from .simple_followup_p49_cards import register_simple_followup_p49_cards
    register_simple_followup_p49_cards(registry)
    from .native_forced_attack_cards import register_native_forced_attack_cards
    register_native_forced_attack_cards(registry)
    from .simple_followup_p50_cards import register_simple_followup_p50_cards
    register_simple_followup_p50_cards(registry)
    from .native_shuffle_damage_cards import register_native_shuffle_damage_cards
    register_native_shuffle_damage_cards(registry)
    from .simple_followup_p51_cards import register_simple_followup_p51_cards
    register_simple_followup_p51_cards(registry)
    from .native_ceremony_cards import register_native_ceremony_cards
    register_native_ceremony_cards(registry)
    from .native_immune_split_cards import register_native_immune_split_cards
    register_native_immune_split_cards(registry)
    from .simple_followup_p52_cards import register_simple_followup_p52_cards
    register_simple_followup_p52_cards(registry)
    from .native_pool_fill_cards import register_native_pool_fill_cards
    register_native_pool_fill_cards(registry)
    from .simple_followup_p53_cards import register_simple_followup_p53_cards
    register_simple_followup_p53_cards(registry)
    from .native_kindred_group_cards import register_native_kindred_group_cards
    register_native_kindred_group_cards(registry)
    from .simple_followup_p54_cards import register_simple_followup_p54_cards
    register_simple_followup_p54_cards(registry)
    from .native_pool_lifesteal_cards import register_native_pool_lifesteal_cards
    register_native_pool_lifesteal_cards(registry)
    from .simple_followup_p55_cards import register_simple_followup_p55_cards
    register_simple_followup_p55_cards(registry)
    from .native_named_summon_attack_cards import register_native_named_summon_attack_cards
    register_native_named_summon_attack_cards(registry)
    from .simple_followup_p56_cards import register_simple_followup_p56_cards
    register_simple_followup_p56_cards(registry)
    from .native_pool_hand_fill_cards import register_native_pool_hand_fill_cards
    register_native_pool_hand_fill_cards(registry)
    from .simple_followup_p57_cards import register_simple_followup_p57_cards
    register_simple_followup_p57_cards(registry)
    from .native_generated_cost_heal_cards import register_native_generated_cost_heal_cards
    register_native_generated_cost_heal_cards(registry)
    from .simple_followup_p58_cards import register_simple_followup_p58_cards
    register_simple_followup_p58_cards(registry)
    from .native_deck_pool_transform_cards import register_native_deck_pool_transform_cards
    register_native_deck_pool_transform_cards(registry)
    from .simple_followup_p59_cards import register_simple_followup_p59_cards
    register_simple_followup_p59_cards(registry)
    from .native_playable_spell_cards import register_native_playable_spell_cards
    register_native_playable_spell_cards(registry)
    from .simple_followup_p60_cards import register_simple_followup_p60_cards
    register_simple_followup_p60_cards(registry)
    from .native_amara_reward_cards import register_native_amara_reward_cards
    register_native_amara_reward_cards(registry)
    from .native_hand_size_summon_attack_cards import register_native_hand_size_summon_attack_cards
    register_native_hand_size_summon_attack_cards(registry)
    from .simple_followup_p61_cards import register_simple_followup_p61_cards
    register_simple_followup_p61_cards(registry)
    from .native_alexstrasza_full_health_cards import register_native_alexstrasza_full_health_cards
    register_native_alexstrasza_full_health_cards(registry)
    from .simple_followup_p62_cards import register_simple_followup_p62_cards
    register_simple_followup_p62_cards(registry)
    from .native_first_dragon_cost_cards import register_native_first_dragon_cost_cards
    register_native_first_dragon_cost_cards(registry)
    from .simple_followup_p63_cards import register_simple_followup_p63_cards
    register_simple_followup_p63_cards(registry)
    from .native_ashalon_adaptation_cards import register_native_ashalon_adaptation_cards
    register_native_ashalon_adaptation_cards(registry)
    from .simple_followup_p64_cards import register_simple_followup_p64_cards
    register_simple_followup_p64_cards(registry)
    from .native_generated_weapon_combo_cards import register_native_generated_weapon_combo_cards
    register_native_generated_weapon_combo_cards(registry)
    from .native_discovered_set_stats_cards import register_native_discovered_set_stats_cards
    register_native_discovered_set_stats_cards(registry)
    from .simple_followup_p65_cards import register_simple_followup_p65_cards
    register_simple_followup_p65_cards(registry)
    from .native_revealed_deck_spell_cards import register_native_revealed_deck_spell_cards
    register_native_revealed_deck_spell_cards(registry)
    from .native_silvermoon_location_cards import register_native_silvermoon_location_cards
    register_native_silvermoon_location_cards(registry)
    from .simple_followup_p66_cards import register_simple_followup_p66_cards
    register_simple_followup_p66_cards(registry)
    from .native_timeway_location_cards import register_native_timeway_location_cards
    register_native_timeway_location_cards(registry)
    from .native_lakkari_story_cards import register_native_lakkari_story_cards
    register_native_lakkari_story_cards(registry)
    from .simple_followup_p67_cards import register_simple_followup_p67_cards
    register_simple_followup_p67_cards(registry)
    from .native_discovery_remainder_cards import register_native_discovery_remainder_cards
    register_native_discovery_remainder_cards(registry)
    from .simple_followup_p68_cards import register_simple_followup_p68_cards
    register_simple_followup_p68_cards(registry)
    from .native_minion_health_theft_cards import register_native_minion_health_theft_cards
    register_native_minion_health_theft_cards(registry)
    from .simple_followup_p69_cards import register_simple_followup_p69_cards
    register_simple_followup_p69_cards(registry)
    from .native_coin_hand_cost_cards import register_native_coin_hand_cost_cards
    register_native_coin_hand_cost_cards(registry)
    from .simple_followup_p70_cards import register_simple_followup_p70_cards
    register_simple_followup_p70_cards(registry)
    from .native_mana_worth_cards import register_native_mana_worth_cards
    register_native_mana_worth_cards(registry)
    from .native_pterrordax_egg_cards import register_native_pterrordax_egg_cards
    register_native_pterrordax_egg_cards(registry)
    from .simple_followup_p71_cards import register_simple_followup_p71_cards
    register_simple_followup_p71_cards(registry)
    from .native_master_dusk_cards import register_native_master_dusk_cards
    register_native_master_dusk_cards(registry)
    from .simple_followup_p72_cards import register_simple_followup_p72_cards
    register_simple_followup_p72_cards(registry)
    from .native_actual_reborn_cards import register_native_actual_reborn_cards
    register_native_actual_reborn_cards(registry)
    from .native_menagerie_quest_cards import register_native_menagerie_quest_cards
    register_native_menagerie_quest_cards(registry)
    from .simple_followup_p73_cards import register_simple_followup_p73_cards
    register_simple_followup_p73_cards(registry)
    from .native_hiking_trail_cards import register_native_hiking_trail_cards
    register_native_hiking_trail_cards(registry)
    from .simple_followup_p74_cards import register_simple_followup_p74_cards
    register_simple_followup_p74_cards(registry)
    from .native_cavern_map_cards import register_native_cavern_map_cards
    register_native_cavern_map_cards(registry)
    from .native_odd_map_cards import register_native_odd_map_cards
    register_native_odd_map_cards(registry)
    from .simple_followup_p75_cards import register_simple_followup_p75_cards
    register_simple_followup_p75_cards(registry)
    from .native_discovered_turn_cards import register_native_discovered_turn_cards
    register_native_discovered_turn_cards(registry)
    from .simple_followup_p76_cards import register_simple_followup_p76_cards
    register_simple_followup_p76_cards(registry)
    from .native_discovery_cost_cards import register_native_discovery_cost_cards
    register_native_discovery_cost_cards(registry)
    from .simple_followup_p77_cards import register_simple_followup_p77_cards
    register_simple_followup_p77_cards(registry)
    from .simple_followup_p78_cards import register_simple_followup_p78_cards
    register_simple_followup_p78_cards(registry)
    from .simple_followup_p79_cards import register_simple_followup_p79_cards
    register_simple_followup_p79_cards(registry)
    from .native_discovery_delivery_cards import register_native_discovery_delivery_cards
    register_native_discovery_delivery_cards(registry)
    from .simple_followup_p80_cards import register_simple_followup_p80_cards
    register_simple_followup_p80_cards(registry)
    from .simple_followup_p81_cards import register_simple_followup_p81_cards
    register_simple_followup_p81_cards(registry)
    from .simple_followup_p82_cards import register_simple_followup_p82_cards
    register_simple_followup_p82_cards(registry)
    from .simple_followup_p83_cards import register_simple_followup_p83_cards
    register_simple_followup_p83_cards(registry)
    from .native_origin_stone_cards import register_native_origin_stone_cards
    register_native_origin_stone_cards(registry)
    from .simple_followup_p84_cards import register_simple_followup_p84_cards
    register_simple_followup_p84_cards(registry)
    from .native_gift_remainder_cards import register_native_gift_remainder_cards
    register_native_gift_remainder_cards(registry)
    from .simple_followup_p85_cards import register_simple_followup_p85_cards
    register_simple_followup_p85_cards(registry)
    from .native_dormant_growth_cards import register_native_dormant_growth_cards
    register_native_dormant_growth_cards(registry)
    from .simple_followup_p86_cards import register_simple_followup_p86_cards
    register_simple_followup_p86_cards(registry)
    from .native_hero_attack_target_cards import register_native_hero_attack_target_cards
    register_native_hero_attack_target_cards(registry)
    from .simple_followup_p87_cards import register_simple_followup_p87_cards
    register_simple_followup_p87_cards(registry)
    from .native_healing_conversion_cards import register_native_healing_conversion_cards
    register_native_healing_conversion_cards(registry)
    from .simple_followup_p88_cards import register_simple_followup_p88_cards
    register_simple_followup_p88_cards(registry)
    from .native_discard_summon_cards import register_native_discard_summon_cards
    register_native_discard_summon_cards(registry)
    from .simple_followup_p89_cards import register_simple_followup_p89_cards
    register_simple_followup_p89_cards(registry)
    from .native_held_mana_cards import register_native_held_mana_cards
    register_native_held_mana_cards(registry)
    from .simple_followup_p90_cards import register_simple_followup_p90_cards
    register_simple_followup_p90_cards(registry)
    from .native_past_entry_grant_cards import register_native_past_entry_grant_cards
    register_native_past_entry_grant_cards(registry)
    from .simple_followup_p91_cards import register_simple_followup_p91_cards
    register_simple_followup_p91_cards(registry)
    from .native_corpse_keep_discovery_cards import register_native_corpse_keep_discovery_cards
    register_native_corpse_keep_discovery_cards(registry)
    from .native_prepare_discovery_cards import register_native_prepare_discovery_cards
    register_native_prepare_discovery_cards(registry)
    from .simple_followup_p92_cards import register_simple_followup_p92_cards
    register_simple_followup_p92_cards(registry)
    from .simple_followup_p93_cards import register_simple_followup_p93_cards
    register_simple_followup_p93_cards(registry)
    from .native_retained_demon_transform_cards import register_native_retained_demon_transform_cards
    register_native_retained_demon_transform_cards(registry)
    from .simple_followup_p94_cards import register_simple_followup_p94_cards
    register_simple_followup_p94_cards(registry)
    from .native_split_healing_cards import register_native_split_healing_cards
    register_native_split_healing_cards(registry)
    from .simple_followup_p95_cards import register_simple_followup_p95_cards
    register_simple_followup_p95_cards(registry)
    from .native_recruit_program_cards import register_native_recruit_program_cards
    register_native_recruit_program_cards(registry)
    from .native_leyline_cards import register_native_leyline_cards
    register_native_leyline_cards(registry)
    from .native_companion_quantity_cards import register_native_companion_quantity_cards
    register_native_companion_quantity_cards(registry)
    from .native_companion_replacement_cards import register_native_companion_replacement_cards
    register_native_companion_replacement_cards(registry)
    from .native_owner_end_sleep_cards import register_native_owner_end_sleep_cards
    register_native_owner_end_sleep_cards(registry)
    from .native_opponent_deck_fill_cards import register_native_opponent_deck_fill_cards
    register_native_opponent_deck_fill_cards(registry)
    from .native_held_opponent_copy_cards import register_native_held_opponent_copy_cards
    register_native_held_opponent_copy_cards(registry)
    from .periodic_hand_cost_cards import register_periodic_hand_cost_cards
    register_periodic_hand_cost_cards(registry)
    from .historical_deathrattle_cards import register_historical_deathrattle_cards
    register_historical_deathrattle_cards(registry)
    from .killed_minion_recovery_cards import register_killed_minion_recovery_cards
    register_killed_minion_recovery_cards(registry)
    from .stored_native_source_cards import register_stored_native_source_cards
    register_stored_native_source_cards(registry)
    from .opponent_hand_consumption_card import register_opponent_hand_consumption_card
    register_opponent_hand_consumption_card(registry)
    from .hand_buff_deadline_card import register_hand_buff_deadline_card
    register_hand_buff_deadline_card(registry)
    from .burning_hand_spell_cards import register_burning_hand_spell_cards
    register_burning_hand_spell_cards(registry)
    from .corpse_discovery_copy_card import register_corpse_discovery_copy_card
    register_corpse_discovery_copy_card(registry)
    from .dead_treant_summon_card import register_dead_treant_summon_card
    register_dead_treant_summon_card(registry)
    from .cinder_sigil_card import register_cinder_sigil_card
    register_cinder_sigil_card(registry)
    from .hand_spell_transform_card import register_hand_spell_transform_card
    register_hand_spell_transform_card(registry)
    from .discovered_bottom_beast_card import register_discovered_bottom_beast_card
    register_discovered_bottom_beast_card(registry)
    from .destruction_bones_card import register_destruction_bones_card
    register_destruction_bones_card(registry)
    from .lowest_health_demons_card import register_lowest_health_demons_card
    register_lowest_health_demons_card(registry)
    from .owner_turn_pirate_damage_card import register_owner_turn_pirate_damage_card
    register_owner_turn_pirate_damage_card(registry)
    from .cannoneer_shot_quantity_card import register_cannoneer_shot_quantity_card
    register_cannoneer_shot_quantity_card(registry)
    from .temporary_hero_power_card import register_temporary_hero_power_card
    register_temporary_hero_power_card(registry)
    from .retained_banana_cards import register_retained_banana_cards
    register_retained_banana_cards(registry)
    from .adjacent_hand_cost_cards import register_adjacent_hand_cost_cards
    register_adjacent_hand_cost_cards(registry)
    from .upgraded_hero_power_cards import register_upgraded_hero_power_cards
    register_upgraded_hero_power_cards(registry)
    from .native_hand_parity_card import register_native_hand_parity_card
    register_native_hand_parity_card(registry)
    from .mask_battlecry_combo_card import register_mask_battlecry_combo_card
    register_mask_battlecry_combo_card(registry)
    from .generated_aura_duration_card import register_generated_aura_duration_card
    register_generated_aura_duration_card(registry)
    from .deck_stat_distribution_card import register_deck_stat_distribution_card
    register_deck_stat_distribution_card(registry)
    from .colossal_keyword_loss_cards import register_colossal_keyword_loss_cards
    register_colossal_keyword_loss_cards(registry)
    from .weapon_damage_replacement_card import register_weapon_damage_replacement_card
    register_weapon_damage_replacement_card(registry)
    from .infinite_weapon_attack_card import register_infinite_weapon_attack_card
    register_infinite_weapon_attack_card(registry)
    from .elemental_ammunition_card import register_elemental_ammunition_card
    register_elemental_ammunition_card(registry)
    from .random_weapon_battlecry_card import register_random_weapon_battlecry_card
    register_random_weapon_battlecry_card(registry)
    from .temporary_draw_discount_card import register_temporary_draw_discount_card
    register_temporary_draw_discount_card(registry)
    from .discovered_spell_destination_card import register_discovered_spell_destination_card
    register_discovered_spell_destination_card(registry)
    from .opponent_deck_gift_copy_card import register_opponent_deck_gift_copy_card
    register_opponent_deck_gift_copy_card(registry)
    from .one_cost_play_provider_card import register_one_cost_play_provider_card
    register_one_cost_play_provider_card(registry)
    from .nature_damage_replacement_cards import register_nature_damage_replacement_cards
    register_nature_damage_replacement_cards(registry)
    from .arcane_dragon_fabled_cards import register_arcane_dragon_fabled_cards
    register_arcane_dragon_fabled_cards(registry)
    from .divine_shield_hit_provider_card import register_divine_shield_hit_provider_card
    register_divine_shield_hit_provider_card(registry)
    from .temporal_hand_return_card import register_temporal_hand_return_card
    register_temporal_hand_return_card(registry)
    from .nature_opening_imbue_card import register_nature_opening_imbue_card
    register_nature_opening_imbue_card(registry)
    from .muradin_fabled_hammer_cards import register_muradin_fabled_hammer_cards
    register_muradin_fabled_hammer_cards(registry)
    from .azshara_fabled_location_cards import register_azshara_fabled_location_cards
    register_azshara_fabled_location_cards(registry)
    from .beatrix_deck_cards import register_beatrix_deck_cards
    register_beatrix_deck_cards(registry)
    from .soul_sacrifice_card import register_soul_sacrifice_card
    register_soul_sacrifice_card(registry)
    from .follow_hand_cards import register_follow_hand_cards
    register_follow_hand_cards(registry)
    from .choose_one_bribe_card import register_choose_one_bribe_card
    register_choose_one_bribe_card(registry)
    from .skeleton_key_card import register_skeleton_key_card
    register_skeleton_key_card(registry)
    from .location_reopen_card import register_location_reopen_card
    register_location_reopen_card(registry)
    from .timeway_warden_card import register_timeway_warden_card
    register_timeway_warden_card(registry)
    from .torch_card import register_torch_card
    register_torch_card(registry)
    from .shaladrassil_cards import register_shaladrassil_cards
    register_shaladrassil_cards(registry)
    from .jade_hellraiser_card import register_jade_hellraiser_card
    register_jade_hellraiser_card(registry)
    from .fill_board_hand_quest_cards import register_fill_board_hand_quest_cards
    register_fill_board_hand_quest_cards(registry)
    from .chef_nethrek_card import register_chef_nethrek_card
    register_chef_nethrek_card(registry)
    from .contraband_sideboard_card import register_contraband_sideboard_card
    register_contraband_sideboard_card(registry)
    from .seek_balance_cards import register_seek_balance_cards
    register_seek_balance_cards(registry)
    from .food_chain_quest_cards import register_food_chain_quest_cards
    register_food_chain_quest_cards(registry)
    from .legendary_beast_discovery_card import register_legendary_beast_discovery_card
    register_legendary_beast_discovery_card(registry)
    from .wild_god_discovery_card import register_wild_god_discovery_card
    register_wild_god_discovery_card(registry)
    from .aviana_lunar_cycle_card import register_aviana_lunar_cycle_card
    register_aviana_lunar_cycle_card(registry)
    from .omen_attack_growth_card import register_omen_attack_growth_card
    register_omen_attack_growth_card(registry)
    from .agamaggan_health_payment_card import register_agamaggan_health_payment_card
    register_agamaggan_health_payment_card(registry)
    from .ohnahra_top_deck_card import register_ohnahra_top_deck_card
    register_ohnahra_top_deck_card(registry)
    from .ursol_spell_aura_card import register_ursol_spell_aura_card
    register_ursol_spell_aura_card(registry)
    from .gelbin_deck_aura_card import register_gelbin_deck_aura_card
    register_gelbin_deck_aura_card(registry)
    from .opponent_hand_entry_theft_card import register_opponent_hand_entry_theft_card
    register_opponent_hand_entry_theft_card(registry)
    from .joint_hand_shuffle_card import register_joint_hand_shuffle_card
    register_joint_hand_shuffle_card(registry)
    from .private_hand_inspection_cards import register_private_hand_inspection_cards
    register_private_hand_inspection_cards(registry)
    from .alarm_hand_swap_card import register_alarm_hand_swap_card
    register_alarm_hand_swap_card(registry)
    from .murozond_owner_start_card import register_murozond_owner_start_card
    register_murozond_owner_start_card(registry)
    from .corrupted_roost_card import register_corrupted_roost_card
    register_corrupted_roost_card(registry)
    from .ascendance_card import register_ascendance_card
    register_ascendance_card(registry)
    from .plucky_podling_card import register_plucky_podling_card
    register_plucky_podling_card(registry)
    from .briarspawn_drake_card import register_briarspawn_drake_card
    register_briarspawn_drake_card(registry)
    from .underfel_rift_cards import register_underfel_rift_cards
    register_underfel_rift_cards(registry)
    from .futuristic_forefather_card import register_futuristic_forefather_card
    register_futuristic_forefather_card(registry)
    from .ectoplasmic_execution_cards import register_ectoplasmic_execution_cards
    register_ectoplasmic_execution_cards(registry)
    from .security_blind_spot_card import register_security_blind_spot_card
    register_security_blind_spot_card(registry)
    from .slice_and_dice_card import register_slice_and_dice_card
    register_slice_and_dice_card(registry)
    from .violet_tormentor_card import register_violet_tormentor_card
    register_violet_tormentor_card(registry)
    from .warptooth_card import register_warptooth_card
    register_warptooth_card(registry)
    from .damage_quest_reward_cards import register_damage_quest_reward_cards
    register_damage_quest_reward_cards(registry)
    from .secret_pair_card import register_secret_pair_card
    register_secret_pair_card(registry)
    from .mana_budget_cards import register_mana_budget_cards
    register_mana_budget_cards(registry)
    from .carved_treant_cards import register_carved_treant_cards
    register_carved_treant_cards(registry)
    from .wallow_card import register_wallow_card
    register_wallow_card(registry)
    from .time_lord_nozdormu_card import register_time_lord_nozdormu_card
    register_time_lord_nozdormu_card(registry)
    from .shadow_of_demise_card import register_shadow_of_demise_card
    register_shadow_of_demise_card(registry)
    from .fission_card import register_fission_card
    register_fission_card(registry)
    from .infinite_cost_card import register_infinite_cost_card
    register_infinite_cost_card(registry)
    from .commander_geddon_card import register_commander_geddon_card
    register_commander_geddon_card(registry)
    from .hand_jar_cards import register_hand_jar_cards
    register_hand_jar_cards(registry)
    from .live_source_hand_spell_card import register_live_source_hand_spell_card
    register_live_source_hand_spell_card(registry)
    from .native_stat_gain_card import register_native_stat_gain_card
    register_native_stat_gain_card(registry)
    from .remaining_mana_numbers_card import register_remaining_mana_numbers_card
    register_remaining_mana_numbers_card(registry)
    from .native_blight_replacement_cards import register_native_blight_replacement_cards
    register_native_blight_replacement_cards(registry)
    from .azalina_original_deck_card import register_azalina_original_deck_card
    register_azalina_original_deck_card(registry)
    from .nythendra_beetle_cards import register_nythendra_beetle_cards
    register_nythendra_beetle_cards(registry)
    from .overdraw_return_card import register_overdraw_return_card
    register_overdraw_return_card(registry)
    from .lost_city_quest_cards import register_lost_city_quest_cards
    register_lost_city_quest_cards(registry)
    from .mugzee_card import register_mugzee_card
    register_mugzee_card(registry)
    from .destructive_phoenix_card import register_destructive_phoenix_card
    register_destructive_phoenix_card(registry)
    from .shadowed_informant_card import register_shadowed_informant_card
    register_shadowed_informant_card(registry)
    from .anomalize_card import register_anomalize_card
    register_anomalize_card(registry)
    from .magmaw_card import register_magmaw_card
    register_magmaw_card(registry)
    from .nefarian_crafted_faces import register_nefarian_crafted_faces
    register_nefarian_crafted_faces(registry)
    from .nefarian_crafting_card import register_nefarian_crafting_card
    register_nefarian_crafting_card(registry)
    from .highborne_student_cards import register_highborne_student_cards
    register_highborne_student_cards(registry)
    from .toki_issued_spell_card import register_toki_issued_spell_card
    register_toki_issued_spell_card(registry)
    from .storm_gates_card import register_storm_gates_card
    register_storm_gates_card(registry)
    from .titanographer_next_spell_card import register_titanographer_next_spell_card
    register_titanographer_next_spell_card(registry)
    from .titanographer_draw_copy_cards import register_titanographer_draw_copy_cards
    register_titanographer_draw_copy_cards(registry)
    from .titanographer_osk_card import register_titanographer_osk_card
    register_titanographer_osk_card(registry)
    from .talanji_bwonsamdi_cards import register_talanji_bwonsamdi_cards
    register_talanji_bwonsamdi_cards(registry)
    from .medivh_fabled_cards import register_medivh_fabled_cards
    register_medivh_fabled_cards(registry)
    from .dragon_soul_essences_cards import register_dragon_soul_essences_cards
    register_dragon_soul_essences_cards(registry)
    from .kazakus_potion_cards import register_kazakus_potion_cards
    register_kazakus_potion_cards(registry)
    from .aya_counterfeit_cards import register_aya_counterfeit_cards
    register_aya_counterfeit_cards(registry)
    from .zuramat_prison_cards import register_zuramat_prison_cards
    register_zuramat_prison_cards(registry)
    from .noggenfogger_card import register_noggenfogger_card
    register_noggenfogger_card(registry)
    from .elise_location_cards import register_elise_location_cards
    register_elise_location_cards(registry)
    from .watfin_card import register_watfin_card
    register_watfin_card(registry)
    from .kazakus_sham_trial_card import register_kazakus_sham_trial_card
    register_kazakus_sham_trial_card(registry)
    from .avatar_standard_pack_card import register_avatar_standard_pack_card
    register_avatar_standard_pack_card(registry)
    from .nozdormu_turn_clock_card import register_nozdormu_turn_clock_card
    register_nozdormu_turn_clock_card(registry)
    from .timethief_rafaam_cards import register_timethief_rafaam_cards
    register_timethief_rafaam_cards(registry)
    from .broxigar_cards import register_broxigar_cards
    register_broxigar_cards(registry)
    from .past_one_cost_leaf_cards import register_past_one_cost_leaf_cards
    register_past_one_cost_leaf_cards(registry)
    from .past_hand_weapon_leaf_cards import register_past_hand_weapon_leaf_cards
    register_past_hand_weapon_leaf_cards(registry)
    from .black_empire_primitive_cards import register_black_empire_primitive_cards
    register_black_empire_primitive_cards(registry)
    from .black_empire_stat_cards import register_black_empire_stat_cards
    register_black_empire_stat_cards(registry)
    from .black_empire_followup_cards import register_black_empire_followup_cards
    register_black_empire_followup_cards(registry)
    from .black_empire_death_condition_cards import register_black_empire_death_condition_cards
    register_black_empire_death_condition_cards(registry)
    from .native_assemble_entry_cards import register_native_assemble_entry_cards
    register_native_assemble_entry_cards(registry)
    from .native_assemble_followup_cards import register_native_assemble_followup_cards
    register_native_assemble_followup_cards(registry)
    from .assemble_source_exception_cards import register_assemble_source_exception_cards
    register_assemble_source_exception_cards(registry)
    from .native_consumer_followup_cards import register_native_consumer_followup_cards
    register_native_consumer_followup_cards(registry)
    from .native_combat_consumer_cards import register_native_combat_consumer_cards
    register_native_combat_consumer_cards(registry)
    from .hand_rank_death_neighbor_cards import register_hand_rank_death_neighbor_cards
    register_hand_rank_death_neighbor_cards(registry)
    from .neptulon_entry_stat_card import register_neptulon_entry_stat_card
    register_neptulon_entry_stat_card(registry)
    from .native_pool_hand_copy_cards import register_native_pool_hand_copy_cards
    register_native_pool_hand_copy_cards(registry)
    from .draw_type_native_cards import register_draw_type_native_cards
    register_draw_type_native_cards(registry)
    from .held_spell_school_cards import register_held_spell_school_cards
    register_held_spell_school_cards(registry)
    from .ancient_word_cards import register_ancient_word_cards
    register_ancient_word_cards(registry)
    from .corpse_damage_wave_card import register_corpse_damage_wave_card
    register_corpse_damage_wave_card(registry)
    from .hand_shuffle_turn_copy_cards import register_hand_shuffle_turn_copy_cards
    register_hand_shuffle_turn_copy_cards(registry)
    from .armor_gain_history_card import register_armor_gain_history_card
    register_armor_gain_history_card(registry)
    from .armor_summon_reward_card import register_armor_summon_reward_card
    register_armor_summon_reward_card(registry)
    from .health_armor_conversion_card import register_health_armor_conversion_card
    register_health_armor_conversion_card(registry)
    from .end_turn_fatigue_card import register_end_turn_fatigue_card
    register_end_turn_fatigue_card(registry)
    from .adjacent_deathrattle_copy_card import register_adjacent_deathrattle_copy_card
    register_adjacent_deathrattle_copy_card(registry)
    from .hatching_sigil_card import register_hatching_sigil_card
    register_hatching_sigil_card(registry)
    from .positional_keyword_aura_card import register_positional_keyword_aura_card
    register_positional_keyword_aura_card(registry)
    from .combo_play_turn_cost_card import register_combo_play_turn_cost_card
    register_combo_play_turn_cost_card(registry)
    from .source_cost_stat_spell_card import register_source_cost_stat_spell_card
    register_source_cost_stat_spell_card(registry)
    from .hand_entry_spell_provider_card import register_hand_entry_spell_provider_card
    register_hand_entry_spell_provider_card(registry)
    from .encircle_card import register_encircle_card
    register_encircle_card(registry)
    from .flame_shock_card import register_flame_shock_card
    register_flame_shock_card(registry)
    from .efflorescence_card import register_efflorescence_card
    register_efflorescence_card(registry)
    from .frontline_ironborn_card import register_frontline_ironborn_card
    register_frontline_ironborn_card(registry)
    from .kronn_impaler_card import register_kronn_impaler_card
    register_kronn_impaler_card(registry)
    from .broodqueen_shakar_card import register_broodqueen_shakar_card
    register_broodqueen_shakar_card(registry)
    from .ammunae_card import register_ammunae_card
    register_ammunae_card(registry)
    from .zerontu_card import register_zerontu_card
    register_zerontu_card(registry)
    from .dreadlynx_cards import register_dreadlynx_cards
    register_dreadlynx_cards(registry)
    from .ritual_cards import register_ritual_cards
    register_ritual_cards(registry)
    from .kithix_cards import register_kithix_cards
    register_kithix_cards(registry)
    from .mechacycle_card import register_mechacycle_card
    register_mechacycle_card(registry)
    from .amitut_card import register_amitut_card
    register_amitut_card(registry)
    from .holy_soldier_cards import register_holy_soldier_cards
    register_holy_soldier_cards(registry)
    from .therazane_card import register_therazane_card
    register_therazane_card(registry)
    from .lightcaller_card import register_lightcaller_card
    register_lightcaller_card(registry)
    from .reload_card import register_reload_card
    register_reload_card(registry)
    from .empire_cthun_cards import register_empire_cthun_cards
    register_empire_cthun_cards(registry)
    from .nzoth_card import register_nzoth_card
    register_nzoth_card(registry)
    from .yshaarj_card import register_yshaarj_card
    register_yshaarj_card(registry)
    from .uldir_quarantine_card import register_uldir_quarantine_card
    register_uldir_quarantine_card(registry)
    from .fetid_devourer_card import register_fetid_devourer_card
    register_fetid_devourer_card(registry)
    from .ghuun_card import register_ghuun_card
    register_ghuun_card(registry)
    from .scion_insight_card import register_scion_insight_card
    register_scion_insight_card(registry)
    from .discs_norgannon_card import register_discs_norgannon_card
    register_discs_norgannon_card(registry)
    from .setesh_card import register_setesh_card
    register_setesh_card(registry)
    from .isiset_card import register_isiset_card
    register_isiset_card(registry)
    from .drestagath_card import register_drestagath_card
    register_drestagath_card(registry)
    from .archaedas_card import register_archaedas_card
    register_archaedas_card(registry)
    from .shadowcrafter_card import register_shadowcrafter_card
    register_shadowcrafter_card(registry)
    from .rajh_card import register_rajh_card
    register_rajh_card(registry)
    from .assemble_sigil_fragments import register_assemble_sigil_fragments
    register_assemble_sigil_fragments(registry)
    from .assemble_weapon_hero_fragments import register_assemble_weapon_hero_fragments
    register_assemble_weapon_hero_fragments(registry)
    from .assemble_draw_armor_heal_fragments import register_assemble_draw_armor_heal_fragments
    register_assemble_draw_armor_heal_fragments(registry)
    from .assemble_dual_prefix_fragments import register_assemble_dual_prefix_fragments
    register_assemble_dual_prefix_fragments(registry)
    from .assemble_conditional_spell_damage_fragments import register_assemble_conditional_spell_damage_fragments
    register_assemble_conditional_spell_damage_fragments(registry)
    from .assemble_native_damage_fragments import register_assemble_native_damage_fragments
    register_assemble_native_damage_fragments(registry)
    from .assemble_native_summon_fragments import register_assemble_native_summon_fragments
    register_assemble_native_summon_fragments(registry)
    from .assemble_native_buffs_removal_health_fragments import register_assemble_native_buffs_removal_health_fragments
    register_assemble_native_buffs_removal_health_fragments(registry)
    register_reviewed_pool_metadata(registry)
    from .candidate_generation_catalog import register_candidate_pool_metadata
    register_candidate_pool_metadata(registry)
    from .generation_source_families import register_generation_source_families
    register_generation_source_families(registry)
    registry.validate()
    return registry
