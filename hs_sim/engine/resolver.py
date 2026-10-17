"""Transactional, bounded effect execution and explicit reaction checkpoints."""
from __future__ import annotations
from .hand_capacity import hand_capacity

from collections import deque
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, is_dataclass, replace
from enum import Enum

from .actions import Attack, PlayCard
from .colossal import enter_minion, ColossalBattlecry
from .effects import (Buff, Damage, DamageBatch, Destroy, DestroyBatch, Draw, Effect, GainArmor, LoseArmor, Heal, RandomDamage, RandomDamageBatch, RandomDestroy, RandomReturnToHand, Summon,
                      Silence, GrantKeyword, GrantDeathrattle, GrantTrigger, GrantAura, RemoveEnchantment,
                      ReturnToHand, Transform, CopyMinion, FillBoardWithCopies, ChangeControl, ShuffleIntoDeck, GrantSpellDamage, Freeze, Unfreeze,
                      SetStats, SwapStats, DoubleStats, CombatExchange, EquipWeapon, TransferWeapon, ModifyWeapon,
                      ReplaceHeroPower, RefreshHeroPower, SetHeroPowerUses, ReplaceHero,
                      ModifyCost, AddCostModifier, GrantCostAura, GainTemporaryMana, SpendMana, RefreshMana,
                      ChangeManaCrystals, SetManaCap, Overload, UnlockOverload, GainResource, SpendResource,
                      HealBatch, GrantHealthRule, RequestChoice, ChoiceOption, InvokeBehavior, SplitDamage)
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import AbilityInstance, Enchantment, DeathRecord, CardType, ChoiceResult, DamageKind, Entity, Event, HealthFlow, Keyword, Resource, StatReference, TriggerCandidate, Zone
from .costs import pay_cost, modify_cost
from .resources import begin_mana_turn, refresh_mana, mana_effect, resource_effect, lose_armor, consume_mana
from .stats import resolve_stat
from .equipment import total_hero_attack, WEAPON_KEYWORDS, equip_entity, equip_weapon, transfer_weapon, modify_weapon, refresh_equipment, validate_exchange, finish_exchange
from .hero_powers import (ActivateHeroPower, FinishHeroPower, activate_hero_power, finish_hero_power,
                          replace_hero_power, refresh_hero_power, set_hero_power_uses, replace_hero,
                          play_hero, assign_hero_class)
from .combat import calculate_damage, apply_healing, freeze_deadline
from .health_rules import prepare_health, rule_sources
from .registry import RuleContext
from .model import HeroAttackReference, KindredActivation
from .lifecycle import (active_abilities, attachment_id, install_base, install_printed, refresh_entity,
                        remove_attachments, reset_to_definition, consume_keyword, copy_attachments, initialize_dormancy)


@dataclass(frozen=True)
class BehaviorCall:
    behavior_id: str
    context: RuleContext


@dataclass(frozen=True)
class ResolutionFrame:
    choice_id: int
    root_action_number: int
    steps: int
    ending_turn: bool
    prefix: tuple[Effect | BehaviorCall, ...]
    continuation: tuple[Effect | BehaviorCall, ...]
    options: tuple[ChoiceOption, ...]
    on_select: str | None
    paid_hand_choice_boundary: object
    death_deferrals: int = 0
    spell_acceptances: tuple[int, ...] = ()
    paid_hand_acceptances: tuple[int, ...] = ()


@dataclass(frozen=True)
class ResolveChoiceResult(Effect):
    result: ChoiceResult
    behavior_id: str
    kindred: KindredActivation | None = None

    def __post_init__(self):
        if self.kindred is not None:
            from .kindred import validate_prepared_choice
            validate_prepared_choice(self.kindred, self.result)


@dataclass(frozen=True)
class PlayFromHand(Effect):
    action: PlayCard


@dataclass(frozen=True)
class BeginAttack(Effect):
    action: Attack


@dataclass(frozen=True)
class CombatDamage(Effect):
    attacker_id: int
    defender_id: int
    forced: bool = False
    combat_relation: str = 'opponent'
    hero_attack: 'HeroAttackReference | None' = None
    attack_window_id: int | None = None

    def __post_init__(self):
        from .model import validate_combat_relation
        validate_combat_relation(self.combat_relation)
        if self.attack_window_id is not None:
            from .model import _int
            _int(self.attack_window_id, 'character attack window', 1)
        if self.hero_attack is not None:
            if type(self.hero_attack) is not HeroAttackReference: raise ValueError('Expected exact hero attack reference')
            self.hero_attack.__post_init__()
        if type(self.forced) is not bool:
            raise ValueError('Expected forced combat flag')
        if self.combat_relation != 'opponent' and not self.forced:
            raise ValueError('Friendly combat requires a forced attack')


@dataclass(frozen=True)
class FinishPlay(Effect):
    source_id: int
    player_id: int
    target_id: int | None
    play_id: int
    spellburst_candidates: tuple[TriggerCandidate, ...] = ()


@dataclass(frozen=True)
class EndTurnPhase(Effect):
    player_id: int


@dataclass(frozen=True)
class StartNextTurn(Effect):
    pass


@dataclass(frozen=True)
class BeginTurnEvents(Effect):
    pass


@dataclass(frozen=True)
class ExpireTurn(Effect):
    turn: int


@dataclass(frozen=True)
class ThawCharacters(Effect):
    player_id: int


@dataclass(frozen=True)
class RebornMinion(Effect):
    death_id: int


CORE_EFFECTS_VERSION = 'core-effects-v448'


class Mechanics:
    """Trusted effect handlers. Card behaviors normally need only existing effects."""
    def __init__(self, version=CORE_EFFECTS_VERSION):
        if not isinstance(version, str) or not version:
            raise ValueError('Mechanics version must be nonempty')
        self._version = version
        self._handlers = {}
        self._payload_types = {}
        self._frozen = False

    @property
    def version(self):
        return self._version

    def register(self, effect_type: type[Effect], handler: Callable):
        if self._frozen:
            raise ValueError('Mechanics are frozen')
        if not isinstance(effect_type, type) or not issubclass(effect_type, Effect) or not callable(handler):
            raise ValueError('Expected an Effect class and callable handler')
        if effect_type in self._handlers:
            raise ValueError(f'Duplicate effect handler: {effect_type.__name__}')
        self._handlers[effect_type] = handler
        return self

    def freeze(self):
        self._frozen = True
        return self

    def register_payload_type(self, kind):
        """Opt an immutable extension value into the explicit frame codec."""
        if self._frozen:
            raise ValueError('Mechanics are frozen')
        if not isinstance(kind, type) or not (issubclass(kind, Enum) or
                (is_dataclass(kind) and kind.__dataclass_params__.frozen)):
            raise ValueError('Frame payload types must be frozen dataclasses or enums')
        if issubclass(kind, Effect):
            raise ValueError('Effect types require a handler; use Mechanics.register')
        name = f'{kind.__module__}.{kind.__qualname__}'
        if name in self._payload_types:
            raise ValueError('Duplicate frame payload type')
        self._payload_types[name] = kind
        return self

    @property
    def effect_types(self):
        return tuple(self._handlers)

    @property
    def payload_types(self):
        return tuple(self._payload_types.values())

    def replace(self, effect_type, handler):
        """Explicit policy replacement, with a distinct version for replays."""
        if self._frozen or self.version.startswith('core-effects-v'):
            raise ValueError('Replacing a core handler requires unfrozen, versioned mechanics')
        if effect_type not in self._handlers or not callable(handler):
            raise ValueError('Replace requires an existing effect type and callable handler')
        self._handlers[effect_type] = handler
        return self

    def handler(self, effect):
        try:
            return self._handlers[type(effect)]
        except KeyError as exc:
            raise ResolutionError(f'Unsupported effect: {type(effect).__name__}') from exc

    @property
    def signature(self):
        return {'version': self.version, 'effect_types': sorted(
            f'{kind.__module__}.{kind.__qualname__}' for kind in self._handlers),
                'payload_types': sorted(self._payload_types)}


