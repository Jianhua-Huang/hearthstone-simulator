"""Finite current-stat selection, held-minion buffs and original draw conditions."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import Buff, GrantKeyword, InvokeBehavior, SetStats
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import (CardDefinition, CardType, Keyword, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_sequences import DrawIfCheap
from hs_sim.engine.spell_targets import RandomSpellTarget
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/stat-draw-effects-v1.json'
BATCH_HASH = '54929307929dcd5ee35dbcedd1dcb4cefa9029cf781312131548e2712c91be08'
PREFIX = 'cards.stat_draw.'
SCRIPTS = {'CORE_EX1_619':'equality', 'CORE_RLK_087':'asphyxiate', 'EDR_255':'flames',
           'TIME_447':'barrier', 'TIME_449':'legacy', 'JAIL_377':'bola', 'END_003':'finality'}
HAND = MinionScope(zones=(Zone.HAND,))


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Stat/draw cards differ from their reviewed complete source pin')
    return data


def register_stat_draw_cards(registry):
    def invoke(c, name):
        return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
                              None if c.play is None else c.play.id)

    def asphyxiate(c):
        ids=minions(c,registry,3-c.player_id)
        if not ids: return ()
        highest=max(c.state.entities[eid].attack for eid in ids)
        refs=tuple(MinionReference.capture(c.state.entities[eid]) for eid in ids
                   if c.state.entities[eid].attack == highest)
        return (RandomSpellTarget(refs,c.source_id,'destroy'),)

    def flames_hit(c):
        ids=characters(c,registry,3-c.player_id)
        if not ids:return ()
        lowest=min(c.state.entities[eid].health for eid in ids)
        refs=tuple(MinionReference.capture(c.state.entities[eid]) if c.state.entities[eid].kind == CardType.MINION
                   else eid for eid in ids if c.state.entities[eid].health == lowest)
        return (RandomSpellTarget(refs,c.source_id,'damage',5),)

    def legacy_hand(c):
        if any(c.state.entities[eid].kind == CardType.MINION for eid in c.state.players[c.player_id].deck):
            return ()
        return (BuffMinionsInZones(c.player_id,attack=4,scope=HAND,source_id=c.source_id),)

    bodies={
        'equality':lambda c:tuple(SetStats(eid,health=1,source_id=c.source_id)
            for pid in (1,2) for eid in minions(c,registry,pid)),
        'asphyxiate':asphyxiate,
        'flames':lambda c:(invoke(c,'flames_hit'),invoke(c,'flames_hit')),
        'flames_hit':flames_hit,
        'barrier':lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),
            BuffMinionsInZones(c.player_id,health=2,scope=HAND,source_id=c.source_id)),
        'legacy':lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=4,source_id=c.source_id,
            expires_turn=c.state.turn),invoke(c,'legacy_hand')),
        'legacy_hand':legacy_hand,
        'bola':lambda c:(DrawIfCheap(c.player_id,2,c.source_id),),
        'finality':lambda c:(DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,),tribes_any=('undead',)),
            'skip',selection='random',source_id=c.source_id),Imbue(c.player_id,c.source_id,count=2)),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if (canonical_digest(raw) != row['record_sha256'] or SCRIPTS.get(raw['id']) != recipe['script']
                or raw['type'] != 'SPELL' or not raw['collectible'] or raw['cost'] != recipe['cost']):
            raise TargetValidationError('Stat/draw card lost its reviewed complete source face')
        kwargs={}
        if recipe['target'] == 'character':
            kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),
                kinds=(CardType.HERO,CardType.MINION))
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=recipe['cost'],
            keywords=tuple(Keyword(value) for value in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),
            on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
