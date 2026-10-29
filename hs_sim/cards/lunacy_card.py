"""Deck of Lunacy composes frozen original deck requests and stored transforms."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.costs import local_cost
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
CARD='DMF_108'
BODY='cards.lunacy.transform'
BATCH_PATH=ROOT/'data/cards/lunacy-card-v1.json'
BATCH_HASH='ca574796e002560d83111fd5ec677a154ac2d1ee95cc497aa8feb2fd60cf9e18'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=(*data['cards'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            [v['record']['id']for v in rows]!=[CARD,CARD+'e']or len(data['official_observations'])!=2 or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in rows)or
            any(data[k]for k in ('dependencies','new_standard_roots','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Lunacy requires complete original spell, enchant evidence and primary faces')
    ref=ROOT/data['reference_document'];raw=rows[0]['record']
    if ((raw['type'],raw['cost'],raw['tags'].get('RARITY'),raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,5,None)or
            hashlib.sha256(ref.read_bytes()).hexdigest()!=data['reference_sha256']or
            CARD not in json.loads(ref.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Lunacy lost its original face or past-Mage reference')
    return data


def register_lunacy_card(registry):
    raw=load_batch()['cards'][0]['record']
    def transform(c):
        if c.cast is None or c.cast.card_id!=CARD:
            raise UnsupportedDefinitionError('Lunacy requires its original actual spell CAST')
        requests=[]
        for identity in c.state.players[c.player_id].deck:
            entity=c.state.entities[identity]
            if entity.kind!=CardType.SPELL:continue
            cost=max(0,local_cost(entity)[0]);tier=min(10,cost+3)
            requests.append(TransformStoredFromPool(CardReference.capture(entity),'constructed.cards',
                PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=tier,max_cost=tier),
                c.source_id,retained_cost=cost))
        return tuple(requests)
    registry.register_behavior(BODY,transform)
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
