"""Timethief and Giant reuse the complete existing P70 native companions."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.deck_size_rules import DeckSizeRule
from hs_sim.engine.effects import Destroy
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import CardDefinition, CardType, Keyword, PlayerPlayedClassCostSpec
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.rafaams import ROOT, MEMBERS, FAMILY, GIANT, SHEEP, PROFILE
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BEHAVIOR = 'cards.timethief_rafaam.complete'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/timethief-rafaam-v1.json'
BATCH_HASH = 'be2ab36345891823af9352d8b38b62195c5576c06a04000b1483cdbed1c60d9a'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=(*data['cards'],*data['dependencies'],*data['existing_dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(i['record']['id']for i in data['cards'])!=(ROOT,) or
            tuple(i['record']['id']for i in data['dependencies'])!=(GIANT,) or
            {i['record']['id']for i in rows}!=set(FAMILY) or data['evidence_only'] or
            any(canonical_digest(i['record'])!=i['record_sha256']for i in rows) or
            tuple(data['fabled_companion_ids'])!=MEMBERS or tuple(data['rafaam_family_ids'])!=FAMILY or
            any(i['record']['tags'].get('3928')!=1 for i in rows)):
        raise TargetValidationError('Rafaam requires the complete original Fabled bundle and separately tagged Sheep')
    return data


def register_timethief_rafaam_cards(registry):
    data=load_batch()
    for item in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(item['record']['id'])))!=item['definition_sha256']:
            raise TargetValidationError('Existing complete Rafaam companion changed')
    def complete(c):
        used={p.played_face.card_id for p in played_cards(c.state,c.player_id)}
        return (Destroy(c.state.players[3-c.player_id].hero_id,c.source_id),)if set(MEMBERS)<=used else ()
    registry.register_behavior(BEHAVIOR,complete)
    for item in (*data['cards'],*data['dependencies']):
        raw=item['record'];cid=raw['id'];meta=metadata_from_record(raw)
        if canonical_digest(asdict(meta))!=canonical_digest(item['metadata']):raise TargetValidationError('Rafaam metadata drift')
        kwargs=dict(battlecry=BEHAVIOR)if cid==ROOT else dict(keywords=(Keyword.RUSH,),
            player_played_class_cost=PlayerPlayedClassCostSpec(None,PROFILE))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=meta,**kwargs)
        registry.register_card(card)
        member=PoolCard.from_definition(card)
        if cid in registry.pool_cards:
            if registry.pool_cards[cid]!=member:raise TargetValidationError('Rafaam changed an existing full pool record')
        else:registry.register_pool_card(member)
    registry.register_fabled(FabledSpec(ROOT,MEMBERS))
    registry.register_deck_size_rule(DeckSizeRule(ROOT,40))
