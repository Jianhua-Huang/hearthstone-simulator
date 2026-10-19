"""High King's Hammer dependency; Muradin's holding adapter remains explicit."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.growing_weapon_shuffles import ShuffleGrowingWeapon
from hs_sim.engine.model import CardDefinition,CardType,Keyword,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT='TIME_209';HAMMER='TIME_209t';AVATAR='TIME_209t2'
PREFIX='cards.muradin_fabled_hammer.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/muradin-fabled-hammer-v1.json'
BATCH_HASH='a4bd85134756c501850a9a507d37cf6a7a2d68110efcca00f6dc5ee315ae71ae'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or d['cards']or tuple(r['record']['id']for r in d['dependencies'])!=(HAMMER,)
            or tuple(r['record']['id']for r in d['existing_dependencies'])!=(AVATAR,)
            or tuple(r['record']['id']for r in d['source_roots'])!=(ROOT,)
            or tuple(r['record']['id']for r in d['evidence_only'])!=('TIME_209e','TIME_209t2e')):
        raise TargetValidationError('Muradin family complete dependency source changed')
    for section in('dependencies','existing_dependencies','source_roots','evidence_only'):
        for row in d[section]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Muradin original complete row changed')
    return d


def register_muradin_fabled_hammer_cards(registry):
    def shuffle(c):
        entity=c.state.entities.get(c.source_id)
        if entity is None or entity.kind!=CardType.WEAPON:raise ResolutionError('Hammer shuffle requires its actual physical weapon')
        death=c.death
        if death is None:raise ResolutionError('Hammer shuffle requires its actual original weapon death')
        if entity.zone!=Zone.GRAVEYARD or entity.zone_epoch!=death.cause.target_zone_epoch+1:return ()
        work=ShuffleGrowingWeapon(SourceAllocationFact.capture(c.state,entity),death,c.player_id,2,c.source_id)
        return (ShuffleDeckCards(c.player_id,c.player_id,(work,),c.source_id),)
    registry.register_behavior(PREFIX+'shuffle',shuffle)
    raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('WEAPON',6,3,4):raise TargetValidationError('Unexpected Hammer source face')
    card=CardDefinition(HAMMER,raw['name'],CardType.WEAPON,cost=6,attack=3,durability=4,keywords=(Keyword.WINDFURY,),
        deathrattle=PREFIX+'shuffle',metadata=replace(metadata_from_record(raw),deck_identity=HAMMER))
    registry.register_card(card)
    if HAMMER not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
