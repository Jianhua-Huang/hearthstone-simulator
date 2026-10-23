"""Vilefin Inquisitor installs its real skill and ordinary Murloc token."""
import json
from pathlib import Path

from hs_sim.engine.effects import ReplaceHeroPower
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, TOKEN, POWER = 'OG_006', 'OG_006a', 'OG_006b'
LEAVES = (CARD,)
DEPENDENCIES = (CARD, TOKEN, POWER)
COLLECTIBLE_ROOTS = ()
EVIDENCE_ONLY = ('LOE_076', 'DRG_253', 'ETC_382', 'TRL_390')
PREFIX = 'cards.past_murloc_hero_power.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-murloc-hero-power-v1.json'
BATCH_HASH = '3e10312a0eb5653341c6023934ee3b57890b6ac094a7c771b8ca08057b9826c9'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['evidence_only']) != EVIDENCE_ONLY or
            any(data[k] for k in ('cards', 'existing_dependencies', 'choice_only', 'skipped',
                                 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['dependencies'] + data['evidence_only'])):
        raise TargetValidationError('Vilefin lost its complete original skill and token sources')
    return data


def register_past_murloc_hero_power_card(registry):
    registry.register_behavior(PREFIX+'replace', lambda c: (
        ReplaceHeroPower(c.player_id, POWER, source_id=c.source_id),))
    registry.register_behavior(PREFIX+'summon', lambda c: (
        SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), SummonCause.capture(c)),))
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']; fields = {}
        if cid == CARD:
            if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 1, 1, 3, 1):
                raise TargetValidationError('Vilefin lost its printed battlecry minion face')
            fields['battlecry'] = PREFIX+'replace'
        elif cid == POWER:
            if (raw['type'], raw['cost']) != ('HERO_POWER', 2):
                raise TargetValidationError('The linked physical Murloc skill changed its type or cost')
            fields.update(on_use=PREFIX+'summon', requires_board_space=True)
        elif (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 1, 1, 1):
            raise TargetValidationError('The linked ordinary Murloc token changed its printed body')
        kind = CardType(raw['type'].lower())
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
