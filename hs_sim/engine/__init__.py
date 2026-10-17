"""Headless, deterministic traditional-card-game rules prototype."""
from .actions import UseInteractable, Concede
from .model import InteractableSpec
from .interactables import InstallInteractable
from .model import (AttackPolicySpec, AttackPolicyCondition, CurrentTurnFactQuery,
                    BoardPresenceReference, AttackSourcePolicy, AttackSourceBinding)
from .turn_facts import current_turn_fact_count
from .attack_policies import GrantAttackPolicy, attack_limit, has_action_remaining
from .model import (PrintedAttackPolicyDeclaration, SelfPrintedAttackReference,
                    PrintedAttackPermitRequest, PrintedAttackPermit)
from .printed_attack_permits import GrantPrintedAttackPermit, capture_printed_attack_permit
from .model import StatRelationSpec, StatRelationOperand, StatRelationLayer
from .stat_relations import GrantStatRelation
from .model import TribeChangeSpec
from .discard_history import DiscardRecord, discarded_cards
from .tribes import ChangeMinionTribes, TribeState, tribe_state, has_any_tribe, has_any_subtype
__tribe_exports = ['TribeChangeSpec', 'ChangeMinionTribes', 'TribeState', 'tribe_state', 'has_any_tribe', 'has_any_subtype']
__discard_exports = ['DiscardRecord', 'discarded_cards']
__stat_relation_exports = ['StatRelationSpec', 'StatRelationOperand', 'StatRelationLayer', 'GrantStatRelation']
__printed_permit_exports = ['PrintedAttackPolicyDeclaration', 'SelfPrintedAttackReference',
    'PrintedAttackPermitRequest', 'PrintedAttackPermit', 'GrantPrintedAttackPermit', 'capture_printed_attack_permit']
from .model import CounterPolicySpec
from .model import TimedKeywordSpec, KeywordExpiry, OwnerTurnExpiry
from .model import HandOtherClassRow, HandOtherClassMatch
from .hand_conditions import capture_hand_other_class, hand_has_other_class
from .model import CardAbilityCondition, CostAuraSpec
from .card_conditions import matches_ability
from .counter_policies import GrantCounterPolicy
from .actions import Attack, EndTurn, PlayCard, UseHeroPower, UseHandAction, UseLocation, LaunchStarship, SelectChoice
from .errors import IllegalAction, ResolutionError, ResolutionLimitExceeded, SnapshotError
from .game import ActionResult, Game, PlayerSetup, Scenario
from .model import AbilityInstance, AuraSpec, CardDefinition, CardType, DamageKind, DeathRecord, Enchantment, HandActionSpec, Keyword, StatReference, TargetMode, TargetSpec, TriggerSpec, Zone
from .model import KeywordAuraSpec
from .keyword_auras import GrantKeywordAura
from .model import SpellRepeatSpec, SpellRepeatRecord
from .model import RecipientMetadataFilter, RepeatMatchSpec
from .model import RepeatSourceEligibility, RepeatWitnessProfile
from .repeat_source_conditions import qualifying_repeat_witnesses
from .spell_repeats import GrantSpellRepeatAura
from .card_spell_repeats import GrantCardSpellRepeat, RemoveCardSpellRepeat
from .model import HealthLossKind, HealthLossReplacementSpec
from .health_loss import LoseHealth, GainMaxHealth, GrantHealthLossReplacement
from .model import HealthLossFloorSpec
from .health_loss_floors import GrantHealthLossFloor, LossFloorPlan, LossFloorResult, loss_floor_result
from .registry import Registry, RuleContext, UnsupportedDefinitionError
from .dredge import Dredge
from .model import CardPreview
from .summon_sources import CopyStoredMinion
from .rules import Ruleset
from .fabled_decks import FabledSpec, expand_fabled_cards
from .model import CostScope, CostSpec, CostModifier, PaymentType, Resource
from .costs import CostQuote
from .ordered_choices import ChooseInOrder
from .model import HandEntryRecord
from .model import ShatterSpec
from .model import HandLifetime, HandRepeatSpec
from .model import HandDerivativeSpec
from .temporary_cards import CreateTemporaryCard, MakeHandCardTemporary
from .model import HealingKind, HealthFlow, HealthLayer, HealthOp, HealthRule, SpellSchool
from .model import ChoiceItem, ChoiceResult, PendingChoice
from .model import CardClass, CardMetadata, ChoicePurpose, OpeningHook, OpeningState, Rarity, Runes
from .construction import DeckPolicy, DeckSpec, DeckValidation, DeckValidationError, MatchSetup, validate_deck
from .registry import PlayerRuleContext
from .player_api import PlayerPort
from .starships import LaunchStarshipEffect
from .bonus_effects import GrantRandomBonusEffects
from .pools import SummonFromCandidates
from .pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, PoolQuery, DiscoverFromPool, GenerateFromPool
from .zones import AddToDeck, CardReference, MoveCard, CopyCard, DiscardCard, ShuffleDeck, ReorderZone, DrawMatching, DiscardMatching, ChooseFromZone

