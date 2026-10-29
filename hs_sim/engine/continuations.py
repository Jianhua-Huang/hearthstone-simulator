"""An allowlisted, typed JSON codec for suspended interpreter work.

Names identify types already supplied by the host's trusted mechanics. JSON
cannot import modules, look up arbitrary attributes, or carry Python callables.
"""
from dataclasses import fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Union, get_args, get_origin, get_type_hints

from . import actions, effects, model
from .model import CardType, Event, GameState, validate_invariants
from .registry import RuleContext
from .serialization import (event_from_dict, event_to_dict, state_from_dict, state_to_dict,
                            end_turn_rng_from_json, end_turn_rng_to_json)


def type_name(kind):
    return f'{kind.__module__}.{kind.__qualname__}'


def deck_origin(state):
    """Immutable match facts shared by live and earlier captured rule states."""
    return (state.opening is not None,
        None if state.opening is None else state.opening.original_entities,
        None if state.opening is None else state.opening.deck_copies,
        tuple(state.players[p].original_deck for p in (1, 2)),
        tuple(tuple((b.source_card_id, b.cards) for b in state.players[p].sideboards) for p in (1, 2)))


def matches(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(matches(value, a) for a in args)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(args) == 2 and args[1] is Ellipsis:
            return all(matches(v, args[0]) for v in value)
        return len(value) == len(args) and all(matches(v, a) for v, a in zip(value, args))
    if annotation in (int, str, bool, float, type(None)):
        return type(value) is annotation
    return isinstance(annotation, type) and isinstance(value, annotation)


class FrameCodec:
    MAX_DEPTH = 64

    def __init__(self, mechanics, registry, *, origin_state=None, origin_events=None):
        from .resolver import BehaviorCall, ResolutionFrame
        self.registry = registry
        self.origin_events = origin_events
        self.origin_state = origin_state
        self.deck_origin = deck_origin(origin_state) if origin_state is not None else None
        kinds = [RuleContext, BehaviorCall, ResolutionFrame, *mechanics.effect_types, *mechanics.payload_types]
        for module in (model, actions, effects):
            kinds.extend(kind for kind in vars(module).values() if isinstance(kind, type) and
                         kind.__module__ == module.__name__ and not issubclass(kind, effects.Effect) and
                         (issubclass(kind, Enum) or
                          (is_dataclass(kind) and kind.__dataclass_params__.frozen)))
        self.types = {}
        for kind in kinds:
            name = type_name(kind)
            if name in self.types and self.types[name] is not kind:
                raise ValueError(f'Conflicting frame type: {name}')
            self.types[name] = kind

    def _depth(self, depth):
        if depth > self.MAX_DEPTH:
            raise ValueError('Frame payload nesting exceeds codec limit')

    def _validate(self, value):
        from .summoned_attack_targets import TransformAttackedMinion
        if type(value) is TransformAttackedMinion and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry,self.origin_events)
        from .pools import SummonFromPool
        if type(value) is SummonFromPool and value.attack_window is not None and self.origin_state is not None:
            from .summoned_attack_targets import validate_request
            validate_request(self.origin_state,self.registry,value,self.origin_events)
        from .attack_redirects import RandomRedirectAttack
        if type(value) is RandomRedirectAttack and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry, self.origin_events)
        from .countered_spell_secrets import CounterReturnSpell,CounterReplaceSpell
        if type(value) in (CounterReturnSpell,CounterReplaceSpell) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .death_summon_entries import ResurrectOneHealth,SummonDormantDeathCopy
        if type(value) in (ResurrectOneHealth,SummonDormantDeathCopy) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .death_hand_returns import ReturnDeadMinion
        if type(value) is ReturnDeadMinion and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .attack_substitution import CheckAttackSubstitutes
        if type(value) is CheckAttackSubstitutes and self.origin_state is not None:
            from .allocation_facts import validate_allocation
            from .native_attack_targets import original_event
            validate_allocation(self.origin_state,self.registry,value.source)
            original_event(self.origin_state,value.event)
        from .death_self_copies import SummonDeathrattleSelfCopy
        if type(value) is SummonDeathrattleSelfCopy and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry)
        from .assemble_faces import CheckAssembledEndCondition
        if type(value) is CheckAssembledEndCondition and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .draw_cast_grants import GrantedDrawCastBasis, validate_basis as validate_draw_cast_basis
        if type(value) is GrantedDrawCastBasis and self.origin_state is not None:
            validate_draw_cast_basis(self.origin_state, self.registry, value)
        from .native_hand_targets import NativeHandTargetProof,validate_proof as validate_native_hand_proof
        if type(value)is NativeHandTargetProof:
            validate_native_hand_proof(value,self.registry)
        from .native_active_targets import NativeActiveTargetProof, validate_proof as validate_native_active_proof
        if type(value) is NativeActiveTargetProof:
            validate_native_active_proof(value,self.registry)
        from .native_attack_targets import NativeAttackTargetProof, validate_proof as validate_native_attack_proof
        if type(value) is NativeAttackTargetProof:
            validate_native_attack_proof(value,self.registry)
        from .native_target_acceptance import NativeTargetProof, validate_proof as validate_native_target_proof
        if type(value) is NativeTargetProof:
            validate_native_target_proof(value,self.registry)
        from .deck_generation import ShuffleGeneratedCopies,validate_request as validate_generated_shuffle
        if type(value) is ShuffleGeneratedCopies and self.origin_state is not None:
            validate_generated_shuffle(self.origin_state,self.registry,value)
        from .model import BattlecryPayload
        if type(value) is BattlecryPayload:
            from .remaining_mana_numbers import validate_payload
            validate_payload(self.registry,value)
            from .rotating_discovery_classes import validate_payload as validate_discovery_class_payload
            validate_discovery_class_payload(self.registry,value)
        from .native_stat_gains import RewardNativeStatGain,validate_request as validate_native_stat_gain_request
        if type(value) is RewardNativeStatGain and self.origin_state is not None:
            validate_native_stat_gain_request(self.origin_state,self.registry,value)
        from .dark_gift_echo import CopyReceivedDarkGift
        if type(value) is CopyReceivedDarkGift and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .carved_spells import validate_creation as validate_carved_creation,validate_ability as validate_carved_ability
        from .carved_spells import CastCarvedSpell
        if type(value) is CastCarvedSpell and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        if type(value) is effects.AddToHand:validate_carved_creation(self.registry,value)
        if type(value) is model.AbilityInstance and value.carved_spell_id is not None:
            validate_carved_ability(self.registry,value)
        from .bonus_effects import StealBonusEffects
        from .deathrattle_copies import GainAdjacentDeathrattles, CopiedDeathrattleSource, validate_material as validate_copied_deathrattle_material
        if type(value) is GainAdjacentDeathrattles and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        if type(value) is CopiedDeathrattleSource and self.origin_state is not None:
            validate_copied_deathrattle_material(self.origin_state, self.registry, value)
        if type(value) is model.AbilityInstance and value.deathrattle_copied_from is not None and self.origin_state is not None:
            from .deathrattle_copies import validate_ability as validate_copied_deathrattle_ability
            validate_copied_deathrattle_ability(self.origin_state, self.registry, value)
        if type(value) is StealBonusEffects and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .natural_turn_end import RequestNaturalTurnEnd,FinishNaturalTurnEnd
        if type(value) in (RequestNaturalTurnEnd,FinishNaturalTurnEnd) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .controlled_turns import RequestControlledTurn,FinishControlledTurnRequest
        if type(value) in (RequestControlledTurn,FinishControlledTurnRequest) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .deck_auras import PutStoredAura
        if type(value) is PutStoredAura and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry)
        from .spell_auras import CastAuraSpell, validate_instance
        if type(value) is CastAuraSpell and self.origin_state is not None:
            validate_instance(self.origin_state, self.registry, value.instance)
            if value.player_id != value.instance.spell_aura_player_id:
                raise ValueError('Captured Aura trigger changed its original beneficiary')
        from .deck_card_plays import PlayTopDeckCards
        if type(value) is PlayTopDeckCards and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .after_play_grants import RunAfterPlay,accepted_ability
        if type(value)is RunAfterPlay and self.origin_state is not None:
            accepted_ability(self.origin_state,self.registry,value)
        from .minion_families import (UpgradeMinionFamily, SummonFamilyMember,
            validate_request as validate_family_upgrade, validate_summon as validate_family_summon)
        if self.origin_state is not None:
            if type(value) is UpgradeMinionFamily:
                validate_family_upgrade(self.origin_state, self.registry, value, closed=True)
            elif type(value) is SummonFamilyMember:
                validate_family_summon(self.origin_state, self.registry, value, closed=True)
        if (type(value) is model.PaidTargetObservation and self.origin_events is not None and
                value.original_event_cursor > len(self.origin_events)):
            raise ValueError('Original player target cursor exceeds actual retained events')
        from .dead_minion_shuffles import ShuffleDeadMinion, validate_request as validate_dead_shuffle
        if type(value) is ShuffleDeadMinion and self.origin_state is not None:
            validate_dead_shuffle(self.origin_state, self.registry, value)
        from .growing_weapon_shuffles import ShuffleGrowingWeapon,validate_request as validate_growing_weapon_shuffle
        if type(value)is ShuffleGrowingWeapon and self.origin_state is not None:
            validate_growing_weapon_shuffle(self.origin_state,self.registry,value)
        from .battlecry_weapon_outputs import (GenerateBattlecryCard, GenerateBattlecryWeapon, validate_work as validate_weapon_work,
                                              validate_context as validate_weapon_context)
        if type(value) in (GenerateBattlecryCard, GenerateBattlecryWeapon):
            validate_weapon_work(value, self.registry, self.origin_state)
        if type(value) is RuleContext and self.origin_state is not None and self.origin_events is not None:
            validate_weapon_context(value, self.origin_state, self.origin_events)
        from .adapt_memory import AdaptAndRemember, validate_request as validate_adapt_memory
        if type(value) is AdaptAndRemember:
            validate_adapt_memory(value, self.registry, self.origin_state)
        from .resolver import BehaviorCall
        from .linked_hand_costs import SetRandomHandCostForDeathrattle, RestoreRememberedCost
        if type(value) in (SetRandomHandCostForDeathrattle, RestoreRememberedCost) and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry)
        if type(value) is BehaviorCall:
            from .named_summon_followups import validate_call as validate_named_call
            validate_named_call(value)
        if (type(value) is effects.GrantDeathrattle and value.deathrattle_memory is not None
                and self.origin_state is not None):
            from .deathrattle_memory import validate_copy_memory
            validate_copy_memory(self.origin_state, self.registry, value.deathrattle_memory)
        if type(value) is effects.SpendResource and value.requires_board_space and self.origin_state is not None:
            from .summon_quantities import validate_cause
            validate_cause(self.origin_state, self.registry, value.on_success[0].cause)
        from .dark_gift_generation import DiscoverDarkGift
        if type(value) is DiscoverDarkGift and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .discovery import HealHeroFromDiscoveredSpell,validate_cost_healing
        if type(value)is HealHeroFromDiscoveredSpell:validate_cost_healing(self.registry,value)
        from .discovery import DeliverAndSummonDiscoveredMinion,validate_selected_copy
        if type(value)is DeliverAndSummonDiscoveredMinion:validate_selected_copy(self.registry,value)
        from .spell_target_sequences import FreezeAdjacentThenDestroyDamaged,FreezeOriginalGroupMember,DestroyDamagedFrozenGroup,validate_frozen_group
        if type(value)in(FreezeAdjacentThenDestroyDamaged,FreezeOriginalGroupMember,DestroyDamagedFrozenGroup)and self.origin_state is not None:
            validate_frozen_group(self.origin_state,self.registry,value)
        from .captured_minion_spell_groups import DamageCapturedMinionGroup
        if type(value)is DamageCapturedMinionGroup and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .summon_attack_groups import AttackSummonedGroup,validate_request as validate_summon_attack_request
        if type(value)is AttackSummonedGroup:validate_summon_attack_request(self.registry,value,self.origin_state,self.origin_events)
        from .summon_keyword_groups import GrantOutcastSummonedGroup,validate_request as validate_outcast_summon_request
        if type(value)is GrantOutcastSummonedGroup:validate_outcast_summon_request(self.registry,value,self.origin_state)
        from .spell_targets import DamageResidentSpellTarget,ApplyResidentSpellTarget
        if type(value) in(DamageResidentSpellTarget,ApplyResidentSpellTarget) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .spell_targets import RandomDestroyEnemySpellGroup, DestroySelectedSpellGroup
        if type(value) in (RandomDestroyEnemySpellGroup, DestroySelectedSpellGroup) and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry)
        if type(value) is model.AbilityInstance and value.kind == 'corpse_gain':
            from .corpse_gains import validate_ability as validate_corpse_gain_ability
            validate_corpse_gain_ability(self.registry, value)
        from .guarded_corpse_spends import SpendCorpsesForMinion,validate_request as validate_guarded_corpse_request
        if type(value)is SpendCorpsesForMinion and self.origin_state is not None:validate_guarded_corpse_request(self.origin_state,self.registry,value)
        from .successful_summons import DamageSummonedMinion
        if type(value)is DamageSummonedMinion and self.origin_state is not None:value.validate_in_state(self.origin_state)
        from .costs import DestroyPaidMinion
        if type(value)is DestroyPaidMinion and self.origin_state is not None:value.validate_in_state(self.origin_state)
        from .bonus_effects import SpendManaForRandomGrowth,GrantManaRandomGrowth
        if type(value)in(SpendManaForRandomGrowth,GrantManaRandomGrowth)and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .corpse_summon_rewards import ResolveCorpseSummons,FinishCorpseSummons,validate_request as validate_corpse_summon_request,validate_finish as validate_corpse_summon_finish
        if type(value)is ResolveCorpseSummons:validate_corpse_summon_request(self.registry,value)
        if type(value)is FinishCorpseSummons:validate_corpse_summon_finish(self.registry,value,self.origin_state)
        from .successful_summons import GrantSummonedKeyword
        if type(value)is GrantSummonedKeyword and self.origin_state is not None:value.validate_in_state(self.origin_state)
        from .mana_summon_rewards import SpendManaForSummonedPair,BuffManaSummonedPair,validate_request as validate_mana_pair_request,validate_reward as validate_mana_pair_reward
        if type(value)is SpendManaForSummonedPair:validate_mana_pair_request(self.registry,value)
        if type(value)is BuffManaSummonedPair:validate_mana_pair_reward(self.registry,value,self.origin_state)
        from .kindred import ResolveKindred,RunKindredComponent,FinishKindred,validate_activation,validate_component,validate_request as validate_kindred_request
        if type(value)is model.KindredActivation:validate_activation(value,self.registry)
        if type(value)is ResolveKindred:
            validate_kindred_request(value,self.registry)
        if type(value)is RunKindredComponent:
            validate_component(value,self.registry)
            if value.prepared_choice is not None and self.origin_state is not None:
                from .kindred import validate_preparation
                validate_preparation(self.origin_state,self.registry,value.activation)
                if value.prepared_choice.choice.id>=self.origin_state.next_choice_id:
                    raise ValueError('Prepared Kindred group has a future choice identity')
        from .resolver import ResolveChoiceResult
        if type(value)in(effects.RequestChoice,ResolveChoiceResult)and value.kindred is not None:
            validate_activation(value.kindred,self.registry)
            if self.origin_state is not None:
                from .kindred import validate_preparation
                validate_preparation(self.origin_state,self.registry,value.kindred)
                if type(value)is ResolveChoiceResult and value.result.choice.id>=self.origin_state.next_choice_id:
                    raise ValueError('Sampled Kindred callback has a future choice identity')
        from .sacrifice import FreezeCapturedMinion
        if type(value)is FreezeCapturedMinion and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
            if self.registry.card(value.beneficiary.card_id).kind!=CardType.MINION:
                raise ValueError('Captured freeze requires an actual original minion definition')
        if type(value)is FinishKindred:validate_activation(value.activation,self.registry)
        if type(value)is RuleContext and value.kindred is not None:
            validate_activation(value.kindred,self.registry)
            old=value.kindred.original
            if(value.source_id,value.player_id,value.target_id)!=(old.source_id,old.player_id,old.target_id):
                raise ValueError('Saved Kindred body changed its original caller')
            from .owner_turns import validate_accepted_prefix
            validate_accepted_prefix(old.state,value.state,self.registry)
        from .successful_summons import BuffSummonedMinion
        if type(value)is BuffSummonedMinion and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .zones import PutMatchingDeckMinionOnTop
        if type(value)is PutMatchingDeckMinionOnTop and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .hand_play_locks import LockHandCard, validate_request as validate_hand_lock
        if type(value) is LockHandCard and self.origin_state is not None:
            validate_hand_lock(self.origin_state,self.registry,value)
        from .random_effect_choices import ChooseRandomEffects
        if type(value) is ChooseRandomEffects and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .hand_play_locks import TrapRandomHandCards,validate_random_request
        if type(value) is TrapRandomHandCards and self.origin_state is not None:
            validate_random_request(self.origin_state,value)
        from .physical_draw_groups import ContinuePhysicalDrawGroup, CapturePhysicalDrawGroup, validate_material as validate_draw_group
        if type(value) in (ContinuePhysicalDrawGroup, CapturePhysicalDrawGroup) and self.origin_state is not None:
            validate_draw_group(self.origin_state, self.registry, value)
        from .assemble_death_programs import ContinueAssembledDeathrattle,AssembleDeathContinuation,validate_material as validate_death_program
        if type(value) is ContinueAssembledDeathrattle and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        if type(value) is AssembleDeathContinuation:
            validate_death_program(self.registry,value)
        from .assemble_corpse_prefixes import ContinueAssembledPaidBattlecry,AssemblePaidBattlecryContinuation,validate_material as validate_paid_material
        if type(value)is ContinueAssembledPaidBattlecry and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        if type(value)is AssemblePaidBattlecryContinuation:
            validate_paid_material(self.registry,value)
        from .assemble_health_prefixes import (AssembleHealthContinuation,ApplyAssembledHealthPrefix,
            AssembledHealthDamageBatch,ResolveAssembledHealthResult,RecheckAssembledHealthResult,
            validate_material as validate_health_material)
        if type(value)is AssembleHealthContinuation:validate_health_material(self.registry,value)
        from .assemble_reveals import (AssembleRevealContinuation,RevealAssembledPrefix,ResolveAssembledRevealResult,
            validate_material as validate_reveal_material)
        if type(value)is AssembleRevealContinuation:validate_reveal_material(self.registry,value)
        if type(value)in(RevealAssembledPrefix,ResolveAssembledRevealResult)and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
            if type(value)is ResolveAssembledRevealResult and self.origin_events is not None:
                event=value.context.event
                if event.sequence>len(self.origin_events)or self.origin_events[event.sequence-1]!=event:
                    raise ValueError('Assembled reveal lost its original committed event')
        if type(value)in(ApplyAssembledHealthPrefix,AssembledHealthDamageBatch,ResolveAssembledHealthResult,
                RecheckAssembledHealthResult)and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
            if type(value)in(ResolveAssembledHealthResult,RecheckAssembledHealthResult)and self.origin_events is not None:
                event=value.context.event if type(value)is ResolveAssembledHealthResult else value.event
                if event.sequence>len(self.origin_events)or self.origin_events[event.sequence-1]!=event:
                    raise ValueError('Assembly health continuation lost its original committed event')
        from .next_spell_bodies import ContinueNextSpellBodies, FinishNextSpellBody, validate_queued as validate_next_spell_body
        if type(value) in (ContinueNextSpellBodies, FinishNextSpellBody) and self.origin_state is not None:
            validate_next_spell_body(self.origin_state, self.registry, value)
        from .bonus_effects import RotatePrintedHandBonuses
        from .bonus_effects import GrantRandomBonusEffects
        from .sacrifice import BuffCapturedMinion, GrantCapturedKeyword, GrantCapturedSpellDamage
        if type(value) in (GrantRandomBonusEffects, BuffCapturedMinion, GrantCapturedKeyword, GrantCapturedSpellDamage) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        if type(value) is RotatePrintedHandBonuses and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .destruction_resources import DestroyMinionsForResources, DestroyMinionsForDiscard,DestroyMinionsForStats, CompleteDestroyedResources, validate_material as validate_destruction_resources
        from .terminal_spell_loops import CastSpellUntilHeroDies
        if type(value)is CastSpellUntilHeroDies and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .random_control import TakeRandomEnemyMinions
        if type(value)is TakeRandomEnemyMinions and self.origin_state is not None:value.validate_in_state(self.origin_state)
        from .destruction_resummon_spells import DestroyForResummonSpells, CompleteResummonSpells, DestroyedSpellGroup, SpellResummonValue, validate_group as validate_destroyed_spell_group, validate_value as validate_resummon_value
        if type(value) in (DestroyForResummonSpells, CompleteResummonSpells) and self.origin_state is not None:
            value.validate_in_state(self.origin_state, self.registry)
        if type(value) is DestroyedSpellGroup and self.origin_state is not None:
            validate_destroyed_spell_group(self.origin_state, self.registry, value)
        if type(value) is SpellResummonValue and self.origin_state is not None:
            validate_resummon_value(self.origin_state, self.registry, value)
        if type(value) in (DestroyMinionsForResources, DestroyMinionsForDiscard,DestroyMinionsForStats, CompleteDestroyedResources) and self.origin_state is not None:
            validate_destruction_resources(self.origin_state, self.registry, value)
        if type(value) in (effects.ForceAttack, effects.CopyMinion) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .forced_attack_sequences import AttackRandomEnemyMinion, AttackLowestHealthEnemy, AttackRandomEnemyCharacter, AttackAllOtherMinions, ForceEachMinionAttack
        if type(value) in (AttackRandomEnemyMinion, AttackLowestHealthEnemy, AttackRandomEnemyCharacter, AttackAllOtherMinions, ForceEachMinionAttack) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .minion_attack_damage import EachMinionDealsAttackDamage
        if type(value) is EachMinionDealsAttackDamage and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .source_kills import KillSourceReference, ResurrectKilledMinions, validate_reference as validate_kill_source, validate_effect as validate_kill_effect
        if type(value) is KillSourceReference and self.origin_state is not None:
            validate_kill_source(self.origin_state, self.registry, value)
        if type(value) is ResurrectKilledMinions and self.origin_state is not None:
            validate_kill_effect(self.origin_state, self.registry, value)
        from .sacrifice import SetCapturedMinionStats, BuffCapturedMinionWithStartTrigger, TransformCapturedMinion
        if type(value) in (SetCapturedMinionStats, BuffCapturedMinionWithStartTrigger, TransformCapturedMinion) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        if type(value) is TransformCapturedMinion and (
                self.registry.card(value.beneficiary.card_id).kind!=CardType.MINION or
                self.registry.card(value.card_id).kind!=CardType.MINION):
            raise ValueError('Captured transform requires original and resulting minion definitions')
        if type(value) is BuffCapturedMinionWithStartTrigger:
            self.registry.behavior(value.behavior_id)
            self.registry.trigger_condition(value.condition_id)
            if self.registry.card(value.beneficiary.card_id).kind != CardType.MINION:
                raise ValueError('Numeric/start grant requires an original minion definition')
        from .attack_policies import GrantAttackPolicy
        if type(value) is GrantAttackPolicy and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
            if value.recipient is not None and self.registry.card(value.recipient.card_id).kind != CardType.MINION:
                raise ValueError('Captured attack recipient requires a minion definition')
        from .limited_triggers import GrantLimitedTrigger
        if type(value)is GrantLimitedTrigger and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
            if value.recipient is not None and self.registry.card(value.recipient.card_id).kind!=CardType.MINION:
                raise ValueError('Captured finite trigger recipient requires a minion definition')
        from .stored_spell_damage import GrantStoredSpellDamage,DrawMatchingSpellDamage
        if type(value) in (GrantStoredSpellDamage,DrawMatchingSpellDamage) and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        from .copy_materials import CapturedCardCopyMaterial,validate_captured_card_copy
        if type(value)is CapturedCardCopyMaterial and self.origin_state is not None:
            validate_captured_card_copy(self.origin_state,self.registry,value)
        from .played_minion_copies import PlayedMinionCopyMaterial, validate_material as validate_played_minion_copy
        if type(value) is PlayedMinionCopyMaterial and self.origin_state is not None:
            validate_played_minion_copy(self.origin_state, self.registry, value)
        from .deathrattle_memory import DiscardForDeathrattle,ImprisonForDeathrattle,AwakenRememberedDormancy,ShuffleRememberedTargetSpell
        if type(value) in (DiscardForDeathrattle,ImprisonForDeathrattle,AwakenRememberedDormancy,ShuffleRememberedTargetSpell) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .retained_spell_damage import DamageReturningSpell
        from .spent_spells import ReturnSpentSpell
        if (type(value) is DamageReturningSpell or type(value) is ReturnSpentSpell and value.native_value is not None) and self.origin_state is not None:
            value.validate_in_state(self.origin_state,self.registry)
        from .zones import CopyCard
        if type(value) is CopyCard and type(value.card) is model.FrozenPlayedFaceFact and self.origin_state is not None:
            from .played_card_copies import original_entity
            original_entity(self.origin_state, self.registry, value.card)
        from .discard_history import DiscardRecord,validate_base_copy
        if type(value) is CopyCard and type(value.card) is DiscardRecord and self.origin_state is not None:
            validate_base_copy(self.origin_state,self.registry,value.card)
        from .resolver import BehaviorCall
        from .player_effects import PlayerEffectDamage,validate_player_damage
        if type(value)is PlayerEffectDamage and self.origin_state is not None:
            validate_player_damage(self.origin_state,self.registry,value)
        from .player_effects import ConsumePlayerEffect, validate_consumption
        if type(value) is ConsumePlayerEffect and self.origin_state is not None:
            validate_consumption(self.origin_state, self.registry, value)
        if type(value) is model.HandOtherClassMatch:
            from .hand_conditions import validate_hand_other_class_match
            validate_hand_other_class_match(value,self.registry)
        if type(value) is model.CardDiscoveredTurnMatch:
            from .card_discoveries import validate_turn_match
            validate_turn_match(value, self.registry)
        if type(value) is model.CostPresenceMatch:
            from .cost_presence import validate_match
            validate_match(value,self.registry)
        if type(value) is BehaviorCall:
            from .discard_history import validate_call as validate_discard_call
            validate_discard_call(value, self.registry)
            from .zones import validate_destroyed_call
            validate_destroyed_call(value, self.registry)
            from .physical_draw_groups import validate_qualified_call
            validate_qualified_call(value, self.registry)
            from .assemble_death_programs import validate_call as validate_death_followup
            validate_death_followup(value,self.registry)
            from .assemble_corpse_prefixes import validate_call as validate_paid_followup
            validate_paid_followup(value,self.registry)
        if type(value) is effects.RequestChoice:
            from .choose_policies import reject_choice_control as reject_choose_policy_control
            reject_choose_policy_control(value.options)
            from .whole_card_replays import reject_choice_control as reject_whole_card_choice_control
            reject_whole_card_choice_control(value.options)
            from .summon_quantities import reject_choice_control as reject_summon_choice_control
            reject_summon_choice_control(value.options)
            from .pool_summons import reject_choice_control as reject_pool_summon_control
            reject_pool_summon_control(value.options)
            from .ordered_group_batches import reject_choice_control as reject_ordered_group_control
            reject_ordered_group_control(value.options)
            from .recruit_stat_groups import reject_choice_control as reject_recruit_stat_group_control
            reject_recruit_stat_group_control(value.options)
            from .discovery_summons import reject_choice_control as reject_discovery_summon_control
            reject_discovery_summon_control(value.options)
            from .random_split_damage import reject_choice_control as reject_split_choice_control
            reject_split_choice_control(value.options)
            from .resource_operations import reject_choice_control
            reject_choice_control(value.options)
            from .attack_substitution import reject_choice_control as reject_attack_substitution_control
            reject_attack_substitution_control(value.options)
            from .hero_lethal_windows import reject_choice_control as reject_hero_choice_control
            reject_hero_choice_control(value.options)
        if type(value) is model.PrintedAttackPolicyDeclaration:
            from .printed_attack_permits import declaration_spec
            declaration_spec(self.registry, value)
        if type(value) in (model.SelfPrintedAttackReference, model.PrintedAttackPermitRequest, model.PrintedAttackPermit):
            from .printed_attack_permits import declaration_spec
            declaration = value.reference.declaration if type(value) is model.PrintedAttackPermitRequest else value.declaration
            declaration_spec(self.registry, declaration, restriction=True)
        if type(value) is model.IntrinsicCostStageFact:
            from .intrinsic_costs import validate_intrinsic_stage_fact
            validate_intrinsic_stage_fact(self.registry, value)
        if type(value) is model.GeneratedCostQuoteFact:
            from .intrinsic_costs import validate_generated_quote_fact
            validate_generated_quote_fact(self.registry, value)
        if type(value) is model.FrozenPlayedFaceFact:
            from .owner_turns import validate_face
            validate_face(value, self.registry)
        from .model import HeroPowerReference, EndTurnRequest, EndTurnActivation
        if type(value) is HeroPowerReference and self.registry.card(value.card_id).kind != CardType.HERO_POWER:
            raise ValueError('Captured power reference requires a hero power definition')
        from .imbue import Imbue
        if isinstance(value, Imbue) and value.count:
            self.registry.imbue_profile(value.profile_id)
        from .pools import GenerateFromCandidates, validate_hand_candidates, SummonFromCandidates, validate_summon_candidates
        if type(value) is GenerateFromCandidates:
            validate_hand_candidates(self.registry, value.card_ids)
            if self.origin_state is not None and value.source_id is not None and value.source_id not in self.origin_state.entities:
                raise ValueError('Finite hand generation has an unknown original source')
        if isinstance(value, SummonFromCandidates):
            validate_summon_candidates(self.registry, value.card_ids)
        from .zones import DrawMatching
        if type(value) is DrawMatching:
            for card_id in value.card_ids: self.registry.card(card_id)
        from .producer_amounts import AcceptedProducerAmount,validate as validate_producer_amount
        if type(value)is AcceptedProducerAmount:validate_producer_amount(self.registry,value)
        from .ordered_summon_groups import OrderedGroupSelection,validate_selection as validate_group_selection
        if type(value)is OrderedGroupSelection:validate_group_selection(self.registry,value)
        from .ordered_group_batches import SummonOrderedGroup,request_profile as group_request_profile
        if type(value)is SummonOrderedGroup:group_request_profile(self.registry,value)
        if type(value)is model.SummonProducerProfile and self.registry.summon_producer_profile(value.id)!=value:
            raise ValueError('Captured logical producer profile differs from its registry')
        annotations = get_type_hints(type(value))
        from .choose_policies import ChoosePolicyProof, validate_proof as validate_choose_policy_proof
        if type(value) is ChoosePolicyProof:
            validate_choose_policy_proof(value, self.registry)
        from .automatic_targets import AutomaticTargetProof, validate_proof as validate_automatic_target_proof
        if type(value) is AutomaticTargetProof:
            validate_automatic_target_proof(value, self.registry)
        from .card_spell_repeats import CardCastRepeatProof, validate_automatic_proof as validate_card_cast_repeat
        if type(value) is CardCastRepeatProof:
            validate_card_cast_repeat(value, self.registry)
        from .automatic_spell_groups import AutomaticSpellGroupProof, validate_proof as validate_automatic_group
        if type(value) is AutomaticSpellGroupProof:
            validate_automatic_group(value, self.registry)
        from .whole_card_replays import (ReplayAcceptanceProof, ReplaySpellProof,
            validate_acceptance as validate_whole_card_acceptance, validate_spell_proof)
        if type(value) is ReplayAcceptanceProof:
            validate_whole_card_acceptance(value, self.registry)
        if type(value) is ReplaySpellProof:
            validate_spell_proof(value, self.registry)
        from .whole_card_physical import PhysicalBodyProof, PhysicalReplayProgress, validate_body_proof
        if type(value) is PhysicalBodyProof:
            validate_body_proof(value, self.registry)
        if type(value) is RuleContext and value.physical is not None:
            if type(value.physical) is not PhysicalReplayProgress:
                raise ValueError('Physical callback requires its concrete activation context')
            child = value.state.whole_card_replay_ledger.children[value.physical.child_id - 1]
            if child.physical != value.physical or value.source_id != value.physical.source.entity_id:
                raise ValueError('Physical callback changed its actual current activation context')
        from .random_split_damage import SplitAcceptanceProof, SplitPacketProof, validate_acceptance as validate_split_acceptance, validate_packet_proof
        if type(value) is SplitAcceptanceProof:
            validate_split_acceptance(value, self.registry)
        if type(value) is SplitPacketProof:
            validate_packet_proof(value, self.registry)
        from .kidnap_custody import StoredMinionCustody, KidnapPlayedMinion, ReturnSackCaptive, validate_custody
        if self.origin_state is not None:
            if type(value) is StoredMinionCustody:
                validate_custody(self.origin_state, self.registry, value)
            elif type(value) in (KidnapPlayedMinion, ReturnSackCaptive):
                value.validate_in_state(self.origin_state, self.registry)
        from .sacrifice import DestroyCapturedMinion
        if type(value) is DestroyCapturedMinion and self.origin_state is not None:
            value.validate_in_state(self.origin_state)
        for field in fields(value):
            item = getattr(value, field.name)
            if field.name not in annotations or not matches(item, annotations[field.name]):
                raise ValueError(f'Invalid frame field type: {type(value).__name__}.{field.name}')
            if field.name in ('card_id', 'hero_power_card_id') and item is not None:
                self.registry.card(item)
            if field.name in ('behavior_id', 'on_select', 'on_summon', 'on_result', 'on_fatigue') and item is not None:
                self.registry.behavior(item)
            if field.name == 'producer_profile_id' and item is not None:
                self.registry.summon_producer_profile(item)
            if field.name == 'spec_id':
                self.registry.player_effect(item)
            if field.name == 'player_id' and item not in (1, 2) and not (type(value) is Event and item is None):
                raise ValueError('Invalid frame player ID')
            if field.name in ('source_id', 'target_id', 'attacker_id', 'defender_id', 'entity_id', 'death_id', 'choice_id'):
                from .pools import GenerationContext
                # This target identifies a versioned rules inventory, not an entity.
                if type(value) is GenerationContext and field.name == 'target_id':
                    value.__post_init__()
                elif (type(value) is effects.ForceAttack and field.name in ('attacker_id', 'defender_id')
                      and type(item) is model.BoardPresenceReference):
                    item.__post_init__()
                elif (type(value) is effects.CopyMinion and field.name == 'target_id'
                      and type(item) is model.BoardPresenceReference):
                    item.__post_init__()
                elif (type(value) is effects.ModifyWeapon and field.name == 'target_id'
                      and type(item) is model.EquippedWeaponReference):
                    item.__post_init__()
                elif item is not None and (type(item) is not int or item <= 0):
                    raise ValueError('Invalid frame entity/record ID')
        if hasattr(value, '__post_init__'):
            value.__post_init__()
        if type(value) is model.EquippedWeaponReference and self.registry.card(value.card_id).kind!=model.CardType.WEAPON:
            raise ValueError('Equipped weapon frame reference requires a Weapon definition')
        if type(value) is model.Event:
            from .zones import destruction_result
            destroyed = destruction_result(value)
            if destroyed is not None and self.registry.card(destroyed.card.card_id).kind != destroyed.kind:
                raise ValueError('Stored destruction frame event changed its original type')
            from .resources import armor_loss_result, mana_consumption_result
            armor_loss_result(value)
            mana_consumption_result(value)
            from .mana_exhaustion import payment_available
            payment_available(value)
            if value.kind=='hero_health_set':
                from .hero_health_history import validate_health_set_event
                validate_health_set_event(value)
            from .equipment import weapon_transfer_reference
            ref=weapon_transfer_reference(value)
            if ref is not None and self.registry.card(ref.card_id).kind!=model.CardType.WEAPON:
                raise ValueError('Weapon transfer frame event changed its original type')
        if type(value) is RuleContext:
            from .resources import mana_consumption_result
            row=mana_consumption_result(value.event)
            if row is not None and (row.id>len(value.state.mana_consumption_history) or value.state.mana_consumption_history[row.id-1]!=row):
                raise ValueError('Mana callback lost its original captured consumption')
            if value.event is not None and value.event.kind=='hero_health_set':
                from .hero_health_history import validate_event as validate_hero_event
                validate_hero_event(value.state,value.event)
        if type(value) in (model.SpellRepeatSpec, model.BattlecryRepeatSpec,
                           model.ComboRepeatSpec, model.DeathrattleRepeatSpec,
                           model.HeroPowerRepeatSpec, model.EndTurnRepeatSpec):
            from .repeat_source_conditions import validate_source_declaration
            validate_source_declaration(self.registry, value)
        if type(value) is model.BattlecryRecipient:
            if self.registry.card(value.card_id).kind != value.kind:
                raise ValueError('Captured Battlecry recipient differs from its registered physical kind')
        if type(value) is model.ComboRecipient:
            if self.registry.card(value.card_id).kind != value.kind:
                raise ValueError('Captured Combo recipient differs from its registered physical kind')
        if type(value) is model.DeathrattleRecipient:
            if self.registry.card(value.card_id).kind != value.kind:
                raise ValueError('Captured Deathrattle recipient differs from its registered physical kind')
        if type(value) is model.DeathrattleRepeatContributor:
            if self.registry.card(value.card_id).kind != CardType.MINION:
                raise ValueError('Captured Deathrattle repeat source requires a minion carrier')
        if type(value) is model.RepeatSourceEligibility:
            self.registry.repeat_witness_profile(value.profile_id)
        if type(value) is model.RepeatWitnessProfile:
            if self.registry.repeat_witness_profile(value.id) != value:
                raise ValueError('Captured repeat witness profile differs from its registry')
        if type(value) is EndTurnRequest:
            self.registry.end_turn_profile(value.profile_id)
        if type(value) is getattr(model, 'EndTurnProducerRequest', None):
            self.registry.end_turn_candidate_profile(value.candidate_profile_id)
            self.registry.end_turn_profile(value.activation_profile_id)
        if type(value) is getattr(model, 'EndTurnCarrier', None):
            if value.kind == 'player_effect':
                self.registry.player_effect(value.player_effect.spec_id)
            else:
                kinds = {CardType.MINION: 'minion', CardType.WEAPON: 'weapon',
                         CardType.HERO_POWER: 'hero_power', CardType.LOCATION: 'location'}
                if kinds.get(self.registry.card(value.card_id).kind) != value.kind:
                    raise ValueError('End-turn carrier differs from its registered physical card kind')
        if type(value) is getattr(model, 'EndTurnSelection', None):
            self.registry.end_turn_candidate_profile(value.request.candidate_profile_id)
            self.registry.end_turn_profile(value.request.activation_profile_id)
            # The selection receipt is independently checkable, even when
            # later bodies have already advanced the game's shared RNG.
            import random
            probe = random.Random()
            probe.setstate(value.rng_before)
            selected = probe.choice(value.candidates) if value.candidates else None
            if selected != value.selected or probe.getstate() != value.rng_after:
                raise ValueError('End-turn selection differs from its one recorded random draw')
        if type(value) is EndTurnActivation:
            self.registry.card(value.issuer_card_id)
            if value.request is not None:
                profile = self.registry.end_turn_profile(value.request.profile_id)
                if profile.kind != value.kind:
                    raise ValueError('End-turn activation differs from its registered profile kind')
            if value.selection is not None:
                request = value.selection.request
                self.registry.end_turn_candidate_profile(request.candidate_profile_id)
                profile = self.registry.end_turn_profile(request.activation_profile_id)
                if value.request is None or value.request.profile_id != request.activation_profile_id or profile.kind != value.kind:
                    raise ValueError('End-turn selection differs from its registered activation profile')
        from .deathrattles import FinishDeathrattleBatch, validate_acceptance as validate_deathrattle_acceptance
        if type(value) is FinishDeathrattleBatch:
            validate_deathrattle_acceptance(value,self.registry)
        from .battlecry_repeats import FinishBattlecryAcceptance, validate_acceptance as validate_battlecry_acceptance
        if type(value) is FinishBattlecryAcceptance:
            validate_battlecry_acceptance(value,self.registry)
        from .combo_acceptance import FinishComboAcceptance, validate_acceptance as validate_combo_acceptance
        if type(value) is FinishComboAcceptance:
            validate_combo_acceptance(value,self.registry)
        from .spell_acceptance import FinishSpellAcceptance, validate_acceptance as validate_spell_acceptance
        if type(value) is FinishSpellAcceptance:
            validate_spell_acceptance(value, self.registry)
        from .spell_cost_proof import HandPlayCostProof, validate_hand_cost_proof
        from .paid_hand_acceptance import (PaidHandCostProof, PaidHandChoiceBoundaryProof,
            FinishPaidHandAcceptance, validate_tail, validate_choice_boundary_proof)
        if type(value) is PaidHandCostProof:
            from .spell_cost_proof import _validate_hand_cost_proof
            _validate_hand_cost_proof(value, self.registry, proof_type=PaidHandCostProof)
        if type(value) is FinishPaidHandAcceptance:
            validate_tail(value, self.registry)
        if type(value) is PaidHandChoiceBoundaryProof:
            validate_choice_boundary_proof(value, self.registry)
        from .resolver import ResolutionFrame
        if type(value) is ResolutionFrame:
            validate_choice_boundary_proof(value.paid_hand_choice_boundary, self.registry)
            if value.paid_hand_choice_boundary.state.pending_choice.id != value.choice_id:
                raise ValueError('Frame differs from its complete original choice boundary')
        if type(value) is HandPlayCostProof:
            validate_hand_cost_proof(value, self.registry)
        from .hero_powers import FinishHeroPower, validate_acceptance as validate_power_acceptance
        if type(value) is FinishHeroPower:
            validate_power_acceptance(value, self.registry)
        from .end_turns import FinishEndTurnBatch
        from .end_turn_acceptance import validate_acceptance as validate_end_turn_acceptance
        if type(value) is FinishEndTurnBatch:
            validate_end_turn_acceptance(value, self.registry)
        if type(value) is PaidHandChoiceBoundaryProof:
            from .summon_quantities import validate_frame_references as validate_summon_frame_references
            validate_summon_frame_references(value.state, self.registry, value.work)
            from .pool_summons import validate_frame_references as validate_pool_summon_frame_references
            validate_pool_summon_frame_references(value.state,self.registry,value)
            from .ordered_group_batches import validate_frame_references as validate_ordered_group_frame_references
            validate_ordered_group_frame_references(value.state,self.registry,value)
            from .discovery_summons import validate_frame_references as validate_discovery_summon_frame_references
            validate_discovery_summon_frame_references(value.state,self.registry,value)
            from .recruit_summons import validate_frame_references as validate_recruit_summon_frame_references
            validate_recruit_summon_frame_references(value.state,self.registry,value)
            from .resurrection_summons import validate_frame_references as validate_resurrection_summon_frame_references
            validate_resurrection_summon_frame_references(value.state,self.registry,value)
            from .stat_relations import validate_frame_references as validate_stat_relation_frame_references
            validate_stat_relation_frame_references(value.state, self.registry, value.work)
            from .tribes import validate_frame_references as validate_tribe_frame_references
            validate_tribe_frame_references(value.state, self.registry, value.work)
            from .health_floors import validate_frame_references as validate_floor_frame_references
            validate_floor_frame_references(value.state, self.registry, value.work)
            from .health_loss_floors import validate_frame_references as validate_loss_floor_frame
            validate_loss_floor_frame(value.state, self.registry, value.work)
        if type(value) is RuleContext:
            from .composed_locations import STEP as location_step, component_context as validate_location_context
            from .hand_history import validate_context as validate_hand_context
            validate_hand_context(value, self.origin_state, self.origin_events)
            if value.event is not None and value.event.kind == location_step:
                validate_location_context(value, self.registry)
                if self.origin_events is not None and (value.event.sequence > len(self.origin_events) or
                        self.origin_events[value.event.sequence - 1] != value.event):
                    raise ValueError('Location component frame lost its actual original cursor event')
            from .discard_history import validate_context as validate_discard_context
            validate_discard_context(value, self.registry)
            from .zones import validate_destroyed_context
            validate_destroyed_context(value, self.registry)
            if (value.trigger is not None and value.trigger.kind == 'on_destroyed' and self.origin_events is not None and
                    (value.event.sequence > len(self.origin_events) or
                     self.origin_events[value.event.sequence-1] != value.event)):
                raise ValueError('Native destroyed frame lost its actual original event')
            from .deathrattles import validate_context as validate_deathrattle_context
            validate_deathrattle_context(value,self.registry)
            if value.paid_battlecry_followup is not None:
                from .assemble_corpse_prefixes import validate_context as validate_paid_context
                validate_paid_context(value,self.registry)
            from .power_payloads import validate_context as validate_power_payload_context
            validate_power_payload_context(value,self.registry)
            from .end_turns import validate_context as validate_end_turn_context
            validate_end_turn_context(value,self.registry)
            from .invoke import validate_context as validate_invoke_context
            validate_invoke_context(value, self.registry)
            if self.deck_origin is not None and deck_origin(value.state) != self.deck_origin:
                raise ValueError('Captured starting deck facts differ from the match origin')
            if type(value.rewind_attempt) is not int or value.rewind_attempt < 0:
                raise ValueError('Invalid captured Rewind attempt')
            if (value.source_id not in value.state.entities or
                    (value.target_id is not None and value.target_id not in value.state.entities)):
                raise ValueError('Captured context references a missing entity')
            if value.event is not None and value.event.action > value.state.action_number:
                raise ValueError('Captured event is newer than its context')
            if value.death is not None and value.death not in value.state.death_history:
                raise ValueError('Captured death record is absent from its context')
            if value.choice is not None and value.choice.choice.id >= value.state.next_choice_id:
                raise ValueError('Captured choice result is newer than its context')
            if value.window is not None and value.window not in value.state.action_windows:
                raise ValueError('Captured action window is absent from its context')
            if value.play is not None and value.play not in value.state.play_history:
                raise ValueError('Captured play record is absent from its context')
            if value.cast is not None and value.cast not in value.state.cast_history:
                raise ValueError('Captured spell cast is absent from its context')
            if value.combo is not None and value.combo not in value.state.combo_history:
                raise ValueError('Captured Combo is absent from its context')
            if value.battlecry is not None and value.battlecry not in value.state.battlecry_history:
                raise ValueError('Captured Battlecry is absent from its context')
            if value.power is not None and value.power not in value.state.hero_power_history:
                raise ValueError('Captured hero power is absent from its context')
            if value.draw is not None and value.draw not in value.state.draw_history:
                raise ValueError('Captured draw is absent from its context')
            from .physical_draw_groups import validate_qualified_context
            validate_qualified_context(value, self.registry)
            from .end_turns import started_extra_context
            if value.trigger is not None and value.trigger not in value.source.abilities and not started_extra_context(value):
                raise ValueError('Captured trigger instance is absent from its source')
            if value.player_effect is not None:
                effect = value.player_effect
                effect.__post_init__()
                if effect.source_allocation is not None:
                    from .allocation_facts import allocation_from_payload,validate_allocation
                    validate_allocation(value.state,self.registry,allocation_from_payload(effect.source_allocation))
                    if effect.source_player_id!=value.player_id:raise ValueError('Captured player health source changed beneficiary')
                spec = self.registry.player_effect(effect.spec_id)
                if spec.capture_health_source and effect.source_allocation is None:
                    raise ValueError('Captured Sigil context lost its declared original health source')
                self.registry.card(effect.source_card_id)
                from .aura_duration import maximum_duration
                maximum = maximum_duration(self.registry, effect, value.state, value.player_id)
                if (effect.source_id != value.source_id or effect.id >= value.state.next_attachment_id or
                        effect.created_turn > value.state.turn or effect.entered_order >= value.state.next_order or
                        (effect.remaining_turns is None) != (spec.duration is None) or
                        (spec.duration is not None and effect.remaining_turns > maximum)):
                    raise ValueError('Invalid captured player effect provenance')

    def encode(self, value, depth=0):
        self._depth(depth)
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is GameState:
            validate_invariants(value, self.registry)
            return {'state': state_to_dict(value)}
        if type(value) is Event:
            row = event_to_dict(value)
            self._event(row)
            return {'event': row}
        if type(value) is tuple:
            return {'tuple': [self.encode(item, depth + 1) for item in value]}
        kind = type(value)
        if self.types.get(type_name(kind)) is not kind:
            raise ValueError(f'Unregistered frame payload type: {type_name(kind)}')
        if isinstance(value, Enum):
            return {'enum': type_name(kind), 'value': value.value}
        if not is_dataclass(value) or not kind.__dataclass_params__.frozen:
            raise ValueError('Frame work and payloads must be frozen dataclasses')
        self._validate(value)
        from .attack_redirects import AttackRedirectSelection
        if kind in (getattr(model, 'EndTurnSelection', None), AttackRedirectSelection):
            return {'type': type_name(kind), 'fields': {
                f.name: {'end_turn_rng': end_turn_rng_to_json(getattr(value, f.name))}
                if f.name in ('rng_before', 'rng_after') else self.encode(getattr(value, f.name), depth + 1)
                for f in fields(value)}}
        return {'type': type_name(kind), 'fields': {
            f.name: self.encode(getattr(value, f.name), depth + 1) for f in fields(value)}}

    def decode(self, value, depth=0):
        self._depth(depth)
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is not dict:
            raise ValueError('Frame value must be a typed JSON object or scalar')
        if set(value) == {'tuple'} and type(value['tuple']) is list:
            return tuple(self.decode(v, depth + 1) for v in value['tuple'])
        if set(value) == {'state'}:
            result = state_from_dict(value['state'])
            validate_invariants(result, self.registry)
            return result
        if set(value) == {'event'}:
            result = self._event(value['event'])
            self._validate(result)
            return result
        if set(value) == {'enum', 'value'}:
            kind = self.types.get(value['enum']) if type(value['enum']) is str else None
            if kind is None or not issubclass(kind, Enum):
                raise ValueError('Unknown frame enum type')
            return kind(value['value'])
        if set(value) != {'type', 'fields'} or type(value['type']) is not str:
            raise ValueError('Invalid frame object fields')
        kind = self.types.get(value['type'])
        if kind is None or not is_dataclass(kind) or not kind.__dataclass_params__.frozen:
            raise ValueError(f'Unknown immutable frame type: {value["type"]}')
        row = value['fields']
        if type(row) is not dict or set(row) != {f.name for f in fields(kind)}:
            raise ValueError('Frame payload fields must match the declared type')
        from .attack_redirects import AttackRedirectSelection
        if kind in (getattr(model, 'EndTurnSelection', None), AttackRedirectSelection):
            decoded = {}
            for name, item in row.items():
                if name in ('rng_before', 'rng_after'):
                    self._depth(depth + 1)
                    if type(item) is not dict or set(item) != {'end_turn_rng'}:
                        raise ValueError('Producer selection RNG requires its dedicated typed receipt')
                    decoded[name] = end_turn_rng_from_json(item['end_turn_rng'])
                else:
                    decoded[name] = self.decode(item, depth + 1)
        else:
            decoded = {name: self.decode(item, depth + 1) for name, item in row.items()}
        from .model import EndTurnBatch, EndTurnRepeatContributor, EndTurnRecord
        # Python constructors permit concise declarations; saved wire facts
        # must already contain the complete plans and resolved identities.
        if kind is EndTurnBatch and (type(decoded['plans']) is not tuple or
                type(decoded['subjects']) is not tuple or len(decoded['plans']) != len(decoded['subjects'])):
            raise ValueError('Saved end-turn batch requires every explicit subject plan')
        if kind is EndTurnRepeatContributor and decoded['spec'] is None:
            raise ValueError('Saved end-turn contributor requires its explicit specification')
        if kind is EndTurnRecord and decoded['guard_id'] is None:
            raise ValueError('Saved end-turn record requires its original guard identity')
        result = kind(**decoded)
        self._validate(result)
        return result

    @staticmethod
    def _event(row):
        if type(row) is not dict or set(row) != {f.name for f in fields(Event)}:
            raise ValueError('Invalid captured event fields')
        event = event_from_dict(row)
        from .invoke import validate_event as validate_invoke_event
        validate_invoke_event(event)
        from .jade import validate_event as validate_jade_event
        validate_jade_event(event)
        from .zones import destruction_result
        destruction_result(event)
        from .cthun import validate_event as validate_cthun_event
        validate_cthun_event(event)
        if (type(event.sequence) is not int or event.sequence < 1 or type(event.action) is not int or event.action < 0 or
                type(event.kind) is not str or not event.kind or type(event.amount) is not int):
            raise ValueError('Invalid captured event')
        for value in (event.source_id, event.target_id):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError('Invalid captured event entity ID')
        if event.player_id is not None and (type(event.player_id) is not int or event.player_id not in (1, 2)):
            raise ValueError('Invalid captured event player ID')
        return event


