"""Canonical JSON only: no pickle, dynamic imports, or executable snapshots."""
from dataclasses import asdict, fields
from copy import deepcopy
import hashlib
import json
from .model import DeathCause, ComboPayload, ComboRecord, ComboBatchRecord

SNAPSHOT_SCHEMA_VERSION = 621

from .model import (HeraldRecord, ColossalRecord, MagneticRecord, HandEntryRecord, HandProgressSpec, HandProgressCandidate, LimitedTriggerSpec, TriggerCandidate, PlayRecord, ActionWindow, PlayerEffect, QuestProgress,
    AbilityInstance, ActivatedAbilitySpec, TargetSpec, TargetMode, DormancyState, DeathRecord, StarshipLaunchRecord, Enchantment, Entity, Event, GameState,
    CardClass, CardType, ChoiceItem, ChoicePurpose, PendingChoice, OpeningState, StartingHandCard, Runes, CostSpec, CostModifier, CostScope, DamageKind, HealingKind, HealthFlow, HealthLayer, HealthOp,
    HealthRule, Keyword, PaymentType, PlayerState, Resource, SpellSchool, Zone,
)
from .model import HandLifetime, HandPreparation, HandDerivativeSpec, ResurrectionRecord, SummonStats, SpellCastRecord, DrawRecord, CastWhenDrawnSpec, CardPreview
from .model import (EndTurnSpec, TriggerSpec, EndTurnSubject, EndTurnBatch, EndTurnCapture, EndTurnRecord,
                    EndTurnRepeatSpec, EndTurnRepeatContributor, EndTurnRepeatPlan,
                    EndTurnSelector, EndTurnRequest, EndTurnActivation)


def canonical_hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def event_to_dict(event: Event) -> dict:
    result = asdict(event)
    result['data'] = dict(event.data)
    # Return a genuine JSON value, not tuples which only json.dumps tolerates.
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def event_from_dict(value: dict) -> Event:
    value = deepcopy(value)
    data = value.pop('data')
    if not isinstance(data, dict):
        raise ValueError('Event data must be an object')
    def freeze(v):
        return tuple(freeze(item) for item in v) if isinstance(v, list) else v
    event = Event(**value, data=tuple((k, freeze(v)) for k, v in data.items()))
    from .health_outcomes import health_result
    health_result(event)
    from .resource_operations import resource_result
    resource_result(event)
    from .joust import joust_result
    joust_result(event)
    from .nondeath_removal import removal_result
    removal_result(event)
    from .armor_consumption import consumption_result as armor_consumption_result
    armor_consumption_result(event)
    return event


def state_to_dict(state: GameState) -> dict:
    result = asdict(state)
    result['temporary_power_returns'] = {str(k): asdict(v) for k, v in sorted(state.temporary_power_returns.items())}
    from .whole_card_replay_state import encode as encode_whole_card_replay
    result['whole_card_replay_ledger'] = encode_whole_card_replay(state.whole_card_replay_ledger)
    result['players'] = {str(k): asdict(v) for k, v in sorted(state.players.items())}
    for row, batch in zip(result['end_turn_batches'], state.end_turn_batches):
        if batch.event is not None:
            row['event'] = event_to_dict(batch.event)
    for row, record in zip(result['end_turn_history'], state.end_turn_history):
        if record.guard_event is not None:
            row['guard_event'] = event_to_dict(record.guard_event)
    for row, record in zip(result['ability_trigger_history'], state.ability_trigger_history):
        if record.request.native_event is not None:
            row['request']['native_event'] = event_to_dict(record.request.native_event)
    for row, receipt in zip(result['resource_operations'], state.resource_operations):
        row['event'] = event_to_dict(receipt.event)
    result['entities'] = {}
    for key, entity in sorted(state.entities.items()):
        result['entities'][str(key)] = entity_to_dict(entity)
    # Includes tuple/enum fields nested in immutable attachments and history.
    return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def _row(value, cls) -> dict:
    if not isinstance(value, dict) or set(value) != {field.name for field in fields(cls)}:
        raise ValueError(f'{cls.__name__} requires exactly its declared fields')
    return dict(value)


def _integer(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f'Invalid integer for {name}')
    return value


def deathrattle_memory_from_dict(value):
    from .model import DeathrattleMemory, NativeDeathrattleSpec, RememberedDraw, RememberedDormancy, RememberedDiscovery, RememberedCost
    memory = _row(value, DeathrattleMemory)
    memory['spec'] = NativeDeathrattleSpec(**_row(memory['spec'], NativeDeathrattleSpec))
    memory['draws'] = tuple(RememberedDraw(**_row(x, RememberedDraw)) for x in _list(memory['draws'], 'remembered physical draws'))
    memory['discard_ids'] = tuple(_list(memory['discard_ids'], 'remembered physical discards'))
    memory['hand_entry_ids'] = tuple(_list(memory['hand_entry_ids'], 'remembered original hand selections'))
    memory['dormancies'] = tuple(RememberedDormancy(**_row(x, RememberedDormancy)) for x in _list(memory['dormancies'], 'remembered dormancy intervals'))
    memory['discoveries'] = tuple(RememberedDiscovery(**_row(x, RememberedDiscovery)) for x in _list(memory['discoveries'], 'remembered discoveries'))
    memory['cost_links'] = tuple(RememberedCost(**_row(x, RememberedCost)) for x in _list(memory['cost_links'], 'remembered cost attachments'))
    from .model import RememberedTargetSpell, BoardPresenceReference
    from .allocation_facts import allocation_from_dict
    from .copy_materials import CapturedCardCopyMaterial, from_dict
    def targeted_spell(value):
        row = _row(value, RememberedTargetSpell)
        row['target'] = allocation_from_dict(row['target'])
        row['residence'] = BoardPresenceReference(**_row(row['residence'], BoardPresenceReference))
        row['spell'] = from_dict(CapturedCardCopyMaterial, row['spell'])
        return RememberedTargetSpell(**row)
    memory['targeted_spells'] = tuple(targeted_spell(x) for x in _list(memory['targeted_spells'], 'remembered targeted spells'))
    if memory['summon_copy'] is not None:
        from .copy_materials import CopyEntryMaterial, from_dict
        memory['summon_copy'] = from_dict(CopyEntryMaterial, memory['summon_copy'])
    return DeathrattleMemory(**memory)


def player_effect_from_dict(value):
    row=_row(value,PlayerEffect)
    if row['issued_spell_set'] is not None:
        from .issued_spell_sets import from_dict as issued_spell_set_from_dict
        row['issued_spell_set']=issued_spell_set_from_dict(row['issued_spell_set'])
    if row['investigation'] is not None:
        from .model import HandInvestigation
        row['investigation'] = HandInvestigation(**_row(row['investigation'], HandInvestigation))
    row['aura_duration_grants'] = tuple(_ability_from_dict(a)
        for a in _list(row['aura_duration_grants'], 'direct Aura original duration grants'))
    row['adaptations'] = tuple(_list(row['adaptations'], 'remembered Adaptations'))
    if row['source_allocation'] is not None:
        from .allocation_facts import allocation_from_payload
        row['source_allocation']=allocation_from_payload(tuple(tuple(r)for r in
            _list(row['source_allocation'],'player effect source allocation'))).payload()
    return PlayerEffect(**row)


def _boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'Invalid boolean for {name}')


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'Invalid string for {name}')


def _optional_id(value, name):
    if value is not None:
        _integer(value, name, 1)


def _list(value, name):
    if not isinstance(value, list):
        raise ValueError(f'{name} must be a JSON array')
    return value


def _keyword_list(value):
    values = _list(value, 'keywords')
    if any(not isinstance(k, str) for k in values) or len(set(values)) != len(values):
        raise ValueError('Invalid or duplicate keywords')
    return tuple(Keyword(k) for k in values)


def _activation_from_dict(value):
    row = _row(value, ActivatedAbilitySpec)
    if row['targeting'] is not None:
        target = _row(row['targeting'], TargetSpec)
        target['mode'] = TargetMode(target['mode'])
        target['zones'] = tuple(Zone(v) for v in _list(target['zones'], 'target zones'))
        target['kinds'] = tuple(CardType(v) for v in _list(target['kinds'], 'target kinds'))
        row['targeting'] = TargetSpec(**target)
    return ActivatedAbilitySpec(**row)


def _battlecry_plan(value):
    from .model import BattlecryRepeatPlan
    row=_row(value,BattlecryRepeatPlan)
    row['contributors']=tuple(_list(row['contributors'],'Battlecry contributors'))
    row['consumable_ids']=tuple(_list(row['consumable_ids'],'Battlecry consumable contributors'))
    return BattlecryRepeatPlan(**row)


def _battlecry_recipient_from_dict(value):
    from .model import BattlecryRecipient
    row = _row(value, BattlecryRecipient); row['kind'] = CardType(row['kind'])
    return BattlecryRecipient(**row)


def _spell_submission_from_dict(value):
    from .model import SpellSubmissionReceipt
    row = _row(value, SpellSubmissionReceipt)
    if row['hero_class'] is not None: row['hero_class'] = CardClass(row['hero_class'])
    row['modifiers'] = tuple(_spell_modifier_from_dict(m)
        for m in _list(row['modifiers'], 'Spell submitted modifiers'))
    if row['cost_facts'] is not None:
        row['cost_facts'] = _spell_cost_facts_from_dict(row['cost_facts'])
    return SpellSubmissionReceipt(**row)


def _spell_payload_from_dict(value):
    from .model import SpellPayloadReceipt, SpellRepeatContributor
    row = _row(value, SpellPayloadReceipt)
    if row['hero_class'] is not None: row['hero_class'] = CardClass(row['hero_class'])
    row['behavior_ids'] = tuple(_list(row['behavior_ids'], 'Spell accepted behaviors'))
    contributors = []
    for item in _list(row['contributors'], 'Spell accepted contributors'):
        source = _row(item, SpellRepeatContributor)
        source['ability'] = _ability_from_dict(source['ability'])
        contributors.append(SpellRepeatContributor(**source))
    row['contributors'] = tuple(contributors)
    if row['cost_facts'] is not None:
        row['cost_facts'] = _spell_cost_facts_from_dict(row['cost_facts'])
    return SpellPayloadReceipt(**row)


def _battlecry_modifier_from_dict(value):
    from .model import BattlecryRepeatModifier
    row=_row(value,BattlecryRepeatModifier)
    row['spec']=_battlecry_repeat_spec(row['spec'])
    return BattlecryRepeatModifier(**row)


def _battlecry_repeat_spec(value):
    from .model import BattlecryRepeatSpec
    from .battlecry_matching import battlecry_match_from_dict
    row = _row(value, BattlecryRepeatSpec)
    row['kinds'] = tuple(CardType(k) for k in _list(row['kinds'], 'Battlecry repeat kinds'))
    row['match'] = battlecry_match_from_dict(row['match'])
    return BattlecryRepeatSpec(**row)


def _combo_plan(value):
    from .model import ComboRepeatPlan
    row=_row(value,ComboRepeatPlan)
    row['contributors']=tuple(_list(row['contributors'],'Combo contributors'))
    row['consumable_ids']=tuple(_list(row['consumable_ids'],'Combo consumable contributors'))
    return ComboRepeatPlan(**row)


def _spell_repeat_spec(value):
    from .model import SpellRepeatSpec
    from .repeat_matching import repeat_match_from_dict
    row = _row(value, SpellRepeatSpec)
    row['match'] = repeat_match_from_dict(row['match'])
    return SpellRepeatSpec(**row)


def _spell_modifier_from_dict(value):
    from .model import SpellRepeatModifier
    row=_row(value,SpellRepeatModifier)
    row['spec']=_spell_repeat_spec(row['spec'])
    return SpellRepeatModifier(**row)


def _combo_modifier_from_dict(value):
    from .model import ComboRepeatModifier
    row=_row(value,ComboRepeatModifier)
    row['spec']=_combo_repeat_spec(row['spec'])
    return ComboRepeatModifier(**row)


def _combo_repeat_spec(value):
    from .model import ComboRepeatSpec
    from .combo_matching import combo_match_from_dict
    spec=_row(value,ComboRepeatSpec)
    spec['kinds']=tuple(CardType(k) for k in _list(spec['kinds'],'Combo repeat kinds'))
    spec['match']=combo_match_from_dict(spec['match'])
    return ComboRepeatSpec(**spec)


def _combo_recipient_from_dict(value):
    from .model import ComboRecipient
    row=_row(value,ComboRecipient)
    row['kind']=CardType(row['kind'])
    return ComboRecipient(**row)


def _combo_acceptance_from_dict(value):
    from .model import ComboAcceptanceReceipt, ComboPayload
    row=_row(value,ComboAcceptanceReceipt)
    row['recipient']=_combo_recipient_from_dict(row['recipient'])
    row['payloads']=tuple(ComboPayload(**_row(p,ComboPayload))
        for p in _list(row['payloads'],'accepted Combo declarations'))
    if row['plan'] is not None:row['plan']=_combo_plan(row['plan'])
    return ComboAcceptanceReceipt(**row)


def _deathrattle_repeat_spec(value):
    from .model import DeathrattleRepeatSpec
    from .deathrattle_matching import deathrattle_match_from_dict
    row=_row(value,DeathrattleRepeatSpec)
    row['kinds']=tuple(CardType(k) for k in _list(row['kinds'],'Deathrattle repeat kinds'))
    row['origins']=tuple(_list(row['origins'],'Deathrattle repeat origins'))
    row['match']=deathrattle_match_from_dict(row['match'])
    return DeathrattleRepeatSpec(**row)