__all__ = ['ActionResult', 'Attack', 'EndTurn', 'Concede', 'PlayCard', 'UseHeroPower', 'UseHandAction', 'UseLocation', 'HandActionSpec', 'LaunchStarship', 'LaunchStarshipEffect', 'Game', 'PlayerSetup', 'Scenario',
           'AttackPolicySpec', 'AttackPolicyCondition', 'GrantAttackPolicy', 'attack_limit', 'has_action_remaining',
           'BoardPresenceReference', 'AttackSourcePolicy', 'AttackSourceBinding',
           'CounterPolicySpec', 'GrantCounterPolicy',
           'CardAbilityCondition', 'CostAuraSpec', 'matches_ability',
           'HandEntryRecord', 'ShatterSpec', 'HandLifetime', 'HandRepeatSpec', 'HandDerivativeSpec', 'CreateTemporaryCard', 'MakeHandCardTemporary',
           'SpellRepeatSpec', 'SpellRepeatRecord', 'RecipientMetadataFilter', 'RepeatMatchSpec', 'RepeatSourceEligibility', 'RepeatWitnessProfile', 'qualifying_repeat_witnesses', 'GrantSpellRepeatAura', 'GrantCardSpellRepeat', 'RemoveCardSpellRepeat',
           'HealthLossKind', 'HealthLossReplacementSpec', 'LoseHealth', 'GainMaxHealth', 'GrantHealthLossReplacement',
           'AbilityInstance', 'AuraSpec', 'KeywordAuraSpec', 'GrantKeywordAura', 'CardDefinition', 'CardType', 'DeathRecord', 'Enchantment',
           'Keyword', 'StatReference', 'DamageKind', 'TargetMode', 'TargetSpec', 'TriggerSpec', 'Zone',
           'Registry', 'RuleContext', 'Ruleset', 'IllegalAction', 'ResolutionError',
           'ResolutionLimitExceeded', 'SnapshotError', 'UnsupportedDefinitionError',
           'CostScope', 'CostSpec', 'CostModifier', 'CostQuote', 'ChooseInOrder', 'PaymentType', 'Resource',
           'HealingKind', 'HealthFlow', 'HealthLayer', 'HealthOp', 'HealthRule', 'SpellSchool',
           'SelectChoice', 'ChoiceItem', 'ChoiceResult', 'PendingChoice',
           'CardClass', 'CardMetadata', 'ChoicePurpose', 'OpeningHook', 'OpeningState', 'Rarity', 'Runes',
           'DeckPolicy', 'DeckSpec', 'DeckValidation', 'DeckValidationError', 'MatchSetup', 'validate_deck',
           'PlayerRuleContext', 'PlayerPort', 'GenerationContext', 'PoolCard', 'PoolDefinition', 'PoolMember',
           'PoolQuery', 'DiscoverFromPool', 'GenerateFromPool', 'AddToDeck', 'CardReference', 'MoveCard', 'CopyCard',
           'DiscardCard', 'ShuffleDeck', 'ReorderZone', 'DrawMatching', 'DiscardMatching', 'ChooseFromZone',
           'GrantRandomBonusEffects', 'SummonFromCandidates']
__all__ += __tribe_exports
__all__ += __discard_exports

from .zones import DestroyStoredCard, CardDestructionRecord, destruction_result
__all__ += ['DestroyStoredCard', 'CardDestructionRecord', 'destruction_result']

from .locations import PlaceLocation, ModifyLocation, RefreshLocation, DestroyLocation
__all__ += ['PlaceLocation', 'ModifyLocation', 'RefreshLocation', 'DestroyLocation']

from .fatigue import TakeFatigue
__all__ += ['TakeFatigue']

from .model import StarshipLaunchRecord
from .starships import RelaunchStarships
__all__ += ['StarshipLaunchRecord', 'RelaunchStarships']

from .model import DormancyState
from .dormancy import MakeDormant, AwakenMinion, AdvanceDormancy
__all__ += ['DormancyState', 'MakeDormant', 'AwakenMinion', 'AdvanceDormancy']

from .actions import UseMinionAbility
from .model import ActivatedAbilitySpec
__all__ += ['UseMinionAbility', 'ActivatedAbilitySpec']
__all__ += ['UseInteractable', 'InteractableSpec', 'InstallInteractable']

from .model import QuestSpec, QuestStageSpec, QuestProgress
from .quests import AdvanceQuest, ResetQuestProgress, RemoveQuest
__all__ += ['QuestSpec', 'QuestStageSpec', 'QuestProgress', 'AdvanceQuest', 'ResetQuestProgress', 'RemoveQuest']

from .model import PlayerEffect, PlayerEffectSpec, PlayerAuraSpec, PlayerKeywordAuraSpec
from .player_effects import AddPlayerEffect, RemovePlayerEffect, ConsumePlayerEffect
__all__ += ['PlayerEffect', 'PlayerEffectSpec', 'PlayerAuraSpec', 'PlayerKeywordAuraSpec', 'AddPlayerEffect', 'RemovePlayerEffect']

from .model import SecretSpec, ActionWindow
from .secrets import SetSecret, RemoveSecret
from .interrupts import CounterSpell, RedirectAttack, SummonAttackTarget, RedirectSpellTarget, SummonSpellTarget
__all__ += ['SecretSpec', 'ActionWindow', 'SetSecret', 'RemoveSecret', 'CounterSpell', 'RedirectAttack', 'SummonAttackTarget',
           'RedirectSpellTarget', 'SummonSpellTarget']

