"""Azalina's original deck rule and ordinary opening-health/Battlecry effects."""
import json
from pathlib import Path
from hs_sim.engine.deck_size_rules import DeckSizeRule
from hs_sim.engine.effects import DrawToHandLimit,SetStats
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,OpeningHook
from hs_sim.engine.opening_deck_copies import SOURCE,COUNT
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD=SOURCE
BODY='cards.azalina.draw'
OPENING='cards.azalina.starting_health'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/azalina-original-deck-v1.json'
BATCH_HASH='66d94d18960954ed293d5044cc7d539193bab32f451d4624dc6340cbf3cf8c72'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in d['evidence_only'])!=('JAIL_430e1',)or
            any(d[k]for k in ('dependencies','existing_dependencies','skipped'))or
            (d['policy']['original_main'],d['policy']['opponent_copies'],d['policy']['starting_health'])!=(COUNT,COUNT,40)):
        raise TargetValidationError('Azalina requires her complete original face and copied-hint evidence')
    for row in (*d['cards'],*d['evidence_only']):
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Azalina complete source row changed')
    return d


def register_azalina_original_deck_card(registry):
    def health(c):
        opening=c.state.opening
        if opening is None or opening.stage!='dealing':raise ResolutionError('Azalina health requires genuine pre-deal construction')
        # A copied Azalina is an opening-hook source, but never a second
        # submitted construction rule or a recursive twenty-card producer.
        originals=opening.original_entities[c.player_id-1]
        if c.source_id not in originals:return ()
        if c.state.players[c.player_id].original_deck[originals.index(c.source_id)]!=CARD:
            raise ResolutionError('Azalina health lost her accepted original deck slot')
        return (SetStats(c.state.players[c.player_id].hero_id,health=40,source_id=c.source_id),)
    registry.register_behavior(BODY,lambda c:(DrawToHandLimit(c.player_id),))
    registry.register_behavior(OPENING,health)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('DECK_RULE_MOD_DECK_SIZE'))!=('MINION',7,7,7,COUNT):
        raise TargetValidationError('Azalina changed her reviewed native deck-size face')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=7,attack=7,health=7,battlecry=BODY,
        opening_hooks=(OpeningHook('before_deal',OPENING),),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_deck_size_rule(DeckSizeRule(CARD,COUNT))
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
