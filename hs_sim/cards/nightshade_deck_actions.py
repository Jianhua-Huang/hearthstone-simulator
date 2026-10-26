"""Actual Nightshade Bud branches use original deck cards and ordinary entry paths."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deck_discovery_actions import DiscoverDeckCardAction
from hs_sim.engine.model import CardDefinition, CardType, ChooseBranch, ChooseOneSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT = 'CORE_REV_311'
MINION, SPELL = 'REV_311t2', 'REV_311t'
COMBINED = ROOT+':combined'
PREFIX = 'cards.nightshade_deck_actions.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/nightshade-deck-actions-v1.json'
BATCH_HASH = 'fcfe14b21a06782cc497d7edd9e9a9684b2351a192f130c55c15087bdfb8d39f'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    all_rows = value['cards']+value['choices']+value['evidence_only']
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            tuple(r['record']['id'] for r in value['cards']) != (ROOT,) or
            tuple(r['record']['id'] for r in value['choices']) != (MINION,SPELL) or
            tuple(r['record']['id'] for r in value['evidence_only']) != ('REV_311',) or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['official_faces']) != 2 or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in all_rows)):
        raise TargetValidationError('Nightshade Bud lost its complete original branch and source scope')
    core = value['cards'][0]['record']; old = value['evidence_only'][0]['record']
    if (any(core[k] != old[k] for k in ('cost','type','text_en')) or
            any(core['dbf_id'] not in face['face'].get('copyOfCardId',()) for face in value['official_faces'])):
        raise TargetValidationError('Nightshade Core identity lost its complete original copy association')
    return value


def register_nightshade_deck_actions(registry):
    value = load_batch(); rows = {r['record']['id']:r['record'] for r in value['cards']+value['choices']}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Nightshade Bud cannot replace existing native identities')

    def discover(c, kind):
        return DiscoverDeckCardAction(c.player_id, kind, SummonCause.capture(c))

    bodies = {MINION:lambda c:(discover(c,CardType.MINION),),
        SPELL:lambda c:(discover(c,CardType.SPELL),),
        COMBINED:lambda c:(discover(c,CardType.MINION),discover(c,CardType.SPELL))}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    branches = ChooseOneSpec(tuple(ChooseBranch(cid,rows[cid]['name'],PREFIX+cid) for cid in (MINION,SPELL)),
        ChooseBranch(COMBINED,'兼得',PREFIX+COMBINED))
    for cid,raw in rows.items():
        internal = cid != ROOT
        meta = metadata_from_record(raw)
        if not internal:meta=replace(meta,deck_identity='REV_311')
        card = CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if internal else raw['cost'],
            metadata=meta,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            choice_only=internal,choose_one=None if internal else branches)
        registry.register_card(card)
        if not internal:registry.register_pool_card(PoolCard.from_definition(card))
