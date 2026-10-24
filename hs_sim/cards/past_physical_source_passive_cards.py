"""Historical physical deck and native owner-turn hand sources."""
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import TransformDefiningHandCardFromPool
from hs_sim.engine.defining_hand_copies import TransformDefiningHandCardFromHand
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, Zone
from hs_sim.engine.play_history import play_record, matches_play_tribes
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PATCHES, CHAMELEOS, ZERUS = 'CFM_637', 'GIL_142', 'OG_123'
DEPENDENCIES = (PATCHES, CHAMELEOS, ZERUS)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_physical_source.'
POOL_ID = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-physical-source-passives-v1.json'
BATCH_HASH = '3feb6adfab52d746b8c9d54f851238fc0492d2376e1db1a3e020455df0edc02c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Physical source passives lost their complete reviewed raw faces')
    return data


def register_past_physical_source_passive_cards(registry):
    def pirate(c):
        if c.event is None or c.event.kind != 'card_played':
            return False
        play = play_record(c.state, dict(c.event.data)['play_id'])
        if not play.completed or (play.source_id, play.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Patches requires its original completed physical play')
        return (play.player_id == c.player_id and play.kind == CardType.MINION and
            matches_play_tribes(registry, play, ('pirate',)))

    def patches(c):
        return (SummonStoredCard(CardReference.capture(c.source), c.player_id,
            cause=SummonCause.capture(c)),)

    def shift(c):
        source = c.trigger
        if source is None or source.kind != 'defining_hand_source':
            raise ResolutionError('Hand shifter requires its original native source')
        ref = CardReference.capture(c.source)
        if source.defining_card_id == ZERUS:
            return (TransformDefiningHandCardFromPool(ref, ZERUS, source.id, POOL_ID,
                query=PoolQuery(kinds=(CardType.MINION,), collectible=True)),)
        if source.defining_card_id == CHAMELEOS:
            return (TransformDefiningHandCardFromHand(ref, CHAMELEOS, source.id),)
        raise ResolutionError('Unknown original hand shifter')

    registry.register_trigger_condition(PREFIX+'pirate', pirate)
    registry.register_behavior(PREFIX+'patches', patches)
    registry.register_behavior(PREFIX+'shift', shift)
    for item in load_batch()['dependencies']:
        raw = item['record']; cid = raw['id']
        if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health']) != ('MINION', True, 1, 1, 1):
            raise TargetValidationError('Physical source passive printed body changed')
        if cid == PATCHES:
            fields = dict(hand_progress=HandProgressSpec('event', on_complete=PREFIX+'patches',
                repeat=True, event='card_played', condition_id=PREFIX+'pirate', zone=Zone.DECK))
        else:
            fields = dict(defining_hand_source=HandProgressSpec('event', on_complete=PREFIX+'shift',
                repeat=True, event='turn_started'))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=1, health=1,
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
        if cid == CHAMELEOS:
            registry.register_defining_hand_copy(cid)
