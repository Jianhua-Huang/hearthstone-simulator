"""One fixed target's newest printed edition advances original dormancy."""
import json
from pathlib import Path
from types import MappingProxyType

from hs_sim.engine.dormancy import AdvanceCapturedDormancy
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, Keyword, TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_063'
BODY = 'cards.timelord_nozdormu.advance'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/time-lord-nozdormu-v1.json'
BATCH_HASH = '8b0e9d8f436b2cc315250db23d8b0c9e68f76955ebaa14c5c7a016a7b7f94632'
PRELAUNCH_POLICY = 'cn37-prelaunch-20261015'
POSTLAUNCH_POLICY = 'cn37-black-empire-20261021'
POSTLAUNCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/cn37-postlaunch-printed-expansion-v1.json'
POSTLAUNCH_HASH = '5dc6b889ac5fcf6d6614d3c890bf2411e8d8d36520986029ccfcecbe4060c3d1'
POSTLAUNCH_BODY = BODY+'.'+POSTLAUNCH_POLICY+'.'+POSTLAUNCH_HASH


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('TIME_063e1', 'TIME_063e2') or
            len(data['printed_card_sets']) != data['source_record_count'] or data['source_record_count'] != 23452 or
            data['latest_expansion']['card_set_id'] != 1988):
        raise TargetValidationError('Timelord requires the full printed edition inventory and fixed target policy')
    for row in (*data['cards'], *data['evidence_only']):
        if (canonical_digest(row['record']) != row['record_sha256'] or
                data['printed_card_sets'][row['record']['id']] != row['record']['card_set_id']):
            raise TargetValidationError('Timelord source or actual printed edition changed')
    return data


def load_postlaunch_policy(base):
    policy = json.loads(POSTLAUNCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(base) != BATCH_HASH or canonical_digest(policy) != POSTLAUNCH_HASH or
            policy['schema'] != 1 or policy['policy_id'] != POSTLAUNCH_POLICY or
            policy['base_batch_sha256'] != BATCH_HASH or policy['card_set_id'] != 1994 or
            policy['printed_inventory_count'] != base['source_record_count'] or
            policy['printed_inventory_sha256'] != canonical_digest(base['printed_card_sets']) or
            policy['release_evidence']['publication_date'] != '2026-10-21' or
            policy['release_evidence']['url'] != 'https://hs.blizzard.cn/news/24304163/index.html'):
        raise TargetValidationError('Postlaunch printed edition policy lost its fixed CN source or inventory')
    evidence = base['latest_expansion']['set_id_evidence']
    standard = next(x['subcategories'] for x in evidence['response']['data']['list'] if x['name_en'] == 'standard')
    entry = next((x for x in standard if x['id'] == policy['card_set_id']), None)
    if (entry != policy['set_id_evidence']['entry'] or entry is None or entry['name'] != policy['name'] or
            policy['set_id_evidence']['url'] != evidence['url'] or
            policy['set_id_evidence']['response_sha256'] != evidence['response_sha256']):
        raise TargetValidationError('Postlaunch printed edition changed its complete original CN set evidence')
    return policy


def register_time_lord_nozdormu_card(registry, *, policy_id=PRELAUNCH_POLICY):
    if policy_id not in (PRELAUNCH_POLICY, POSTLAUNCH_POLICY):
        raise TargetValidationError('Unknown fixed Timelord printed edition policy')
    data = load_batch()
    editions = MappingProxyType(dict(data['printed_card_sets']))
    policy = load_postlaunch_policy(data) if policy_id == POSTLAUNCH_POLICY else data['latest_expansion']
    latest = policy['card_set_id']
    body_id = POSTLAUNCH_BODY if policy_id == POSTLAUNCH_POLICY else BODY
    def advance(c):
        if c.event is None or c.event.kind != 'card_played':
            raise ResolutionError('Timelord requires an original completed card-play event')
        row = play_record(c.state, dict(c.event.data).get('play_id'))
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Timelord lost its actual completed play')
        if row.player_id != c.player_id:
            return ()
        if row.card_id not in editions or editions[row.card_id] is None:
            raise UnsupportedDefinitionError('Unreviewed original played-card edition: ' + row.card_id)
        if editions[row.card_id] != latest or c.source.dormancy is None:
            return ()
        return (AdvanceCapturedDormancy(MinionReference.capture(c.source), c.source.dormancy.id,
                                         source_id=c.source_id),)
    registry.register_behavior(body_id, advance)
    raw = data['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CLASS'], raw['tags']['CARDRACE']) != (
            'MINION', 3, 8, 8, 12, 24):
        raise TargetValidationError('Timelord lost its original neutral Dragon face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=8, health=8,
        keywords=(Keyword.RUSH,), dormant_turns=5, dormant_triggers=(TriggerSpec('card_played', body_id),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
