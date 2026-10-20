"""Broxigar's actual Fabled weapon, four portals and four printed Demons."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_generation import ShuffleGeneratedCopies
from hs_sim.engine.effects import Draw
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,OpeningHook,TriggerSpec
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.vanished_cards import (DisappearOriginalCard,ReappearOriginalCard,VanishedCardProfile)
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT='TIME_020';AXE='TIME_020t1'
PORTALS=('TIME_020t2','TIME_020t3','TIME_020t4','TIME_020t5')
DEMONS=('TIME_020t2t','TIME_020t3t','TIME_020t4t','TIME_020t5t')
PREFIX='cards.broxigar.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/broxigar-v1.json'
BATCH_HASH='990f97c9837474c60ae3cca66ee8ca48c7f50830cb0829cc66c5ec9a7d78cf91'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));items=(*data['cards'],*data['dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(i['record']['id']for i in data['cards'])!=(ROOT,) or
            {i['record']['id']for i in items}!={ROOT,AXE,*PORTALS,*DEMONS} or
            any(data[k]for k in('existing_dependencies','evidence_only')) or
            any(canonical_digest(i['record'])!=i['record_sha256']for i in items) or
            data['fabled_companion_ids']!=[PORTALS[0],AXE]):
        raise TargetValidationError('Broxigar requires its complete actual ten-face native chain')
    return data


def register_broxigar_cards(registry):
    registry.register_behavior(PREFIX+'disappear',lambda c:(DisappearOriginalCard(c.source_id,c.player_id,ROOT),))
    def last(c):
        if c.deathrattle is None:raise ValueError('Broxigar return requires its actual final Demon Deathrattle')
        return(ReappearOriginalCard(3-c.player_id,c.source_id,ROOT,c.deathrattle.id),)
    registry.register_behavior(PREFIX+'return',last)
    def portal(c,index):
        return(SummonByCard(3-c.player_id,(SummonEntryMaterial(DEMONS[index]),),SummonCause.capture(c)),)
    def follow(c,index):
        return(Draw(3-c.player_id,1),ShuffleGeneratedCopies(3-c.player_id,c.player_id,PORTALS[index+1],1,c.source_id))
    def axe(c):
        row=completed_attack(c)
        if row is None or row.source_kind!=CardType.HERO or row.combat.weapon_id!=c.source_id or row.combat.player_id!=c.player_id:
            return ()
        target=c.state.entities[row.delivery.target_id]
        if target.kind!=CardType.MINION:return ()
        causes=[target.death_cause]+[d.cause for d in c.state.death_history if d.entity_id==target.id]
        for cause in causes:
            result=None if cause is None else cause.health_result
            if (result is not None and cause.kind in('damage','poison')and result.damage_kind==DamageKind.COMBAT.value and
                    result.weapon_id==c.source_id and result.source_id==row.declaration.source_id and
                    result.original_target_id==row.delivery.target_id and
                    row.combat.event_cursor<result.batch_id<=row.terminal.event_cursor):
                return(DrawMatching(c.player_id,PoolQuery(card_ids=PORTALS),'skip',source_id=c.source_id),)
        return ()
    registry.register_behavior(PREFIX+'axe',axe)
    for index,cid in enumerate(PORTALS):registry.register_behavior(PREFIX+cid,lambda c,index=index:portal(c,index))
    for index,cid in enumerate(DEMONS[:-1]):registry.register_behavior(PREFIX+cid,lambda c,index=index:follow(c,index))
    for item in(*load_batch()['cards'],*load_batch()['dependencies']):
        raw=item['record'];cid=raw['id'];kind=CardType(raw['type'].lower());meta=metadata_from_record(raw)
        if canonical_digest(asdict(meta))!=canonical_digest(item['metadata']):raise TargetValidationError('Broxigar printed metadata drift')
        kwargs={}
        if cid==ROOT:kwargs=dict(keywords=(Keyword.CHARGE,),opening_hooks=(OpeningHook('before_deal',PREFIX+'disappear'),))
        elif cid==AXE:kwargs=dict(keywords=(Keyword.LIFESTEAL,),durability=raw['health'],triggers=(TriggerSpec('attack_finished',PREFIX+'axe'),))
        elif cid in PORTALS:kwargs=dict(on_play=PREFIX+cid,spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']])
        else:kwargs['deathrattle']=PREFIX+'return'if cid==DEMONS[-1]else PREFIX+cid
        cost=raw['cost']if raw['cost']is not None else item['numeric_normalizations']['cost']
        card=CardDefinition(cid,raw['name'],kind,cost=cost,attack=raw['attack']or 0,
            health=(raw['health']or 0)if kind==CardType.MINION else 0,metadata=meta,**kwargs)
        registry.register_card(card);member=PoolCard.from_definition(card)
        if cid in registry.pool_cards:
            if registry.pool_cards[cid]!=member:raise TargetValidationError('Broxigar changed an existing full pool member')
        else:registry.register_pool_card(member)
    registry.register_fabled(FabledSpec(ROOT,(PORTALS[0],AXE)))
    registry.register_vanished_card_profile(VanishedCardProfile(ROOT,PREFIX+'disappear',PREFIX+'return'))