def _deathrattle_repeat_plan(value):
    from .model import DeathrattleRepeatPlan,DeathrattleRepeatContributor,DeathrattlePlayerContributor
    row=_row(value,DeathrattleRepeatPlan);sources=[]
    for item in _list(row['contributors'],'Deathrattle repeat contributors'):
        if type(item) is dict and 'instance' in item:
            source=_row(item,DeathrattlePlayerContributor)
            source['instance']=player_effect_from_dict(source['instance'])
            source['spec']=_deathrattle_repeat_spec(source['spec']);sources.append(DeathrattlePlayerContributor(**source))
        else:
            source=_row(item,DeathrattleRepeatContributor);source['ability']=_ability_from_dict(source['ability'])
            sources.append(DeathrattleRepeatContributor(**source))
    row['contributors']=tuple(sources);return DeathrattleRepeatPlan(**row)


def _hero_power_repeat_plan(value):
    from .model import HeroPowerRepeatPlan, HeroPowerRepeatContributor
    row = _row(value, HeroPowerRepeatPlan)
    sources = []
    for item in _list(row['contributors'], 'hero power repeat contributors'):
        source = _row(item, HeroPowerRepeatContributor)
        source['ability'] = _ability_from_dict(source['ability'])
        sources.append(HeroPowerRepeatContributor(**source))
    row['contributors'] = tuple(sources)
    return HeroPowerRepeatPlan(**row)


def _hand_progress_spec(value):
    row = _row(value, HandProgressSpec)
    row['zone'] = tuple(Zone(x) for x in row['zone']) if type(row['zone']) in (list, tuple) else Zone(row['zone'])
    return HandProgressSpec(**row)


def _ability_from_dict(value):
    row = _row(value, AbilityInstance)
    if row['devour_parent'] is not None:
        from .model import BoardPresenceReference
        row['devour_parent'] = BoardPresenceReference(**_row(row['devour_parent'], BoardPresenceReference))
    if row['cost_polarity'] is not None:
        from .model import CostPolarityState
        row['cost_polarity']=CostPolarityState(**_row(row['cost_polarity'],CostPolarityState))
    if row['draw_cast'] is not None:
        row['draw_cast'] = CastWhenDrawnSpec(**_row(row['draw_cast'], CastWhenDrawnSpec))
    if row['deathrattle_copied_from'] is not None:
        from .deathrattle_copies import source_from_dict
        row['deathrattle_copied_from'] = source_from_dict(row['deathrattle_copied_from'])
    if row['prison_playback'] is not None:
        from .model import PrisonPlaybackState
        binding = _row(row['prison_playback'], PrisonPlaybackState)
        binding['consumed_discard_ids'] = tuple(_list(binding['consumed_discard_ids'], 'spent Prison discards'))
        row['prison_playback'] = PrisonPlaybackState(**binding)
    if row['spell_resummon_value'] is not None:
        from .destruction_resummon_spells import value_from_dict
        row['spell_resummon_value'] = value_from_dict(row['spell_resummon_value'])
    if row['deathrattle_inherited_from'] is not None:
        row['deathrattle_inherited_from']=tuple(_list(row['deathrattle_inherited_from'],'inherited physical Deathrattle'))
    if row['spell_base_value'] is not None:
        from .model import SpellBaseDamageValue,SpellRemainderDamageValue,SourceAttackSpellValue,GrowingSpellDamageValue
        if 'source' in row['spell_base_value']:
            from .allocation_facts import allocation_from_dict
            binding = _row(row['spell_base_value'], SourceAttackSpellValue)
            binding['source'] = allocation_from_dict(binding['source'])
            row['spell_base_value'] = SourceAttackSpellValue(**binding)
        elif 'parent_cast_id' in row['spell_base_value']:
            row['spell_base_value']=GrowingSpellDamageValue(**_row(row['spell_base_value'],GrowingSpellDamageValue))
        else:
            typ = SpellRemainderDamageValue if 'cast_id' in row['spell_base_value'] else SpellBaseDamageValue
            row['spell_base_value']=typ(**_row(row['spell_base_value'],typ))
    if row['spell_stat_value'] is not None:
        from .model import SpellStatGrantValue
        value = _row(row['spell_stat_value'], SpellStatGrantValue)
        value['cause'] = _death_cause_from_dict(value['cause'])
        row['spell_stat_value'] = SpellStatGrantValue(**value)
    if row['deathrattle_memory'] is not None:
        row['deathrattle_memory'] = deathrattle_memory_from_dict(row['deathrattle_memory'])
    if row['native_condition'] is not None:
        from .model import NativeSourceCondition
        row['native_condition']=NativeSourceCondition(**_row(row['native_condition'],NativeSourceCondition))
    if row['spell_mirror'] is not None:
        from .model import SpellMirrorBinding
        row['spell_mirror']=SpellMirrorBinding(**_row(row['spell_mirror'],SpellMirrorBinding))
    if row['hand_mirror'] is not None:
        from .model import HandMirrorBinding
        row['hand_mirror']=HandMirrorBinding(**_row(row['hand_mirror'],HandMirrorBinding))
    if row['hero_power_use_aura'] is not None:
        from .model import HeroPowerUseAuraSpec
        row['hero_power_use_aura'] = HeroPowerUseAuraSpec(**_row(row['hero_power_use_aura'],HeroPowerUseAuraSpec))
    from .model import SpellSchool
    row['spell_damage_schools'] = tuple(SpellSchool(s) for s in _list(row['spell_damage_schools'], 'spell damage schools'))
    row['aura_tribes_any'] = tuple(_list(row['aura_tribes_any'], 'stat aura tribes'))
    row['aura_card_ids'] = tuple(_list(row['aura_card_ids'], 'stat aura card IDs'))
    if row['cthun_ritual'] is not None:
        from .model import CthunRitualStamp
        row['cthun_ritual'] = CthunRitualStamp(**_row(row['cthun_ritual'], CthunRitualStamp))
    if row['stat_relation'] is not None:
        from .model import StatReference, StatRelationOperand, StatRelationLayer, StatRelationSpec
        spec = _row(row['stat_relation'], StatRelationSpec)
        spec['target'] = StatReference(spec['target'])
        spec['operand'] = StatRelationOperand(spec['operand'])
        spec['layer'] = StatRelationLayer(spec['layer'])
        row['stat_relation'] = StatRelationSpec(**spec)
    from .model import PrintedAttackPolicyDeclaration, PrintedAttackPermit
    if row['attack_policy_declaration'] is not None:
        row['attack_policy_declaration'] = PrintedAttackPolicyDeclaration(**_row(row['attack_policy_declaration'], PrintedAttackPolicyDeclaration))
    if row['printed_attack_permit'] is not None:
        permit = _row(row['printed_attack_permit'], PrintedAttackPermit)
        permit['declaration'] = PrintedAttackPolicyDeclaration(**_row(permit['declaration'], PrintedAttackPolicyDeclaration))
        row['printed_attack_permit'] = PrintedAttackPermit(**permit)
    if row['attack_source_binding'] is not None:
        from .model import AttackSourceBinding, AttackSourcePolicy, BoardPresenceReference
        binding = _row(row['attack_source_binding'], AttackSourceBinding)
        binding['reference'] = BoardPresenceReference(**_row(binding['reference'], BoardPresenceReference))
        binding['policy'] = AttackSourcePolicy(**_row(binding['policy'], AttackSourcePolicy))
        row['attack_source_binding'] = AttackSourceBinding(**binding)
    if row['attack_policy'] is not None:
        from .model import AttackPolicySpec, AttackPolicyCondition, CurrentTurnFactQuery
        spec = _row(row['attack_policy'], AttackPolicySpec)
        conditions = []
        for value in _list(spec['conditions'], 'attack policy conditions'):
            condition = _row(value, AttackPolicyCondition)
            if condition['turn_fact'] is not None:
                query = _row(condition['turn_fact'], CurrentTurnFactQuery)
                query['origins'] = tuple(_list(query['origins'], 'current-turn origins'))
                condition['turn_fact'] = CurrentTurnFactQuery(**query)
            conditions.append(AttackPolicyCondition(**condition))
        spec['conditions'] = tuple(conditions)
        row['attack_policy'] = AttackPolicySpec(**spec)
    if row['end_turn_repeat'] is not None:
        row['end_turn_repeat'] = _end_turn_repeat_spec_from_dict(row['end_turn_repeat'])
    if row['end_turn'] is not None:
        row['end_turn'] = _end_turn_spec_from_dict(row['end_turn'])
    from .model import TimedKeywordSpec, KeywordExpiry
    if row['timed_keyword'] is not None:
        spec = _row(row['timed_keyword'], TimedKeywordSpec)
        spec['keyword'] = Keyword(spec['keyword'])
        row['timed_keyword'] = TimedKeywordSpec(**spec)
    if row['keyword_expiry'] is not None:
        row['keyword_expiry'] = KeywordExpiry(**_row(row['keyword_expiry'], KeywordExpiry))
    if row['health_rule_expiry'] is not None:
        row['health_rule_expiry'] = KeywordExpiry(**_row(row['health_rule_expiry'], KeywordExpiry))
    if row['attack_policy_expiry'] is not None:
        row['attack_policy_expiry'] = KeywordExpiry(**_row(row['attack_policy_expiry'], KeywordExpiry))
    if row['limited_trigger_deadline'] is not None:
        row['limited_trigger_deadline'] = KeywordExpiry(**_row(row['limited_trigger_deadline'], KeywordExpiry))
    if row['summon_quantity'] is not None:
        from .summon_quantities import from_dict as quantity_from_dict
        from .model import SummonQuantitySpec
        row['summon_quantity']=quantity_from_dict(SummonQuantitySpec,row['summon_quantity'])
    if row['health_loss_floor'] is not None:
        from .model import HealthLossKind, HealthLossFloorSpec
        spec = _row(row['health_loss_floor'], HealthLossFloorSpec)
        spec['kinds'] = tuple(HealthLossKind(k) for k in _list(spec['kinds'], 'health loss floor kinds'))
        spec['target_kinds'] = tuple(CardType(k) for k in _list(spec['target_kinds'], 'health loss floor targets'))
        row['health_loss_floor'] = HealthLossFloorSpec(**spec)
    from .weapon_wear import from_dict as wear_from_dict
    from .model import WeaponWearSpec, PrintedWeaponWearDeclaration
    if row['weapon_wear_policy'] is not None:row['weapon_wear_policy']=wear_from_dict(WeaponWearSpec,row['weapon_wear_policy'])
    if row['weapon_wear_declaration'] is not None:row['weapon_wear_declaration']=wear_from_dict(PrintedWeaponWearDeclaration,row['weapon_wear_declaration'])
    if row['health_loss_replacement'] is not None:
        from .model import HealthLossKind, HealthLossReplacementSpec
        spec = _row(row['health_loss_replacement'], HealthLossReplacementSpec)
        spec['kinds'] = tuple(HealthLossKind(k) for k in _list(spec['kinds'], 'health loss kinds'))
        row['health_loss_replacement'] = HealthLossReplacementSpec(**spec)
    if row['deathrattle_repeat'] is not None:
        row['deathrattle_repeat']=_deathrattle_repeat_spec(row['deathrattle_repeat'])
    if row['hero_power_repeat'] is not None:
        from .model import HeroPowerRepeatSpec
        from .hero_power_matching import hero_power_match_from_dict
        spec = _row(row['hero_power_repeat'], HeroPowerRepeatSpec)
        spec['match'] = hero_power_match_from_dict(spec['match'])
        row['hero_power_repeat'] = HeroPowerRepeatSpec(**spec)
    if row['battlecry_repeat'] is not None:
        row['battlecry_repeat'] = _battlecry_repeat_spec(row['battlecry_repeat'])
    if row['combo_repeat'] is not None:
        row['combo_repeat'] = _combo_repeat_spec(row['combo_repeat'])
    if row['spell_repeat'] is not None:
        row['spell_repeat'] = _spell_repeat_spec(row['spell_repeat'])
    if row['keyword_aura'] is not None:
        from .model import KeywordAuraSpec
        spec = _row(row['keyword_aura'], KeywordAuraSpec)
        spec['keyword'] = Keyword(spec['keyword'])
        spec['tribes_any'] = tuple(_list(spec['tribes_any'], 'keyword aura tribes'))
        spec['card_ids'] = tuple(_list(spec['card_ids'], 'keyword aura card IDs'))
        row['keyword_aura'] = KeywordAuraSpec(**spec)
    if row['deck_sacrifice'] is not None:
        from .model import DeckSacrificeSpec
        spec = _row(row['deck_sacrifice'], DeckSacrificeSpec)
        spec['card_ids'] = tuple(_list(spec['card_ids'], 'deck sacrifice card IDs'))
        row['deck_sacrifice'] = DeckSacrificeSpec(**spec)
    if row['hand_progress'] is not None:
        row['hand_progress'] = _hand_progress_spec(row['hand_progress'])
    row['progress_keys'] = tuple(_list(row['progress_keys'], 'progress witnesses'))
    row['progress_units'] = tuple(_list(row['progress_units'], 'progress witness units'))
    if row['activation'] is not None:
        row['activation'] = _activation_from_dict(row['activation'])
    if row['limited_trigger'] is not None:
        spec = _row(row['limited_trigger'], LimitedTriggerSpec)
        if spec['end_turn'] is not None:
            spec['end_turn'] = _end_turn_spec_from_dict(spec['end_turn'])
        if spec['keyword'] is not None:
            spec['keyword'] = Keyword(spec['keyword'])
        row['limited_trigger'] = LimitedTriggerSpec(**spec)
    if row['counter_policy'] is not None:
        from .model import CounterPolicySpec
        spec = _row(row['counter_policy'], CounterPolicySpec)
        spec['kind'] = CardType(spec['kind'])
        row['counter_policy'] = CounterPolicySpec(**spec)
    if row['keyword'] is not None:
        if not isinstance(row['keyword'], str):
            raise ValueError('Ability keyword must be a string')
        row['keyword'] = Keyword(row['keyword'])
    if row['cost_aura'] is not None:
        from .model import CostAuraSpec
        spec = _row(row['cost_aura'], CostAuraSpec)
        spec['cost'] = _cost_spec_from_dict(spec['cost'])
        spec['tribes_any'] = tuple(spec['tribes_any'])
        row['cost_aura'] = CostAuraSpec(**spec)
    if row['health_rule'] is not None:
        row['health_rule'] = _health_rule_from_dict(row['health_rule'])
    return AbilityInstance(**row)


