"""Original semantic histories and native removal/combat consumers."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.character_attacks import character_attacks,validate_history
from hs_sim.engine.effects import ChoiceOption,Damage,DamageBatch,InvokeBehavior,RequestChoice
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,
    TargetSpec,Zone)
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import DestroyCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p49-v1.json'
BATCH_HASH='a524f6fcca6901a2db674f05a69a53b8a3357f5bb5e5de33e06c0220ec33ca07'
DECIMATION='CATA_581';KNOCKBACK='TLC_517';SCULLERY='JAIL_200';DISCIPLE='TIME_EVENT_301'
WATCHMAN='JAIL_455';HOUND='JAIL_435';SABER='EDR_014'
ROOTS=(DECIMATION,SCULLERY,DISCIPLE,WATCHMAN)
SKIPPED=('JAIL_445','TIME_872','DINO_413','TLC_517','JAIL_435','EDR_014');PREFIX='cards.simple_followup_p49.';POOL_ID='constructed.cards'

def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS
            or tuple(x['record']['id']for x in d['skipped'])!=SKIPPED):raise TargetValidationError('P49 reviewed complete recipes changed')
    for row in d['cards']+d['skipped']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('P49 complete source row changed')
    return d

def sample(c,options,count,callback):
    return(RequestChoice(c.player_id,tuple(options),c.source_id,min_count=0,max_count=0,
        sample_size=min(count,len(options)),on_select=callback),)if options else()

def register_simple_followup_p49_cards(registry):
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']}
    def all_minions(c):return tuple(i for p in(1,2)for i in minions(c,registry,p))
    def decimation(c):
        ids=all_minions(c)
        count=sum(c.state.entities[i].kind==CardType.MINION for p in(1,2)for i in c.state.players[p].board)
        amount=raws[DECIMATION]['tags']['TAG_SCRIPT_DATA_NUM_1']+count
        return(DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.SPELL)for i in ids)),)
    def scullery(c):
        validate_history(c.state,registry)
        count=sum(row.source_kind==CardType.HERO for row in character_attacks(c.state,c.player_id))
        cost=raws[SCULLERY]['tags']['TAG_SCRIPT_DATA_NUM_1']+count
        return(GenerateFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=cost,max_cost=cost),count=2,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)
    def disciple(c):
        count=1+sum(e.kind==CardType.MINION and has_any_tribe(registry,e,('dragon',))
            for i in c.state.players[c.player_id].hand for e in(c.state.entities[i],))
        return tuple(InvokeBehavior(PREFIX+'destroy_one',c.source_id,c.player_id)for _ in range(count))
    def destroy_one(c):
        options=tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])),sort_keys=True),
            'Original minion')for i in all_minions(c)if i!=c.source_id)
        return sample(c,options,1,PREFIX+'destroy_selected')
    def destroy_selected(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:
            raise TargetValidationError('Disciple lost its original single sampled target')
        ref=MinionReference(**json.loads(c.choice.choice.options[0].id))
        if ref.entity_id==c.source_id:raise TargetValidationError('Disciple cannot destroy its own source')
        return(DestroyCapturedMinion(ref,c.source_id),)
    def watchman(c):
        return tuple(InvokeBehavior(PREFIX+'watch_wave',c.source_id,c.source.controller)for _ in range(2))
    def watch_wave(c):
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.MINION_ABILITY)
            for i in minions(c,registry,c.player_id)if i!=c.source_id)),)
    bodies={DECIMATION:decimation,SCULLERY:scullery,DISCIPLE:disciple,WATCHMAN:watchman,
        'destroy_one':destroy_one,'destroy_selected':destroy_selected,'watch_wave':watch_wave}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower())
        kwargs={'battlecry'if kind==CardType.MINION else'on_play':PREFIX+cid}
        if cid==WATCHMAN:kwargs['disguised']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
