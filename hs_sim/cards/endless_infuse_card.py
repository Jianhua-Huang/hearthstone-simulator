"""Sire Denathrius: real Infuse stages and ordinary split Lifesteal damage."""
import json
from pathlib import Path
from hs_sim.engine.infused_battlecries import InfusedBattlecryProfile
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, HandProgressSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, INFUSED, ORIGINAL = 'CORE_REV_906', 'REV_906t', 'REV_906'
PREFIX = 'cards.endless_infuse.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/endless-infuse-v1.json'
BATCH_HASH = '7d483894089ee2b213a55cf72963a8c1700b49de5419f1e3af40c28f07603a93'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            tuple(x['record']['id']for x in data['cards']) != (CARD,) or
            tuple(x['record']['id']for x in data['dependencies']) != (INFUSED,) or
            tuple(x['record']['id']for x in data['evidence_only']) != (ORIGINAL,) or
            len(data['official_faces']) != 4 or data['formal_pool_complete'] is not False or
            data['cn_calibrated'] is not False or any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards']+data['dependencies']+data['evidence_only'])):
        raise TargetValidationError('Endless Infuse lost its complete pinned native source')
    root, original = data['cards'][0]['record'], data['evidence_only'][0]['record']
    primary = [x['face']for x in data['official_faces']if x['card_id'] == ORIGINAL]
    if (any(root[k] != original[k]for k in ('name','text','text_en','cost','attack','health','type','collectible')) or
            any(root['dbf_id'] not in f.get('copyOfCardId', ()) or 77222 not in f.get('childIds', ())for f in primary)):
        raise TargetValidationError('Endless Infuse Core/primary/child association changed')
    return data


def register_endless_infuse_card(registry):
    data = load_batch()
    registry.register_behavior(PREFIX+'noop', lambda c: ())
    registry.register_behavior(PREFIX+'body', lambda c: (RandomSplitDamage(
        c.player_id, None, c.source_id, c.battlecry.payload.infused_damage,
        profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),))
    for item in data['cards']+data['dependencies']:
        raw = item['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Endless Infuse cannot overwrite an existing native identity')
        spec = HandProgressSpec('infuse', raw['tags']['TAG_SCRIPT_DATA_NUM_1'],
            upgrade_card_id=INFUSED if cid == CARD else None,
            on_complete=None if cid == CARD else PREFIX+'noop', repeat=cid == INFUSED)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), battlecry=PREFIX+'body',
            keywords=(Keyword.LIFESTEAL, Keyword.INFUSE), hand_progress=spec)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    for item in data['cards']+data['dependencies']:
        raw = item['record']
        registry.register_infused_battlecry_profile(InfusedBattlecryProfile(raw['id'],
            raw['tags']['TAG_SCRIPT_DATA_NUM_2'], raw['tags']['TAG_SCRIPT_DATA_NUM_1'],
            INFUSED if raw['id'] == CARD else None))
