"""Actual Pterrordax battlecry choice uses original recipients and owner expiry."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.model import CardDefinition, CardType, Keyword, TimedKeywordSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-timed-grants-v1.json'
BATCH_HASH = '0fdf524829db711c68ebab977822ab46fb11f55118dcbe77501b7cfc5c37eb6d'
PTERRORDAX = 'TLC_246'
STEALTH = 'UNG_999t10'
ELUSIVE = 'UNG_999t5'
WINDFURY = 'UNG_999t7'
CHOICE_ONLY = (STEALTH, ELUSIVE, WINDFURY)
PREFIX = 'cards.native_timed_grant.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native timed grant source pin changed')
    if (tuple(row['record']['id'] for row in data['cards']) != (PTERRORDAX,) or
            tuple(row['record']['id'] for row in data['dependencies']) != CHOICE_ONLY or
            tuple(data['choice_only_ids']) != CHOICE_ONLY or data['evidence_only']):
        raise TargetValidationError('Unreviewed native timed grant family')
    for row in data['cards'] + data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native timed grant complete source changed')
    return data


def register_native_timed_grant_cards(registry):
    data = load_batch()
    raws = {row['record']['id']: row['record'] for row in data['cards'] + data['dependencies']}
    def battlecry(c):
        if not living_source(c):
            return ()
        original = MinionReference.capture(c.source)
        options = tuple(ChoiceOption(cid, raws[cid]['name'], (
            GrantCapturedKeyword(original, keyword, c.source_id,
                duration=TimedKeywordSpec(Keyword.STEALTH) if cid == STEALTH else None),
        ), card_id=cid) for cid, keyword in ((STEALTH, Keyword.STEALTH), (ELUSIVE, Keyword.ELUSIVE), (WINDFURY, Keyword.WINDFURY)))
        return (RequestChoice(c.player_id, options, source_id=c.source_id),)
    registry.register_behavior(PREFIX+'pterrordax', battlecry)
    for cid, raw in raws.items():
        choice = cid in CHOICE_ONLY
        if raw['type'] != ('SPELL' if choice else 'MINION') or raw['collectible'] != (not choice):
            raise TargetValidationError('Pterrordax lost its actual card/option kind')
        card = CardDefinition(cid, raw['name'], CardType.SPELL if choice else CardType.MINION,
            cost=0 if choice else raw['cost'], attack=raw['attack'] or 0,
            health=0 if choice else raw['health'], choice_only=choice,
            battlecry=None if choice else PREFIX+'pterrordax',
            metadata=replace(metadata_from_record(raw), deck_identity=cid))
        registry.register_card(card)
        if not choice:
            registry.register_pool_card(PoolCard.from_definition(card))