from .model import PlayRecord
from .model import (OwnerTurnRecord, FrozenPlayedFaceFact, PlayedTypeQuery,
                    OwnerTurnMatchRow, PreviousOwnerTurnMatch, OwnerTurnTypeMatch, OwnerTurnTypeHistory)
from .model import (IntrinsicCostSpec, IntrinsicCostStageFact, IntrinsicCostOperationFact,
                    OwnerTurnQueryBoundaryFact, GeneratedCostQuoteInput, GeneratedCostQuoteFact)
from .costs import capture_generated_quote_fact
from .model import PaidHandClose, PaidHandInterruption
__all__ += ['PaidHandClose', 'PaidHandInterruption']
__all__ += ['IntrinsicCostSpec', 'IntrinsicCostStageFact', 'IntrinsicCostOperationFact',
            'OwnerTurnQueryBoundaryFact', 'GeneratedCostQuoteInput', 'GeneratedCostQuoteFact',
            'capture_generated_quote_fact']
from .owner_turns import query_previous_owner_turn, query_for_definition, query_owner_turn_history
__all__ += ['OwnerTurnRecord', 'FrozenPlayedFaceFact', 'PlayedTypeQuery',
            'OwnerTurnMatchRow', 'PreviousOwnerTurnMatch',
            'query_previous_owner_turn', 'query_for_definition',
            'OwnerTurnTypeMatch', 'OwnerTurnTypeHistory', 'query_owner_turn_history']
from .play_history import played_cards, preplay_conditions
__all__ += ['PlayRecord', 'played_cards', 'preplay_conditions']

from .hand_upgrades import BuffStoredCard, UpgradeHandCard
__all__ += ['BuffStoredCard', 'UpgradeHandCard']

from .model import HandProgressSpec
__all__ += ['HandProgressSpec']

from .model import LimitedTriggerSpec
from .limited_triggers import GrantLimitedTrigger
__all__ += ['LimitedTriggerSpec', 'GrantLimitedTrigger']

from .model import EndTurnSpec, EndTurnSubject, EndTurnBatch, EndTurnCapture, EndTurnRecord
__all__ += ['EndTurnSpec', 'EndTurnSubject', 'EndTurnBatch', 'EndTurnCapture', 'EndTurnRecord']

from .model import EndTurnSelector, EndTurnRequest, EndTurnActivationProfile, EndTurnActivation
__all__ += ['EndTurnSelector', 'EndTurnRequest', 'EndTurnActivationProfile', 'EndTurnActivation']

from .model import EndTurnCandidateProfile, EndTurnProducerRequest, EndTurnCarrier, EndTurnSelection, validate_end_turn_rng
__all__ += ['EndTurnCandidateProfile', 'EndTurnProducerRequest', 'EndTurnCarrier', 'EndTurnSelection', 'validate_end_turn_rng']

from .end_turns import TriggerEndTurnEffects
__all__ += ['TriggerEndTurnEffects']

from .end_turn_producers import TriggerRandomEndTurnEffects, end_turn_carriers
__all__ += ['TriggerRandomEndTurnEffects', 'end_turn_carriers']

from .model import EndTurnRepeatMatchSpec, EndTurnRepeatSpec, EndTurnRepeatContributor, EndTurnRepeatPlan
__all__ += ['EndTurnRepeatMatchSpec', 'EndTurnRepeatSpec', 'EndTurnRepeatContributor', 'EndTurnRepeatPlan']

from .model import AppendageSpec, ColossalRecord
from .colossal import SummonStoredCard
__all__ += ['AppendageSpec', 'ColossalRecord', 'SummonStoredCard']

from .herald import Herald, herald_count, herald_rank, herald_multiplier
from .model import HeraldRecord
__all__ += ['Herald', 'HeraldRecord', 'herald_count', 'herald_rank', 'herald_multiplier']

from .sacrifice import MinionReference, DestroyForBuff, SacrificeAdjacent
__all__ += ['MinionReference', 'DestroyForBuff', 'SacrificeAdjacent']

from .model import DeckSacrificeSpec
from .sacrifice import BuffCapturedMinion, GrantCapturedKeyword, GrantDeckSacrificeAura
from .zones import DestroyDeckCard, DestroyDeckMatching
__all__ += ['DeckSacrificeSpec', 'BuffCapturedMinion', 'GrantDeckSacrificeAura', 'DestroyDeckCard', 'DestroyDeckMatching']
__all__ += ['GrantCapturedKeyword']

from .hand_keywords import GrantStoredKeyword
__all__ += ['GrantStoredKeyword']

from .model import ResurrectionRecord, SummonStats
from .summon_sources import DeathQuery, Resurrect, ResurrectMinion, SummonFromZone, SummonFromStoredCandidates, death_candidates
__all__ += ['ResurrectionRecord', 'DeathQuery', 'Resurrect', 'ResurrectMinion', 'SummonFromZone', 'SummonFromStoredCandidates', 'death_candidates']
__all__ += ['SummonStats']

