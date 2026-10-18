"""Original hero attack class buffs and successful after-cast companions."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardDefinition,CardType,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .fixed_companion_cards import companion_effects,load_batch as companion_batch
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p14-v1.json'
BATCH_HASH='d5b968462d2cc12daba8354f27744d158d63f29f5f190ea81ce5ea3c5f58804c'
HAMMER='JAIL_329';BROLL='EDR_853';FRAGMENT='END_026';ROOTS=(HAMMER,BROLL)
COMPANIONS=('NEW1_034','NEW1_033','NEW1_032');PREFIX='cards.simple_followup_p14.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P14 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['skipped'])!=(FRAGMENT,)or
       {x['record']['id']for x in data['existing_dependencies']}!=set(COMPANIONS)or tuple(data['companion_order'])!=COMPANIONS or
       data['dependencies']or data['evidence_only']):raise TargetValidationError('Unreviewed P14 roots/dependencies')
    for row in data['cards']+data['skipped']+data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P14 original row')
    return data

def register_simple_followup_p14_cards(registry):
    data=load_batch();fixed={x['record']['id']:x['record']for x in companion_batch()['cards']}
    for row in data['existing_dependencies']:
        raw=row['record'];card=registry.card(raw['id'])
        if raw!=fixed.get(raw['id'])or card.kind!=CardType.MINION or card.metadata!=replace(metadata_from_record(raw),deck_identity=raw['id']):
            raise TargetValidationError('P14 lost an existing complete companion')
    def hammer(c):
        attack=completed_attack(c)
        if(attack is None or attack.source_kind!=CardType.HERO or attack.declaration.player_id!=c.player_id or
           attack.combat.weapon_id!=c.source_id):return ()
        selected=[]
        for eid in minions(c,registry,c.player_id):
            e=c.state.entities[eid];meta=registry.card(e.card_id).metadata
            if meta is None or meta.classes is None:raise UnsupportedDefinitionError('Truth Seeker current minion class is unknown')
            if CardClass.PALADIN in meta.classes:selected.append(MinionReference.capture(e))
        return tuple(BuffCapturedMinion(ref,2,2,c.source_id)for ref in selected)
    def broll(c):
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):
            raise ResolutionError('Broll lost its original completed spell linkage')
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:
            raise ResolutionError('Broll requires an actual successful spell completion')
        if cast.player_id!=c.player_id or not living_source(c):return ()
        return companion_effects(c,registry)
    registry.register_behavior(PREFIX+'hammer',hammer);registry.register_behavior(PREFIX+'broll',broll)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if raw['collectible']is not True:raise TargetValidationError('P14 requires complete collectible roots')
        if cid==HAMMER:kwargs.update(durability=raw['health'],triggers=(TriggerSpec('attack_finished',PREFIX+'hammer'),))
        else:kwargs.update(health=raw['health'],triggers=(TriggerSpec('spell_cast_finished',PREFIX+'broll'),))
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],attack=raw['attack'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