def _end_turn_spec_from_dict(value):
    return EndTurnSpec(**_row(value, EndTurnSpec))


def _end_turn_repeat_spec_from_dict(value):
    from .end_turn_matching import end_turn_spec_from_dict
    return end_turn_spec_from_dict(value)


def _end_turn_repeat_contributor_from_dict(value):
    row = _row(value, EndTurnRepeatContributor)
    if row['ability'] is not None:
        row['ability'] = _ability_from_dict(row['ability'])
    if row['player_effect'] is not None:
        row['player_effect'] = player_effect_from_dict(row['player_effect'])
    # Saved contributors always carry their full resolved spec, including ability sources.
    row['spec'] = _end_turn_repeat_spec_from_dict(row['spec'])
    return EndTurnRepeatContributor(**row)


def _end_turn_repeat_plan_from_dict(value):
    row = _row(value, EndTurnRepeatPlan)
    row['contributors'] = tuple(_end_turn_repeat_contributor_from_dict(source)
                                for source in _list(row['contributors'], 'end-turn repeat contributors'))
    return EndTurnRepeatPlan(**row)


def _trigger_from_dict(value):
    row = _row(value, TriggerSpec)
    if row['end_turn'] is not None:
        row['end_turn'] = _end_turn_spec_from_dict(row['end_turn'])
    return TriggerSpec(**row)


def _end_turn_subject_from_dict(value):
    row = _row(value, EndTurnSubject)
    if row['ability'] is not None:
        row['ability'] = _ability_from_dict(row['ability'])
    if row['player_effect'] is not None:
        row['player_effect'] = player_effect_from_dict(row['player_effect'])
    if row['trigger'] is not None:
        row['trigger'] = _trigger_from_dict(row['trigger'])
    return EndTurnSubject(**row)


def _end_turn_selector_from_dict(value):
    row = _row(value, EndTurnSelector)
    for name in ('player_ids', 'carrier_kinds', 'entity_ids', 'player_effect_ids'):
        row[name] = tuple(_list(row[name], 'end-turn selector ' + name))
    return EndTurnSelector(**row)


def _end_turn_request_from_dict(value):
    row = _row(value, EndTurnRequest)
    row['selector'] = _end_turn_selector_from_dict(row['selector'])
    return EndTurnRequest(**row)


def _end_turn_producer_request_from_dict(value):
    from .model import EndTurnProducerRequest
    row = _row(value, EndTurnProducerRequest)
    row['selector'] = _end_turn_selector_from_dict(row['selector'])
    return EndTurnProducerRequest(**row)


def _end_turn_carrier_from_dict(value):
    from .model import EndTurnCarrier
    row = _row(value, EndTurnCarrier)
    if row['player_effect'] is not None:
        row['player_effect'] = player_effect_from_dict(row['player_effect'])
    return EndTurnCarrier(**row)


def _end_turn_selection_from_dict(value):
    from .model import EndTurnSelection
    row = _row(value, EndTurnSelection)
    row['request'] = _end_turn_producer_request_from_dict(row['request'])
    row['candidates'] = tuple(_end_turn_carrier_from_dict(item)
                              for item in _list(row['candidates'], 'end-turn carrier candidates'))
    if row['selected'] is not None:
        row['selected'] = _end_turn_carrier_from_dict(row['selected'])
    for name in ('rng_before', 'rng_after'):
        row[name] = end_turn_rng_from_json(row[name])
    return EndTurnSelection(**row)


def _end_turn_activation_from_dict(value):
    row = _row(value, EndTurnActivation)
    if row['request'] is not None:
        row['request'] = _end_turn_request_from_dict(row['request'])
    if row['selection'] is not None:
        row['selection'] = _end_turn_selection_from_dict(row['selection'])
    return EndTurnActivation(**row)


def _end_turn_batch_from_dict(value):
    row = _row(value, EndTurnBatch)
    if row['event'] is not None:
        row['event'] = event_from_dict(_row(row['event'], Event))
    # Activation is mandatory on saved wire; never infer a natural origin.
    row['activation'] = _end_turn_activation_from_dict(row['activation'])
    row['subjects'] = tuple(_end_turn_subject_from_dict(subject)
                            for subject in _list(row['subjects'], 'end-turn subjects'))
    row['plans'] = tuple(_end_turn_repeat_plan_from_dict(plan)
                         for plan in _list(row['plans'], 'end-turn plans'))
    if len(row['plans']) != len(row['subjects']):
        raise ValueError('Saved end-turn subjects require exactly one explicit plan each')
    return EndTurnBatch(**row)


def _end_turn_capture_from_dict(value):
    row = _row(value, EndTurnCapture)
    row['subject'] = _end_turn_subject_from_dict(row['subject'])
    row['plan'] = _end_turn_repeat_plan_from_dict(row['plan'])
    return EndTurnCapture(**row)


def _end_turn_record_from_dict(value):
    row = _row(value, EndTurnRecord)
    row['capture'] = _end_turn_capture_from_dict(row['capture'])
    _integer(row['guard_id'], 'end-turn guard receipt ID', 1)
    if row['guard_event'] is not None:
        row['guard_event'] = event_from_dict(_row(row['guard_event'], Event))
    return EndTurnRecord(**row)


def _health_rule_from_dict(value):
    row = _row(value, HealthRule)
    for name, enum in (('flow', HealthFlow), ('operation', HealthOp), ('layer', HealthLayer)):
        row[name] = enum(row[name])
    for name, enum in (('target_kinds', CardType), ('damage_kinds', DamageKind),
                       ('healing_kinds', HealingKind), ('schools', SpellSchool)):
        row[name] = tuple(enum(v) for v in _list(row[name], f'health rule {name}'))
    return HealthRule(**row)


def _enchantment_from_dict(value):
    row = _row(value, Enchantment)
    if row['discovery_guess'] is not None:
        from .model import DiscoveryGuessMemory
        from .allocation_facts import allocation_from_dict
        memory = _row(row['discovery_guess'], DiscoveryGuessMemory)
        memory['recipient'] = allocation_from_dict(memory['recipient'])
        row['discovery_guess'] = DiscoveryGuessMemory(**memory)
    if row['minion_base_stats'] is not None:
        from .model import MinionBaseStatsOrigin
        row['minion_base_stats']=MinionBaseStatsOrigin(**_row(row['minion_base_stats'],MinionBaseStatsOrigin))
    if row['hand_play_lock'] is not None:
        from .model import HandPlayLock, OtherCardPlayLock, OwnerTurnExpiry
        if 'after_play_id' in row['hand_play_lock']:
            row['hand_play_lock'] = OtherCardPlayLock(**_row(row['hand_play_lock'], OtherCardPlayLock))
        else:
            lock = _row(row['hand_play_lock'], HandPlayLock)
            lock['deadline'] = OwnerTurnExpiry(**_row(lock['deadline'], OwnerTurnExpiry))
            row['hand_play_lock'] = HandPlayLock(**lock)
    if row['owner_turn_expiry'] is not None:
        from .model import OwnerTurnExpiry
        row['owner_turn_expiry'] = OwnerTurnExpiry(**_row(row['owner_turn_expiry'], OwnerTurnExpiry))
    if row['control_return_expiry'] is not None:
        from .model import OwnerTurnExpiry
        row['control_return_expiry'] = OwnerTurnExpiry(**_row(row['control_return_expiry'], OwnerTurnExpiry))
    if row['cthun_ritual'] is not None:
        from .model import CthunRitualStamp
        row['cthun_ritual'] = CthunRitualStamp(**_row(row['cthun_ritual'], CthunRitualStamp))
    if row['payment'] is not None:
        row['payment'] = PaymentType(row['payment'])
    if row['tribe_change'] is not None:
        from .model import TribeChangeSpec
        spec = _row(row['tribe_change'], TribeChangeSpec)
        spec['tribes'] = tuple(_list(spec['tribes'], 'changed tribes'))
        row['tribe_change'] = TribeChangeSpec(**spec)
    return Enchantment(**row)


def _cost_spec_from_dict(value):
    row = _row(value, CostSpec)
    if row['ability'] is not None:
        from .model import CardAbilityCondition
        row['ability'] = CardAbilityCondition(**_row(row['ability'], CardAbilityCondition))
    row['card_types'] = tuple(CardType(k) for k in _list(row['card_types'], 'cost card_types'))
    row['card_ids'] = tuple(_list(row['card_ids'], 'cost card_ids'))
    if row['payment'] is not None:
        row['payment'] = PaymentType(row['payment'])
    return CostSpec(**row)


def _cost_modifier_from_dict(value):
    row = _row(value, CostModifier)
    row['spec'] = _cost_spec_from_dict(row['spec'])
    row['scope'] = CostScope(row['scope'])
    row['tribes_any'] = tuple(_list(row['tribes_any'],'original tribal cost modifier'))
    if row['minion_keyword'] is not None:
        row['minion_keyword'] = Keyword(row['minion_keyword'])
    return CostModifier(**row)


def _cost_quote_input_from_dict(value):
    from .model import CostQuoteInput
    row = _row(value, CostQuoteInput)
    row['kind'] = CardType(row['kind'])
    row['enchantments'] = tuple(_enchantment_from_dict(v) for v in _list(row['enchantments'], 'cost quote enchantments'))
    row['abilities'] = tuple(_ability_from_dict(v) for v in _list(row['abilities'], 'cost quote abilities'))
    if row['hand_lifetime'] is not None:row['hand_lifetime']=HandLifetime(**_row(row['hand_lifetime'],HandLifetime))
    return CostQuoteInput(**row)


def _player_spell_count_cost_row_from_dict(value):
    from .model import PlayerSpellCountCostRow
    row = _row(value, PlayerSpellCountCostRow)
    if row['spell_school'] is not None:
        row['spell_school'] = SpellSchool(row['spell_school'])
    return PlayerSpellCountCostRow(**row)


def _cost_contribution_from_dict(value):
    from .model import CostContribution
    row = _row(value, CostContribution)
    if row['enchantment'] is not None: row['enchantment'] = _enchantment_from_dict(row['enchantment'])
    if row['modifier'] is not None: row['modifier'] = _cost_modifier_from_dict(row['modifier'])
    if row['ability'] is not None: row['ability'] = _ability_from_dict(row['ability'])
    if row['first_play'] is not None:
        from .model import FirstPlayCostFact, PlayerPlayedClassCostRow
        first = _row(row['first_play'], FirstPlayCostFact)
        first['kind'] = CardType(first['kind'])
        rows = []
        for value in _list(first['rows'], 'first-play original price prefix'):
            original = _row(value, PlayerPlayedClassCostRow)
            original['face'] = _played_face_from_dict(original['face'])
            rows.append(PlayerPlayedClassCostRow(**original))
        first['rows'] = tuple(rows)
        first['tribes_any'] = tuple(_list(first['tribes_any'], 'first-play original tribe qualifier'))
        if first['tribal_inputs'] is not None:
            first['tribal_inputs'] = tuple(_cost_quote_input_from_dict(x)
                for x in _list(first['tribal_inputs'], 'first-play original submitted inputs'))
        if first['cast_rows'] is not None:
            first['cast_rows'] = tuple(_player_spell_count_cost_row_from_dict(x)
                for x in _list(first['cast_rows'], 'periodic spell original cast prefix'))
        row['first_play'] = FirstPlayCostFact(**first)
    return CostContribution(**row)


def _cost_quote_fact_from_dict(value):
    from .model import CostQuoteFact
    row = _row(value, CostQuoteFact)
    row['quote_input'] = _cost_quote_input_from_dict(row['quote_input'])
    row['intrinsic'] = _intrinsic_stage_from_dict(row['intrinsic'])
    row['local_payment'] = PaymentType(row['local_payment'])
    row['payment'] = PaymentType(row['payment'])
    row['contributions'] = tuple(_cost_contribution_from_dict(v) for v in _list(row['contributions'], 'cost quote contributions'))
    for name in ('modifier_ids', 'consumable_ids'):
        row[name] = tuple(_list(row[name], 'cost quote '+name))
    return CostQuoteFact(**row)


def _hand_play_cost_from_dict(value):
    from .model import HandPlayCostReceipt
    row = _row(value, HandPlayCostReceipt)
    row['quote'] = _cost_quote_fact_from_dict(row['quote'])
    return HandPlayCostReceipt(**row)


def _spell_cost_facts_from_dict(value):
    from .model import SpellCostFacts
    row = _row(value, SpellCostFacts)
    row['cost_input'] = _cost_quote_input_from_dict(row['cost_input'])
    row['intrinsic'] = _intrinsic_stage_from_dict(row['intrinsic'])
    row['local_payment'] = PaymentType(row['local_payment'])
    row['window_quotes'] = tuple(_cost_quote_fact_from_dict(v) for v in _list(row['window_quotes'], 'Spell window cost quotes'))
    return SpellCostFacts(**row)


def _current_deck_count_match_from_dict(value):
    from .model import CurrentDeckCountMatch
    row = _row(value, CurrentDeckCountMatch)
    row['deck'] = tuple(_list(row['deck'], 'original current physical deck'))
    return CurrentDeckCountMatch(**row)


