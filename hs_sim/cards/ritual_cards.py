"""Two real two-start rituals reuse native ongoing effects, draws and summons."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword, PlayerEffectSpec, SpellSchool
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup, DrawGroupSlot, DrawGroupReward
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.rituals import from_expiry
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DRAW='BE_005'; SUMMON='BE_085'; TOKEN='BE_085t'; ROOTS=(DRAW,SUMMON)
P='cards.rituals.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/rituals-v1.json'
BATCH_HASH='d4663caf692307c332772bbc9e9f0c99cd238ae41962c23b23d8ed400723f73e'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=(TOKEN,)or
            any(d[k]for k in('existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']+d['dependencies'])):
        raise TargetValidationError('Rituals require all three complete original reviewed faces')
    return d


def register_ritual_cards(registry):
    d=load_batch()
    def draw(c):
        from_expiry(c)
        return(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*2,DrawGroupReward('cost_all',2)),)
    def summon(c):
        from_expiry(c);cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN),),cause)for _ in range(2))
    for cid,body,cost,rarity in((DRAW,draw,3,4),(SUMMON,summon,2,1)):
        raw=next(x['record']for x in d['cards']if x['record']['id']==cid)
        if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('RARITY'),
                raw['tags'].get('SPELL_SCHOOL'),raw['tags'].get('OBJECTIVE'),raw['tags'].get('OBJECTIVE_COUNTDOWN'),
                raw['tags'].get('QUEST_PROGRESS_TOTAL'),raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'))!=('SPELL',cost,9,rarity,6,1,1,2,2):
            raise TargetValidationError('Ritual lost its real Shadow Warlock two-turn objective')
        program=P+cid;expiry=program+'.expire';registry.register_behavior(expiry,body)
        registry.register_player_effect(PlayerEffectSpec(program,cid,kind='ritual',duration=2,
            tick_event='turn_started',on_expire=expiry))
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=cost,spell_school=SpellSchool.SHADOW,
            ongoing_effect_id=program,metadata=metadata_from_record(raw))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    raw=d['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('TAUNT'))!=('MINION',4,3,5,False,1):
        raise TargetValidationError('Summoning Ritual requires its full actual 3/5 Taunt Cthraxxi')
    card=CardDefinition(TOKEN,raw['name'],CardType.MINION,cost=4,attack=3,health=5,
        keywords=(Keyword.TAUNT,),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
