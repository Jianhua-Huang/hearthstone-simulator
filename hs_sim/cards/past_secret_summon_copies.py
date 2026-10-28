"""Original secret summon requests and current copies with actual entry material."""
from dataclasses import replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.interrupts import attack_live
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,SummonStats,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import rat
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .past_secret_base_effects import enemy_cast,played_minion

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-secret-summon-copies-v1.json'
BATCH_HASH='0f7a219b2fee0a00956f5a383feb3addd0241de3c0d1312dd8d6686daf6a4527'
BEAR,PACK,AMBUSH,SHADOW,SNAKES,VENOM,CAT,RAT,STEED,SPIDER=LEAVES=(
    'AT_060','BT_203','BT_707','DMF_513','EX1_554','ICC_200','KAR_004','GIL_577','BAR_550','REV_827')
TOKENS=('BT_707t','EX1_554t','KAR_004a','BAR_550t','REV_827t')
DEPENDENCIES=(*LEAVES,*TOKENS)
EXISTING=('CS2_125','EX1_170','GIL_577t')
TOKEN_KEYWORDS=((Keyword.POISONOUS,),(),(Keyword.STEALTH,),(Keyword.TAUNT,),(Keyword.STEALTH,))
PREFIX='cards.past_secret_summon_copies.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-secret-summon-copies-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id'] for x in d['existing_dependencies'])!=EXISTING or len(d['official_observations'])!=24 or
            any(d[k] for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in (*d['dependencies'],*d['existing_dependencies']))):
        raise TargetValidationError('Past summon secrets lost complete roots, tokens or original dependencies')
    rows={x['record']['id']:x['record'] for x in d['dependencies']}
    for obs in d['official_observations']:
        if obs['card_id'] in d['bilingual_parent_token_links']:
            token=rows[d['bilingual_parent_token_links'][obs['card_id']]]
            if obs['face']['childIds']!=[token['dbf_id']]:raise TargetValidationError('Original token child link changed')
    path=ROOT/d['reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Past summon secrets lost the full unfiltered reference')
    return d


def hero_attacked(c,registry):
    if c.event is None or c.event.kind!='attack_finished':return None
    row=completed_attack(c)
    return row if (row is not None and row.combat.target_player_id==c.player_id and
        registry.card(row.combat.target_card_id).kind==CardType.HERO) else None


def attacking_minion(c,registry):
    row=hero_attacked(c,registry)
    if row is None or row.source_kind!=CardType.MINION:return None
    e=c.state.entities.get(row.declaration.source_id)
    return e if (e is not None and e.zone==Zone.BOARD and e.kind==CardType.MINION and e.active and
        e.health>0 and not e.doomed and e.entered_order==row.combat.source_entered_order) else None


def attacked_friendly(c):
    if not attack_live(c.state,c.window):return None
    e=c.state.entities[c.window.target_id]
    return e if e.kind==CardType.MINION and e.controller==c.player_id else None


def validate_existing(registry,data):
    for item,keywords in zip(data['existing_dependencies'],((Keyword.TAUNT,),(Keyword.POISONOUS,),())):
        raw=item['record'];card=registry.card(raw['id'])
        meta=replace(metadata_from_record(raw),deck_identity=raw['id'])
        if (card.kind,card.cost,card.attack,card.health,card.keywords,card.metadata)!=(
                CardType.MINION,raw['cost'],raw['attack'],raw['health'],keywords,meta):
            raise TargetValidationError('Original reused summon face changed: '+raw['id'])
        if registry.pool_card(raw['id'])!=PoolCard.from_definition(card):raise TargetValidationError('Original summon metadata changed')


def register_past_secret_summon_copies(registry):
    data=load_batch();validate_existing(registry,data)
    conditions={BEAR:lambda c:hero_attacked(c,registry) is not None,PACK:lambda c:attacked_friendly(c) is not None,
        AMBUSH:lambda c:played_minion(c) is not None,SHADOW:lambda c:attacking_minion(c,registry) is not None,
        SNAKES:lambda c:attacked_friendly(c) is not None,VENOM:lambda c:attacked_friendly(c) is not None,
        CAT:lambda c:enemy_cast(c,'spell_cast_finished') is not None,RAT:rat,STEED:rat,
        SPIDER:lambda c:enemy_cast(c,'spell_cast_finished') is not None}
    named={BEAR:('CS2_125',1),AMBUSH:('BT_707t',1),SNAKES:('EX1_554t',3),VENOM:('EX1_170',1),
        CAT:('KAR_004a',1),RAT:('GIL_577t',1),STEED:('BAR_550t',1),SPIDER:('REV_827t',1)}
    def summon(c,token,count):
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(token),),cause) for _ in range(count))
    def pack(c):
        e=attacked_friendly(c)
        return () if e is None else (CopyMinion(capture_board_presence(c.state,e.id),c.player_id,
            stats=SummonStats(3,3),cause=SummonCause.capture(c)),)
    def shadow(c):
        e=attacking_minion(c,registry)
        return () if e is None else (CopyMinion(capture_board_presence(c.state,e.id),c.player_id,
            cause=SummonCause.capture(c),minion_grant=CreatedMinionGrant(keywords=(Keyword.STEALTH,))),)
    bodies={cid:(lambda c,token=token,count=count:summon(c,token,count)) for cid,(token,count) in named.items()}
    bodies.update({PACK:pack,SHADOW:shadow})
    events={BEAR:'attack_finished',PACK:'attack_declared',AMBUSH:'card_played',SHADOW:'attack_finished',
        SNAKES:'attack_declared',VENOM:'attack_declared',CAT:'spell_cast_finished',RAT:'card_played',STEED:'card_played',SPIDER:'spell_cast_finished'}
    prepared=[]
    for i,item in enumerate(data['dependencies']):
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Summon secret identity already registered')
        meta=metadata_from_record(raw)
        if cid in LEAVES:
            if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Summon root is not an actual secret')
            if cid==RAT:meta=replace(meta,deck_identity=RAT)
            card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
                secret=SecretSpec(cid,(events[cid],),PREFIX+cid,PREFIX+cid,requires_board_space=True),
                spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=meta)
        else:
            if raw['type']!='MINION' or raw['collectible']:raise TargetValidationError('New token must keep its noncollectible minion face')
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
                keywords=TOKEN_KEYWORDS[i-len(LEAVES)],metadata=meta)
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,conditions[cid]);registry.register_behavior(PREFIX+cid,bodies[cid])
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