class Resolution:
    def __init__(self, game):
        self.game = game
        self.state = game._state
        self.rules = game.ruleset
        self.registry = game.registry
        self._captured = []
        self._steps = 0
        self.root_action_number = self.state.action_number
        self._choice_request = None
        self._paid_hand_choice_boundary = None
        self.ending_turn = False
        self.removed_weapons = []
        self.death_deferrals = 0

    def charge(self):
        self._steps += 1
        if self._steps > self.rules.max_resolution_steps:
            raise ResolutionLimitExceeded('Resolution step budget exhausted; action rolled back')

    def collect(self, generated):
        """Bound generated work even when an extension returns an iterator."""
        result = []
        for item in generated:
            if len(result) >= self.rules.max_resolution_steps:
                raise ResolutionLimitExceeded('Effect expansion exceeds resolution budget')
            result.append(item)
        return result

    def emit(self, kind, *, source_id=None, target_id=None, player_id=None, amount=0, _spellburst_candidates=(), _capture=True, _end_turn=False, _end_turn_guard=None, _choice_paid_boundary=False, _cast_acceptance=False, _overload_commit=None, _discard_commit=None, _deck_insertion_mode=None, _hero_health_before=None, _corpse_spend_record=None, **data):
        if kind == 'card_burned':
            entity = self.state.entities.get(target_id)
            if entity is not None and (active_abilities(entity, 'on_destroyed') or
                    self.registry.card(entity.card_id).stored_deathrattle) and 'burn_destruction' not in data:
                raise ResolutionError('Native destroyed-card burn requires its original supported overflow profile')
        actual_corpse_debit = kind == 'corpses_spent' or kind == 'resource_spent'
        if actual_corpse_debit and kind == 'resource_spent' and data.get('resource') != Resource.CORPSES.value:
            raise ResolutionError('Resource spending requires its known actual account')
        if actual_corpse_debit != (_corpse_spend_record is not None) or 'corpse_spend' in data:
            raise ResolutionError('Corpse spending requires its original actual debit record')
        if _corpse_spend_record is not None:
            from .model import CorpseSpendRecord
            from .resources import corpse_spend_data
            if type(_corpse_spend_record) is not CorpseSpendRecord or not self.state.corpse_spend_history or self.state.corpse_spend_history[-1] != _corpse_spend_record:
                raise ResolutionError('Corpse event borrowed a non-original debit')
            data.update(corpse_spend_data(self.state, _corpse_spend_record.id))
        if kind=='turn_ended' and not _end_turn:
            raise ResolutionError('A turn-ended fact requires the natural turn boundary')
        if kind == 'spell_cast_accepted' and not _cast_acceptance:
            raise ResolutionError('A cast acceptance fact requires the physical payload boundary')
        if (kind == 'overload_added') != (_overload_commit is not None):
            raise ResolutionError('An overload fact requires its actual original mana operation')
        if (kind == 'card_discarded') != (_discard_commit is not None):
            raise ResolutionError('A discard fact requires its actual original physical movement')
        if kind == 'card_discarded' and not _capture:
            raise ResolutionError('A successful discard requires its original trigger capture')
        if _hero_health_before is not None:
            from .hero_health_history import commit as commit_hero_health, snapshot as hero_health_snapshot
            if 'hero_health_transition' in data or 'hero_health_change_id' in data:
                raise ResolutionError('Hero event cannot record its transition twice')
            data.update(commit_hero_health(self.state, _hero_health_before,
                hero_health_snapshot(self.state.entities[target_id]), kind))
        from .event_normalization import normalize_event_state
        normalize_event_state(self.state, getattr(self, '_cause_reason', kind),
            registry=self.registry,
            cause_source=getattr(self, '_cause_source', None),
            cause_target_id=getattr(self, '_cause_target_id', None))
        from .invoke import synchronize as synchronize_galakrond
        synchronize_galakrond(self.state, self.registry)
        from .mana_ranks import synchronize as synchronize_mana_ranks
        synchronize_mana_ranks(self)
        from .unidentified import synchronize as synchronize_unidentified
        synchronize_unidentified(self)
        from .deck_shuffles import INSERT_EVENTS,publication as shuffle_publication
        if (kind in INSERT_EVENTS) != (_deck_insertion_mode is not None) or 'deck_insertion' in data:
            raise ResolutionError('Deck insertion requires its actual original placement publication')
        if _deck_insertion_mode is not None:
            data['deck_insertion']=shuffle_publication(self,kind,target_id,player_id,source_id,_deck_insertion_mode)
        event = Event(sequence=len(self.game._events) + 1, action=self.state.action_number,
                      kind=kind, source_id=source_id, target_id=target_id,
                      player_id=player_id, amount=amount, data=tuple(sorted(deepcopy(data).items())))
        if kind=='card_burned':
            from .zones import destruction_result
            destruction_result(event)
        if _corpse_spend_record is not None:
            from .resources import corpse_spend_from_event
            if corpse_spend_from_event(event) != _corpse_spend_record:
                raise ResolutionError('Corpse event changed its original debit')
        if 'hero_health_transition' in data or 'hero_health_change_id' in data:
            from .hero_health_history import validate_event as validate_hero_health_event
            validate_hero_health_event(self.state, event)
        if _overload_commit is not None:
            from .overload_history import commit as commit_overload
            commit_overload(self, event, _overload_commit)
        if _discard_commit is not None:
            from .discard_history import commit as commit_discard
            commit_discard(self,event,_discard_commit)
            from .stat_relations import refresh_conditional_attacks
            refresh_conditional_attacks(self.state, self.registry)
        if kind == 'minion_summoned':
            from .successful_summons import commit as commit_successful_summon
            commit_successful_summon(self, event)
        if kind == 'spell_cast_accepted':
            from .spell_casts import accepted_cast
            accepted_cast(self.state, event)
        if _choice_paid_boundary:
            if kind != 'choice_requested':
                raise ResolutionError('Choice payment boundary requires its genuine request event')
            from .paid_hand_acceptance import capture_choice_boundary
            event = capture_choice_boundary(self, event)
        self.game._events.append(event)
        from .hand_choice_followups import note_delivery, note_play, synchronize, ended
        note_delivery(self, event)
        hand_followup_work = note_play(self, event)
        synchronize(self)
        if kind == 'game_ended':
            ended(self)
            from .temporary_hands import ended as end_temporary_hands
            end_temporary_hands(self)
        if _end_turn_guard is not None:
            from .end_turns import pass_guard
            pass_guard(self.state,_end_turn_guard,event)
        if self.game._information is not None:
            self.game._information.record(self.game, event)
        from .hand_mirrors import synchronize as synchronize_hand_mirrors
        synchronize_hand_mirrors(self,event)
        if not _capture:
            return event
        from .end_turns import listeners, prepare, schedule
        end_captures={}
        if _end_turn:
            if kind!='turn_ended' or not self.ending_turn or player_id!=self.state.active_player:
                raise ResolutionError('End-turn subjects require the natural ending boundary')
            end_captures,self._end_turn_finish=prepare(self,event)
        for controller, _, entity_id, player_effect in listeners(self.state):
            if player_effect is not None:
                for index,trigger in enumerate(self.registry.player_effect(player_effect.spec_id).triggers):
                    if trigger.event == kind:
                        capture=end_captures.get(('player_effect',player_effect.id,index))
                        if trigger.end_turn is not None:
                            if not _end_turn: raise ResolutionError('Classified end-turn body requires a natural boundary')
                            if capture is None: continue
                            self._captured.extend(schedule(self,capture));continue
                        call=self.call(trigger.behavior_id, entity_id, controller,
                            target_id=target_id, event=event, player_effect=player_effect)
                        self._captured.append(call)
                continue
            entity = self.state.entities[entity_id]
            if entity.zone == Zone.SECRET:
                spec = self.registry.card(entity.card_id).secret
                if kind in spec.events and source_id != entity.id:
                    from .secrets import CheckSecret
                    self._captured.append(CheckSecret(entity.id, entity.secret_instance_id, event))
                continue
            if entity.zone == Zone.QUEST:
                progress = entity.quest_progress
                stage = self.registry.card(entity.card_id).quest.stages[progress.stage]
                if (not progress.completing and kind in stage.events and
                        not (source_id == entity.id and kind in ('card_committed', 'card_played'))):
                    self._captured.append(self.call(stage.progress_behavior, entity.id, entity.controller, event=event))
                continue
            for trigger in sorted((*active_abilities(entity, 'trigger'), *active_abilities(entity, 'dormant_trigger'),
                                   *active_abilities(entity, 'limited_trigger'),
                                   *active_abilities(entity, 'counter_policy')), key=lambda a:a.id):
                if trigger.kind == 'counter_policy':
                    from .counter_policies import capture
                    work = capture(self, entity, trigger, event)
                    if work is not None:
                        self._captured.append(work)
                    continue
                if trigger.kind == 'limited_trigger':
                    from .limited_triggers import capture as capture_finite, CheckLimitedTrigger, candidate
                    captured=end_captures.get(('ability',entity_id,trigger.id))
                    if trigger.end_turn_spec is not None and trigger.limited_trigger.event==kind:
                        if not _end_turn: raise ResolutionError('Classified finite end-turn body requires a natural boundary')
                        if captured is None: continue
                        self._captured.extend(schedule(self,captured));continue
                    else:
                        work = capture_finite(self, entity, trigger, event, _spellburst_candidates)
                    if work is not None:
                        self._captured.append(work)
                    continue
                if trigger.event == kind:
                    capture=end_captures.get(('ability',entity_id,trigger.id))
                    if trigger.end_turn_spec is not None:
                        if not _end_turn: raise ResolutionError('Classified end-turn body requires a natural boundary')
                        if capture is None: continue
                        self._captured.extend(schedule(self,capture));continue
                    call=self.call(trigger.behavior_id, entity_id, entity.controller,target_id=target_id,event=event,
                                   trigger=None)
                    if entity.zone == Zone.HERO_POWER:
                        from .hero_powers import CheckHeroPowerTrigger
                        self._captured.append(CheckHeroPowerTrigger(call.behavior_id,call.context,trigger.id))
                    else:
                        self._captured.append(call)
        from .hand_progress import capture_hand_progress
        self._captured.extend(capture_hand_progress(self, event))
        self._captured.extend(hand_followup_work)
        if _discard_commit is not None:
            from .discard_history import capture_body
            own_body = capture_body(self, event)
            self._captured.extend(own_body)
        if kind=='card_burned' and 'burn_destruction' in data:
            from .zones import capture_destroyed_body
            own_body=capture_destroyed_body(self,event)
            self._captured.extend(own_body)
        return event

    def call(self, behavior_id, source_id, player_id, target_id=None, event=None, death=None, choice=None, player_effect=None, window=None, play=None, trigger=None, cast=None, draw=None, power=None, battlecry=None, combo=None, deathrattle=None, power_payload=None, end_turn=None, physical=None, discard=None, kindred=None):
        if discard is not None:
            if target_id is not None or any(value is not None for value in
                    (death,choice,player_effect,window,play,cast,draw,power,battlecry,combo,deathrattle,power_payload,end_turn,physical)):
                raise ResolutionError('Own-discard acceptance is independent of other body roots')
            call = BehaviorCall(behavior_id, RuleContext(deepcopy(self.state), source_id, player_id,
                event=deepcopy(event), trigger=deepcopy(trigger), discard=discard))
            from .discard_history import validate_call as validate_discard_call
            validate_discard_call(call, self.registry)
            return call
        if play is None and event is not None and (play_id := dict(event.data).get('play_id')) is not None:
            from .play_history import play_record
            play = play_record(self.state, play_id)
        if cast is None:
            from .spell_casts import active_cast, cast_record
            cast_id = dict(event.data).get('cast_id') if event is not None else None
            cast = cast_record(self.state, cast_id) if cast_id is not None else active_cast(self.state, source_id, player_id)
        if draw is None:
            from .draw_casts import draw_record, active_after_draw
            draw_id = dict(event.data).get('draw_id') if event is not None else None
            if draw_id is None and cast is not None: draw_id = cast.draw_id
            draw = draw_record(self.state, draw_id) if draw_id is not None else active_after_draw(self.state,source_id,player_id)
        if cast is None and draw is not None and draw.cast_id is not None:
            from .spell_casts import cast_record
            cast = cast_record(self.state, draw.cast_id)
        if power is None:
            from .hero_powers import power_record, active_power
            power_id = dict(event.data).get('power_id') if event is not None else None
            power = power_record(self.state,power_id) if power_id is not None else active_power(self.state,source_id,player_id)
        if combo is None:
            from .combos import active_combo, combo_record
            combo_id = dict(event.data).get('combo_id') if event is not None else None
            combo = combo_record(self.state,combo_id) if combo_id is not None else active_combo(self.state,source_id,player_id)
        if battlecry is None:
            from .battlecries import active_battlecry, battlecry_record
            battlecry_id = dict(event.data).get('battlecry_id') if event is not None else None
            battlecry = battlecry_record(self.state,battlecry_id) if battlecry_id is not None else active_battlecry(self.state,source_id,player_id)
        rewind = self.game._rewind
        attempt = rewind.attempt if rewind is not None and source_id == rewind.action.entity_id else 0
        if power is not None:
            from .actions import UseHeroPower
            if (rewind is None or type(rewind.action) is not UseHeroPower or power.origin != 'manual' or
                    power.id != len(rewind.before.hero_power_history)+1):
                attempt = 0
        from .rewind_outcomes import active_outcome
        retained = active_outcome(self.state, source_id, player_id, power_id=power.id if power else None)
        if retained is not None: attempt = retained.completed
        if physical is None:
            from .whole_card_physical import active_progress
            physical = active_progress(self.state, source_id, player_id)
        if battlecry is not None and battlecry.origin != 'hand':
            own_physical_result = (retained is not None and retained.physical_child_id is not None
                and physical is not None and physical.child_id == retained.physical_child_id
                and battlecry.physical_child_id == physical.child_id and battlecry.outcome_id == retained.id
                and physical.active_battlecry_id == battlecry.id and source_id == battlecry.source_id)
            if not own_physical_result: attempt = 0
        return BehaviorCall(behavior_id, RuleContext(deepcopy(self.state), source_id,
                                                     player_id, target_id, deepcopy(event), death, choice, player_effect, window, play, trigger, cast, draw, attempt, power, battlecry, combo, deathrattle, power_payload,end_turn,physical,kindred=kindred))

    def player(self, player_id):
        if type(player_id) is not int or player_id not in self.state.players:
            raise ResolutionError(f'Unknown player: {player_id}')
        return self.state.players[player_id]

    def live_character(self, entity_id):
        if type(entity_id) is not int:
            raise ResolutionError('Entity ID must be an integer')
        entity = self.state.entities.get(entity_id)
        return entity if entity is not None and entity.active and entity.is_character and entity.zone in (Zone.HERO, Zone.BOARD) else None

    def stale(self, effect, target_id):
        self.emit('effect_skipped', target_id=target_id, effect=type(effect).__name__, reason='target_not_in_play')

    def create_entity(self, player_id, card_id, zone, position=None, ready=False, *, components=(), hand_entry_reason='created', additional_hero_power=False, entry_herald_count=None, interactable_object=False, entry_dormant_turns=None):
        from .entity_materialization import create_entity
        return create_entity(self.state, self.registry, player_id, card_id, zone, position, ready,
            components=components, hand_entry_reason=hand_entry_reason,
            additional_hero_power=additional_hero_power, entry_herald_count=entry_herald_count,
            interactable_object=interactable_object, entry_dormant_turns=entry_dormant_turns)

    def move(self, entity, zone, position=None, *, hand_entry_reason='move', controller_id=None, draw_id=None):
        previous_zone = entity.zone
        drawn_spell_transfer = False
        if draw_id is not None:
            from .draw_casts import draw_record
            drawn = draw_record(self.state, draw_id)
            drawn_spell_transfer = (previous_zone == Zone.DECK and zone == Zone.GRAVEYARD
                and entity.kind == CardType.SPELL and not drawn.interrupted
                and drawn.id == len(self.state.draw_history)
                and (drawn.entity_id,drawn.card_id,drawn.player_id,drawn.outcome,drawn.phase) ==
                    (entity.id,entity.card_id,controller_id,'cast','pending_cast')
                and drawn.spec == self.registry.card(entity.card_id).cast_when_drawn)
            if not drawn_spell_transfer:
                raise ResolutionError('Drawn spell transfer lost its original pending physical draw')
        if controller_id is not None:
            initial_minion=previous_zone==Zone.PLAY and zone==Zone.BOARD and entity.kind==CardType.MINION
            weapon_transfer=(previous_zone==zone==Zone.WEAPON and entity.kind==CardType.WEAPON
                and controller_id!=entity.controller and self.player(entity.controller).weapon_id==entity.id)
            if type(controller_id) is not int or controller_id not in (1,2) or not (initial_minion or weapon_transfer or drawn_spell_transfer):
                raise ResolutionError('Controller movement requires its exact pending minion, weapon or drawn spell transfer')
        if zone == Zone.DECK:
            from .prepare import enter_deck
            enter_deck(entity)
        player = self.player(entity.controller)
        if entity.zone == Zone.HERO or zone == Zone.HERO:
            raise ResolutionError('Moving heroes is not supported')
        if zone == Zone.DECK and self.game._information is not None:
            self.game._information.conceal(entity.id)
        slots = {Zone.WEAPON: 'weapon_id', Zone.HERO_POWER: 'hero_power_id'}
        if entity.zone == Zone.HERO_POWER and entity.id in player.additional_hero_power_ids:
            player.additional_hero_power_ids.remove(entity.id)
        elif entity.zone in slots:
            setattr(player, slots[entity.zone], None)
        else:
            getattr(player, entity.zone.value.lower()).remove(entity.id)
        if controller_id is not None:
            entity.controller = controller_id
            player = self.player(controller_id)
        entity.zone = zone
        entity.zone_epoch += 1
        entity.death_cause = None
        from .timed_keywords import arm
        arm(self.state, entity)
        from .lifecycle import renew_hand_progress
        renew_hand_progress(self.state, entity, previous_zone=previous_zone)
        initialize_dormancy(self.state, entity, self.registry.card(entity.card_id))
        if zone in slots:
            if getattr(player, slots[zone]) is not None:
                raise ResolutionError('Entity slot is already occupied')
            setattr(player, slots[zone], entity.id)
        else:
            dest = getattr(player, zone.value.lower())
            if position is None:
                dest.append(entity.id)
            else:
                dest.insert(max(0, min(position, len(dest))), entity.id)
        if zone in (Zone.BOARD, Zone.WEAPON, Zone.QUEST, Zone.SECRET, Zone.HERO_POWER):
            entity.summoned_turn = self.state.turn
            entity.entered_order = self.state.next_order
            self.state.next_order += 1
        if zone != Zone.BOARD or entity.kind != CardType.MINION:
            entity.board_presence_id = None
        elif previous_zone != Zone.BOARD:
            entity.board_presence_id = entity.entered_order
        from .herald import initialize_instance
        initialize_instance(self.state, entity, self.registry.card(entity.card_id))
        if zone == Zone.HAND and previous_zone != Zone.HAND and hand_entry_reason is not None:
            from .hand_history import enter_hand
            enter_hand(self.state, entity, previous_zone, hand_entry_reason)

    def refresh_auras(self, include_dying=False, *, emit_freeze_changes=True, rebind_frozen_ids=()):
        from .stat_auras import matches_card_identity
        # Calculate simultaneously, using the old settled health to select sources.
        # Resetting health auras before selecting sources breaks mutual support.
        bonuses = {i: [0, 0] for i in self.state.entities}
        old_health = {i: e.health for i, e in self.state.entities.items()}
        old_aura = {i: e.aura_health for i, e in self.state.entities.items()}
        old_conditional = {i: e.conditional_health for i, e in self.state.entities.items()}
        for entity in self.state.entities.values():
            refresh_entity(entity)
        for player in self.state.players.values():
            for effect in player.player_effects:
                for aura in self.registry.player_effect(effect.spec_id).auras:
                    for target_id in player.board:
                        target = self.state.entities[target_id]
                        if (target.active and target.kind == CardType.MINION and
                                matches_card_identity(target, aura.card_ids)):
                            bonuses[target_id][0] += aura.attack
                            bonuses[target_id][1] += aura.health
            for source_id in player.board:
                source = self.state.entities[source_id]
                if not source.active or (not include_dying and (source.health <= 0 or source.doomed)):
                    continue
                for aura in active_abilities(source, 'aura'):
                    if aura.aura_target != 'friendly_minions':
                        continue
                    targets = player.board
                    if aura.adjacent_only:
                        index = player.board.index(source_id)
                        targets = player.board[max(0, index - 1):index] + player.board[index + 1:index + 2]
                    for target_id in targets:
                        if (self.state.entities[target_id].active and self.state.entities[target_id].kind == CardType.MINION
                                and (target_id != source_id or aura.include_self)):
                            if aura.aura_tribes_any:
                                from .tribes import has_any_tribe
                                if not has_any_tribe(self.registry, self.state.entities[target_id],
                                                     aura.aura_tribes_any, basis='current'):
                                    continue
                            if not matches_card_identity(self.state.entities[target_id], aura.aura_card_ids):
                                continue
                            bonuses[target_id][0] += aura.attack
                            bonuses[target_id][1] += aura.health
        from .stat_relations import refresh_conditional_health
        refresh_conditional_health(self.state, clamp=False)
        for entity_id, entity in self.state.entities.items():
            entity.aura_attack, entity.aura_health = bonuses[entity_id]
            if entity.aura_health + entity.conditional_health < old_aura[entity_id] + old_conditional[entity_id]:
                entity.damage = max(0, entity.max_health - old_health[entity_id])
        from .keyword_auras import refresh_keyword_auras
        from .stat_auras import refresh_weapon_auras,refresh_hero_auras
        from .stat_relations import refresh_conditional_attacks
        # Weapon conditions read health after the existing health-aura clamp.
        refresh_weapon_auras(self.state, include_dying=include_dying)
        refresh_hero_auras(self.state, include_dying=include_dying)
        refresh_keyword_auras(self.state, self.registry, include_dying=include_dying)
        refresh_conditional_attacks(self.state, self.registry)
        refresh_equipment(self.state)
        from .combat import can_be_frozen
        thawed = tuple(e for e in self.state.entities.values() if e.active and e.is_character
            and e.zone in (Zone.BOARD, Zone.HERO) and e.frozen and not can_be_frozen(e))
        # Settle the entire contribution before publishing any thaw reaction.
        for entity in thawed:
            entity.frozen_until_owner_turn = None
        # A frozen physical minion's deadline belongs to its current controller.
        # Rebind only actual control moves, after all derived contributions and
        # genuine thaw have settled, before any observer captures the new state.
        for entity_id in dict.fromkeys(rebind_frozen_ids):
            entity = self.state.entities[entity_id]
            if entity.frozen:
                entity.frozen_until_owner_turn = freeze_deadline(self.state, entity,
                    ending_turn=self.ending_turn, registry=self.registry)
        if emit_freeze_changes:
            for entity in thawed:
                self.emit("unfrozen", target_id=entity.id, reason="cannot_be_frozen")
        from .death_causes import sync
        sync(self, getattr(self, '_cause_reason', 'aura_change'))
        from .dormancy import capture_board_full
        self._captured.extend(capture_board_full(self))

    def pay_cost(self, player, source):
        pay_cost(self, player, source)

    def record_death(self, entity, position, batch=None):
        from .death_causes import mark
        if entity.death_cause is None:
            mark(self, entity, 'health_state', 'death_checkpoint')
        if batch is None:
            batch = self.state.next_death_batch
            self.state.next_death_batch += 1
        record = DeathRecord(
            id=self.state.next_death_id, batch=batch, entity_id=entity.id, card_id=entity.card_id,
            owner=entity.owner, controller=entity.controller, position=position,
            turn=self.state.turn, attack=entity.attack, max_health=entity.max_health, damage=entity.damage,
            base_attack=entity.base_attack, base_health=entity.base_health, base_cost=entity.base_cost, cause=entity.death_cause,
            keywords=tuple(sorted(entity.keywords)), abilities=tuple(entity.abilities),
            enchantments=tuple(entity.enchantments), frozen_until_owner_turn=entity.frozen_until_owner_turn,
            zone=entity.zone, durability=entity.durability, corpse_value=entity.corpse_value, components=entity.components,
            herald_rank=entity.herald_rank, jade_size=entity.jade_size)
        self.state.next_death_id += 1
        self.state.death_history.append(record)
        return record

    def death_checkpoint(self):
        from .death_causes import sync
        sync(self, getattr(self, '_cause_reason', 'death_checkpoint'))
        from .deathrattles import schedule_group, capture_prohibition
        deathrattles = []
        reborns = []
        # Replaced weapons have already left their singleton slot. Announce their
        # destruction after installation, before other death batches are gathered.
        for record, reason in self.removed_weapons:
            record = capture_prohibition(self, record)
            event = self.emit('weapon_destroyed', source_id=record.entity_id, target_id=record.entity_id,
                              player_id=record.controller, death_id=record.id, reason=reason)
            deathrattles.extend(schedule_group(self,record.entity_id,record.controller,
                tuple(a for a in record.abilities if a.kind == 'deathrattle' and not a.consumed),event=event,death=record))
        self.removed_weapons.clear()
        while True:
            dead = [i for player in self.state.players.values() for i in player.board
                    if self.state.entities[i].active and (self.state.entities[i].doomed or
                        (self.state.entities[i].durability <= 0 if self.state.entities[i].kind == CardType.LOCATION
                         else self.state.entities[i].health <= 0))]
            dead.extend(player.weapon_id for player in self.state.players.values()
                        if player.weapon_id is not None and
                        (self.state.entities[player.weapon_id].durability <= 0 or self.state.entities[player.weapon_id].doomed))
            if not dead:
                break
            self.charge()
            dead = self.rules.entity_order(self.state, dead)
            positions = {i: self.player(self.state.entities[i].controller).board.index(i)
                         if self.state.entities[i].zone == Zone.BOARD else 0 for i in dead}
            records = {}
            batch = self.state.next_death_batch
            self.state.next_death_batch += 1
            for entity_id in dead:
                entity = self.state.entities[entity_id]
                record = self.record_death(entity, positions[entity_id], batch)
                records[entity_id] = record
                if entity.zone == Zone.BOARD and Keyword.REBORN in entity.keywords:
                    consume_keyword(entity, Keyword.REBORN)
                    reborns.append(RebornMinion(record.id))
            for entity_id in dead:
                self.move(self.state.entities[entity_id], Zone.GRAVEYARD)
            self.refresh_auras()
            # Credit the complete batch before any death/ordinary trigger
            # captures a view; weapons and no-corpse minions contribute zero.
            records = {i: capture_prohibition(self, d) for i, d in records.items()}
            from .corpse_gains import gain_amount
            credits = {i: gain_amount(self.state, self.registry, d.controller, d.corpse_value)
                       for i, d in records.items()}
            for record in records.values():
                self.player(record.controller).resources[Resource.CORPSES] += credits[record.entity_id]
            from .starships import contribute
            contribute(self, records.values())
            for record in records.values():
                if record.corpse_value:
                    self.emit('resource_gained', source_id=record.entity_id, player_id=record.controller,
                              amount=credits[record.entity_id], resource=Resource.CORPSES.value, death_id=record.id)
            for entity_id in dead:
                entity = self.state.entities[entity_id]
                event = self.emit('location_destroyed' if entity.kind == CardType.LOCATION else
                                  'minion_died' if records[entity_id].zone == Zone.BOARD else 'weapon_destroyed',
                                  source_id=entity_id, target_id=entity_id,
                                  player_id=entity.controller, position=positions[entity_id], card_id=entity.card_id,
                                  death_id=records[entity_id].id, batch=batch)
                deathrattles.extend(schedule_group(self,entity_id,entity.controller,
                    tuple(a for a in records[entity_id].abilities if a.kind == 'deathrattle' and not a.consumed),
                    event=event,death=records[entity_id]))
        from .hero_lethal_windows import checkpoint as hero_lethal_checkpoint
        self._hero_new_work = hero_lethal_checkpoint(self)
        return [*deathrattles, *reborns]

    def run(self, effects: Iterable[Effect | BehaviorCall]):
        from .paid_hand_acceptance import FinishPaidHandAcceptance
        from .hero_lethal_windows import CONTROL as HERO_CONTROL, route as route_hero_work
        from .random_split_damage import FinishSplitPacket, FinishRandomSplitRoot
        from .rewind import RetryRewind
        from .resource_operations import InvokeResourcePayload, FinishResourceConsumption
        from .deathrattles import InvokeDeathrattle, FinishDeathrattle, FinishDeathrattleBatch
        from .battlecry_repeats import FinishBattlecryAcceptance
        from .spell_acceptance import FinishSpellAcceptance
        from .combo_acceptance import FinishComboAcceptance
        from .power_payloads import InvokeHeroPowerPayload, FinishHeroPowerPayload
        from .end_turns import InvokeEndTurn, FinishEndTurn, FinishEndTurnBatch, CheckActiveEndTurn
        queue = deque(effects)
        self._work_queue = queue
        while queue and self.state.status == 'playing':
            self.charge()
            work = queue.popleft()
            from .whole_card_replays import validate_control_work as validate_whole_card_control_work
            validate_whole_card_control_work(self, work)
            from .paid_hand_acceptance import validate_control_work as validate_paid_hand_control_work
            validate_paid_hand_control_work(self, work)
            from .owner_turns import validate_control_work as validate_owner_control_work
            validate_owner_control_work(self, work)
            from .deathrattle_acceptance import validate_control_work
            validate_control_work(self,work)
            from .hero_power_acceptance import validate_control_work as validate_power_control_work
            validate_power_control_work(self,work)
            from .end_turn_acceptance import validate_control_work as validate_end_turn_control_work
            validate_end_turn_control_work(self,work)
            from .spell_acceptance import validate_control_work as validate_spell_control_work
            validate_spell_control_work(self,work)
            transparent_power_guard=(type(work) is CheckActiveEndTurn and
                work.context.end_turn.subject.ability.kind!='limited_trigger')
            from .pool_summons import CONTROL as POOL_SUMMON_CONTROL
            from .ordered_group_batches import CONTROL as ORDERED_GROUP_CONTROL
            from .discovery_summons import CONTROL as DISCOVERY_SUMMON_CONTROL
            from .hand_choice_followups import CONTROL as HAND_FOLLOWUP_CONTROL
            from .summon_quantities import SummonByCard,FinishCardSummon
            from .source_stat_summons import SummonBySourceStats
            from .whole_card_replays import DIAGNOSTIC_CONTROL as WHOLE_CARD_CONTROL
            from .indirect_body_targets import CONTROL as INDIRECT_BODY_CONTROL
            from .historical_body_targets import CONTROL as HISTORICAL_BODY_CONTROL
            if type(work) in (*HAND_FOLLOWUP_CONTROL,*HISTORICAL_BODY_CONTROL,*INDIRECT_BODY_CONTROL,*WHOLE_CARD_CONTROL,*DISCOVERY_SUMMON_CONTROL,*POOL_SUMMON_CONTROL,*ORDERED_GROUP_CONTROL,SummonBySourceStats,SummonByCard,FinishCardSummon,InvokeDeathrattle, FinishDeathrattle, FinishDeathrattleBatch, FinishBattlecryAcceptance, FinishSpellAcceptance, FinishComboAcceptance, FinishPaidHandAcceptance, InvokeHeroPowerPayload, FinishHeroPowerPayload,
                              InvokeEndTurn,FinishEndTurn,FinishEndTurnBatch,InvokeResourcePayload,FinishResourceConsumption,FinishSplitPacket,FinishRandomSplitRoot,*HERO_CONTROL) or transparent_power_guard:
                # Diagnostic control work preserves the old callback window.
                generated = self.game.mechanics.handler(work)(self,work)
                if generated is not None: queue.extendleft(reversed(self.collect(generated)))
                continue
            if isinstance(work, BehaviorCall):
                from .discard_history import validate_call as validate_discard_call
                validate_discard_call(work, self.registry)
                from .zones import validate_destroyed_call
                validate_destroyed_call(work, self.registry)
                if (work.context.trigger is not None and work.context.trigger.kind == 'on_destroyed' and
                        (work.context.event.sequence > len(self.game._events) or
                         self.game._events[work.context.event.sequence-1] != work.context.event)):
                    raise ResolutionError('Native destroyed body lost its actual original event')
                generated = self.registry.behavior(work.behavior_id)(work.context)
                continuation = self.collect(generated)
                if any(not isinstance(item, Effect) for item in continuation):
                    raise ResolutionError(f'{work.behavior_id} returned a non-Effect')
                # A behavior is a pure planner, not an additional effect checkpoint.
                queue.extendleft(reversed(continuation))
                continue
            if not isinstance(work, Effect):
                raise ResolutionError(f'Invalid work item: {type(work).__name__}')
            if type(work) is RetryRewind:
                # Restoring a valid checkpoint is interpreter control, not a
                # gameplay stat change/death/attack-gain trigger checkpoint.
                queue.extendleft(reversed(self.collect(self.game.mechanics.handler(work)(self, work))))
                continue
            had_hero_root = self.state.active_hero_lethal_root_id
            self._hero_new_work = []
            hero_attacks = {p.id: total_hero_attack(self.state, p) for p in self.state.players.values()}
            self._cause_reason = type(work).__name__
            self._cause_target_id = getattr(work, 'target_id', None)
            self._cause_source = deepcopy(self.state.entities.get(getattr(work, 'source_id', None)))
            generated = self.game.mechanics.handler(work)(self, work)
            continuation = [] if generated is None else self.collect(generated)
            if any(not isinstance(item, (Effect, BehaviorCall)) for item in continuation):
                raise ResolutionError('Effect handler returned invalid work')
            from .shatter import settle_hands
            settle_hands(self)
            self.refresh_auras(include_dying=True)
            for player in self.state.players.values():
                gain = total_hero_attack(self.state, player) - hero_attacks[player.id]
                if gain > 0:
                    self.emit('hero_attack_gained', target_id=player.hero_id, player_id=player.id, amount=gain)
            # A launch resolves its captured abilities before removing dying
            # minions. Hero death still uses the existing immediate terminal
            # policy, flushing the board before abandoning the remaining work.
            defer = self.death_deferrals > 0 and all(
                self.state.entities[p.hero_id].health > 0 and not self.state.entities[p.hero_id].doomed
                for p in self.state.players.values())
            deathrattles = [] if defer else self.death_checkpoint()
            self.refresh_auras(include_dying=defer)
            triggers, self._captured = self._captured, []
            hero_mode = self.state.active_hero_lethal_root_id is not None
            routed = route_hero_work(self,queue,triggers,deathrattles,continuation,self._hero_new_work,
                new_root=had_hero_root is None and hero_mode)
            if self._choice_request is not None and self.state.status == 'playing':
                from .continuations import FrameCodec
                if self._steps >= self.rules.max_resolution_steps:
                    raise ResolutionLimitExceeded('No resolution budget remains for the requested choice')
                request, self._choice_request = self._choice_request, None
                frame = ResolutionFrame(self.state.pending_choice.id, self.root_action_number, self._steps,
                                        self.ending_turn, tuple(routed if hero_mode else self.rules.reactions(triggers, deathrattles, [])),
                                        tuple(queue) if hero_mode else tuple(continuation) + tuple(queue), request.options, request.on_select,
                                        self._paid_hand_choice_boundary, self.death_deferrals)
                frame = replace(frame, spell_acceptances=tuple(w.play_id for w in
                    (*frame.prefix, *frame.continuation) if type(w) is FinishSpellAcceptance))
                frame = replace(frame, paid_hand_acceptances=tuple(w.play_id for w in
                    (*frame.prefix, *frame.continuation) if type(w) is FinishPaidHandAcceptance))
                # Validate before committing a waiting boundary. Unsupported
                # queued work must fail now, not after the user picks an option.
                codec = FrameCodec(self.game.mechanics, self.registry)
                self.game._frame = codec.decode(codec.encode(frame))
                return
            queue.extendleft(reversed(routed))
        if self.death_deferrals and self.state.status == 'playing':
            raise ResolutionError('Resolution ended with an unclosed death deferral boundary')
        self.death_deferrals = 0
        if self.state.status != 'playing':
            from .kindred import interrupt as interrupt_kindred
            interrupt_kindred(self,queue)
            from .choose_policies import interrupt as interrupt_choose_policies
            interrupt_choose_policies(self, queue)
            from .spell_casts import validate_target_queue
            validate_target_queue(self.state, self.registry, tuple(queue))
            from .whole_card_replay_state import interrupt as interrupt_whole_card_replays
            interrupt_whole_card_replays(self)
            from .summon_quantities import interrupt as interrupt_card_summons
            interrupt_card_summons(self)
            from .pool_summons import interrupt as interrupt_pool_summons
            interrupt_pool_summons(self)
            from .ordered_group_batches import interrupt as interrupt_ordered_groups
            interrupt_ordered_groups(self)
            from .discovery_summons import interrupt as interrupt_discovery_summons
            interrupt_discovery_summons(self)
            from .recruit_summons import interrupt as interrupt_recruit_summons
            interrupt_recruit_summons(self)
            from .resurrection_summons import interrupt as interrupt_resurrection_summons
            interrupt_resurrection_summons(self)
            from .random_split_damage import interrupt as interrupt_split_damage
            interrupt_split_damage(self, queue)
            from .owner_turns import interrupt_owner_start
            interrupt_owner_start(self, queue)
            from .owner_turns import validate_control_work as validate_owner_control_work
            for work in queue:
                validate_owner_control_work(self, work)
            from .combo_acceptance import validate_terminal_queue
            validate_terminal_queue(self,queue)
            from .deathrattle_acceptance import validate_terminal_queue as validate_deathrattle_terminal_queue
            validate_deathrattle_terminal_queue(self,queue)
            from .hero_power_acceptance import validate_terminal_queue as validate_power_terminal_queue
            validate_power_terminal_queue(self,queue)
            from .end_turn_acceptance import validate_terminal_queue as validate_end_turn_terminal_queue
            validate_end_turn_terminal_queue(self,queue)
            from .spell_acceptance import validate_terminal_queue as validate_spell_terminal_queue
            validate_spell_terminal_queue(self,queue)
            from .paid_hand_acceptance import validate_terminal_queue as validate_paid_hand_terminal_queue
            validate_paid_hand_terminal_queue(self, queue)
            from .indirect_body_targets import validate_terminal_queue as validate_indirect_terminal_queue
            validate_indirect_terminal_queue(self,queue)
            from .historical_body_targets import validate_terminal_queue as validate_historical_terminal_queue
            validate_historical_terminal_queue(self,queue)
            from .resource_operations import interrupt as interrupt_resource_operations
            interrupt_resource_operations(self, queue)
            from .deathrattles import interrupt
            interrupt(self.state)
            from .power_payloads import interrupt as interrupt_power_payloads
            interrupt_power_payloads(self.state)
            from .end_turns import interrupt as interrupt_end_turns
            interrupt_end_turns(self.state)
            self.game._rewind = None
            for player in self.state.players.values():
                for source_id in tuple(player.pending_plays):
                    self.move(self.state.entities[source_id], Zone.GRAVEYARD)
            from .hero_attack_history import interrupt as interrupt_hero_attacks
            interrupt_hero_attacks(self,queue)
            from .character_attacks import interrupt as interrupt_character_attacks
            interrupt_character_attacks(self,queue)
            self.state.action_windows.clear()
            self.state.draw_history = [replace(d, interrupted=True)
                if not d.completed and not d.interrupted else d for d in self.state.draw_history]
            self.state.hero_power_history = [replace(p, interrupted=True)
                if not p.completed and not p.interrupted else p for p in self.state.hero_power_history]
            self.state.battlecry_batches = [replace(b, running=False, interrupted=True)
                if not b.finished and not b.interrupted else b for b in self.state.battlecry_batches]
            self.state.combo_batches = [replace(b,running=False,interrupted=True)
                if not b.finished and not b.interrupted else b for b in self.state.combo_batches]
            self.state.combo_history = [replace(b, interrupted=True)
                if not b.completed and not b.interrupted else b for b in self.state.combo_history]
            self.state.battlecry_history = [replace(b, interrupted=True)
                if not b.completed and not b.interrupted else b for b in self.state.battlecry_history]
            from .indirect_body_targets import interrupt as interrupt_indirect_bodies
            interrupt_indirect_bodies(self.state)
            from .historical_body_targets import interrupt as interrupt_historical_bodies
            interrupt_historical_bodies(self.state)
            self.state.cast_history = [replace(c, interrupted=True)
                if not c.completed and not c.interrupted else c for c in self.state.cast_history]
            self.state.spell_repeats = [replace(x, running=False, interrupted=True)
                if not x.finished and not x.interrupted else x for x in self.state.spell_repeats]
            self.state.rewind_outcomes = [replace(x, running=False, interrupted=True)
                if not x.finished and not x.interrupted else x for x in self.state.rewind_outcomes]
            self.state.colossal_history=[replace(x,completed=True,canceled=True) if not x.completed else x for x in self.state.colossal_history]
            from .play_history import update_play
            for record in tuple(self.state.play_history):
                if not record.completed and not record.interrupted:
                    update_play(self.state, record.id, interrupted=True)
        elif self.state.action_windows:
            raise ResolutionError('Resolution ended with an unclosed action window')
        self._captured.clear()
        self._paid_hand_choice_boundary = None
        self.game._frame = None
        self.state.pending_choice = None


