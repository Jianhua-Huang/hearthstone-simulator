"""Forge of Origination uses one original group and an ordinary armor reward."""
import json
from pathlib import Path
from hs_sim.engine.armor_summon_rewards import SpendArmorForSummonedGroup
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_561'; TOKEN = 'BE_561t'; BODY = 'cards.armor_summon_reward.forge'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/armor-summon-reward-v1.json'
BATCH_HASH = 'ebd5895e1e1bc41173c9296cba3b45e6e13d76d8e1689301d1dd59b04f052f12'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (TOKEN,) or
            any(data[k] for k in ('existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['dependencies'])):
        raise TargetValidationError('Forge requires its full original Location and Golem faces')
    return data


def register_armor_summon_reward_card(registry):
    data = load_batch(); root = data['cards'][0]['record']; token = data['dependencies'][0]['record']
    if ((root['type'], root['cost'], root['health'], root['tags'].get('CLASS')) != ('LOCATION', 3, 2, 10) or
            (token['type'], token['cost'], token['attack'], token['health'], token['tags'].get('TAUNT'), token['collectible']) !=
            ('MINION', 3, 3, 3, 1, False)):
        raise TargetValidationError('Forge lost its real three-cost two-durability face or 3/3 Taunt Golem')
    def body(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),), SummonCause.capture(c)),
            SpendArmorForSummonedGroup(c, TOKEN, 3, 3, 3))
    registry.register_behavior(BODY, body)
    for card in (CardDefinition(TOKEN, token['name'], CardType.MINION, cost=3, attack=3, health=3,
            keywords=(Keyword.TAUNT,), metadata=metadata_from_record(token)),
            CardDefinition(CARD, root['name'], CardType.LOCATION, cost=3, durability=2,
                on_use=BODY, requires_board_space=True, metadata=metadata_from_record(root))):
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