def _cost_use_from_dict(value):
    from .model import CostUseReceipt, PermanentManaMatch
    row = _row(value, CostUseReceipt)
    row['payment'] = PaymentType(row['payment'])
    row['modifier_ids'] = tuple(_list(row['modifier_ids'], 'cost use modifier IDs'))
    row['consumable_ids'] = tuple(_list(row['consumable_ids'], 'cost use consumable IDs'))
    row['player_modifiers'] = tuple(_cost_modifier_from_dict(m) for m in _list(row['player_modifiers'], 'cost use player modifiers'))
    row['kindred_sources']=tuple(player_effect_from_dict(x)for x in _list(row['kindred_sources'],'original Kindred payment sources'))
    if row['current_deck'] is not None:
        row['current_deck'] = _current_deck_count_match_from_dict(row['current_deck'])
    if row['permanent_mana'] is not None:
        row['permanent_mana'] = PermanentManaMatch(**_row(row['permanent_mana'], PermanentManaMatch))
    return CostUseReceipt(**row)


def _death_from_dict(value):
    row = _row(value, DeathRecord)
    from .death_self_copies import source_from_dict
    row['copy_source'] = source_from_dict(row['copy_source'])
    from .model import BoardPresenceReference
    row['adjacent_minions'] = tuple(BoardPresenceReference(**_row(x, BoardPresenceReference))
        for x in _list(row['adjacent_minions'], 'original death neighbors'))
    row['cause'] = _death_cause_from_dict(row['cause'])
    row['zone'] = Zone(row['zone'])
    row['components'] = tuple(_list(row['components'], 'components'))
    row['keywords'] = _keyword_list(row['keywords'])
    row['abilities'] = tuple(_ability_from_dict(item) for item in _list(row['abilities'], 'death abilities'))
    row['enchantments'] = tuple(_enchantment_from_dict(item) for item in _list(row['enchantments'], 'death enchantments'))
    return DeathRecord(**row)


def _death_cause_from_dict(value):
    row = _row(value, DeathCause)
    if not isinstance(row['result'], list):
        raise ValueError('Death result must be a JSON list')
    row['result'] = rng_from_json(row['result'])
    return DeathCause(**row)


def _canonical_id(key, name):
    if not isinstance(key, str):
        raise ValueError(f'Noncanonical {name} ID')
    try:
        parsed = int(key)
    except (ValueError, OverflowError):
        raise ValueError(f'Noncanonical {name} ID') from None
    if parsed < 1 or key != str(parsed):
        raise ValueError(f'Noncanonical {name} ID')
    return parsed


def preview_to_dict(value):
    result = asdict(value)
    result['keywords'] = [k.value for k in value.keywords]
    if value.display_name is None: result.pop('display_name')
    if value.tribes is None: result.pop('tribes')
    if not value.tribes_excluded: result.pop('tribes_excluded')
    if 'tribes' in result: result['tribes'] = list(value.tribes)
    if 'tribes_excluded' in result: result['tribes_excluded'] = list(value.tribes_excluded)
    return result


def preview_from_dict(value):
    row = _row({'display_name': None, 'tribes': None, 'tribes_excluded': [], **value}
        if type(value) is dict else value, CardPreview)
    row['keywords'] = tuple(Keyword(k) for k in _list(row['keywords'], 'preview keywords'))
    if row['tribes'] is not None: row['tribes'] = tuple(_list(row['tribes'], 'preview tribes'))
    row['tribes_excluded'] = tuple(_list(row['tribes_excluded'], 'preview tribe exclusions'))
    return CardPreview(**row)


def choice_item_from_dict(value):
    row = _row(value, ChoiceItem)
    if row['preview'] is not None: row['preview'] = preview_from_dict(row['preview'])
    return ChoiceItem(**row)


def choice_from_dict(value):
    row = _row(value, PendingChoice)
    row['options'] = tuple(choice_item_from_dict(item) for item in _list(row['options'], 'choice options'))
    row['purpose'] = ChoicePurpose(row['purpose'])
    return PendingChoice(**row)


def _played_face_from_dict(value):
    from .model import CardMetadata, FrozenPlayedFaceFact, Rarity
    row = _row(value, FrozenPlayedFaceFact)
    row['kind'] = CardType(row['kind'])
    if row['spell_school'] is not None:
        row['spell_school'] = SpellSchool(row['spell_school'])
    if row['metadata'] is not None:
        metadata = _row(row['metadata'], CardMetadata)
        metadata['classes'] = tuple(CardClass(v) for v in _list(metadata['classes'], 'frozen face classes'))
        if metadata['rarity'] is not None:
            metadata['rarity'] = Rarity(metadata['rarity'])
        if metadata['runes'] is not None:
            metadata['runes'] = Runes(**_row(metadata['runes'], Runes))
        for name in ('tribes', 'factions', 'subtypes'):
            if metadata[name] is not None:
                metadata[name] = tuple(_list(metadata[name], 'frozen face ' + name))
        row['metadata'] = CardMetadata(**metadata)
    return FrozenPlayedFaceFact(**row)


def _owner_turn_from_dict(value):
    from .model import OwnerTurnRecord, OwnerTurnStartInterruption
    row = _row(value, OwnerTurnRecord)
    if row['start_interruption'] is not None:
        row['start_interruption'] = OwnerTurnStartInterruption(**_row(row['start_interruption'], OwnerTurnStartInterruption))
    return OwnerTurnRecord(**row)


def _previous_owner_match_from_dict(value):
    from .model import PreviousOwnerTurnMatch, OwnerTurnMatchRow, PlayedTypeQuery
    row = _row(value, PreviousOwnerTurnMatch)
    query = _row(row['query'], PlayedTypeQuery)
    query['kind'] = CardType(query['kind'])
    if query['tribes'] is not None: query['tribes'] = tuple(_list(query['tribes'], 'intrinsic query tribes'))
    if query['spell_school'] is not None: query['spell_school'] = SpellSchool(query['spell_school'])
    row['query'] = PlayedTypeQuery(**query)
    if row['owner_turn'] is not None: row['owner_turn'] = _owner_turn_from_dict(row['owner_turn'])
    rows = []
    for item in _list(row['rows'], 'intrinsic complete history rows'):
        record = _row(item, OwnerTurnMatchRow)
        record['face'] = _played_face_from_dict(record['face'])
        rows.append(OwnerTurnMatchRow(**record))
    row['rows'] = tuple(rows)
    return PreviousOwnerTurnMatch(**row)


def _intrinsic_spec_from_dict(value):
    from .model import IntrinsicCostSpec
    row=_row(value,IntrinsicCostSpec)
    row['card_ids']=tuple(_list(row['card_ids'],'intrinsic exact controlled card selectors'))
    return IntrinsicCostSpec(**row)


