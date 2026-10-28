"""Eleven full past-secret faces over existing physical facts and effects."""
from dataclasses import replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.effects import Damage,Draw,GrantKeyword,RandomDamage,RandomDestroy
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.hero_powers import power_record
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealthFlow,Keyword,SecretSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference,SetCapturedMinionStats
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.secret_conditions import SecretHandSpace
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import enemy_minions,event_play,rat
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-secret-base-effects-v1.json'
BATCH_HASH='8d7831a3e6029ca8332c59c0e75f1f27b3c0861c9639f62a0817b9fb05b9b228'
LEAVES=DEPENDENCIES=('AT_073','BOT_908','BT_709','DAL_570','EX1_132','EX1_379','EX1_609','WON_018','ULD_152','GIL_903','LOE_021')
SPIRIT,MATRIX,TRICKS,SURRENDER,EYE,REPENT,SNIPE,SNIPE_REPRINT,PLATE,WISDOM,DART=LEAVES
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_secret_base.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-secret-base-effects-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=LEAVES or
            len(d['official_observations'])!=22 or any(d[k] for k in ('cards','existing_dependencies','new_standard_roots',
                'source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in d['dependencies'])):
        raise TargetValidationError('Past secret consumers lost eleven full faces and22 primary observations')
    path=ROOT/d['reference_document'];ref=json.loads(path.read_text(encoding='utf8'))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(ref['candidate_ids']):
        raise TargetValidationError('Past secret consumers lost their unfiltered full reference')
    return d


def friendly_minions(c):
    return tuple(e for i in c.state.players[c.player_id].board for e in (c.state.entities[i],)
        if e.kind==CardType.MINION and e.active and e.health>0 and not e.doomed)


def enemy_cast(c,kind):
    if c.event is None or c.event.kind!=kind:return None
    row=cast_record(c.state,dict(c.event.data)['cast_id'])
    if (row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
        raise ResolutionError('Secret lost its original CAST receipt')
    if row.player_id==c.player_id:return None
    if kind=='spell_cast_finished' and (not row.completed or not row.payload_started or row.failure is not None or row.interrupted):return None
    return row


def played_minion(c):
    row=event_play(c)
    if row is None or row.player_id==c.player_id or row.kind!=CardType.MINION or row.countered or row.minion_result!='summoned':return None
    e=c.state.entities.get(row.source_id)
    if e is None or e.zone!=Zone.BOARD or e.kind!=CardType.MINION or e.controller!=row.player_id or not e.active or e.health<=0 or e.doomed:return None
    original=[x for x in c.state.successful_summon_history if x.entity_id==row.source_id and
        x.turn==row.turn and x.action==row.action and x.minion.zone_epoch==row.submitted_cost.zone_epoch+2]
    if len(original)!=1 or original[0].minion.entered_order!=e.entered_order:return None
    return e


def attacked_minion(c):
    if not attack_live(c.state,c.window):return None
    attacker=c.state.entities[c.window.source_id];target=c.state.entities[c.window.target_id]
    return target if (attacker.controller!=c.player_id and target.kind==CardType.MINION and
        target.controller==c.player_id and Keyword.DIVINE_SHIELD not in target.keywords) else None


def hero_damage(c):
    if c.event is None or c.event.kind!='health_resolved':return None
    row=health_result(c.event)
    return row if (row is not None and row.flow==HealthFlow.DAMAGE.value and row.target_kind==CardType.HERO.value and
        row.target_controller==c.player_id and row.damage_dealt>0 and row.prevention is None) else None


def enemy_power(c):
    if c.event is None or c.event.kind!='hero_power_used':return False
    row=power_record(c.state,dict(c.event.data)['power_id'])
    if (row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id) or not row.completed:
        raise ResolutionError('Dart Trap lost its original completed Hero Power')
    return row.player_id!=c.player_id and row.origin=='manual' and not row.interrupted


def register_past_secret_base_effects(registry):
    def buff_board(c,attack,health):
        return tuple(BuffCapturedMinion(capture_board_presence(c.state,e.id),attack,health,c.source_id) for e in friendly_minions(c))
    def matrix(c):
        target=attacked_minion(c)
        return () if target is None else (GrantKeyword(target.id,Keyword.DIVINE_SHIELD,c.source_id),)
    def snipe(c):
        target=played_minion(c)
        return () if target is None else (Damage(target.id,6,c.source_id,DamageKind.SPELL),)
    def repent(c):
        target=played_minion(c)
        return () if target is None else (SetCapturedMinionStats(MinionReference.capture(target),health=1,source_id=c.source_id),)
    def eye(c):
        row=hero_damage(c)
        return () if row is None else (Damage(c.state.players[3-c.player_id].hero_id,row.damage_dealt,c.source_id,DamageKind.SPELL),)
    conditions={SPIRIT:lambda c:bool(c.event and c.event.kind=='turn_started' and c.event.player_id==c.player_id and friendly_minions(c)),
        MATRIX:lambda c:attacked_minion(c) is not None,TRICKS:lambda c:SecretHandSpace(enemy_cast(c,'spell_cast_finished') is not None),
        SURRENDER:lambda c:enemy_cast(c,'spell_cast_started') is not None and bool(friendly_minions(c)),
        EYE:lambda c:hero_damage(c) is not None,REPENT:lambda c:played_minion(c) is not None and played_minion(c).max_health!=1,
        SNIPE:lambda c:played_minion(c) is not None,SNIPE_REPRINT:lambda c:played_minion(c) is not None,
        PLATE:lambda c:enemy_cast(c,'spell_cast_finished') is not None and bool(enemy_minions(c,registry)),
        WISDOM:lambda c:SecretHandSpace(rat(c)),DART:enemy_power}
    bodies={SPIRIT:lambda c:buff_board(c,1,1),MATRIX:matrix,TRICKS:lambda c:(Draw(c.player_id,2,c.source_id),),
        SURRENDER:lambda c:buff_board(c,0,2),EYE:eye,REPENT:repent,SNIPE:snipe,SNIPE_REPRINT:snipe,
        PLATE:lambda c:(RandomDestroy(enemy_minions(c,registry),c.source_id),),WISDOM:lambda c:(Draw(c.player_id,2,c.source_id),),
        DART:lambda c:(RandomDamage((c.state.players[3-c.player_id].hero_id,*enemy_minions(c,registry)),5,c.source_id,DamageKind.SPELL),)}
    events={SPIRIT:'turn_started',MATRIX:'attack_declared',TRICKS:'spell_cast_finished',SURRENDER:'spell_cast_started',
        EYE:'health_resolved',REPENT:'card_played',SNIPE:'card_played',SNIPE_REPRINT:'card_played',PLATE:'spell_cast_finished',WISDOM:'card_played',DART:'hero_power_used'}
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id'];key=SNIPE if cid==SNIPE_REPRINT else cid
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Past secret already registered')
        if raw['tags'].get('SECRET')!=1 or raw['type']!='SPELL':raise TargetValidationError('Past root is not an actual Secret')
        meta=metadata_from_record(raw)
        if cid in (SNIPE,SNIPE_REPRINT):meta=replace(meta,deck_identity=SNIPE)
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(key,(events[cid],),PREFIX+cid,PREFIX+cid,turn='owner' if cid==SPIRIT else 'opponent'),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=meta)
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,conditions[cid]);registry.register_behavior(PREFIX+cid,bodies[cid])
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