def nonnegative(value, name='amount'):
    if type(value) is not int or value < 0:
        raise ResolutionError(f'{name} must be a nonnegative integer')


def settle_health_batch(r, instructions, combat=None, *, split_link=None, partition_request=None, numeric_limit=None, apply_spell_bonus=True,player_effect=None,player_effect_owner=None):
    from .health_loss import replacement_for, commit_loss
    from .model import HealthLossKind
    from .health_outcomes import capture_result
    # Freeze eligibility and source statistics once for the entire simultaneous
    # batch, including its intrinsic lifesteal. Numeric shields/armor still
    # consume in packet order without an intervening death checkpoint.
    state = deepcopy(r.state)
    rules = rule_sources(state)
    if player_effect is not None and (combat is not None or len(instructions)!=1 or partition_request is not None):
        raise ResolutionError('Logical player damage requires one independent non-combat packet')
    if numeric_limit is not None and (combat is not None or split_link is not None or
            partition_request is not None or len(instructions) != 1):
        raise ResolutionError('Infinite damage requires its single original non-combat health request')
    if split_link is not None and (combat is not None or len(instructions) != 1):
        raise ResolutionError('An internal split packet requires exactly one non-combat instruction')
    if partition_request is not None:
        from .excess_damage import prepare_partition
        if instructions or combat is not None or split_link is not None:
            raise ResolutionError('Partition batch cannot borrow unrelated instructions or combat/split controls')
        instructions, packets = prepare_partition(state, r.registry, partition_request, rules)
        if not instructions:
            r.stale(partition_request, partition_request.minion.entity_id)
            return ()
    else:
        packets = [prepare_health(state, r.registry, instruction, rules=rules, split_link=split_link,
                                  numeric_limit=numeric_limit, apply_spell_bonus=apply_spell_bonus,
                                  player_effect=player_effect,player_effect_owner=player_effect_owner) for instruction in instructions]
    for instruction in instructions:
        instruction.__post_init__()
        if instruction.on_result is not None:
            r.registry.behavior(instruction.on_result)
    pending_events = []
    lifesteals = []
    callbacks = {}
    batch_id, packet_index = len(r.game._events)+1, 0

    def settle(packet, on_result=None):
        nonlocal packet_index
        packet_index += 1
        r.charge()
        target = r.live_character(packet.target_id)
        if target is None:
            pending_events.append(('effect_skipped', dict(target_id=packet.target_id,
                                  effect='Damage' if packet.original_flow == HealthFlow.DAMAGE else 'Heal',
                                  reason='target_not_in_play')))
            return 0
        before = deepcopy(target)
        if on_result is not None: callbacks[packet_index] = on_result

        def outcome(**values):
            payload = capture_result(state, packet, target, before, batch_id, packet_index, combat, **values)
            from .hero_health_history import commit as commit_hero_health, snapshot as hero_health_snapshot
            payload.update(commit_hero_health(r.state, hero_health_snapshot(before),
                hero_health_snapshot(target), 'health_resolved'))
            from .death_causes import health_transition
            health_transition(state, target, payload['result'])
            pending_events.append(('health_resolved', payload))

        if packet.converted:
            pending_events.append(('health_effect_converted', dict(source_id=packet.source_id,
                                  target_id=target.id, from_flow=packet.original_flow.value, to_flow=packet.flow.value,
                                  **packet.event_data())))
        if packet.redirect_path:
            pending_events.append(('health_effect_redirected', dict(source_id=packet.source_id,
                                  target_id=target.id, **packet.event_data())))
        if packet.flow == HealthFlow.HEALING:
            actual = 0 if packet.prevented else apply_healing(target, packet.amount)
            if packet.prevented:
                pending_events.append(('healing_prevented', dict(source_id=packet.source_id, target_id=target.id,
                                      reason='rule_prevention', **packet.event_data())))
            if actual:
                pending_events.append(('healed', dict(source_id=packet.source_id, target_id=target.id,
                                      player_id=target.controller, amount=actual,
                                      healing_kind=packet.healing_kind.value,
                                      reason='lifesteal' if packet.from_lifesteal else 'effect', **packet.event_data())))
            outcome(healed=actual, prevention='rule_prevention' if packet.prevented else None)
            return actual
        result = calculate_damage(packet, target, state=state, combat=combat)
        if result.prevention == 'divine_shield':
            consume_keyword(target, Keyword.DIVINE_SHIELD)
            pending_events.append(('shield_lost', dict(source_id=packet.source_id, target_id=target.id)))
        if result.prevention:
            pending_events.append(('damage_prevented', dict(source_id=packet.source_id, target_id=target.id,
                                    reason=result.prevention, **result.event_data())))
            outcome(prevention=result.prevention)
            return 0
        source = r.state.entities.get(packet.source_id)
        if (result.dealt and packet.damage_kind == DamageKind.MINION_ABILITY and source is not None
                and Keyword.STEALTH in source.keywords):
            consume_keyword(source, Keyword.STEALTH)
            pending_events.append(('stealth_lost', dict(source_id=source.id, target_id=source.id, reason='minion_ability_damage')))
        target.armor -= result.armor_absorbed
        replacement = replacement_for(state, target.id, HealthLossKind.DAMAGE)
        loss_events = commit_loss(r, target, result.health_damage, HealthLossKind.DAMAGE,
                                  packet.source_id, replacement)
        loss_data = dict(health_lost=0, health_replaced=result.health_damage) if loss_events else {}
        if result.health_damage > 0 and target.zone == Zone.BOARD and Keyword.POISONOUS in packet.source_keywords:
            target.doomed = True
        if result.floor_prevented:
            pending_events.append(('damage_prevented', dict(source_id=packet.source_id, target_id=target.id,
                reason='health_floor', **result.event_data())))
        if result.dealt:
            pending_events.append(('damage_dealt', dict(source_id=packet.source_id, target_id=target.id,
                                    player_id=target.controller, amount=result.dealt, **result.event_data(), **loss_data)))
        pending_events.extend(loss_events)
        outcome(damage=result, replaced=result.health_damage if loss_events else 0)
        if result.dealt and Keyword.LIFESTEAL in packet.source_keywords and not packet.from_lifesteal:
            lifesteals.append((packet, result.dealt))
        return 0

    for instruction, packet in zip(instructions, packets):
        settle(packet, instruction.on_result)
    # Converted lifesteal damage must not create another lifesteal restoration.
    # This explicit guard is separate from the engineering resolution budget.
    for source_packet, amount in lifesteals:
        hero_id = state.players[source_packet.source_controller].hero_id
        instruction = Heal(hero_id, amount, source_packet.source_id, source_packet.healing_kind)
        packet = prepare_health(state, r.registry, instruction, rules=rules,
                                from_lifesteal=True, source_packet=source_packet)
        marker = len(pending_events)
        actual = settle(packet)
        pending_events.insert(marker, ('lifesteal', dict(source_id=packet.source_id, target_id=packet.target_id,
                                    player_id=packet.source_controller, amount=amount, healed=actual,
                                    converted=packet.converted)))
    from .health_history import commit_batch as commit_health_batch
    commit_health_batch(r.state, pending_events)
    continuations = []
    for kind, payload in pending_events:
        event = r.emit(kind, **payload)
        if kind == 'health_resolved':
            result = dict(payload['result'])
            behavior = callbacks.get(result['packet_index'])
            if behavior is not None:
                continuations.append(r.call(behavior, result['source_id'], result['source_controller'],
                    target_id=result['target_id'], event=event))
    if combat is not None:
        finish_exchange(r, combat)
    return continuations


