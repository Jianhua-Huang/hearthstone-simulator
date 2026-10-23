"""Reviewed printed tribes, including the client's additional race boolean tags."""

from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.representative import metadata_from_record as base_metadata
from hs_sim.engine.model import Rarity
from hs_sim.targets import TargetValidationError, canonical_digest


PIN_PATH = Path(__file__).resolve().parents[2]/'data/cards/race-metadata-v1.json'
PIN_HASH = 'b0a09a7dc1226dd962ebe5b3bdb66986de2ee4bb9a2d6d8101b132f2cc322d32'


def reviewed_definition_digest(definition):
    """Keep pre-native-policy dependency pins; never omit an actual policy."""
    value=asdict(definition)
    if value['reborn_policy'] is None:value.pop('reborn_policy')
    if value['hand_mirror'] is None:value.pop('hand_mirror')
    if value['native_condition'] is None:value.pop('native_condition')
    if value['dormant_board_full'] is False:value.pop('dormant_board_full')
    if value['native_deathrattle'] is None:value.pop('native_deathrattle')
    return canonical_digest(value)
RACES = {2:'draenei', 11:'undead', 14:'murloc', 15:'demon', 17:'mech',
         18:'elemental', 20:'beast', 21:'totem', 23:'pirate', 24:'dragon', 26:'all', 43:'quilboar', 92:'naga'}
RACE_FLAGS = {2525:2, 2534:11, 2536:14, 2537:15, 2539:17, 2540:18,
              2542:20, 2543:21, 2522:23, 2523:24, 2546:43, 2553:92}


def validate_race_pin():
    data = json.loads(PIN_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN_HASH:
        raise TargetValidationError('Race metadata mapping differs from its reviewed source')
    actual = {row['m_isRaceTagId']:row['m_ID'] for row in data['race_rows'] if row['m_isRaceTagId']}
    if any(actual.get(tag) != race for tag,race in RACE_FLAGS.items()):
        raise TargetValidationError('Race flag does not match the client race table')


def metadata_from_record(raw):
    tags = raw['tags']
    primary = tags.get('CARDRACE')
    if primary is not None and (type(primary) is not int or primary not in RACES):
        raise TargetValidationError('Unreviewed primary constructed race')
    # Reuse the established class/rarity/rune/identity decoding. Tribe values
    # are declared separately so new reviewed races need no legacy-pack changes.
    stripped = dict(raw, tags={key:value for key,value in tags.items() if key != 'CARDRACE'})
    meta = base_metadata(stripped)
    if raw['collectible'] is False and 'RARITY' not in tags:
        meta = replace(meta, rarity=Rarity.NONE)
    tribes = [] if primary is None else [RACES[primary]]
    for tag,race in RACE_FLAGS.items():
        value = tags.get(str(tag), 0)
        if type(value) is not int or value not in (0,1):
            raise TargetValidationError('Printed race flag must be an explicit zero or one')
        if value and RACES[race] not in tribes:
            tribes.append(RACES[race])
    lackey = tags.get('MARK_OF_EVIL', 0)
    if type(lackey) is not int or lackey not in (0, 1) or lackey and raw['type'] != 'MINION':
        raise TargetValidationError('Printed Lackey identity requires a reviewed minion boolean')
    return replace(meta, tribes=tuple(tribes), subtypes=meta.subtypes + (('lackey',) if lackey else ()))
