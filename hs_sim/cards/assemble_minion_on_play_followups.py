"""Six real minion play halves use native Outcast and Kindred subjects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_on_play import AssembleOnPlaySource
from hs_sim.engine.effects import Draw, GrantKeyword
from hs_sim.engine.model import Keyword
from hs_sim.engine.owner_turns import query_for_definition, query_previous_owner_turn
from hs_sim.targets import TargetValidationError, canonical_digest
from .hero_outcast_immunity_cards import IMMUNITY

SOURCES = ('CORE_BT_480', 'TIME_021', 'DINO_138', 'DINO_404', 'TLC_429', 'TLC_903')
TOKEN = 'TLC_429t'
PREFIX = 'cards.assemble_minion_play.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-minion-on-play-followups-v1.json'
BATCH_HASH = '00cabd0e5f491532e0880016d36b4b0606bba97938679b163941f11fe667ea08'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (TOKEN,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies']) or
            data['hero_immunity'] != asdict(IMMUNITY)):
        raise TargetValidationError('Minion play assembly requires six full originals and their real token and immunity')
    return data


def register_assemble_minion_on_play_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Minion play assembly changed a complete original source or token')
    rows = {row['record']['id']: row['record'] for row in data['existing_dependencies']}
    link = data['token_link']
    if (link != dict(root_id='TLC_429', card_id=TOKEN, dbf_id=118184) or
            rows['TLC_429']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != link['dbf_id'] or
            rows[TOKEN]['dbf_id'] != link['dbf_id']):
        raise TargetValidationError('Minion play assembly changed the original named Murloc token')
    for cid, profile in data['original_kindred_profiles'].items():
        if asdict(registry.kindred_profiles[cid]) != profile:
            raise TargetValidationError('Minion play assembly changed the complete native Kindred component')
        registry.behavior(profile['active'])

    def outcast(c):
        if c.spell_conditions is None:
            raise ValueError('Assembly Outcast lost its original accepted physical conditions')
        return c.spell_conditions.outcast

    def kindred(c):
        if c.spell_conditions is None:
            raise ValueError('Assembly Kindred lost its original accepted printed subject')
        return query_previous_owner_turn(c.state, c.player_id,
            query_for_definition(registry.card(c.spell_conditions.card_id))).matched

    registry.register_trigger_condition(PREFIX + 'outcast', outcast)
    registry.register_trigger_condition(PREFIX + 'kindred', kindred)
    registry.register_behavior(PREFIX + 'draw', lambda c: (Draw(c.player_id, source_id=c.source_id),))
    registry.register_behavior(PREFIX + 'hero_immune', lambda c: (GrantKeyword(
        c.state.players[c.player_id].hero_id, Keyword.IMMUNE, c.source_id, duration=IMMUNITY),))
    for entry in data['reviewed_templates']:
        registry.register_assemble_on_play_source(AssembleOnPlaySource(entry['card_id'],
            entry['original_behavior_id'], entry['condition_id'], entry['kind']))
        registry.register_assemble_template(AssembleTemplate(entry['card_id'],
            AssemblePrefix('on_play', tuple(Keyword(key) for key in entry['keywords']),
                condition_id=entry['condition_id']),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