def damage_batch(r, effect):
    validate_exchange(r, effect.combat)
    from .cleave import validate_combat_hits
    validate_combat_hits(r.state, effect)
    from .hero_attack_history import accept
    accept(r,effect.combat)
    from .character_attacks import accept as accept_character_attack
    accept_character_attack(r,effect.combat)
    return settle_health_batch(r, effect.hits, effect.combat)


def damage_single(r, effect):
    # Declared damage enters the batch handler; replacements share the common
    # settlement above so conversion cannot create a premature death checkpoint.
    return [DamageBatch((effect,))]


def heal(r, effect):
    return [HealBatch((effect,))]


def heal_batch(r, effect):
    return settle_health_batch(r, effect.heals)


def grant_health_rule(r, effect):
    from .health_floors import validate_grant
    validate_grant(r.state, r.registry, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = r.state.entities.get(effect.target_id)
    if entity is None or not entity.active or entity.zone not in (Zone.HERO, Zone.BOARD, Zone.WEAPON):
        r.stale(effect, effect.target_id)
        return
    if entity.kind == CardType.LOCATION:
        raise ResolutionError('Location health-rule holders are not supported by this contract')
    if entity.zone == Zone.WEAPON and effect.rule.redirect_to == 'self':
        raise ResolutionError('A weapon cannot receive redirected health effects')
    if effect.until_owner_turn_start is not None and entity.kind!=CardType.HERO:
        raise ResolutionError('Owner health expiry requires a hero carrier')
    from .timed_keywords import owner_deadline
    expiry=owner_deadline(r.state,effect.until_owner_turn_start)if effect.until_owner_turn_start is not None else None
    ability = AbilityInstance(attachment_id(r.state), 'health_rule', source_id=effect.source_id,
                             health_rule=effect.rule, expires_turn=effect.expires_turn,health_rule_expiry=expiry)
    entity.abilities.append(ability)
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind='health_rule')


def summon_entity(r, effect):
    from .summon_quantities import reject_ambiguous
    reject_ambiguous(r)
    player = r.player(effect.player_id)
    definition = r.registry.card(effect.card_id)
    if definition.kind != CardType.MINION:
        raise ResolutionError('Summon requires a minion definition')
    if effect.position is not None and (type(effect.position) is not int or effect.position < 0):
        raise ResolutionError('Summon position must be nonnegative')
    if len(player.board) >= r.rules.max_board:
        r.emit('summon_failed', player_id=player.id, card_id=effect.card_id, reason='board_full')
        return
    entity = r.create_entity(player.id, effect.card_id, Zone.BOARD, effect.position)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state, entity, effect.stats)
    r.refresh_auras()
    return entity


def summon(r, effect):
    entity=summon_entity(r,effect)
    return enter_minion(r,entity,'summon') if entity is not None else []


def draw(r, effect):
    nonnegative(effect.count, 'count')
    player = r.player(effect.player_id)
    if effect.count != 1:
        if effect.count > r.rules.max_resolution_steps:
            raise ResolutionLimitExceeded('Draw count exceeds resolution budget')
        return [Draw(effect.player_id, source_id=effect.source_id) for _ in range(effect.count)]
    from .draw_casts import draw_one
    return draw_one(r,player.id,source_id=effect.source_id)


def buff(r, effect):
    effect.__post_init__()
    if type(effect.attack) is not int:
        raise ResolutionError('Attack buff must be an integer')
    if type(effect.health) is not int:
        raise ResolutionError('Health buff must be an integer')
    # Signed deltas are ordered attachments, not damage or a maximum-health set.
    # Preserve accumulated damage; the ordinary checkpoint owns fatal states.
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return
    _buff_to(r, effect, entity)


def _buff_to(r, effect, entity, *, notify=True):
    """One attachment installer; trusted entry material can precede announcement."""
    effect.__post_init__()
    if entity.id != effect.target_id:
        raise ResolutionError('Buff material changed its physical recipient')
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(entity)
    from .timed_keywords import owner_deadline
    expiry = (owner_deadline(r.state, effect.until_owner_turn_start)
              if effect.until_owner_turn_start is not None else None)
    enchantment = Enchantment(attachment_id(r.state), source_id=effect.source_id,
                              attack=effect.attack, health=effect.health, expires_turn=effect.expires_turn,
                              owner_turn_expiry=expiry)
    entity.enchantments.append(enchantment)
    refresh_entity(entity)
    if notify:
        r.emit('stats_changed', source_id=effect.source_id, target_id=entity.id,
               enchantment_id=enchantment.id, attack_delta=effect.attack, health_delta=effect.health,
               _hero_health_before=health_before)
    return enchantment


def destroy(r, effect):
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, None)
    entity = r.state.entities.get(effect.target_id)
    if entity is not None and (not entity.active or entity.kind == CardType.LOCATION or entity.zone not in (Zone.HERO, Zone.BOARD, Zone.WEAPON)):
        entity = None
    if entity is None:
        r.stale(effect, effect.target_id)
    else:
        from .death_causes import mark
        mark(r, entity, 'destroy', 'Destroy', effect.source_id)
        entity.doomed = True
        r.emit('destroyed', target_id=entity.id)


def destroy_batch(r, effect):
    effect.__post_init__()
    validate_attachment_source(r, effect.source_id, None)
    from .locations import DestroyLocation, modify_location
    # Dispatch the existing mark operations inside one handler. Reactions and
    # the shared death coordinator run only after every original target is marked.
    for target_id in effect.target_ids:
        entity = r.state.entities.get(target_id)
        if entity is None or entity.zone != Zone.BOARD or not entity.active:
            r.stale(effect, target_id)
        elif entity.kind == CardType.LOCATION:
            modify_location(r, DestroyLocation(target_id, effect.source_id))
        elif entity.kind == CardType.MINION:
            destroy(r, Destroy(target_id, effect.source_id))
        else:
            r.stale(effect, target_id)


