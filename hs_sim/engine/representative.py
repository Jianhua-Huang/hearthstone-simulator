"""Explicit real-ID mechanism fixtures, not a complete official card implementation pack.

Only the small audited snapshot is read. Effects and targeting are handwritten;
tags/text never create behavior automatically. Pinned record hashes reject a
changed data version until this adapter is deliberately reviewed and versioned.
"""
from __future__ import annotations
from .summon_quantities import card_summon, SummonCause

from .model import CardAbilityCondition, CostAuraSpec
from types import MappingProxyType
from dataclasses import replace
from pathlib import Path
import json

from hs_sim.targets import TargetValidationError, canonical_digest, load_baseline
from .battlecry_modifiers import AddBattlecryRepeatModifier
from .combo_modifiers import AddComboRepeatModifier
from .spell_modifiers import AddSpellRepeatModifier
from .held_spells import satisfied as held_spell_condition
from .class_tags import classes_from_tags
from .card_creation import CardSpellRepeatGrant
from .card_spell_sources import POOL_ID as CARD_SPELL_POOL_ID, register_pool as register_card_spell_pool
from .model import (ComboRepeatSpec, TimedKeywordSpec, HeroPowerRepeatSpec, EndTurnSpec, EndTurnRepeatSpec,
                    EndTurnCandidateProfile, EndTurnProducerRequest, EndTurnSelector)
from .end_turn_producers import TriggerRandomEndTurnEffects
from .deck_conditions import CheckDeckCondition, DeckCondition
from .herald import Herald, instance_multiplier, herald_count, herald_multiplier
from .ordered_choices import ChooseInOrder
from .sacrifice import MinionReference, SacrificeAdjacent, BuffCapturedMinion, GrantCapturedKeyword
from .model import DeathrattleRepeatSpec, BattlecryRepeatSpec, DeckSacrificeSpec, KeywordAuraSpec, SpellRepeatSpec, HealthLossReplacementSpec, RewindSpec, RecipientMetadataFilter, RepeatMatchSpec
from .effects import (GrantDeathrattle, TriggerDeathrattles, RandomForceAttack, ReplaceHeroPower, Buff, Damage, DamageBatch, DoubleStats, Draw, DrawToHandLimit, EquipWeapon, Freeze, GainArmor,
                      GrantKeyword, Heal, ReturnToHand, SetStats, Silence, Summon, SwapStats,
                      AddCostModifier, GainTemporaryMana, Overload, SpendResource, HealBatch,
                      ChangeManaCrystals, RefreshMana, ChoiceOption, RequestChoice, ModifyCost, RandomDamage,
                      RandomDestroy, CopyMinion, InvokeBehavior, SplitDamage, AddToHand)
from .model import (AppendageSpec, ActivatedAbilitySpec, TriggerSpec, AuraSpec, CardClass, CardDefinition, CardMetadata, CardType, CostSpec, DamageKind, HealingKind,
                    HealthFlow, HealthLayer, HealthOp, HealthRule, HandActionSpec, Keyword, Resource,
                    Rarity, Runes, SpellSchool, StatReference, TargetMode, TargetSpec, Zone, CostScope, PaymentType)
from .registry import Registry, RuleContext, PlayerRuleContext
from .played_battlecries import (PlayedBattlecryQuery, RepeatPlayedBattlecry,
                                played_battlecry_candidates)
from .pools import DiscoverFromPool, GenerateFromPool, GenerationPolicy, PoolCard, PoolDefinition, PoolMember, PoolQuery, SummonFromCandidates, SummonFromPool
from .zones import CardReference, ChooseFromZone, CopyCard, DiscardMatching, DrawMatching, AddToDeck
from .dormancy import MakeDormant
from .bonus_effects import GrantRandomBonusEffects
from .model import QuestSpec, QuestStageSpec
from .quests import AdvanceQuest
from .model import PlayerEffectSpec
from .player_effects import AddPlayerEffect
from .model import SecretSpec, LimitedTriggerSpec, HandProgressSpec
from .hand_upgrades import BuffStoredCard
from .interrupts import CounterMinion, CounterSpell, SummonAttackTarget, SummonSpellTarget, attack_live
from .starships import LaunchStarshipEffect, RelaunchStarships, construction
from .dredge import Dredge
from .colossal import SummonStoredCard
from .summon_sources import CopyStoredMinion, DeathQuery, Resurrect
from .model import SummonStats
from .excavate import Excavate, ExcavationClass, ExcavationProfile, PLAYABLE_CLASSES, excavation_count
from .cross_zone import BuffMinionsInZones, TransformMinionsInZones, MinionScope, RandomBuffStoredMinion, TransformMinionFromPool
from .health_loss import StealHeroHealth
from .imbue import Imbue, ImbueClass, ImbueProfile, imbue_value
from .model import CastWhenDrawnSpec
from .pool_offers import ChooseFromPools, PoolOfferGroup

IMBUE_INVENTORY_HASH = 'ed7366423c2c3d929c891afbc060e4840c8d0c00ff4005456bde3d5cb24dc2fd'
COMBO_SOURCE_INVENTORY_HASH = 'e7bac0ae2341d94bd7abf4c2e9ef0f2457878aa395fd12162e1a9321be5b80d4'
COMBO_POOL_ID = 'representative.combo-minions'
MOON_POOL_ID = 'representative.moon-cards'
MOON_SAMPLE_IDS = ('BRM_004','TID_700','TSC_216','EX1_350','EX1_591','UNG_029','CS1_112','CS1_129','CS2_236','EX1_332')
PORTAL_POOL_ID = 'representative.emerald-dragons'
PORTAL_SAMPLE_IDS = ('BRM_004','NEW1_023','EDR_451','WW_434','EX1_563')
WIND_POOL_ID = 'representative.wind-minions'
WIND_SAMPLE_IDS = ('EX1_010','LOE_029','CS2_117','CS2_182','BOT_563','ULD_208','CS2_222','TTN_724')
BRONZE_POOL_ID = 'representative.bronze-minions'
BRONZE_SAMPLE_IDS = ('EDR_451','EX1_608','TID_099','EX1_134','CS2_182')
IMBUE_CLASS_POWERS = MappingProxyType({
    CardClass.DRUID:'EDR_847p', CardClass.HUNTER:'EDR_850p', CardClass.MAGE:'EDR_851p',
    CardClass.PALADIN:'EDR_445p', CardClass.PRIEST:'EDR_449p', CardClass.SHAMAN:'EDR_448p',
    CardClass.ROGUE:'END_000p', CardClass.DEATH_KNIGHT:'END_003p',
})

EXCAVATE_SHARED_SAMPLE_IDS = ('WW_001t18','WW_001t5','WW_001t17')
EXCAVATE_TITAN_POOL_ID = 'representative.excavate-titans'
EXCAVATE_TITAN_SAMPLE_IDS = ('TTN_903',)
EXCAVATE_EIGHT_POOL_ID = 'representative.excavate-eight-cost'
EXCAVATE_EIGHT_SAMPLE_IDS = ('TTN_724','TID_711','CATA_150')
EXCAVATE_TRANSFORM_POOL_ID = 'representative.excavate-transform'
EXCAVATE_TRANSFORM_SAMPLE_IDS = ('CS2_182','BOT_563','ULD_208','CS2_222','TTN_724')
EXCAVATE_CLASS_REWARDS = MappingProxyType({
    CardClass.DEATH_KNIGHT:'WW_001t26', CardClass.MAGE:'WW_001t24',
    CardClass.PALADIN:'DEEP_999t4', CardClass.ROGUE:'WW_001t23',
    CardClass.SHAMAN:'DEEP_999t5', CardClass.WARLOCK:'WW_001t25', CardClass.WARRIOR:'WW_001t27',
})
EXCAVATE_INVENTORY_HASH = '6173641a6ca49a7254c5837d3aa4ea3e51a51c8f8ac5213ce77ba5322e2d7f40'


# Deliberately enumerated experimental inventory, independent of implementation
# discovery and constructed legality. Never replace with registry.cards filtering.
GENERATION_SAMPLE_IDS = (
    'LOE_029', 'CS2_182', 'CS2_179', 'EX1_019', 'CS2_117', 'CS2_122',
    'CS2_029', 'CS2_024', 'CS2_007', 'CS1_112', 'CS2_106', 'EX1_238',
    'EX1_350', 'FP1_007t', 'GAME_005',
)
GENERATION_POOL_ID = 'representative.generation'
REWIND_POOL_ID = 'representative.rewind-cards'
REWIND_SAMPLE_IDS = ('TIME_000', 'TIME_EVENT_999')
HERALD_POOL_ID = 'representative.herald-generation'
HERALD_POOL_IDS = ('CS2_029', 'CS2_024', 'CS2_007', 'CS1_112', 'EX1_238', 'EX1_332',
                   'EX1_096', 'FP1_007', 'LOE_029', 'CS2_182', 'CS2_179', 'CATA_150')
DEATHWING_POOL_ID = 'representative.legendary-dragons'
DEATHWING_POOL_IDS = ('EX1_563', 'CATA_497')
ATTACK_COST_POOL_ID = 'representative.attack-cost-minions'
ATTACK_COST_POOL_IDS = ('EX1_010', 'EX1_096', 'CS2_117', 'CS2_182', 'CS2_179',
                        'BOT_563', 'ULD_208', 'AT_124', 'CS2_222', 'TID_711',
                        'CATA_150', 'EX1_563', 'CATA_726', 'OG_141')
# Audited character IDs, not a substring search (Spawn/Progeny and cosmetic
# heroes are not Deathwing cards). Unsupported family members stay unsupported.
DEATHWING_FAMILY_IDS = ('CATA_190h', 'NEW1_030', 'VAN_NEW1_030', 'OG_317',
                       'DRG_026', 'CORE_DRG_026', 'CS3_036', 'LEG_CS3_036')
TERRAN_LAUNCH_PIECES = ('SC_403a', 'SC_403b', 'SC_403c', 'SC_403d', 'SC_403f')


PACKAGE_LIMITATIONS = (
    "Experimental subset using local build 36.6.0.251952 data; no official timing certification.",
    "Construction metadata is limited to pinned records; no standard/wild legality or complete generation pool claim.",
    "General packet rules are provisional; special card exceptions and official ordering are not fully calibrated.",
)
def _bolner_repeat(context: RuleContext):
    """Experimental R-122 policy; freeze the first play at listener capture."""
    play = context.play
    if (play is None or not play.completed or play.interrupted or
            play.player_id != context.player_id or play.kind != CardType.MINION or
            not play.battlecries):
        return []
    # Trigger kind and historical source kind are separate. Countered plays are
    # included provisionally, as for Macaw; exact CN eligibility awaits M6.
    candidates = played_battlecry_candidates(context.state, context.player_id,
        PlayedBattlecryQuery(turn=play.turn, before_id=play.id + 1, countered='include'))
    if not candidates:
        return []
    return [RepeatPlayedBattlecry(context.player_id, context.source_id, candidates[0].id)]


