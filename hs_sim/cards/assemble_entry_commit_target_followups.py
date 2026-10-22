"""Four actual ordinary windows bind original entry, attack, play and cast facts."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.effects import ChoiceOption, Draw, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import from_event
from hs_sim.engine.model import CardType, Keyword
from hs_sim.engine.pools import GenerateFromPool
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from . import hand_entry_spell_provider_card as native_panda
from .simple_timing_p06_cards import committed, minion_identity

PANDA, SHAW, WEBWEAVER, FRAGMENT = SOURCES = ('BE_997', 'CAP_005', 'EDR_540', 'END_026')
PREFIX = 'cards.assemble_entry_commit_target.'
SHAW_CALLBACK = 'cards.simple_followup_p64.shaw_selected'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-entry-commit-target-followups-v1.json'
BATCH_HASH = 'd3704033fc221f809f56ecb0a0defdef7b7b8cc9ff4a5acf5b94191877fcfe2f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies']) or
            canonical_digest(data['spell_query']) != data['spell_query_sha256']):
        raise TargetValidationError('Entry/commit/target assembly requires four complete original ordinary sources')
    return data


def register_assemble_entry_commit_target_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        original = registry.card(row['record']['id'])
        if canonical_digest(asdict(original)) != row['definition_sha256']:
            raise TargetValidationError('Entry/commit/target assembly changed a complete original source')
        registry.behavior(original.triggers[0].behavior_id)
    if (native_panda.POOL != data['spell_pool_id'] or
            canonical_digest(asdict(native_panda.QUERY)) != data['spell_query_sha256'] or
            SHAW_CALLBACK != data['original_shaw_callback']):
        raise TargetValidationError('Entry/commit/target assembly changed the complete original spell domain or continuation')
    registry.behavior(SHAW_CALLBACK)

    def external_own_hand_entry(c):
        entry = from_event(c.state, c.event)
        if c.state.entities[c.source_id].controller != c.player_id:
            raise ResolutionError('Pandaren assembly requires its original captured observer controller')
        return entry.player_id == c.player_id and entry.source_id != c.source_id

    def friendly_stealth_attack(c):
        if c.event is None or c.event.kind != 'stealth_lost':
            raise ResolutionError('Shaw assembly requires its original stealth-loss event')
        if dict(c.event.data).get('reason') != 'attack':
            return False
        attacker = c.state.entities[c.event.source_id]
        return attacker.kind == CardType.MINION and attacker.controller == c.player_id

    def repeated_committed_minion(c):
        record = committed(c)
        if record.player_id != c.player_id or record.kind != CardType.MINION or record.source_id == c.source_id:
            return False
        identity = minion_identity(record)
        return any(minion_identity(previous) == identity for previous in
            played_cards(c.state, c.player_id, before_id=record.id, kind=CardType.MINION))

    def own_minion_target_spell(c):
        if c.event is None or c.event.kind != 'spell_cast_finished':
            raise ResolutionError('Fragment assembly requires its original successful spell completion')
        cast = cast_record(c.state, dict(c.event.data)['cast_id'])
        if ((cast.source_id, cast.player_id, cast.target_id) != (c.event.source_id, c.event.player_id, c.event.target_id) or
                not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted):
            raise ResolutionError('Fragment assembly lost its actual original successful cast')
        return (cast.player_id == c.player_id and living_source(c) and cast.target_origin is not None and
            cast.target_origin.kind == CardType.MINION)

    def reduce_hand_three(c):
        options = tuple(ChoiceOption(json.dumps(asdict(CardReference.capture(c.state.entities[i])), sort_keys=True),
            'Original hand card') for i in c.state.players[c.player_id].hand)
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=SHAW_CALLBACK),) if options else ()

    for name, predicate in (('external_own_hand_entry', external_own_hand_entry),
            ('friendly_stealth_attack', friendly_stealth_attack), ('repeated_committed_minion', repeated_committed_minion),
            ('own_minion_target_spell', own_minion_target_spell)):
        registry.register_trigger_condition(PREFIX + name, predicate)
    for name, body in {
            'spells_for_both': lambda c: tuple(GenerateFromPool(pid, native_panda.POOL, native_panda.QUERY,
                source_id=c.source_id) for pid in (c.player_id, 3-c.player_id)),
            'reduce_hand_three': reduce_hand_three,
            'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
            }.items():
        registry.register_behavior(PREFIX + name, body)
    for entry in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(entry['card_id'], entry['event'],
            entry['original_behavior_id'], entry['condition_id']))
        registry.register_assemble_template(AssembleTemplate(entry['card_id'],
            AssemblePrefix(entry['event'], tuple(Keyword(key) for key in entry['keywords']), condition_id=entry['condition_id']),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