def fill_board_with_copies(r, effect):
    effect.__post_init__()
    player=r.player(effect.player_id)
    target=r.live_character(effect.target_id)
    if target is None or target.kind!=CardType.MINION or target.zone!=Zone.BOARD or target.health<=0 or target.doomed:
        r.stale(effect,effect.target_id)
        return
    return tuple(CopyMinion(target.id,player.id) for _ in range(max(0,r.rules.max_board-len(player.board))))


def set_stats(r, effect):
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(entity)
    if isinstance(effect, SwapStats):
        attack, health = entity.health, entity.attack
    else:
        attack, health = resolve_stat(entity, effect.attack), resolve_stat(entity, effect.health)
    old_attack, old_health, old_max = entity.attack, entity.health, entity.max_health
    enchantment = Enchantment(attachment_id(r.state), source_id=effect.source_id,
                              set_attack=attack, set_health=health,
                              expires_turn=effect.expires_turn, label=type(effect).__name__)
    entity.enchantments.append(enchantment)
    refresh_entity(entity)
    if health is not None:
        entity.damage = 0
    r.emit('stats_changed', source_id=effect.source_id, target_id=entity.id,
           enchantment_id=enchantment.id, operation=type(effect).__name__,
           old_attack=old_attack, old_health=old_health, old_max_health=old_max,
           attack=entity.attack, health=entity.health, max_health=entity.max_health,
           _hero_health_before=health_before)


def double_stats(r, effect):
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return
    # An additive frozen operand doubles remaining health without healing damage
    # or multiplying again at future refreshes. Reuse the common buff lifecycle.
    return [Buff(entity.id, entity.attack if effect.attack else 0,
                 entity.health if effect.health else 0, effect.source_id, effect.expires_turn)]


def armor(r, effect):
    nonnegative(effect.amount)
    hero = r.state.entities[r.player(effect.player_id).hero_id]
    hero.armor += effect.amount
    r.emit('armor_gained', target_id=hero.id, player_id=effect.player_id, amount=effect.amount)


def random_destroy(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Random destruction source does not exist')
    candidates = sorted(i for i in effect.candidate_ids if (e := r.live_character(i)) is not None
                        and e.zone == Zone.BOARD and e.health > 0 and not e.doomed)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return
    target = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=target, candidates=tuple(candidates))
    return [Destroy(target, effect.source_id)]


def random_return_to_hand(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Random return source does not exist')
    candidates = sorted(i for i in effect.candidate_ids if (e := r.live_character(i)) is not None
        and e.kind == CardType.MINION and e.zone == Zone.BOARD and e.health > 0 and not e.doomed)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return
    target = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=target, candidates=tuple(candidates))
    return [ReturnToHand(target, to_owner=True)]


def invoke_behavior(r, effect):
    r.player(effect.player_id)
    r.registry.behavior(effect.behavior_id)
    if effect.source_id not in r.state.entities or (
            effect.target_id is not None and effect.target_id not in r.state.entities):
        raise ResolutionError('Behavior invocation references a missing entity')
    from .play_history import play_record
    record=play_record(r.state,effect.play_id) if effect.play_id is not None else None
    if record is not None and (record.source_id,record.player_id)!=(effect.source_id,effect.player_id):
        raise ResolutionError('Play continuation has a different source or player')
    return [r.call(effect.behavior_id, effect.source_id, effect.player_id, effect.target_id, play=record)]


def split_damage(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Split damage source does not exist')
    if not effect.amount:
        return
    if effect.amount > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Split damage exceeds resolution budget')
    player = r.player(effect.player_id)
    ids = (*((player.hero_id,) if effect.include_hero else ()), *player.board)
    candidates = sorted(i for i in ids if (e := r.live_character(i)) is not None
                        and e.health > 0 and not e.doomed)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return
    target = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=target, candidates=tuple(candidates))
    return [Damage(target, 1, effect.source_id, effect.kind), replace(effect, amount=effect.amount - 1)]


def random_buff(r,effect):
    from .effects import Buff
    effect.__post_init__()
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Random buff source does not exist')
    candidates=tuple(sorted(i for i in effect.candidate_ids if(e:=r.live_character(i))is not None
        and e.kind==CardType.MINION and e.zone==Zone.BOARD and e.health>0 and not e.doomed))
    if not candidates:
        r.emit('random_choice_skipped',source_id=effect.source_id,reason='no_candidates');return()
    target=r.game._rng.choice(candidates)
    r.emit('random_choice',source_id=effect.source_id,target_id=target,candidates=candidates)
    return(Buff(target,effect.attack,effect.health,effect.source_id),)


def random_damage(r, effect):
    effect.__post_init__()
    if effect.on_result is not None: r.registry.behavior(effect.on_result)
    nonnegative(effect.amount)
    if not isinstance(effect.candidate_ids, tuple) or any(type(i) is not int for i in effect.candidate_ids):
        raise ResolutionError('Random candidates must be a tuple of integer IDs')
    if len(set(effect.candidate_ids)) != len(effect.candidate_ids):
        raise ResolutionError('Duplicate random candidates are not supported')
    candidates = sorted(i for i in effect.candidate_ids if (e := r.live_character(i)) is not None
                        and e.health > 0 and not e.doomed)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_candidates')
        return
    target = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=target, candidates=tuple(candidates))
    return [Damage(target, effect.amount, effect.source_id, effect.kind, effect.on_result)]


def random_damage_batch(r,effect):
    effect.__post_init__()
    candidates=tuple(sorted(i for i in effect.candidate_ids if(e:=r.live_character(i))is not None
        and e.health>0 and not e.doomed))
    if not candidates:
        r.emit('random_choice_skipped',source_id=effect.source_id,reason='no_candidates')
        return ()
    selected=tuple(r.game._rng.sample(candidates,effect.count))if len(candidates)>effect.count else candidates
    for target in selected:r.emit('random_choice',source_id=effect.source_id,target_id=target,candidates=candidates)
    return (DamageBatch(tuple(Damage(i,effect.amount,effect.source_id,effect.kind)for i in selected)),)


def play_from_hand(r, effect):
    action = effect.action
    player, entity = r.player(action.player_id), r.state.entities[action.entity_id]
    definition = r.registry.card(entity.card_id)
    if not definition.hand_playable or not definition.manual_playable:
        raise ResolutionError('This card cannot be manually played from hand')
    from .play_requirements import manual_requirement_error
    if reason := manual_requirement_error(r.state, r.registry, entity):
        raise ResolutionError(reason)
    from .player_effects import manual_play_allowed
    if not manual_play_allowed(r.state, r.registry, player.id, definition.kind):
        raise ResolutionError('Current-turn rule prohibits manually playing this card type')
    from .choose_policies import matching as choose_matching, capture as capture_choose, accept as accept_choose
    choose_before = deepcopy(r.state) if choose_matching(r.state, definition, player.id, 'hand') else None
    choose_proof = None if choose_before is None else capture_choose(choose_before, r.registry, definition.id, player.id,
        'play', len(r.state.play_history) + 1, 'hand', action.branch_id, source_id=entity.id)
    from .costs import pay_quote
    from .play_history import prepare_play
    from .temporary_cards import repeat_spec, on_committed
    hand_repeat = repeat_spec(entity, definition)
    from .magnetic import host_at_position, merge
    magnetic_host=host_at_position(r.state,r.registry,entity,action.position)
    from .rewind import retry_quote
    quote=retry_quote(r,entity)
    body_receipt = None
    if action.body_target_profile_id is not None:
        from .paid_body_targets import capture as capture_paid_body_targets
        from .rewind import capture_hand_spell_session
        body_receipt = capture_paid_body_targets(r.state, r.registry, action, quote,
            rewind_session=capture_hand_spell_session(r, entity.id), game=r.game)
    record=prepare_play(r.state,r.registry,entity,action.target_id,quote,position=action.position,
                        magnetic_target_id=magnetic_host.id if magnetic_host is not None else None,
                        branch_id=action.branch_id,body_targets=body_receipt,
                        board_player_id=action.board_player_id)
    spell_cost_proof = None
    paid_hand_proof = None
    if record.kind == CardType.SPELL:
        from .spell_cost_proof import capture_hand_cost_proof
        record, spell_cost_proof = capture_hand_cost_proof(r, record, quote)
    else:
        from .paid_hand_acceptance import capture as capture_paid_hand_cost_proof
        record, paid_hand_proof = capture_paid_hand_cost_proof(r, record, quote)
    pay_quote(r,player,entity,quote)
    paid_hand_submission_base = None if paid_hand_proof is None else deepcopy(r.state)
    r.state.play_history.append(record)
    paid_hand_tail = None
    if paid_hand_proof is not None:
        from .paid_hand_acceptance import make_tail
        paid_hand_tail = make_tail(r, paid_hand_proof, paid_hand_submission_base)
    combo_submission=[]
    if record.kind in (CardType.MINION,CardType.WEAPON,CardType.HERO):
        from .combo_matching import capture_recipient
        from .combo_modifiers import capture as capture_combo_policies, consume as consume_combo_policies
        from .combo_acceptance import make_proof
        from .play_history import accept_combo_submission
        receipt=capture_combo_policies(r,record,'play',
            capture_recipient(r.state,r.registry,entity.id),bool(record.combos))
        record=accept_combo_submission(r.state,record.id,receipt.id)
        combo_submission=[make_proof(r,record,'play',receipt)]
        consume_combo_policies(r,receipt)
    spell_acceptance = None
    if record.kind == CardType.SPELL:
        from .spell_acceptance import accept_submission
        record, spell_acceptance = accept_submission(r, record, spell_cost_proof)
    from .spell_modifiers import capture as capture_spell_policies
    capture_spell_policies(r,record)
    # Payment/Spell submission owns its exact postpayment projection. This
    # independent branch acceptance consumes only after that window is saved,
    # still before commitment reactions or any payload executes.
    choose_tail = accept_choose(r, choose_proof)
    if definition.kind == CardType.MINION:
        from .interrupts import open_window
        from .minion_plays import MinionCounterPhase
        r.move(entity, Zone.PLAY)
        window = open_window(r, 'minion', player.id, entity.id, action.target_id, play_id=record.id)
        r.emit('card_committed', source_id=entity.id, target_id=action.target_id,
               player_id=player.id, window_id=window.id, play_id=record.id)
        on_committed(r, record, hand_repeat)
        return [MinionCounterPhase(window.id),*combo_submission,
                FinishPlay(entity.id,player.id,action.target_id,record.id), paid_hand_tail, *choose_tail]
    if definition.kind == CardType.SPELL:
        from .interrupts import open_window, SpellTargetPhase
        r.move(entity, Zone.GRAVEYARD)
        window = open_window(r, 'spell', player.id, entity.id, action.target_id, play_id=record.id)
        r.emit('card_committed', source_id=entity.id, target_id=action.target_id,
               player_id=player.id, window_id=window.id, play_id=record.id)
        on_committed(r, record, hand_repeat)
        return [SpellTargetPhase(window.id), spell_acceptance, *choose_tail]
    if definition.kind == CardType.WEAPON:
        equip_entity(r, entity)
    elif definition.kind == CardType.HERO:
        play_hero(r, entity)
    else:
        r.move(entity, Zone.BOARD if definition.kind in (CardType.MINION, CardType.LOCATION) else Zone.GRAVEYARD, action.position)
    r.refresh_auras()
    r.emit('card_committed', source_id=entity.id, target_id=action.target_id, player_id=player.id, play_id=record.id)
    on_committed(r, record, hand_repeat)
    if definition.kind == CardType.LOCATION:
        r.emit('location_placed', source_id=entity.id, target_id=entity.id, player_id=player.id)
    result=enter_minion(r,entity,'play',play_id=record.id) if definition.kind==CardType.MINION else []
    if result:
        result.append(ColossalBattlecry(r.state.colossal_history[-1].id,record.id))
    else:
        from .rewind_outcomes import payload
        from .battlecries import capture
        result.extend(payload(r, entity.id, player.id, action.target_id,
            tuple(a.behavior_id for a in active_abilities(entity, 'on_play')), play=record, battlecries=capture(entity)))
    result.extend(combo_submission)
    result.append(FinishPlay(entity.id, player.id, action.target_id, record.id))
    result.append(paid_hand_tail)
    result.extend(choose_tail)
    return result


def begin_attack(r, effect):
    action = effect.action
    r.state.entities[action.attacker_id].attacks_this_turn += 1
    attacker = r.state.entities[action.attacker_id]
    if Keyword.STEALTH in attacker.keywords:
        consume_keyword(attacker, Keyword.STEALTH)
        r.emit('stealth_lost', source_id=attacker.id, target_id=attacker.id, reason='attack')
    from .interrupts import open_window, ResolveAttack
    window = open_window(r, 'attack', action.player_id, action.attacker_id, action.defender_id)
    from .character_attacks import declare as declare_character_attack
    declare_character_attack(r, window)
    from .hero_attack_history import declare
    declare(r, window)
    r.emit('attack_declared', source_id=action.attacker_id, target_id=action.defender_id,
           player_id=action.player_id, window_id=window.id,
           target_presence_id=None if window.attack_target_presence is None else window.attack_target_presence.presence_id)
    return [ResolveAttack(window.id)]


def force_attack(r, effect):
    from .combat import combat_relation_matches
    from .model import BoardPresenceReference
    from .board_presence import resolve_board_presence
    effect.validate_in_state(r.state)
    def original(value):
        return resolve_board_presence(r.state, value) if type(value) is BoardPresenceReference else r.live_character(value)
    attacker, defender = original(effect.attacker_id), original(effect.defender_id)
    defender_id = effect.defender_id.entity_id if type(effect.defender_id) is BoardPresenceReference else effect.defender_id
    if (attacker is None or defender is None or attacker.doomed or defender.doomed or
            not attacker.active or not defender.active or attacker.health <= 0 or defender.health <= 0 or
            not combat_relation_matches(attacker, defender, effect.combat_relation)):
        r.stale(effect, defender_id)
        return
    if attacker.kind != CardType.MINION:
        raise ResolutionError('ForceAttack currently requires a minion attacker')
    if Keyword.STEALTH in attacker.keywords:
        consume_keyword(attacker, Keyword.STEALTH)
        r.emit('stealth_lost', source_id=attacker.id, target_id=attacker.id, reason='attack')
    from .interrupts import open_window, ResolveAttack
    window = open_window(r, 'attack', attacker.controller, attacker.id, defender.id, forced=True,
                         combat_relation=effect.combat_relation)
    from .character_attacks import declare as declare_character_attack
    declare_character_attack(r, window)
    r.emit('attack_declared', source_id=attacker.id, target_id=defender.id,
           player_id=attacker.controller, forced=True, window_id=window.id,
           target_presence_id=None if window.attack_target_presence is None else window.attack_target_presence.presence_id)
    return [ResolveAttack(window.id)]


def random_force_attack(r,effect):
    """Sample existing forced-combat pairs: minion attackers, character defenders."""
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Random combat source does not exist')
    def live(i, *, attacker=False):
        e=r.live_character(i)
        return e is not None and (not attacker or e.kind==CardType.MINION) and e.health>0 and not e.doomed
    from .combat import combat_relation_matches
    pairs=sorted((a,d) for a in effect.attacker_ids if live(a,attacker=True) for d in effect.defender_ids
                 if live(d) and combat_relation_matches(r.state.entities[a], r.state.entities[d],
                                                       effect.combat_relation))
    if not pairs:return
    from .effects import ForceAttack
    attacker,defender=r.game._rng.choice(pairs)
    r.emit('random_choice',source_id=effect.source_id,target_id=attacker,defender_id=defender)
    return [ForceAttack(attacker,defender,combat_relation=effect.combat_relation)]