CARD_LIMITATIONS = MappingProxyType({
    'RLK_541': 'R-150 necessary Arcane-school source composed with R-149 and the existing manual paid-hand repeat profile: casts=2, class_mode=any, accepted printed Arcane school. Friendly live active board source, full contributor set and max merging use inherited internal policies. Automatic/effect/draw/history casts are outside this partial adapter; source timing, eligibility, CN deployment and Standard/Wild legality remain uncalibrated.',
    'TIME_064': 'R-148 necessary mixed repeat carrier: four independent typed printed policies compose R-114/R-137/R-142/R-144. Physical hand Battlecries, friendly printed/granted minion/weapon/location Deathrattles, friendly Hero Power payloads and all classified friendly end-turn subjects use family-local max and independent acceptance windows. No own Battlecry/Deathrattle/end body, enchantment grant path or new generation pool is inferred. Broader source graphs, special policies, fixed end-turn producer rounds, CN timing and formal legality remain uncalibrated.',
    'CATA_472': 'R-147 necessary random friendly-minion end-turn producer using structural carrier presence and the public R-146 activation root. Active/live/unconsumed pool and all classified bodies of the selected minion are local policies; CN timing, printed-only/dormant/consumed scope and complete official producer graph remain uncalibrated.',
    'ICC_901': 'R-145 necessary printed end-turn set-count source composed with R-144. All classified friendly subjects, max merging and acceptance/fresh-extra windows are internal profiles; broader source coverage, CN timing and formal legality remain uncalibrated.',
    'CATA_480': 'R-145 necessary minion end-turn set-count source composed with R-144 and the existing player objective clock. Duration=3 owner-end ticks including the normal casting end is a local tags-based profile; raw @ is preserved. Generic duplicate-instance/capacity policies, Paladin Aura rules and CN timing remain uncalibrated.',
    'TOY_528': 'R-142: frozen friendly-board set-count plan repeats hero power effects; max merge, acceptance/extra execution windows and CN timing remain uncalibrated. More power uses and damage multipliers are separate policies.',
    'EX1_158t': 'Basic 2/2 Treant reached by Soul of the Forest. Partial representative support only; formal source pools and CN legality unverified.',
    'EX1_158': 'R-140 public GrantDeathrattle composition on active friendly minions. Granted Treant payloads share normal Summon capacity and original death-position handling. Exact acceptance/placement uncalibrated.',
    'RLK_912': 'R-140 self-scoped granted-only Deathrattle set-count, captured from live/frozen death abilities. Payload-wise max merge, origin semantics and lifecycle windows remain provisional; not CN calibrated.',
    'JAM_005': 'R-139 fixed active Deathrattle rounds composed with source repeat plans and Battlecry activation. Frozen payload/controller/count, round-ability-repeat ordering, fresh later rounds and any live friendly minion target are provisional. No CN calibration or complete-pool claim.',
    'AV_400': 'R-138 player Deathrattle set-count source on the existing objective clock. Three owner-end ticks, end reactions before expiry, minion/weapon/location scope and max merge are provisional. No CN calibration or complete-pool claim.',
    'FP1_031': 'R-137 allied minion Deathrattle set-count aura, captured natural/effect plans and independent repeat positions. Max merge, source/death window and per-ability ordering are provisional; no CN calibration or complete-pool claim.',
    'JAIL_123': 'R-135: explicitly incomplete experimental current-class five-plus spell pool. Discovered physical card gets an atomic repeat attachment. Possibly preloaded; CN release, legal pool and source policies unverified.',
    'CS2_028': 'R-135 necessary damage-batch/Freeze representative; targets captured per iteration. Exact damage/freeze/death ordering still requires CN calibration.',
    'CS2_032': 'R-135 necessary enemy damage-batch representative; each repetition reads the changed board. CN patch legality and timing unverified.',
    'EX1_279': 'R-135 necessary targeted spell representative; shared original target, one payment, repeat/terminal policy. CN patch legality and timing unverified.',

    'TSC_071': 'R-132 held-card accepted spell facts, then R-131 next hand-played spell repetition. Copy/reset and indirect activation policies remain provisional; CN timing and legality uncalibrated.',
    'BOT_411': 'R-131: next hand-played spell this global turn repeats; commitment consumes even if countered. Source windows, stacking, automatic casts and CN legality remain uncalibrated.',
    'EDR_464': 'R-131: next three hand-played spells repeat using independent player budget; source lifetime does not revoke it. CN timing, stacking and legality remain uncalibrated.',
    'TRL_092': 'Minion-only Battlecry/Combo max-count auras and one-turn printed Stealth. R-128/R-129/R-130 source, copy/control and timing policies remain CN-uncalibrated.',
    'GDB_873': 'R-130: pinned incomplete experimental Combo pool; Discover delivery precedes a source-independent one-use play policy. No formal pool or CN consumption/stacking certification.',
    'EX1_131': 'R-130: necessary summoning Combo representative; repeated bodies use shared summons and live board capacity. Official version legality and ordering remain uncalibrated.',
    'EX1_131t': 'R-130: pinned Defias token for summoning Combo composition; not independently collectible.',
    'GIL_820': 'Experimental R-126: 30 direct attempts, random subset/order, original exclusive history window, own behavior excluded; same-incarnation carrier, current controller and direct self-target exclusion. Nested windows/limits and CN rules uncalibrated.',
    'DEEP_020': 'Experimental starting-deck identity predicate and permanent Battlecry count policy. Requires a constructed origin; arbitrary scenarios fail explicitly. R-123 timing/identity and CN legality remain uncalibrated.',
    'SW_115': 'Experimental R-122: completed own Battlecry minion plays trigger once; first Battlecry play this turn includes weapons/heroes/countered plays. Captured ordinary listener, random targets/choices; not CN calibrated.',
    'DED_509': 'Experimental played-history policy: includes countered declarations, uses original exclusive play window for nested repeats and random targets/choices; R-121 not CN calibrated.',
    'TID_710': 'Physical deck Battlecry filtering; captured batch and current/printed identity use provisional R-119 semantics, not CN-calibrated.',
    'FP1_017': 'Both-player structural Battlecry cost aura. Current/printed identity and mixed source ordering are provisional R-118; not CN-calibrated.',
    'TSC_032': 'Private carrier counter choices; same-kind refresh and different-kind coexistence are explicit provisional R-117 semantics, not CN-verified. Copy/control preserve budget; knowledge receipts remain historical.',
    'TSC_032t': 'Choice-only private minion-counter descriptor.',
    'TSC_032t2': 'Choice-only private spell-counter descriptor.',
    'MAW_006': 'Pending minion counter after commit reactions and before board/magnetic/colossal entry; R-116 CN timing remains provisional. Okani uses the separate provisional R-117 carrier policy.',
    'ULD_291p': 'Player Battlecry count policy with global-turn expiry; R-115 consumption and composition await CN calibration. Quest acquisition is outside this adapter.',
    'LOOT_517': 'Player Battlecry count policy with global-turn expiry; R-115 consumption and composition await CN calibration. Quest acquisition is outside this adapter.',
    'LOE_077': 'Captured board-carried set-count policy for hand-play Battlecries; max combination and target/death/choice windows provisional R-114. Indirect/history sources are not implemented.',
    'OG_044': 'Shared pre-activation Choose One and explicit combined payload; R-112 timing/source policies await CN calibration.',
    'EX1_178': 'Shared pre-activation Choose One and explicit combined payload; R-112 timing/source policies await CN calibration.',
    'EX1_154': 'Shared pre-activation Choose One and explicit combined payload; R-112 timing/source policies await CN calibration.',
    'AT_082': 'Manual power completion via shared history predicate; listener capture, indirect sources and R-111 timing await CN calibration.',
    'AT_066': 'Manual power completion via shared history predicate; listener capture, indirect sources and R-111 timing await CN calibration.',
    'AV_143': 'Frozen death attribution and shared Honorable Kill predicate; first fatal/rescue/source, live deathrattle and resummon position policies await R-110 CN calibration.',
    'TRL_506': 'Shared captured health-result predicate; R-109 source, same-batch and death windows remain uncalibrated.',
    'AV_121': 'Shared captured health-result predicate; R-109 source, same-batch and death windows remain uncalibrated.',
    'AT_011': 'Shared captured health-result predicate; R-109 source, same-batch and death windows remain uncalibrated.',

    'EDR_449p': 'R-106: experimental grouped Priest offers and temporary delivery; default Priest power unadapted; exact affordability and offer windows provisional.',
    'HERO_09': 'R-106: experimental grouped Priest offers and temporary delivery; default Priest power unadapted; exact affordability and offer windows provisional.',

    'BRM_004': 'R-105: portal/draw/caster-growth experimental composition; five-member dragon pool incomplete; Paladin default Reinforce is bound to the existing adapter. Exact windows and base-one need calibration.',
    'EDR_445p': 'R-105: portal/draw/caster-growth experimental composition; five-member dragon pool incomplete; Paladin default Reinforce is bound to the existing adapter. Exact windows and base-one need calibration.',
    'EDR_445pt3': 'R-105: portal/draw/caster-growth experimental composition; five-member dragon pool incomplete; Paladin default Reinforce is bound to the existing adapter. Exact windows and base-one need calibration.',
    'HERO_04': 'Paladin class hero with existing Reinforce adapter now bound as its default; formal card pools and CN timing remain unverified.',
    'NEW1_023': 'R-105: portal/draw/caster-growth experimental composition; five-member dragon pool incomplete; Paladin default Reinforce is bound to the existing adapter. Exact windows and base-one need calibration.',

    'EDR_448p': 'R-104: random stored buff and directed transform experimental subset; default hero powers and complete pools remain unadapted; CN timing uncalibrated.',
    'EDR_850p': 'R-104: random stored buff and directed transform experimental subset; default hero powers and complete pools remain unadapted; CN timing uncalibrated.',
    'HERO_02': 'R-104: random stored buff and directed transform experimental subset; default hero powers and complete pools remain unadapted; CN timing uncalibrated.',
    'HERO_05': 'R-104: random stored buff and directed transform experimental subset; default hero powers and complete pools remain unadapted; CN timing uncalibrated.',

    'END_003p': 'R-103: guarded passive listeners, first matching play by frozen identity; trigger window, dormant/magnetic and indirect passive semantics await CN calibration.',
    'HERO_11': 'DK class hero for explicit mechanism scenarios; default Ghoul Charge is not adapted. Start with an explicit skill or install one via Imbue; no implicit active substitute.',
    'END_000p': 'R-102: Hero Power Rewind and retained results provisional; explicit incomplete experimental other-class minion pool. All eight declared Imbue powers have experimental adapters; additional slots remain gaps.',
    'EDR_519': 'R-101: indirect power activation cost/use, target and choice timing pending CN calibration; one Imbue power adapter remain missing.',
    'EDR_852': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'EDR_451': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'EDR_847p': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'EDR_851p': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'EDR_847pt2': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'EDR_851t': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',
    'HERO_06': 'Imbue prototype; R-100 growth, usage and token inheritance need CN calibration; all eight declared powers have experimental adapters; special sources and multiple slots remain gaps.',

    'WW_001t25': 'Maximum-health transfer prototype; R-099 amount cap, protection interaction and atomic window await CN calibration.',
    'DEEP_999t4': 'Cross-zone batch prototype; explicit incomplete transformation pool and R-098 costs/order await CN calibration.',
    'DEEP_999t5': 'Cross-zone batch prototype; explicit incomplete transformation pool and R-098 costs/order await CN calibration.',

    'WW_001t24': 'Explicit incomplete sample pool and specialized eligibility/Discover delivery; R-097 awaits CN calibration.',
    'WW_001t27': 'Explicit incomplete sample pool and specialized eligibility/Discover delivery; R-097 awaits CN calibration.',

    'WW_001t26': 'Experimental highest-cost resurrection and guarded follow-up; R-096 cost basis and entry timing await CN calibration.',
    'WW_001': 'Experimental Excavation representative only; incomplete shared pools and seven experimental class reward adapters remain explicit. R-095 awaits CN calibration.',
    'WW_001t18': 'Experimental Excavation representative only; incomplete shared pools and seven experimental class reward adapters remain explicit. R-095 awaits CN calibration.',
    'WW_001t5': 'Experimental Excavation representative only; incomplete shared pools and seven experimental class reward adapters remain explicit. R-095 awaits CN calibration.',
    'WW_001t17': 'Experimental Excavation representative only; incomplete shared pools and seven experimental class reward adapters remain explicit. R-095 awaits CN calibration.',
    'WW_001t23': 'Experimental Excavation representative only; incomplete shared pools and seven experimental class reward adapters remain explicit. R-095 awaits CN calibration.',

    'TID_700': 'Opponent Dredge and cost set; R-094 cost and reaction windows await CN calibration.',
    'TID_703': 'Selected snapshot reveal and spell damage batch; R-094 cost/window policies await CN calibration.',
    'TID_099': 'Selected physical one-local-Cost minion summon; full-board and source policies await CN calibration.',
    'TID_003': 'Selected stored Murloc copied as a 2/2 using normal entry expansion; R-094 copy/stat policy awaits CN calibration.',
    'END_036': 'Captured, non-stacking cumulative Rewind payloads; one play/cast/payment, normal enclosing death policy. R-093 source/timing/face semantics await CN calibration. Battlecry uses an explicit incomplete experimental class-Rewind pool.',
    'TIME_000': 'Rewind and -3 generated-minion cost use a frozen, incomplete experimental generation pool. R-091/092 payment, timing and current CN eligibility remain uncalibrated.',
    'TIME_EVENT_999': 'Discover from the explicit incomplete experimental spell pool; retry changes eligibility to current hero class, excluding Neutral. Exact CN choice/source policy awaits R-091/092.',
    'CATA_155': 'Own-turn damage, health payment and explicit loss become permanent max-health gain. Full CN timing, damage/lifesteal semantics, special health setters and secondary-tribe metadata pending R-082.',
    'CATA_154': 'Manual-play cross-class spells execute twice with a frozen quota and same target. One payment/play, deferred minion deaths, sticky Choose One and independent Discover. CN windows and auto-casts pending R-081.',
    'CATA_153': 'Current Attack is captured after appendage reactions, candidates are sampled with replacement before acquisition. Uses an explicit incomplete experimental pool; R-080 awaits CN calibration.',
    'CATA_151': 'Hero Windfury is a live non-stacking aura; source/control/death windows and interaction with attack opportunities await CN calibration (R-079).',
    'CATA_726': 'Live friendly Arms/Soldiers sacrifice replacement; provisional random enemy deck minion and no fallback on an empty pool. Deck destruction/reward windows and revelation await CN calibration (R-077/R-078).',
    'CATA_190h': 'Sequential distinct Cataclysms use frozen 1/2/4 quota and resolve reactions between branches (R-075); exact CN ordering/automatic-all policy uncalibrated. Enthrall uses an explicit two-card experimental pool, not official eligibility or probabilities.',
    'CATA_497': 'R-076 provisionally captures one plus prior Herald count and installs a permanent player-owned discount for reviewed Deathwing IDs; formula, scope and family aliases need CN calibration.',
    'SCH_182': 'Uses the frozen pre-payment spell cost quote; modified/alternative-cost semantics await CN calibration (R-058).',
    'tt_010': 'Spellbender uses a separate target replacement phase after counter checks; exact phase ordering and selection-predicate bypass remain provisional.',
    'EX1_287': 'Counterspell uses a resumable pre-resolution spell window; payment and cast events remain. Precise ordering awaits CN calibration.',
    'EX1_610': 'Explosive Trap uses the live attack target and current spell damage; chained secret timing remains provisional.',
    'EX1_611': 'Freezing Trap returns the current attacker to its original owner with +2 cost; full-hand burn and attack cancellation use shared lifecycle.',
    'EX1_130': 'Noble Sacrifice summons a returned physical Defender identity as the new opposing target; no trigger without board space.',
    'EX1_289': 'Ice Barrier reacts to an eligible live attack on the owning hero; special redirected/forced windows await calibration.',
    'EX1_294': 'Mirror Entity copies a surviving active played minion after its current play sequence; special copy policies await M5/M6.',
    'AV_344': 'Duplicate public objectives and triggered permanent buffs; three owner-end ticks and independent ongoing capacity remain provisional (R-047/R-048).',
    'BAR_306': 'Current local record deals 3 spell damage at next owner start. Exact sigil/dormancy/trigger order and source-routing exceptions remain uncalibrated.',
    'SW_450t4': 'Battlecry installs source-independent Spell Damage +3. The rest of this Mage questline is not implemented; full special-rule composition awaits M5/M6.',
    "UNG_029": "Deck spell candidates only, distinct card IDs with a frozen physical representative; current copy preserves local attachments. Complex copy/choice timing remains uncalibrated.",
    "ICC_091": "Copies the remaining hand in order through current-state CopyCard with random deck insertion; hand/deck-copy trigger timing remains uncalibrated.",
    "EX1_308": "Damage followed by random hand discard; special discard-card self abilities and official terminal timing remain uncalibrated.",
    "LOE_029": "Discover uses only the explicit representative-generation-v1 experimental pool. No complete official generation pool or timing certification.",
    "EX1_164": "Pre-play branch identity with shared target/payment validation and explicit mana-plus-draw combined payload; R-112 CN timing and cap exceptions remain uncalibrated.",
    "CS2_029": "Base 6 plus spell damage and packet rules; official replacement/multiplier edge ordering is uncalibrated.",
    "EX1_012": "Additive Spell Damage +1 and deathrattle draw; official edge timing remains uncalibrated.",
    "ULD_205": "Reborn uses the documented prototype death phases; official edge timing remains uncalibrated.",
    "ULD_208": "Reborn/deathrattle ordering follows prototype death phases, not an official calibration claim.",
    "CS1_129": "Snapshot remaining-health attack set; ongoing auras apply afterward, pending official calibration.",
    "CS2_236": "Adds current remaining health to maximum; damaged-health and aura interactions remain uncalibrated.",
    "EX1_059": "Snapshot stat swap with damage reset; aura reapplication follows the provisional stat layer.",
})
UNSUPPORTED_CARDS = MappingProxyType({"ULD_209": "The complete Discover pool and eligibility rules are not implemented; card is not registered."})
EXPECTED_CARD_HASHES = MappingProxyType({
    'RLK_541': '1dffa975913600e7435fd0172399c7686a044f403284dcf6013e07511cf5add1',
    'TIME_064': '3a188816fe1329124fa54e420b4a5161a0ca3fedb8194b107d18d7f7fbe5e00d',
    'CATA_472': '43df6f13cb9f2d5cc6c02d39906c1c93e44df959f484bbc872b8314a4163f2e9',
    'ICC_901': '070a2203d4bc37018eb158552c443b69698282fe69f0c7970d1d8c57efa45a6d',
    'CATA_480': '97a07ad8a9f0cb55fc0cef49192ef58b74e527bd0043c013996b402900cb5d15',
    'TOY_528': '5f0115d3b003195df90c5eac4f485018f87420a68b0eb77b2162787d7d2b6699',
    'EX1_158t': '7c9ea2b672a7774d72fa5a2adc332bec03e22ef9094b47edaac29f53f8e03f8f',
    'EX1_158': '4a6682506e8c06ac28d79206642df150331741f1c0a3722f2f8d318d84c53170',
    'RLK_912': 'bf74eb3c57778dc4edd00e8f3924dd3c3cdfefe47729b3a227b2404b8f39dbbe',
    'JAM_005': 'fd03458bbbe6573de278a00bc78d15031f97f9c58fafae5fe39bc3f4b37c5514',
    'AV_400': '56d9f6d79e814a077bf3fd799519030266b7a04d0d0cc7cd55afc71550793dbf',
    'FP1_031': 'bb65daa779c5e02c0a86f31745dde563674d0d784045655f484ced7e0061bcc5',
    'JAIL_123': 'd504d5e17cd2e80030eb21c62f0f18e63a1c428ef5b85f266423705adc8cae9f',
    'CS2_028': '4321f5801c1c9a77a8ab0b9eec7bb952e4465206cd4aac028969760c26f1afaa',
    'CS2_032': '3805324e371bff0fde39630ca9852979fe618710b24e21e0aabe4149467ead9a',
    'EX1_279': '41f4a738fd904ad79edee08ffb7a210041737af4a87fc704904b794b5264a417',

    'TSC_071': 'd9cf98f3cd69c482f56edb02352b2516276f179baf1ed0c28606524321e83c13',
    'BOT_411': '8d9c5cd92d75137a3af931469d79a4f2fbaa1df2af1d0297e5a7b57d9774b5e8',
    'EDR_464': 'ae6e811d364c0884f4671f2c0b6cad002459a274342e0137a5aac14e614861d0',
    'TRL_092': '4446380dfbe538fc927a1fca15e09c87b14640469f39fb4b4f66d39b8dc6ac1f',
    'GDB_873': '54492069b3c2fb00c4dc599f4f63125103c49b69e0913b70ef098c26a7626a07',
    'EX1_131': 'b90dd6c999365e98d7ce239c5c15b38983e6db19833acaca1e625331dcd1aa01',
    'EX1_131t': 'ee2c26dab15bf4f743a7bb39fd79a89569806b1c359731d0cb338c1c1993fdcd',
    'GIL_820': '1c8c3de287e3082e0f3575c9b750d39fd55d4e85fe646bba42ab52c7457c8461',
    'DEEP_020': '76ea93274d37fa6ac3af7680fbd0007cbfb38379044f4263ac6f1641ed31179c',
    'SW_115': '395f19a5b63418c58253c3781135718ef1a1cb494b8fe23667a9e5d0844dc185',
    'DED_509': '25b730077d1d8a2a0164f6d1b6c3556fac264ae36e6c1ce3007d794ecca8a8f0',
    'TID_710': '7d7aad5487a0ce934359e8531b5c8167f2293fcf8cfa41088c418b95195fdbcf',
    'FP1_017': 'c7dba0821e9bdea0d85e7ab59a3f3e0c8ede55b23eff1205f25b1a9948d254e1',
    'TSC_032': 'ead32717c641504dc5df920aa7131ee7b86c8681ed3e247944efdc0557e1810d',
    'TSC_032t': 'e89f2785076e1d31a2a7cbb66f23b1b8200f785fe3d5f828c09c42f9de725160',
    'TSC_032t2': 'f5a4ecccbe3a7d89b23cea927f25ef78554b9cfaa205190fc955f1306ccceb15',

    'MAW_006': 'fe87658786b3c3b17381860758954bdef5b04451dc278c8e865f6ae4f1fd8720',
    'ULD_291p': '40a4be2d77a9f9fca07025a2fc96256d765b695c8a610a21b0fa54a74111c0e5',
    'LOOT_517': '6b9dac9a0dae080908d92d5cf6cec83da857292a5b886d19cfac338695fed066',
    'LOE_077': 'f4c7eb19aaadea3b37eb11811d6d3c5cef281d06786dbaf8c21ff0751b6e293a',
    'OG_044': 'e4516f5a425e37f944201eb42a93b003bb80b1833bfe318cbeeedd79c0b789e2',
    'EX1_178': '53a9b4c674b26cade45e018d9594314a8edbbf750187bc6b5dfe9e5c892e6943',
    'EX1_154': 'e7c24968e0127dcf972f25f131426fe4cb3958e5a6112a9e05fcf7e1eaa76c12',
    'AT_082': '2a9b68dc487788b14f9a7ce425879cb3a01f68397a0274dd7839442092d729ae',
    'AT_066': '6c79fd88969f654d99a9b885240ebfeeb01b5a85d0e21befde20fc8d4ccf785b',
    'AV_143': '5994d83cf7496481bad591c121ce91b28be3db60d5c36ee74f78cac5d5fb83b7',
    'TRL_506': 'ca3e616bfc7389a4e6bfddc7cdb6364a4218c54d2434efe01127f5ac1ea1b110',
    'AV_121': '22719b713bec8fb52d30854328eb3fa594c0636920071266c0f62903b6fed237',
    'AT_011': '79cd2543e5eb716c5ead69dc38453e3e7e405183e0947435da6b160e443ac5e5',

    'EDR_449p': 'ff575e5092a13bbc5c3ecaefefa541c8eed0b94c673e677b426600850a1d46fa',
    'HERO_09': 'cbbf3ff720a1b5b451940424bc7e2d39899fb1f4df6a00f21af5809efbab526e',
    'BRM_004': 'ad063b29b3b600f72a3b3a9949225f2773d46098cb3268367164a2aca74513ee',
    'EDR_445p': 'd34d3daa19789471ae3bab2dea91423af4dabb214165017dfdc34b84d19b3d9c',
    'EDR_445pt3': 'a6c6f87cfe029cc02c2d99ef3874d936ac47266f1d56839fa3331972a483f700',
    'HERO_04': '686ec283eee8757631af6eed4a0b0f2414a031722dfc2efea62b0176333e60cd',
    'NEW1_023': '7f319abfe66e78aead31390b8e8f2c1f5c79388e72f87bb9ee53a2b088a4559c',
    'EDR_448p': '78708d1e8004fb7f12719c506451c0da6fe07d836cb51c61c1f91933db6bf070',
    'EDR_850p': 'd356092ac4f73be0291255cc65082f27aeedd030131610aa3989b68d6143eea1',
    'HERO_02': '35ec0dbfbf485477276343cad882ce0278f7c1e51adf4a728f5b3e9f1da6732a',
    'HERO_05': '5919e0e666bf758feed32dbcda2c012f343740b314cf0992a07593ea762257fa',
    'END_003p': 'e8caa42eecb73f5e64d05f237d154ad025ecbbf37b86130e933bf9845c33ac4a',
    'HERO_11': '56e1c595e773001b0520a2b039d43e01ca54ba489c24afde036d08d4188307cc',
    'END_000p': '05dd9af817e227ed95d9b6202dd805de275b1ef572b39edd52bef07ba1ba103f',
    'EDR_519': '439b400bddd30c5e8a24ca39554c1f1dce317792e4be76aa292ab78f58b75f85',
    'EDR_852': '07a8afa28864d0cc052b4639aabe4f2483fd9063a032381771801d279fe99283',
    'EDR_451': '07222339cfb7287d2a1b71b7926fe764d55d25d16f199ae45d490a33c7d2f09c',
    'EDR_847p': 'cbb58d3801da572980a42c16d210b21829b9771d455ec12e5552cf098daf7b53',
    'EDR_851p': '31c11cfb2aeb866a8cdc3712716df7b89511fe57e99f4647fe6510db6a720725',
    'EDR_847pt2': '60cd7db8127eb2c3fa08b9a37874b658fae093f6351707a84a758c068a882ab6',
    'EDR_851t': 'd63abece2e44a0c7c4f7e18eb9e357ab2748753f284b209cefa63e7e01311a68',
    'HERO_06': '266d08b6ed374f2163f600be416e0a1b69bd05feac6b91d02cb5e22b63f49151',
    'WW_001t25': '8b5acca8297d0a351fa389b01afedf52617b9bf9f4bc5b7930e4a99d8093be46',
    'DEEP_999t4': '4667aec1d285f28f5dca451993137de29a204d2737ae09bcb80d0f87cf5e99be',
    'DEEP_999t5': '77ad7181f819a6c3e95ddd16a5d683e1249aaa7ad41370b63742b9b9ae0b34bb',
    'WW_001t24': 'a3c8b2967cbd58e6fcf81ce38a8134193c11770812fab143e6efc4081d38c1e5',
    'WW_001t27': '4a8554ed9f1ba6b4a9b9476946ea26e69eaa9deecbc435e37a40f9be9f85d7d4',
    'WW_001t26': 'e4f8b9f1f9d54915fc370944c3f45bdbd09804846c1159a07be058e7e104749b',
    'HERO_03': 'c5c3d5882c31e3f9414f06618a485b2e21fa4928316cd218a7035cf8380aa88e',
    'WW_001': '89133253851a3e1ef75d613b1e7e3e644ff9cc0cc540fa80411227006d3be386',
    'WW_001t18': 'c1fc36c306ad8a29b4d2c1d3029be53371b50eb8f2eb0d32b7c874dc242f9020',
    'WW_001t5': '1751a84faa5d699de3b21f9f5217b732cc81d7e54d0f4518c9d0072aab1529f8',
    'WW_001t17': 'ad86dd09b0cd6610a745feb05168ae95b23cffb454ee855e03355b7ac70c4452',
    'WW_001t23': '75870a875cd23d0c4618e881468ccd8912ae1e51fdddd118a744ebb276d56d7c',
    'TID_700': '19b48c0dc862380b709b6ebea4ae274c777142955a472cfe45ae690a570899a0',
    'TID_703': '356fc46606f80a03780746efa494fa07b8ab8d24816c7562e5b263b77350995f',
    'TID_099': '4b21c1a4e787d2bf3124d2cacb391bc451e0c6c8bd2bf67068f4eac7970c77d0',
    'TID_003': '5f513203fb561d5149858f1349101ee1ed7a984a525186ee5e6c6e6c62288655',
    'END_036': '7be58404521504dbb93766663a39bc04f3a0e68815739196d7cc41631b5e0854',
    'TIME_000': '5419d4bb6798d83235b0ba0d570026dffcec19a7f043f4c0c6289fce27f01a01',
    'TIME_EVENT_999': 'd448816f4f947d1fc85d23533ea9cb70dc3e72a76e2a11055a6f5f19d9281094',
    'CATA_155': 'f92fe5f9328057ad4de23c4afea3ee7049e385332adc65dcaf8a6ecb0bcda4d6',
    'CATA_154': 'd8c4696973fd2b7b8a9e8284bd0078c46810d9989f07bf23c2cff26ac58c47f0',
    'CATA_153': 'db9415cf0420b9ee0052b592fed51941af7e756e6754f40cd81b4f8eef427b2c',
    'OG_141': 'd69377eb0782a21e0ee162f269ed1ccdb14989d680cea71ef97d2d60fc8bbea6',

    'CATA_151': '211616c2ae83e3dff5899cb88f9aace06be0ad2e56e3b9d35427e30d495c1bd1',
    'CATA_726': '76706edb367120e826750b8ad60d3961dec8b14c96d03899902b6dddd31841a0',
    'CATA_190h': 'b6bd2272e16dcfca8bd378d5a448502561ee292f9602c91ab4c9b2d120bfd680',
    'CATA_190p': 'b5e6c03e64c858e1970a09e290462a4ed6ca2700f045878128c886f4651559c7',
    'CATA_190t10': '33ad72b3de55b95ed4c65f4df18ca718b2b476aba8ce138750c92256a6a8a518',
    'CATA_190t11': '00b145c571c55cf8aff23a131129646ea0e95139ef3ff7fefafb4458dec162da',
    'CATA_190t12': '3a37e5e22b99f5e1c55ed4da1b13920a0899890f9de2ef7a1f7ffe9cdda6312d',
    'CATA_190t13': '08a0aaff932997eb3d5d29c39eb89f6a7f34bfdeb08a2ffd669b8df16e614761',
    'CATA_190t14': 'fe54933762fb34ef8d2f7b464b9409835daec8359b8299d86abdadefa4527880',
    'CATA_497': '23749591526c15e05dba1c0b205689b70dc17fef24af97a52c5dbc70f19d19d5',
    'EX1_563': '8b867fb6afef48eb966084904720a770ee07d7403c211fb54c8072eaca6c47ab',

    'CATA_725': '2b13bb0360c43d64587e788e8df440cf6ab295f2ff44763ab521054ea4e4bd86',
    'CATA_725t': '7bcc61fd133da6de9d157ba3d8cfebe140d9b78c33f220c4be91ed2dbb88dc1a',
    'CATA_726t': 'b03e898519966d860f39e978acdca5727094c0eee0e24899bf39f05283f3cb20',
    'CATA_726t1': '3aae63f974cf48ed840a8f22bbe332e817bec6bca07d8a231c64376a18b4cb67',

    'CATA_565': '33d842d20ecba4b569df06e4dc3f0dfae79eb49d5d33b51fe4f1c2d819b26ff5',
    'CATA_565t': '88367afba26f678779721e976deabb974f6c7549febc37c9dc71c7bc7059c190',
    'CATA_153t': 'f4bbd1d20009872b49dd647109d2e949469f8add055b1b87931342bd0de81f37',
    'CATA_153t1': '7e421bc37e08d88c42b9701f1e2f422da14aa3398dace7ccb58f510e10778f5c',
    'CATA_158': 'f446c809d0377245a5c15688ade21786e7d947ec89fb8659926835cf1279d58d',
    'CATA_158t': 'f155d8495473de880266cf1cd3d7af2085dbb9a474f96da0e07c9e7bc001bd12',
    'CATA_154t': 'fee8ac74fb54ff1857a241cc24b9b548f60fdc848486a2b1cf8604fb62b22842',
    'CATA_154t1': 'c8e62c480afd72bc821a9646b653e1e5fd75fd654bdea4d28f048c9766665257',
    'CATA_780': '83b37c3b57e9ff11b550489f53397780bb0d0abd42be9ebaa69b10e335f734bf',
    'CATA_780t': '9d9707885b9a222ab0ece2fdc1fa4b6090405b44b671b2dbf11be8fca3e5d65e',
    'CATA_155t': '9f1127dcbf5927f72916f9768913e2bbe1ecebbb83f6d7e24e6837af1cb51976',
    'CATA_155t1': '672c92b3a7218dbdfc4ac522af2f4a6274a048ba58efa23254424cbddd86025f',

    'CATA_150': '2cc6aebea46f45e719ab4aa6035d475c702721fe66e6606ccf3575dc4af02b52',
    'CATA_150t': '20ef05f30daa3fe30bc55b9d33dda0174a0a4200b4673e3404e83c09f18a0a93',
    'CATA_150t1': '9e95582a204e8869a5ae7a655e5b9fa392b8cf14ad8bbdb5f61b9c9e04a838a9',
    'CATA_580t': '57dd1456c1ed8d8ebdcb87276b62417abbf87622092af38ef33935d39e42b038',
    'CATA_160': '4a6a3d8aad5c9f8e9f1ccc27f063931b6d9027e8198f651dbd5d70ab41a53bec',
    'CATA_580': '0850b26e2880c4955287b158ffd379e822c288620ec82acaee7f4495123b1eba',
    'CATA_722': '41534e26ec35087b18a92ee08bc9db3919595582e85032ee3b7644861672d861',
    'CATA_525': '05d2a66d81193c0e46306cbc9c269fa6ab32ddc41c64132a5234a6d19fd7ebba',
    'CATA_525t': '4b2558af44953f6eea945e5a537712387044ddc866b36dbded5d2207dedff1ce',
    'CATA_530': 'ca9b164708f95247bcb51d8e8ee86fd79de7fa44d4c588522a6ab2cab27c2842',
    'CATA_151t': '4f892cd5c6f34ffd47646fadf267591aa35f72a50999252adf09c956641b377c',
    'CATA_151t1': '089acf79fd5f2f04b64206b69d057dccd5c2d7dd75a18870d35b7937f4bf6461',

    'TSC_216': '5dd4fcd49a8155d79899b0fe3696cab2b2be524079dc4b29473405447f2d6884',
    'TSC_216t': 'a8a7b7612322e49873dbc8a6fbf0c887f8b837f4f2a2c4ef9714126b02451039',
    'TSC_639': '70a8d62ac76854ac9c4e840aac436f346e1fa4fe3fb218990819ecc2392bc84e',
    'TSC_639t': '7bfced04ff8a0282f3239383fe9904c083c7accc9b119ceb06f9084838ab918a',
    'TSC_639t2': 'eaa8dba192efd717dc6a6702fdb22232ffa1db2ea226705d3a061ba88315d561',
    'TSC_639t3': '6df817aa3f02f3a4cde60c352d360120226920a7689590117d1bc8c62ae24c11',
    'TID_711': 'fe9bbefe5cf212670421835e843a92e13c047941a5630fb2e660e2e56046dc54',
    'TID_711t': 'eaee382264b774165d0c6c2a5c00c48f7d476b134fe5eae62b8dba6767517e99',
    'TID_711t2': '2a07adb81bd0398c13df6beaf2a4350b2d78fa9857d3fa070d0b98deebfb9807',
    'TID_711t3': 'b9b50e87539b787b262d648c16563e4f48faa70be0b104ce13379a4de11ff072',
    'TID_711t4': '43ecdcdee9e51bf366bc6c8f5231fdcdcc639700a0b205abe7dde579c720af3f',
    'TID_711t5': 'b69c55d138f54e91e5b57e640ccbddffc57b9c38806140e8cd705f88176f99f3',
    'TID_711t6': '0e108fb0b320c4f14ddd60caaf1598a6d88e143137694bf26f906b54184689dc',

    'BOT_563': '1f751ade54a81c81f52bff461dcee66eb3de4a125624a674e56f28db8c66147a',
    'BOT_911': '75234a19b9106964d33bf142e8f72716bbb943eb0e9e1943824b7e85cee33100',
    'BOT_035': 'd7c5283fcd69f752e8cf1d69cd9f7fde9fde3e5506035cf503989afad1c4bd05',
    'BOT_548': 'e66f3479af44d54b4b0cb63344cfc8011b0f89fa6d8b8efe6383836ca8757431',
    'BOT_251': 'edecda2e0f6e71f67ef24de2872c2b138cf71b29591963195cfa1aede8571d80',
    'BOT_107': '65cc268029126405988b6157e3901446967bb20b1b10b81d4f99472aa7d1a19b',
    'DEEP_015': '3ac6693136128931ff285dd6a692428c6709a4966a1518aabb77839255e3464e',
    'TTN_087': '4d1abf020cc178049d73b5c65b666aae8065aab43660c4335ecf7351733a2f8d',

    'ETC_325': '45830571beaf4357e7d8849cf4d6214a8991777fc2001a1084dcd227ed8aacc9',
    'JAM_017': 'aa1168c2df9ac7df472f888118b8463339457b7b08842c26df09cf094f508346',
    'RLK_843': '551e31bbbf70b048c9637c979bf1a850539e406916f33fdd4bf6eced4abe6f30',
    'RLK_518': '5c86c3be790519985ba5a3f929ece83f496adb66562cfb06d739a080e6bfacaf',
    'WW_434': 'f7ca67d2e6b0f1070c03e55b0a8a9f01d45d0d1e176893160619ddafcf4a1a2a',
    'WW_823': 'dda79ddc184587754bb5653ce664e67a76c6d37a83beb9ee28bc0022888ec4fa',

    'DMF_073': 'c76d2a8687fee3543b2c83062c5baecf599f122a048cb5161b6dc44f7f066e8d',
    'DMF_073t': '9a9a2041291d8343467e6372487f3f8f46cc6001e46f7ecd608938b214679c3b',
    'DMF_124': '8cd994009f77e0afdb400c719523b12b8dd494a495854952b32a0826e1be3460',
    'DMF_124t': '1e0a88022affb400b438dc031e6a7d96166c32273a3e4e8d9e3acdbe1002f8ef',
    'DMF_248': '5b4decac0ca5b7b722e04efacce13708955cce9d131e70820350cd925f1463df',
    'DMF_248t': '1c131273ce7a100c057324c2d3a677bb5f98fd7dc93055d9c32f4da80306cfd5',
    'REV_019': '88813c9b95c19170f29eaec5ba397e53888516b31dc00b5420579af2f1c7020b',
    'REV_019t': 'b75745b46a049c020301e6d281982092a33712be0bfeb9c18f8c965d6337faee',
    'REV_601': '86938fed6fff9aab1e841ff294232111f456bbecba62641f77b16ee57512d5a5',
    'REV_601t': '9ce75a5ee67a0c27473a457366c9f13fc1a9ddb5fb71050b52b6977a246f3b44',
    'REV_956': 'e7a21d642f66143adde6d02755c747db89a8a8e40a6fbaf40dc2ce6b74312b47',
    'REV_956t': 'fd1ce5649c941af3d4d58caea9780132496e96b20b2687cbb1926bd70c27427f',
    'REV_957': '8d6ea254bb7b68afe18ce0dcc12444725764ba25d8e3bd7e43f37e9472f6449c',
    'REV_957t': '72ee25d1b1e09893d3dd135f32ac91646e0c83ec9ea3a978b90046bc02b277ed',

    'SCH_231': '1d211b9ac123b59c2f5bc486023e9fd51bca00ddc6c3c1db26f2f56e349d6fbd',
    'SCH_242': '2e75e4bcadd7c790e611060e3871aabae4b71b0398d68075dfb876d967ea1882',
    'SCH_248': '2e516f81a0e845435b9713700b1b4457851ec9ad94e4fc5b362bc81ea37d8372',
    'SCH_182': '5dae8507bcde88af596c035938769c3b3e766c52a264b5991b2714567376bd9b',
    'BAR_024': '2358ae1e821e14f4a5fef2c7caf59677407649bbd1f15892dfe0696bced4b63a',
    'BAR_025': '5ed21faa9fec544cfe6aff5c120403c7f30e8e20348ef2f0391e3dac5fbd5f71',
    'BAR_021': '2a50027902f776a998872991c89bf9555b23cd8adb446b566795e1c5cef4d834',
    'BAR_078': '0f9c81f36e926807070702280d631252598b84f1c148b9db8d208cc55fab7d52',

    'EX1_124': '668921a0c648be29e14311dc29da9e1daaecf72124978e770fd7f1d5d2c88e50',
    'EX1_134': '8719f46b52724cab6a431254763ce36f00646c6f895e1fa75cc3034fa860af08',
    'EX1_613': '4225d4e837abf5d377a9035dba130d6e705a0778be18cf3f8d77482125ad34d3',
    'BT_480': '785bed4291668340b9ff778a4b8c3addb45498b93b388b8668770d2bdea83d51',
    'BT_490': '9183eee6cc507f9132151aded7f7ea63c13f6bd5d259cb7feef2024dbafd63e0',
    'BT_491': 'cd6d293ee874a6c4e0bd4a5ac834f569769d92ce482132183d4b9b50e86089b4',

    'tt_010': 'c1d5fc7f9cee500fc367caf15d7758a42dff008a05c803c9bb5e1af79a5ccf2f',
    'tt_010a': '7a37414cd012279ec6884099e1727f0b71c5be85344f4e9517f34b18dc9bccb9',

    'EX1_287': '9a8e2534e99589ab400acca8a3f7742e2fd9a74d7a97de33e59cd2841d5d4ffe',
    'EX1_610': '1714b1f9d51c5a188b757e0f722c1393badea5d18010025ea25fd79fafdeb113',
    'EX1_611': '9ee16b879aa1125b38229d3f2130064275c60dea2c65aa06541e10d26b35dc90',
    'EX1_130': '6cbd8bc635dda9461fb7e25a0132f93c883ce251fbb04daf0bc33a9c16a894d4',
    'EX1_130a': 'e5e557e5448f885085d71980c7210b79071874d9eecf075e73b7e4f8d8d5fbfd',
    'EX1_289': 'bcedc371766ea84b7d85b2d47d66a6e6cf0772c947d2b7591552dbf88caa4648',
    'EX1_294': '76fbec132025f5f0f5565efea56a4989389493c58c7751a719b9e98fb5a34bcd',

    'AV_344': 'fd9c43728cd95f2cef7fadcab33d07ca0e3ad0c028e7fd8e71c47c7785b65b88',
    'BAR_306': '35969b481e0cfc955ff040151a7ed72b91bfdd9811384f773bfae7e6281ed226',
    'SW_450t4': '6411bfd4d81362734d43bcd9f128dedf006b5b59ae8dc548dcd791823800a2f3',

    'ULD_155': '6bffdda42d0f51d4d4cacb470ed83bba709dd221642c465e5f4f85c3ec6c735d',
    'ULD_155p': 'd0223bbeb2a6fac9002e88cf86e6286d9f43ab7d51c6d0e0d447f20023f2adf9',
    'SW_428': '3b03bd3fe357c70cb5b3a2219095fbe3bf5547f3912bc1ca0f75454c64a95eeb',
    'SW_428t': '29e3e3707ad815f8a6ce593ad6a7590ee0469f993d5e4b904467cef9a4d46426',
    'SW_428t2': '10a92f8ae43fafb3c20494c06cef32985c5d5a9964758be4ad054617d889c49b',
    'SW_428t4': '90fd0f3c12f221a61d94879efea3c6c26b89b24698fc6923ba970d3463dcda0a',
    'DRG_008': '7387abf4984736cd77e953d047739fddb2a13cc6225c2e5b4a57105458cedb36',

    'TTN_903': '8fc944c94419b03290df232e673cfdaaa41f54aaa3e44c1980569d8535145579',
    'TTN_903t': '1bef0d43efada55b7f479d15b422d3fb13b40df2605a69f4c1f82928f0c466f4',
    'TTN_903t2': '3f306991c4a4ef8600717fb799a1768a80d0e8d4aed8afb3843b74b94e5c66de',
    'TTN_903t3': '5502e2913e6365fcab4fc4ac4fe8d04120f99b655266baeee147b394df12fb1e',
    'TTN_903t4': '4f621ccea38cf8e4dbd4b86051d3d8ccfd1829475850c9246c6323a094845f15',

    'BT_004': 'b4ddf4ea50adac688a95f8997796575b261dcee1de148cd274bd376c2766408c',
    'BT_156': '0a4f77da626c3ab2f0c54a971bb458f9bc8daf6781f9d4dd0a8d588975f7ca24',
    'BT_737': 'f5cfd17e1e04e759c9c7003b90bf78e1cebd103cb9d7af43d5032d1bdfde9aa6',
    'TSC_647': 'e7cfdafce7eae5ea1f985a8e0eaca8fc83f476d0febb6131dd5ed307ef9c62a1',

    'SC_400': 'd28f22a5e294c2e3b09ddbc1391c8575c660583b7ef0f9600888b4145f879602',
    'SC_400p': '2406578f407568782902972ed05dc7a18df04e1c59f7c6c667a64f4d23fc2313',
    'SC_403': '6ad33d818e5109a1d4a7322ddc19aed4e27ecb26ead3f47cef274e7f12362baf',
    'CORE_REV_990': '8bda7b70ff39b83637d3a6f95d35c811642173a596de53fb0c4b1914f64cb815',
    'SC_403c': '34974caec81fb91178223b5d7f58f8c9cb3433bb58190ed4302a930705a6535a',
    'SC_410': '52934dee4bc3279d407eb6aea2e023a27d5e0e4d2ec147387d9b10f7d0b08d1e',
    'GDB_120': '450a10f2ee19075b4d4f90df7c6feb5885cba3b3dca3782b0deb35345dd44e1f',
    'GDB_100a': '402aab5608e1056b834c8b0c1bc9fdcdc8ec1b371ec5501a58a1b70f876695a3',
    'GDB_100b': '4b4ddced06c2a655b3b94b0c4b62cb64a47f02bf21f37a7b05d8182776cba604',
    'GDB_100c': 'c3337843f0400d12dfac62d9a03bc22e0983ead9e1400ae34ac77bc2abed3217',
    'SC_401': 'a4fe086331cdd46f25a43026538f1788ec14c7191c7344df42ddd5bf928a858a',
    'SC_403a': '09afffa8ba05873da8a23322494e05cd77b84c0f7280e585a17e95a562343bdc',
    'SC_403b': '8171195931026abd4982d26c8027ef6a562419aef81aeb943e65319cecdf6676',
    'SC_403d': 'b9af024db8031dbea7c745b06aaa3b4a0102b5654503962c2b1e25fcaecaf4f6',
    'SC_403f': '3d92db139a6838438c0eaad5145468d1a47b1bed73e3542d5dc81457b8170152',
    'SC_403t': '54d2d75cd225acfbf2c96e2b0daebb4d9ff10eabb0bbe52a54902ed5d358343a',
    'SC_404': '5db623661f4e05aca1ff4543c85db77527336158317e08b9e04041602a4dce58',
    'SC_405': '0dfad865b5125d3295149e6a720f35fe191736f85685f4a43c9de29f1bd556db',
    'SC_406': '9cd8688b39375d7b5c19da8d4e20161bb6ec7f5fd1befcdfcaf8692f92c4431b',
    'SC_407': 'c9f2a63cd1eaf24280b3074cfc9f875026cb88cefa5e6ea21b742e53281c803d',
    'SC_409': '3e3598d705c17cbd188b679e953c8cb490b0192a26eb87024117a82acae636e2',
    'SC_411': '8169c5fd4bb2b1aa71556a4728ed7bf8165b0085d24367b10c166a867d4ded29',
    'GDB_466': '70a740655397a65822c1a73fb48a68d8812fa33f8146be45d80eda72220daec0',
    'SC_999t': '2bfa58a946e46eefd0cb2e5c649309c93915e4b21ec8789639d0203f0c4d10bf',
    'GDB_100': 'ea41604e270b88a8367f38b806af88fb73e776ba16b6d243282f3a44a6342197',
    'GDB_101': '49d675001c87c57c62825e9a8a39c7847290fdda6c6df90a4330b1aa15044457',
    'GDB_109': 'a1179d47d9ea1e4838ef93487a2294af129342f76e9d08ee8ba4e59b0f8970f3',
    'GDB_111': '0cc2ac65aa643190cc45ae1c73c1661bcae7f7ccf51da01bbcfe535231d8c8d7',
    'GDB_100t2': '2435ae29d9cc9c55e536b37920d37855bfc3b583b75f3e0d45d08eac31e3217e',
    'GDB_100t4': '5387cee00d67ff037ee841095bbe5dc64e9f05ec29682af6f2116f42d8cad6c9',
    'GDB_100t5': 'e429f3ffdcad08fe2aef9e3269582c1a0ba01e91e4332a1a41ff68346a5082ee',
    'GDB_100t6': 'ee4326b005f3d0aabc36fb0322dc58a51726ceafcc52a94330f9e045a86ebad7',
    'GDB_100t7': '39e315a53db78fdb70ac0664a45dd89fe9eb31d0315e7aaf82e085c74dc54076',
    'GDB_100t8': 'e1a159dcb9e1afdc25f9c786cf22bcd704ff112f4bcc5c1049f3650c48d7f42a',
    'GDB_100t9': 'ad2bda20febf9ea10440ef031a515dbe59e2864a2a9c8b90ec20ee83a04738a4',

    'SW_094': 'a8fda2b180ae17f9db70e3e8814f7be362a15c64b1c0ad5cb846dba301897e43',
    'TTN_042': 'ade75f8ecef24f1af38a148280cbdf348522edaaabfcf4fa142e79b91de0b89c',
    'TTN_042t': '8bee126857c0c3056d98eaf9f9ddb5a4b7daf980478ee16d861979f2e909be3c',
    'TTN_724': '98af06a5241baae5d89916a14c9bd7805bf064f89b56b00e37d6a91a7197e32d',
    'TTN_724t': 'bcb3ee5acdb860c59a6d8df0f60e6ee338df1c05448f0bb4b195ead398d8ad0e',

    'UNG_029': 'a8935605294263edd4ef62f1a9a550402e6727dec1c50ab6e740612655c85da8',
    'ICC_091': '54092b12ec8f5ddd53efbdcf88b1e2b5b866faac6b962afc53980ff28b0119e0',
    'EX1_308': '65a776117661f80c007aaad163b2cf0809ee7afcb6666abe08c3542c61c5485b',
    'LOE_029': 'c8454eb4877eff9470fd5cbf34e6b712fa3cf69ba025c4d43dc7e61d26d64aac',
    'HERO_08': '75699b36f24b0eda2a0d96eaa34922914dcb5b8ff26db9f681745bf82bc70b1d',
    'HERO_01': '21be00517d244dd5e9a8f13c5d1b04daa2e66b229a7e7ba0275c11f48d09498d',
    'EX1_164': '9095f3f3d2fdba0efcda094492c0ebe486ef1d4c061915448afed1891c88b278',
    'CS2_182': 'f8b3732e6482a7ead67a379195156f2545bf609549fcb6ca556ef7ece5c5069f',
    'CS2_179': '56a5965a64fed4366df8b151c506cbd9ef0c7564f16fcff6800d934b15890233',
    'CS2_029': '2ec39f75e5e3c741955c80b49c9b75d516ca302a5a414b48a5e538c0f0ea5f6b',
    'CS2_009': '4ab1e2ca8449d3731c7cac3d0ddf03d8a992233b4480315262c891f223865782',
    'EX1_332': '4973febb67be520f4d42b26430c2ce870be1659cc224c1cf216487f353078e88',
    'CS2_203': '2392a2689262c90f38a24f0718d450f762710b246b35b6b2deb23194e8f2eaba',
    'EX1_581': 'c51c974ad3266111657cd96181e18125d62504a796a835ba155ccb3ea916b316',
    'EX1_096': '2d205f7817d1e1ee86187b6ac644bbbc37b7668d3a5168927e1f6f8a610a1cdc',
    'FP1_007': '3308a76c1a198e8c3ecd33b97d13c5e864655c62c55a28c1169670efc870eaca',
    'FP1_007t': '14f74a8cdb9929c1ececae6953bc767df0d18e0025ed53f0b429ebbae935f28d',
    'CS2_122': 'faeeaec881c4d2728e9e8073df3b673a90957c644e870fc859007ca90ec5395d',
    'ULD_205': 'd23f21dee4f3e6cf2de95ccda36e849390047f13543a3eaa80e6ffa0605b922f',
    'ULD_208': '2f09f4ac1ce1434f1a701b1e7983eb1d0226ebf36fcc8f38b2c1fa272c01c6e9',
    'CS2_188': '3fd0bece01efaae10c1e3e7686188ad21e0c1ef69488286398cc2b35d7d68931',
    'EX1_019': 'a868794aae16e8e63995202049c813f4d47467c809a4240a547e3912698c23fa',
    'EX1_012': 'b2a58d64fdf96ebaf0abb6b357bf357a36383e0c66eeaa85f07a09411fd5c640',
    'CS2_024': '7214630fc5ae85be9f8318285abde3554069acb8684a41d77d9b115679b103f3',
    'ICC_820': 'bc747e2c21d195e11ae73e3f2998a3f9349b88d69a0d4ec6e8d92da30d416177',
    'EX1_010': '9d60f3d922eed4a3aa6a714cbe8c48f368863f5dc99a2c298664f1ff528362ad',
    'CS2_222': '21dead113303a3e8704f2ba2d670fba2a0598266ce2ff652a8cdde2d4f28e892',
    'CS1_129': 'e9b4957f5727fa5bfc360d375143abc26cab1c29dc1f4bdb9eb5ff77f5ea04ac',
    'CS2_236': 'ee1c607d3a1ddba5359e833bad112806ae07af89435a6f3a431e689af479dbd6',
    'EX1_059': 'f6e122aa082e555eece369e2f29e81ba63c823d7f36d030e58017d7e9efd5885',
    'CS2_106': '810017c5dd6021d7be9aa35fb9be9e2affef1bd44941aae3c9b7586816747fd7',
    'CS2_082': 'fd2dd304603d3e55c4dfef5ffd7f4e45c885433b49cd4890edc8b8e09cbb9fdc',
    'FP1_021': '430729aaa90d589e884a6f8a63514cda7f050b69ab33b1aa361a8673668bd409',
    'HERO_08bp': '6633c59b7f4b69a48a2f1c67f4e165d8813aab4093fb7b66a9f96f5c3890edb5',
    'HERO_03bp': 'b2ab90b1bfea2d25f852c369a488f980d3aa651fcf888d157c9e7c7df7adb4d5',
    'HERO_01bp': '32ccb67b12dea9ffe9c2db5f30b40af3c4d9055a3e7644c8894c508a41fe370b',
    'HERO_04bp': '22e24c67f57a79abf41949f45fb6cdfe7f7854af55aad90a19666c9ed6390bc2',
    'HERO_06bp': '9e8982b30ca42640aa587d79478a3279d32a41cee3d05dba579f7fb5cfe50015',
    'CS2_101t': '1cf8910c8e175248d173bfbc183fa03248e56fa2bcf2b023cca53237dfa47384',
    'GAME_005': 'dc9ee9f9bbdfd7d49a72717eb0c43901480b86cf0b3d3573989b3b6dd033598c',
    'EX1_169': '3c5bb9a8dd043176e23c98707502eb0b95787e8202c8c79c592cd8e7211f0dff',
    'EX1_145': 'f7d9454674a19f699536cdc71588156ea881ea56450c50cea61cc8649528e695',
    'EX1_608': 'b02d152da3764c87ff41d6217a0245deadbbbf511fd56d2c567f9e0f91d1df00',
    'EX1_238': '19b46a04f8a240ad740f9864414d540e5bd29f8e950f85305ceeca559b91b11a',
    'RLK_051': '21fbf370fad589b6e0674638a7e6ebfe072cdab179632eb25b1b93c2b6ba6c83',
    'EX1_350': '5626584489fb0d489cc3dbcb77ff38c887c5a99a5c13d417f980bda53c4a9250',
    'EX1_591': 'df1f72a177336f3ce28b12cce3c1573787e4e8b9fd48c675f509924617c71bed',
    'BT_733': '2c061b61dcdd0259849f84c220245de0f62a632063e05ce81cbe7d21145204ad',
    'AT_124': '25a61966f3e24f3bd0d198e401caff12f0fbfd8be01d17ed5d759f6cdd189c97',
    'LOE_119': '080ebf6cddc9e3f5b080b84effb4b2bcf64dbf7194c1c0fa2631f78d27f1630f',
    'CS2_007': '32f7f6b2ca6814e9ae56ef653e1bf46d0ad593fb8040a2ce93c95ae9174bf26e',
    'CS2_117': 'fae2fcf9c28c012a4b0b865ae996f36218d5383b9f7037d94a219fddec0ea67e',
    'CS1_112': '1d765421b5e0edbd768c7b4b062701c07a5d06c69ca5e36ee27ebb7464957a94',
})