def _intrinsic_stage_from_dict(value):
    from .model import (IntrinsicCostSpec, IntrinsicCostStageFact, BoardMinionCostSpec,
                        BoardMinionCostFact, BoardMinionCostRow, HandCountCostSpec, HandCountCostFact,
                        HeroMissingHealthCostSpec, HeroMissingHealthCostFact,
                        PlayerSpellCountCostSpec, PlayerSpellCountCostRow, PlayerSpellCountCostFact,
                        PlayerHeroPowerCountCostSpec, PlayerHeroPowerCountCostRow, PlayerHeroPowerCountCostFact,
                        PlayerSpellManaCostSpec, PlayerSpellManaCostRow, PlayerSpellManaCostFact,
                        MinionDeathCostSpec, MinionDeathCostFact,
                        PlayerOverloadCostSpec, PlayerOverloadCostFact, OverloadRecord,
                        PlayerPlayedClassCostSpec, PlayerPlayedClassCostRow, PlayerPlayedClassCostFact,
                        HeroHealthChangeCostSpec, HeroHealthChangeCostFact, HeroHealthChangeRecord,
                        PlayerDrawCountCostSpec, PlayerDrawCountCostFact,
                        PlayerWeaponAttackCostSpec, PlayerWeaponAttackCostFact,
                        PlayerArmorCostSpec, PlayerArmorCostFact,
                        PlayerSummonCountCostSpec, PlayerSummonCountCostFact,
                        PlayerElementalStreakCostSpec, PlayerElementalStreakCostFact,
                        PlayerCorpseSpendCostSpec, PlayerCorpseSpendCostFact, CorpseSpendRecord,
                        IntrinsicCostOperationFact, OwnerTurnQueryBoundaryFact)
    row = _row(value, IntrinsicCostStageFact)
    row['kindred_sources']=tuple(player_effect_from_dict(x)for x in _list(row['kindred_sources'],'intrinsic Kindred sources'))
    row['kind'] = CardType(row['kind'])
    boundary = _row(row['boundary'], OwnerTurnQueryBoundaryFact)
    if boundary['last_owner_turn'] is not None:
        boundary['last_owner_turn'] = _owner_turn_from_dict(boundary['last_owner_turn'])
    row['boundary'] = OwnerTurnQueryBoundaryFact(**boundary)
    row['rules'] = tuple(_intrinsic_spec_from_dict(v) for v in _list(row['rules'], 'intrinsic rules'))
    from .model import PRESENCE_COST_CONDITIONS
    if row['rules'] and row['rules'][0].condition in PRESENCE_COST_CONDITIONS:
        from .cost_presence import from_dict
        row['condition_facts'] = tuple(from_dict(v) for v in _list(row['condition_facts'],'original presence conditions'))
    elif row['rules'] and row['rules'][0].condition == 'current_deck_count':
        row['condition_facts'] = tuple(_current_deck_count_match_from_dict(value)
            for value in _list(row['condition_facts'], 'intrinsic current deck conditions'))
    elif row['rules'] and row['rules'][0].condition == 'hand_other_class':
        from .model import HandOtherClassMatch, HandOtherClassRow
        conditions = []
        for value in _list(row['condition_facts'], 'intrinsic hand class conditions'):
            condition = _row(value,HandOtherClassMatch)
            condition['hero_class'] = CardClass(condition['hero_class'])
            condition['rows'] = tuple(HandOtherClassRow(**_row(v,HandOtherClassRow)) for v in _list(condition['rows'],'original hand class rows'))
            conditions.append(HandOtherClassMatch(**condition))
        row['condition_facts'] = tuple(conditions)
    elif row['rules'] and row['rules'][0].condition == 'permanent_mana_at_least':
        from .model import PermanentManaMatch
        row['condition_facts'] = tuple(PermanentManaMatch(**_row(v,PermanentManaMatch))
            for v in _list(row['condition_facts'],'intrinsic permanent mana conditions'))
    elif row['rules'] and row['rules'][0].condition == 'own_location_use_count':
        from .location_uses import match_from_dict
        row['condition_facts']=tuple(match_from_dict(v)for v in _list(row['condition_facts'],'original location-use conditions'))
    elif row['rules'] and row['rules'][0].condition == 'own_deck_shuffle_count':
        from .model import DeckShuffleCostMatch
        from .deck_shuffles import row_from_dict
        conditions=[]
        for value in _list(row['condition_facts'],'original shuffle price conditions'):
            condition=_row(value,DeckShuffleCostMatch)
            condition['records']=tuple(row_from_dict(r) for r in _list(condition['records'],'original shuffle operation prefix'))
            condition['selected_ids']=tuple(_list(condition['selected_ids'],'original selected shuffle operations'))
            conditions.append(DeckShuffleCostMatch(**condition))
        row['condition_facts']=tuple(conditions)
    elif row['rules'] and row['rules'][0].condition == 'held_opponent_copy':
        from .model import HeldOpponentCopyMatch
        conditions = []
        for value in _list(row['condition_facts'], 'original held copied-play conditions'):
            condition = _row(value, HeldOpponentCopyMatch)
            condition['play_ids'] = tuple(_list(condition['play_ids'], 'original copied-play witnesses'))
            conditions.append(HeldOpponentCopyMatch(**condition))
        row['condition_facts'] = tuple(conditions)
    elif row['rules'] and row['rules'][0].condition == 'card_discovered_this_turn':
        from .model import CardDiscoveredTurnMatch
        from .card_discoveries import record_from_dict
        conditions = []
        for value in _list(row['condition_facts'], 'original discovery price conditions'):
            condition = _row(value, CardDiscoveredTurnMatch)
            condition['records'] = tuple(record_from_dict(v)
                for v in _list(condition['records'], 'original discovery price prefix'))
            conditions.append(CardDiscoveredTurnMatch(**condition))
        row['condition_facts'] = tuple(conditions)
    elif row['rules'] and row['rules'][0].condition == 'hero_healed_this_turn':
        from .model import HeroHealedTurnMatch
        from .healing_history import record_from_dict
        conditions = []
        for value in _list(row['condition_facts'], 'intrinsic conditions'):
            condition = _row(value, HeroHealedTurnMatch)
            condition['records'] = tuple(record_from_dict(v) for v in _list(condition['records'], 'hero-healed original records'))
            conditions.append(HeroHealedTurnMatch(**condition))
        row['condition_facts'] = tuple(conditions)
    else:
        row['condition_facts'] = tuple(_previous_owner_match_from_dict(v) for v in _list(row['condition_facts'], 'intrinsic conditions'))
    operations = []
    for item in _list(row['operations'], 'intrinsic operations'):
        operation = _row(item, IntrinsicCostOperationFact)
        operation['spec'] = _intrinsic_spec_from_dict(operation['spec'])
        operations.append(IntrinsicCostOperationFact(**operation))
    row['operations'] = tuple(operations)
    if row['board_minions'] is not None:
        board = _row(row['board_minions'], BoardMinionCostFact)
        board['spec'] = BoardMinionCostSpec(**_row(board['spec'], BoardMinionCostSpec))
        def board_row(value):
            entry = _row(value,BoardMinionCostRow)
            if entry['tribe_changes'] is not None:
                entry['tribe_changes'] = tuple(_enchantment_from_dict(c) for c in _list(entry['tribe_changes'],'original board tribe attachments'))
            return BoardMinionCostRow(**entry)
        board['boards'] = tuple(tuple(board_row(v) for v in _list(b, 'board price rows'))
            for b in _list(board['boards'], 'board price inventories'))
        row['board_minions'] = BoardMinionCostFact(**board)
    if row['hand_cards'] is not None:
        from .hand_count_costs import fact_from_dict
        row['hand_cards'] = fact_from_dict(row['hand_cards'])
    if row['hero_missing_health'] is not None:
        hero = _row(row['hero_missing_health'], HeroMissingHealthCostFact)
        hero['spec'] = HeroMissingHealthCostSpec(**_row(hero['spec'], HeroMissingHealthCostSpec))
        row['hero_missing_health'] = HeroMissingHealthCostFact(**hero)
    if row['player_spells'] is not None:
        personal = _row(row['player_spells'], PlayerSpellCountCostFact)
        personal['spec'] = PlayerSpellCountCostSpec(**_row(personal['spec'], PlayerSpellCountCostSpec))
        personal_rows = []
        for value in _list(personal['rows'], 'personal spell price prefix'):
            original = _row(value, PlayerSpellCountCostRow)
            if original['spell_school'] is not None:
                original['spell_school'] = SpellSchool(original['spell_school'])
            personal_rows.append(PlayerSpellCountCostRow(**original))
        personal['rows'] = tuple(personal_rows)
        row['player_spells'] = PlayerSpellCountCostFact(**personal)
    if row['player_hero_powers'] is not None:
        powers = _row(row['player_hero_powers'], PlayerHeroPowerCountCostFact)
        powers['spec'] = PlayerHeroPowerCountCostSpec(**_row(powers['spec'], PlayerHeroPowerCountCostSpec))
        power_rows = []
        for value in _list(powers['rows'], 'personal power price prefix'):
            power = _row(value, PlayerHeroPowerCountCostRow)
            power['payment'] = None if power['payment'] is None else PaymentType(power['payment'])
            power_rows.append(PlayerHeroPowerCountCostRow(**power))
        powers['rows'] = tuple(power_rows)
        row['player_hero_powers'] = PlayerHeroPowerCountCostFact(**powers)
    if row['player_spell_mana'] is not None:
        mana = _row(row['player_spell_mana'], PlayerSpellManaCostFact)
        mana['spec'] = PlayerSpellManaCostSpec(**_row(mana['spec'], PlayerSpellManaCostSpec))
        mana_rows = []
        for value in _list(mana['rows'], 'original spell mana price prefix'):
            paid = _row(value, PlayerSpellManaCostRow)
            paid['kind'] = CardType(paid['kind'])
            paid['payment'] = PaymentType(paid['payment'])
            mana_rows.append(PlayerSpellManaCostRow(**paid))
        mana['rows'] = tuple(mana_rows)
        from .resources import mana_consumption_from_dict
        mana['consumption_rows'] = tuple(mana_consumption_from_dict(value)
            for value in _list(mana['consumption_rows'],'original direct mana price prefix'))
        row['player_spell_mana'] = PlayerSpellManaCostFact(**mana)
    if row['minion_deaths'] is not None:
        deaths = _row(row['minion_deaths'], MinionDeathCostFact)
        deaths['spec'] = MinionDeathCostSpec(**_row(deaths['spec'], MinionDeathCostSpec))
        deaths['records'] = tuple(_death_from_dict(value) for value in _list(deaths['records'], 'original destruction price prefix'))
        deaths['selected_ids'] = tuple(_list(deaths['selected_ids'], 'selected original death occurrences'))
        row['minion_deaths'] = MinionDeathCostFact(**deaths)
    if row['player_overload'] is not None:
        overload = _row(row['player_overload'], PlayerOverloadCostFact)
        overload['spec'] = PlayerOverloadCostSpec(**_row(overload['spec'], PlayerOverloadCostSpec))
        overload['records'] = tuple(OverloadRecord(**_row(value, OverloadRecord))
            for value in _list(overload['records'], 'original overload price prefix'))
        row['player_overload'] = PlayerOverloadCostFact(**overload)
    if row['player_played_class'] is not None:
        played = _row(row['player_played_class'], PlayerPlayedClassCostFact)
        spec = _row(played['spec'], PlayerPlayedClassCostSpec)
        spec['card_class'] = None if spec['card_class'] is None else CardClass(spec['card_class'])
        played['spec'] = PlayerPlayedClassCostSpec(**spec)
        originals = []
        for value in _list(played['rows'], 'original class price face prefix'):
            original = _row(value, PlayerPlayedClassCostRow)
            original['face'] = _played_face_from_dict(original['face'])
            originals.append(PlayerPlayedClassCostRow(**original))
        played['rows'] = tuple(originals)
        played['selected_ids'] = tuple(_list(played['selected_ids'], 'original selected class plays'))
        if played['combo_inputs'] is not None:
            played['combo_inputs'] = tuple(_cost_quote_input_from_dict(value)
                for value in _list(played['combo_inputs'], 'original Combo-card submitted inputs'))
        for key in ('starting_entities', 'starting_cards'):
            if played[key] is not None:
                played[key] = tuple(tuple(_list(group, 'original starting-deck group'))
                                    for group in _list(played[key], 'original starting-deck pair'))
        row['player_played_class'] = PlayerPlayedClassCostFact(**played)
    if row['hero_health_changes'] is not None:
        health = _row(row['hero_health_changes'], HeroHealthChangeCostFact)
        health['spec'] = HeroHealthChangeCostSpec(**_row(health['spec'], HeroHealthChangeCostSpec))
        health['records'] = tuple(HeroHealthChangeRecord(**_row(value, HeroHealthChangeRecord))
            for value in _list(health['records'], 'original hero health-change price prefix'))
        row['hero_health_changes'] = HeroHealthChangeCostFact(**health)
    if row['player_draws'] is not None:
        draws = _row(row['player_draws'], PlayerDrawCountCostFact)
        draws['spec'] = PlayerDrawCountCostSpec(**_row(draws['spec'], PlayerDrawCountCostSpec))
        draws['records'] = tuple(_draw_from_dict(v) for v in _list(draws['records'], 'original physical draw price prefix'))
        draws['selected_ids'] = tuple(_list(draws['selected_ids'], 'original selected physical draws'))
        row['player_draws'] = PlayerDrawCountCostFact(**draws)
    if row['weapon_attack'] is not None:
        weapon = _row(row['weapon_attack'], PlayerWeaponAttackCostFact)
        weapon['spec'] = PlayerWeaponAttackCostSpec(**_row(weapon['spec'], PlayerWeaponAttackCostSpec))
        if weapon['weapon_allocation'] is not None:
            weapon['weapon_allocation'] = tuple(tuple(_list(v, 'original weapon allocation field'))
                for v in _list(weapon['weapon_allocation'], 'original weapon allocation'))
        row['weapon_attack'] = PlayerWeaponAttackCostFact(**weapon)
    if row['player_armor'] is not None:
        armor = _row(row['player_armor'], PlayerArmorCostFact)
        armor['spec'] = PlayerArmorCostSpec(**_row(armor['spec'], PlayerArmorCostSpec))
        armor['hero_allocation'] = tuple(tuple(_list(v, 'original Armor hero allocation field'))
            for v in _list(armor['hero_allocation'], 'original Armor hero allocation'))
        row['player_armor'] = PlayerArmorCostFact(**armor)
    if row['player_summons'] is not None:
        from .successful_summons import record_from_dict as successful_summon_from_dict
        summons = _row(row['player_summons'], PlayerSummonCountCostFact)
        from .model import TreantSummonCountCostSpec
        if type(summons['spec']) is dict and summons['spec'].get('profile_id')=='cost.player-summoned-treant-count-v1':
            spec = _row(summons['spec'], TreantSummonCountCostSpec)
            spec['card_ids'] = tuple(_list(spec['card_ids'], 'complete original Treant identity group'))
            summons['spec'] = TreantSummonCountCostSpec(**spec)
        else:
            summons['spec'] = PlayerSummonCountCostSpec(**_row(summons['spec'], PlayerSummonCountCostSpec))
        summons['records'] = tuple(successful_summon_from_dict(item)
            for item in _list(summons['records'], 'original successful summon price prefix'))
        summons['selected_ids'] = tuple(_list(summons['selected_ids'], 'original selected successful summons'))
        from .summon_deathrattle_qualifications import from_dict as qualification_from_dict
        summons['deathrattle_qualifications']=tuple(qualification_from_dict(item) for item in
            _list(summons['deathrattle_qualifications'],'original own-entry Deathrattle qualifications'))
        row['player_summons'] = PlayerSummonCountCostFact(**summons)
    if row['player_elemental_streak'] is not None:
        streak = _row(row['player_elemental_streak'], PlayerElementalStreakCostFact)
        streak['spec'] = PlayerElementalStreakCostSpec(**_row(streak['spec'], PlayerElementalStreakCostSpec))
        original_boundary = _row(streak['boundary'], OwnerTurnQueryBoundaryFact)
        if original_boundary['last_owner_turn'] is not None:
            original_boundary['last_owner_turn'] = _owner_turn_from_dict(original_boundary['last_owner_turn'])
        streak['boundary'] = OwnerTurnQueryBoundaryFact(**original_boundary)
        streak['owner_turns'] = tuple(_owner_turn_from_dict(v)
            for v in _list(streak['owner_turns'], 'original Elemental price owner prefix'))
        originals = []
        for item in _list(streak['rows'], 'original Elemental price physical face prefix'):
            original = _row(item, PlayerPlayedClassCostRow)
            original['face'] = _played_face_from_dict(original['face'])
            originals.append(PlayerPlayedClassCostRow(**original))
        streak['rows'] = tuple(originals)
        streak['selected_interval_ids'] = tuple(_list(streak['selected_interval_ids'], 'original consecutive own intervals'))
        row['player_elemental_streak'] = PlayerElementalStreakCostFact(**streak)
    if row['player_corpses'] is not None:
        corpses = _row(row['player_corpses'], PlayerCorpseSpendCostFact)
        corpses['spec'] = PlayerCorpseSpendCostSpec(**_row(corpses['spec'], PlayerCorpseSpendCostSpec))
        corpses['records'] = tuple(CorpseSpendRecord(**_row(item, CorpseSpendRecord))
            for item in _list(corpses['records'], 'original successful corpse debit price prefix'))
        row['player_corpses'] = PlayerCorpseSpendCostFact(**corpses)
    if row['hero_damage_taken'] is not None:
        from .model import HeroDamageTakenCostSpec, HeroDamageTakenCostFact
        from .damage_history import record_from_dict
        damage = _row(row['hero_damage_taken'], HeroDamageTakenCostFact)
        damage['spec'] = HeroDamageTakenCostSpec(**_row(damage['spec'], HeroDamageTakenCostSpec))
        damage['records'] = tuple(record_from_dict(item) for item in
            _list(damage['records'], 'complete original received-damage price packets'))
        row['hero_damage_taken'] = HeroDamageTakenCostFact(**damage)
    if row['player_spell_damage'] is not None:
        from .model import PlayerSpellDamageCostSpec, PlayerSpellDamageCostRow, PlayerSpellDamageCostFact
        from .damage_history import record_from_dict
        damage = _row(row['player_spell_damage'], PlayerSpellDamageCostFact)
        damage['spec'] = PlayerSpellDamageCostSpec(**_row(damage['spec'], PlayerSpellDamageCostSpec))
        rows = []
        for item in _list(damage['rows'], 'complete original spell damage price packets'):
            original = _row(item, PlayerSpellDamageCostRow)
            original['record'] = record_from_dict(original['record'])
            if original['source_kind'] is not None:
                original['source_kind'] = CardType(original['source_kind'])
            rows.append(PlayerSpellDamageCostRow(**original))
        damage['rows'] = tuple(rows)
        row['player_spell_damage'] = PlayerSpellDamageCostFact(**damage)
    if row['player_character_attacks'] is not None:
        from .model import PlayerCharacterAttackCostSpec, PlayerCharacterAttackCostFact
        from .character_attacks import record_from_dict
        attacks = _row(row['player_character_attacks'], PlayerCharacterAttackCostFact)
        attacks['spec'] = PlayerCharacterAttackCostSpec(**_row(attacks['spec'], PlayerCharacterAttackCostSpec))
        attacks['records'] = tuple(record_from_dict(item) for item in
            _list(attacks['records'], 'complete original character declarations'))
        row['player_character_attacks'] = PlayerCharacterAttackCostFact(**attacks)
    return IntrinsicCostStageFact(**row)


def _draw_from_dict(value):
    row = _row(value, DrawRecord)
    if row['cast_grant'] is not None:
        from .draw_cast_grants import from_dict as draw_grant_from_dict
        row['cast_grant'] = draw_grant_from_dict(row['cast_grant'])
    if row['spec'] is not None:
        row['spec'] = CastWhenDrawnSpec(**_row(row['spec'], CastWhenDrawnSpec))
    return DrawRecord(**row)


