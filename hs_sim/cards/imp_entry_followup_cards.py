"""Actual Imp-formant top placement and source-independent entry rewards."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.successful_summons import BuffSummonedMinion
from hs_sim.engine.zones import PutMatchingDeckMinionOnTop
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/imp-entry-followup-effects-v1.json'
BATCH_HASH='bf90a30399e9bb34cbad7effaed70eba06a1382d3b9bd5f6375facd49032af48'
PREFIX='cards.imp_entry_followups.'
IMP='CAP_400t2t'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Imp-entry followups lost their complete reviewed source pin')
    return data


def original_imp_summon(c):
    if c.event is None or c.event.kind!='minion_summoned':
        raise ResolutionError('Imp-formant reward requires an original successful entry event')
    if c.event.player_id!=c.player_id:return None
    rows=[x for x in c.state.successful_summon_history if x.event_sequence==c.event.sequence]
    if len(rows)!=1:raise ResolutionError('Imp-formant reward lost its original successful entry')
    row=rows[0]
    if(row.entity_id,row.player_id)!=(c.event.target_id,c.event.player_id):
        raise ResolutionError('Imp-formant reward changed its original recipient')
    return row if row.card_id==IMP else None


def register_imp_entry_followup_cards(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record']
        if(raw['id']!=IMP or canonical_digest(raw)!=row['record_sha256']or
                canonical_digest(asdict(registry.card(IMP)))!=row['definition_sha256']):
            raise TargetValidationError('Imp-entry reward lost its complete existing dependency')
    def reward(c):
        row=original_imp_summon(c)
        return(BuffSummonedMinion(c.player_id,row.id,c.source_id,2,2),)if row is not None else()
    registry.register_behavior(PREFIX+'constable',lambda c:(PutMatchingDeckMinionOnTop(3-c.player_id,(IMP,),c.source_id,2,2),))
    registry.register_behavior(PREFIX+'mastermind',lambda c:(AddPlayerEffect(c.player_id,PREFIX+'mastermind',c.source_id),))
    registry.register_behavior(PREFIX+'reward',reward)
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'mastermind','CAP_406',
        triggers=(TriggerSpec('minion_summoned',PREFIX+'reward'),)))
    if[(x['record']['id'],x['recipe']['script'])for x in data['cards']]!=[('CAP_401','constable'),('CAP_406','mastermind')]:
        raise TargetValidationError('Unreviewed Imp-entry root identities')
    for row in data['enchantment_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Imp reward raw evidence changed')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('BATTLECRY')!=1:
            raise TargetValidationError('Unreviewed complete Imp-entry minion face')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            battlecry=PREFIX+recipe['script'],keywords=(Keyword.TAUNT,)if cid=='CAP_406'else(),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