def metadata_from_record(raw):
    """Decode only the reviewed tags used by this pinned representative pack."""
    rarities = {1: Rarity.COMMON, 2: Rarity.FREE, 3: Rarity.RARE, 4: Rarity.EPIC, 5: Rarity.LEGENDARY}
    races = {2: 'draenei', 11: 'undead', 14: 'murloc', 15: 'demon', 17: 'mech', 18: 'elemental', 20: 'beast', 23: 'pirate', 24: 'dragon', 92: 'naga'}
    tags = raw['tags']
    class_id, rarity_id, race_id = tags.get('CLASS'), tags.get('RARITY'), tags.get('CARDRACE')
    if raw['id'] in ('SC_999t', 'SC_400', 'SC_400p', 'SC_401', 'SC_403', 'SC_403a', 'SC_403b', 'SC_403c', 'SC_403d', 'SC_403f', 'SC_403t', 'SC_410'):
        if class_id is not None or tags.get('MULTIPLE_CLASSES') != 656:
            raise TargetValidationError('Unexpected reviewed Terran class mask')
        card_classes = (CardClass.PALADIN, CardClass.SHAMAN, CardClass.WARRIOR)
    elif raw['id'] in ('CATA_722', 'CATA_190h', 'CATA_497'):
        if class_id is not None or tags.get('MULTIPLE_CLASSES')!=9153:
            raise TargetValidationError('Unexpected reviewed Herald class mask')
        card_classes=(CardClass.DEATH_KNIGHT,CardClass.DEMON_HUNTER,CardClass.ROGUE,
                      CardClass.SHAMAN,CardClass.WARLOCK,CardClass.WARRIOR)
    elif raw['id']=='DEEP_015':
        if class_id!=1 or tags.get('MULTIPLE_CLASSES')!=17:
            raise TargetValidationError('Unexpected reviewed Death Knight/Paladin mask')
        card_classes=(CardClass.DEATH_KNIGHT,CardClass.PALADIN)
    elif raw['id']=='JAM_017':
        if class_id!=10 or tags.get('MULTIPLE_CLASSES')!=8704:
            raise TargetValidationError('Unexpected reviewed Warrior/Demon Hunter mask')
        card_classes=(CardClass.WARRIOR,CardClass.DEMON_HUNTER)
    else:
        card_classes = classes_from_tags(tags)
    if rarity_id is not None and (type(rarity_id) is not int or rarity_id not in rarities):
        raise TargetValidationError('Unknown representative rarity metadata')
    if race_id is not None and (type(race_id) is not int or race_id not in races):
        raise TargetValidationError('Unknown representative race metadata')
    runes = Runes(*(tags.get(k, 0) for k in ('COST_BLOOD', 'COST_FROST', 'COST_UNHOLY')))
    if any(k in tags and (type(tags[k]) is not int or tags[k] not in (0, 1))
           for k in ('TERRAN', 'ZERG', 'PROTOSS')):
        raise TargetValidationError('Unknown representative faction metadata')
    if any(k in tags and (type(tags[k]) is not int or tags[k] not in (0, 1))
           for k in ('IMP', 'WHELP')):
        raise TargetValidationError('Unknown representative minion subtype metadata')
    subtypes = tuple(k.lower() for k in ('IMP', 'WHELP') if tags.get(k) == 1)
    if subtypes and raw['type'] != 'MINION':
        raise TargetValidationError('Representative subtypes require a minion')
    return CardMetadata(raw['collectible'], card_classes, rarities.get(rarity_id),
                        deck_identity=raw['id'], runes=runes,
                        tribes=(races[race_id],) if race_id is not None else (),
                        factions=tuple(k.lower() for k in ('TERRAN', 'ZERG', 'PROTOSS') if tags.get(k) == 1),
                        subtypes=subtypes)


