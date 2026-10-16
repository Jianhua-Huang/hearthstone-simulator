"""Reviewed Kindred play bodies and the Murloc generation dependencies they add."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Buff, CopyMinion, Damage, InvokeBehavior
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    DamageKind, EndTurnSpec, Keyword, TargetMode, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.owner_turns import query_for_definition, query_previous_owner_turn
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/kindred-murloc-effects-v1.json'
BATCH_HASH = '5b49352fcbb40a089c3995939b3fb296c7d659f3f2f4ae93d0e563646d07c18e'
PREFIX = 'cards.kindred_murlocs.'
ROOTS = ('DINO_404', 'TIME_428', 'TLC_427', 'TLC_429', 'TLC_243', 'TLC_903', 'TLC_226')
DEPENDENCIES = ('WW_001t', 'TLC_429t')
KINDRED = frozenset(('DINO_404', 'TLC_429', 'TLC_243', 'TLC_903', 'TLC_226'))


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value) != BATCH_HASH:
        raise TargetValidationError('Kindred/Murloc recipes lost their complete reviewed source pin')
    return value


def register_kindred_murloc_cards(registry):
    def matched(c, cid):
        return query_previous_owner_turn(c.state, c.player_id,
            query_for_definition(registry.card(cid))).matched

    def firegill(c):
        return tuple(GrantCapturedKeyword(MinionReference.capture(c.state.entities[eid]),
            Keyword.RUSH, c.source_id) for eid in minions(c, registry, c.player_id)
            if eid != c.source_id)

    def thief(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial('TLC_429t'),),
            SummonCause.capture(c))
        return request, request

    bodies = {
        'DINO_404': firegill,
        'TLC_429': thief,
        'TLC_243': lambda c: (GrantCapturedKeyword(MinionReference.capture(c.source),
            Keyword.IMMUNE, c.source_id, c.state.turn),),
        'TLC_903': lambda c: (Buff(c.state.players[c.player_id].hero_id,
            attack=5, source_id=c.source_id, expires_turn=c.state.turn),),
        'TLC_226': lambda c: (CopyMinion(BoardPresenceReference.capture(c.state, c.source_id),
            c.player_id, cause=SummonCause.capture(c)),),
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid,
            lambda c, cid=cid, body=body: body(c) if matched(c, cid) else ())
    # End-turn activations re-read the actual board when each accepted body runs.
    registry.register_behavior(PREFIX + 'TIME_428', lambda c:
        (InvokeBehavior(PREFIX + 'yesterloc_execute', c.source_id, c.player_id),))
    registry.register_behavior(PREFIX + 'yesterloc_execute', lambda c:
        tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[eid]),
            health=1, source_id=c.source_id) for eid in minions(c, registry, c.player_id)
            if eid != c.source_id))
    registry.register_behavior(PREFIX + 'TLC_427',
        lambda c: (AddToHand(c.player_id, 'WW_001t', c.source_id),))
    registry.register_behavior(PREFIX + 'rock',
        lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),))
    registry.register_behavior(PREFIX + 'draw_spell', lambda c:
        (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.SPELL,)), 'skip',
            source_id=c.source_id),))

    data = load_batch()
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != DEPENDENCIES):
        raise TargetValidationError('Unreviewed Kindred/Murloc identities')
    for row in data['cards'] + data['dependencies']:
        raw, recipe = row['record'], row['recipe']
        cid = raw['id']
        if (canonical_digest(raw) != row['record_sha256'] or
                raw['collectible'] is not (cid in ROOTS) or
                raw['type'] != ('SPELL' if cid == 'WW_001t' else 'MINION')):
            raise TargetValidationError('Unreviewed Kindred/Murloc face')
        kwargs = {}
        if cid in KINDRED:
            if raw['tags'].get('KINDRED') != 1 or raw['tags'].get('BATTLECRY', 0):
                raise TargetValidationError('Kindred play bodies must remain separate from Battlecry')
            kwargs['on_play'] = PREFIX + cid
        if cid == 'TIME_428':
            kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX + cid, EndTurnSpec()),)
        elif cid == 'TLC_427':
            kwargs['battlecry'] = PREFIX + cid
        elif cid == 'TLC_226':
            kwargs['deathrattle'] = PREFIX + 'draw_spell'
        elif cid == 'WW_001t':
            kwargs['on_play'] = PREFIX + 'rock'
            kwargs['targeting'] = TargetSpec(TargetMode.REQUIRED,
                zones=(Zone.HERO, Zone.BOARD), kinds=(CardType.HERO, CardType.MINION))
        definition = CardDefinition(cid, raw['name'], CardType[raw['type']],
            cost=raw['cost'], attack=raw['attack'] or 0, health=raw['health'] or 0,
            keywords=tuple(Keyword(k) for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']),
            **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
