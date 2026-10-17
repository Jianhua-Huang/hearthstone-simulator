"""Current Jaraxxus hero and exact physical variants of reviewed P50 children."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import EquipWeapon
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p51-v1.json'
BATCH_HASH = '1128cb97347addaf3b641034b92a1a6b6c55a6d952431c6ccc8b252963d9c11a'
HERO = 'CORE_EX1_323'
WEAPON = 'EX1_323w'
POWER = 'EX1_tk33'
INFERNAL = 'EX1_tk34'
BODY_FORMS = ('CATA_550t2', 'CATA_550t3', 'CATA_550t4', 'CATA_550t5', 'CATA_550t6')
PLUME = 'CATA_488t'
BLOOD_FORMS = ('CATA_300t2', 'CATA_300t3')
RECIPES = {**dict.fromkeys(BODY_FORMS, 'CATA_550t'), PLUME: 'CATA_488t2',
           **dict.fromkeys(BLOOD_FORMS, 'CATA_300t1')}
ROOTS = (HERO, WEAPON, *BODY_FORMS, PLUME, *BLOOD_FORMS)
EXISTING = (POWER, INFERNAL, 'CATA_550t', 'CATA_488t2', 'CATA_300t1')
PARENTS = ('CATA_550', 'CATA_488', 'CATA_300')
BATTLECRY = 'cards.simple_followup_p51.jaraxxus'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != EXISTING or
            tuple(x['record']['id'] for x in data['evidence_only']) != PARENTS or
            data['dependencies'] or data['skipped']):
        raise TargetValidationError('P51 complete reviewed hero and physical forms changed')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P51 complete original source row changed')
    return data


def register_simple_followup_p51_cards(registry):
    data = load_batch()
    for cid, pin in data['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P51 accepted native dependency changed: ' + cid)
    rows = {x['record']['id']: x['record'] for x in data['cards'] + data['existing_dependencies']}
    registry.register_behavior(BATTLECRY, lambda c: (EquipWeapon(c.player_id, WEAPON),))
    for cid in ROOTS:
        raw = rows[cid]
        if cid in RECIPES:
            original = rows[RECIPES[cid]]
            # These are full identical printed records, apart from physical identity.
            if ({k: v for k, v in raw.items() if k not in ('id', 'dbf_id')} !=
                    {k: v for k, v in original.items() if k not in ('id', 'dbf_id')}):
                raise TargetValidationError('P51 form differs from its complete accepted recipe')
            card = replace(registry.card(RECIPES[cid]), id=cid, name=raw['name'],
                           metadata=metadata_from_record(raw))
        elif cid == HERO:
            card = CardDefinition(cid, raw['name'], CardType.HERO, cost=raw['cost'],
                health=raw['health'], metadata=metadata_from_record(raw), hero_card=True,
                hero_armor=raw['tags']['ARMOR'], initial_hero_power=POWER, battlecry=BATTLECRY)
        else:
            card = CardDefinition(cid, raw['name'], CardType.WEAPON, cost=raw['cost'],
                attack=raw['attack'], durability=raw['health'], metadata=metadata_from_record(raw))
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
