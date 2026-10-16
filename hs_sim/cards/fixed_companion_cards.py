"""Complete fixed companion family and real Halazzi hand refill."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import AuraSpec,CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import FillHandWithCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/fixed-companion-effects-v1.json'
BATCH_HASH='f2449788713574047bda45e1cb3aec96251998b0f59ad9c83e8d5c5474547aaf'
PREFIX='cards.fixed_companions.'
SCRIPTS={'CORE_NEW1_031':'random_companion','CORE_OG_211':'all_companions','CORE_TRL_900':'fill_lynx',
    'NEW1_034':'huffer','NEW1_033':'leokk','NEW1_032':'misha','TRL_348t':'lynx'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Fixed companion complete source pin changed')
    return value


def register_fixed_companion_cards(registry):
    batch=load_batch();order=tuple(batch['companion_order']);materials=tuple(SummonEntryMaterial(cid)for cid in order)
    if order!=('NEW1_034','NEW1_033','NEW1_032')or batch['lynx_card_id']!='TRL_348t':
        raise TargetValidationError('Fixed companion identities/order changed')
    bodies=dict(random_companion=lambda c:(SummonByCard(c.player_id,materials,SummonCause.capture(c),selection='random'),),
        all_companions=lambda c:tuple(SummonByCard(c.player_id,(material,),SummonCause.capture(c))for material in materials),
        fill_lynx=lambda c:(FillHandWithCard(c.player_id,batch['lynx_card_id'],c.source_id),))
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in batch['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Fixed companion identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script'];kind=CardType(raw['type'].lower())
        if(canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=script or
                raw['collectible']!=(recipe['role']=='root')):raise TargetValidationError('Unreviewed fixed companion face')
        kwargs={}
        if script in bodies:kwargs['on_play'if kind==CardType.SPELL else'battlecry']=PREFIX+script
        if script=='leokk':kwargs['auras']=(AuraSpec(attack=1),)
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,
            health=raw['health']if kind==CardType.MINION else 0,keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