def validate_frame(game):
    from .resolver import ResolutionFrame
    choice, frame = game._state.pending_choice, game._frame
    if choice is None:
        if frame is not None:
            raise ValueError('A resolution frame requires a pending choice')
        return
    if type(frame) is not ResolutionFrame or frame.choice_id != choice.id:
        raise ValueError('Pending choice and resolution frame do not match')
    from .discard_history import validate_frame_materials
    validate_frame_materials(game._state, game.registry, frame)
    from .locations import validate_location_face_frame_references
    validate_location_face_frame_references(game._state, game.registry, frame)
    from .printed_attack_permits import validate_frame_references
    validate_frame_references(game._state, game.registry, frame)
    from .stat_relations import validate_frame_references as validate_stat_relation_frame_references
    validate_stat_relation_frame_references(game._state, game.registry, frame)
    from .tribes import validate_frame_references as validate_tribe_frame_references
    validate_tribe_frame_references(game._state, game.registry, frame)
    from .health_floors import validate_frame_references as validate_floor_frame_references
    validate_floor_frame_references(game._state, game.registry, frame)
    from .health_loss_floors import validate_frame_references as validate_loss_floor_frame
    validate_loss_floor_frame(game._state, game.registry, frame)
    from .paid_hand_acceptance import validate_choice_boundary
    validate_choice_boundary(game)
    if (type(frame.steps) is not int or not 1 <= frame.steps < game.ruleset.max_resolution_steps or
            type(frame.root_action_number) is not int or not 0 <= frame.root_action_number <= game._state.action_number or
            type(frame.ending_turn) is not bool):
        raise ValueError('Invalid suspended resolution budget or action')
    if frame.root_action_number == 0 and game._match_setup is None:
        raise ValueError('Only a constructed opening can suspend the setup resolution')
    if choice.max_count == 0 or len(choice.options) > game.ruleset.max_choice_options:
        raise ValueError('Invalid offered choice count')
    if tuple(o.item for o in frame.options) != choice.options:
        raise ValueError('Choice branches and offered metadata differ')
    from .dredge import validate_choice as validate_dredge_choice
    validate_dredge_choice(game)
    from .stored_gift_discovery import validate_choice as validate_stored_gift_choice
    validate_stored_gift_choice(game)
    from .zones import validate_deck_take_choice
    validate_deck_take_choice(game)
    from .deck_discovery_actions import validate_choice as validate_deck_action_choice
    validate_deck_action_choice(game)
    if len(frame.prefix) + len(frame.continuation) > game.ruleset.max_resolution_steps:
        raise ValueError('Suspended work queue exceeds resolution budget')
    from .starships import FinishStarshipLaunch
    from .spell_repeats import FinishSpellRepeat
    closers = sum(isinstance(work, (FinishStarshipLaunch, FinishSpellRepeat)) for work in (*frame.prefix, *frame.continuation))
    if type(frame.death_deferrals) is not int or not 0 <= frame.death_deferrals == closers:
        raise ValueError('Invalid suspended death deferral boundaries')
    from .interrupts import ResolveSpell, ResolveAttack, SpellTargetPhase
    from .minion_plays import ResolveMinionPlay, MinionCounterPhase
    from .spell_group_targets import SettleSpellGroupArrow
    window_closers = [work for work in (*frame.prefix, *frame.continuation) if isinstance(work, (ResolveSpell, ResolveAttack, SpellTargetPhase, ResolveMinionPlay, MinionCounterPhase, SettleSpellGroupArrow))]
    windows = list(reversed(game._state.action_windows))
    if (len(window_closers) != len(windows) or any(work.window_id != window.id or
            (isinstance(work, (ResolveSpell, SpellTargetPhase, SettleSpellGroupArrow))) != (window.kind == 'spell') or
            (isinstance(work, (ResolveMinionPlay, MinionCounterPhase))) != (window.kind == 'minion') or
            (window.kind == 'spell' and isinstance(work, (ResolveSpell, SettleSpellGroupArrow)) != window.target_phase) or
            (window.kind == 'minion' and isinstance(work, ResolveMinionPlay) != window.counter_phase)
            for work, window in zip(window_closers, windows))):
        raise ValueError('Pending action windows and their continuations do not match')
    codec = FrameCodec(game.mechanics, game.registry, origin_state=game._state, origin_events=game._events)
    from .resolver import FinishPlay
    from .play_history import play_record
    unresolved=[p.id for p in game._state.play_history if not p.completed and not p.interrupted]
    finishers=[w for w in (*frame.prefix,*frame.continuation) if isinstance(w,FinishPlay)]
    window_play_ids=[w.play_id for w in game._state.action_windows if w.kind in ('spell','minion')]
    pending_minion_ids=[w.play_id for w in game._state.action_windows if w.kind=='minion']
    finisher_play_ids=[w.play_id for w in finishers]
    if (any(window_play_ids.count(play_id)!=1 for play_id in window_play_ids) or
            any(finisher_play_ids.count(play_id)!=1 for play_id in finisher_play_ids) or
            any(finisher_play_ids.count(play_id)!=1 for play_id in pending_minion_ids)):
        raise ValueError('Pending plays require unique windows and completion markers')
    # A pending minion already owns its unique FinishPlay. Its entry window and
    # completion protect one root; the minion and Combo guards bind their order.
    protected=window_play_ids+[play_id for play_id in finisher_play_ids if play_id not in pending_minion_ids]
    if sorted(protected)!=unresolved:
        raise ValueError('Pending plays and their continuations do not match')
    for work in finishers:
        from .limited_triggers import validate_candidates
        validate_candidates(game._state,work.spellburst_candidates,work.player_id)
        record=play_record(game._state,work.play_id)
        if work.spellburst_candidates and record.kind != CardType.SPELL:
            raise ValueError('Only spells can capture Spellburst candidates')
        if (record.source_id,record.player_id)!=(work.source_id,work.player_id):
            raise ValueError('Invalid suspended play completion')
    codec.decode(codec.encode(frame))
    from .counter_policies import validate_frame as validate_counter_frame
    validate_counter_frame(game)
    from .temporary_cards import validate_temporary_frame
    validate_temporary_frame(game)
    from .weapon_wear import validate_frame as validate_wear_frame
    validate_wear_frame(game)