def combat_damage(r, effect):
    from .hero_attack_history import require_link, cancel
    require_link(r.state,effect.attacker_id,effect.defender_id,effect.forced,effect.combat_relation,effect.hero_attack)
    from .character_attacks import require_link as require_character_link, cancel as cancel_character_attack
    original = require_character_link(r.state, effect)
    if original is not None:
        from .interrupts import replaced_combatant
        reason = replaced_combatant(r.state, original.delivery)
        if reason is not None:
            cancel(r,effect,reason)
            cancel_character_attack(r,effect,reason)
            r.emit('attack_cancelled',source_id=effect.attacker_id,target_id=effect.defender_id,reason=reason)
            return
    attacker, defender = r.live_character(effect.attacker_id), r.live_character(effect.defender_id)
    if attacker is None or defender is None:
        cancel(r,effect,'combatant_left_play')
        cancel_character_attack(r,effect,'combatant_left_play')
        r.emit('attack_cancelled', source_id=effect.attacker_id, target_id=effect.defender_id, reason='combatant_left_play')
        return
    from .combat import combat_relation_matches
    if not combat_relation_matches(attacker, defender, effect.combat_relation):
        reason = ('combatants_became_friendly' if effect.combat_relation == 'opponent'
                  else 'combat_relation_changed')
        cancel(r,effect,reason)
        cancel_character_attack(r,effect,reason)
        r.emit('attack_cancelled', source_id=attacker.id, target_id=defender.id, reason=reason)
        return
    if attacker.frozen and not effect.forced:
        cancel(r,effect,'attacker_frozen')
        cancel_character_attack(r,effect,'attacker_frozen')
        r.emit('attack_cancelled', source_id=attacker.id, target_id=defender.id, reason='attacker_frozen')
        return
    weapon_id = r.player(attacker.controller).weapon_id if attacker.zone == Zone.HERO else None
    from .cleave import adjacent_targets
    neighbors = tuple(Damage(i, attacker.attack, attacker.id, DamageKind.COMBAT)
                      for i in adjacent_targets(r.state, attacker, defender))
    return [DamageBatch((Damage(defender.id, attacker.attack, attacker.id, DamageKind.COMBAT),
                         Damage(attacker.id, defender.attack, defender.id, DamageKind.COMBAT), *neighbors),
                        CombatExchange(attacker.id, defender.id, weapon_id,
                                       combat_relation=effect.combat_relation, hero_attack=effect.hero_attack,
                                       attack_window_id=effect.attack_window_id))]


def finish_play(r, effect):
    from .play_history import play_record, update_play
    record=play_record(r.state,effect.play_id)
    if (record.source_id,record.player_id)!=(effect.source_id,effect.player_id):
        raise ResolutionError('Mismatched play completion')
    if record.kind != CardType.SPELL:
        from .paid_hand_acceptance import FinishPaidHandAcceptance
        tails = [work for work in r._work_queue if type(work) is FinishPaidHandAcceptance and work.play_id == record.id]
        if len(tails) != 1 or record.paid_hand_close is not None or record.paid_hand_interrupt is not None:
            raise ResolutionError('Physical hand completion lost its unique complete payment tail')
    if record.kind in (CardType.MINION,CardType.WEAPON,CardType.HERO):
        from .combo_acceptance import FinishComboAcceptance
        if (record.combo_submission_receipt_id is None or record.combo_acceptance is None or
                any(type(w) is FinishComboAcceptance and w.context.play.id==record.id for w in r._work_queue)):
            raise ResolutionError('Physical play completion precedes its complete Combo acceptance obligations')
    update_play(r.state,effect.play_id,completed=True)
    r.emit('card_played', source_id=effect.source_id, target_id=effect.target_id, player_id=effect.player_id,
           play_id=effect.play_id, _spellburst_candidates=effect.spellburst_candidates)
    from .hand_derivatives import after_hand_play
    return after_hand_play(record)


def end_turn(r, effect):
    r.ending_turn = True
    from .player_effects import turn_countdowns
    countdowns = turn_countdowns(r, r.player(effect.player_id), 'turn_ended')
    from .hand_deadlines import due_before_end, ExpireHandDeadline
    hand_expiries = due_before_end(r.state, effect.player_id)
    event = r.emit('turn_ended', player_id=effect.player_id,_end_turn=True)
    from .owner_turns import mark_owner_end
    mark_owner_end(r.state, event)
    finish=r._end_turn_finish
    r._end_turn_finish=None
    return [finish,*countdowns, *(ExpireHandDeadline(i, event.sequence) for i in hand_expiries),
            ThawCharacters(effect.player_id), ExpireTurn(r.state.turn), StartNextTurn()]


def start_next_turn(r, effect):
    from .owner_turns import close_owner_turn, start_owner_turn
    from .player_effects import due_turn_rules
    if due_turn_rules(r.state, r.registry, r.state.turn):
        return [ExpireTurn(r.state.turn), StartNextTurn()]
    if r.rules.draw_after_turn is not None and r.state.turn >= r.rules.draw_after_turn:
        r.ending_turn = False
        close_owner_turn(r.state, len(r.game._events))
        r.state.status = 'draw'
        r.state.winner = None
        r.emit('game_ended', reason='configured_draw_turn', result='draw')
        return
    if r.state.turn >= r.rules.max_turns:
        raise ResolutionLimitExceeded('Engineering turn budget exhausted; action rolled back')
    from .turn_scheduling import take_next_slot
    player_id, skipped = take_next_slot(r.state)
    if skipped:
        r.emit('turn_skipped', player_id=player_id)
        return [StartNextTurn()]
    r.ending_turn = False
    close_owner_turn(r.state, len(r.game._events))
    ending = r.player(r.state.active_player)
    ending.temporary_mana = 0
    refresh_mana(ending)
    r.state.active_player = player_id
    r.state.turn += 1
    from .keyword_auras import refresh_turn_keywords
    refresh_turn_keywords(r.state, r.registry)
    from .stat_relations import refresh_turn_attacks
    refresh_turn_attacks(r.state, r.registry)
    from .limited_triggers import refresh_turn_budgets
    refresh_turn_budgets(r.state)
    player = r.player(r.state.active_player)
    start_owner_turn(r.state, len(r.game._events))
    begin_mana_turn(player)
    for participant in r.state.players.values():
        participant.hero_power_uses_this_turn = 0
        for power_id in participant.hero_power_ids:
            r.state.entities[power_id].uses_this_turn = 0
        for entity_id in [participant.hero_id, *participant.board]:
            r.state.entities[entity_id].attacks_this_turn = 0
            r.state.entities[entity_id].old_god_free_used = False
            if r.state.entities[entity_id].kind == CardType.LOCATION:
                r.state.entities[entity_id].uses_this_turn = 0
    from .timed_keywords import expire
    expire(r, 'turn_started', r.state.turn, player.id)
    from .temporary_deck_hands import due_start,ExpireTemporaryDeckHands
    if due_start(r.state):return [ExpireTemporaryDeckHands(),BeginTurnEvents()]
    return [BeginTurnEvents()]


def begin_turn_events(r, effect):
    player = r.player(r.state.active_player)
    r.refresh_auras()
    from .locations import begin_location_turn
    begin_location_turn(r, player)
    from .dormancy import turn_countdowns
    countdowns = turn_countdowns(r, player)
    from .player_effects import turn_countdowns as player_countdowns
    countdowns += player_countdowns(r, player, 'turn_started')
    event = r.emit('turn_started', player_id=player.id, turn=r.state.turn)
    from .owner_turns import publish_owner_start
    publish_owner_start(r.state, event)
    from .turn_start_draws import DrawAtTurnStart
    return [*countdowns, DrawAtTurnStart(player.id)]


def validate_attachment_source(r, source_id, expires_turn):
    if source_id is not None and source_id not in r.state.entities:
        raise ResolutionError('Attachment source does not exist')
    if expires_turn is not None and expires_turn < r.state.turn:
        raise ResolutionError('Cannot attach an effect which already expired')


def board_minion(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or not entity.active or entity.zone != Zone.BOARD:
        r.stale(effect, effect.target_id)
        return None
    if r.registry.card(entity.card_id).kind != CardType.MINION:
        raise ResolutionError('Effect requires a minion')
    return entity


def silence(r, effect):
    entity = board_minion(r, effect)
    if entity is None:
        return
    had_shield=Keyword.DIVINE_SHIELD in entity.keywords
    removed = tuple(e for e in entity.enchantments if e.remove_on_silence)
    remove_attachments(entity, enchantment_predicate=lambda e: e.remove_on_silence,
                       ability_predicate=lambda a: a.remove_on_silence)
    entity.silenced = True
    entity.frozen_until_owner_turn = None
    restore_removed_control(r, entity, removed)
    r.refresh_auras()
    if had_shield and Keyword.DIVINE_SHIELD not in entity.keywords:
        r.emit('shield_lost',target_id=entity.id)
    r.emit('silenced', target_id=entity.id, player_id=entity.controller)


def grant_ability(r, effect):
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    candidate = r.state.entities.get(effect.target_id)
    if candidate is not None and candidate.zone == Zone.HERO and isinstance(effect, (GrantDeathrattle, GrantTrigger)):
        entity = candidate
    elif candidate is not None and candidate.zone == Zone.WEAPON and isinstance(effect, (GrantKeyword, GrantDeathrattle, GrantTrigger)):
        entity = candidate
        if isinstance(effect, GrantKeyword) and effect.keyword not in WEAPON_KEYWORDS:
            raise ResolutionError('Unsupported weapon keyword transfer')
    else:
        entity = r.live_character(effect.target_id) if isinstance(effect, (GrantKeyword, GrantSpellDamage)) else board_minion(r, effect)
    if entity is None:
        if isinstance(effect, (GrantKeyword, GrantSpellDamage)):
            r.stale(effect, effect.target_id)
        return
    _grant_to(r, effect, entity)


def _grant_to(r, effect, entity, *, notify=True, pending=False, grant_card_id=None):
    """Install ordinary ability material after the caller binds the recipient."""
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    if entity.id != effect.target_id or pending and (entity.kind != CardType.MINION or entity.zone != Zone.PLAY):
        raise ResolutionError('Ability material changed its original pending recipient')
    fields = dict(source_id=effect.source_id, expires_turn=effect.expires_turn)
    if isinstance(effect, GrantKeyword):
        if effect.duration is not None:
            from .timed_keywords import deadline, supports_grant
            if not (pending or supports_grant(entity, effect.duration, effect.source_id)):
                raise ResolutionError('Timed keyword grants require board minions or source-bound next-turn hero immunity')
            fields['timed_keyword'] = effect.duration
            fields['keyword_expiry'] = deadline(r.state, entity.controller, effect.duration)
        if effect.keyword in (Keyword.REWIND, Keyword.CASTS_WHEN_DRAWN, Keyword.TWINSPELL, Keyword.MINIATURIZE, Keyword.GIGANTIFY, Keyword.MINI, Keyword.GIGANTIC, Keyword.ECHO, Keyword.SHATTER, Keyword.SHATTERED, Keyword.TITAN, Keyword.OLD_GOD, Keyword.QUEST, Keyword.QUESTLINE, Keyword.SIDEQUEST, Keyword.SECRET, Keyword.HERALD, Keyword.INVOKE, Keyword.COLOSSAL, Keyword.MAGNETIC, Keyword.COMBO, Keyword.OUTCAST, Keyword.FINALE, Keyword.MANATHIRST, Keyword.QUICKDRAW, Keyword.SPELLBURST, Keyword.FRENZY, Keyword.CORRUPT, Keyword.INFUSE):
            raise ResolutionError('This keyword requires registered ability instances; cannot grant as a bare keyword')
        kind, fields['keyword'] = 'keyword', effect.keyword
        if effect.reborn_policy is not None:
            if entity.kind != CardType.MINION:
                raise ResolutionError('Full-health Reborn requires a minion carrier')
            fields['reborn_policy'] = effect.reborn_policy
    elif isinstance(effect, GrantSpellDamage):
        kind, fields['spell_damage'] = 'spell_damage', effect.amount
    elif isinstance(effect, GrantDeathrattle):
        kind, fields['behavior_id'] = 'deathrattle', effect.behavior_id
        fields['deathrattle_grant_card_id'] = (grant_card_id if grant_card_id is not None else
            r.state.entities[effect.source_id].card_id if effect.source_id else None)
    elif isinstance(effect, GrantTrigger):
        kind, fields['behavior_id'], fields['event'] = 'trigger', effect.behavior_id, effect.event
        fields['end_turn']=effect.end_turn
        if effect.end_turn is not None: r.registry.trigger_condition(effect.end_turn.condition_id)
    else:
        kind, fields['attack'], fields['include_self'] = 'aura', effect.attack, effect.include_self
        fields['health'] = effect.health
        fields['adjacent_only'] = effect.adjacent_only
    if 'behavior_id' in fields:
        r.registry.behavior(fields['behavior_id'])
    ability = AbilityInstance(attachment_id(r.state), kind, **fields)
    entity.abilities.append(ability)
    r.refresh_auras()
    if notify:
        r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
               ability_id=ability.id, ability_kind=kind)


