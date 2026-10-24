"""Four full, split-marked historical sources for real Assemble dependencies.

These declarations do not install a curated pool or assert Standard legality.
"""
import json
from pathlib import Path

from hs_sim.engine.assemble_end_conditions import AssembleNativeEndConditionSource
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.character_attacks import character_attacks
from hs_sim.engine.effects import Draw
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, EndTurnSpec, Keyword, TriggerSpec
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

EXPLORER, HUCKSTER, SCRYER, SERPENT = SOURCES = ('DRG_254', 'OG_330', 'BT_014', 'TTN_907')
PREFIX = 'cards.assemble_remaining_split.'
SPELL_BODY = 'cards.kindred_murlocs.draw_spell'
CONDITION = 'assemble.native_end_condition:astral_serpent_unattacked'
POOL_ID = 'constructed.cards'
DRAGONS = PoolQuery(kinds=(CardType.MINION,), collectible=True,
    class_mode='current', tribes_any=('dragon',))
TIMINGS = ('battlecry', 'deathrattle', 'end_turn', 'start_turn', 'attack_finished')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-remaining-split-minions-v1.json'
BATCH_HASH = '3437c0c927779c1270767989cacb66f4dc1f41c612f4b641178a1ed6a0757451'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards']+data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != SOURCES or
            tuple(row['record']['id'] for row in data['evidence_only']) != ('CORE_OG_330',) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            tuple(data['allowed_timings']) != TIMINGS or
            any(data[key] for key in ('dependencies', 'existing_dependencies', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Remaining Assemble sources require four full originals and the separate Core evidence')
    return data


def did_not_attack(c):
    # Opportunity counters do not include forced combat and can be refreshed.
    # Read the original attack ledger for this uninterrupted physical residence;
    # control changes keep that residence, while leaving/re-entering does not.
    source = BoardPresenceReference.capture(c.state, c.source_id)
    return not any(row.declaration.attack_source_presence == source
        for player in (1, 2)
        for row in character_attacks(c.state, player, phase='declared', turn=c.state.turn))


def register_assemble_remaining_split_minions(registry):
    data = load_batch()
    if any(cid in registry.cards or cid in registry.assemble_templates for cid in SOURCES):
        raise TargetValidationError('Remaining Assemble sources cannot replace an existing definition')
    registry.behavior(SPELL_BODY)
    registry.register_behavior(PREFIX+'dragon', lambda c:
        (DiscoverFromPool(c.player_id, POOL_ID, DRAGONS, source_id=c.source_id),))

    def opponent_card(c):
        other_class = c.state.players[3-c.player_id].hero_class
        query = PoolQuery(collectible=True, class_mode='specified',
            classes=(other_class,), include_neutral=False)
        return (GenerateFromPool(c.player_id, POOL_ID, query, source_id=c.source_id),)

    registry.register_behavior(PREFIX+'opponent_card', opponent_card)
    registry.register_behavior(PREFIX+'draw_two', lambda c: (Draw(c.player_id, 2, c.source_id),))
    registry.register_trigger_condition(CONDITION, did_not_attack)
    registry.register_behavior(PREFIX+'serpent_end', lambda c:
        (Draw(c.player_id, 2, c.source_id),) if did_not_attack(c) else ())
    for entry, declaration in zip(data['cards'], data['reviewed_templates']):
        raw = entry['record']
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                any(type(raw[key]) is not int for key in ('cost', 'attack', 'health'))):
            raise TargetValidationError('Remaining Assemble source lost its complete split-marked minion face')
        cid, body = raw['id'], declaration['body_id']
        timing = declaration['timing']
        keys = tuple(Keyword(k) for k in declaration['keywords'])
        end = EndTurnSpec() if cid == SERPENT else None
        fields = (dict(triggers=(TriggerSpec('turn_ended', declaration['original_id'], end),))
            if cid == SERPENT else {timing: body})
        card = CardDefinition(cid, raw['name'], CardType.MINION,
            cost=raw['cost'], attack=raw['attack'], health=raw['health'],
            keywords=keys, metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
        if cid == SERPENT:
            registry.register_assemble_native_end_condition(
                AssembleNativeEndConditionSource(cid, declaration['original_id'], CONDITION))
        registry.register_assemble_template(AssembleTemplate(cid,
            AssemblePrefix(timing, keys, end, condition_id=CONDITION if cid == SERPENT else None),
            AssembleSuffix(body, TIMINGS), original_end_turn_id=declaration['original_id']))
