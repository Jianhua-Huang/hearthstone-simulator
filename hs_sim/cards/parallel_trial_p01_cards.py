"""P01: eight reviewed real cards composed from existing public effects.

This optional batch does not change the shared constructed registry or its
content identity. Official faces establish text, not precise CN timing.
"""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import BuffMinionsInZones, MinionScope
from hs_sim.engine.effects import (
    ChangeManaCrystals, InvokeBehavior, RandomBuff, RandomDamage,
    RandomDamageBatch, SetStats,
)
from hs_sim.engine.model import (
    CardDefinition, CardType, DamageKind, EndTurnSpec, HandActionSpec, Keyword,
    RewindSpec, TriggerSpec, Zone,
)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import completed_attack
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/parallel-trial-p01-v1.json'
BATCH_HASH = '74784c4395f54e810706b5a8c90328492b33a179d3b79d0e65b0abe3462e666d'
CLAW = 'CATA_467'
DOVE = 'TIME_037'
DINOMANCY = 'TLC_828'
STONECARVER = 'TLC_623'
KROG = 'TLC_480'
TENDER = 'TLC_255'
DAGGERS = 'TIME_001'
REND = 'TIME_441'
ROOTS = (CLAW, DOVE, DINOMANCY, STONECARVER, KROG, TENDER, DAGGERS, REND)
PREFIX = 'cards.parallel_trial_p01.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P01 lost its complete reviewed source pin')
    if tuple(row['record']['id'] for row in data['cards']) != ROOTS or data['dependencies']:
        raise TargetValidationError('Unreviewed P01 root/dependency set')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('P01 complete source row changed')
    return data


def register_parallel_trial_p01_cards(registry):
    data = load_batch()

    def follow(c, name):
        return InvokeBehavior(PREFIX + name, c.source_id, c.player_id, c.target_id,
                              None if c.play is None else c.play.id)

    def claw(c):
        row = completed_attack(c)
        if row is None or row.source_kind != CardType.HERO or row.declaration.player_id != c.player_id:
            return ()
        return (RandomBuff(minions(c, registry, c.player_id), 2, 0, c.source_id),)

    def stonecarver(c):
        candidates = tuple(i for i in minions(c, registry, c.player_id)
                           if i != c.source_id and c.state.entities[i].health < c.state.entities[i].max_health)
        return (RandomBuff(candidates, 2, 2, c.source_id),)

    def tender(c):
        difference = max(0, c.state.players[3-c.player_id].max_mana - c.state.players[c.player_id].max_mana)
        return (ChangeManaCrystals(c.player_id, difference, filled=False),) if difference else ()

    bodies = {
        'claw': claw,
        'dove': lambda c: (
            DrawMatching(c.player_id, PoolQuery(kinds=(CardType.MINION,)), 'skip', source_id=c.source_id),
            follow(c, 'dove_hand'),
        ),
        'dove_hand': lambda c: (BuffMinionsInZones(
            c.player_id, health=2, scope=MinionScope(zones=(Zone.HAND,)), source_id=c.source_id),),
        'dinomancy': lambda c: (BuffMinionsInZones(
            c.player_id, 2, 2, MinionScope(query=PoolQuery(tribes_any=('beast',)), tribe_basis='current'), c.source_id),),
        'stonecarver': stonecarver,
        'krog': lambda c: tuple(SetStats(i, attack=1, health=1, source_id=c.source_id)
                                for i in minions(c, registry, 3-c.player_id)),
        'tender': tender,
        'daggers': lambda c: tuple(follow(c, 'knife') for _ in range(3)),
        'knife': lambda c: (RandomDamage(characters(c, registry, 3-c.player_id), 2, c.source_id, DamageKind.SPELL),),
        'rend': lambda c: (RandomDamageBatch(characters(c, registry, 3-c.player_id), 2, 4, c.source_id, DamageKind.SPELL),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for row in data['cards']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        if raw['collectible'] is not True:
            raise TargetValidationError('P01 requires reviewed collectible roots')
        kwargs = {}
        if cid == CLAW:
            kwargs.update(durability=raw['health'], triggers=(TriggerSpec('attack_finished', PREFIX + 'claw'),))
        elif cid in (DOVE, TENDER):
            kwargs['battlecry'] = PREFIX + ('dove' if cid == DOVE else 'tender')
            if cid == TENDER:
                kwargs['hand_actions'] = (HandActionSpec('trade', 'trade', 1),)
        elif cid in (STONECARVER, KROG):
            kwargs['triggers'] = (TriggerSpec('turn_ended', PREFIX + ('stonecarver' if cid == STONECARVER else 'krog'), EndTurnSpec()),)
        else:
            kwargs['on_play'] = PREFIX + {DINOMANCY: 'dinomancy', DAGGERS: 'daggers', REND: 'rend'}[cid]
            if cid in (DAGGERS, REND):
                kwargs.update(keywords=(Keyword.REWIND,), rewind=RewindSpec())
        card = CardDefinition(
            cid, raw['name'], kind, cost=raw['cost'], attack=raw['attack'] or 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs,
        )
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
