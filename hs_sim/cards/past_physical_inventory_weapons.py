"""Real original hand/deck/board consumers and ordinary random equipment."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.cross_zone import MinionScope,TransformCapturedMinion,minion_references
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.destruction_resources import SacrificeForFriendlyAttack
from hs_sim.engine.effects import Draw,ForceAttack
from hs_sim.engine.excavate import excavation_count
from hs_sim.engine.hand_exchange_discovery import DiscoverHandExchange
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.opponent_deck_copies import CopyOpponentDeck
from hs_sim.engine.original_minion_shuffles import ShuffleOriginalMinion
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_weapon_equipment import EquipRandomWeapons
from hs_sim.engine.random_zone_destruction import DestroyRandomZoneMinion
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-physical-inventory-weapons-v1.json'
BATCH_HASH='758dc33a9664ec5246b5587279ff6cd0081aeed63c6311bbde9951e54de2c6da'
PATCH,NADOX,FINLEY,KRUSH,THEOTAR,TONY,BENEDICTUS,BLING,MALKOROK,KURTRUS=ROOTS=(
    'LEG_RLK_071','RLK_658','DEEP_007','TOY_357','REV_238','ETC_541','ICC_215','GVG_119','OG_220','BAR_333')
DEPENDENCIES=()
EXISTING=('CORE_LOEA10_3',)
EVIDENCE=('MIS_701','LOEA10_3')
PREFIX='cards.past_physical_inventory_weapons.'
UNDEAD=PREFIX+'undead'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION'or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Physical inventory consumers require their complete original minion faces')
    fields={}
    if cid==NADOX:fields.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),'friendly'),target_rule=UNDEAD)
    if cid in(KRUSH,TONY,KURTRUS):fields['keywords']=({KRUSH:(Keyword.CHARGE,),TONY:(Keyword.FINALE,),KURTRUS:(Keyword.OUTCAST,)}[cid])
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=PREFIX+cid,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=24 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Physical inventory source roles or completeness claims changed')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original inventory source row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):raise TargetValidationError('Cropped full original past source')
    finley=next(x['record']for x in d['cards']if x['record']['id']==FINLEY)
    child=d['existing_dependencies'][0]['record']
    if finley['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')!=child['dbf_id']or child['id']!=EXISTING[0]:
        raise TargetValidationError('Finley lost its explicit original client child identity')
    return d


def register_past_physical_inventory_weapons(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Finley changed its exact existing Tinyfin')
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Physical inventory consumer replaced or changed another original face')
        registry._validate_card(card);prepared.append(card)
    registry.register_target_predicate(TargetPredicateSpec(UNDEAD,current_tribes_any=('undead',)))
    def patch(c):
        return tuple(DestroyRandomZoneMinion(c.player_id,3-c.player_id,z,c.source_id)for z in(Zone.HAND,Zone.DECK,Zone.BOARD))
    def nadox(c):
        if c.target_id is None:return()
        e=c.state.entities[c.target_id]
        if(e.id==c.source_id or e.kind!=CardType.MINION or e.controller!=c.player_id or e.zone!=Zone.BOARD or
                not e.active or e.doomed or e.health<=0 or not has_any_tribe(registry,e,('undead',),basis='current')):return()
        return(SacrificeForFriendlyAttack(c.player_id,c.source_id,MinionReference.capture(e)),)
    def finley(c):
        if excavation_count(c.state,c.player_id)<2:return()
        refs=minion_references(c.state,registry,3-c.player_id,MinionScope((Zone.BOARD,)),c.source_id)
        return tuple(TransformCapturedMinion(ref,EXISTING[0],c.source_id)for ref in refs)
    def krush(c):
        entries={1:[],2:[]}
        for pid in(c.player_id,3-c.player_id):
            for ref in minion_references(c.state,registry,pid,MinionScope((Zone.BOARD,)),c.source_id):
                e=c.state.entities[ref.entity_id]
                if e.attack<c.source.attack:
                    entries[e.owner].append(ShuffleOriginalMinion(SourceAllocationFact.capture(c.state,e),e.owner,c.source_id))
        return tuple(work for pid in(c.player_id,3-c.player_id)for work in shuffled(c,entries[pid],player_id=pid))
    def tony(c):
        conditions=c.spell_conditions
        if conditions is None:raise ValueError('Tony requires its actual accepted Finale conditions')
        return(CopyOpponentDeck(c.player_id,c.source_id,True),*((Draw(c.player_id,1,c.source_id),)if conditions.finale else()))
    def kurtrus(c):
        conditions=c.spell_conditions
        if conditions is None:raise ValueError('Kurtrus requires its actual accepted Outcast conditions')
        if not living_source(c):return()
        source=BoardPresenceReference.capture(c.state,c.source_id)
        refs=minion_references(c.state,registry,3-c.player_id,MinionScope((Zone.BOARD,)),c.source_id)
        work=(GrantCapturedKeyword(source,Keyword.IMMUNE,c.source_id,expires_turn=c.state.turn),)if conditions.outcast else()
        if refs:
            work+=tuple(ForceAttack(source,BoardPresenceReference.capture(c.state,ref.entity_id))for ref in(refs[0],refs[-1]))
        return work
    bodies={PATCH:patch,NADOX:nadox,FINLEY:finley,KRUSH:krush,THEOTAR:lambda c:(DiscoverHandExchange(c.player_id,c.source_id),),
        TONY:tony,BENEDICTUS:lambda c:(CopyOpponentDeck(c.player_id,c.source_id),),
        BLING:lambda c:(EquipRandomWeapons(c.player_id,c.source_id,own_attack=0,own_durability=0),),
        MALKOROK:lambda c:(EquipRandomWeapons(c.player_id,c.source_id,own_attack=0,own_durability=0,opponent=False),),KURTRUS:kurtrus}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
