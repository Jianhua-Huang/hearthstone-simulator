"""Husk's actual once-per-grant Hero life, using existing fatal/resource APIs."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.effects import GrantDeathrattle
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_lethal_windows import RecoverHero
from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec,Resource,Zone
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.resource_operations import HERO_PROFILE,SpendUpToResource
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/hero-corpse-rescue-v1.json'
BATCH_HASH='66c096b7300f582f50e31e00b88662e0878c217c64aa250c063eb2e843260bdd'
HUSK='TIME_618';PREFIX='cards.hero_corpse_rescue.';LIFE=PREFIX+'life';MARKER=PREFIX+'eternal_life'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Hero corpse rescue complete source pin changed')
    return data


def original_life_markers(c):
    """Use the genuine natural death's complete old set, never a later grant."""
    ref=c.hero_lethal
    if (ref is None or c.death is None or c.death.zone!=Zone.HERO or
            c.event is None or c.event.kind!='hero_died'):
        raise UnsupportedDefinitionError('Eternal Life requires its actual natural Hero fatal episode')
    if (ref.hero_id,ref.player_id,ref.death_id)!=(c.source_id,c.player_id,c.death.id):
        raise ResolutionError('Eternal Life borrowed another physical Hero death')
    fact=allocation_from_payload(dict(c.event.data)['source_allocation'])
    if (fact.entity_id,fact.controller,fact.kind)!=(ref.hero_id,ref.player_id,CardType.HERO):
        raise ResolutionError('Eternal Life lost its original Hero death allocation')
    sources={a.source_id for a in c.death.abilities if a.kind=='deathrattle'and not a.consumed and
        a.behavior_id==LIFE and a.deathrattle_grant_card_id==HUSK}
    return tuple(e for e in c.state.players[c.player_id].player_effects if e.spec_id==MARKER and
        e.source_card_id==HUSK and e.source_id in sources and e.entered_order<fact.next_order)


def register_hero_corpse_rescue_cards(registry):
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(HUSK,)or tuple(x['record']['id']for x in data['evidence_only'])!=('TIME_618t','TIME_618e','TIME_618e2'):
        raise TargetValidationError('Unreviewed Hero life root or visual dependency set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete Hero corpse rescue raw row')
    visual=data['evidence_only'][0]['record']
    if visual['tags'].get('VISIBLE_PLAYER_ENCHANTMENT_CARD')!=1 or visual['tags'].get('HIDE_COST')!=1:
        raise TargetValidationError('Eternal Life must remain a real nonphysical player-effect display')
    def grant(c):
        return(GrantDeathrattle(c.state.players[c.player_id].hero_id,LIFE,c.source_id),AddPlayerEffect(c.player_id,MARKER,c.source_id))
    def life(c):
        markers=original_life_markers(c)
        return(*(RemovePlayerEffect(c.player_id,e.id)for e in markers),
            SpendUpToResource(c.player_id,Resource.CORPSES,20,c.source_id,PREFIX+'recover',HERO_PROFILE,c.hero_lethal))
    def recover(c):
        result=c.resource_result
        if (result is None or result.profile!=HERO_PROFILE or result.resource!=Resource.CORPSES or result.cap!=20 or
                result.player_id!=c.player_id or result.source_id!=c.source_id or result.hero_lethal_reference is None):
            raise ResolutionError('Eternal Life lost its exact committed Hero corpse result')
        return(RecoverHero(result.hero_lethal_reference,result.actual_amount),)if result.actual_amount else()
    for name,body in dict(grant=grant,life=life,recover=recover).items():registry.register_behavior(PREFIX+name,body)
    raw=data['cards'][0]['record'];metadata=replace(metadata_from_record(raw),deck_identity=HUSK)
    card=CardDefinition(HUSK,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata,battlecry=PREFIX+'grant')
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    # A known physical source face exposes the actual public effect without
    # inventing a playable Eternal Life spell or another source entity.
    registry.register_player_effect(PlayerEffectSpec(MARKER,HUSK))
