"""P11 complete deck batches, original equipped reward and native death copies."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.costs import local_cost
from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.effects import Draw, ModifyWeapon
from hs_sim.engine.model import CardDefinition, CardType, SummonStats, TriggerSpec, Zone
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_sources import DeathQuery, death_candidates
from hs_sim.engine.zones import CardReference, CopyCard, DestroyDeckBatch
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack, living_source
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-native-p11-v1.json'
BATCH_HASH = '6db1b1ff8c0ca0b7bfe4653a38d130a795bf242da3bff62cc05e43dac03670a4'
BLACKHORN = 'CATA_720'
CINDERSWORD = 'FIR_922'
ESCAPE = 'JAIL_030'
CHARITY = 'MEND_805'
ROOTS = (BLACKHORN,CINDERSWORD,ESCAPE,CHARITY)
PREFIX = 'cards.simple_native_p11.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('P11 lost its complete reviewed source pin')
    if (tuple(x['record']['id']for x in data['cards'])!=ROOTS or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Unreviewed P11 roots or dependencies')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('P11 complete source row changed')
    return data


def register_simple_native_p11_cards(registry):
    data=load_batch()
    def blackhorn(c):
        targets=[]
        for pid in(1,2):
            for eid in c.state.players[pid].deck:
                entity=c.state.entities[eid];registry.card(entity.card_id)
                if local_cost(entity)[0]<=2:targets.append(CardReference.capture(entity))
        return(DestroyDeckBatch(tuple(targets),c.source_id),)
    def sword(c):
        source=c.source
        if (c.state.players[c.player_id].weapon_id!=c.source_id or source.zone!=Zone.WEAPON or
                not source.active or source.durability<=0 or source.doomed):return ()
        if not any(c.state.entities[i].kind==CardType.MINION and public_gifts(c.state.entities[i])
                   for i in c.state.players[c.player_id].hand):return ()
        return(ModifyWeapon(source.id,attack=3,source_id=c.source_id),)
    def escape(c):
        row=completed_attack(c)
        if (row is None or row.declaration.source_id!=c.source_id or row.source_kind!=CardType.MINION or
                not living_source(c) or (row.combat.source_zone_epoch,row.combat.source_entered_order,row.combat.source_card_id)!=
                (c.source.zone_epoch,c.source.entered_order,c.source.card_id)):return ()
        original=MinionReference.capture(c.source)
        return(Draw(c.player_id,source_id=c.source_id),RemoveFromGame((original,),c.source_id))
    def charity(c):
        rows=death_candidates(c.state,registry,c.player_id,
            DeathQuery(min_turn=c.state.turn,max_turn=c.state.turn),c.source_id)
        return tuple(CopyCard(row,c.player_id,mode='base',source_id=c.source_id,
            stats=SummonStats(row.base_attack+3,row.base_health+3))for row in rows)
    for name,body in(('blackhorn',blackhorn),('sword',sword),('escape',escape),('charity',charity)):
        registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True:raise TargetValidationError('P11 requires complete collectible roots')
        if cid==CHARITY:
            if 'SPELL_SCHOOL'in raw['tags']:raise TargetValidationError('Charity must retain its absent printed school')
            kwargs['on_play']=PREFIX+'charity'
        else:
            kwargs['attack']=raw['attack']
            if cid==CINDERSWORD:kwargs.update(durability=raw['health'],battlecry=PREFIX+'sword')
            else:
                kwargs['health']=raw['health']
                if cid==BLACKHORN:kwargs['battlecry']=PREFIX+'blackhorn'
                else:kwargs['triggers']=(TriggerSpec('attack_finished',PREFIX+'escape'),)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