from .model import SpellCastRecord
from .spell_casts import CastSpell, CastStoredSpell, cast_spells
__all__ += ['SpellCastRecord', 'CastSpell', 'CastStoredSpell', 'cast_spells']

from .model import CastWhenDrawnSpec, DrawRecord
from .model import RewindSpec
__all__ += ['RewindSpec']
from .model import RewindOutcomeRecord
from .rewind_outcomes import GrantRewindRetention
__all__ += ['RewindOutcomeRecord', 'GrantRewindRetention']
from .draw_casts import drawn_cards
__all__ += ['CastWhenDrawnSpec', 'DrawRecord', 'drawn_cards']

from .spell_history import (SpellHistoryQuery, spell_history_candidates, DiscoverSpellHistory,
    RecastSpell, RecastFromHistory, CastFromPool)
__all__ += ['SpellHistoryQuery', 'spell_history_candidates', 'DiscoverSpellHistory',
    'RecastSpell', 'RecastFromHistory', 'CastFromPool']
__all__ += ['Dredge', 'CardPreview', 'CopyStoredMinion']
from .excavate import Excavate, ExcavationProfile, ExcavationClass, excavation_count
from .pools import GenerationPolicy
__all__ += ['GenerationPolicy']
from .model import ExcavationRecord
__all__ += ['Excavate','ExcavationProfile','ExcavationClass','ExcavationRecord','excavation_count']

from .cross_zone import MinionScope, minion_references, BuffMinionsInZones, TransformCapturedMinion, TransformMinionsInZones, TransformStoredCard, TransformStoredIntoCopy, TransformMinionIntoCopy, TransformDefiningHandCard, TransformDefiningHandCardFromPool
__all__ += ['MinionScope','minion_references','BuffMinionsInZones','TransformCapturedMinion','TransformMinionsInZones','TransformStoredCard','TransformStoredIntoCopy','TransformMinionIntoCopy','TransformDefiningHandCard','TransformDefiningHandCardFromPool']
from .model import HandMirrorSpec
__all__ += ['HandMirrorSpec']

from .health_loss import ChangeHeroMaxHealth, StealHeroHealth
__all__ += ['ChangeHeroMaxHealth','StealHeroHealth']

from .imbue import Imbue, ImbueClass, ImbueProfile, imbue_count, imbue_value
from .model import ImbueRecord
__all__ += ['Imbue','ImbueClass','ImbueProfile','ImbueRecord','imbue_count','imbue_value']

from .model import (HeroPowerRecord, HeroPowerPayloadBatch, HeroPowerPayloadCapture, HeroPowerPayloadRecord,
                    HeroPowerRepeatSpec, HeroPowerRepeatMatchSpec,
                    HeroPowerRepeatContributor, HeroPowerRepeatPlan)
from .hero_powers import AddHeroPower, RemoveHeroPower, TriggerHeroPower, activated_powers, hero_power_references
from .hero_power_repeats import GrantHeroPowerRepeatAura
from .model import HeroPowerReference
__all__ += ['HeroPowerRecord','HeroPowerPayloadBatch','HeroPowerPayloadCapture','HeroPowerPayloadRecord',
            'HeroPowerRepeatSpec','HeroPowerRepeatMatchSpec',
            'HeroPowerRepeatContributor','HeroPowerRepeatPlan',
            'GrantHeroPowerRepeatAura',
            'AddHeroPower','RemoveHeroPower','TriggerHeroPower','activated_powers',
            'HeroPowerReference','hero_power_references']

from .play_history import is_first_play
__all__ += ['is_first_play']

from .model import ChooseBranch, ChooseOneSpec
from .choose_one import GrantChooseBoth
__all__ += ['ChooseBranch','ChooseOneSpec','GrantChooseBoth']

from .inspire import completed_manual_power, is_inspire
__all__ += ['completed_manual_power', 'is_inspire']

from .cross_zone import RandomBuffStoredMinion, TransformMinionFromPool
__all__ += ['RandomBuffStoredMinion','TransformMinionFromPool']

from .pools import SummonFromPool
__all__ += ['SummonFromPool']
from .costs import quote_generated_cost
from .pool_offers import PoolOfferGroup, ChooseFromPools
__all__ += ['quote_generated_cost','PoolOfferGroup','ChooseFromPools']
from .health_outcomes import HealthResult, health_result, is_overkill, is_honorable_kill, is_overheal
__all__ += ['HealthResult', 'health_result', 'is_overkill', 'is_honorable_kill', 'is_overheal']
from .model import HealingRecord
from .healing_history import healing_records, restored_health, hero_was_healed
__all__ += ['HealingRecord', 'healing_records', 'restored_health', 'hero_was_healed']
from .model import DeathCause
from .death_causes import was_honorably_killed
__all__ += ['DeathCause', 'was_honorably_killed']

from .model import (BattlecryRecord, BattlecryPayload, BattlecryRepeatSpec, BattlecryRepeatPlan,
                    BattlecryBatchRecord, BattlecryRecipientMetadataFilter, BattlecryRepeatMatchSpec,
                    BattlecryRecipient, BattlecryAcceptanceReceipt)
