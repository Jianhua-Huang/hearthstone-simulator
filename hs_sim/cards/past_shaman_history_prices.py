"""Three real Shaman consumers of original accounts, casts and printed plays."""
from dataclasses import asdict
from functools import lru_cache
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,Keyword,
    PlayerOverloadCostSpec,PlayerSpellCountCostSpec,SpellSchool,TargetSpec,Zone)
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-history-prices-v1.json'
BATCH_HASH='5b33b66c033acf24916f403245d7dd67df06335136772616ffc53735fa232f17'
ROOTS=('ETC_356','SW_035','TTN_831')
DEPENDENCIES=()
PREFIX='cards.past_shaman_history_prices.'
CURRENT_OVERLOAD=PlayerOverloadCostSpec('cost.player-current-overload-discount-v1')
TURN_NATURE=PlayerSpellCountCostSpec('cost.player-turn-nature-cast-count-v1')
SOURCE=ROOT/'data/reference/card-integration-20261014/cards-37.0.0.255026.json'
SOURCE_HASH='3c7991d63b9905226320861844c2def8b839321294bd8b301a1c1632150083c2'


@lru_cache(maxsize=1)
def printed_overload_source():
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_HASH:
        raise TargetValidationError('Charged Call lost its full original classification source')
    rows=json.loads(raw.decode('utf-8-sig'))
    if type(rows)is dict:rows=rows['cards']
    if len(rows)!=23452 or len({row['id']for row in rows})!=len(rows):
        raise TargetValidationError('Charged Call requires the complete unique original card inventory')
    overload=tuple(row for row in rows if type(row['tags'].get('OVERLOAD'))is int and row['tags']['OVERLOAD']>0)
    return frozenset(row['id']for row in rows),overload


def make_definition(raw):
    cid=raw['id']
    if (cid not in ROOTS or raw['type']!='SPELL' or raw['collectible']is not True
            or type(raw['cost'])is not int or raw['tags'].get('SPELL_SCHOOL')!=4):
        raise TargetValidationError('Shaman history prices require complete original Nature spell faces')
    fields={}
    if cid=='ETC_356':
        if raw['tags'].get('LIFESTEAL')!=1:raise TargetValidationError('Altered Chord lost native Lifesteal')
        fields.update(keywords=(Keyword.LIFESTEAL,),player_overload_cost=CURRENT_OVERLOAD,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
    if cid=='TTN_831':fields['player_spell_count_cost']=TURN_NATURE
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1
            or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or d['evidence_only']
            or [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013','EX1_238','EX1_251','AT_051']
            or len(d['official_observations'])!=14
            or any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman history prices changed original roles or claimed a partial source complete')
    for key in('cards','existing_dependencies','printed_overload_records'):
        for row in d[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:
                raise TargetValidationError('Shaman history prices lost a complete original row')
    known,overload=printed_overload_source()
    if [x['record']for x in d['printed_overload_records']]!=list(overload):
        raise TargetValidationError('Charged Call changed its full original Overload classification')
    source=(ROOT/d['full_union_source_document']).resolve()
    if not source.is_relative_to(ROOT)or hashlib.sha256(source.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Shaman history prices changed the full original Nature union')
    return d


def register_past_shaman_history_prices(registry):
    d=load_batch();prepared=[]
    known,_=printed_overload_source()
    overload=frozenset(x['record']['id']for x in d['printed_overload_records'])
    for row in d['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Shaman history prices cannot change an existing original face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Shaman history prices changed complete existing pool metadata')
        prepared.append(card)

    def call(c):
        original=played_cards(c.state,c.player_id)
        if any(row.played_face.card_id not in known for row in original):
            raise UnsupportedDefinitionError('Charged Call encountered an unknown printed Overload classification')
        count=sum(row.played_face.card_id in overload for row in original)
        cost=min(10,1+count)
        return(DiscoverFromPool(c.player_id,'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost),
            source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)

    def crash(c):
        enemy=c.state.players[3-c.player_id]
        ids=(enemy.hero_id,*tuple(eid for eid in enemy.board if c.state.entities[eid].kind==CardType.MINION
            and c.state.entities[eid].active and c.state.entities[eid].health>0 and not c.state.entities[eid].doomed))
        return(DamageBatch(tuple(Damage(eid,3,c.source_id,DamageKind.SPELL)for eid in ids)),)

    registry.register_behavior(PREFIX+'ETC_356',lambda c:(Damage(c.target_id,6,c.source_id,DamageKind.SPELL),))
    registry.register_behavior(PREFIX+'SW_035',call)
    registry.register_behavior(PREFIX+'TTN_831',crash)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