def _spell_cast_from_dict(value):
    row = _row(value, SpellCastRecord)
    from .spell_target_groups import selection_from_dict as spell_group_from_dict
    row['spell_target_group'] = spell_group_from_dict(row['spell_target_group'])
    from .automatic_spell_groups import receipt_from_dict as actual_spell_targets_from_dict
    row['spell_target_receipt'] = actual_spell_targets_from_dict(row['spell_target_receipt'])
    if row['source_cost'] is not None:row['source_cost'] = _cost_quote_fact_from_dict(row['source_cost'])
    row['hand_cost_rank'] = _hand_cost_rank_from_dict(row['hand_cost_rank'])
    from .spell_mana_budget import link_from_dict
    row['mana_budget']=link_from_dict(row['mana_budget'])
    row['held_higher_cost'] = _held_higher_cost_from_dict(row['held_higher_cost'])
    if row['target_origin'] is not None:
        from .allocation_facts import allocation_from_dict
        row['target_origin']=allocation_from_dict(row['target_origin'])
    row['local_spell_damage'] = tuple(_ability_from_dict(a)
        for a in _list(row['local_spell_damage'], 'original local spell damage abilities'))
    if row['native_spell_value'] is not None:row['native_spell_value']=_ability_from_dict(row['native_spell_value'])
    row['aura_duration_grants'] = tuple(_ability_from_dict(a)
        for a in _list(row['aura_duration_grants'], 'original Aura duration attachments'))
    row['spell_damage_effects'] = tuple(player_effect_from_dict(e)
        for e in _list(row['spell_damage_effects'], 'claimed next-spell damage effects'))
    row['next_spell_body_effects'] = tuple(player_effect_from_dict(e)
        for e in _list(row['next_spell_body_effects'], 'claimed next-spell body programs'))
    if 'next_spell_body_cursor' not in row:
        raise ValueError('Cast lost its original next-spell body cursor')
    row['next_spell_bonus_effects'] = tuple(player_effect_from_dict(e)
        for e in _list(row['next_spell_bonus_effects'], 'original paired next-spell effects'))
    if row['target_selection'] is not None:
        from .automatic_targets import selection_from_dict
        row['target_selection'] = selection_from_dict(row['target_selection'])
    if row['from_zone'] is not None:
        row['from_zone'] = Zone(row['from_zone'])
    return SpellCastRecord(**row)


def _hand_cost_rank_from_dict(value):
    if value is None: return None
    from .model import HandCostRankFact
    row = _row(value, HandCostRankFact)
    row['source_zone'] = Zone(row['source_zone'])
    row['quotes'] = tuple(_cost_quote_fact_from_dict(q) for q in _list(row['quotes'], 'hand rank quotes'))
    return HandCostRankFact(**row)


def _held_higher_cost_from_dict(value):
    if value is None: return None
    from .model import HeldHigherCostProgress
    row = _row(value, HeldHigherCostProgress)
    row['spec'] = _hand_progress_spec(row['spec'])
    row['keys'] = tuple(_list(row['keys'], 'original higher-cost witnesses'))
    return HeldHigherCostProgress(**row)


