"""Two real physical-card consumers of ordinary shuffle and end-turn work."""
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import ShuffleDeckCards
from hs_sim.engine.effects import CopyMinion, GrantTrigger, ModifyCost, ShuffleIntoDeck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, CostSpec, EndTurnSpec, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import HAND_TYPES
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

WRIGGLER = 'BE_566'
OOZE = 'BE_734'
PREFIX = 'cards.hand_shuffle_turn_copy.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/hand-shuffle-and-turn-copy-v1.json'
BATCH_HASH = '0fe1c75d8ebfd5b13e2ed1405fca8c57f2cb7ad186cfd41b3ee994aebee974d8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (WRIGGLER, OOZE) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Physical shuffle/copy requires its complete reviewed source faces')
    return data


def register_hand_shuffle_turn_copy_cards(registry):
    def wriggler(c):
        if c.target_id is None:
            return ()
        original = c.state.entities[c.target_id]
        if original.zone != Zone.HAND or original.controller != c.player_id:
            raise ResolutionError('Wriggler requires its actual friendly hand target')
        return (
            ShuffleDeckCards(c.player_id, c.player_id, (ShuffleIntoDeck(original.id, c.player_id),), c.source_id),
            ModifyCost(original.id, CostSpec(delta=-1), c.source_id),
        )

    def ooze(c):
        source = c.source
        if source.kind != CardType.MINION or source.zone != Zone.BOARD or not source.active:
            return ()
        return (GrantTrigger(source.id, 'turn_ended', PREFIX+'copy', source.id,
            expires_turn=c.state.turn, end_turn=EndTurnSpec('either')),)

    def copy(c):
        source = c.source
        if source.zone != Zone.BOARD or not source.active or source.health <= 0 or source.doomed:
            return ()
        board = c.state.players[source.controller].board
        return (CopyMinion(BoardPresenceReference.capture(c.state, source.id), c.player_id,
            position=board.index(source.id)+1, cause=SummonCause.capture(c)),)

    for name, body in (('wriggler', wriggler), ('ooze', ooze), ('copy', copy)):
        registry.register_behavior(PREFIX+name, body)
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']
        expected = (1, 3, 3, 14, 20) if cid == WRIGGLER else (4, 3, 2, 12, 26)
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or raw['tags'].get('BATTLECRY') != 1 or
                (raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'), raw['tags'].get('CARDRACE')) != expected):
            raise TargetValidationError('Physical shuffle/copy lost its complete printed minion face')
        fields = dict(battlecry=PREFIX+('wriggler' if cid == WRIGGLER else 'ooze'))
        if cid == WRIGGLER:
            fields['targeting'] = TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.HAND,), kinds=HAND_TYPES, relation='friendly')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
            health=raw['health'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
