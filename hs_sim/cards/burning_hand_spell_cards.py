"""Two native Smoldering spells reuse held progress and physical self-discard."""
import json
from pathlib import Path

from hs_sim.engine.effects import Buff,Damage,DamageBatch
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HandProgressSpec,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

STRENGTH,ASCENT='FIR_914','FIR_916'
PREFIX='cards.burning_hand_spells.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/burning-hand-spell-cards-v1.json'
BATCH_HASH='923ad51a2d667f328688169aba7c2280344077c44adfd85c8906237f7c692bdd'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or [r['record']['id']for r in data['cards']]!=[STRENGTH,ASCENT]
            or [r['record']['id']for r in data['evidence_only']]!=['FIR_914e']
            or any(data[k]for k in('dependencies','existing_dependencies','skipped'))
            or any(canonical_digest(r['record'])!=r['record_sha256']for r in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Smoldering spells lost their complete original source')
    return data


def register_burning_hand_spell_cards(registry):
    registry.register_trigger_condition(PREFIX+'own_end',lambda c:c.event is not None and c.event.player_id==c.player_id)
    progress=HandProgressSpec('event',1,on_complete=PREFIX+'end',repeat=True,
                             event='turn_ended',condition_id=PREFIX+'own_end')
    def power(c):
        ability=progress_ability(c.source)
        if ability is None or ability.hand_progress!=progress:
            raise TargetValidationError('Smoldering spell lost its native physical growth')
        return 1+ability.progress_completions
    def strength(c):
        value=power(c)
        return (Buff(c.target_id,value,value,c.source_id),)
    def ascent(c):
        value=power(c)
        hits=tuple(Damage(i,value,c.source_id,DamageKind.SPELL)for i in c.state.players[3-c.player_id].board
                   if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active)
        return (DamageBatch(hits),)
    def end(c):
        if c.trigger is None or c.trigger.hand_progress!=progress:
            raise TargetValidationError('Smoldering end lost its actual completed progress')
        current=progress_ability(c.source)
        if (c.source.zone!=Zone.HAND or c.source.controller!=c.player_id or current is None
                or current.id!=c.trigger.id or current.progress_completions!=c.trigger.progress_completions):
            return ()
        return (DiscardCard(CardReference.capture(c.source),c.source_id),)if c.trigger.progress_completions>=3 else ()
    for name,body in (('strength',strength),('ascent',ascent),('end',end)):
        registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if (raw['type']!='SPELL' or raw['cost']!=(1 if cid==STRENGTH else 2)
                or (raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'),raw['tags'].get('TAG_SCRIPT_DATA_NUM_2'))!=(1,3)):
            raise TargetValidationError('Smoldering spell changed its original cost or counters')
        fields=dict(targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))if cid==STRENGTH else {}
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],
            on_play=PREFIX+('strength'if cid==STRENGTH else'ascent'),hand_progress=progress,
            spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']],metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
