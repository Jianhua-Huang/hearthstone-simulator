"""Past secrets over original physical plays, health packets and live windows."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import Damage,GrantKeyword,RandomBuff,Destroy
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealthFlow,Keyword,SecretSpec,Zone
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference,SetCapturedMinionStats
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play,rat
from .fixed_companion_cards import companion_effects
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .past_secret_base_effects import friendly_minions,hero_damage
from .past_secret_summon_copies import attacked_friendly

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-secret-event-effects-v1.json'
BATCH_HASH='0ba3af7aa2b832128dd6e6e874ea514b7f1de2b57eea627a0526ba98e0cdde5b'
CACHE,RECKON,CAGE,AVENGE,EVADE,MOTION,BIN,BAIT,JUDGMENT=LEAVES=(
    'CFM_026','CS3_016','DMF_123','FP1_020','LOOT_214','MAW_010','MIS_105','TTN_504','WC_033')
EXISTING=('NEW1_034','NEW1_033','NEW1_032')
PREFIX='cards.past_secret_event_effects.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-secret-event-effects-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=LEAVES or
            tuple(x['record']['id'] for x in d['existing_dependencies'])!=EXISTING or len(d['official_observations'])!=18 or
            any(d[k] for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in (*d['dependencies'],*d['existing_dependencies'])) or
            any(canonical_digest(x['definition'])!=x['definition_sha256'] for x in d['existing_dependencies'])):
        raise TargetValidationError('Past event secrets lost complete identities or reused companions')
    path=ROOT/d['reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Past event secrets lost their full unfiltered reference')
    return d


def physical_play(c,kinds):
    row=event_play(c)
    return row if row is not None and row.player_id!=c.player_id and row.kind in kinds else None


def hand_minion(c):
    return any(c.state.entities[i].kind==CardType.MINION for i in c.state.players[c.player_id].hand)


def controlled_minions(c):
    return tuple(c.state.entities[i] for i in c.state.players[c.player_id].board
        if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].health>0 and not c.state.entities[i].doomed)


def damaging_enemy(c):
    if c.event is None or c.event.kind!='health_resolved':return None
    row=health_result(c.event)
    if row is None or row.flow!=HealthFlow.DAMAGE.value or row.damage_dealt<3 or row.source_controller==c.player_id:return None
    e=c.state.entities.get(row.source_id)
    return e if (e is not None and e.zone==Zone.BOARD and e.kind==CardType.MINION and e.controller==row.source_controller and
        e.active and e.health>0 and not e.doomed and (e.zone_epoch,e.entered_order)==(row.source_zone_epoch,row.source_entered_order)) else None


def attacking_enemy(c):
    if not attack_live(c.state,c.window):return None
    e=c.state.entities[c.window.source_id]
    return e if e.kind==CardType.MINION and e.controller!=c.player_id else None


def register_past_secret_event_effects(registry):
    data=load_batch()
    for item in data['existing_dependencies']:
        cid=item['record']['id'];card=registry.card(cid)
        if canonical_digest(asdict(card))!=item['definition_sha256'] or registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Original complete Animal Companion changed: '+cid)
    def cache(c):return (RandomBuffStoredMinion(c.player_id,2,2,source_id=c.source_id),)
    def reckon(c):
        e=damaging_enemy(c)
        return () if e is None else (Destroy(e.id,c.source_id),)
    def bait(c):
        e=attacked_friendly(c)
        return () if e is None else (BuffCapturedMinion(MinionReference.capture(e),3,3,c.source_id),)
    def reckoner(c):
        e=attacking_enemy(c)
        return () if e is None else (SetCapturedMinionStats(MinionReference.capture(e),attack=1,health=1,source_id=c.source_id),)
    kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON)
    def bargain(c):
        row=physical_play(c,kinds)
        return () if row is None else (DrawPhysicalGroup(c.player_id,c.source_id,
            tuple(DrawGroupSlot(PoolQuery(kinds=(kind,))) for kind in kinds if kind!=row.kind)),)
    conditions={CACHE:lambda c:physical_play(c,(CardType.MINION,)) is not None and hand_minion(c),
        RECKON:lambda c:damaging_enemy(c) is not None,
        CAGE:lambda c:bool(c.event and c.event.kind=='turn_started' and c.event.player_id==c.player_id and len(controlled_minions(c))>=2),
        AVENGE:lambda c:bool(c.event and c.event.kind=='minion_died' and c.event.player_id==c.player_id and friendly_minions(c)),
        EVADE:lambda c:hero_damage(c) is not None,MOTION:rat,
        BIN:lambda c:physical_play(c,kinds) is not None,BAIT:lambda c:attacked_friendly(c) is not None,
        JUDGMENT:lambda c:attacking_enemy(c) is not None}
    bodies={CACHE:cache,RECKON:reckon,CAGE:lambda c:companion_effects(c,registry),
        AVENGE:lambda c:(RandomBuff(tuple(e.id for e in friendly_minions(c)),3,2,c.source_id),),
        EVADE:lambda c:(GrantKeyword(c.state.players[c.player_id].hero_id,Keyword.IMMUNE,c.source_id,expires_turn=c.state.turn),),
        MOTION:lambda c:(Damage(c.state.players[3-c.player_id].hero_id,6,c.source_id,DamageKind.SPELL),),
        BIN:bargain,BAIT:bait,JUDGMENT:reckoner}
    events={CACHE:'card_played',RECKON:'health_resolved',CAGE:'turn_started',AVENGE:'minion_died',EVADE:'health_resolved',
        MOTION:'card_played',BIN:'card_played',BAIT:'attack_declared',JUDGMENT:'attack_declared'}
    prepared=[]
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Past event secret identity already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Past event root is not an actual secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,(events[cid],),PREFIX+cid,PREFIX+cid,turn='owner' if cid==CAGE else 'opponent',requires_board_space=cid==CAGE),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,conditions[cid]);registry.register_behavior(PREFIX+cid,bodies[cid])
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
