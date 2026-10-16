"""Real low-cost deck casting and Holy history recasting with original-self priority."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.automatic_targets import PreferredMinionTarget
from hs_sim.engine.deck_spell_casts import CastRandomDeckSpell
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    EndTurnSpec, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.spell_history import RecastFromHistory, SpellHistoryQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/self-target-spell-effects-v1.json'
BATCH_HASH = '8a5895b6b30ad88fb06903b6835aaf95b1596c17981b41c016f2b4852e22acc0'
PREFIX = 'cards.self_target_spells.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Self-target spell cards lost their complete reviewed source pin')
    return data


def register_self_target_spell_cards(registry):
    def preference(c):
        if c.source.zone != Zone.BOARD or c.source.kind != CardType.MINION:
            return None
        if c.end_turn is not None and c.source.board_presence_id > c.end_turn.subject.entered_order:
            return None
        if c.play is not None and c.play.source_id == c.source_id:
            entry = next((x for x in c.state.successful_summon_history
                if x.entity_id == c.source_id and x.action == c.play.action), None)
            if entry is None or c.source.board_presence_id != entry.minion.entered_order:
                return None
        return PreferredMinionTarget(BoardPresenceReference.capture(c.state, c.source_id))

    registry.register_behavior(PREFIX+'treasuregill', lambda c:
        (CastRandomDeckSpell(c.player_id, 2, c.source_id, preference(c)),))
    registry.register_behavior(PREFIX+'cave', lambda c:
        (RecastFromHistory(c.player_id, SpellHistoryQuery(
            cards=PoolQuery(spell_schools=(SpellSchool.HOLY,)),
            min_turn=c.state.turn, max_turn=c.state.turn),
            count=1, selection='random', source_id=c.source_id,
            target_preference=preference(c)),))
    data = load_batch()
    if [x['record']['id'] for x in data['cards']] != ['TLC_438','TLC_430']:
        raise TargetValidationError('Unreviewed self-target spell identities')
    for row in data['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256'] or raw['type'] != 'MINION' or not raw['collectible']:
            raise TargetValidationError('Unreviewed self-target spell face')
        kwargs = dict(battlecry=PREFIX+'treasuregill') if raw['id'] == 'TLC_438' else dict(
            triggers=(TriggerSpec('turn_ended',PREFIX+'cave',EndTurnSpec()),))
        definition = CardDefinition(raw['id'],raw['name'],CardType.MINION,
            cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
