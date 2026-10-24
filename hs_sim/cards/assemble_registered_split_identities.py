"""Separate declarations for fifteen existing original physical identities."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .native_followup_cards import deathrattle_position

SOURCES = ('BAR_313', 'BT_351', 'BT_480', 'BT_493', 'BT_510', 'DMF_067',
    'DRG_024', 'EX1_007', 'EX1_131', 'KAR_069', 'RLK_121', 'RLK_814',
    'UNG_912', 'WC_701', 'YOD_026')
DEATH_BODY = 'cards.assemble_registered_split.defias_death'
TOKEN = 'EX1_131t'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-registered-split-identities-v1.json'
BATCH_HASH = '6959b1cbfce58e72cdf3517dca3839ec9546a932acd6f7454da0e90b3be4505f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['card_id'] for x in data['reviewed_sources']) != SOURCES or
            tuple(x['record']['id'] for x in rows) != SOURCES+tuple('CORE_'+cid for cid in SOURCES)+
                (TOKEN, 'CORE_EX1_096', 'CORE_UNG_809') or
            tuple(data['added_pool_metadata']) != ('BT_480',) or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Registered split identities require all complete independent sources')
    return data


def register_assemble_registered_split_identities(registry):
    data = load_batch()
    if any(cid in registry.assemble_templates or cid in registry.assemble_projections for cid in SOURCES):
        raise TargetValidationError('Registered split identities cannot replace an existing adapter')
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Registered split identity changed its complete original definition')
    for declaration in data['reviewed_sources']:
        original = registry.assemble_templates[declaration['core_id']]
        if (canonical_hash(asdict(original)) != declaration['original_core_template_sha256'] or
                canonical_hash(declaration['original_core_template']) != declaration['original_core_template_sha256']):
            raise TargetValidationError('Registered split identity changed its complete reviewed Core declaration')
        for key, profiles in (('reaction_source', registry.assemble_reaction_sources),
                ('on_play_source', registry.assemble_on_play_sources)):
            if declaration[key] is not None and (
                    canonical_hash(asdict(profiles[declaration['core_id']])) != canonical_hash(declaration[key])):
                raise TargetValidationError('Registered split identity lost its complete native source proof')
    for cid in data['added_pool_metadata']:
        if cid in registry.pool_cards:
            raise TargetValidationError('Registered split identity cannot replace existing generation metadata')
        registry.register_pool_card(PoolCard.from_definition(registry.card(cid)))

    def defias_death(c):
        if c.deathrattle is None:
            raise ResolutionError('Borrowed Defias death body requires its original deathrattle context')
        return (SummonByCard(c.player_id, (SummonEntryMaterial(TOKEN),),
            SummonCause.capture(c), position=deathrattle_position(c)),)

    registry.register_behavior(DEATH_BODY, defias_death)
    amendment = data['death_body_amendment']
    registry.set_assemble_suffix_deathrattle_body(amendment['card_id'], DEATH_BODY,
        expected_template_sha256=amendment['original_template_sha256'])
    for amendment in data['timing_amendments']:
        registry.extend_assemble_suffix_timings(amendment['card_id'], tuple(amendment['add_timings']),
            expected_template_sha256=amendment['original_template_sha256'])
    for declaration in data['reviewed_sources']:
        cid, core = declaration['card_id'], declaration['core_id']
        original, template = registry.card(cid), registry.assemble_templates[core]
        suffix = template.suffix
        slot = declaration['native_body_slot']
        if slot is not None:
            body = original.triggers[0].behavior_id if slot == 'end_turn' else getattr(original, slot)
            suffix = replace(suffix, behavior_id=body)
        updated = replace(template, card_id=cid, suffix=suffix,
            original_battlecry_id=original.battlecry if declaration['replace_original_battlecry'] else
                template.original_battlecry_id)
        if declaration['reaction_source'] is not None:
            registry.register_assemble_reaction_source(replace(registry.assemble_reaction_sources[core], card_id=cid))
        if declaration['on_play_source'] is not None:
            registry.register_assemble_on_play_source(replace(registry.assemble_on_play_sources[core],
                card_id=cid, original_behavior_id=original.on_play))
        registry.register_assemble_template(updated)
