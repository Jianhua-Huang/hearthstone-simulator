"""Four real1-Cost roots expressed through existing payment/target/zone effects."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.disguised import play_destination
from hs_sim.engine.effects import AddToHand,Buff,Overload
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/one-cost-basic-effects-v1.json'
BATCH_HASH='f61c4ced5073b2039ecea0167dc0921436bbfbce8017053e1839cb23706cf886'
PREFIX='cards.one_cost_basic.'
SCRIPTS={'CATA_130':'last_crystal','FIR_908':'chameleon','JAIL_452':'detective','TLC_820':'ecologist','TLC_813':'vines'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('One-Cost effects lost their complete reviewed source pin')
    return value


def last_crystal(c):
    if c.event is None or c.event.kind not in ('mana_spent','mana_consumed'):
        raise ResolutionError('Crystalspine Cub requires a real positive mana debit')
    if c.event.player_id!=c.player_id or c.event.amount<=0 or c.state.players[c.player_id].mana!=0 or not living_source(c):return ()
    return(BuffCapturedMinion(MinionReference.capture(c.source),1,1,c.source_id),)


def chameleon(c):
    if c.target_id is None or c.state.players[c.player_id].hero_power_uses_this_turn<=0:return ()
    ref=MinionReference.capture(c.state.entities[c.target_id])
    return(BuffCapturedMinion(ref,1,2,c.source_id),GrantCapturedKeyword(ref,Keyword.RUSH,c.source_id))


def vines(c):
    if c.target_id is None:return ()
    target=c.state.entities[c.target_id]
    if target.controller==c.player_id:return(BuffCapturedMinion(MinionReference.capture(target),health=2,source_id=c.source_id),)
    return(Buff(target.id,health=-2,source_id=c.source_id),)


def register_one_cost_basic_cards(registry):
    registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'power_used','v1'),
        lambda c:c.observation['players'][c.player_id-1]['hero_power_uses_this_turn']>0)
    def detective(c):
        side=play_destination(registry,c.play)if c.play is not None else c.source.controller
        return(Overload(side,2),)
    bodies={'last_crystal':last_crystal,'chameleon':chameleon,'detective':detective,
        'ecologist':lambda c:(AddToHand(c.player_id,'TLC_813',c.source_id),),'vines':vines}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    data=load_batch()
    for row in data['cards']+data['dependencies']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(cid)!=script or raw['cost']!=1:
            raise TargetValidationError('Unreviewed complete1-Cost face')
        kwargs={}
        if script=='last_crystal':kwargs['triggers']=tuple(TriggerSpec(event,PREFIX+script)for event in ('mana_spent','mana_consumed'))
        elif script=='chameleon':
            kwargs.update(battlecry=PREFIX+script,target_rule=PREFIX+'power_used',
                targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        elif script=='detective':kwargs.update(disguised=True,on_play=PREFIX+script)
        elif script=='ecologist':kwargs['deathrattle']=PREFIX+script
        else:kwargs.update(on_play=PREFIX+script,spell_school=SpellSchool.HOLY,
                targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        card=CardDefinition(cid,raw['name'],CardType[raw['type']],cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            keywords=tuple(Keyword(x)for x in recipe['keywords']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
