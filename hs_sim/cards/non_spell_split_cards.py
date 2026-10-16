"""Real original non-spell split groups consume the shared packet receipts."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, DamageKind, SpellSchool
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage, killed_minions
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/non-spell-split-v1.json'
BATCH_HASH = 'db6fe82eb56ca587c114a440f0b41f80c4eff296ea5d6be77aa8e990575ab70b'
ELEPHANT = 'MEND_302'
VOLCANO = 'CATA_584'
ROOTS = (ELEPHANT, VOLCANO)
PREFIX = 'cards.non_spell_split.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Non-spell split complete source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != ROOTS or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed non-spell split family')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Non-spell split complete source row changed')
    return data


def register_non_spell_split_cards(registry):
    def request(c, kind, after=None):
        return RandomSplitDamage(c.player_id, None, c.source_id, 3, on_complete=after,
                                 profile=NON_SPELL_PROFILE, kind=kind)
    registry.register_behavior(PREFIX+'elephant', lambda c: (
        request(c, DamageKind.MINION_ABILITY, PREFIX+'after_elephant'),))
    registry.register_behavior(PREFIX+'after_elephant', lambda c: (
        (request(c, DamageKind.MINION_ABILITY),) if killed_minions(c.state, c.event) else ()))
    def volcano(c):
        fire = any(p.played_face.spell_school == SpellSchool.FIRE for p in
                   played_cards(c.state, c.player_id, turn=c.state.turn, kind=CardType.SPELL))
        return tuple(request(c, DamageKind.EFFECT) for _ in range(2 if fire else 1))
    registry.register_behavior(PREFIX+'volcano', volcano)
    for row in load_batch()['cards']:
        raw = row['record']; cid = raw['id']
        if cid == ELEPHANT:
            if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY')) != ('MINION',4,3,3,1):
                raise TargetValidationError('Elephant lost its actual battlecry minion face')
            kind=CardType.MINION;kwargs=dict(attack=3,health=3,battlecry=PREFIX+'elephant')
        else:
            if (raw['tags']['CARDTYPE'],raw['cost'],raw['health']) != (39,3,3):
                raise TargetValidationError('Volcano requires its actual Location face')
            kind=CardType.LOCATION;kwargs=dict(durability=3,on_use=PREFIX+'volcano')
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid), **kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
