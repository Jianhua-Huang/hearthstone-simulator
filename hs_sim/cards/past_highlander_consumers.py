"""Current no-duplicate-deck consumers over existing ordinary effects."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.deck_conditions import CheckDeckCondition,DeckCondition
from hs_sim.engine.effects import AddCostModifier,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE,RandomSplitDamage,SplitDamageScope
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference,CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-highlander-consumers-v1.json'
BATCH_HASH='c8dbc9573d21902568d1d45b1a6b2eb1efbc1683bcda8183a35cd469c2070c6d'
RAZA,SOLIA,KRUL,KRUL_PRINT,ELISE,BRANN,RENO=ROOTS=(
    'CFM_020','CFM_687','CFM_750','WON_324','ULD_139','ULD_156','ULD_238')
KRUSH,=DEPENDENCIES=('ULD_156t3',)
PREFIX='cards.past_highlander_consumers.'
CONDITION=DeckCondition('current','no_duplicates')


def make_definition(raw):
    cid=raw['id']
    if(cid not in ROOTS+DEPENDENCIES or raw['type']!='MINION'or
            raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Highlander consumer requires its complete actual Legendary minion')
    if cid==KRUSH:
        if raw['collectible']or raw['tags'].get('CHARGE')!=1:
            raise TargetValidationError('Brann requires his actual noncollectible Charge child')
        fields=dict(keywords=(Keyword.CHARGE,))
    else:
        if not raw['collectible']or raw['tags'].get('BATTLECRY')!=1:
            raise TargetValidationError('Highlander root lost its complete actual Battlecry role')
        fields=dict(battlecry=PREFIX+cid)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-highlander-consumers-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or
            tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in data['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701','EX1_543']or
            len(data['official_observations'])!=20 or
            any(data[k]for k in('complete_past_legendary_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Highlander consumers lost complete identities, roles or domain boundaries')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Highlander consumer changed a complete pinned raw row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Highlander consumer changed a complete retained reference')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    records={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Highlander consumers cropped the complete original past domain')
    parent=next(x['record']for x in data['cards']if x['record']['id']==BRANN)
    child=data['dependencies'][0]['record']
    faces=[x['face']for x in data['official_observations']if x['card_id']==BRANN]
    if(parent['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=child['dbf_id']or
            len(faces)!=2 or any(child['dbf_id']not in f.get('childIds',[])for f in faces)):
        raise TargetValidationError('Brann lost his actual distinct named child association')
    return data


def register_past_highlander_consumers(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Highlander consumer changed a complete existing dependency')
    for row in data['cards']+data['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Highlander consumer cannot replace or alter a complete physical face')
        registry._validate_card(card);prepared.append(card)
    def branch(c,effects):return(CheckDeckCondition(c.player_id,CONDITION,effects),)
    def raza(c):return branch(c,(AddCostModifier(c.player_id,CostSpec(set_to=0,
        card_types=(CardType.HERO_POWER,)),source_id=c.source_id),))
    def solia(c):return branch(c,(AddCostModifier(c.player_id,CostSpec(set_to=0,
        card_types=(CardType.SPELL,)),uses_remaining=1,source_id=c.source_id,expires_turn=c.state.turn),))
    def krul(c):return branch(c,(InvokeBehavior(PREFIX+'demons',c.source_id,c.player_id),))
    def demons(c):
        refs=[]
        for eid in tuple(c.state.players[c.player_id].hand):
            e=c.state.entities[eid];card=registry.card(e.card_id)
            if card.kind==CardType.MINION and has_any_tribe(registry,e,('demon',)):refs.append(CardReference.capture(e))
        cause=SummonCause.capture(c)
        return tuple(SummonStoredCard(ref,c.player_id,cause=cause)for ref in refs)
    def elise(c):return branch(c,(InvokeBehavior(PREFIX+'copy_hand',c.source_id,c.player_id),))
    def copy_hand(c):
        materials=tuple(CapturedCardCopyMaterial.capture(c.state,c.state.entities[eid])
            for eid in tuple(c.state.players[c.player_id].hand))
        return tuple(CopyCard(material,c.player_id,mode='current',source_id=c.source_id)for material in materials)
    def brann(c):return branch(c,(SummonByCard(c.player_id,(SummonEntryMaterial(KRUSH),),SummonCause.capture(c)),))
    def reno(c):return branch(c,(RandomSplitDamage(c.player_id,None,c.source_id,10,
        SplitDamageScope('enemy',(CardType.MINION,)),profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY),))
    for name,body in((RAZA,raza),(SOLIA,solia),(KRUL,krul),(KRUL_PRINT,krul),(ELISE,elise),
            (BRANN,brann),(RENO,reno),('demons',demons),('copy_hand',copy_hand)):
        registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
