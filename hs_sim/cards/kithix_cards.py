"""Kithix starts a real Sinful Ritual after a genuine prior ritual completion."""
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import AddToHand, ChoiceOption, RequestChoice
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, PlayerEffectSpec, Rarity, SpellSchool
from hs_sim.engine.named_summon_followups import original_pool_delivery
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.rituals import completed_rituals, from_expiry
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_090'; RITUALS=('BE_090t1','BE_090t2','BE_090t3'); P='cards.kithix.'
COPY=P+'original_copy'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/kithix-v1.json'
BATCH_HASH='6b2cc659046e5cffa1592e45ca23775c05314a7ce732637467d265f946877a83'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in d['dependencies'])!=RITUALS or
            tuple(x['record']['id']for x in d['evidence_only'])!=('BE_090e1','BE_090e2')or
            any(d[k]for k in('existing_dependencies','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']+d['dependencies']+d['evidence_only'])):
        raise TargetValidationError('Kithix requires complete root, three actual choices and original enchantment evidence')
    return d


def register_kithix_cards(registry):
    d=load_batch();raw=d['cards'][0]['record'];choices={x['record']['id']:x['record']for x in d['dependencies']}
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'))!=('MINION',6,6,6,9,5,1):
        raise TargetValidationError('Kithix lost its actual Warlock legendary 6-cost 6/6 Battlecry')
    def choose(c):
        if not completed_rituals(c.state,c.player_id):return()
        return(RequestChoice(c.player_id,tuple(ChoiceOption(cid,choices[cid]['name'],
            (AddPlayerEffect(c.player_id,P+cid,c.source_id),),card_id=cid)for cid in RITUALS),c.source_id),)
    def famine(c):
        from_expiry(c)
        return(DrawMatching(c.player_id,PoolQuery(),'fatigue',count=5,selection='first',
            source_id=c.source_id,owner_id=3-c.player_id),)
    def dominance(c):
        from_expiry(c);cause=SummonCause.capture(c)
        return tuple(SummonFromPool(c.player_id,'constructed.cards',
            PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,)),
            source_id=c.source_id,cause=cause,on_summon=COPY,followup_policy='original_delivery')for _ in range(3))
    def conquest(c):
        from_expiry(c)
        return(BuffMinionsInZones(c.player_id,6,6,MinionScope(),c.source_id),)
    def copy(c):
        original=original_pool_delivery(c)
        return(AddToHand(c.player_id,original.card_id,c.source_id,cost=CostSpec(set_to=1)),)
    registry.register_behavior(P+'choose',choose);registry.register_behavior(COPY,copy)
    for cid,body in zip(RITUALS,(famine,dominance,conquest)):
        record=choices[cid]
        if(record['type'],record['collectible'],record['tags'].get('OBJECTIVE_COUNTDOWN'),
                record['tags'].get('TAG_SCRIPT_DATA_NUM_1'),record['tags'].get('QUEST_PROGRESS_TOTAL'))!=('SPELL',False,1,2,2):
            raise TargetValidationError('Sinful Ritual lost its complete actual two-start spell face')
        callback=P+cid+'.expire';registry.register_behavior(callback,body)
        registry.register_player_effect(PlayerEffectSpec(P+cid,cid,kind='ritual',duration=2,
            tick_event='turn_started',on_expire=callback))
        card=CardDefinition(cid,record['name'],CardType.SPELL,cost=record['cost'],choice_only=True,
            spell_school=SpellSchool.SHADOW,metadata=metadata_from_record(record))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=6,attack=6,health=6,
        battlecry=P+'choose',metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
