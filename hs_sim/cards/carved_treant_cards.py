"""Bashana's three real Treants carry original printed Nature spell text."""
import json
from pathlib import Path

from hs_sim.engine.carved_spells import CarvedSpellProfile,CreateCarvedTreants,CastCarvedSpell
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='MEND_046'
TREE='MEND_046t'
PREFIX='cards.bashana.'
POOL_ID='constructed.cards'
PROFILE=CarvedSpellProfile(TREE,CARD,SpellSchool.NATURE)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/carved-treant-v1.json'
BATCH_HASH='354328ab967324623583b01f99d5148a4c8b2fcde1e3d26a3abebfa975d1cd14'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in data['dependencies'])!=(TREE,) or
            any(data[k] for k in ('evidence_only','skipped'))):
        raise TargetValidationError('Bashana requires both complete native faces and all reviewed Nature sources')
    for row in (*data['cards'],*data['dependencies'],*data['existing_dependencies']):
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Carved source pin changed')
    for row,values in zip((*data['cards'],*data['dependencies']),((7,4,4,True),(1,2,2,False))):
        raw=row['record']
        if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags']['CLASS'],raw['tags']['BATTLECRY'])!=('MINION',*values,2,1):
            raise TargetValidationError('Original Druid creator or one-cost Treant changed')
    if any(x['record']['type']!='SPELL' or x['record']['tags'].get('SPELL_SCHOOL')!=4 for x in data['existing_dependencies']):
        raise TargetValidationError('Original Nature dependency lost its printed school')
    return data


def register_carved_treant_cards(registry):
    registry.register_behavior(PREFIX+'create',lambda c:(CreateCarvedTreants(c.player_id,TREE,POOL_ID,c.source_id),))
    def cast(c):
        if c.battlecry is None:raise ResolutionError('Carved spell requires its actual accepted native Battlecry')
        return (CastCarvedSpell(c.battlecry.id),)
    registry.register_behavior(PREFIX+'cast',cast)
    data=load_batch()
    for row in (*data['cards'],*data['dependencies']):
        raw=row['record'];cid=raw['id']
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            battlecry=PREFIX+('create' if cid==CARD else 'cast'),metadata=metadata_from_record(raw))
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_carved_spell_profile(PROFILE)