from .battlecry_repeats import GrantBattlecryRepeatAura
from .model import BattlecryRepeatModifier
from .battlecry_modifiers import AddBattlecryRepeatModifier, RemoveBattlecryRepeatModifier
__all__ += ['BattlecryRecord','BattlecryPayload','BattlecryRepeatSpec','BattlecryRepeatPlan',
            'BattlecryRecipientMetadataFilter','BattlecryRepeatMatchSpec','BattlecryRecipient','BattlecryAcceptanceReceipt',
            'BattlecryBatchRecord','GrantBattlecryRepeatAura','BattlecryRepeatModifier',
            'AddBattlecryRepeatModifier','RemoveBattlecryRepeatModifier','activated_battlecries','battlecry_record']
from .battlecries import activated_battlecries, battlecry_record
from .battlecry_sources import (BattlecryHistoryQuery, battlecry_history_candidates,
    TriggerBattlecry, RepeatBattlecry, RepeatBattlecries)
__all__ += ['BattlecryHistoryQuery','battlecry_history_candidates','TriggerBattlecry',
            'RepeatBattlecry','RepeatBattlecries']
from .played_battlecries import (PlayedBattlecryQuery, played_battlecry_candidates,
    RepeatPlayedBattlecry, RepeatPlayedBattlecries, battlecry_play_window)
__all__ += ['PlayedBattlecryQuery','played_battlecry_candidates','RepeatPlayedBattlecry',
            'RepeatPlayedBattlecries','battlecry_play_window']
from .battlecry_sequences import (BattlecrySequencePolicy, PlayedBattlecryFilter, PlayedBattlecryCandidate,
    played_battlecry_payloads, RepeatPlayedBattlecrySequence)
__all__ += ['BattlecrySequencePolicy','PlayedBattlecryFilter','PlayedBattlecryCandidate','played_battlecry_payloads',
            'RepeatPlayedBattlecrySequence']
from .interrupts import CounterCard, CounterMinion
__all__ += ['CounterCard', 'CounterMinion']

from .deck_conditions import DeckCondition, DeckCostCondition, DeckSpellSchoolCondition, DeckMinionCostCondition, DeckCostCeilingCondition, DeckMinionCostSumCondition, DeckCostDiversityCondition, DeckCountCondition, CheckDeckCondition, UnknownDeckFacts, matches_deck_condition
__all__ += ['DeckCondition', 'DeckCostCondition', 'DeckSpellSchoolCondition', 'DeckMinionCostCondition', 'DeckCostCeilingCondition', 'DeckMinionCostSumCondition', 'DeckCostDiversityCondition', 'DeckCountCondition', 'CheckDeckCondition', 'UnknownDeckFacts', 'matches_deck_condition']

from .model import ComboPayload, ComboRecord
from .combos import activated_combos
__all__ += ['ComboPayload','ComboRecord','activated_combos']

from .model import (ComboRepeatSpec, ComboRepeatModifier, ComboRepeatPlan, ComboBatchRecord, ComboPolicyReceipt,
                    ComboRecipient, ComboRecipientMetadataFilter, ComboRepeatMatchSpec, ComboAcceptanceReceipt)
from .combo_repeats import GrantComboRepeatAura
from .combo_modifiers import AddComboRepeatModifier, RemoveComboRepeatModifier
__all__ += ['ComboRepeatSpec','ComboRepeatModifier','ComboRepeatPlan','ComboBatchRecord','ComboPolicyReceipt',
            'ComboRecipient','ComboRecipientMetadataFilter','ComboRepeatMatchSpec','ComboAcceptanceReceipt',
            'GrantComboRepeatAura','AddComboRepeatModifier','RemoveComboRepeatModifier']

__all__ += ['TimedKeywordSpec', 'KeywordExpiry', 'OwnerTurnExpiry']
__all__ += ['HandOtherClassRow','HandOtherClassMatch','capture_hand_other_class','hand_has_other_class']

from .model import SpellRepeatModifier, SpellPolicyReceipt
from .spell_modifiers import AddSpellRepeatModifier, RemoveSpellRepeatModifier
from .choose_policies import AddChooseBothModifier, RemoveChooseBothModifier, ChooseBothModifier
__all__ += ['AddChooseBothModifier', 'RemoveChooseBothModifier', 'ChooseBothModifier']
from .choose_branch_state import SetChooseBranch
from .model import ChooseBranchSelection
__all__ += ['SetChooseBranch', 'ChooseBranchSelection']
__all__ += ['SpellRepeatModifier','SpellPolicyReceipt','AddSpellRepeatModifier','RemoveSpellRepeatModifier']

from .model import HeldSpellProgress
from .held_spells import satisfied as held_spell_condition
__all__ += ['HeldSpellProgress','held_spell_condition']

from .card_creation import CardSpellRepeatGrant, CreatedMinionGrant, DiscoveryMinionGift
from .pools import DiscoveryGiftPool
__all__ += ["CardSpellRepeatGrant", "CreatedMinionGrant", "DiscoveryMinionGift", "DiscoveryGiftPool"]
from .dark_gifts import DARK_GIFTS, GrantDarkGift, dark_gift_pool
__all__ += ["DARK_GIFTS", "GrantDarkGift", "dark_gift_pool"]

