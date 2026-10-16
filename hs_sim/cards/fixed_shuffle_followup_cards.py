"""Complete fixed shuffles reusing original taxes and physical drawn minions."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,HandProgressSpec,Keyword,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .next_play_price_cards import PREFIX as PRICE_PREFIX
from .recruit_cards import PREFIX as RECRUIT_PREFIX,shuffle

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/fixed-shuffle-followup-effects-v1.json'
BATCH_HASH='e4c7d0e5da98b9b4dc47984dfcb490988d74ceab3b8faf61aee1ec95afd1370b'
PREFIX='cards.fixed_shuffle_followups.'
IMP='CAP_400t2t'
NINJA='TLC_513t2'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Fixed shuffle followups lost their complete reviewed source pin')
    return data


def register_fixed_shuffle_followup_cards(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        raw=row['record']
        if(raw['id']!=IMP or canonical_digest(raw)!=row['record_sha256']or
                canonical_digest(asdict(registry.card(IMP)))!=row['definition_sha256']):
            raise TargetValidationError('Fixed shuffle source lost its complete Imp-formant dependency')
    rows=data['cards']
    if[(x['record']['id'],x['recipe']['script'])for x in rows]!=[
            ('CAP_404','harsh'),('TLC_518','interrogation'),(NINJA,'drawn_ninja')]:
        raise TargetValidationError('Unreviewed fixed shuffle identities')
    registry.register_behavior(PREFIX+'harsh',lambda c:(
        AddPlayerEffect(3-c.player_id,PREFIX+'pending_harsh',c.source_id),*shuffle(c,IMP,2,True)))
    registry.register_behavior(PREFIX+'interrogation',lambda c:shuffle(c,NINJA,3))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'pending_harsh','CAP_404',
        triggers=(TriggerSpec('turn_started',PRICE_PREFIX+'activate_tar'),)))
    for row in rows:
        raw,recipe=row['record'],row['recipe'];cid=raw['id']
        if(canonical_digest(raw)!=row['record_sha256']or raw['collectible']!=recipe['root']or
                type(raw['cost'])is not int or raw['cost']<0 or raw['tags'].get('SPELL_SCHOOL')is not None):
            raise TargetValidationError('Unreviewed fixed shuffle face')
        kwargs={}
        if cid==NINJA:
            if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('STEALTH'))!=('MINION',3,3,3,1):
                raise TargetValidationError('Unreviewed complete Tortollan Ninja')
            kwargs.update(keywords=(Keyword.STEALTH,),hand_progress=HandProgressSpec('event',
                event='card_drawn',condition_id=RECRUIT_PREFIX+'physical_draw',
                on_complete=RECRUIT_PREFIX+'draw_drawer',repeat=True))
        else:
            if raw['type']!='SPELL':raise TargetValidationError('Fixed shuffle root must be a spell')
            kwargs['on_play']=PREFIX+recipe['script']
        card=CardDefinition(cid,raw['name'],CardType[raw['type']],cost=raw['cost'],
            attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
