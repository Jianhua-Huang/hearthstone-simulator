"""Native Paladin Aura and a real controlled-Aura Battlecry consumer."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage, DamageBatch
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, PlayerEffectSpec, SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-paladin-aura-v1.json'
BATCH_HASH = '58a224367bfaf9ce6f1bbd73cefafed19701e11a522701a659a031501767e486'
RESISTANCE = 'TTN_851'
TIMEWAYS = 'TIME_019'
SPEC = 'cards.native_paladin_aura.resistance'
BODY = 'cards.native_paladin_aura.timeways'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) !=
            (RESISTANCE, TIMEWAYS) or any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Native Aura requires its complete reviewed recipes')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native Aura original source row changed')
    return data


def register_native_paladin_aura_cards(registry):
    rows = load_batch()['cards']
    raw = rows[0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('PALADIN_AURA'), raw['tags'].get('OBJECTIVE_AURA'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'), raw['tags'].get('QUEST_PROGRESS_TOTAL')) != ('SPELL', 2, 1, 1, 2, 2):
        raise TargetValidationError('Resistance Aura lost its explicit native two-enemy-turn source')
    registry.register_player_effect(PlayerEffectSpec(SPEC, RESISTANCE, kind='aura', duration=2,
        tick_event='turn_ended', tick_player='opponent', opponent_spell_cost=1))
    card = CardDefinition(RESISTANCE, raw['name'], CardType.SPELL, cost=2, metadata=metadata_from_record(raw),
        spell_school=SpellSchool.HOLY, ongoing_effect_id=SPEC)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    def timeways(c):
        if not any(registry.player_effect(e.spec_id).kind == 'aura' for e in c.state.players[c.player_id].player_effects):
            return ()
        other = 3-c.player_id
        targets = (c.state.players[other].hero_id, *minions(c, registry, other))
        return (DamageBatch(tuple(Damage(eid, 3, c.source_id, DamageKind.MINION_ABILITY) for eid in targets)),)
    registry.register_behavior(BODY, timeways)
    raw = rows[1]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CARDRACE'),
            raw['tags'].get('BATTLECRY'), raw['tags'].get('CLASS')) != ('MINION', 4, 3, 3, 18, 1, 5):
        raise TargetValidationError('Manifested Timeways lost its complete Paladin Elemental Battlecry')
    card = CardDefinition(TIMEWAYS, raw['name'], CardType.MINION, cost=4, attack=3, health=3,
        metadata=metadata_from_record(raw), battlecry=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
