"""Reviewed held-Dragon, actual Demon-entry and named Fel Beast recipes."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,HandActionSpec,
    HandProgressSpec,Keyword,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import apply_change,normalized
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/entry-native-effects-v1.json'
BATCH_HASH='e421ec4b4506e2151f6f3f86e35a0435dfecfaba37361ea8eadd44976ecc5cca'
PREFIX='cards.entry_native.'
FEL_BEASTS=('TLC_446t2','TLC_446t3','TLC_446t4')

def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Real entry recipes lost their complete reviewed source pin')
    return value

def submitted_tribes(record):
    if record.played_face is None or record.submitted_cost is None:raise ResolutionError('Held Dragon condition lost its original submitted face')
    meta=record.played_face.metadata
    tribes=None if meta is None or meta.tribes is None else normalized(meta.tribes)
    for enchantment in record.submitted_cost.quote.quote_input.enchantments:
        if enchantment.tribe_change is not None:tribes=apply_change(tribes,enchantment.tribe_change)
    if tribes is None:raise UnsupportedDefinitionError('Unknown original submitted Dragon tribes')
    return tribes

def scout_dragon(c):
    if c.event is None or c.event.kind!='card_committed':raise ResolutionError('Scout requires the original hand-play commitment')
    record=play_record(c.state,dict(c.event.data)['play_id'])
    if(record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):raise ResolutionError('Scout lost its original committed hand play')
    return(record.player_id==c.player_id and record.kind==CardType.MINION and record.source_id!=c.source_id
        and submitted_tribes(record).matches_any(('dragon',)))

def parasite(c):
    if c.event is None or c.event.kind!='minion_summoned':raise ResolutionError('Parasite requires its actual minion entry')
    if c.event.player_id!=c.player_id:return ()
    rows=[x for x in c.state.successful_summon_history if x.event_sequence==c.event.sequence]
    if len(rows)!=1:raise ResolutionError('Parasite lost its original successful summon occurrence')
    row=rows[0];fact=row.minion;target=c.state.entities[c.event.target_id]
    if(row.entity_id,row.player_id)!=(c.event.target_id,c.event.player_id)or(
        target.id,target.card_id,target.controller,target.zone_epoch,target.entered_order)!=(
        fact.entity_id,fact.card_id,fact.controller,fact.zone_epoch,fact.entered_order):
        raise ResolutionError('Parasite borrowed another physical entry or later residence')
    if row.tribes is None:raise UnsupportedDefinitionError('Unknown original Demon summon tribes')
    if not row.tribes.matches_any(('demon',)):return ()
    return(BuffCapturedMinion(MinionReference.capture(c.source),target.attack,target.max_health,c.source_id),)

def register_entry_native_cards(registry):
    data=load_batch();rows={x['record']['id']:x for x in data['cards']}
    if set(rows)!={'CATA_552','CATA_552t','JAIL_721','TLC_479',*FEL_BEASTS}or tuple(data['fel_beast_candidate_ids'])!=FEL_BEASTS:
        raise TargetValidationError('Unreviewed native-entry family')
    gallery={x['id']:x for x in data['gallery_links']}
    if(gallery[119789]['child_ids']!=[rows[cid]['record']['dbf_id']for cid in FEL_BEASTS]
            or gallery[122869]['child_ids']!=[rows['CATA_552t']['record']['dbf_id']]):
        raise TargetValidationError('Named family lost its complete explicit CN child links')
    registry.register_trigger_condition(PREFIX+'dragon',scout_dragon)
    registry.register_behavior(PREFIX+'scout',lambda c:(InvokeBehavior(PREFIX+'scout_now',c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),))
    registry.register_behavior(PREFIX+'scout_now',lambda c:(Damage(c.target_id,c.source.attack,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None else())
    registry.register_behavior(PREFIX+'parasite',parasite)
    def maw(c):
        board=c.state.players[c.player_id].board
        position=c.death.position if c.death is not None else board.index(c.source_id)+1 if c.source_id in board else None
        return(SummonByCard(c.player_id,tuple(SummonEntryMaterial(cid)for cid in FEL_BEASTS),SummonCause.capture(c),selection='random',position=position),)
    registry.register_behavior(PREFIX+'maw',maw)
    for cid,row in rows.items():
        raw,recipe=row['record'],row['recipe'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']!=recipe['root']:
            raise TargetValidationError('Unreviewed complete entry-native face')
        if cid in('CATA_552','CATA_552t'):
            kwargs.update(battlecry=PREFIX+'scout',targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))
            if cid=='CATA_552':kwargs['hand_progress']=HandProgressSpec('event',1,'CATA_552t',event='card_committed',condition_id=PREFIX+'dragon')
        elif cid=='JAIL_721':kwargs.update(triggers=(TriggerSpec('minion_summoned',PREFIX+'parasite'),),hand_actions=(HandActionSpec('prepare','prepare',1),))
        elif cid=='TLC_479':kwargs['deathrattle']=PREFIX+'maw'
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=tuple(Keyword(k)for k in recipe['keywords']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