def state_from_dict(value: dict) -> GameState:
    value = _row(deepcopy(value), GameState)
    from .model import TemporaryHeroPowerReturn
    bindings = value['temporary_power_returns']
    if type(bindings) is not dict: raise ValueError('Temporary hero powers require a physical binding map')
    parsed = {}
    for key, item in bindings.items():
        if type(key) is not str or not key.isdecimal() or str(int(key)) != key:
            raise ValueError('Invalid temporary hero power identity')
        row = _row(item, TemporaryHeroPowerReturn)
        row['use_ids'] = tuple(_list(row['use_ids'], 'temporary power original uses'))
        parsed[int(key)] = TemporaryHeroPowerReturn(**row)
    value['temporary_power_returns'] = parsed
    from .card_discoveries import rows_from_dict as discovery_rows_from_dict
    discovery_rows_from_dict(value)
    from .battlecry_weapon_outputs import from_dict as weapon_output_from_dict
    value['battlecry_weapon_outputs'] = [weapon_output_from_dict(row) for row in
        _list(value['battlecry_weapon_outputs'], 'Battlecry weapon outputs')]
    from .kindred import rows_from_dict as kindred_rows_from_dict
    kindred_rows_from_dict(value)
    _optional_id(value['board_id'], 'game board ID')
    from .model import TurnSchedule
    schedule = _row(value['turn_schedule'], TurnSchedule)
    for name in ('pending', 'skip_counts'):
        schedule[name] = tuple(_list(schedule[name], 'turn schedule ' + name))
    schedule['controlled_slots']=tuple(tuple(_list(v,'controlled slot')) for v in _list(schedule['controlled_slots'],'controlled slots'))
    value['turn_schedule'] = TurnSchedule(**schedule)
    from .whole_card_replay_state import decode as decode_whole_card_replay
    value['whole_card_replay_ledger'] = decode_whole_card_replay(value['whole_card_replay_ledger'])
    from .natural_turn_end import record_from_dict as natural_turn_end_record_from_dict
    value['natural_turn_end_requests'] = [natural_turn_end_record_from_dict(row)
        for row in _list(value['natural_turn_end_requests'],'original natural end requests')]
    from .controlled_turns import record_from_dict as controlled_turn_record_from_dict
    value['controlled_turn_requests']=[controlled_turn_record_from_dict(row) for row in
        _list(value['controlled_turn_requests'],'original controlled turn requests')]
    players, entities = value.pop('players'), value.pop('entities')
    if not isinstance(players, dict) or not isinstance(entities, dict):
        raise ValueError('Players and entities must be objects')
    for name in ('active_player', 'turn', 'next_entity_id', 'next_order',
                 'next_attachment_id', 'next_death_id', 'next_death_batch', 'next_deathrattle_id',
                 'next_choice_id', 'next_window_id', 'next_resource_operation_id', 'next_hero_lethal_id'):
        _integer(value[name], name, 1)
    _integer(value['action_number'], 'action_number', 0)
    from .model import OverloadRecord
    _integer(value['next_overload_id'], 'next_overload_id', 1)
    value['overload_history'] = [OverloadRecord(**_row(item, OverloadRecord))
        for item in _list(value['overload_history'], 'overload history')]
    from .model import HeroHealthChangeRecord
    _integer(value['next_hero_health_change_id'], 'next_hero_health_change_id', 1)
    value['hero_health_change_history'] = [HeroHealthChangeRecord(**_row(item, HeroHealthChangeRecord))
        for item in _list(value['hero_health_change_history'], 'hero health change history')]
    from .armor_gains import record_from_dict as armor_gain_from_dict
    value['armor_gain_history'] = [armor_gain_from_dict(item)
        for item in _list(value['armor_gain_history'], 'armor gain history')]
    from .healing_history import rows_from_dict as healing_rows_from_dict
    healing_rows_from_dict(value)
    from .damage_history import rows_from_dict as damage_rows_from_dict
    damage_rows_from_dict(value)
    from .model import CorpseSpendRecord
    from .resources import mana_consumption_from_dict
    value['mana_consumption_history'] = [mana_consumption_from_dict(item)
        for item in _list(value['mana_consumption_history'],'original direct mana history')]
    value['corpse_spend_history'] = [CorpseSpendRecord(**_row(item, CorpseSpendRecord))
        for item in _list(value['corpse_spend_history'], 'original corpse debit history')]
    from .deck_shuffles import row_from_dict as shuffle_from_dict
    value['deck_shuffle_history']=[shuffle_from_dict(r) for r in _list(value['deck_shuffle_history'],'original shuffle operations')]
    from .location_uses import row_from_dict as location_use_from_dict
    value['location_use_history']=[location_use_from_dict(r)for r in _list(value['location_use_history'],'original location activations')]
    from .discard_history import rows_from_dict as discard_rows_from_dict
    discard_rows_from_dict(value)
    from .successful_summons import rows_from_dict as successful_summon_rows_from_dict
    successful_summon_rows_from_dict(value)
    from .summon_deathrattle_qualifications import from_dict as qualification_from_dict
    value['summon_deathrattle_qualifications']=[qualification_from_dict(item) for item in
        _list(value['summon_deathrattle_qualifications'],'own-entry Deathrattle qualification history')]
    from .rituals import rows_from_dict as ritual_rows_from_dict
    ritual_rows_from_dict(value)
    _optional_id(value['winner'], 'winner')
    if value['status'] not in ('playing', 'finished', 'draw'):
        raise ValueError('Invalid game status')
    from .hero_lethal_windows import state_rows_from_dict
    state_rows_from_dict(value)
    from .summon_quantities import rows_from_dict as summon_rows_from_dict
    summon_rows_from_dict(value)
    from .pool_summons import rows_from_dict as pool_summon_rows_from_dict
    pool_summon_rows_from_dict(value)
    from .ordered_group_batches import rows_from_dict as ordered_group_rows_from_dict
    ordered_group_rows_from_dict(value)
    from .discovery_summons import rows_from_dict as discovery_summon_rows_from_dict
    discovery_summon_rows_from_dict(value)
    from .hand_choice_followups import rows_from_dict as hand_followup_rows_from_dict
    hand_followup_rows_from_dict(value)
    from .temporary_hands import rows_from_dict as temporary_hand_rows_from_dict
    temporary_hand_rows_from_dict(value)
    from .future_hand_returns import rows_from_dict as future_hand_rows_from_dict
    future_hand_rows_from_dict(value)
    from .overdraw_returns import rows_from_dict as overdraw_rows_from_dict
    overdraw_rows_from_dict(value)
    from .quest_hand_rewards import rows_from_dict as quest_hand_reward_rows_from_dict
    quest_hand_reward_rows_from_dict(value)
    from .consumed_cards import rows_from_dict as consumed_card_rows_from_dict
    consumed_card_rows_from_dict(value)
    from .spell_auras import rows_from_dict as spell_aura_rows_from_dict
    spell_aura_rows_from_dict(value)
    from .hand_deadlines import rows_from_dict as hand_deadline_rows_from_dict
    hand_deadline_rows_from_dict(value)
    from .live_hand_spells import rows_from_dict as live_hand_spell_rows_from_dict
    live_hand_spell_rows_from_dict(value)
    from .recruit_summons import rows_from_dict as recruit_summon_rows_from_dict
    recruit_summon_rows_from_dict(value)
    from .resurrection_summons import rows_from_dict as resurrection_summon_rows_from_dict
    resurrection_summon_rows_from_dict(value)
    from .ability_families import rows_from_dict as ability_family_rows_from_dict
    ability_family_rows_from_dict(value)
    from .random_split_damage import rows_from_dict as split_rows_from_dict
    split_rows_from_dict(value)
    from .resource_operations import SpendUpToResource, ResourceConsumptionResult, ResourceConsumptionReceipt, SourceAllocationFact
    operations=[]
    for item in _list(value['resource_operations'], 'resource operations'):
        row=_row(item,ResourceConsumptionReceipt)
        request=_row(row['request'],SpendUpToResource); request['resource']=Resource(request['resource'])
        from .hero_lethal_windows import reference_from_dict
        if request['hero_lethal_reference'] is not None:request['hero_lethal_reference']=reference_from_dict(request['hero_lethal_reference'])
        result=_row(row['result'],ResourceConsumptionResult); result['resource']=Resource(result['resource'])
        if result['source_zone'] is not None: result['source_zone']=Zone(result['source_zone'])
        if result['hero_lethal_reference'] is not None:result['hero_lethal_reference']=reference_from_dict(result['hero_lethal_reference'])
        if result['source_allocation'] is not None:
            allocation=_row(result['source_allocation'],SourceAllocationFact)
            allocation['kind']=CardType(allocation['kind']); allocation['zone']=Zone(allocation['zone'])
            result['source_allocation']=SourceAllocationFact(**allocation)
        row['request']=SpendUpToResource(**request); row['result']=ResourceConsumptionResult(**result)
        row['event']=event_from_dict(row['event'])
        operations.append(ResourceConsumptionReceipt(**row))
    value['resource_operations']=operations
    value['death_history'] = [_death_from_dict(item) for item in _list(value['death_history'], 'death_history')]
    resurrections = []
    for item in _list(value['resurrection_history'], 'resurrection history'):
        row = _row(item, ResurrectionRecord)
        if row['stats'] is not None: row['stats'] = SummonStats(**_row(row['stats'], SummonStats))
        resurrections.append(ResurrectionRecord(**row))
    value['resurrection_history'] = resurrections
    from .model import BattlecryPayload, BattlecryAcceptanceReceipt, BattlecryRecipient
    from .hero_attack_history import record_from_dict
    value['hero_attack_history'] = [record_from_dict(item) for item in _list(value['hero_attack_history'], 'hero attack history')]
    from .character_attacks import record_from_dict as character_attack_from_dict
    value['character_attack_history'] = [character_attack_from_dict(item) for item in
        _list(value['character_attack_history'], 'character attack history')]
    value['owner_turn_history'] = [_owner_turn_from_dict(item)
        for item in _list(value['owner_turn_history'], 'owner-turn history')]
    plays=[]
    for item in _list(value['play_history'], 'play history'):
        row=_row(item, PlayRecord)
        from .played_minion_copies import from_dict as played_minion_copy_from_dict
        if row['minion_copy_material'] is not None:
            row['minion_copy_material'] = played_minion_copy_from_dict(row['minion_copy_material'])
        from .spell_target_groups import selection_from_dict as spell_group_from_dict
        row['spell_target_group'] = spell_group_from_dict(row['spell_target_group'])
        from .spell_group_targets import receipt_from_dict as actual_spell_targets_from_dict
        row['spell_target_receipt'] = actual_spell_targets_from_dict(row['spell_target_receipt'])
        row['next_spell_bonus_effects']=tuple(player_effect_from_dict(e)for e in _list(row['next_spell_bonus_effects'],'reserved paired next-spell effects'))
        row['copy_origin'] = _copy_origin_from_dict(row['copy_origin'])
        if row['body_targets'] is not None:
            from .paid_body_retries import receipt_from_dict
            row['body_targets'] = receipt_from_dict(row['body_targets'])
        row['played_face'] = _played_face_from_dict(row['played_face'])
        from .model import PaidHandClose, PaidHandInterruption
        if row['paid_hand_close'] is not None:
            row['paid_hand_close'] = PaidHandClose(**_row(row['paid_hand_close'], PaidHandClose))
        if row['paid_hand_interrupt'] is not None:
            row['paid_hand_interrupt'] = PaidHandInterruption(**_row(row['paid_hand_interrupt'], PaidHandInterruption))
        if row['submitted_cost'] is not None:
            row['submitted_cost'] = _hand_play_cost_from_dict(row['submitted_cost'])
        if row['spell_submission'] is not None:
            row['spell_submission'] = _spell_submission_from_dict(row['spell_submission'])
        if row['spell_payload'] is not None:
            row['spell_payload'] = _spell_payload_from_dict(row['spell_payload'])
        row['card_spell_repeats']=tuple(_ability_from_dict(a) for a in _list(row['card_spell_repeats'],'card spell repeats'))
        row['after_play']=tuple(_ability_from_dict(a) for a in _list(row['after_play'],'after-play attachments'))
        row['combos']=tuple(ComboPayload(**_row(b,ComboPayload)) for b in _list(row['combos'],'played Combo declarations'))
        if row['combo_acceptance'] is not None:
            row['combo_acceptance']=_combo_acceptance_from_dict(row['combo_acceptance'])
        row['battlecries']=tuple(BattlecryPayload(**_row(b,BattlecryPayload))
            for b in _list(row['battlecries'],'played Battlecry declarations'))
        if row['battlecry_acceptance'] is not None:
            accepted = _row(row['battlecry_acceptance'], BattlecryAcceptanceReceipt)
            accepted['payloads'] = tuple(BattlecryPayload(**_row(b, BattlecryPayload))
                for b in _list(accepted['payloads'], 'accepted Battlecry declarations'))
            if accepted['plan'] is not None: accepted['plan'] = _battlecry_plan(accepted['plan'])
            recipient = _row(accepted['recipient'], BattlecryRecipient)
            recipient['kind'] = CardType(recipient['kind'])
            accepted['recipient'] = BattlecryRecipient(**recipient)
            row['battlecry_acceptance'] = BattlecryAcceptanceReceipt(**accepted)
        row['corrupt_candidates'] = tuple(HandProgressCandidate(**_row(c, HandProgressCandidate))
            for c in _list(row['corrupt_candidates'], 'Corrupt candidates'))
        derivatives = []
        for entry in _list(row['hand_derivatives'], 'hand derivatives'):
            spec = _row(entry, HandDerivativeSpec)
            spec['keyword'] = Keyword(spec['keyword'])
            derivatives.append(HandDerivativeSpec(**spec))
        row['hand_derivatives'] = tuple(derivatives)
        row['kind']=CardType(row['kind']);row['payment']=PaymentType(row['payment'])
        row['held_higher_cost'] = _held_higher_cost_from_dict(row['held_higher_cost'])
        if row['held_mana'] is not None:
            from .model import HeldManaProgress
            fact=_row(row['held_mana'],HeldManaProgress)
            fact['spec']=_hand_progress_spec(fact['spec'])
            for key in ('keys','units'):fact[key]=tuple(_list(fact[key],'held mana '+key))
            row['held_mana']=HeldManaProgress(**fact)
        if row['held_spells'] is not None:
            from .model import HeldSpellProgress,HandProgressSpec
            fact=_row(row['held_spells'],HeldSpellProgress)
            fact['spec'] = _hand_progress_spec(fact['spec'])
            fact['cast_ids']=tuple(_list(fact['cast_ids'],'held-spell witnesses'))
            row['held_spells']=HeldSpellProgress(**fact)
        from .model import HandNeighborFact
        row['hand_neighbors']=None if row['hand_neighbors'] is None else tuple(HandNeighborFact(**_row(x,HandNeighborFact))
            for x in _list(row['hand_neighbors'],'original submitted hand neighbors'))
        row['hand_cost_rank'] = _hand_cost_rank_from_dict(row['hand_cost_rank'])
        plays.append(PlayRecord(**row))
    value['play_history']=plays
    value['cost_use_history'] = [_cost_use_from_dict(row) for row in _list(value['cost_use_history'], 'cost use history')]
    value['cast_history'] = [_spell_cast_from_dict(item)
        for item in _list(value['cast_history'], 'spell cast history')]
    from .model import HeroPowerRecord, HeroPowerPayloadBatch, HeroPowerPayloadCapture, HeroPowerPayloadRecord
    powers=[]
    for item in _list(value['hero_power_history'], 'hero power history'):
        row=_row(item,HeroPowerRecord)
        from .native_target_acceptance import selection_from_dict as native_selection_from_dict
        row['native_target']=native_selection_from_dict(row['native_target'])
        row['payloads']=tuple(_ability_from_dict(a) for a in _list(row['payloads'],'accepted hero power payloads'))
        row['repeat_plan']=_hero_power_repeat_plan(row['repeat_plan'])
        from .hero_power_values import plan_from_dict as power_value_plan_from_dict
        row['value_plan'] = power_value_plan_from_dict(row['value_plan'])
        row['payment']=PaymentType(row['payment']) if row['payment'] is not None else None
        powers.append(HeroPowerRecord(**row))
    value['hero_power_history']=powers
    batches=[]
    for item in _list(value['hero_power_payload_batches'],'hero power payload batches'):
        row=_row(item,HeroPowerPayloadBatch)
        row['payloads']=tuple(_ability_from_dict(a) for a in _list(row['payloads'],'hero power batch payloads'))
        row['plan']=_hero_power_repeat_plan(row['plan'])
        batches.append(HeroPowerPayloadBatch(**row))
    value['hero_power_payload_batches']=batches
    payload_records=[]
    for item in _list(value['hero_power_payload_history'],'hero power payload history'):
        row=_row(item,HeroPowerPayloadRecord)
        capture=_row(row['capture'],HeroPowerPayloadCapture)
        capture['ability']=_ability_from_dict(capture['ability'])
        row['capture']=HeroPowerPayloadCapture(**capture)
        payload_records.append(HeroPowerPayloadRecord(**row))
    value['hero_power_payload_history']=payload_records
    value['end_turn_batches'] = [_end_turn_batch_from_dict(item)
        for item in _list(value['end_turn_batches'], 'end-turn batches')]
    value['end_turn_history'] = [_end_turn_record_from_dict(item)
        for item in _list(value['end_turn_history'], 'end-turn history')]
    from .model import BattlecryPayload, BattlecryRecord, BattlecryBatchRecord
    batches=[]
    for item in _list(value['battlecry_batches'], 'Battlecry batches'):
        row=_row(item,BattlecryBatchRecord)
        row['payloads']=tuple(BattlecryPayload(**_row(b,BattlecryPayload)) for b in _list(row['payloads'],'Battlecry payloads'))
        row['plan']=_battlecry_plan(row['plan'])
        batches.append(BattlecryBatchRecord(**row))
    value['battlecry_batches']=batches
    batches=[]
    for item in _list(value['combo_batches'], 'Combo batches'):
        row=_row(item,ComboBatchRecord)
        row['payloads']=tuple(ComboPayload(**_row(b,ComboPayload)) for b in _list(row['payloads'],'Combo payloads'))
        row['plan']=_combo_plan(row['plan'])
        batches.append(ComboBatchRecord(**row))
    value['combo_batches']=batches
    battlecries=[]
    for item in _list(value['battlecry_history'], 'Battlecry history'):
        row=_row(item,BattlecryRecord)
        from .native_target_acceptance import selection_from_dict as native_selection_from_dict
        row['native_target']=native_selection_from_dict(row['native_target'])
        row['held_opponent_copy'] = _held_opponent_copy_match_from_dict(row['held_opponent_copy'])
        row['payload']=BattlecryPayload(**_row(row['payload'],BattlecryPayload))
        battlecries.append(BattlecryRecord(**row))
    value['battlecry_history']=battlecries
    from .indirect_body_targets import sequence_from_dict
    value['indirect_body_sequences']=[sequence_from_dict(row) for row in _list(
        value['indirect_body_sequences'],'indirect body sequences')]
    from .historical_body_targets import receipt_from_dict as historical_receipt_from_dict
    value['historical_body_invocations']=[historical_receipt_from_dict(row) for row in _list(
        value['historical_body_invocations'],'historical body invocations')]
    combos=[]
    for item in _list(value['combo_history'],'Combo history'):
        row=_row(item,ComboRecord)
        from .native_target_acceptance import selection_from_dict as native_selection_from_dict
        row['native_target']=native_selection_from_dict(row['native_target'])
        row['payload']=ComboPayload(**_row(row['payload'],ComboPayload))
        combos.append(ComboRecord(**row))
    value['combo_history']=combos
    from .model import DeathrattleCapture, DeathrattleRecord
    deathrattles=[]
    for item in _list(value['deathrattle_history'],'Deathrattle history'):
        row=_row(item,DeathrattleRecord);capture=_row(row['capture'],DeathrattleCapture)
        capture['ability']=_ability_from_dict(capture['ability']);capture['kind']=CardType(capture['kind'])
        if capture['historical_root'] is not None:
            root=capture['historical_root']
            root['data']=dict(root['data'])
            capture['historical_root']=event_from_dict(root)
        row['capture']=DeathrattleCapture(**capture);deathrattles.append(DeathrattleRecord(**row))
    value['deathrattle_history']=deathrattles
    from .model import DeathrattleBatch,DeathrattlePayloadPlan
    batches=[]
    for item in _list(value['deathrattle_batches'],'Deathrattle batches'):
        row=_row(item,DeathrattleBatch);payloads=[]
        for item in _list(row['payloads'],'Deathrattle payload plans'):
            payload=_row(item,DeathrattlePayloadPlan)
            payload['ability']=_ability_from_dict(payload['ability'])
            payload['plan']=_deathrattle_repeat_plan(payload['plan'])
            payloads.append(DeathrattlePayloadPlan(**payload))
        row['payloads']=tuple(payloads);batches.append(DeathrattleBatch(**row))
    value['deathrattle_batches']=batches
    from .model import ComboPolicyReceipt
    receipts=[]
    for item in _list(value['combo_policy_receipts'],'Combo policy receipts'):
        row=_row(item,ComboPolicyReceipt)
        row['recipient']=_combo_recipient_from_dict(row['recipient'])
        row['modifiers']=tuple(_combo_modifier_from_dict(m) for m in _list(row['modifiers'],'captured Combo modifiers'))
        receipts.append(ComboPolicyReceipt(**row))
    value['combo_policy_receipts']=receipts
    from .battlecry_policy_uses import receipt_from_dict as battlecry_use_from_dict
    value['battlecry_policy_uses'] = [battlecry_use_from_dict(row) for row in _list(value['battlecry_policy_uses'], 'Battlecry policy uses')]
    from .model import SpellPolicyReceipt
    receipts=[]
    for item in _list(value['spell_policy_receipts'],'spell policy receipts'):
        row=_row(item,SpellPolicyReceipt)
        row['hero_class']=CardClass(row['hero_class']) if row['hero_class'] is not None else None
        row['modifiers']=tuple(_spell_modifier_from_dict(m) for m in _list(row['modifiers'],'captured spell modifiers'))
        receipts.append(SpellPolicyReceipt(**row))
    value['spell_policy_receipts']=receipts
    value['draw_history'] = [_draw_from_dict(item) for item in _list(value['draw_history'], 'draw history')]
    from .model import SpellRepeatRecord, SpellChoiceMemo
    repeats = []
    for item in _list(value['spell_repeats'], 'spell repeats'):
        row = _row(item, SpellRepeatRecord)
        row['behavior_ids'] = tuple(_list(row['behavior_ids'], 'repeat behaviors'))
        memos = []
        for memo in _list(row['choices'], 'repeat choices'):
            memo = _row(memo, SpellChoiceMemo)
            memo['selected_ids'] = tuple(_list(memo['selected_ids'], 'repeat selected IDs'))
            memos.append(SpellChoiceMemo(**memo))
        row['choices'] = tuple(memos)
        repeats.append(SpellRepeatRecord(**row))
    value['spell_repeats'] = repeats
    from .model import RewindOutcomeRecord
    outcomes = []
    for item in _list(value['rewind_outcomes'], 'Rewind outcomes'):
        row = _row(item, RewindOutcomeRecord)
        row['combos']=tuple(ComboPayload(**_row(b,ComboPayload)) for b in _list(row['combos'],'retained Combos'))
        row['battlecry_plan'] = _battlecry_plan(row['battlecry_plan']) if row['battlecry_plan'] is not None else None
        row['combo_plan'] = _combo_plan(row['combo_plan']) if row['combo_plan'] is not None else None
        row['battlecries'] = tuple(BattlecryPayload(**_row(b,BattlecryPayload)) for b in _list(row['battlecries'],'retained Battlecries'))
        for key in ('behavior_ids', 'contributors'):
            row[key] = tuple(_list(row[key], 'retained outcome '+key))
        outcomes.append(RewindOutcomeRecord(**row))
    value['rewind_outcomes'] = outcomes
    entries=[]
    for item in _list(value['hand_entries'], 'hand acquisitions'):
        row=_row(item, HandEntryRecord)
        if row['from_zone'] is not None:
            row['from_zone']=Zone(row['from_zone'])
        entries.append(HandEntryRecord(**row))
    value['hand_entries']=entries
    magnets=[]
    for item in _list(value['magnetic_history'],'magnetic history'):
        row=_row(item,MagneticRecord)
        if row['source_material'] is not None:
            from .copy_materials import CapturedCardCopyMaterial, from_dict as copy_material_from_dict
            row['source_material']=copy_material_from_dict(CapturedCardCopyMaterial,row['source_material'])
        row['ability_ids']=tuple(_list(row['ability_ids'],'magnetic abilities'))
        row['host_tribe_changes']=tuple(_enchantment_from_dict(c) for c in _list(row['host_tribe_changes'],'original magnetic host tribe changes'))
        magnets.append(MagneticRecord(**row))
    value['magnetic_history']=magnets
    colossals=[]
    for item in _list(value['colossal_history'],'colossal history'):
        row=_row(item,ColossalRecord)
        row['limbs']=tuple(_list(row['limbs'],'appendage entities'))
        colossals.append(ColossalRecord(**row))
    value['colossal_history']=colossals
    heralds=[]
    for item in _list(value['herald_history'], 'Herald history'):
        row=_row(item, HeraldRecord)
        row['hero_class']=CardClass(row['hero_class'])
        heralds.append(HeraldRecord(**row))
    value['herald_history']=heralds
    from .model import ExcavationRecord
    excavations=[]
    for item in _list(value['excavation_history'], 'Excavation history'):
        row=_row(item,ExcavationRecord)
        row['hero_class']=CardClass(row['hero_class'])
        excavations.append(ExcavationRecord(**row))
    value['excavation_history']=excavations
    from .model import ImbueRecord
    imbues=[]
    for item in _list(value['imbue_history'], 'Imbue history'):
        row=_row(item,ImbueRecord)
        row['hero_class']=CardClass(row['hero_class'])
        imbues.append(ImbueRecord(**row))
    value['imbue_history']=imbues
    from .model import InvokeRecord, GalakrondMain
    invokes = []
    for item in _list(value['invoke_history'], 'Invoke history'):
        row = _row(item, InvokeRecord)
        row['hero_class'] = CardClass(row['hero_class']) if row['hero_class'] is not None else None
        row['main_zone'] = Zone(row['main_zone']) if row['main_zone'] is not None else None
        invokes.append(InvokeRecord(**row))
    value['invoke_history'] = invokes
    from .model import JadeGolemRecord
    value['jade_history'] = [JadeGolemRecord(**_row(item, JadeGolemRecord))
                             for item in _list(value['jade_history'], 'Jade history')]
    from .model import CthunGrowthRecord
    value['cthun_history'] = [CthunGrowthRecord(**_row(item, CthunGrowthRecord))
                              for item in _list(value['cthun_history'], 'Cthun history')]
    from .minion_families import FamilyReplacementRecord, from_dict as family_from_dict
    value['minion_family_history'] = [family_from_dict(FamilyReplacementRecord, item)
        for item in _list(value['minion_family_history'], 'Minion family history')]
    mains = value['galakrond_mains']
    if type(mains) is not dict or set(mains) != {'1', '2'}:
        raise ValueError('Main Galakronds require the two canonical player keys')
    bindings = {}
    for key, item in mains.items():
        if item is None:
            bindings[int(key)] = None
        else:
            row = _row(item, GalakrondMain)
            row['hero_class'] = CardClass(row['hero_class'])
            bindings[int(key)] = GalakrondMain(**row)
    value['galakrond_mains'] = bindings
    windows=[]
    for item in _list(value['action_windows'], 'action windows'):
        row=_row(item,ActionWindow)
        for name in ('attack_source_presence', 'attack_target_presence'):
            if row[name] is not None:
                from .model import BoardPresenceReference
                row[name] = BoardPresenceReference(**_row(row[name], BoardPresenceReference))
        row['spellburst_candidates']=tuple(TriggerCandidate(**_row(c,TriggerCandidate))
            for c in _list(row['spellburst_candidates'],'Spellburst candidates'))
        windows.append(ActionWindow(**row))
    value['action_windows']=windows
    launches = []
    for item in _list(value['starship_history'], 'starship_history'):
        row = _row(item, StarshipLaunchRecord)
        row['components'] = tuple(_list(row['components'], 'launch components'))
        launches.append(StarshipLaunchRecord(**row))
    value['starship_history'] = launches
    if value['pending_choice'] is not None:
        value['pending_choice'] = choice_from_dict(value['pending_choice'])
    if value['opening'] is not None:
        opening = _row(value['opening'], OpeningState)
        from .opening_deck_copies import from_dict as opening_copy_from_dict
        opening['deck_copies']=tuple(opening_copy_from_dict(row)for row in _list(opening['deck_copies'],'opening deck copies'))
        for field in ('offered', 'selected', 'original_entities'):
            opening[field] = tuple(tuple(_list(group, field)) for group in _list(opening[field], field))
        opening['completed'] = tuple(_list(opening['completed'], 'completed'))
        if opening['starting_hands'] is not None:
            opening['starting_hands'] = tuple(tuple(StartingHandCard(**_row(card, StartingHandCard))
                for card in _list(group, 'starting hand')) for group in _list(opening['starting_hands'], 'starting hands'))
        value['opening'] = OpeningState(**opening)
    from .choose_policies import receipt_from_dict as choose_receipt_from_dict
    from .interactables import InteractableUseRecord
    from .zones import CardReference
    interactable_uses = []
    for item in _list(value['interactable_history'], 'interactable history'):
        row = _row(item, InteractableUseRecord)
        invested = _row(row['invested'], CardReference)
        invested['zone'] = Zone(invested['zone'])
        row['invested'] = CardReference(**invested)
        interactable_uses.append(InteractableUseRecord(**row))
    value['interactable_history'] = interactable_uses
    value['choose_policy_receipts'] = [choose_receipt_from_dict(v) for v in _list(value['choose_policy_receipts'], 'Choose policy history')]
    parsed_players = {}
    for key, row in players.items():
        player_id = _canonical_id(key, 'player')
        row = _row(row, PlayerState)
        if row['hero_class'] is not None:
            row['hero_class'] = CardClass(row['hero_class'])
        if row['deck_class'] is not None:
            row['deck_class'] = CardClass(row['deck_class'])
        if row['runes'] is not None:
            row['runes'] = Runes(**_row(row['runes'], Runes))
        row['original_deck'] = tuple(_list(row['original_deck'], 'original_deck'))
        from .sideboards import SideboardState
        bands = []
        for item in _list(row['sideboards'], 'player sideboards'):
            band = _row(item, SideboardState)
            band['cards'] = tuple(_list(band['cards'], 'sideboard cards'))
            band['taken_slots'] = tuple(_list(band['taken_slots'], 'sideboard taken slots'))
            bands.append(SideboardState(**band))
        row['sideboards'] = tuple(bands)
        from .void_decks import VoidCard
        row['void_cards'] = tuple(VoidCard(**_row(v, VoidCard)) for v in _list(row['void_cards'], 'void cards'))
        for name in ('id', 'hero_id'):
            _integer(row[name], f'player {name}', 1)
        for name in ('weapon_id', 'hero_power_id'):
            _optional_id(row[name], name)
        for name in ('max_mana', 'mana', 'fatigue', 'hero_power_uses_this_turn', 'mana_cap',
                     'mana_spent', 'temporary_mana', 'overload_owed', 'overload_locked'):
            _integer(row[name], f'player {name}', 0)
        if row['hand_cap'] is not None:
            _integer(row['hand_cap'], 'player hand capacity', 1)
        if not isinstance(row['resources'], dict) or set(row['resources']) != {k.value for k in Resource}:
            raise ValueError('Unknown or missing resource account')
        row['resources'] = {Resource(k): _integer(v, 'resource amount', 0) for k, v in row['resources'].items()}
        row['battlecry_modifiers'] = [_battlecry_modifier_from_dict(m) for m in _list(row['battlecry_modifiers'],'Battlecry modifiers')]
        row['combo_modifiers'] = [_combo_modifier_from_dict(m) for m in _list(row['combo_modifiers'],'Combo modifiers')]
        row['spell_modifiers'] = [_spell_modifier_from_dict(m) for m in _list(row['spell_modifiers'],'spell modifiers')]
        from .choose_policies import modifier_from_dict as choose_modifier_from_dict
        row['choose_both_modifiers'] = [choose_modifier_from_dict(m) for m in _list(row['choose_both_modifiers'], 'Choose Both policies')]
        row['cost_modifiers'] = [_cost_modifier_from_dict(m) for m in _list(row['cost_modifiers'], 'cost_modifiers')]
        row['player_effects'] = [player_effect_from_dict(e)
                                 for e in _list(row['player_effects'], 'player_effects')]
        for name in ('deck', 'hand', 'board', 'graveyard', 'setaside', 'pending_plays', 'quests', 'secrets', 'additional_hero_power_ids'):
            for entity_id in _list(row[name], f'player {name}'):
                _integer(entity_id, f'player {name} entity ID', 1)
        parsed_players[player_id] = PlayerState(**row)
    parsed_entities = {}
    for key, row in entities.items():
        entity_id = _canonical_id(key, 'entity')
        parsed_entities[entity_id] = entity_from_dict(row)
    return GameState(players=parsed_players, entities=parsed_entities, **value)


