"""Real Hunter Nature damage, Emerald Spellstones and Infest consumers.

This effect cohort does not bind the still incomplete nine-card Hunter source.
"""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HandProgressSpec,Keyword,SpellSchool,TargetSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedDeathrattle,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-hunter-nature-leaves-v1.json'
BATCH_HASH='751e2c9061df3f49b2d782ecf34debcd6c83e3d017f425d2fe443be3d74a3d13'
ROOTS=('DRG_006','GVG_073','ICC_049','LOOT_080','OG_045','WON_306')
STONES=('LOOT_080','LOOT_080t2','LOOT_080t3')
WOLF='LOOT_077t'
DEPENDENCIES=(*STONES[1:],WOLF)
PREFIX='cards.past_hunter_nature_leaves.'
BEASTS=PoolQuery(kinds=(CardType.MINION,),tribes_any=('beast',),collectible=True)
TARGETED=('DRG_006','GVG_073','ICC_049','WON_306')


def make_definition(raw):
    cid=raw['id'];kind=CardType.MINION if cid==WOLF else CardType.SPELL
    if (cid not in ROOTS+DEPENDENCIES or raw['type'].lower()!=kind.value or
            raw['collectible']is not(cid in ROOTS) or type(raw['cost'])is not int or
            (kind==CardType.SPELL and raw['tags'].get('SPELL_SCHOOL')!=4)):
        raise TargetValidationError('Hunter Nature leaves require complete original faces')
    fields={}
    if cid in TARGETED:fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid in STONES[:2]:
        fields['hand_progress']=HandProgressSpec('event',1,STONES[STONES.index(cid)+1],
            event='card_committed',condition_id=PREFIX+'secret',upgrade_cost_policy='clear_local')
    if cid==WOLF:
        if (raw['cost'],raw['attack'],raw['health'])!=(3,3,3):raise TargetValidationError('Emerald requires its actual 3/3 Wolf')
        fields.update(attack=3,health=3)
    else:fields.update(on_play=PREFIX+cid,spell_school=SpellSchool.NATURE)
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            [x['record']['id']for x in d['evidence_only']]!=['ICC_049e','OG_045a'] or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013'] or
            len(d['official_observations'])!=20 or d['remaining_hunter_ids']!=['AV_333','REV_361','TID_075'] or
            any(d[k]for k in('complete_hunter_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Hunter Nature leaves lost source roles or claimed a partial class view complete')
    for key in ('cards','dependencies','existing_dependencies','evidence_only'):
        for row in d[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Hunter Nature lost a complete original row')
    document=(ROOT/d['full_union_source_document']).resolve()
    if not document.is_relative_to(ROOT)or hashlib.sha256(document.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Hunter Nature changed its original complete reference')
    return d


def register_past_hunter_nature_leaves(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Hunter Nature cannot replace or change a complete native face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Hunter Nature changed existing complete pool metadata')
        prepared.append(card)

    def shot(c,dragon=False):
        hero=not dragon or any(has_any_tribe(registry,c.state.entities[eid],('dragon',))
            for eid in c.state.players[c.player_id].hand if eid!=c.source_id)
        hits=(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),)
        if hero:hits+=(Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),)
        return(DamageBatch(hits),)

    def poison(c):
        result=c.health_result
        if result is None or c.event is None or c.event.kind!='health_resolved':
            raise ResolutionError('Toxic Arrow requires its original health result')
        if (result.target_id!=result.original_target_id or result.target_kind!=CardType.MINION.value or
                result.health_before<=0 or result.doomed_before or result.health_after<=0 or result.doomed_after):return()
        ref=MinionReference(result.target_id,result.target_controller,result.target_card_id,
            result.target_zone_epoch,result.target_entered_order)
        return(GrantCapturedKeyword(ref,Keyword.POISONOUS,c.source_id),)

    def secret(c):
        if c.event is None or c.event.kind!='card_committed':raise ResolutionError('Emerald requires a real committed hand play')
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Emerald lost its original committed play')
        return(record.player_id==c.player_id and record.source_id!=c.source_id and
            record.kind==CardType.SPELL and registry.card(record.card_id).secret is not None)

    def wolves(c,count):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(WOLF),),SummonCause.capture(c))
        return(request,)*count

    def infest(c):
        refs=tuple(MinionReference.capture(c.state.entities[eid])for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].kind==CardType.MINION and c.state.entities[eid].active and
            c.state.entities[eid].health>0 and not c.state.entities[eid].doomed)
        return tuple(GrantCapturedDeathrattle(ref,PREFIX+'beast',c.source_id)for ref in refs)

    registry.register_trigger_condition(PREFIX+'secret',secret)
    registry.register_behavior(PREFIX+'DRG_006',lambda c:shot(c,True))
    for cid in ('GVG_073','WON_306'):registry.register_behavior(PREFIX+cid,shot)
    registry.register_behavior(PREFIX+'ICC_049',lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL,on_result=PREFIX+'poison'),))
    registry.register_behavior(PREFIX+'poison',poison)
    for count,cid in enumerate(STONES,2):registry.register_behavior(PREFIX+cid,lambda c,count=count:wolves(c,count))
    registry.register_behavior(PREFIX+'OG_045',infest)
    registry.register_behavior(PREFIX+'beast',lambda c:(GenerateFromPool(c.player_id,'constructed.cards',BEASTS,source_id=c.source_id),))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
