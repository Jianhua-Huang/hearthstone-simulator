"""Eldritch Being uses the existing native Outcast and Spellburst entries."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_order import ShuffleHand
from hs_sim.engine.model import CardDefinition, CardType, Keyword, LimitedTriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


CARD = 'GDB_116'
LEAVES = DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_hand_shuffle.'
OUTCAST = PREFIX+'outcast'
SHUFFLE = PREFIX+'shuffle'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-hand-shuffle-v1.json'
BATCH_HASH = '8bc0627c777667394ebf8516a3ab5f1bc4acd6f66a60b8199faf1cbad9e8ce67'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(d['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in d['dependencies']) != LEAVES or
            any(d[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in d['dependencies'])):
        raise TargetValidationError('Eldritch Being lost its complete native source and hand-order policy')
    return d


def register_past_hand_shuffle_card(registry):
    raw = load_batch()['dependencies'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible']) != ('MINION', 1, 1, 3, True) or
            raw['tags'].get('OUTCAST') != 1 or raw['tags'].get('SPELLBURST') != 1):
        raise TargetValidationError('Eldritch Being requires both actual printed native entries')

    def outcast(c):
        if c.spell_conditions is None:
            raise ResolutionError('Eldritch Being requires its original accepted hand-position conditions')
        return (ShuffleHand(c.player_id, c.source_id),) if c.spell_conditions.outcast else ()

    registry.register_behavior(OUTCAST, outcast)
    registry.register_behavior(SHUFFLE, lambda c: (ShuffleHand(c.player_id, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=1, attack=1, health=3,
        keywords=(Keyword.OUTCAST, Keyword.SPELLBURST), on_play=OUTCAST,
        limited_triggers=(LimitedTriggerSpec.spellburst(SHUFFLE),), metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