def rng_to_json(state):
    return [rng_to_json(v) for v in state] if isinstance(state, tuple) else state


def rng_from_json(state):
    return tuple(rng_from_json(v) for v in state) if isinstance(state, list) else state


def end_turn_rng_to_json(state):
    """Only a producer RNG receipt accepts its standard finite Gaussian cache."""
    from .model import validate_end_turn_rng
    validate_end_turn_rng(state)
    return rng_to_json(state)


def end_turn_rng_from_json(value):
    from .model import validate_end_turn_rng
    # MT19937 has a fixed, shallow shape. Do not recursively normalize an
    # arbitrary nested JSON value before rejecting a malformed receipt.
    if (type(value) is not list or len(value) != 3 or
            type(value[1]) is not list or len(value[1]) != 625):
        raise ValueError('End-turn RNG state requires its complete standard array')
    state = (value[0], tuple(value[1]), value[2])
    validate_end_turn_rng(state)
    return state


def _held_opponent_copy_match_from_dict(value):
    from .model import HeldOpponentCopyMatch
    if value is None: return None
    row = _row(value, HeldOpponentCopyMatch)
    row['play_ids'] = tuple(_list(row['play_ids'], 'original held copied-play witnesses'))
    return HeldOpponentCopyMatch(**row)


def _copy_origin_from_dict(value):
    from .model import CardCopyOrigin
    return None if value is None else CardCopyOrigin(**_row(value, CardCopyOrigin))


def entity_from_dict(row):
    row = _row(row, Entity)
    from .location_rune_locks import from_dict as location_lock_from_dict
    row['location_lock'] = location_lock_from_dict(row['location_lock'])
    from .spell_mana_freeze import from_dict as spell_mana_freeze_from_dict
    row['spell_mana_freeze'] = spell_mana_freeze_from_dict(row['spell_mana_freeze'])
    row['copy_origin'] = _copy_origin_from_dict(row['copy_origin'])
    if row['choose_branch'] is not None:
        from .choose_branch_state import selection_from_dict
        row['choose_branch'] = selection_from_dict(row['choose_branch'])
    if row['death_cause'] is not None:
        row['death_cause'] = _death_cause_from_dict(row['death_cause'])
    _string(row['card_id'], 'card_id')
    for name in ('id', 'owner', 'controller'):
        _integer(row[name], f'entity {name}', 1)
    for name in ('base_attack', 'base_health', 'base_cost', 'damage', 'armor',
                 'attacks_this_turn', 'summoned_turn', 'entered_order'):
        _integer(row[name], f'entity {name}', 0)
    for name in ('attack_bonus', 'health_bonus', 'cost_modifier', 'aura_attack'):
        _integer(row[name], f'entity {name}')
    for name in ('silenced', 'doomed', 'starship_building', 'interactable_object','old_god_free_used','face_replaced'):
        _boolean(row[name], f'entity {name}')
    if row['hand_lifetime'] is not None:
        row['hand_lifetime'] = HandLifetime(**_row(row['hand_lifetime'], HandLifetime))
    if row['preparation'] is not None:
        row['preparation'] = HandPreparation(**_row(row['preparation'], HandPreparation))
    _optional_id(row['origin_entity_id'], 'origin_entity_id')
    _optional_id(row['frozen_until_owner_turn'], 'frozen_until_owner_turn')
    _integer(row['aura_health'], 'aura_health', 0)
    _integer(row['durability'], 'durability')
    _integer(row['weapon_attack'], 'weapon_attack', 0)
    _integer(row['conditional_attack'], 'conditional_attack', 0)
    _integer(row['conditional_health'], 'conditional_health', 0)
    _integer(row['uses_this_turn'], 'uses_this_turn', 0)
    _integer(row['use_limit'], 'use_limit', 1)
    _integer(row['corpse_value'], 'corpse_value', 0)
    _integer(row['location_cooldown'], 'location_cooldown', 0)
    if row['quest_progress'] is not None:
        progress = _row(row['quest_progress'], QuestProgress)
        progress['keys'] = tuple(_list(progress['keys'], 'quest keys'))
        progress['completed_before'] = tuple(_list(progress['completed_before'], 'quest original completed plays'))
        row['quest_progress'] = QuestProgress(**progress)
    if row['dormancy'] is not None:
        row['dormancy'] = DormancyState(**_row(row['dormancy'], DormancyState))
    row['kind'] = CardType(row['kind'])
    if not isinstance(row['zone'], str):
        raise ValueError('Entity zone must be a string')
    row['zone'] = Zone(row['zone'])
    row['components'] = tuple(_list(row['components'], 'components'))
    row['keywords'] = set(_keyword_list(row['keywords']))
    row['weapon_keywords'] = set(_keyword_list(row['weapon_keywords']))
    row['aura_keywords'] = set(_keyword_list(row['aura_keywords']))
    row['hand_aura_keywords'] = set(_keyword_list(row['hand_aura_keywords']))
    row['conditional_keywords'] = set(_keyword_list(row['conditional_keywords']))
    row['abilities'] = [_ability_from_dict(item) for item in _list(row['abilities'], 'entity abilities')]
    row['enchantments'] = [_enchantment_from_dict(item) for item in _list(row['enchantments'], 'entity enchantments')]
    return Entity(**row)


def entity_to_dict(entity):
    row = asdict(entity)
    row['zone'] = entity.zone.value
    row['keywords'] = sorted(keyword.value for keyword in entity.keywords)
    row['weapon_keywords'] = sorted(keyword.value for keyword in entity.weapon_keywords)
    row['aura_keywords'] = sorted(keyword.value for keyword in entity.aura_keywords)
    row['hand_aura_keywords'] = sorted(keyword.value for keyword in entity.hand_aura_keywords)
    row['conditional_keywords'] = sorted(keyword.value for keyword in entity.conditional_keywords)
    return json.loads(json.dumps(row, ensure_ascii=False, allow_nan=False))