def remove_enchantment(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or not entity.active:
        r.stale(effect, effect.target_id)
        return
    if not any(e.id == effect.enchantment_id for e in entity.enchantments):
        r.emit('effect_skipped', target_id=entity.id, reason='enchantment_absent', effect='RemoveEnchantment')
        return
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(entity)
    group=next(e.magnetic_id for e in entity.enchantments if e.id==effect.enchantment_id)
    removed = tuple(e for e in entity.enchantments if e.id == effect.enchantment_id or group is not None and e.magnetic_id == group)
    remove_attachments(entity, enchantment_predicate=lambda e: e.id == effect.enchantment_id or group is not None and e.magnetic_id==group,
                       ability_predicate=lambda a: group is not None and a.magnetic_id==group)
    restore_removed_control(r, entity, removed)
    r.emit('enchantment_removed', target_id=entity.id, enchantment_id=effect.enchantment_id,
           _hero_health_before=health_before)


def expire_turn(r, effect):
    from .owner_turns import owner_turn_index
    from .temporary_hands import due as temporary_hands_due,ReturnTemporaryHand
    due=temporary_hands_due(r.state,effect.turn)
    if due:return [ReturnTemporaryHand(due[-1]),ExpireTurn(effect.turn)]
    from .player_effects import expire_turn_rules
    expired_player_rules = expire_turn_rules(r, effect.turn)
    from .hand_choice_followups import expire as expire_hand_followups
    expire_hand_followups(r, effect.turn)
    from .timed_keywords import expire
    expired_keywords = expire(r, 'turn_ended', effect.turn, r.state.active_player)
    from .temporary_cards import expire_temporary_cards
    expired_cards = expire_temporary_cards(r, effect.turn)
    from .battlecry_modifiers import expire as expire_battlecry_modifiers
    expired_battlecries = expire_battlecry_modifiers(r, effect.turn)
    from .combo_modifiers import expire as expire_combo_modifiers
    expired_combos = expire_combo_modifiers(r,effect.turn)
    from .spell_modifiers import expire as expire_spell_modifiers
    expired_spells = expire_spell_modifiers(r,effect.turn)
    from .choose_policies import expire as expire_choose_policies
    expired_choices = expire_choose_policies(r, effect.turn)
    expired_events = []
    control_events = []
    expired_modifiers = []
    for player in r.state.players.values():
        expired = [m.id for m in player.cost_modifiers if m.expires_turn is not None and m.expires_turn <= effect.turn]
        if expired:
            player.cost_modifiers = [m for m in player.cost_modifiers if m.id not in expired]
            expired_modifiers.append((player.id, tuple(expired)))
    for entity in list(r.state.entities.values()):
        expired = [a.id for a in [*entity.enchantments, *entity.abilities]
                   if a.expires_turn is not None and a.expires_turn <= effect.turn or
                   isinstance(a, Enchantment) and a.control_return_expiry is not None and
                   a.control_return_expiry.player_id == r.state.active_player and
                   a.control_return_expiry.owner_turn_index <= owner_turn_index(r.state, r.state.active_player)]
        if expired:
            from .hero_health_history import commit as commit_hero_health, snapshot as hero_health_snapshot
            health_before = hero_health_snapshot(entity)
            removed = tuple(e for e in entity.enchantments if e.id in expired)
            remove_attachments(entity, enchantment_predicate=lambda e: e.id in expired,
                               ability_predicate=lambda a: a.id in expired)
            control_events.extend(restore_removed_control(r, entity, removed, publish=False))
            health_data = commit_hero_health(r.state, health_before, hero_health_snapshot(entity), 'attachments_expired')
            expired_events.append((entity.id, tuple(expired), health_data))
    r.refresh_auras(rebind_frozen_ids=tuple(data['target_id'] for kind, data in control_events
                                         if kind == 'control_changed'))
    for kind, data in control_events:
        r.emit(kind, **data)
    for entity_id, expired, health_data in expired_events:
        r.emit('attachments_expired', target_id=entity_id, attachment_ids=expired, **health_data)
    for player_id, expired in expired_modifiers:
        r.emit('cost_modifiers_expired', player_id=player_id, modifier_ids=expired)
    # Resolve reactions, then settle any same-turn attachments those reactions
    # create. The shared resolution budget also bounds this stabilization.
    return [ExpireTurn(effect.turn)] if expired_player_rules or expired_events or expired_modifiers or expired_cards or expired_battlecries or expired_combos or expired_keywords or expired_spells or expired_choices else []


def return_to_hand(r, effect):
    effect.__post_init__()
    if effect.lock_next_owner_turn:
        validate_attachment_source(r, effect.source_id, None)
    if effect.discard is not None:
        from .discard_history import return_material
        return return_material(r, effect)
    entity = board_minion(r, effect)
    if entity is None:
        return
    old_controller = entity.controller
    player = r.player(entity.owner if effect.to_owner else entity.controller)
    def move_to_destination(zone):
        r.move(entity, zone, hand_entry_reason=None)
        if player.id != old_controller:
            getattr(r.player(old_controller), zone.value).remove(entity.id)
            getattr(player, zone.value).append(entity.id)
            entity.controller = player.id
    if len(player.hand) >= hand_capacity(player, r.rules):
        from .death_causes import mark
        mark(r, entity, 'destroy', 'ReturnToHand')
        entity.doomed = True
        r.refresh_auras()
        r.emit('card_burned', target_id=entity.id, player_id=player.id, reason='return_hand_full')
        return
    move_to_destination(Zone.HAND)
    from .hand_history import enter_hand
    enter_hand(r.state, entity, Zone.BOARD, 'return')
    reset_to_definition(r.state, entity, r.registry.card(entity.card_id), r.registry, preserve_jade=True, preserve_cthun=True)
    if effect.cost is not None:
        modify_cost(r, ModifyCost(entity.id, effect.cost))
    if effect.lock_next_owner_turn:
        from .hand_play_locks import LockHandCard, lock_hand_card
        from .zones import CardReference
        # Bind the actual successful arrival before return reactions. No later
        # name lookup, retry after a full hand, or post-reaction reacquisition.
        lock_hand_card(r, LockHandCard(CardReference.capture(entity), 2, effect.source_id))
    r.refresh_auras()
    r.emit('card_returned', target_id=entity.id, player_id=player.id)


def transform(r, effect):
    entity = board_minion(r, effect)
    if entity is None:
        return
    definition = r.registry.card(effect.card_id)
    if definition.kind != CardType.MINION:
        raise ResolutionError('Transform requires a minion definition')
    return transform_minion(r,entity,definition)


def transform_minion(r, entity, definition, *, source_id=None, retained_cost=None,
                     copy_material=None, stats=None):
    from .game_boards import resolve_card_id
    definition = r.registry.card(resolve_card_id(r.state, r.registry, definition.id))
    old_card = entity.card_id
    entity.face_replaced = True
    attacks, summoned = entity.attacks_this_turn, entity.summoned_turn
    entity.zone_epoch += 1
    reset_to_definition(r.state, entity, definition, r.registry,
                        components=() if copy_material is None else copy_material.components)
    if copy_material is not None:
        from .zones import copy_current_stored_state
        entity.dormancy = None
        copy_current_stored_state(r.state, copy_material, entity)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state, entity, stats)
    entity.attacks_this_turn, entity.summoned_turn = attacks, summoned
    if retained_cost is not None:
        from .costs import attach_cost
        from .model import CostSpec
        attach_cost(r.state,entity,CostSpec(set_to=retained_cost),source_id)
    r.refresh_auras()
    if copy_material is not None and copy_material.frozen:
        from .combat import can_be_frozen
        if can_be_frozen(entity):
            entity.frozen_until_owner_turn = freeze_deadline(r.state, entity,
                ending_turn=r.ending_turn, registry=r.registry)
    r.emit('transformed', target_id=entity.id, old_card_id=old_card, card_id=definition.id)
    return enter_minion(r,entity,'transform')


def copy_minion(r, effect):
    effect.__post_init__()
    from .summon_quantities import reject_ambiguous
    if effect.cause is None:reject_ambiguous(r)
    else:
        from .copy_materials import validate_effect_scope
        validate_effect_scope(r.state,r.registry,effect)
    from .model import BoardPresenceReference
    if type(effect.target_id) is BoardPresenceReference:
        from .board_presence import resolve_board_presence
        effect.validate_in_state(r.state)
        source = resolve_board_presence(r.state, effect.target_id)
        if (source is None or not (source.active or effect.allow_dormant and source.dormancy is not None)
                or source.health <= 0 or source.doomed):
            r.stale(effect, effect.target_id.entity_id)
            return
    elif effect.allow_dormant:
        source = r.state.entities.get(effect.target_id)
        if (source is None or source.zone != Zone.BOARD or source.kind != CardType.MINION or
                not (source.active or source.dormancy is not None)):
            r.stale(effect, effect.target_id)
            return
    else:
        source = board_minion(r, effect)
    if source is None:
        return
    if effect.cause is not None:
        from .copy_materials import accept_copy
        return accept_copy(r,effect,source,'board_copy')
    player = r.player(effect.player_id)
    if len(player.board) >= r.rules.max_board:
        r.emit('summon_failed', player_id=player.id, card_id=source.card_id, reason='board_full')
        return
    entity = r.create_entity(player.id, source.card_id, Zone.BOARD, effect.position, components=source.components)
    entity.origin_entity_id = source.id
    from .jade import inherit_printed
    inherit_printed(source, entity)
    if effect.mode == 'current':
        if not (effect.allow_dormant and source.dormancy is not None):
            entity.dormancy = None
        entity.base_attack, entity.base_health, entity.base_cost = source.base_attack, source.base_health, source.base_cost
        entity.damage = source.damage
        entity.corpse_value = source.corpse_value
        copy_attachments(r.state, source, entity)
    from .lifecycle import apply_summon_stats
    apply_summon_stats(r.state, entity, effect.stats)
    r.refresh_auras()
    from .combat import can_be_frozen
    if effect.mode == 'current' and source.frozen and can_be_frozen(entity):
        # The new physical position and controller determine current opportunities.
        # Compute the deadline after Charge/Windfury/attack-stat auras are derived.
        entity.frozen_until_owner_turn = freeze_deadline(r.state, entity, ending_turn=r.ending_turn, registry=r.registry)
    return enter_minion(r,entity,'copy',origin_id=source.id,copy_mode=effect.mode)


def change_control(r, effect):
    effect.__post_init__()
    temporary = effect.until_end_of_turn or effect.until_previous_controller_turn_end
    if temporary:
        validate_attachment_source(r, effect.source_id, None)
    entity = board_minion(r, effect)
    if entity is None or entity.controller == effect.player_id:
        return
    if temporary and any(e.control_return_player_id is not None for e in entity.enchantments):
        raise ResolutionError('Overlapping temporary control sources require a separate supported contract')
    previous = entity.controller
    if not transfer_control(r, entity, effect.player_id):
        return
    if temporary:
        from .timed_keywords import owner_deadline
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=effect.source_id,
            expires_turn=r.state.turn if effect.until_end_of_turn else None, label='temporary_control',
            control_return_player_id=previous, control_return_expiry=owner_deadline(r.state, previous, 'turn_ended')
                if effect.until_previous_controller_turn_end else None))
    r.refresh_auras(rebind_frozen_ids=(entity.id,))
    if effect.cannot_attack_this_turn:
        from .attack_policies import GrantAttackPolicy, grant
        from .model import AttackPolicySpec
        grant(r, GrantAttackPolicy(entity.id, AttackPolicySpec('cannot_attack'), effect.source_id, r.state.turn))
    r.emit('control_changed', target_id=entity.id, player_id=effect.player_id, previous_controller=previous)


def transfer_control(r, entity, player_id):
    """Original physical board mutation, shared with control-enchantment removal."""
    player = r.player(player_id)
    if len(player.board) >= r.rules.max_board:
        r.emit('control_change_failed', target_id=entity.id, player_id=player.id, reason='board_full')
        return False
    previous = entity.controller
    r.player(previous).board.remove(entity.id)
    player.board.append(entity.id)
    entity.controller = player.id
    entity.summoned_turn = r.state.turn
    entity.entered_order = r.state.next_order
    r.state.next_order += 1
    return True


def restore_removed_control(r, entity, removed, *, publish=True):
    """Undo removed control layers on the same resident; no zone reacquisition.

    Reset/transform discard control as part of replacing the old incarnation.
    Copying never copies a physical return. Current-turn expiry uses the same
    original remover and publishes only after all due attachments are cleared.
    """
    events = []
    for enchantment in reversed(removed):
        player_id = enchantment.control_return_player_id
        if (player_id is None or entity.kind != CardType.MINION or entity.zone != Zone.BOARD or
                entity.doomed or entity.health <= 0 or entity.controller == player_id):
            continue
        if len(r.player(player_id).board) >= r.rules.max_board:
            if not entity.active:
                raise ResolutionError('Dormant full-board control return requires a separately supported death policy')
            from .death_causes import mark
            mark(r, entity, 'destroy', 'temporary_control_return_board_full', enchantment.source_id)
            entity.doomed = True
            events.append(('destroyed', dict(target_id=entity.id)))
            continue
        previous = entity.controller
        transfer_control(r, entity, player_id)
        events.append(('control_changed', dict(target_id=entity.id, player_id=player_id, previous_controller=previous)))
    if publish and events:
        r.refresh_auras(rebind_frozen_ids=tuple(data['target_id'] for kind, data in events
                                             if kind == 'control_changed'))
        for kind, data in events:r.emit(kind, **data)
    return events


def shuffle_into_deck(r, effect):
    entity = r.state.entities.get(effect.target_id)
    if entity is None or not entity.active or entity.zone not in (Zone.HAND, Zone.BOARD):
        r.stale(effect, effect.target_id)
        return
    if not r.registry.card(entity.card_id).hand_playable:
        raise ResolutionError('Cannot shuffle a hero')
    player = r.player(effect.player_id if effect.player_id is not None else entity.controller)
    previous_controller = entity.controller
    getattr(r.player(entity.controller), entity.zone.value).remove(entity.id)
    entity.controller, entity.zone = player.id, Zone.DECK
    entity.board_presence_id = None
    entity.zone_epoch += 1
    r.game._information.conceal(entity.id)
    reset_to_definition(r.state, entity, r.registry.card(entity.card_id), r.registry,
                        preserve_jade=True, preserve_cthun=previous_controller == player.id)
    if previous_controller != player.id:
        from .cthun import initialize_instance as initialize_cthun
        initialize_cthun(r.state, r.registry, entity)
    position = r.game._rng.randrange(len(player.deck) + 1)
    player.deck.insert(position, entity.id)
    r.refresh_auras()
    r.emit('card_shuffled', target_id=entity.id, player_id=player.id, position=position, _deck_insertion_mode='random')


def reborn_minion(r, effect):
    record = next((d for d in r.state.death_history if d.id == effect.death_id), None)
    if record is None or r.registry.card(record.card_id).kind != CardType.MINION:
        raise ResolutionError('Missing death record for reborn')
    player = r.player(record.controller)
    if len(player.board) >= r.rules.max_board:
        r.emit('reborn_failed', source_id=record.entity_id, player_id=player.id, reason='board_full', death_id=record.id)
        return
    entity = r.create_entity(player.id, record.card_id, Zone.BOARD, record.position, components=record.components)
    entity.origin_entity_id = record.entity_id
    from .jade import inherit_printed
    inherit_printed(record, entity)
    full_health = any(a.kind == 'keyword' and a.keyword == Keyword.REBORN and
                      not a.consumed and a.reborn_policy == 'full_health_enchantments'
                      for a in record.abilities)
    if full_health:
        from .lifecycle import restore_reborn_enchantments
        restore_reborn_enchantments(r.state, record, entity)
    consume_keyword(entity, Keyword.REBORN)
    r.refresh_auras()
    entity.damage = 0 if full_health else max(0, entity.max_health - 1)
    return enter_minion(r,entity,'reborn',origin_id=record.entity_id,death_id=record.id)


