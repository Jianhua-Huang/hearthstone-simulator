"""Ursol's real wrapper spell uses the shared stored-spell Aura program."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, PlayerEffectSpec, SpellSchool, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_auras import CastAuraSpell, CastHighestHandSpellAsAura
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_259'
AURA = 'EDR_259e1'
PREFIX = 'cards.ursol_spell_aura.'
PROGRAM = PREFIX+'program'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/ursol-spell-aura-v1.json'
BATCH_HASH = '2cd56a0428a3e2b89b0d02893f86926dfcef4d7e056f49b076a104b1b29d6d92'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            tuple(row['record']['id'] for row in data['dependencies']) != (AURA,) or
            data['existing_dependencies'] or data['evidence_only'] or data['skipped']):
        raise TargetValidationError('Ursol requires his complete original body and actual Aura spell')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Ursol source record')
    return data


def register_ursol_spell_aura_card(registry):
    data = load_batch()
    raw, aura = data['cards'][0]['record'], data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')) != ('MINION', 8, 9, 7, 1, 3):
        raise TargetValidationError('Ursol changed his actual printed body or Aura duration')
    if (aura['type'], aura['cost'], aura['tags'].get('PALADIN_AURA'),
            aura['tags'].get('TAG_SCRIPT_DATA_NUM_2')) != ('SPELL', 1, 1, 3):
        raise TargetValidationError('Ursol lost his real three-turn Aura spell wrapper')
    registry.register_behavior(PREFIX+'begin', lambda c:
        (CastHighestHandSpellAsAura(c.player_id, AURA, c.source_id),))
    registry.register_behavior(PREFIX+'cast', lambda c:
        (CastAuraSpell(c.player_id, c.player_effect),))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, AURA, kind='aura', duration=3,
        tick_event='turn_ended', stored_spell=True,
        triggers=(TriggerSpec('turn_ended', PREFIX+'cast', EndTurnSpec()),)))
    registry.register_card(CardDefinition(AURA, aura['name'], CardType.SPELL, cost=1,
        spell_school=SpellSchool.HOLY, metadata=metadata_from_record(aura), ongoing_effect_id=PROGRAM))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=8, attack=9, health=7,
        metadata=metadata_from_record(raw), battlecry=PREFIX+'begin')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
