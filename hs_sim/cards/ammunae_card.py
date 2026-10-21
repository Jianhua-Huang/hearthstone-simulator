"""Ammunae copies a qualified original played residence through ordinary copy."""
import json
from pathlib import Path

from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .played_minion_keyword_cards import original_played_presence, played_minion

CARD='BE_852'
BODY='cards.ammunae.install'
COPY='cards.ammunae.copy_played'
PROGRAM='cards.ammunae.deathrattle_copies'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/ammunae-v1.json'
BATCH_HASH='064eeb8c3f7a14e1d4ad5bbb90dbecd8b48d6e7065b125e4d7b22a37a4332bce'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(row['record']['id']for row in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in data['cards'])):
        raise TargetValidationError('Ammunae lost its original complete reviewed face')
    return data


def register_ammunae_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'),raw['tags'].get('BATTLECRY'))!=('MINION',8,6,6,2,5,1):
        raise TargetValidationError('Ammunae requires its actual Druid legendary 8-cost 6/6 battlecry')
    def copy_played(c):
        row=played_minion(c,exclude_source=False)
        if row is None:return()
        if row.submitted_cost is None:raise ResolutionError('Ammunae lost original paid Deathrattle qualification')
        if not any(a.kind=='deathrattle'and not a.consumed for a in row.submitted_cost.quote.quote_input.abilities):return()
        presence=original_played_presence(c,row)
        return(CopyMinion(presence,c.player_id,cause=SummonCause.capture(c),allow_dormant=True),)if presence is not None else()
    registry.register_behavior(BODY,lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))
    registry.register_behavior(COPY,copy_played)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=8,attack=6,health=6,battlecry=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD,triggers=(TriggerSpec('card_played',COPY),)))
