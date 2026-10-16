"""Three reviewed P06 roots over native hand facts and public owner clocks."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.effects import Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, SpellSchool, TriggerSpec
from hs_sim.engine.play_history import played_cards, play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-timing-p06-v1.json'
BATCH_HASH = 'f34ca54f652764df6881ae6f8b7f8615b8f3e8f74632b8f74a86fc067339eb2a'
WEBWEAVER = 'EDR_540'
MAGMA = 'TLC_224'
FLOCK = 'TLC_232'
HATCHLING = 'TLC_237t'
ROOTS = (WEBWEAVER, MAGMA, FLOCK)
PREFIX = 'cards.simple_timing_p06.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P06 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or data['dependencies'] or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (HATCHLING,) or data['skipped']):
        raise TargetValidationError('Unreviewed P06 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P06 complete source row changed')
    return data


def committed(c):
    if c.event is None or c.event.kind != 'card_committed':
        raise ResolutionError('P06 requires its original hand-play commitment')
    record = play_record(c.state, dict(c.event.data)['play_id'])
    if (record.source_id, record.player_id) != (c.event.source_id, c.event.player_id):
        raise ResolutionError('P06 borrowed a different hand-play commitment')
    if record.played_face is None or record.submitted_cost is None:
        raise ResolutionError('P06 lost its frozen submitted face or cost receipt')
    return record


def minion_identity(record):
    if record.played_face is None:
        raise ResolutionError('Webweaver lost an earlier original submitted face')
    face = record.played_face
    return (face.metadata.deck_identity if face.metadata is not None else None) or face.card_id


def register_simple_timing_p06_cards(registry):
    data = load_batch()
    dependency, = data['existing_dependencies']
    if (dependency['record']['dbf_id'] != 118658 or
            canonical_digest(asdict(registry.card(HATCHLING))) != dependency['definition_sha256']):
        raise TargetValidationError('Flock requires the exact complete existing Hatchling118658')

    def webweaver(c):
        record = committed(c)
        if record.player_id != c.player_id or record.kind != CardType.MINION or record.source_id == c.source_id:
            return ()
        identity = minion_identity(record)
        if any(minion_identity(previous) == identity for previous in
               played_cards(c.state, c.player_id, before_id=record.id, kind=CardType.MINION)):
            return (Draw(c.player_id, source_id=c.source_id),)
        return ()

    def magma(c):
        record = committed(c)
        if (record.player_id != c.player_id or record.kind != CardType.SPELL or
                record.played_face.spell_school != SpellSchool.FIRE):
            return ()
        amount = record.submitted_cost.quote.amount
        if (amount, record.submitted_cost.quote.payment) != (record.cost, record.payment):
            raise ResolutionError('Magma lost its original accepted cost quote')
        return (BuffCapturedMinion(MinionReference.capture(c.source), amount, amount, c.source_id),) if amount else ()

    registry.register_behavior(PREFIX+'webweaver', webweaver)
    registry.register_behavior(PREFIX+'magma', magma)
    registry.register_behavior(PREFIX+'hatchlings', lambda c: tuple(
        SummonByCard(c.player_id, (SummonEntryMaterial(HATCHLING),), SummonCause.capture(c)) for _ in range(3)))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'flock', FLOCK, kind='objective',
        duration=1, tick_event='turn_started', on_expire=PREFIX+'hatchlings'))
    for row in data['cards']:
        raw = row['record']
        cid = raw['id']
        kind = CardType(raw['type'].lower())
        kwargs = {}
        if cid == FLOCK:
            if (raw['tags'].get('OBJECTIVE'), raw['tags'].get('QUEST_PROGRESS_TOTAL'),
                    raw['tags'].get('COLLECTION_RELATED_CARD_DATABASE_ID')) != (1, 1, 118658):
                raise TargetValidationError('Flock lost its real Objective or named Hatchling')
            kwargs['ongoing_effect_id'] = PREFIX+'flock'
        else:
            kwargs['triggers'] = (TriggerSpec('card_committed', PREFIX+('webweaver' if cid == WEBWEAVER else 'magma')),)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
