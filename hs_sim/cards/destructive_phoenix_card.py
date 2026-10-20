"""Destructive Phoenix uses a bound hand residence and the shared end clock."""
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.native_hand_targets import hand_target
from hs_sim.engine.hand_deadlines import ScheduleHandRemoval, same_hand
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_EVENT_001'
BODY = 'cards.destructive_phoenix.ignite'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/destructive-phoenix-v1.json'
BATCH_HASH = '97b45d0a2276e332ae88b1cb4e8dfea7bc029bcba2ebef40e3bb7c7a9be556d3'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows = data['cards'] + data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or
            [x['record']['id'] for x in rows] != [CARD, CARD+'e'] or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in rows)):
        raise TargetValidationError('Destructive Phoenix requires its complete original source')
    raw = rows[0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'],
            rows[1]['record']['tags'].get('TAG_SCRIPT_DATA_NUM_2')) != ('MINION', 4, 5, 5, 3):
        raise TargetValidationError('Destructive Phoenix changed its body or burn duration')
    return data


def register_destructive_phoenix_card(registry):
    def ignite(c):
        marked = {t.entity_id for root in c.state.hand_deadlines
                  if root.expired_event is None and root.request.retirement == 'discard_copy'
                  for t in root.targets if same_hand(c.state, t)}
        options = []
        for identity in c.state.players[c.player_id].hand:
            if identity in marked:
                continue
            entity = c.state.entities[identity]
            request = ScheduleHandRemoval(c.player_id, 3, c.source_id, 'discard_copy',
                                          cards=(CardReference.capture(entity),))
            options.append(ChoiceOption(str(identity), registry.card(entity.card_id).name,
                                        (request,), card_id=entity.card_id, entity_id=identity))
        return (RequestChoice(c.player_id, tuple(options), c.source_id,
                              prompt='选择一张手牌并点燃', targeting=hand_target()),) if options else ()

    registry.register_behavior(BODY, ignite)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=5, health=5,
                          battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