from .model import DeathrattleCapture, DeathrattleRecord
from .model import DeathrattleRecipient, DeathrattleRecipientMetadataFilter, DeathrattleRepeatMatchSpec
from .deathrattles import activated_deathrattles
__all__ += ['DeathrattleCapture', 'DeathrattleRecord', 'activated_deathrattles']
__all__ += ['DeathrattleRecipient', 'DeathrattleRecipientMetadataFilter', 'DeathrattleRepeatMatchSpec']
from .model import DeathrattlePayloadPlan, DeathrattleRepeatSpec, DeathrattleRepeatPlan, DeathrattleRepeatContributor, DeathrattleBatch, DeathrattlePlayerContributor
from .deathrattle_repeats import GrantDeathrattleRepeatAura
__all__ += ['DeathrattleRepeatSpec','DeathrattleRepeatPlan','DeathrattleRepeatContributor','DeathrattleBatch','GrantDeathrattleRepeatAura','DeathrattlePlayerContributor']

__all__ += ['DeathrattlePayloadPlan']

from .end_turn_repeats import GrantEndTurnRepeatAura
__all__ += ['GrantEndTurnRepeatAura']

from .model import (CostQueryProfile, RepeatCostFilter, CostQuoteInput, CostContribution,
                    CostQuoteFact, HandPlayCostReceipt, SpellCostFacts, FirstPlayCostFact)
__all__ += ['CostQueryProfile', 'RepeatCostFilter', 'CostQuoteInput', 'CostContribution',
            'CostQuoteFact', 'HandPlayCostReceipt', 'SpellCostFacts', 'FirstPlayCostFact']
__all__ += __printed_permit_exports

from .hero_attack_history import (HeroAttackIdentity, HeroAttackDeclarationFact, HeroAttackDeliveryReceipt,
    HeroAttackReference, HeroAttackCombatFact, HeroAttackTerminalFact, HeroAttackRecord,
    HeroAttackQuery, hero_attack_count, hero_attacks)

from .model import TurnSchedule
from .joust import Joust, JoustCard, JoustResult, joust_result
__all__ += ['Joust', 'JoustCard', 'JoustResult', 'joust_result']
from .reveals import RevealCapturedHandCard
__all__ += ['RevealCapturedHandCard']
from .turn_scheduling import QueueTurns, SkipTurns
__all__ += ['TurnSchedule', 'QueueTurns', 'SkipTurns']

from .locations import LocationFaceReference, AdvanceLocationFace
__all__ += ['LocationFaceReference', 'AdvanceLocationFace']

from .resource_operations import SpendUpToResource, ResourceConsumptionResult, resource_result
__all__ += ['SpendUpToResource', 'ResourceConsumptionResult', 'resource_result']

from .hero_lethal_windows import HeroLethalReference, RecoverHero
__all__ += __stat_relation_exports

from .random_split_damage import RandomSplitDamage, SplitDamageScope, split_candidates
__all__ += ['RandomSplitDamage', 'SplitDamageScope', 'split_candidates']

from .model import (WeaponWearProfile,WeaponWearPredicate,WeaponWearSpec,PrintedWeaponWearDeclaration,
    WeaponWearInputs,WeaponWearPlan,WeaponWearReceipt)
from .weapon_wear import GrantWeaponWearPolicy
__all__ += ['WeaponWearProfile','WeaponWearPredicate','WeaponWearSpec','PrintedWeaponWearDeclaration',
    'WeaponWearInputs','WeaponWearPlan','WeaponWearReceipt','GrantWeaponWearPolicy']

__all__ += ['HealthLossFloorSpec', 'GrantHealthLossFloor', 'LossFloorPlan', 'LossFloorResult', 'loss_floor_result']

from .model import SummonQuantitySpec
from .summon_quantities import SummonCause,SummonEntryMaterial,SummonByCard,GrantSummonQuantity
__all__ += ['SummonQuantitySpec','SummonCause','SummonEntryMaterial','SummonByCard','GrantSummonQuantity']

from .pool_summons import PoolSummonBasis,PoolSummonEntryLink
__all__ += ['PoolSummonBasis','PoolSummonEntryLink']

from .ordered_summon_groups import OrderedGroupMember,OrderedSummonGroupSpec,GroupSummonEntryLink
from .ordered_group_batches import SummonOrderedGroup,FillBoardWithCard
__all__ += ['OrderedGroupMember','OrderedSummonGroupSpec','GroupSummonEntryLink','SummonOrderedGroup','FillBoardWithCard']

from .body_grants import BodyReference, GrantBattlecry, GrantCombo, RemoveGrantedBody, ConsumeGrantedBody
__all__ += ['BodyReference', 'GrantBattlecry', 'GrantCombo', 'RemoveGrantedBody', 'ConsumeGrantedBody']

from .target_predicates import TargetPredicateSpec
__all__ += ['TargetPredicateSpec']
from .player_target_inputs import PlayerTargetRuleSpec
__all__ += ['PlayerTargetRuleSpec']

from .body_conditions import BodyPlayReference, BodyPlayConditions, IfBodyCondition, body_play_conditions
__all__ += ['BodyPlayReference', 'BodyPlayConditions', 'IfBodyCondition', 'body_play_conditions']

from .body_targets import (BodyTargetProfile, BodyTargetContract, BodyTargetReference, BodyTargetDeclaration,
    body_target_contract, body_target_declarations, body_target_declaration)
