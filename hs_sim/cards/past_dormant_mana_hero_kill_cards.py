"""Actual dormant spell costs and an original hero combat-kill consumer."""
import json
from pathlib import Path

from hs_sim.engine.dormancy import AwakenCapturedMinion
from hs_sim.engine.dormant_spell_mana import DormantSpellManaProfile, completed_mana
from hs_sim.engine.effects import Draw
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Keyword, TimedKeywordSpec, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .metadata import metadata_from_record

KELP, SPIRIT = 'TSC_657', 'TRL_223'
DEPENDENCIES = (KELP, SPIRIT)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_dormant_mana_hero_kill.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-dormant-mana-hero-kill-v1.json'
BATCH_HASH = '2779625fc7fd5b46882cbc353efa596cef0868eb9589e090421bcbac0354179f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            data['numeric_normalizations'] != {SPIRIT: {'attack': 0}} or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Dormant mana/hero kill lost their complete original sources')
    return data


def register_past_dormant_mana_hero_kill_cards(registry):
    def kelp(context):
        if completed_mana(context, registry) < registry.dormant_spell_mana_profiles[KELP].goal:
            return ()
        return (AwakenCapturedMinion(MinionReference.capture(context.source),
            context.source.dormancy.id, context.source_id),)

    def spirit(context):
        row = completed_attack(context)
        if (row is None or not living_source(context) or row.source_kind != CardType.HERO or
                row.combat.player_id != context.player_id):
            return ()
        target = context.state.entities[row.delivery.target_id]
        cause = target.death_cause
        if target.kind != CardType.MINION or cause is None or cause.kind not in ('damage', 'poison'):
            return ()
        result = cause.health_result
        if (result is None or result.damage_kind != DamageKind.COMBAT.value or
                result.source_id != row.declaration.source_id or result.original_target_id != row.delivery.target_id or
                (result.source_zone_epoch, result.source_entered_order) !=
                    (row.combat.source_zone_epoch, row.combat.source_entered_order) or
                not row.combat.event_cursor < result.batch_id <= row.terminal.event_cursor):
            return ()
        return (Draw(context.player_id, 1, context.source_id),)

    registry.register_behavior(PREFIX + KELP, kelp)
    registry.register_behavior(PREFIX + SPIRIT, spirit)
    for item in load_batch()['dependencies']:
        raw = item['record']; cid = raw['id']
        if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health']) != (
                'MINION', True, 1, 4 if cid == KELP else None, 4 if cid == KELP else 3):
            raise TargetValidationError('Dormant mana/hero kill changed their original printed body')
        if cid == KELP:
            if raw['tags'].get('RUSH') != 1:
                raise TargetValidationError('Kelpkeeper lost its printed Rush')
            fields = dict(keywords=(Keyword.RUSH,), dormant_turns=None,
                dormant_triggers=(TriggerSpec('spell_cast_finished', PREFIX + cid),))
        else:
            if raw['tags'].get('STEALTH') != 1:
                raise TargetValidationError('Raptor Spirit lost its printed Stealth')
            fields = dict(keywords=(Keyword.STEALTH,), timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),),
                triggers=(TriggerSpec('attack_finished', PREFIX + cid),))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1,
            attack=raw['attack'] if cid == KELP else 0, health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_dormant_spell_mana_profile(DormantSpellManaProfile(KELP))
