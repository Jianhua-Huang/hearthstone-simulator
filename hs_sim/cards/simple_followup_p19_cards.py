"""Real Shatter and healing consumers using native damage and forced combat."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,DamageBatch,ForceAttack
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,DamageKind,HealthFlow,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p19-v1.json'
BATCH_HASH='5594282d20d5226ed751eab1da152319096f0602ffb98a647baf9d881d9c2ebb'
PYROMANCER='TIME_101';SHADOW='TLC_821';ROOTS=(PYROMANCER,SHADOW);DEPENDENCIES=();PREFIX='cards.simple_followup_p19.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P19 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or data['evidence_only']or data['skipped']):raise TargetValidationError('Unreviewed P19 root/dependency set')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P19 original row')
    return data

def register_simple_followup_p19_cards(registry):
    data=load_batch()
    def pyromancer(c):
        if not living_source(c)or c.event is None or c.event.kind!='card_shattered'or c.event.player_id!=c.player_id:return()
        return(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)for i in minions(c,registry,3-c.player_id))),)
    def shadow(c):
        result=c.health_result
        if result is None:raise ResolutionError('Wilted Shadow requires its original settled health result')
        if(not living_source(c)or result.flow!=HealthFlow.HEALING.value or result.healed<=0 or
           result.source_controller!=c.player_id or result.target_controller==c.player_id):return()
        target=c.state.entities.get(result.target_id)
        if(target is None or not target.active or target.health<=0 or target.doomed or
           (target.zone_epoch,target.entered_order)!=(result.target_zone_epoch,result.target_entered_order)or
           target.zone not in(Zone.HERO,Zone.BOARD)or target.kind not in(CardType.HERO,CardType.MINION)):return()
        defender=BoardPresenceReference.capture(c.state,target.id)if target.kind==CardType.MINION else target.id
        return(ForceAttack(BoardPresenceReference.capture(c.state,c.source_id),defender),)
    registry.register_behavior(PREFIX+'pyromancer',pyromancer);registry.register_behavior(PREFIX+'shadow',shadow)
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION':raise TargetValidationError('P19 consumers require complete minion faces')
        kwargs={'triggers':(TriggerSpec('card_shattered'if cid==PYROMANCER else'health_resolved',PREFIX+('pyromancer'if cid==PYROMANCER else'shadow')),)}
        if cid==SHADOW:
            if raw['tags'].get('LIFESTEAL')!=1:raise TargetValidationError('Wilted Shadow lost its printed Lifesteal')
            kwargs['keywords']=(Keyword.LIFESTEAL,)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
