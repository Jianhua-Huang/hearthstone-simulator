"""Real weapon/Hero text sources over the existing secondary projection layer."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleProjection, AssembleSuffix
from hs_sim.engine.model import CardType
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .native_followup_cards import deathrattle_position

HAMMER, JARAXXUS = SOURCES = ('CORE_OG_031', 'CORE_EX1_323')
ELEMENTAL, BLOOD_FURY = TOKENS = ('OG_031a', 'EX1_323w')
PREFIX = 'cards.assemble_weapon_hero.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-weapon-hero-fragments-v1.json'
BATCH_HASH = '139d019d38104c34f56a10b97b00838858b5b8bba367e4aa515d89deed99f558'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in rows) != SOURCES+TOKENS or
            any(data[k] for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows)):
        raise TargetValidationError('Weapon/Hero assembly requires its complete original sources and exact children')
    return data


def register_assemble_weapon_hero_fragments(registry):
    data = load_batch(); rows = {r['record']['id']: r for r in data['existing_dependencies']}
    for cid, row in rows.items():
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Weapon/Hero assembly changed a complete native dependency: '+cid)
    hammer, hero = rows[HAMMER]['record'], rows[JARAXXUS]['record']
    if ((hammer['type'],hammer['cost'],hammer['attack'],hammer['health']) != ('WEAPON',5,4,2) or
            (hero['type'],hero['cost'],hero['attack'],hero['health'],hero['tags'].get('ARMOR')) != ('HERO',8,None,30,5) or
            any(row['record']['text'].count('&') != 1 or row['record']['text_en'].count('&') != 1
                for row in (rows[HAMMER],rows[JARAXXUS]))):
        raise TargetValidationError('Weapon/Hero assembly lost its literal split or whole printed source')

    def twilight(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(ELEMENTAL),), SummonCause.capture(c),
            position=deathrattle_position(c) if c.deathrattle is not None else None),)
    registry.register_behavior(PREFIX+'twilight', twilight)
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']; row = rows[cid]
        if cid == JARAXXUS and declaration['behavior_id'] != registry.card(JARAXXUS).battlecry:
            raise TargetValidationError('Jaraxxus projects only its original equipment body')
        registry.register_assemble_projection(AssembleProjection(cid, CardType(row['record']['type'].lower()),
            row['definition_sha256'], row['record_sha256'], AssemblePrefix(declaration['timing']),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']))))