__all__ += ['BodyTargetProfile', 'BodyTargetContract', 'BodyTargetReference', 'BodyTargetDeclaration',
    'body_target_contract', 'body_target_declarations', 'body_target_declaration']

from .body_target_preflight import (BodyTargetSelection, PaidBodyTargetRequest, PaidBodyTargetRequirement,
    PaidBodyTargetPlan, PaidBodyTargetSubmission, paid_body_target_plan, preflight_paid_body_targets,
    validate_paid_body_target_submission)
__all__ += ['BodyTargetSelection', 'PaidBodyTargetRequest', 'PaidBodyTargetRequirement', 'PaidBodyTargetPlan',
    'PaidBodyTargetSubmission', 'paid_body_target_plan', 'preflight_paid_body_targets', 'validate_paid_body_target_submission']

from .body_target_authority import (BodyTargetBinding, BodyTargetAuthority, AuthorizedPaidBodyTargetSubmission,
    body_target_authorities, body_target_authority, authorize_paid_body_targets, validate_authorized_paid_body_targets)
__all__ += ['BodyTargetBinding', 'BodyTargetAuthority', 'AuthorizedPaidBodyTargetSubmission',
    'body_target_authorities', 'body_target_authority', 'authorize_paid_body_targets', 'validate_authorized_paid_body_targets']

from .body_root_targets import (BodyRootTargetBinding, PaidBodyRootTargetRequirement, PaidBodyRootTargetPlan,
    PaidBodyRootTargetSubmission, paid_body_root_target_plan, preflight_paid_body_root_targets, validate_paid_body_root_target_submission)
__all__ += ['BodyRootTargetBinding', 'PaidBodyRootTargetRequirement', 'PaidBodyRootTargetPlan',
    'PaidBodyRootTargetSubmission', 'paid_body_root_target_plan', 'preflight_paid_body_root_targets', 'validate_paid_body_root_target_submission']
from .actions import PlayBodyTarget
from .paid_body_targets import play_with_body_targets

__all__ += ['PlayBodyTarget', 'play_with_body_targets']
from .indirect_body_targets import IndirectBattlecryBinding
__all__ += ['IndirectBattlecryBinding']
from .historical_body_targets import HistoricalBattlecryBinding
__all__ += ['HistoricalBattlecryBinding']
from .generated_body_targets import GeneratedWholeTargetBinding
__all__ += ['GeneratedWholeTargetBinding']
from .choose_branch_state import transfer_choose_branch, capture_power_choose_branch
__all__ += ['transfer_choose_branch', 'capture_power_choose_branch']
from .jade import JadeGolemFamily, SummonJadeGolem, jade_count
from .cthun import CthunProfile, GrowCthun, cthun_ritual_stats, cthun_attack_at_least
from .model import JadeGolemRecord
__all__ += ['JadeGolemFamily', 'SummonJadeGolem', 'JadeGolemRecord', 'jade_count']
from .nondeath_removal import RemoveFromGame
__all__ += ['RemoveFromGame']
from .mana_ranks import ManaRankFamily, rank_for_maximum
__all__ += ['ManaRankFamily', 'rank_for_maximum']
from .unidentified import UnidentifiedFamily
__all__ += ['UnidentifiedFamily']
from .hand_choice_followups import DiscoverForPlayFollowup
__all__ += ['DiscoverForPlayFollowup']
from .game_boards import BoardCardFamily, BoardCardForm
__all__ += ['BoardCardFamily', 'BoardCardForm']
from .tourists import TouristSpec
__all__ += ['TouristSpec']
from .sideboards import SideboardSpec, SideboardProfile, SideboardState, DiscoverSideboard
__all__ += ['SideboardSpec', 'SideboardProfile', 'SideboardState', 'DiscoverSideboard']
from .deck_size_rules import DeckSizeRule
from .void_decks import SendDeckToVoid, GetFromVoid, VoidCard
__all__ += ['DeckSizeRule']
__all__ += ['FabledSpec', 'expand_fabled_cards']
from .modular_decks import ModularProfile, ModularSelection, assemble_modular_card
__all__ += ['ModularProfile', 'ModularSelection', 'assemble_modular_card']
from .model import BoardMinionCostSpec, BoardMinionCostRow, BoardMinionCostFact
__all__ += ['BoardMinionCostSpec', 'BoardMinionCostRow', 'BoardMinionCostFact']
from .model import HandCountCostSpec, HandCountCostFact
__all__ += ['HandCountCostSpec', 'HandCountCostFact']
from .model import CoinHandCountCostSpec, CoinHandCountCostFact
__all__ += ['CoinHandCountCostSpec', 'CoinHandCountCostFact']
from .model import HeroMissingHealthCostSpec, HeroMissingHealthCostFact
__all__ += ['HeroMissingHealthCostSpec', 'HeroMissingHealthCostFact']
from .model import PlayerSpellCountCostSpec, PlayerSpellCountCostRow, PlayerSpellCountCostFact
__all__ += ['PlayerSpellCountCostSpec', 'PlayerSpellCountCostRow', 'PlayerSpellCountCostFact']
from .model import PlayerHeroPowerCountCostSpec, PlayerHeroPowerCountCostRow, PlayerHeroPowerCountCostFact
__all__ += ['PlayerHeroPowerCountCostSpec', 'PlayerHeroPowerCountCostRow', 'PlayerHeroPowerCountCostFact']
from .model import PlayerSpellManaCostSpec, PlayerSpellManaCostRow, PlayerSpellManaCostFact
__all__ += ['PlayerSpellManaCostSpec', 'PlayerSpellManaCostRow', 'PlayerSpellManaCostFact']
from .model import MinionDeathCostSpec, MinionDeathCostFact
__all__ += ['MinionDeathCostSpec', 'MinionDeathCostFact']
from .model import OverloadRecord, PlayerOverloadCostSpec, PlayerOverloadCostFact
from .overload_history import overloaded_crystals
__all__ += ['OverloadRecord', 'overloaded_crystals', 'PlayerOverloadCostSpec', 'PlayerOverloadCostFact']