def _minion(ctx: PlayerRuleContext) -> bool:
    entity = ctx.target
    return entity is not None and entity['zone'] == 'board' and entity['health'] > 0


def _friendly_minion(ctx: PlayerRuleContext) -> bool:
    return _minion(ctx) and ctx.target['controller'] == ctx.player_id


def _enemy_minion(ctx: PlayerRuleContext) -> bool:
    return _minion(ctx) and ctx.target['controller'] != ctx.player_id


def _egg_hatch(ctx: RuleContext):
    if ctx.death is not None:
        return [card_summon(ctx,ctx.death.controller, "FP1_007t", ctx.death.position)]
    # Forced deathrattles have a captured living source, not a fabricated death.
    return [card_summon(ctx,ctx.player_id, "FP1_007t", ctx.state.players[ctx.player_id].board.index(ctx.source_id)+1)]


def _biopod(c):
    enemy = c.state.players[3 - c.player_id]
    attack = c.death.attack if c.death is not None else c.source.attack
    return [RandomDamage((enemy.hero_id, *enemy.board), attack, c.source_id)]


def _launch_discount(c):
    return [AddCostModifier(c.player_id, CostSpec(delta=-2), uses_remaining=1,
                            source_id=c.source_id, scope=CostScope.STARSHIP_LAUNCH)]


def _marines(c):
    return [card_summon(c,c.player_id, 'SC_403t'), card_summon(c,c.player_id, 'SC_403t')]


def _supercapacitor(c):
    others = sum(i != c.source_id and c.state.entities[i].active and c.state.entities[i].kind == CardType.MINION
                 for i in c.state.players[c.player_id].board)
    return [Buff(c.source_id, others, others, c.source_id)]


def _enemy_damage(c, amount, include_hero=False):
    enemy = c.state.players[3 - c.player_id]
    ids = (*((enemy.hero_id,) if include_hero else ()), *enemy.board)
    # Keep functionally dead minions until the launch boundary closes (32.0).
    return [DamageBatch(tuple(Damage(i, amount, c.source_id) for i in ids))]


def _exodar(c):
    ship = construction(c.state, c.player_id)
    if ship is None:
        return []
    return [LaunchStarshipEffect(c.player_id, ship.id, followup=(
        InvokeBehavior('m4.exodar_protocols', c.source_id, c.player_id, ship.id),))]


def _exodar_protocols(c):
    # Bind the ship that was launched, never a new construction or a copy.
    ship = c.state.entities[c.target_id]
    if not ship.components:
        return []  # Its composition was lost (e.g. transformation); R-034.
    attack, health, pieces = ship.attack, ship.health, ship.components
    if ship.zone == Zone.GRAVEYARD:
        record = next((d for d in reversed(c.state.death_history)
                       if d.entity_id == ship.id and d.components), None)
        if record is not None:
            attack, health, pieces = record.attack, record.max_health-record.damage, record.components
    # Values and multiplicity are captured when options are offered. These are
    # battlecry branches, not spells cast by the ship (no inherited ship lifesteal).
    return [RequestChoice(c.player_id, (
        ChoiceOption('GDB_100a', '紧急修复', (GainArmor(c.player_id, max(0,health)),
            GainArmor(c.player_id, max(0,health))), card_id='GDB_100a'),
        ChoiceOption('GDB_100b', '攻击队形', (SplitDamage(3-c.player_id, max(0,attack), c.source_id),),
            card_id='GDB_100b'),
        ChoiceOption('GDB_100c', '乘务转运', tuple(AddToHand(c.player_id, card_id, c.source_id,
            cost=CostSpec(set_to=1)) for card_id in pieces), card_id='GDB_100c'),
    ), source_id=c.source_id, prompt='埃索达：选择一项指令')]


def quest_increment(c):
    if c.event.player_id != c.player_id:
        return []
    progress = c.source.quest_progress
    amount = c.event.amount if c.event.kind == 'hero_attack_gained' else 1
    return [AdvanceQuest(c.source_id, progress.id, progress.stage, amount)]


def secret_enemy_attack(c):
    return attack_live(c.state, c.window) and c.state.entities[c.window.source_id].controller != c.player_id


def secret_hero_attack(c):
    return secret_enemy_attack(c) and c.window.target_id == c.state.players[c.player_id].hero_id


def blessing_of_the_golem(c):
    n=imbue_value(c.state,c.player_id)
    return [card_summon(c,c.player_id,'EDR_847pt2',stats=SummonStats(n,n))]


def blessing_of_the_wisp(c):
    n=imbue_value(c.state,c.player_id)
    # Yield a bounded interpreter expansion rather than materializing arbitrary
    # amounts before the resolution budget can be checked.
    for _ in range(n):
        yield card_summon(c,c.player_id,'EDR_851t')
    yield SplitDamage(3-c.player_id,n,c.source_id,kind=DamageKind.HERO_POWER)


def blessing_of_the_infinite(c,registry):
    from .play_history import is_first_play
    if (c.play is None or c.play.player_id != c.player_id or not is_first_play(c.state,c.play,
            registry=registry,kind=CardType.MINION,tribes_any=('undead',))):
        return []
    # Accepted-entry listeners run after a successful magnetic merge or summon.
    target=c.state.entities[c.play.magnetic_target_id if c.play.minion_result=='magnetized' else c.play.source_id]
    if target.zone != Zone.BOARD or target.kind != CardType.MINION: return []
    return [BuffCapturedMinion(MinionReference.capture(target),imbue_value(c.state,c.player_id),0,c.source_id)]


def blessing_of_the_wolf(c):
    n=imbue_value(c.state,c.player_id)
    return [RandomBuffStoredMinion(c.player_id,attack=n,query=PoolQuery(tribes_any=('beast',)),
        source_id=c.source_id,cost=CostSpec(delta=-n))]


def blessing_of_the_wind(c):
    target=c.state.entities.get(c.target_id)
    if target is None or target.zone!=Zone.BOARD or target.kind!=CardType.MINION:return []
    return [TransformMinionFromPool(MinionReference.capture(target),WIND_POOL_ID,
        imbue_value(c.state,c.player_id),source_id=c.source_id)]


def emerald_portal(c):
    # R-105: caster-owned progress at payload capture, not at portal creation.
    cost=imbue_value(c.state,c.player_id)
    return [SummonFromPool(c.player_id,PORTAL_POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',),min_cost=cost,max_cost=cost),
        c.source_id,cause=SummonCause.capture(c))]


def blessing_of_the_moon(c):
    # R-106: one independent minion and spell offer, filtered by affordability.
    groups=tuple(PoolOfferGroup(MOON_POOL_ID,PoolQuery(kinds=(kind,),collectible=True,
        class_mode='specified',classes=(CardClass.PRIEST,),include_neutral=False))
        for kind in (CardType.MINION,CardType.SPELL))
    return [ChooseFromPools(c.player_id,groups,c.source_id,cost=CostSpec(delta=-imbue_value(c.state,c.player_id)),
        temporary_until=c.state.turn,affordable=True,prompt='选择一张本回合可用的临时牧师牌')]


def twilight_whelp(c,registry):
    from .cross_zone import minion_references
    if minion_references(c.state,registry,c.player_id,MinionScope((Zone.HAND,),PoolQuery(tribes_any=('dragon',)))):
        return [BuffCapturedMinion(MinionReference.capture(c.state.entities[c.source_id]),health=2,source_id=c.source_id)]
    return []


def _shudderwock(c):
    """R-126 experimental composition; parameters are not CN certification.

    Use the same original-window policy as the experimental Macaw adapter.
    Along played-history edges that bound strictly decreases, so mixed replay
    terminates by its declared history policy, never by swallowing a budget error.
    The cap covers this sequence's direct attempts, not descendant activations.
    """
    from .battlecry_sequences import RepeatPlayedBattlecrySequence, PlayedBattlecryFilter, BattlecrySequencePolicy
    from .played_battlecries import battlecry_play_window
    return [RepeatPlayedBattlecrySequence(c.player_id, c.source_id, 30,
        query=PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry),countered='include'),
        filters=PlayedBattlecryFilter(exclude_behaviors=('m5.shudderwock',)),
        selection='random', order='random', choices='random',
        policy=BattlecrySequencePolicy('same_incarnation','current',exclude_source_target=True))]


def register_combo_pool(registry, baseline, metadata_decoder=metadata_from_record):
    """Use a frozen raw inventory, never derive discovery membership from adapters."""
    path=Path(__file__).resolve().parents[2]/'data/support/combo-source-inventory.json'
    inventory=json.loads(path.read_text(encoding='utf-8'))
    if canonical_digest(inventory)!=COMBO_SOURCE_INVENTORY_HASH:
        raise TargetValidationError('Combo source inventory differs from its pinned version')
    sample=inventory['experimental_pool']
    for entry in sample['rows']:
        raw=entry['data'];cid=raw['id']
        if canonical_digest(raw)!=entry['data_sha256']:
            raise TargetValidationError('Combo pool raw record fingerprint mismatch')
        # These reviewed rows use only COMBO or STEALTH flags. Reference tags
        # (Shark mentions Combo) are not printed keyword declarations.
        keywords=tuple(k for k in (Keyword.COMBO,Keyword.STEALTH) if raw['tags'].get(k.name)==1)
        row=PoolCard(cid,CardType(raw['type'].lower()),raw['cost'],metadata_decoder(raw),
            keywords=keywords,battlecry=raw['tags'].get('BATTLECRY')==1,
            deathrattle=raw['tags'].get('DEATHRATTLE')==1,choose_one=raw['tags'].get('CHOOSE_ONE')==1,
            attack=raw['attack']if raw['type']=='MINION'else None)
        if cid in registry.pool_cards:
            if registry.pool_card(cid)!=row:
                raise TargetValidationError('Combo pool metadata conflicts with another pinned inventory')
        else:registry.register_pool_card(row)
    registry.register_pool(PoolDefinition(sample['id'],sample['version'],baseline.target['target_id'],
        sample['mode'],tuple(PoolMember(i) for i in sample['members']),complete=sample['complete']))


