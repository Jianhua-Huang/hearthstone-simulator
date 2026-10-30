"""Five real consumers of existing attack, cost, healing, mana and play facts."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.character_attacks import completed_attack,completed_minion_keywords
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import AddCostModifier,ChangeManaCrystals,Damage,DamageBatch,InvokeBehavior
from hs_sim.engine.healing_history import restored_health
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword,TriggerSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-hand-edge-cost-healing-v1.json'
BATCH_HASH='3ae204e634b8ee75faca7ed204af6e0b894dce4244c2a3e93edf27a5c0066351'
HALVERIA,SCABBS,XYRELLA,NOZDORMU,ALTRUIS=ROOTS=('ETC_399','BAR_552','BAR_735','DRG_309','BT_937')
DEPENDENCIES=EXISTING=()
EVIDENCE=('MIS_701',)
PREFIX='cards.past_hand_edge_cost_healing.'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Hand-edge/cost/healing consumers require their complete original minion faces')
    fields={}
    if cid==SCABBS:fields.update(combo=PREFIX+cid,keywords=(Keyword.COMBO,))
    elif cid in(XYRELLA,NOZDORMU):fields['battlecry']=PREFIX+cid
    else:fields['triggers']=(TriggerSpec('attack_finished'if cid==HALVERIA else'card_played',PREFIX+cid),)
    if cid==HALVERIA:fields['keywords']=(Keyword.RUSH,)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            any(d[k]for k in('dependencies','existing_dependencies','complete_past_source_bound','new_standard_roots',
                'membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=12):
        raise TargetValidationError('Hand-edge/cost/healing consumers changed their complete roles or claimed full support')
    for row in d['cards']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original hand-edge/cost/healing row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed complete past source')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            row['record']!=rows[row['record']['id']]for row in d['cards']):raise TargetValidationError('Cropped original past source')
    return d


def register_past_hand_edge_cost_healing(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Hand-edge/cost/healing consumer changed or replaced another original face')
        registry._validate_card(card);prepared.append(card)
    def haria(c):
        row=completed_attack(c)
        if row is None or row.source_kind!=CardType.MINION or row.combat.player_id!=c.player_id or not living_source(c):return ()
        if Keyword.RUSH not in completed_minion_keywords(c,registry):return ()
        return(BuffMinionsInZones(c.player_id,1,0,MinionScope((Zone.BOARD,)),c.source_id),)
    def scabbs(c):
        return(AddCostModifier(c.player_id,CostSpec(delta=-2),uses_remaining=2,source_id=c.source_id,expires_turn=c.state.turn),)
    def xyrella(c):
        amount=restored_health(c.state,c.player_id,turn=c.state.turn)
        return(DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.MINION_ABILITY)
            for i in minions(c,registry,3-c.player_id))),)if amount else ()
    def crystals(c,player_id):
        player=c.state.players[player_id];amount=min(10,player.mana_cap)-player.max_mana
        return(ChangeManaCrystals(player_id,amount,filled=False),)if amount else ()
    def nozdormu(c):
        return tuple(InvokeBehavior(PREFIX+'crystals.'+str(p),c.source_id,c.player_id)for p in(c.player_id,3-c.player_id))
    def altruis(c):
        if c.event is None or c.event.kind!='card_played':raise ValueError('Altruis requires its actual completed physical card play')
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise ValueError('Altruis lost its original completed physical play')
        if row.player_id!=c.player_id or row.source_id==c.source_id or not living_source(c)or row.hand_index not in(0,row.hand_size-1):return ()
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.MINION_ABILITY)for i in characters(c,registry,3-c.player_id))),)
    for cid,body in((HALVERIA,haria),(SCABBS,scabbs),(XYRELLA,xyrella),(NOZDORMU,nozdormu),(ALTRUIS,altruis)):
        registry.register_behavior(PREFIX+cid,body)
    registry.register_behavior(PREFIX+'crystals.1',lambda c:crystals(c,1))
    registry.register_behavior(PREFIX+'crystals.2',lambda c:crystals(c,2))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