from .model import HeroHealthChangeRecord
from .hero_health_history import health_change_count
__all__ += ['HeroHealthChangeRecord', 'health_change_count']
from .successful_summons import SuccessfulSummonRecord, summoned_minions, summon_count
__all__ += ['SuccessfulSummonRecord', 'summoned_minions', 'summon_count']
from .model import PlayerSummonCountCostSpec, PlayerSummonCountCostFact
__all__ += ['PlayerSummonCountCostSpec', 'PlayerSummonCountCostFact']
from .model import PlayerPlayedClassCostSpec, PlayerPlayedClassCostRow, PlayerPlayedClassCostFact
__all__ += ['PlayerPlayedClassCostSpec', 'PlayerPlayedClassCostRow', 'PlayerPlayedClassCostFact']
from .model import HeroHealthChangeCostSpec, HeroHealthChangeCostFact
__all__ += ['HeroHealthChangeCostSpec', 'HeroHealthChangeCostFact']
from .model import PlayerDrawCountCostSpec, PlayerDrawCountCostFact
__all__ += ['PlayerDrawCountCostSpec', 'PlayerDrawCountCostFact']

from .model import PlayerWeaponAttackCostSpec, PlayerWeaponAttackCostFact
__all__ += ['PlayerWeaponAttackCostSpec', 'PlayerWeaponAttackCostFact']

from .model import PlayerArmorCostSpec, PlayerArmorCostFact
__all__ += ['PlayerArmorCostSpec', 'PlayerArmorCostFact']

from .model import PlayerElementalStreakCostSpec, PlayerElementalStreakCostFact
from .player_elemental_streak_costs import consecutive_elemental_turn_count

from .model import CorpseSpendRecord
from .resources import corpse_spends, spent_corpses
__all__ += ['CorpseSpendRecord', 'corpse_spends', 'spent_corpses']

from .model import PlayerCorpseSpendCostSpec, PlayerCorpseSpendCostFact
__all__ += ['PlayerCorpseSpendCostSpec', 'PlayerCorpseSpendCostFact']

from .play_history import starting_deck_identity, played_outside_starting_deck
__all__ += ['starting_deck_identity', 'played_outside_starting_deck']

from .model import DamageRecord
from .damage_history import damage_records, hero_damage_taken, hero_power_damage, spell_damage_dealt
__all__ += ['DamageRecord', 'damage_records', 'hero_damage_taken', 'hero_power_damage', 'spell_damage_dealt']

from .model import HeroDamageTakenCostSpec, HeroDamageTakenCostFact
__all__ += ['HeroDamageTakenCostSpec', 'HeroDamageTakenCostFact']
from .model import CharacterAttackRecord, CharacterAttackCombatFact, CharacterAttackTerminalFact
from .character_attacks import character_attacks, character_attack_count
__all__ += ['CharacterAttackRecord', 'CharacterAttackCombatFact', 'CharacterAttackTerminalFact',
            'character_attacks', 'character_attack_count']
from .model import PlayerSpellDamageCostSpec, PlayerSpellDamageCostRow, PlayerSpellDamageCostFact
__all__ += ['PlayerSpellDamageCostSpec', 'PlayerSpellDamageCostRow', 'PlayerSpellDamageCostFact']
from .model import PlayerCharacterAttackCostSpec, PlayerCharacterAttackCostFact
__all__ += ['PlayerCharacterAttackCostSpec', 'PlayerCharacterAttackCostFact']

from .hand_deadlines import ScheduleHandRemoval
__all__ += ['ScheduleHandRemoval']

from .model import HeroPowerUseAuraSpec
__all__ += ['HeroPowerUseAuraSpec']

from .effects import LoseArmor
from .model import ArmorLossResult
from .resources import armor_loss_result
__all__ += ['LoseArmor','ArmorLossResult','armor_loss_result']
from .effects import SpendMana
from .model import ManaConsumptionRecord
from .resources import mana_consumption_result
__all__ += ['SpendMana','ManaConsumptionRecord','mana_consumption_result']
from .health_loss import SetHeroHealth
__all__ += ['SetHeroHealth']
from .effects import TransferWeapon
from .model import EquippedWeaponReference
__all__ += ['TransferWeapon','EquippedWeaponReference']

from .model import NativeSourceCondition
__all__ += ['NativeSourceCondition']