def build_registry(*, version: str = "representative-m5-v65", known_unrarified_ids: tuple[str, ...] = (),
                   initial_hero_power_bindings: tuple[tuple[str, str], ...] = (), defer_validation: bool = False,
                   metadata_overrides: tuple[tuple[str, CardMetadata], ...] = ()) -> Registry:
    """Compile fixtures; an outer content assembler can defer final reference linking."""
    if type(defer_validation)is not bool:raise ValueError('Deferred content validation must be explicit boolean')
    if (type(metadata_overrides)is not tuple or any(type(row)is not tuple or len(row)!=2 or
            type(row[0])is not str or not row[0].strip()or type(row[1])is not CardMetadata for row in metadata_overrides)):
        raise ValueError('Printed metadata overrides require immutable explicit card/metadata pairs')
    overrides=dict(metadata_overrides);used_metadata=set()
    if len(overrides)!=len(metadata_overrides):raise ValueError('Duplicate printed metadata override')
    for meta in overrides.values():meta.__post_init__()
    if (type(initial_hero_power_bindings)is not tuple or any(type(row)is not tuple or len(row)!=2 or
            any(type(value)is not str or not value.strip()for value in row)for row in initial_hero_power_bindings)):
        raise ValueError('Initial hero bindings require immutable explicit hero/power pairs')
    initial_powers=dict(initial_hero_power_bindings)
    if len(initial_powers)!=len(initial_hero_power_bindings):raise ValueError('Duplicate initial hero binding')
    if type(known_unrarified_ids) is not tuple or len(set(known_unrarified_ids)) != len(known_unrarified_ids) or any(
            type(cid) is not str for cid in known_unrarified_ids):
        raise ValueError('Known unrarified faces require unique explicit card IDs')
    known_unrarified_ids = frozenset(known_unrarified_ids)
    def decode_metadata(raw):
        meta = metadata_from_record(raw)
        if raw['id'] in known_unrarified_ids:
            if meta.collectible or meta.rarity is not None or 'RARITY' in raw['tags']:
                raise TargetValidationError('Known unrarified override conflicts with the original complete face')
            meta = replace(meta, rarity=Rarity.NONE)
        return meta
    baseline = load_baseline()
    snapshots = {row["id"]: row for row in baseline.support["cards"]}
    for card_id, expected in EXPECTED_CARD_HASHES.items():
        row = snapshots.get(card_id)
        if row is None or row["data_sha256"] != expected or canonical_digest(row["data"]) != expected:
            raise TargetValidationError(f"representative adapter requires its pinned card version: {card_id}")

    imbue_inventory=json.loads((Path(__file__).resolve().parents[2]/'data/support/imbue-inventory.json').read_text(encoding='utf-8'))
    if canonical_digest(imbue_inventory) != IMBUE_INVENTORY_HASH or imbue_inventory['class_powers'] != {c.value:i for c,i in IMBUE_CLASS_POWERS.items()}:
        raise TargetValidationError('Imbue inventory differs from its pinned class mappings')

    starship_ids = ('GDB_100t2', 'GDB_100t4', 'GDB_100t5', 'GDB_100t6',
                    'GDB_100t7', 'GDB_100t8', 'GDB_100t9', 'SC_999t')
    registry = Registry(version)
    registry.register_end_turn_candidate_profile(EndTurnCandidateProfile('CATA_472.end_turn_candidates'))
    registry.register_behavior('m5.inspiring_maul', lambda c: [TriggerRandomEndTurnEffects(
        c.player_id, EndTurnProducerRequest(EndTurnSelector('owner', (c.player_id,), ('minion',)),
            'CATA_472.end_turn_candidates'), c.source_id)])
    registry.register_behavior('m5.breakout_architect',lambda c:[DiscoverFromPool(c.player_id,CARD_SPELL_POOL_ID,
        PoolQuery(kinds=(CardType.SPELL,),min_cost=5,collectible=True,class_mode='current'),
        source_id=c.source_id,spell_repeat=CardSpellRepeatGrant())])
    registry.register_behavior('m5.pyroblast',lambda c:[Damage(c.target_id,10,c.source_id,DamageKind.SPELL)])
    def enemy_spell_batch(c,amount,freeze=False):
        ids=tuple(e.id for e in enemy_minions(c))
        return [DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.SPELL) for i in ids)),
                *(Freeze(i,c.source_id) for i in ids if freeze)]
    registry.register_behavior('m5.blizzard',lambda c:enemy_spell_batch(c,2,True))
    registry.register_behavior('m5.flamestrike',lambda c:enemy_spell_batch(c,5))
    registry.register_behavior('m5.lucky_comet', lambda c: [DiscoverFromPool(c.player_id,COMBO_POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.COMBO,)),source_id=c.source_id),
        AddComboRepeatModifier(c.player_id,source_id=c.source_id,uses=1,trigger='play')])
    registry.register_behavior('m5.defias_ringleader',lambda c:[card_summon(c,c.player_id,'EX1_131t')])
    registry.register_behavior('m5.electra',lambda c:[AddSpellRepeatModifier(c.player_id,source_id=c.source_id,uses=1,expires_turn=c.state.turn)])
    registry.register_behavior('m5.tyrande',lambda c:[AddSpellRepeatModifier(c.player_id,source_id=c.source_id,uses=3)])
    registry.register_behavior('m5.twinbow',lambda c:[AddSpellRepeatModifier(c.player_id,source_id=c.source_id,uses=1)]
        if held_spell_condition(c) else [])
    registry.register_behavior('m5.shudderwock', _shudderwock)
    registry.register_behavior('m5.bolner', _bolner_repeat)
    registry.register_behavior('m5.deepminer_brann', lambda c: [CheckDeckCondition(c.player_id,
        DeckCondition('starting'), (AddBattlecryRepeatModifier(c.player_id, source_id=c.source_id),))])
    registry.register_behavior('m5.murmuring_elemental',lambda c:[AddBattlecryRepeatModifier(c.player_id,
        source_id=c.source_id,uses=1,expires_turn=c.state.turn)])
    registry.register_behavior('m5.heart_of_virnaal',lambda c:[AddBattlecryRepeatModifier(c.player_id,
        source_id=c.source_id,expires_turn=c.state.turn)])

    from .played_battlecries import PlayedBattlecryQuery, RepeatPlayedBattlecries, battlecry_play_window
    registry.register_behavior('m5.brilliant_macaw',lambda c:[RepeatPlayedBattlecries(c.player_id,c.source_id,
        PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry),countered='include'))])

    registry.register_behavior('m5.snapdragon',lambda c:[BuffMinionsInZones(c.player_id,1,1,
        MinionScope((Zone.DECK,),PoolQuery(ability=CardAbilityCondition())),c.source_id)])

    from .model import CounterPolicySpec
    from .counter_policies import GrantCounterPolicy
    def okani(c):
        entity = c.state.entities[c.source_id]
        if entity.zone != Zone.BOARD or entity.kind != CardType.MINION or not entity.active or entity.health <= 0 or entity.doomed:
            return []
        carrier = MinionReference.capture(entity)
        return [RequestChoice(c.player_id, tuple(ChoiceOption(kind.value, label,
            (GrantCounterPolicy(carrier, CounterPolicySpec(kind, key='okani'), c.source_id),), card_id=card_id)
            for kind, label, card_id in ((CardType.MINION, '反制随从', 'TSC_032t'),
                                         (CardType.SPELL, '反制法术', 'TSC_032t2'))),
            source_id=c.source_id, prompt='剑圣奥卡尼：秘密选择反制类型')]
    registry.register_behavior('m5.okani', okani)

    from .model import ChooseBranch, ChooseOneSpec
    registry.register_behavior('m5.nourish_mana',lambda c:[ChangeManaCrystals(c.player_id,2,filled=True)])
    registry.register_behavior('m5.nourish_draw',lambda c:[Draw(c.player_id,3)])
    registry.register_behavior('m5.nourish_both',lambda c:[ChangeManaCrystals(c.player_id,2,filled=True),Draw(c.player_id,3)])
    registry.register_behavior('m5.wrath_damage',lambda c:[Damage(c.target_id,3,c.source_id,DamageKind.SPELL)])
    registry.register_behavior('m5.wrath_draw',lambda c:[Damage(c.target_id,1,c.source_id,DamageKind.SPELL),Draw(c.player_id,1)])
    registry.register_behavior('m5.wrath_both',lambda c:[Damage(c.target_id,3,c.source_id,DamageKind.SPELL),
        Damage(c.target_id,1,c.source_id,DamageKind.SPELL),Draw(c.player_id,1)])
    registry.register_behavior('m5.war_attack',lambda c:[Buff(c.source_id,attack=5,source_id=c.source_id)])
    registry.register_behavior('m5.war_health',lambda c:[Buff(c.source_id,health=5,source_id=c.source_id),GrantKeyword(c.source_id,Keyword.TAUNT)])
    registry.register_behavior('m5.war_both',lambda c:[Buff(c.source_id,attack=5,health=5,source_id=c.source_id),GrantKeyword(c.source_id,Keyword.TAUNT)])

    from .inspire import is_inspire
    from .effects import ModifyWeapon
    registry.register_behavior('m5.lowly_squire',lambda c:[Buff(c.source_id,attack=1,source_id=c.source_id)]
        if is_inspire(c.state,c.event,c.player_id) else [])
    registry.register_behavior('m5.orgrimmar_aspirant',lambda c:[
        ModifyWeapon(c.state.players[c.player_id].weapon_id,attack=1,source_id=c.source_id)]
        if is_inspire(c.state,c.event,c.player_id) and c.state.players[c.player_id].weapon_id is not None else [])

    from .death_causes import was_honorably_killed
    registry.register_behavior('m5.korrak',lambda c:[] if was_honorably_killed(c.death) else
        [card_summon(c,c.player_id,'AV_143',position=c.death.position if c.death else None)])

    from .health_outcomes import is_overkill, is_honorable_kill, is_overheal
    registry.register_behavior('m5.gurubashi_chicken',lambda c:[Buff(c.source_id,attack=5,source_id=c.source_id)]
        if is_overkill(c.event,c.source_id) else [])
    registry.register_behavior('m5.gnome_private',lambda c:[Buff(c.source_id,attack=2,source_id=c.source_id)]
        if is_honorable_kill(c.event,c.source_id) else [])
    registry.register_behavior('m5.holy_champion',lambda c:[Buff(c.source_id,attack=2,source_id=c.source_id)]
        if is_overheal(c.event,c.source_id) else [])

    from .hero_powers import TriggerHeroPower
    registry.register_behavior('m5.wisprider',lambda c:[Imbue(c.player_id,c.source_id),TriggerHeroPower(c.player_id,c.source_id)])
    registry.register_behavior('m5.imbue',lambda c:[Imbue(c.player_id,c.source_id)])
    registry.register_behavior('m5.blessing_golem',blessing_of_the_golem)
    registry.register_behavior('m5.blessing_wisp',blessing_of_the_wisp)
    registry.register_behavior('m5.blessing_infinite',lambda c:blessing_of_the_infinite(c,registry))
    registry.register_behavior('m5.blessing_wolf',blessing_of_the_wolf)
    registry.register_behavior('m5.blessing_wind',blessing_of_the_wind)
    from .deck_shuffles import shuffled
    registry.register_behavior('m5.blessing_dragon',lambda c:shuffled(c,(
        AddToDeck(c.player_id,'EDR_445pt3',source_id=c.source_id),
        AddToDeck(c.player_id,'EDR_445pt3',source_id=c.source_id))))
    registry.register_behavior('m5.blessing_moon',blessing_of_the_moon)
    registry.register_behavior('m5.emerald_portal',emerald_portal)
    registry.register_behavior('m5.twilight_whelp',lambda c:twilight_whelp(c,registry))
    registry.register_behavior('m5.blessing_bronze',lambda c:[GenerateFromPool(c.player_id,BRONZE_POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='other',include_neutral=False),
        source_id=c.source_id,cost=CostSpec(delta=-imbue_value(c.state,c.player_id)))])
    registry.register_imbue_profile(ImbueProfile('imbue','representative-imbue-v1',tuple(
        ImbueClass(cls,IMBUE_CLASS_POWERS.get(cls)) for cls in sorted(PLAYABLE_CLASSES))))
    registry.register_behavior('m5.azerite_snake',lambda c:[StealHeroHealth(c.player_id,3-c.player_id,10,c.source_id)])
    registry.register_behavior('m5.azerite_dragon',lambda c:[BuffMinionsInZones(c.player_id,3,3,
        MinionScope(exclude_source=True),c.source_id)])
    registry.register_behavior('m5.azerite_murloc',lambda c:[TransformMinionsInZones(c.player_id,
        EXCAVATE_TRANSFORM_POOL_ID,3,MinionScope(exclude_source=True),
        cost_basis='printed',retain_cost_basis='printed',source_id=c.source_id)])
    registry.register_behavior('m5.azerite_hawk',lambda c:[GenerateFromPool(c.player_id,EXCAVATE_TITAN_POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.TITAN,)),source_id=c.source_id,
        cost=CostSpec(set_to=1),policy=GenerationPolicy((Keyword.TITAN,)))])
    registry.register_behavior('m5.azerite_ox',lambda c:[DiscoverFromPool(c.player_id,EXCAVATE_EIGHT_POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),min_cost=8,max_cost=8,collectible=True,class_mode='current'),source_id=c.source_id,
        discoveries=2,destination='board',delivery='after_all')])
    registry.register_behavior('m5.azerite_rat', lambda c:[Resurrect(c.player_id,
        query=DeathQuery(cost_extreme='highest'), source_id=c.source_id, on_summon='m5.rat_enhance')])
    def rat_enhance(c):
        ref = MinionReference.capture(c.state.entities[c.target_id])
        return [BuffCapturedMinion(ref, 2, 2, c.source_id),
                GrantCapturedKeyword(ref, Keyword.REBORN, c.source_id),
                GrantCapturedKeyword(ref, Keyword.LIFESTEAL, c.source_id)]
    registry.register_behavior('m5.rat_enhance', rat_enhance)
    registry.register_behavior('m5.excavate', lambda c:[Excavate(c.player_id,c.source_id)])
    registry.register_behavior('m5.pouch', lambda c:[AddToHand(c.player_id,'GAME_005',c.source_id) for _ in range(2)])
    registry.register_behavior('m5.stalactite', lambda c:[DamageBatch((
        Damage(c.target_id,3,c.source_id,DamageKind.SPELL),Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id,DamageKind.SPELL)))])
    registry.register_behavior('m5.azerite_scorpion', lambda c:[GenerateFromPool(c.player_id,GENERATION_POOL_ID,
        PoolQuery(kinds=(CardType.SPELL,),collectible=True),count=4,source_id=c.source_id,
        cost=CostSpec(delta=-excavation_count(c.state,c.player_id),minimum=1))])
    for cid, owner, callback, reveal in (
            ('TID_700', 'enemy', 'm5.disarming_selected', False),
            ('TID_703', 'self', 'm5.idol_selected', True),
            ('TID_099', 'self', 'm5.k9_selected', False),
            ('TID_003', 'self', 'm5.burrower_selected', False)):
        registry.register_behavior('m5.dredge.' + cid, lambda c, owner=owner, callback=callback, reveal=reveal:
            [Dredge(c.player_id, 3-c.player_id if owner == 'enemy' else c.player_id,
                    c.source_id, callback, reveal)])
    registry.register_behavior('m5.disarming_selected', lambda c: [ModifyCost(c.target_id, CostSpec(set_to=6), c.source_id)])
    registry.register_behavior('m5.idol_selected', lambda c: [DamageBatch(tuple(
        Damage(i, c.state.entities[c.target_id].cost, c.source_id, DamageKind.SPELL)
        for p in c.state.players.values() for i in p.board
        if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active))])
    registry.register_behavior('m5.k9_selected', lambda c: [SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]), c.player_id)]
        if c.state.entities[c.target_id].kind == CardType.MINION and c.state.entities[c.target_id].cost == 1 else [])
    registry.register_behavior('m5.burrower_selected', lambda c: [CopyStoredMinion(
        CardReference.capture(c.state.entities[c.target_id]), c.player_id, stats=SummonStats(attack=2,health=2))]
        if c.state.entities[c.target_id].kind == CardType.MINION and
            'murloc' in registry.card(c.state.entities[c.target_id].card_id).metadata.tribes else [])
    registry.register_behavior('m5.semi_stable_portal', lambda c: [GenerateFromPool(c.player_id,
        GENERATION_POOL_ID, PoolQuery(kinds=(CardType.MINION,), collectible=True),
        source_id=c.source_id, cost=CostSpec(delta=-3))])
    registry.register_behavior('m5.sands_of_time', lambda c: [DiscoverFromPool(c.player_id,
        GENERATION_POOL_ID, PoolQuery(kinds=(CardType.SPELL,), collectible=True,
            class_mode='current' if c.rewind_attempt else 'any', include_neutral=False), source_id=c.source_id)])
    registry.register_behavior('m5.morchie', lambda c: [DiscoverFromPool(c.player_id,
        REWIND_POOL_ID, PoolQuery(collectible=True, include_neutral=False,
            keywords_all=(Keyword.REWIND,)), source_id=c.source_id)])
    registry.register_target_rule("m1.minion", _minion, visibility='player')
    registry.register_target_rule("m1.friendly_minion", _friendly_minion, visibility='player')
    registry.register_target_rule("m1.enemy_minion", _enemy_minion, visibility='player')
    for key, condition in {
        'm5.minion_counter': lambda c: c.window is not None and c.window.kind == 'minion' and c.window.counter_phase and not c.window.countered and c.window.player_id != c.player_id,
        'm4.counter': lambda c: c.window is not None and c.window.kind == 'spell' and
            not c.window.countered and c.window.player_id != c.player_id,
        'm4.spell_minion': lambda c: c.window is not None and c.window.kind == 'spell' and not c.window.countered and
            c.window.player_id != c.player_id and (e := c.state.entities.get(c.window.target_id)) is not None and
            e.zone == Zone.BOARD and e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed,
        'm4.hero_attacked': secret_hero_attack,
        'm4.enemy_attack': secret_enemy_attack,
        'm4.minion_attack': lambda c: secret_enemy_attack(c) and c.state.entities[c.window.source_id].kind == CardType.MINION,
        'm4.minion_played': lambda c: c.event.player_id != c.player_id and
            (e := c.state.entities.get(c.event.source_id)) is not None and e.zone == Zone.BOARD and
            e.kind == CardType.MINION and e.active and e.health > 0 and not e.doomed,
    }.items():
        registry.register_secret_condition(key, condition)
    def glugg(c):
        death=next((d for d in c.state.death_history if d.id==dict(c.event.data).get('death_id')),None)
        if death is None or death.controller!=c.player_id or death.entity_id==c.source_id:return []
        return [Buff(c.source_id,death.base_attack,death.base_health,c.source_id)]
    def ozumat(c):
        limbs={'TID_711t',*(f'TID_711t{i}' for i in range(2,7))}
        count=sum(c.state.entities[i].card_id in limbs and c.state.entities[i].active and not c.state.entities[i].doomed and c.state.entities[i].health>0 for i in c.state.players[c.player_id].board)
        # Each hit replans the shared random-destruction behavior after the
        # preceding deathrattle/reactions, including newly summoned enemies.
        return [InvokeBehavior('m5.spider_bomb',c.source_id,c.player_id) for _ in range(count)]
    def lure(c):
        return [RandomForceAttack(tuple(c.state.players[3-c.player_id].board),tuple(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='TSC_216'),c.source_id)]
    def ragnaros_hand(c):
        amount=2*instance_multiplier(c.death if c.death is not None else c.source)
        enemy=c.state.players[3-c.player_id]
        return [RandomDamage((enemy.hero_id,*enemy.board),amount,c.source_id)]
    def ragnaros_end(c):
        return [TriggerDeathrattles(i,c.source_id) for i in c.state.players[c.player_id].board
                if c.state.entities[i].kind==CardType.MINION]
    def azshara_soldier(c):
        if c.event.source_id!=c.source_id:return []
        return [Buff(c.state.players[c.player_id].hero_id,instance_multiplier(c.source),0,
                     c.source_id,expires_turn=c.state.turn)]
    def sinestra_soldier(c):
        if c.event.source_id != c.source_id:
            return []
        return [GenerateFromPool(c.player_id, HERALD_POOL_ID,
            PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='other', include_neutral=False),
            source_id=c.source_id, cost=CostSpec(delta=-instance_multiplier(c.source)))]
    def onyxia_soldier(c):
        if c.event.source_id != c.source_id:
            return []
        cost = 2 * instance_multiplier(c.source)
        return [GenerateFromPool(c.player_id, HERALD_POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost, max_cost=cost),
            source_id=c.source_id, cost=CostSpec(payment=PaymentType.HEALTH), expires_turn=c.state.turn)]
    def alakir(c):
        # ColossalBattlecry supplies the settled state after appendages and their
        # reactions. Freeze this value once for the entire two-card generation.
        attack = c.source.attack
        return [GenerateFromPool(c.player_id, ATTACK_COST_POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=attack, max_cost=attack),
            count=2, source_id=c.source_id, cost=CostSpec(set_to=1))]
    def deathwing(c):
        return [ChooseInOrder(c.player_id, tuple(ChoiceOption(cid, snapshots[cid]['data']['name'],
            (InvokeBehavior(behavior, c.source_id, c.player_id),), card_id=cid)
            for cid, behavior in (('CATA_190t10', 'm5.reign'), ('CATA_190t11', 'm5.topple'),
                                  ('CATA_190t12', 'm5.raze'), ('CATA_190t13', 'm5.enthrall'))),
            herald_multiplier(c.state, c.player_id), c.source_id, '选择下一项灾变')]

    def enemy_minions(c):
        return [e for i in c.state.players[3-c.player_id].board
                if (e := c.state.entities[i]).kind == CardType.MINION
                and e.active and e.health > 0 and not e.doomed]

    def topple(c):
        candidates = enemy_minions(c)
        highest = max((e.health for e in candidates), default=0)
        return [RandomDestroy(tuple(e.id for e in candidates if e.health == highest), c.source_id)]

    def ultraxion(c):
        # R-076: capture the printed-one-plus-prior-Herald count before its own
        # Herald. The exact CN formula and scope still require calibration.
        amount = 1 + herald_count(c.state, c.player_id)
        return [Herald(c.player_id, c.source_id), AddCostModifier(c.player_id,
            CostSpec(delta=-amount, card_ids=DEATHWING_FAMILY_IDS), source_id=c.source_id)]

    behaviors = {
        'm5.deathwing': deathwing,
        'm5.ultraxion': ultraxion,
        'm5.ruthless': lambda c: [Buff(c.state.players[c.player_id].hero_id, 5, 0,
                                      c.source_id, expires_turn=c.state.turn)],
        'm5.reign': lambda c: [card_summon(c,c.player_id, 'CATA_190t14')],
        'm5.topple': topple,
        'm5.raze': lambda c: [DamageBatch(tuple(Damage(e.id, 4, c.source_id) for e in enemy_minions(c)))],
        'm5.enthrall': lambda c: [GenerateFromPool(c.player_id, DEATHWING_POOL_ID,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, rarities=(Rarity.LEGENDARY,),
                      tribes_any=('dragon',)), count=5, source_id=c.source_id,
            destination='deck', cost=CostSpec(set_to=1))],
        'm5.chogall_soldier': lambda c: [SacrificeAdjacent(MinionReference.capture(c.source),
            2 * instance_multiplier(c.source), 2 * instance_multiplier(c.source), source_id=c.source_id)],
        'm5.shadowsworn_heal': lambda c: [Heal(c.state.players[c.player_id].hero_id, 3, c.source_id)],
        'm5.sinestra_soldier': sinestra_soldier,
        'm5.onyxia_soldier': onyxia_soldier,
        'm5.herald':lambda c:[Herald(c.player_id,c.source_id)],
        'm5.ravager':lambda c:[Herald(c.player_id,c.source_id,(Keyword.RUSH,))],
        'm5.soul_forest':lambda c:[GrantDeathrattle(i,'m5.treant',c.source_id) for i in c.state.players[c.player_id].board
            if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active],
        'm5.treant':lambda c:[card_summon(c,c.player_id,'EX1_158t',c.death.position if c.death else None)],
        'm5.yodeler':lambda c:[TriggerDeathrattles(c.target_id,c.source_id,times=2)] if c.target_id is not None else [],
        'm5.ragnaros_hand':ragnaros_hand,
        'm5.ragnaros_end':ragnaros_end,
        'm5.azshara_soldier':azshara_soldier,
        'm5.alakir':alakir,
        'm5.fel_infusion':lambda c:[Herald(c.player_id,c.source_id),
            GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.LIFESTEAL,c.source_id,expires_turn=c.state.turn)],
        'm5.glugg':glugg, 'm5.ozumat':ozumat, 'm5.lure':lure,
        'm5.spider_bomb': lambda c: [RandomDestroy(tuple(i for i in c.state.players[3-c.player_id].board if c.state.entities[i].kind==CardType.MINION),c.source_id)],
        'm5.missile_launcher': lambda c: [DamageBatch(tuple(Damage(i,1,c.source_id) for p in c.state.players.values() for i in (p.hero_id,*p.board) if i!=c.source_id and c.state.entities[i].is_character and c.state.entities[i].active))],
        'm5.audio_medic': lambda c: [GrantKeyword(c.source_id,Keyword.LIFESTEAL)] if c.spell_conditions.finale else [],
        'm5.through_fel': lambda c: [GrantKeyword(c.target_id,Keyword.RUSH),*([Buff(c.target_id,1,1)] if c.spell_conditions.finale else [])],
        'm5.arcane_bolt': lambda c: [Damage(c.target_id,3 if c.spell_conditions.manathirst else 2,c.source_id,DamageKind.SPELL)],
        'm5.silvermoon': lambda c: [Buff(c.source_id,2,2),GrantKeyword(c.source_id,Keyword.DIVINE_SHIELD)] if c.spell_conditions.manathirst else [],
        'm5.sunspot': lambda c: [Damage(c.target_id,6,c.source_id)] if c.spell_conditions.quickdraw and c.target_id is not None else [],
        'm5.rehydrate': lambda c: [Heal(c.target_id,7,c.source_id),*([RefreshMana(c.player_id,2)] if c.spell_conditions.quickdraw else [])],
        'm5.growth': lambda c: [BuffStoredCard(CardReference.capture(c.source),1,1,c.source_id)],
        'm5.fool': lambda c: [Draw(c.player_id)],
        'm5.fool_infused': lambda c: [Draw(c.player_id,3)],
        'm5.touch': lambda c: [Damage(c.target_id,3,c.source_id,DamageKind.SPELL)],
        'm5.touch_infused': lambda c: [Damage(c.target_id,3,c.source_id,DamageKind.SPELL),AddToHand(c.player_id,'REV_601')],
        'm5.initiate': lambda c: [Buff(c.source_id,attack=2)],
        'm5.gibberling': lambda c: [card_summon(c,c.player_id,'SCH_242')],
        'm5.flinger_play': lambda c: [Damage(c.target_id,1,c.source_id)] if c.target_id is not None else [],
        'm5.flinger_burst': lambda c: [ReturnToHand(c.source_id)],
        'm5.gidra': lambda c: [Buff(c.source_id,attack=c.play.cost,health=c.play.cost)] if c.play.cost else [],
        'm5.thrasher': lambda c: [Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id)],
        'm5.sunwell': lambda c: [GrantKeyword(c.source_id,Keyword.DIVINE_SHIELD)],
        'm5.grunt': lambda c: [GainArmor(c.player_id,c.event.amount)],
        'm5.samuro': lambda c: [DamageBatch(tuple(Damage(i,c.source.attack,c.source_id)
            for i in c.state.players[3-c.player_id].board if c.state.entities[i].active and c.state.entities[i].kind==CardType.MINION))],
        'm5.eviscerate': lambda c: [Damage(c.target_id,4 if c.spell_conditions.combo else 2,c.source_id,DamageKind.SPELL)],
        'm5.si7': lambda c: [Damage(c.target_id,3,c.source_id)] if c.target_id is not None else [],
        'm5.edwin': lambda c: [Buff(c.source_id,attack=2*c.play.prior_turn_plays,health=2*c.play.prior_turn_plays)],
        'm5.runner': lambda c: [Draw(c.player_id)] if c.spell_conditions.outcast else [],
        'm5.consume': lambda c: [Silence(c.target_id),*([Draw(c.player_id)] if c.spell_conditions.outcast else [])],
        'm5.sight': lambda c: [Draw(c.player_id,2 if c.spell_conditions.outcast else 1)],
        'm5.minion_counter': lambda c: [CounterMinion(c.window.id)],
        'm4.counter': lambda c: [CounterSpell(c.window.id)],
        'm4.spellbender': lambda c: [SummonSpellTarget(c.window.id, c.player_id, 'tt_010a')],
        'm4.explosive': lambda c: [DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.SPELL)
            for i in (c.state.players[3-c.player_id].hero_id, *c.state.players[3-c.player_id].board)
            if c.state.entities[i].is_character and c.state.entities[i].active))],
        'm4.freezing_trap': lambda c: [ReturnToHand(c.window.source_id, to_owner=True, cost=CostSpec(delta=2))],
        'm4.noble': lambda c: [SummonAttackTarget(c.window.id, c.player_id, 'EX1_130a')],
        'm4.barrier': lambda c: [GainArmor(c.player_id, 8)],
        'm4.mirror': lambda c: [CopyMinion(c.event.source_id, c.player_id)],
        'm4.dawngrasp': lambda c: [AddPlayerEffect(c.player_id, 'm4.dawngrasp', c.source_id)],
        'm4.bridge': lambda c: [Buff(c.event.target_id, attack=2, health=2, source_id=c.source_id)]
            if c.event.player_id == c.player_id else [],
        'm4.sigil_flame': lambda c: [DamageBatch(tuple(Damage(i, 3, c.source_id, DamageKind.SPELL)
            for p in c.state.players.values() for i in p.board
            if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active))],
        'm4.quest_increment': quest_increment,
        'm4.vault_reward': lambda c: [ReplaceHeroPower(c.player_id, 'ULD_155p')],
        'm4.warmask': lambda c: [Buff(i, attack=2, source_id=c.source_id)
                                for i in c.state.players[c.player_id].board
                                if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active],
        'm4.park_armor': lambda c: [GainArmor(c.player_id, 5)],
        'm4.park_draw': lambda c: [GainArmor(c.player_id, 5), Draw(c.player_id)],
        'm4.park_guff': lambda c: [AddToHand(c.player_id, 'SW_428t4', revealed_to=(1, 2))],
        'm4.guff': lambda c: [Buff(c.state.players[c.player_id].hero_id, attack=8,
                                  source_id=c.source_id, expires_turn=c.state.turn), GainArmor(c.player_id, 8)],
        'm4.righteous': lambda c: [Buff(i, attack=1, health=1, source_id=c.source_id)
                                  for i in c.state.players[c.player_id].board
                                  if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active],
        'm4.eonar_growth': lambda c: [DrawToHandLimit(c.player_id)],
        'm4.eonar_harvest': lambda c: [Heal(c.state.players[c.player_id].hero_id,
            c.state.entities[c.state.players[c.player_id].hero_id].max_health, c.source_id)],
        'm4.eonar_flourish': lambda c: [RefreshMana(c.player_id, c.state.players[c.player_id].mana_cap)],
        'm4.eonar_ancient': lambda c: [card_summon(c,c.player_id, 'TTN_903t4')]
            if c.event.source_id == c.source_id else [],
        'm4.maiev': lambda c: [MakeDormant(c.target_id, 2, c.source_id)] if c.target_id is not None else [],
        'm4.observer': lambda c: [DamageBatch(tuple(Damage(i, 2, c.source_id)
            for i in c.state.players[3-c.player_id].board
            if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active))],
        'm4.raynor': lambda c: [RelaunchStarships(c.player_id)],
        'm4.stimpack': lambda c: [card_summon(c,c.player_id, 'SC_403t'),
            InvokeBehavior('m4.stimpack_buff', c.source_id, c.player_id)],
        'm4.stimpack_buff': lambda c: [Buff(i, attack=2, source_id=c.source_id)
            for i in c.state.players[c.player_id].board
            if (e := c.state.entities[i]).kind == CardType.MINION and e.active
            and (meta := registry.card(e.card_id).metadata) is not None and 'terran' in meta.factions],
        'm4.exodar': _exodar,
        'm4.exodar_protocols': _exodar_protocols,
        'm4.launch_discount': _launch_discount,
        'm4.viking': lambda c: [GainArmor(c.player_id, 5)],
        'm4.raven': lambda c: [GrantRandomBonusEffects(c.source_id, 2, c.source_id)],
        'm4.starport': lambda c: [SummonFromCandidates(c.player_id, TERRAN_LAUNCH_PIECES, c.source_id)],
        'm4.sanguine_depths': lambda c: [Damage(c.target_id, 1, c.source_id), Buff(c.target_id, attack=2, source_id=c.source_id)],
        'm4.lift_off': lambda c: [DrawMatching(c.player_id, PoolQuery(factions_any=('terran',)),
            empty_deck='skip', count=2, source_id=c.source_id),
            SummonFromCandidates(c.player_id, TERRAN_LAUNCH_PIECES, c.source_id)],
        'm4.liberator': lambda c: _enemy_damage(c, 2),
        'm4.banshee': lambda c: [RandomDamage((c.state.players[3-c.player_id].hero_id,
            *c.state.players[3-c.player_id].board), 3, c.source_id)],
        'm4.medivac': _marines,
        'm4.salvage_bunker': lambda c: [*_marines(c), *_launch_discount(c)],
        'm4.supercapacitor': _supercapacitor,
        'm4.yamato': lambda c: [RandomDestroy(tuple(c.state.players[3-c.player_id].board), c.source_id)],
        'm4.lock_on': lambda c: [SetStats(c.target_id, health=1, source_id=c.source_id), *_launch_discount(c)],
        'm4.missile_pod': lambda c: _enemy_damage(c, 1, include_hero=True),
        'm4.concussive_shells': lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),
            GainArmor(c.player_id, 2), *_launch_discount(c)],
        'm4.displacer': lambda c: [CopyMinion(c.source_id, c.player_id)],
        'm4.arkonite': lambda c: [GainArmor(c.player_id, 4)],
        'm4.biopod': _biopod,
        'm3.heavy_plate': lambda c: [GainArmor(c.player_id, 8)],
        'm3.giant_reforge': lambda c: [ModifyCost(c.source_id, CostSpec(delta=-2), source_id=c.source_id)],
        'm3.shadow_visions': lambda c: [ChooseFromZone(c.player_id, c.player_id, Zone.DECK,
            PoolQuery(kinds=(CardType.SPELL,)), operation='copy_current', source_id=c.source_id, prompt='暗影视界：发现法术的复制',discovery=True)],
        'm3.dead_mans_hand': lambda c: shuffled(c,(CopyCard(CardReference.capture(c.state.entities[i]), c.player_id,
            destination=Zone.DECK, source_id=c.source_id) for i in c.state.players[c.player_id].hand)),
        'm3.soulfire': lambda c: [Damage(c.target_id, 4, c.source_id, DamageKind.SPELL),
            DiscardMatching(c.player_id, source_id=c.source_id)],
        'm3.jeweled_scarab': lambda c: [DiscoverFromPool(c.player_id, GENERATION_POOL_ID,
            PoolQuery(min_cost=3, max_cost=3, collectible=True, class_mode='current', exclude_source=True),
            source_id=c.source_id, prompt='宝石甲虫：发现一张三费牌')],
        'm2.healing_touch': lambda c: [Heal(c.target_id, 8, c.source_id, HealingKind.SPELL)],
        'm2.earthen_ring': lambda c: [] if c.target_id is None else [Heal(c.target_id, 3, c.source_id)],
        'm2.holy_nova': lambda c: [DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.SPELL)
                                                    for i in c.state.players[3 - c.player_id].board)),
                                  HealBatch(tuple(Heal(i, 2, c.source_id, HealingKind.SPELL)
                                                  for i in (c.state.players[c.player_id].hero_id,
                                                            *c.state.players[c.player_id].board)))],
        'm2.temporary_mana': lambda c: [GainTemporaryMana(c.player_id, 1)],
        'm2.preparation': lambda c: [AddCostModifier(c.player_id, CostSpec(delta=-2, card_types=(CardType.SPELL,)),
                                                    1, c.source_id, c.state.turn)],
        'm2.lightning_bolt': lambda c: [Overload(c.player_id, 1), Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)],
        'm2.vampiric_blood': lambda c: [Buff(c.state.players[c.player_id].hero_id, health=5, source_id=c.source_id),
            SpendResource(c.player_id, Resource.CORPSES, 3,
                          on_success=(Buff(c.state.players[c.player_id].hero_id, health=5, source_id=c.source_id),
                                      Draw(c.player_id)))],
        "m1.fireball": lambda ctx: [Damage(ctx.target_id, 6, ctx.source_id, DamageKind.SPELL)],
        "m2.frostbolt": lambda ctx: [Damage(ctx.target_id, 3, ctx.source_id, DamageKind.SPELL), Freeze(ctx.target_id, ctx.source_id)],
        "m1.mark": lambda ctx: [Buff(ctx.target_id, 2, 3, ctx.source_id),
                                 GrantKeyword(ctx.target_id, Keyword.TAUNT, ctx.source_id)],
        "m1.silence": lambda ctx: [] if ctx.target_id is None else [Silence(ctx.target_id)],
        "m1.sap": lambda ctx: [ReturnToHand(ctx.target_id)],
        "m1.loot": lambda ctx: [Draw(ctx.player_id)],
        "m1.egg": _egg_hatch,
        "m1.khartut": lambda ctx: [Heal(ctx.state.players[ctx.player_id].hero_id, 3, ctx.source_id)],
        "m1.sergeant": lambda ctx: [] if ctx.target_id is None else [Buff(ctx.target_id, attack=2, source_id=ctx.source_id,
                                         expires_turn=ctx.state.turn)],
        "m1.cleric": lambda ctx: [] if ctx.target_id is None else [Buff(ctx.target_id, 1, 1, ctx.source_id)],
        "m2.inner_fire": lambda ctx: [SetStats(ctx.target_id, attack=StatReference.HEALTH, source_id=ctx.source_id)],
        "m2.divine_spirit": lambda ctx: [DoubleStats(ctx.target_id, health=True, source_id=ctx.source_id)],
        "m2.alchemist": lambda ctx: [] if ctx.target_id is None else [SwapStats(ctx.target_id, ctx.source_id)],
        "m2.deaths_bite": lambda c: [DamageBatch(tuple(Damage(i, 1, c.source_id)
                                   for p in c.state.players.values() for i in p.board))],
        "m2.fireblast": lambda c: [Damage(c.target_id, 1, c.source_id, DamageKind.HERO_POWER)],
        "m2.dagger": lambda c: [EquipWeapon(c.player_id, 'CS2_082')],
        "m2.armor_up": lambda c: [GainArmor(c.player_id, 2)],
        "m2.reinforce": lambda c: [card_summon(c,c.player_id, 'CS2_101t')],
        "m2.shapeshift": lambda c: [Buff(c.state.players[c.player_id].hero_id, attack=1,
                                         source_id=c.source_id, expires_turn=c.state.turn), GainArmor(c.player_id, 1)],
    }
    for behavior_id, handler in behaviors.items():
        registry.register_behavior(behavior_id, handler)
    registry.register_card(CardDefinition("test.hero", "M1测试英雄", CardType.HERO, health=30))
    registry.register_player_effect(PlayerEffectSpec('m5.sandfury_aura', 'CATA_480', 'objective', 3, 'turn_ended',
        end_turn_repeats=(EndTurnRepeatSpec(2, 'minion'),)))
    registry.register_player_effect(PlayerEffectSpec('m5.snowfall_graveyard', 'AV_400', 'objective', 3, 'turn_ended',
        deathrattle_repeats=(DeathrattleRepeatSpec(kinds=(CardType.MINION,CardType.WEAPON,CardType.LOCATION)),)))
    registry.register_player_effect(PlayerEffectSpec('m4.dawngrasp', 'SW_450t4', spell_damage=3))
    registry.register_player_effect(PlayerEffectSpec('m4.bridge', 'AV_344', 'objective', 3, 'turn_ended',
        triggers=(TriggerSpec('minion_summoned', 'm4.bridge'),)))
    registry.register_player_effect(PlayerEffectSpec('m4.sigil_flame', 'BAR_306', 'sigil', 1, 'turn_started',
        on_expire='m4.sigil_flame'))

    def definition(card_id, kind, **behavior):
        raw = snapshots[card_id]["data"]
        if raw["type"] != kind.value.upper():
            raise TargetValidationError(f"unexpected representative card type: {card_id}")
        # These absent tags have individually reviewed zero defaults; no blanket
        # null -> zero conversion for arbitrary future records.
        cost = 0 if card_id in ("EX1_332", "GAME_005", "EX1_169", "EX1_145", "HERO_08", "HERO_01", "HERO_03", "HERO_06", "HERO_11", "HERO_09", "HERO_04", "HERO_02", "HERO_05", "END_003p", "EDR_851t", "REV_957t", "JAM_017") else raw["cost"]
        if card_id in ('GDB_100a', 'GDB_100b', 'GDB_100c', 'TTN_903t', 'TTN_903t2', 'TTN_903t3', 'SW_428t', 'SW_428t2',
                       'CATA_190t10', 'CATA_190t11', 'CATA_190t12', 'CATA_190t13', 'TSC_032t', 'TSC_032t2'):
            cost = 0  # Hidden cost on an option descriptor, never a playable card.
            behavior['choice_only'] = True
        attack = (0 if card_id in ("FP1_007", 'CATA_565', 'TRL_092') else raw["attack"]) if kind in (CardType.MINION, CardType.WEAPON) else 0
        health = raw["health"] if kind in (CardType.MINION, CardType.HERO) else 0
        if card_id in starship_ids:
            # Hidden body tags are placeholders. The instance supplies stats;
            # the prototype uses 5 as its replayable card cost (R-031).
            cost, attack, health = 5, 0, 0
            behavior['starship_for'] = metadata_from_record(raw).classes
        # The client's weapon HEALTH tag is durability, never character health.
        durability = raw['health'] if kind in (CardType.WEAPON, CardType.LOCATION) else 0
        schools = {1: SpellSchool.ARCANE, 2: SpellSchool.FIRE, 3: SpellSchool.FROST, 4: SpellSchool.NATURE,
                   5: SpellSchool.HOLY, 6: SpellSchool.SHADOW, 7: SpellSchool.FEL}
        school_tag = raw['tags'].get('SPELL_SCHOOL')
        if school_tag is not None and (type(school_tag) is not int or school_tag not in schools):
            raise TargetValidationError(f'Unsupported spell school tag: {card_id}')
        meta = decode_metadata(raw)
        if card_id in overrides:
            meta=overrides[card_id];used_metadata.add(card_id)
        return CardDefinition(card_id, raw["name"], kind, cost=cost, attack=attack, health=health,
                              durability=durability, spell_school=schools[school_tag] if school_tag is not None else None,
                              metadata=meta,
                              **behavior)

    minion, spell = CardType.MINION, CardType.SPELL
    battlecry_target = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,))
    cards = (
        definition('RLK_541', minion, spell_repeats=(SpellRepeatSpec(
            casts=2, class_mode='any', match=RepeatMatchSpec(RecipientMetadataFilter(
                spell_schools=(SpellSchool.ARCANE,)))),)),
        definition('TIME_064', minion,
            battlecry_repeats=(BattlecryRepeatSpec(2, (CardType.MINION, CardType.WEAPON, CardType.HERO)),),
            deathrattle_repeats=(DeathrattleRepeatSpec(2,
                (CardType.MINION, CardType.WEAPON, CardType.LOCATION), 'friendly', ('printed', 'granted')),),
            hero_power_repeats=(HeroPowerRepeatSpec(2),),
            end_turn_repeats=(EndTurnRepeatSpec(2, 'all'),)),
        definition('CATA_472', CardType.WEAPON, deathrattle='m5.inspiring_maul'),
        definition('ICC_901', minion, end_turn_repeats=(EndTurnRepeatSpec(2, 'all'),)),
        definition('CATA_480', spell, ongoing_effect_id='m5.sandfury_aura'),
        definition('JAIL_123',minion,battlecry='m5.breakout_architect'),
        definition('CS2_028',spell,on_play='m5.blizzard'),
        definition('CS2_032',spell,on_play='m5.flamestrike'),
        definition('EX1_279',spell,on_play='m5.pyroblast',requires_target=True),
        definition('BOT_411',minion,battlecry='m5.electra'),
        definition('EDR_464',minion,battlecry='m5.tyrande'),
        definition('TSC_071',minion,battlecry='m5.twinbow',hand_progress=HandProgressSpec('spell_cast')),
        definition('TRL_092',minion,keywords=(Keyword.STEALTH,),timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),),
            battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),),combo_repeats=(ComboRepeatSpec(),)),
        definition('GDB_873',spell,on_play='m5.lucky_comet'),
        definition('EX1_131',minion,keywords=(Keyword.COMBO,),combo='m5.defias_ringleader'),
        definition('EX1_131t',minion),
        definition('GIL_820',minion,battlecry='m5.shudderwock'),
        definition('DEEP_020',minion,battlecry='m5.deepminer_brann'),
        definition('SW_115',minion,triggers=(TriggerSpec('card_played','m5.bolner'),)),
        definition('DED_509',minion,battlecry='m5.brilliant_macaw'),
        definition('TID_710',minion,battlecry='m5.snapdragon'),
        definition('FP1_017',minion,cost_auras=(CostAuraSpec(CostSpec(delta=2,card_types=(minion,),ability=CardAbilityCondition()),'any'),)),
        definition('TSC_032',minion,battlecry='m5.okani'),
        definition('TSC_032t',spell),
        definition('TSC_032t2',spell),
        definition('LOOT_517',minion,battlecry='m5.murmuring_elemental'),
        definition('ULD_291p',CardType.HERO_POWER,on_use='m5.heart_of_virnaal'),
        definition('RLK_912',minion,deathrattle_repeats=(DeathrattleRepeatSpec(scope='self',origins=('granted',)),)),
        definition('EX1_158',spell,on_play='m5.soul_forest'),
        definition('EX1_158t',minion),
        definition('JAM_005',minion,battlecry='m5.yodeler',
            targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(minion,),relation='friendly')),
        definition('FP1_031',minion,deathrattle_repeats=(DeathrattleRepeatSpec(),)),
        definition('TOY_528',minion,hero_power_repeats=(HeroPowerRepeatSpec(),)),
        definition('LOE_077',minion,battlecry_repeats=(BattlecryRepeatSpec(),)),
        definition('OG_044',minion,choose_both=True),
        definition('EX1_178',minion,choose_one=ChooseOneSpec((
            ChooseBranch('attack','+5攻击力','m5.war_attack'),ChooseBranch('health','+5生命值和嘲讽','m5.war_health')),
            ChooseBranch('both','+5/+5和嘲讽','m5.war_both'))),
        definition('EX1_154',spell,choose_one=ChooseOneSpec((
            ChooseBranch('damage','造成3点伤害','m5.wrath_damage',TargetSpec(kinds=(CardType.MINION,))),
            ChooseBranch('draw','造成1点伤害并抽牌','m5.wrath_draw',TargetSpec(kinds=(CardType.MINION,)))),
            ChooseBranch('both','依次伤害并抽牌','m5.wrath_both',TargetSpec(kinds=(CardType.MINION,))))),
        definition('AT_082',minion,triggers=(TriggerSpec('hero_power_used','m5.lowly_squire'),)),
        definition('AT_066',minion,triggers=(TriggerSpec('hero_power_used','m5.orgrimmar_aspirant'),)),
        definition('AV_143',minion,deathrattle='m5.korrak'),
        definition('TRL_506',minion,triggers=(TriggerSpec('health_resolved','m5.gurubashi_chicken'),)),
        definition('AV_121',minion,triggers=(TriggerSpec('health_resolved','m5.gnome_private'),)),
        definition('AT_011',minion,triggers=(TriggerSpec('health_resolved','m5.holy_champion'),)),
        definition('EDR_519',minion,battlecry='m5.wisprider'),
        definition('EDR_852',minion,battlecry='m5.imbue'),
        definition('EDR_451',minion,battlecry='m5.imbue',deathrattle='m5.imbue'),
        definition('EDR_847p',CardType.HERO_POWER,on_use='m5.blessing_golem',requires_board_space=True),
        definition('EDR_851p',CardType.HERO_POWER,on_use='m5.blessing_wisp'),
        definition('HERO_11',CardType.HERO),
        definition('HERO_05',CardType.HERO),
        definition('HERO_04',CardType.HERO,initial_hero_power='HERO_04bp'),
        definition('HERO_09',CardType.HERO),
        definition('EDR_449p',CardType.HERO_POWER,on_use='m5.blessing_moon'),
        definition('EDR_445p',CardType.HERO_POWER,on_use='m5.blessing_dragon'),
        definition('EDR_445pt3',spell,on_play='m5.emerald_portal',keywords=(Keyword.CASTS_WHEN_DRAWN,),
            cast_when_drawn=CastWhenDrawnSpec()),
        definition('BRM_004',minion,battlecry='m5.twilight_whelp'),
        definition('NEW1_023',minion,keywords=(Keyword.ELUSIVE,)),
        definition('HERO_02',CardType.HERO),
        definition('EDR_850p',CardType.HERO_POWER,on_use='m5.blessing_wolf'),
        definition('EDR_448p',CardType.HERO_POWER,on_use='m5.blessing_wind',
            targeting=TargetSpec(TargetMode.REQUIRED,kinds=(minion,),relation='friendly')),
        definition('END_003p',CardType.HERO_POWER,passive_hero_power=True,
            triggers=(TriggerSpec('minion_play_accepted','m5.blessing_infinite'),)),
        definition('END_000p',CardType.HERO_POWER,on_use='m5.blessing_bronze',
            keywords=(Keyword.REWIND,),rewind=RewindSpec()),
        definition('EDR_847pt2',minion),
        definition('EDR_851t',minion),
        definition('HERO_06',CardType.HERO,initial_hero_power='HERO_06bp'),
        definition('WW_001t25', minion, battlecry='m5.azerite_snake'),
        definition('DEEP_999t4', minion, battlecry='m5.azerite_dragon'),
        definition('DEEP_999t5', minion, battlecry='m5.azerite_murloc'),
        definition('WW_001t24', minion, battlecry='m5.azerite_hawk'),
        definition('WW_001t27', minion, battlecry='m5.azerite_ox'),
        definition('WW_001t26', minion, battlecry='m5.azerite_rat'),
        definition('WW_001', minion, battlecry='m5.excavate'),
        definition('WW_001t18', spell, on_play='m5.pouch'),
        definition('WW_001t5', spell, on_play='m5.stalactite', requires_target=True, target_rule='m1.minion'),
        definition('WW_001t17', minion, keywords=(Keyword.RUSH,Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL)),
        definition('WW_001t23', minion, battlecry='m5.azerite_scorpion'),
        definition('TID_700', minion, battlecry='m5.dredge.TID_700'),
        definition('TID_703', spell, on_play='m5.dredge.TID_703'),
        definition('TID_099', minion, battlecry='m5.dredge.TID_099'),
        definition('TID_003', minion, battlecry='m5.dredge.TID_003'),
        definition('END_036', minion, retain_rewind_outcomes=True, battlecry='m5.morchie'),
        definition('TIME_000', spell, keywords=(Keyword.REWIND,), rewind=RewindSpec(), on_play='m5.semi_stable_portal'),
        definition('TIME_EVENT_999', spell, keywords=(Keyword.REWIND,), rewind=RewindSpec(), on_play='m5.sands_of_time'),
        definition('CATA_155', minion, keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec('CATA_155t', 'left'), AppendageSpec('CATA_155t1')),
            health_loss_replacements=(HealthLossReplacementSpec(),)),
        definition('CATA_154', minion, keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec('CATA_154t', 'left'), AppendageSpec('CATA_154t1')),
            spell_repeats=(SpellRepeatSpec(),)),
        definition('CATA_153', minion, keywords=(Keyword.COLOSSAL, Keyword.RUSH, Keyword.WINDFURY),
            colossal=(AppendageSpec('CATA_153t', 'left'), AppendageSpec('CATA_153t1')),
            battlecry='m5.alakir'),
        definition('OG_141', minion),
        definition('CATA_151', minion, keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec('CATA_151t', 'left'), AppendageSpec('CATA_151t1')),
            keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY),)),
        definition('CATA_726', minion, keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec('CATA_726t', 'left'), AppendageSpec('CATA_726t1')),
            deck_sacrifice=DeckSacrificeSpec(('CATA_725t', 'CATA_726t', 'CATA_726t1'))),
        definition('CATA_190h', CardType.HERO, hero_card=True, hero_armor=12, keep_hero_class=True,
                   initial_hero_power='CATA_190p', battlecry='m5.deathwing'),
        definition('CATA_190p', CardType.HERO_POWER, on_use='m5.ruthless'),
        definition('CATA_190t10', spell), definition('CATA_190t11', spell),
        definition('CATA_190t12', spell), definition('CATA_190t13', spell),
        definition('CATA_190t14', minion),
        definition('CATA_497', minion, keywords=(Keyword.HERALD,), battlecry='m5.ultraxion'),
        definition('EX1_563', minion, spell_damage=5),
        definition('CATA_725', minion, keywords=(Keyword.HERALD,), battlecry='m5.herald', deathrattle='m5.shadowsworn_heal'),
        definition('CATA_725t', minion, herald_scaling=True, herald_soldier_for=CardClass.WARLOCK,
            triggers=(TriggerSpec('turn_ended', 'm5.chogall_soldier',EndTurnSpec()),)),
        definition('CATA_726t', minion, herald_scaling=True,
            triggers=(TriggerSpec('turn_ended', 'm5.chogall_soldier',EndTurnSpec()),)),
        definition('CATA_726t1', minion, herald_scaling=True,
            triggers=(TriggerSpec('turn_ended', 'm5.chogall_soldier',EndTurnSpec()),)),
        definition('CATA_565', minion, keywords=(Keyword.TAUNT, Keyword.HERALD), battlecry='m5.herald'),
        definition('CATA_565t', minion, herald_scaling=True, herald_soldier_for=CardClass.SHAMAN,
            auras=(AuraSpec(1, adjacent_only=True),)),
        definition('CATA_153t', minion, herald_scaling=True, auras=(AuraSpec(1, adjacent_only=True),)),
        definition('CATA_153t1', minion, herald_scaling=True, auras=(AuraSpec(1, adjacent_only=True),)),
        definition('CATA_158', minion, keywords=(Keyword.STEALTH, Keyword.HERALD), deathrattle='m5.herald'),
        definition('CATA_158t', minion, herald_scaling=True, herald_soldier_for=CardClass.ROGUE,
            triggers=(TriggerSpec('minion_summoned', 'm5.sinestra_soldier'),)),
        definition('CATA_154t', minion, herald_scaling=True,
            triggers=(TriggerSpec('minion_summoned', 'm5.sinestra_soldier'),)),
        definition('CATA_154t1', minion, herald_scaling=True,
            triggers=(TriggerSpec('minion_summoned', 'm5.sinestra_soldier'),)),
        definition('CATA_780', minion, keywords=(Keyword.LIFESTEAL, Keyword.HERALD), battlecry='m5.herald'),
        definition('CATA_780t', minion, herald_scaling=True, herald_soldier_for=CardClass.DEATH_KNIGHT,
            triggers=(TriggerSpec('minion_summoned', 'm5.onyxia_soldier'),)),
        definition('CATA_155t', minion, herald_scaling=True,
            triggers=(TriggerSpec('minion_summoned', 'm5.onyxia_soldier'),)),
        definition('CATA_155t1', minion, herald_scaling=True,
            triggers=(TriggerSpec('minion_summoned', 'm5.onyxia_soldier'),)),
        definition('CATA_150',minion,keywords=(Keyword.COLOSSAL,),
            colossal=(AppendageSpec('CATA_150t','left'),AppendageSpec('CATA_150t1')),
            triggers=(TriggerSpec('turn_ended','m5.ragnaros_end',EndTurnSpec()),)),
        definition('CATA_150t',minion,herald_scaling=True,deathrattle='m5.ragnaros_hand'),
        definition('CATA_150t1',minion,herald_scaling=True,deathrattle='m5.ragnaros_hand'),
        definition('CATA_580t',minion,herald_scaling=True,herald_soldier_for=CardClass.WARRIOR,deathrattle='m5.ragnaros_hand'),
        definition('CATA_160',minion,keywords=(Keyword.HERALD,),battlecry='m5.ravager'),
        definition('CATA_580',CardType.WEAPON,keywords=(Keyword.HERALD,),battlecry='m5.herald'),
        definition('CATA_722',minion,keywords=(Keyword.TAUNT,Keyword.HERALD),battlecry='m5.herald'),
        definition('CATA_525',minion,keywords=(Keyword.RUSH,Keyword.HERALD),battlecry='m5.herald'),
        definition('CATA_525t',minion,herald_scaling=True,herald_soldier_for=CardClass.DEMON_HUNTER,
            triggers=(TriggerSpec('minion_summoned','m5.azshara_soldier'),)),
        definition('CATA_530',spell,keywords=(Keyword.HERALD,),on_play='m5.fel_infusion'),
        definition('CATA_151t',minion,herald_scaling=True,triggers=(TriggerSpec('minion_summoned','m5.azshara_soldier'),)),
        definition('CATA_151t1',minion,herald_scaling=True,triggers=(TriggerSpec('minion_summoned','m5.azshara_soldier'),)),
        definition('TSC_216',minion,colossal=(AppendageSpec('TSC_216t','left'),),keywords=(Keyword.COLOSSAL,Keyword.LIFESTEAL)),
        definition('TSC_216t',minion,triggers=(TriggerSpec('turn_ended','m5.lure',EndTurnSpec()),)),
        definition('TSC_639',minion,colossal=(AppendageSpec('TSC_639t','right'),AppendageSpec('TSC_639t2','right'),AppendageSpec('TSC_639t3','right'),),keywords=(Keyword.COLOSSAL,),triggers=(TriggerSpec('minion_died','m5.glugg'),)),
        definition('TSC_639t',minion,keywords=(Keyword.TAUNT,)),
        definition('TSC_639t2',minion,keywords=(Keyword.TAUNT,)),
        definition('TSC_639t3',minion,keywords=(Keyword.TAUNT,)),
        definition('TID_711',minion,colossal=(AppendageSpec('TID_711t','right'),AppendageSpec('TID_711t2','right'),AppendageSpec('TID_711t3','right'),AppendageSpec('TID_711t4','right'),AppendageSpec('TID_711t5','right'),AppendageSpec('TID_711t6','right'),),keywords=(Keyword.COLOSSAL,),deathrattle='m5.ozumat'),
        definition('TID_711t',minion),
        definition('TID_711t2',minion),
        definition('TID_711t3',minion),
        definition('TID_711t4',minion),
        definition('TID_711t5',minion),
        definition('TID_711t6',minion),
        definition('BOT_563',minion,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',)),
        definition('BOT_911',minion,keywords=(Keyword.MAGNETIC,Keyword.DIVINE_SHIELD,Keyword.TAUNT),magnetic_tribes=('mech',)),
        definition('BOT_035',minion,keywords=(Keyword.MAGNETIC,Keyword.POISONOUS),magnetic_tribes=('mech',)),
        definition('BOT_548',minion,keywords=(Keyword.MAGNETIC,Keyword.DIVINE_SHIELD,Keyword.TAUNT,Keyword.LIFESTEAL,Keyword.RUSH),magnetic_tribes=('mech',)),
        definition('BOT_251',minion,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),deathrattle='m5.spider_bomb'),
        definition('BOT_107',minion,keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',),triggers=(TriggerSpec('turn_ended','m5.missile_launcher',EndTurnSpec()),)),
        definition('DEEP_015',minion,keywords=(Keyword.MAGNETIC,Keyword.REBORN),magnetic_tribes=('mech','undead')),
        definition('TTN_087',minion,keywords=(Keyword.MAGNETIC,Keyword.RUSH),magnetic_tribes=('mech','beast')),
        definition('ETC_325',minion,on_play='m5.audio_medic',keywords=(Keyword.RUSH,Keyword.FINALE)),
        definition('JAM_017',spell,on_play='m5.through_fel',keywords=(Keyword.FINALE,),targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))),
        definition('RLK_843',spell,on_play='m5.arcane_bolt',keywords=(Keyword.MANATHIRST,),manathirst=8,requires_target=True),
        definition('RLK_518',minion,on_play='m5.silvermoon',keywords=(Keyword.TAUNT,Keyword.MANATHIRST),manathirst=8),
        definition('WW_434',minion,on_play='m5.sunspot',keywords=(Keyword.LIFESTEAL,Keyword.QUICKDRAW),target_condition='quickdraw',targeting=TargetSpec(TargetMode.IF_AVAILABLE),hand_actions=(HandActionSpec('trade','trade',1),)),
        definition('WW_823',spell,on_play='m5.rehydrate',keywords=(Keyword.QUICKDRAW,),requires_target=True),
        definition('DMF_073',minion,keywords=(Keyword.DIVINE_SHIELD,Keyword.CORRUPT),hand_progress=HandProgressSpec('corrupt',upgrade_card_id='DMF_073t')),
        definition('DMF_073t',minion,keywords=(Keyword.DIVINE_SHIELD,Keyword.RUSH,Keyword.CORRUPTED)),
        definition('DMF_124',minion,keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id='DMF_124t')),
        definition('DMF_124t',minion,keywords=(Keyword.CORRUPTED,Keyword.CORRUPT),hand_progress=HandProgressSpec('corrupt',repeat=True,on_complete='m5.growth')),
        definition('DMF_248',minion,keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id='DMF_248t',health_to_durability=True)),
        definition('DMF_248t',CardType.WEAPON,keywords=(Keyword.CORRUPTED,)),
        definition('REV_019',minion,battlecry='m5.fool',keywords=(Keyword.INFUSE,),hand_progress=HandProgressSpec('infuse',4,'REV_019t')),
        definition('REV_019t',minion,battlecry='m5.fool_infused',keywords=(Keyword.INFUSED,)),
        definition('REV_601',spell,on_play='m5.touch',requires_target=True,keywords=(Keyword.INFUSE,),hand_progress=HandProgressSpec('infuse',3,'REV_601t')),
        definition('REV_601t',spell,on_play='m5.touch_infused',requires_target=True,keywords=(Keyword.INFUSED,)),
        definition('REV_956',minion,keywords=(Keyword.TAUNT,Keyword.INFUSE),hand_progress=HandProgressSpec('infuse',3,'REV_956t')),
        definition('REV_956t',minion,keywords=(Keyword.TAUNT,Keyword.INFUSED)),
        definition('REV_957',minion,keywords=(Keyword.LIFESTEAL,Keyword.INFUSE),hand_progress=HandProgressSpec('infuse',4,'REV_957t')),
        definition('REV_957t',minion,keywords=(Keyword.LIFESTEAL,Keyword.INFUSED)),
        definition('SCH_231',minion,keywords=(Keyword.SPELLBURST,),limited_triggers=(LimitedTriggerSpec.spellburst('m5.initiate'),)),
        definition('SCH_242',minion,keywords=(Keyword.SPELLBURST,),limited_triggers=(LimitedTriggerSpec.spellburst('m5.gibberling'),)),
        definition('SCH_248',minion,keywords=(Keyword.SPELLBURST,),battlecry='m5.flinger_play',
            targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,)),
            limited_triggers=(LimitedTriggerSpec.spellburst('m5.flinger_burst'),)),
        definition('SCH_182',minion,keywords=(Keyword.RUSH,Keyword.WINDFURY,Keyword.SPELLBURST,),limited_triggers=(LimitedTriggerSpec.spellburst('m5.gidra'),)),
        definition('BAR_024',minion,keywords=(Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy('m5.thrasher'),)),
        definition('BAR_025',minion,keywords=(Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy('m5.sunwell'),)),
        definition('BAR_021',minion,keywords=(Keyword.TAUNT,Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy('m5.grunt'),)),
        definition('BAR_078',minion,keywords=(Keyword.RUSH,Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy('m5.samuro'),)),
        definition('EX1_124',spell,keywords=(Keyword.COMBO,),on_play='m5.eviscerate',requires_target=True),
        definition('EX1_134',minion,keywords=(Keyword.COMBO,),combo='m5.si7',target_condition='combo',targeting=TargetSpec(TargetMode.IF_AVAILABLE)),
        definition('EX1_613',minion,keywords=(Keyword.COMBO,),combo='m5.edwin'),
        definition('BT_480',minion,keywords=(Keyword.OUTCAST,),on_play='m5.runner'),
        definition('BT_490',spell,keywords=(Keyword.OUTCAST,),on_play='m5.consume',requires_target=True,target_rule='m1.enemy_minion'),
        definition('BT_491',spell,keywords=(Keyword.OUTCAST,),on_play='m5.sight'),
        *(definition(card, spell, keywords=(Keyword.SECRET,), secret=SecretSpec(card, (event,), condition, behavior,
            requires_board_space=space)) for card, event, condition, behavior, space in (
                ('MAW_006', 'minion_counter_check', 'm5.minion_counter', 'm5.minion_counter', False),
                ('EX1_287', 'card_committed', 'm4.counter', 'm4.counter', False),
                ('tt_010', 'spell_targeted', 'm4.spell_minion', 'm4.spellbender', True),
                ('EX1_610', 'attack_declared', 'm4.hero_attacked', 'm4.explosive', False),
                ('EX1_611', 'attack_declared', 'm4.minion_attack', 'm4.freezing_trap', False),
                ('EX1_130', 'attack_declared', 'm4.enemy_attack', 'm4.noble', True),
                ('EX1_289', 'attack_declared', 'm4.hero_attacked', 'm4.barrier', False),
                ('EX1_294', 'card_played', 'm4.minion_played', 'm4.mirror', True))),
        definition('EX1_130a', minion),
        definition('tt_010a', minion),
        definition('SW_450t4', minion, battlecry='m4.dawngrasp'),
        definition('AV_400', spell, ongoing_effect_id='m5.snowfall_graveyard'),
        definition('AV_344', spell, ongoing_effect_id='m4.bridge'),
        definition('BAR_306', spell, ongoing_effect_id='m4.sigil_flame'),
        definition('ULD_155', spell, keywords=(Keyword.QUEST,), quest=QuestSpec('quest', (
            QuestStageSpec('ULD_155', 20, ('minion_summoned',), 'm4.quest_increment', 'm4.vault_reward'),))),
        definition('ULD_155p', CardType.HERO_POWER, on_use='m4.warmask'),
        definition('DRG_008', spell, keywords=(Keyword.SIDEQUEST,), quest=QuestSpec('sidequest', (
            QuestStageSpec('DRG_008', 5, ('minion_summoned',), 'm4.quest_increment', 'm4.righteous'),))),
        definition('SW_428', spell, keywords=(Keyword.QUESTLINE,), quest=QuestSpec('questline', tuple(
            QuestStageSpec(card, goal, ('hero_attack_gained',), 'm4.quest_increment', reward)
            for card, goal, reward in (('SW_428', 4, 'm4.park_armor'),
                                      ('SW_428t', 5, 'm4.park_draw'), ('SW_428t2', 6, 'm4.park_guff'))))),
        *(definition(i, spell) for i in ('SW_428t', 'SW_428t2')),
        definition('SW_428t4', minion, keywords=(Keyword.TAUNT,), battlecry='m4.guff'),
        definition('TTN_903', minion, keywords=(Keyword.TITAN,),
            activated_abilities=tuple(ActivatedAbilitySpec(card, behavior, card_id=card) for card, behavior in (
                ('TTN_903t', 'm4.eonar_growth'), ('TTN_903t2', 'm4.eonar_harvest'), ('TTN_903t3', 'm4.eonar_flourish'))),
            triggers=(TriggerSpec('minion_ability_used', 'm4.eonar_ancient'),)),
        *(definition(i, spell) for i in ('TTN_903t', 'TTN_903t2', 'TTN_903t3')),
        definition('TTN_903t4', minion, keywords=(Keyword.TAUNT,)),
        definition('BT_004', minion, dormant_turns=2, on_awaken='m4.observer'),
        definition('BT_156', minion, dormant_turns=2, keywords=(Keyword.RUSH,)),
        definition('TSC_647', minion, dormant_turns=1, keywords=(Keyword.RUSH,)),
        definition('BT_737', minion, battlecry='m4.maiev', targeting=battlecry_target),
        definition('SC_400', CardType.HERO, hero_card=True, hero_armor=5, keep_hero_class=True,
            initial_hero_power='SC_400p', battlecry='m4.raynor'),
        definition('SC_400p', CardType.HERO_POWER, on_use='m4.stimpack'),
        definition('SC_403', CardType.LOCATION, on_use='m4.starport', requires_board_space=True),
        definition('CORE_REV_990', CardType.LOCATION, on_use='m4.sanguine_depths',
            targeting=TargetSpec(TargetMode.REQUIRED, zones=(Zone.BOARD,), kinds=(CardType.MINION,))),
        definition('GDB_120', minion, battlecry='m4.exodar'),
        *(definition(i, spell) for i in ('GDB_100a', 'GDB_100b', 'GDB_100c')),
        definition('SC_401', minion, battlecry='m4.launch_discount'),
        definition('SC_403a', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.viking'),
        definition('SC_403b', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.liberator'),
        definition('SC_403c', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.raven'),
        definition('SC_403d', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.banshee'),
        definition('SC_403f', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.medivac'),
        definition('SC_403t', minion, keywords=(Keyword.TAUNT,)),
        definition('SC_410', spell, on_play='m4.lift_off'),
        definition('SC_404', spell, on_play='m4.salvage_bunker'),
        definition('SC_405', minion, keywords=(Keyword.STARSHIP_PIECE,), battlecry='m4.supercapacitor', on_launch='m4.supercapacitor'),
        definition('SC_406', minion, keywords=(Keyword.STARSHIP_PIECE,), battlecry='m4.yamato', on_launch='m4.yamato'),
        definition('SC_407', spell, on_play='m4.lock_on', targeting=TargetSpec(TargetMode.REQUIRED,
            zones=(Zone.BOARD,), kinds=(CardType.MINION,))),
        definition('SC_409', minion, keywords=(Keyword.STARSHIP_PIECE,), battlecry='m4.missile_pod', on_launch='m4.missile_pod'),
        definition('SC_411', spell, on_play='m4.concussive_shells', requires_target=True),
        definition('GDB_466', minion, keywords=(Keyword.STARSHIP_PIECE,), on_launch='m4.displacer'),
        *(definition(i, minion) for i in starship_ids),
        definition('GDB_100', minion, keywords=(Keyword.STARSHIP_PIECE, Keyword.TAUNT), deathrattle='m4.arkonite'),
        definition('GDB_101', minion, keywords=(Keyword.STARSHIP_PIECE, Keyword.DIVINE_SHIELD)),
        definition('GDB_109', minion, keywords=(Keyword.STARSHIP_PIECE, Keyword.LIFESTEAL)),
        definition('GDB_111', minion, keywords=(Keyword.STARSHIP_PIECE,), deathrattle='m4.biopod'),
        definition('SW_094', spell, on_play='m3.heavy_plate', hand_actions=(HandActionSpec('trade', 'trade', 1),)),
        definition('TTN_042', minion, keywords=(Keyword.RUSH,), hand_actions=(HandActionSpec('forge', 'forge', 2, 'TTN_042t'),)),
        definition('TTN_042t', minion, keywords=(Keyword.RUSH,)),
        definition('TTN_724', minion, keywords=(Keyword.TAUNT,), hand_actions=(HandActionSpec('forge', 'forge', 2, 'TTN_724t'),)),
        definition('TTN_724t', minion, keywords=(Keyword.TAUNT,), hand_actions=(HandActionSpec('forge', 'forge', 2, 'TTN_724t', on_use='m3.giant_reforge'),)),
        definition('UNG_029', spell, on_play='m3.shadow_visions'),
        definition('ICC_091', spell, on_play='m3.dead_mans_hand'),
        definition('EX1_308', spell, on_play='m3.soulfire', requires_target=True),
        definition('LOE_029', minion, battlecry='m3.jeweled_scarab'),
        definition('HERO_08', CardType.HERO, initial_hero_power='HERO_08bp'),
        definition('HERO_03', CardType.HERO, initial_hero_power='HERO_03bp'),
        definition('HERO_01', CardType.HERO, initial_hero_power='HERO_01bp'),
        definition('EX1_164',spell,choose_one=ChooseOneSpec((
            ChooseBranch('mana','获得两个法力水晶','m5.nourish_mana'),ChooseBranch('draw','抽三张牌','m5.nourish_draw')),
            ChooseBranch('both','获得水晶并抽牌','m5.nourish_both'))),
        definition('EX1_350', minion, health_rules=(
            HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, source_relation='friendly',
                       damage_kinds=(DamageKind.SPELL, DamageKind.HERO_POWER)),
            HealthRule(HealthFlow.HEALING, HealthOp.SCALE, 2, source_relation='friendly',
                       healing_kinds=(HealingKind.SPELL, HealingKind.HERO_POWER)))),
        definition('EX1_591', minion, health_rules=(
            HealthRule(HealthFlow.HEALING, HealthOp.CONVERT, source_relation='friendly'),)),
        definition('BT_733', minion, health_rules=(
            HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=HealthLayer.TARGET,
                       target_kinds=(minion,), damage_kinds=(DamageKind.SPELL,)),)),
        definition('AT_124', minion, health_rules=(
            HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                       target_relation='friendly', target_kinds=(CardType.HERO,), redirect_to='self'),)),
        definition('LOE_119', minion, health_rules=(
            HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET,
                       target_relation='friendly', target_kinds=(CardType.HERO,)),)),
        definition('CS2_007', spell, on_play='m2.healing_touch', requires_target=True),
        definition('CS2_117', minion, battlecry='m2.earthen_ring', targeting=TargetSpec(TargetMode.IF_AVAILABLE)),
        definition('CS1_112', spell, on_play='m2.holy_nova'),
        definition('GAME_005', spell, on_play='m2.temporary_mana'),
        definition('EX1_169', spell, on_play='m2.temporary_mana'),
        definition('EX1_145', spell, on_play='m2.preparation'),
        definition('EX1_608', minion, cost_auras=(CostAuraSpec(CostSpec(delta=-1, minimum=1, card_types=(spell,))),)),
        definition('EX1_238', spell, on_play='m2.lightning_bolt', requires_target=True),
        definition('RLK_051', spell, on_play='m2.vampiric_blood'),
        definition("CS2_182", minion),
        definition("CS2_179", minion, keywords=(Keyword.TAUNT,)),
        definition("CS2_029", spell, on_play="m1.fireball", requires_target=True),
        definition("CS2_024", spell, on_play="m2.frostbolt", requires_target=True),
        definition("ICC_820", minion, keywords=(Keyword.CHARGE, Keyword.LIFESTEAL)),
        definition("EX1_010", minion, keywords=(Keyword.STEALTH,)),
        definition("CS2_222", minion, auras=(AuraSpec(1, health=1),)),
        definition("CS1_129", spell, on_play="m2.inner_fire", requires_target=True, target_rule="m1.minion"),
        definition("CS2_236", spell, on_play="m2.divine_spirit", requires_target=True, target_rule="m1.minion"),
        definition("EX1_059", minion, battlecry="m2.alchemist", targeting=battlecry_target, target_rule="m1.minion"),
        definition('CS2_106', CardType.WEAPON),
        definition('CS2_082', CardType.WEAPON),
        definition('FP1_021', CardType.WEAPON, deathrattle='m2.deaths_bite'),
        definition('HERO_08bp', CardType.HERO_POWER, on_use='m2.fireblast', requires_target=True),
        definition('HERO_03bp', CardType.HERO_POWER, on_use='m2.dagger'),
        definition('HERO_01bp', CardType.HERO_POWER, on_use='m2.armor_up'),
        definition('HERO_04bp', CardType.HERO_POWER, on_use='m2.reinforce', requires_board_space=True),
        definition('HERO_06bp', CardType.HERO_POWER, on_use='m2.shapeshift'),
        definition('CS2_101t', minion),
        definition("CS2_009", spell, on_play="m1.mark", requires_target=True, target_rule="m1.minion"),
        definition("EX1_332", spell, on_play="m1.silence", requires_target=True, target_rule="m1.minion"),
        definition("CS2_203", minion, battlecry="m1.silence", targeting=battlecry_target, target_rule="m1.minion"),
        definition("EX1_581", spell, on_play="m1.sap", requires_target=True, target_rule="m1.enemy_minion"),
        definition("EX1_096", minion, deathrattle="m1.loot"),
        definition("EX1_012", minion, spell_damage=1, deathrattle="m1.loot"),
        definition("FP1_007", minion, deathrattle="m1.egg"),
        definition("FP1_007t", minion),
        definition("CS2_122", minion, auras=(AuraSpec(1),)),
        definition("ULD_205", minion, keywords=(Keyword.REBORN,)),
        definition("ULD_208", minion, keywords=(Keyword.TAUNT, Keyword.REBORN), deathrattle="m1.khartut"),
        definition("CS2_188", minion, battlecry="m1.sergeant", targeting=battlecry_target, target_rule="m1.minion"),
        definition("EX1_019", minion, battlecry="m1.cleric", targeting=battlecry_target, target_rule="m1.friendly_minion"),
    )
    for card in cards:
        if card.id in initial_powers:
            if card.kind!=CardType.HERO or card.hero_card or card.initial_hero_power is not None:
                raise TargetValidationError('Only an unbound ordinary starting hero accepts a content binding')
            card=replace(card,initial_hero_power=initial_powers[card.id])
        registry.register_card(card)
    if any(cid not in registry.cards for cid in initial_powers):raise TargetValidationError('Unknown starting hero content binding')
    if any(cid not in registry.cards or registry.card(cid).metadata.rarity != Rarity.NONE for cid in known_unrarified_ids):
        raise TargetValidationError('Known unrarified faces were not completely installed')
    for card_id in dict.fromkeys((*GENERATION_SAMPLE_IDS, *HERALD_POOL_IDS, *DEATHWING_POOL_IDS, *ATTACK_COST_POOL_IDS, *REWIND_SAMPLE_IDS,
                                *EXCAVATE_TITAN_SAMPLE_IDS,*EXCAVATE_EIGHT_SAMPLE_IDS,*EXCAVATE_TRANSFORM_SAMPLE_IDS,*BRONZE_SAMPLE_IDS,*WIND_SAMPLE_IDS,*PORTAL_SAMPLE_IDS,*MOON_SAMPLE_IDS)):
        registry.register_pool_card(PoolCard.from_definition(registry.card(card_id)))
    register_combo_pool(registry, baseline, decode_metadata)
    register_card_spell_pool(registry, baseline, decode_metadata)
    registry.register_pool(PoolDefinition(MOON_POOL_ID,'representative-moon-cards-v1',
        baseline.target['target_id'],'experimental',tuple(PoolMember(i) for i in MOON_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(WIND_POOL_ID,'representative-wind-minions-v1',
        baseline.target['target_id'],'experimental',tuple(PoolMember(i) for i in WIND_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(PORTAL_POOL_ID,'representative-emerald-dragons-v1',
        baseline.target['target_id'],'experimental',tuple(PoolMember(i) for i in PORTAL_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(BRONZE_POOL_ID,'representative-bronze-minions-v1',
        baseline.target['target_id'],'experimental',tuple(PoolMember(i) for i in BRONZE_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(GENERATION_POOL_ID, 'representative-generation-v1',
        baseline.target['target_id'], 'experimental', tuple(PoolMember(i) for i in GENERATION_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(REWIND_POOL_ID, 'representative-rewind-cards-v1',
        baseline.target['target_id'], 'experimental', tuple(PoolMember(i) for i in REWIND_SAMPLE_IDS)))
    registry.register_pool(PoolDefinition(HERALD_POOL_ID, 'representative-herald-generation-v1',
        baseline.target['target_id'], 'experimental', tuple(PoolMember(i) for i in HERALD_POOL_IDS)))
    registry.register_pool(PoolDefinition(DEATHWING_POOL_ID, 'representative-legendary-dragons-v1',
        baseline.target['target_id'], 'experimental', tuple(PoolMember(i) for i in DEATHWING_POOL_IDS)))
    registry.register_pool(PoolDefinition(ATTACK_COST_POOL_ID, 'representative-attack-cost-minions-v1',
        baseline.target['target_id'], 'experimental', tuple(PoolMember(i) for i in ATTACK_COST_POOL_IDS)))
    for pool_id,members in ((EXCAVATE_TITAN_POOL_ID,EXCAVATE_TITAN_SAMPLE_IDS),(EXCAVATE_EIGHT_POOL_ID,EXCAVATE_EIGHT_SAMPLE_IDS),
                            (EXCAVATE_TRANSFORM_POOL_ID,EXCAVATE_TRANSFORM_SAMPLE_IDS)):
        registry.register_pool(PoolDefinition(pool_id,'representative-excavate-rewards-v1',baseline.target['target_id'],
            'experimental',tuple(PoolMember(i) for i in members)))
    inventory=json.loads((Path(__file__).resolve().parents[2]/'data/support/excavation-inventory.json').read_text(encoding='utf-8'))
    if canonical_digest(inventory) != EXCAVATE_INVENTORY_HASH:
        raise TargetValidationError('Excavation inventory differs from its pinned experimental version')
    for card_id in (*EXCAVATE_SHARED_SAMPLE_IDS,*EXCAVATE_CLASS_REWARDS.values()):
        if card_id in registry.pool_cards:continue
        if card_id in registry.cards:
            registry.register_pool_card(PoolCard.from_definition(registry.card(card_id)))
        else:
            raw=inventory['records'][card_id]
            registry.register_pool_card(PoolCard(card_id,CardType(raw['type'].lower()),raw['cost'],decode_metadata(raw),
                deathrattle=raw['tags'].get('DEATHRATTLE')==1,choose_one=raw['tags'].get('CHOOSE_ONE')==1,
                attack=raw['attack']if raw['type']=='MINION'else None))
    for tier,card_id in enumerate(EXCAVATE_SHARED_SAMPLE_IDS,1):
        registry.register_pool(PoolDefinition(f'excavate.tier{tier}','representative-excavate-v1',baseline.target['target_id'],
            'experimental',(PoolMember(card_id),)))
    for cls,card_id in EXCAVATE_CLASS_REWARDS.items():
        registry.register_pool(PoolDefinition(f'excavate.{cls.value}','representative-excavate-v1',baseline.target['target_id'],
            'experimental',(PoolMember(card_id),)))
    registry.register_excavation_profile(ExcavationProfile('excavate','representative-excavate-v1',baseline.target['target_id'],
        'experimental',('excavate.tier1','excavate.tier2','excavate.tier3'),tuple(
            ExcavationClass(cls,f'excavate.{cls.value}' if cls in EXCAVATE_CLASS_REWARDS else None)
            for cls in sorted(PLAYABLE_CLASSES))))
    from .dark_gift_cards import register_representatives as register_dark_gift_cards
    register_dark_gift_cards(registry, baseline.target['target_id'])
    if used_metadata!=set(overrides):raise ValueError('Printed metadata override has no compiled source card')
    if not defer_validation:registry.validate()
    return registry

