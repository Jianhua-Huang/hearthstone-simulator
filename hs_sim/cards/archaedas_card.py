"""Real Archaedas and Hammer: original spell discovery and shared native CAST."""
import json
from pathlib import Path

from hs_sim.engine.carved_spells import CarvedSpellProfile
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import DiscoverFromPool,PoolCard
from hs_sim.engine.spell_weapons import QUERY,cast_after_attack
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD,WEAPON='BE_055','BE_055t'
BODY,CAST='cards.archaedas.discover','cards.archaedas.weapon-cast'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/archaedas-v1.json'
BATCH_HASH='01a33d9032b9043bd25d4ea4d30a2252e9738abe1f4b741b2ef2e63441fa8cc1'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in data['dependencies'])!=(WEAPON,)or
            any(data[k]for k in ('existing_dependencies','evidence_only','skipped'))or
            data['official_faces_verified']!=4 or data['parent_child_dbf_ids']!=[132338]or
            data['dependency_assignment_primary_confirmed']is not True):
        raise TargetValidationError('Archaedas requires both actual complete records and four full primary faces')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Archaedas complete original source changed')
    return data


def register_archaedas_card(registry):
    data=load_batch();root=data['cards'][0]['record'];weapon=data['dependencies'][0]['record']
    if ((root['type'],root['cost'],root['attack'],root['health'],root['tags'].get('BATTLECRY'))!=('MINION',4,4,3,1)or
            (weapon['type'],weapon['cost'],weapon['attack'],weapon['health'],weapon['dbf_id'])!=('WEAPON',1,3,3,132338)):
        raise TargetValidationError('Archaedas or the real Hammer template changed its full printed face')
    def body(c):
        if c.battlecry is None or c.battlecry.payload.card_id!=CARD:
            raise ResolutionError('Archaedas requires its actual original Battlecry')
        return (DiscoverFromPool(c.player_id,'constructed.cards',QUERY,source_id=c.source_id,
            spell_weapon_card_id=WEAPON),)
    registry.register_behavior(BODY,body)
    registry.register_behavior(CAST,lambda c:cast_after_attack(c,registry))
    definitions=(CardDefinition(CARD,root['name'],CardType.MINION,cost=4,attack=4,health=3,
            metadata=metadata_from_record(root),battlecry=BODY),
        CardDefinition(WEAPON,weapon['name'],CardType.WEAPON,cost=1,attack=3,durability=3,
            metadata=metadata_from_record(weapon),triggers=(TriggerSpec('attack_finished',CAST),)))
    for card in definitions:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_carved_spell_profile(CarvedSpellProfile(WEAPON,CARD,weapon_attack=True))
