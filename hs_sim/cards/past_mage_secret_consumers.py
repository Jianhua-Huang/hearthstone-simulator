"""Four original Mage secrets over ordinary death, copy and damage facts."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import ChoiceOption,CopyMinion,Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,HealthFlow,Keyword,SecretSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import death_record
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-mage-secret-consumers-v1.json'
BATCH_HASH='b11b286e18e241d8a28e77dbb18fc955350ad68bdb609a60b1179b7fba51caad'
POLICY='cn37-local-past-mage-secret-consumers-v1'
EFFIGY,WARD,FAIRE,CLONE=LEAVES=DEPENDENCIES=('AT_002','DEEP_000','DMF_107','ICC_082')
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_mage_secret_consumers.'
POOL='constructed.cards'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(data['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES or
            len(data['official_observations'])!=8 or any(data[k] for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Mage secrets require four complete original rows and eight primary faces')
    path=ROOT/data['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=data['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Mage secrets lost their full past source scope')
    return data


def friendly_death(c):
    if c.event is None or c.event.kind!='minion_died':return None
    fields=dict(c.event.data);row=death_record(c.state,fields['death_id'])
    if (row.entity_id,row.controller,row.batch,row.turn)!=(c.event.source_id,c.event.player_id,fields['batch'],c.state.turn):
        raise ResolutionError('Effigy lost its original committed death')
    return row if row.controller==c.player_id and row.zone==Zone.BOARD else None


def played_opponent_minion(c):
    row=event_play(c)
    return row if row is not None and row.player_id!=c.player_id and row.kind==CardType.MINION and not row.countered and row.minion_result=='summoned' else None


def no_hero_damage_this_opponent_turn(c):
    if c.event is None or c.event.kind!='turn_ended' or c.event.player_id==c.player_id:return False
    return not any((h:=row.health_result).turn==c.state.turn and h.target_kind==CardType.HERO.value and
        h.target_controller==c.player_id and h.flow==HealthFlow.DAMAGE.value and h.damage_dealt>0
        for row in c.state.damage_history)


def highest_friendly(c,registry):
    candidates=tuple(i for i in c.state.players[c.player_id].board
        if (e:=c.state.entities[i]).kind==CardType.MINION and e.active and e.health>0 and not e.doomed and
        not registry.card(e.card_id).interactable)
    if not candidates:return ()
    highest=max(local_cost(c.state.entities[i])[0] for i in candidates)
    return tuple(i for i in candidates if local_cost(c.state.entities[i])[0]==highest)


def register_past_mage_secret_consumers(registry):
    def effigy(c):
        row=friendly_death(c)
        if row is None:return ()
        query=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=row.base_cost,max_cost=row.base_cost)
        return (GenerateFromPool(c.player_id,POOL,query,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)
    def ward(c):
        candidates=highest_friendly(c,registry);cause=SummonCause.capture(c)
        options=tuple(ChoiceOption(str(i),str(i),(CopyMinion(capture_board_presence(c.state,i),c.player_id,cause=cause),))
            for i in candidates)
        if not options:return ()
        return options[0].effects if len(options)==1 else (ChooseRandomEffects(c.player_id,c.source_id,options),)
    def clone(c):
        row=played_opponent_minion(c)
        if row is None:return ()
        if row.minion_copy_material is None:raise ResolutionError('Frozen Clone lost its original played minion recipe')
        return (CopyCard(row.minion_copy_material,c.player_id,mode='base',source_id=c.source_id),)*2
    conditions={EFFIGY:lambda c:friendly_death(c) is not None,
        WARD:lambda c:c.event is not None and c.event.kind=='turn_started' and c.event.player_id==c.player_id and bool(highest_friendly(c,registry)),
        FAIRE:no_hero_damage_this_opponent_turn,CLONE:lambda c:played_opponent_minion(c) is not None}
    bodies={EFFIGY:effigy,WARD:ward,FAIRE:lambda c:(Draw(c.player_id,3,source_id=c.source_id),),CLONE:clone}
    events={EFFIGY:'minion_died',WARD:'turn_started',FAIRE:'turn_ended',CLONE:'card_played'}
    prepared=[]
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Mage secret face already registered')
        if raw['tags'].get('SECRET')!=1:raise TargetValidationError('Mage secret lost its original keyword')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,(events[cid],),PREFIX+cid,PREFIX+cid,turn='owner' if cid==WARD else 'opponent',
                requires_board_space=cid in (EFFIGY,WARD)),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,conditions[cid]);registry.register_behavior(PREFIX+cid,bodies[cid])
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