def freeze_character(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Freeze source does not exist')
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return
    from .combat import can_be_frozen
    if not can_be_frozen(entity):
        r.emit('freeze_unchanged', source_id=effect.source_id, target_id=entity.id, reason='cannot_be_frozen')
        return
    if entity.frozen:
        r.emit('freeze_unchanged', source_id=effect.source_id, target_id=entity.id)
        return
    entity.frozen_until_owner_turn = freeze_deadline(r.state, entity, ending_turn=r.ending_turn, registry=r.registry)
    r.emit('frozen', source_id=effect.source_id, target_id=entity.id, thaw_owner_turn=entity.frozen_until_owner_turn)


def unfreeze_character(r, effect):
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
    elif entity.frozen:
        entity.frozen_until_owner_turn = None
        r.emit('unfrozen', target_id=entity.id)


def thaw_characters(r, effect):
    player = r.player(effect.player_id)
    from .owner_turns import owner_turn_index
    index = owner_turn_index(r.state, player.id)
    changed = []
    for entity_id in (player.hero_id, *player.board):
        entity = r.state.entities[entity_id]
        if entity.frozen and entity.frozen_until_owner_turn <= index:
            entity.frozen_until_owner_turn = None
            changed.append(entity_id)
    for entity_id in changed:
        r.emit('unfrozen', target_id=entity_id, reason='missed_attack')


def trigger_deathrattles(r, effect):
    entity = board_minion(r, effect)
    if entity is None:
        return []
    from .deathrattles import schedule_group
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ValueError('Unknown Deathrattle trigger source')
    return schedule_group(r,entity.id,entity.controller,tuple(active_abilities(entity,'deathrattle')),
                          trigger_source_id=effect.source_id,trigger_count=effect.times)


def default_mechanics(version=CORE_EFFECTS_VERSION):
    from .effects import ForceAttack, DrawToHandLimit
    from .bonus_effects import register_bonus_effects
    from .locations import register_locations
    from .dormancy import register_dormancy
    from .quests import register_quests
    from .player_effects import register_player_effects
    from .secrets import register_secrets
    from .interrupts import register_interrupts
    from .limited_triggers import register_limited_triggers
    from .hand_upgrades import register_hand_upgrades
    from .hand_progress import register_hand_progress
    from .minion_abilities import register_minion_abilities
    from .choices import request_choice, resolve_choice_result
    from .ordered_choices import register_ordered_choices
    from .opening import register_opening
    from .pools import register_generation
    from .zones import register_zones
    from .nondeath_removal import register as register_removal
    from .hand_actions import register_hand_actions
    from .starships import register_starships
    from .effects import RevealHandCard
    from .information import reveal_hand_card
    mechanics = Mechanics(version)
    from .sideboards import register as register_sideboards
    register_sideboards(mechanics)
    from .interactables import register as register_interactables
    register_interactables(mechanics)
    register_removal(mechanics)
    from .deck_conditions import register as register_deck_conditions
    register_deck_conditions(mechanics)
    from .choose_one import register as register_choose_one
    register_choose_one(mechanics)
    from .choose_branch_state import register as register_choose_branch_state
    register_choose_branch_state(mechanics)
    from .choose_policies import register as register_choose_policies
    register_choose_policies(mechanics)
    from .battlecries import register as register_battlecries
    register_battlecries(mechanics)
    from .combos import register as register_combos
    register_combos(mechanics)
    register_ordered_choices(mechanics)
    register_opening(mechanics)
    register_generation(mechanics)
    from .battlecry_weapon_outputs import register as register_battlecry_weapon_outputs
    register_battlecry_weapon_outputs(mechanics)
    register_zones(mechanics)
    from .dredge import register as register_dredge
    register_dredge(mechanics)
    from .excavate import register as register_excavate
    register_excavate(mechanics)
    from .imbue import register as register_imbue
    register_imbue(mechanics)
    from .invoke import register as register_invoke
    register_invoke(mechanics)
    register_hand_actions(mechanics)
    from .joust import register as register_joust
    register_joust(mechanics)
    from .deck_reveals import register as register_deck_reveals
    register_deck_reveals(mechanics)
    from .reveals import register as register_reveals
    register_reveals(mechanics)
    from .turn_scheduling import register as register_turn_scheduling
    register_turn_scheduling(mechanics)
    register_starships(mechanics)
    register_bonus_effects(mechanics)
    register_locations(mechanics)
    register_dormancy(mechanics)
    register_minion_abilities(mechanics)
    register_quests(mechanics)
    register_player_effects(mechanics)
    from .adapt_memory import register as register_adapt_memory
    register_adapt_memory(mechanics)
    from .void_decks import register as register_void_decks
    register_void_decks(mechanics)
    register_secrets(mechanics)
    register_interrupts(mechanics)
    from .counter_policies import register as register_counter_policies
    register_counter_policies(mechanics)
    register_limited_triggers(mechanics)
    register_hand_upgrades(mechanics)
    from .cross_zone import register as register_cross_zone
    register_cross_zone(mechanics)
    register_hand_progress(mechanics)
    from .hand_choice_followups import register as register_hand_followups
    register_hand_followups(mechanics)
    mechanics.register(DrawToHandLimit, lambda r, e: [Draw(e.player_id,
        max(0, hand_capacity(r.player(e.player_id), r.rules) - len(r.player(e.player_id).hand)))])
    from .fatigue import register as register_fatigue
    register_fatigue(mechanics)
    mechanics.register(RevealHandCard, reveal_hand_card)
    for kind, handler in (
        (RequestChoice, request_choice), (ResolveChoiceResult, resolve_choice_result),
        (ModifyCost, modify_cost), (AddCostModifier, modify_cost), (GrantCostAura, modify_cost),
        (GainTemporaryMana, mana_effect), (RefreshMana, mana_effect), (ChangeManaCrystals, mana_effect),
        (SetManaCap, mana_effect), (SpendMana, consume_mana), (Overload, mana_effect), (UnlockOverload, mana_effect),
        (GainResource, resource_effect), (SpendResource, resource_effect),
        (Damage, damage_single), (DamageBatch, damage_batch), (Heal, heal), (HealBatch, heal_batch),
        (GrantHealthRule, grant_health_rule),
        (Freeze, freeze_character), (Unfreeze, unfreeze_character), (ThawCharacters, thaw_characters),
        (Summon, summon), (Draw, draw), (Buff, buff), (Destroy, destroy), (DestroyBatch, destroy_batch),
        (SetStats, set_stats), (SwapStats, set_stats), (DoubleStats, double_stats),
        (EquipWeapon, equip_weapon), (TransferWeapon, transfer_weapon), (ModifyWeapon, modify_weapon),
        (ReplaceHeroPower, replace_hero_power), (RefreshHeroPower, refresh_hero_power),
        (SetHeroPowerUses, set_hero_power_uses), (ReplaceHero, replace_hero),
        (ActivateHeroPower, activate_hero_power), (FinishHeroPower, finish_hero_power),
        (GainArmor, armor), (LoseArmor, lose_armor), (RandomDamage, random_damage), (RandomDamageBatch, random_damage_batch), (RandomDestroy, random_destroy), (RandomReturnToHand, random_return_to_hand),
        (SplitDamage, split_damage), (InvokeBehavior, invoke_behavior), (PlayFromHand, play_from_hand),
        (BeginAttack, begin_attack), (CombatDamage, combat_damage),
        (ForceAttack, force_attack),
        (FinishPlay, finish_play), (EndTurnPhase, end_turn), (StartNextTurn, start_next_turn), (BeginTurnEvents, begin_turn_events),
        (Silence, silence), (GrantKeyword, grant_ability), (GrantDeathrattle, grant_ability),
        (GrantSpellDamage, grant_ability),
        (GrantTrigger, grant_ability), (GrantAura, grant_ability), (RemoveEnchantment, remove_enchantment),
        (ReturnToHand, return_to_hand), (Transform, transform), (CopyMinion, copy_minion), (FillBoardWithCopies, fill_board_with_copies),
        (ChangeControl, change_control), (ShuffleIntoDeck, shuffle_into_deck),
        (ExpireTurn, expire_turn), (RebornMinion, reborn_minion),
    ):
        mechanics.register(kind, handler)
    from .effects import RandomForceAttack
    mechanics.register(RandomForceAttack,random_force_attack)
    from .forced_attack_sequences import register as register_forced_attack_sequences
    register_forced_attack_sequences(mechanics)
    from .stored_spell_damage import register as register_stored_spell_damage
    register_stored_spell_damage(mechanics)
    from .attack_policies import register as register_attack_policies
    register_attack_policies(mechanics)
    from .colossal import register as register_colossal
    register_colossal(mechanics)
    from .herald import register as register_herald
    register_herald(mechanics)
    from .effects import TriggerDeathrattles
    mechanics.register(TriggerDeathrattles, trigger_deathrattles)
    from .deathrattles import register as register_deathrattles
    register_deathrattles(mechanics)
    from .power_payloads import register as register_power_payloads
    register_power_payloads(mechanics)
    from .end_turns import register as register_end_turns
    register_end_turns(mechanics)
    from .end_turn_producers import register as register_end_turn_producers
    register_end_turn_producers(mechanics)
    from .end_turn_repeats import register as register_end_turn_repeats
    register_end_turn_repeats(mechanics)
    from .sacrifice import register as register_sacrifice
    register_sacrifice(mechanics)
    from .random_minion_keywords import register as register_random_minion_keywords
    register_random_minion_keywords(mechanics)
    from .keyword_auras import register as register_keyword_auras
    register_keyword_auras(mechanics)
    from .spell_repeats import register as register_spell_repeats
    register_spell_repeats(mechanics)
    from .spell_modifiers import register as register_spell_modifiers
    register_spell_modifiers(mechanics)
    from .spell_acceptance import register as register_spell_acceptance
    register_spell_acceptance(mechanics)
    from .spell_cost_proof import HandPlayCostProof
    from .rewind import HandSpellRewindAnchor
    mechanics.register_payload_type(HandPlayCostProof)
    from .paid_hand_acceptance import PaidHandCostProof, PaidHandChoiceBoundaryProof, FinishPaidHandAcceptance, finish as finish_paid_hand_acceptance
    mechanics.register_payload_type(PaidHandCostProof)
    mechanics.register_payload_type(PaidHandChoiceBoundaryProof)
    mechanics.register(FinishPaidHandAcceptance, finish_paid_hand_acceptance)
    mechanics.register_payload_type(HandSpellRewindAnchor)
    from .card_spell_repeats import register as register_card_spell_repeats
    register_card_spell_repeats(mechanics)
    from .body_grants import register as register_body_grants
    register_body_grants(mechanics)
    from .body_conditions import register as register_body_conditions
    register_body_conditions(mechanics)
    from .card_creation import CardSpellRepeatGrant, CreatedMinionGrant, CreatedMinionStats
    mechanics.register_payload_type(CardSpellRepeatGrant)
    mechanics.register_payload_type(CreatedMinionGrant)
    mechanics.register_payload_type(CreatedMinionStats)
    from .dark_gifts import register as register_dark_gifts
    register_dark_gifts(mechanics)
    from .dark_gift_generation import register as register_dark_gift_generation
    register_dark_gift_generation(mechanics)
    from .stored_gift_discovery import register as register_stored_gift_discovery
    register_stored_gift_discovery(mechanics)
    from .health_loss import register as register_health_loss
    register_health_loss(mechanics)
    from .health_loss_floors import register as register_loss_floors
    register_loss_floors(mechanics)
    from .temporary_cards import register as register_temporary_cards
    register_temporary_cards(mechanics)
    from .hand_derivatives import register as register_hand_derivatives
    register_hand_derivatives(mechanics)
    from .hand_keywords import register as register_hand_keywords
    register_hand_keywords(mechanics)
    from .summon_sources import register as register_summon_sources
    register_summon_sources(mechanics)
    from .spell_casts import register as register_spell_casts
    register_spell_casts(mechanics)
    from .hero_powers import AddHeroPower, add_hero_power, RemoveHeroPower, remove_hero_power
    mechanics.register(AddHeroPower, add_hero_power)
    mechanics.register(RemoveHeroPower, remove_hero_power)
    from .hero_powers import TriggerHeroPower, trigger_hero_power
    mechanics.register(TriggerHeroPower,trigger_hero_power)
    from .hero_powers import CheckHeroPowerTrigger, check_power_trigger
    mechanics.register(CheckHeroPowerTrigger,check_power_trigger)
    from .spell_history import register as register_spell_history
    register_spell_history(mechanics)
    from .deck_spell_casts import register as register_deck_spell_casts
    register_deck_spell_casts(mechanics)
    from .draw_casts import register as register_draw_casts
    register_draw_casts(mechanics)
    from .deathrattle_memory import register as register_deathrattle_memory
    register_deathrattle_memory(mechanics)
    from .deathrattle_inheritance import register as register_deathrattle_inheritance
    register_deathrattle_inheritance(mechanics)
    from .discard_history import DiscardRecord
    mechanics.register_payload_type(DiscardRecord)
    from .successful_summons import SuccessfulSummonRecord, BuffSummonedMinion, buff_summoned_minion, GrantSummonedKeyword, grant_summoned_keyword
    mechanics.register_payload_type(SuccessfulSummonRecord)
    mechanics.register(BuffSummonedMinion,buff_summoned_minion)
    mechanics.register(GrantSummonedKeyword,grant_summoned_keyword)
    from .successful_summons import DamageSummonedMinion,damage_summoned_minion
    mechanics.register(DamageSummonedMinion,damage_summoned_minion)
    from .guarded_corpse_spends import register as register_guarded_corpse_spends
    register_guarded_corpse_spends(mechanics)
    from .corpse_summon_rewards import register as register_corpse_summon_rewards
    register_corpse_summon_rewards(mechanics)
    from .kindred import register as register_kindred
    register_kindred(mechanics)
    from .mana_summon_rewards import register as register_mana_summon_rewards
    register_mana_summon_rewards(mechanics)
    from .rewind import register as register_rewind
    register_rewind(mechanics)
    from .rewind_outcomes import register as register_rewind_outcomes
    register_rewind_outcomes(mechanics)
    from .resource_operations import register as register_resource_operations
    register_resource_operations(mechanics)
    from .hero_lethal_windows import register as register_hero_lethal_windows
    register_hero_lethal_windows(mechanics)
    from .random_split_damage import register as register_random_split_damage
    register_random_split_damage(mechanics)
    from .stat_relations import register as register_stat_relations
    register_stat_relations(mechanics)
    from .tribes import register as register_tribes
    register_tribes(mechanics)
    from .weapon_wear import register as register_weapon_wear
    register_weapon_wear(mechanics)
    from .summon_quantities import register as register_summon_quantities
    register_summon_quantities(mechanics)
    from .pool_summons import register as register_pool_summons
    register_pool_summons(mechanics)
    from .ordered_group_batches import register as register_ordered_groups
    register_ordered_groups(mechanics)
    from .discovery_summons import register as register_discovery_summons
    register_discovery_summons(mechanics)
    from .assemble_offers import register as register_assembly
    register_assembly(mechanics)
    from .copy_materials import register as register_copy_materials
    register_copy_materials(mechanics)
    from .copy_followups import register as register_copy_followups
    register_copy_followups(mechanics)
    from .hand_identity_shuffle import register as register_hand_identity_shuffle
    register_hand_identity_shuffle(mechanics)
    from .deck_shuffles import register as register_deck_shuffles
    register_deck_shuffles(mechanics)
    from .hidden_damage_pairs import register as register_hidden_damage_pairs
    register_hidden_damage_pairs(mechanics)
    from .recruit_summons import register as register_recruit_summons
    register_recruit_summons(mechanics)
    from .resurrection_summons import register as register_resurrection_summons
    register_resurrection_summons(mechanics)
    from .whole_card_replay_state import register_payloads as register_whole_card_replay_payloads
    register_whole_card_replay_payloads(mechanics)
    from .whole_card_replays import register as register_whole_card_replays
    register_whole_card_replays(mechanics)
    from .jade import register as register_jade
    register_jade(mechanics)
    from .cthun import register as register_cthun
    register_cthun(mechanics)
    from .temporary_hands import register as register_temporary_hands
    register_temporary_hands(mechanics)
    from .hand_deadlines import register as register_hand_deadlines
    register_hand_deadlines(mechanics)
    from .starting_hands import register as register_starting_hands
    register_starting_hands(mechanics)
    from .temporary_deck_hands import register as register_temporary_deck_hands
    register_temporary_deck_hands(mechanics)
    from .hand_capacity import register as register_hand_capacity
    register_hand_capacity(mechanics)
    from .return_followups import register as register_return_followups
    register_return_followups(mechanics)
    from .excess_damage import register as register_excess_damage
    register_excess_damage(mechanics)
    from .infinite_damage import register as register_infinite_damage
    register_infinite_damage(mechanics)
    from .health_theft import register as register_health_theft
    register_health_theft(mechanics)
    from .health_followups import register as register_health_followups
    register_health_followups(mechanics)
    from .spell_sequences import register as register_spell_sequences
    register_spell_sequences(mechanics)
    from .spell_target_sequences import register as register_spell_target_sequences
    register_spell_target_sequences(mechanics)
    from .draw_beneficiaries import register as register_draw_beneficiaries
    register_draw_beneficiaries(mechanics)
    from .physical_draw_groups import register as register_physical_draw_groups
    register_physical_draw_groups(mechanics)
    from .destruction_resources import register as register_destruction_resources
    register_destruction_resources(mechanics)
    from .hand_play_locks import register as register_hand_play_locks
    register_hand_play_locks(mechanics)
    from .spent_spells import register as register_spent_spells
    register_spent_spells(mechanics)
    from .spell_targets import register as register_spell_targets
    register_spell_targets(mechanics)
    from .source_stat_summons import register as register_source_stat_summons
    register_source_stat_summons(mechanics)
    from .summon_attack_groups import register as register_summon_attack_groups
    register_summon_attack_groups(mechanics)
    from .summon_keyword_groups import register as register_summon_keyword_groups
    register_summon_keyword_groups(mechanics)
    from .effects import RandomBuff
    mechanics.register(RandomBuff,random_buff)
    from .turn_start_draws import register as register_turn_start_draws
    register_turn_start_draws(mechanics)
    from .native_spell_values import register as register_native_spell_values
    register_native_spell_values(mechanics)
    return mechanics

