"""Native Kindred components, prepared original rewards and real Challenger."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier,Buff,CopyMinion,Damage,DamageBatch,Destroy,Draw,RandomDestroy
from hs_sim.engine.kindred import current_source,repeat_components
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,KindredProfile,Keyword,PlayerEffectSpec,SpellSchool
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.stored_spell_damage import DrawMatchingSpellDamage
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import DiscardMatching,DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/kindred-component-effects-v1.json'
BATCH_HASH='70501f2526277a4ec198b7c3f5390479aecbbba304b34087eaebf5f781363e61'
PREFIX='cards.kindred_components.'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(d)!=BATCH_HASH:raise TargetValidationError('Native Kindred component source pin changed')
    return d


def register_kindred_component_cards(registry):
    def copy(c):
        source=current_source(c)
        if source is None:return()
        from hs_sim.engine.model import BoardPresenceReference
        return(CopyMinion(BoardPresenceReference.capture(c.state,source.id),c.player_id,cause=SummonCause.capture(c)),)
    def firegill(c):
        return tuple(GrantCapturedKeyword(MinionReference.capture(c.state.entities[i]),Keyword.RUSH,c.source_id)
            for i in minions(c,registry,c.player_id)if i!=c.source_id)
    def thief(c):
        item=SummonByCard(c.player_id,(SummonEntryMaterial('TLC_429t'),),SummonCause.capture(c))
        return item,item
    def immune(c):
        source=current_source(c)
        return(GrantCapturedKeyword(MinionReference.capture(source),Keyword.IMMUNE,c.source_id,c.state.turn),)if source is not None else()
    def diabolus(c):
        # Endpoints are physical board positions, including a dormant Minion.
        # The public damage layer decides whether that endpoint can take damage.
        ids=tuple(i for i in c.state.players[3-c.player_id].board if c.state.entities[i].kind==CardType.MINION
            and registry.card(c.state.entities[i].card_id).interactable is None)
        return(DamageBatch(tuple(Damage(i,6,c.source_id,DamageKind.MINION_ABILITY)for i in(ids[0],ids[-1]))),)if ids else()
    def kodo(c,high):
        ids=minions(c,registry,3-c.player_id)
        if not ids:return()
        value=(max if high else min)(c.state.entities[i].attack for i in ids)
        return(RandomDestroy(tuple(i for i in ids if c.state.entities[i].attack==value),c.source_id),)
    def thrasher(c):
        query=PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.FIRE,))
        return(DrawMatchingSpellDamage(c.player_id,query,c.source_id,2,c.kindred.repetitions),)if c.kindred.condition.matched else(
            DrawMatching(c.player_id,query,'skip',source_id=c.source_id),)
    def hybrid(c):
        reward=DrawGroupReward('cost_all',1,c.kindred.repetitions)if c.kindred.condition.matched else DrawGroupReward()
        slots=tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)),current_cost=n)for n in(1,2,3,4))
        return(DrawPhysicalGroup(c.player_id,c.source_id,slots,reward),)
    def glider(c):
        matched=c.kindred.condition.matched
        return(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.MINION,)),uses_remaining=1,
            source_id=c.source_id,tribes_any=('murloc',),minion_keyword=Keyword.DIVINE_SHIELD if matched else None,
            minion_keyword_repetitions=c.kindred.repetitions if matched else 1),)
    def cryo(c):
        return(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),Draw(c.player_id,1,c.source_id),
            *((Draw(c.player_id,1,c.source_id),)*c.kindred.repetitions if c.kindred.condition.matched else()))
    def ablating(c):return(Destroy(c.target_id,c.source_id),*repeat_components(c))
    def wave(c):
        return(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)for p in(1,2)for i in minions(c,registry,p))),)
    bodies={
        'DINO_138.active':diabolus,'DINO_404.active':firegill,'DINO_435.active':copy,
        'TLC_226.active':copy,'TLC_243.active':immune,'TLC_429.active':thief,
        'TLC_903.active':lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=5,source_id=c.source_id,expires_turn=c.state.turn),),
        'TLC_223.prepare':thrasher,'TLC_236.prepare':hybrid,'TLC_428.prepare':glider,'TLC_440.prepare':cryo,
        'TLC_447.prepare':ablating,'TLC_447.active':wave,
        'TLC_454.active':lambda c:kodo(c,True),'TLC_454.inactive':lambda c:kodo(c,False),
        'TLC_463.active':lambda c:(DiscardMatching(3-c.player_id,source_id=c.source_id),),
        'TLC_463.inactive':lambda c:(DiscardMatching(c.player_id,source_id=c.source_id),),
        'challenger':lambda c:(AddPlayerEffect(c.player_id,PREFIX+'next',c.source_id),)}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    d=load_batch()
    if len(d['cards'])!=1 or d['cards'][0]['record']['id']!='TLC_251'or len(d['reviewed_consumers'])!=17:
        raise TargetValidationError('Unreviewed native Kindred family')
    row=d['cards'][0];raw=row['record']
    if canonical_digest(raw)!=row['record_sha256']or(raw['cost'],raw['attack'],raw['health'],raw['type'])!=(3,3,2,'MINION'):
        raise TargetValidationError('Incomplete Primalfin Challenger face')
    card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=3,attack=3,health=2,battlecry=PREFIX+'challenger',
        metadata=replace(metadata_from_record(raw),deck_identity=raw['id']))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'next','TLC_251',kind='next_kindred'))
    for row in d['reviewed_consumers']:
        if canonical_digest(row['record'])!=row['record_sha256']or row['record']['tags'].get('KINDRED')!=1:
            raise TargetValidationError('Incomplete reviewed Kindred consumer')
        registry.register_kindred_profile(KindredProfile(**row['profile']))
