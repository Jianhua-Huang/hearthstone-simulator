"""Rajh's source-bound assembly and materialized passive power template."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.assembled_powers import AssembledPowerProfile
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, POWER = 'BE_004', 'BE_004p'
POOL = 'constructed.assemble.rajh'
BODY = 'cards.rajh.assemble-passive'
FRAGMENTS = ('CORE_ICC_210', 'TIME_428')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/rajh-v1.json'
BATCH_HASH = 'a8ae9c45ea6e2ff889901907ace8a3c830e783f7db95d55f4d0778e57939ed48'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (POWER,) or
            tuple(data['reviewed_templates']) != FRAGMENTS or data['official_faces_verified'] != 10 or
            data['policy']['formal_pool_installed'] is not False or data['policy']['hand_intermediate'] is not False or
            data['policy']['secondary_cost_rule_confirmed'] is not False):
        raise TargetValidationError('Rajh requires complete source faces and its explicit open curated-domain policy')
    for section in ('cards', 'dependencies', 'existing_dependencies'):
        for row in data[section]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Rajh original complete record changed')
    return data


def register_rajh_card(registry):
    data = load_batch(); raw = data['cards'][0]['record']; power = data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 5, 4, 4):
        raise TargetValidationError('Rajh lost its actual five-cost 4/4 Battlecry')
    if power['type'] != 'HERO_POWER' or power['tags'].get('HIDE_COST') != 1 or power['text'] != '{0}':
        raise TargetValidationError('Rajh requires its actual material-dependent hidden-cost power template')
    for row in data['existing_dependencies']:
        cid = row['record']['id']; card = registry.card(cid)
        if canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Rajh fragment changed its complete original definition: '+cid)
        if cid in FRAGMENTS:
            trigger, = card.triggers
            registry.register_assemble_template(AssembleTemplate(cid,
                AssemblePrefix('end_turn', card.keywords, trigger.end_turn),
                AssembleSuffix(trigger.behavior_id, ('end_turn',))))
    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id != CARD:
            raise ResolutionError('Rajh requires its actual original Battlecry')
        return (Assemble(c.player_id, POOL, c.source_id, passive_power_template_id=POWER),)
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=5, attack=4, health=4,
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_assembled_power_profile(AssembledPowerProfile(
        POWER, CARD, POOL, power['name'], metadata_from_record(power),
        tuple(row['record']['id'] for row in data['existing_dependencies'])))
