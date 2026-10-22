"""Eight real ordinary subjects borrow existing public effects and native views."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import Draw, InvokeBehavior, RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.guarded_corpse_spends import SpendCorpsesForMinion
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import BoardPresenceReference, CardType, Keyword, Zone
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .reactive_growth_cards import buff_source

IRONBORN, DRAGONBANE, ACOLYTE, BOLVAR, DIREHORN, BARKSHIELD, ROACH, RESCUER = SOURCES = (
    'BE_996', 'CORE_DRG_256', 'CORE_RLK_121', 'CORE_SW_047', 'DINO_416', 'EDR_470', 'END_008', 'MEND_801')
RECRUIT = 'CS2_101t'
PREFIX = 'cards.assemble_death_shield_inspire.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-death-shield-inspire-followups-v1.json'
BATCH_HASH = '94783e3b340af2033eb1dcf85bcee4bc47f7b20faab68eb82dfaa0c8e5c1da71'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (RECRUIT,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            canonical_digest(data['recruit_profile']) != data['recruit_profile_sha256']):
        raise TargetValidationError('Death/shield/power assembly requires eight complete sources and the original recruit program')
    return data


def register_assemble_death_shield_inspire_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Death/shield/power assembly changed a complete original source')
    for entry in data['reviewed_templates']:
        original = registry.card(entry['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != entry['event'] or
                original.triggers[0].behavior_id != entry['original_behavior_id']):
            raise TargetValidationError('Death/shield/power assembly lost its actual native ordinary trigger')
        registry.behavior(entry['original_behavior_id'])
    program = data['recruit_profile']['id']
    if canonical_digest(asdict(registry.player_effect(program))) != data['recruit_profile_sha256']:
        raise TargetValidationError('Death/shield/power assembly changed the entire original recruit program')
    registry.behavior(program)
    registry.behavior(data['original_dragonbane_inner'])

    def original_death(c):
        if c.event is None or c.event.kind != 'minion_died':
            raise ResolutionError('Death reaction requires its actual original event')
        identity = dict(c.event.data).get('death_id')
        records = [row for row in c.state.death_history if type(identity) is int and row.id == identity]
        if len(records) != 1:
            raise ResolutionError('Death reaction lost its unique original death fact')
        record = records[0]
        if ((record.entity_id, record.entity_id, record.controller) !=
                (c.event.source_id, c.event.target_id, c.event.player_id) or
                registry.card(record.card_id).kind != CardType.MINION or record.zone != Zone.BOARD):
            raise ResolutionError('Death reaction borrowed another original minion death')
        return record

    def enemy_death_own_turn(c):
        record = original_death(c)
        interval = next((row for row in c.state.owner_turn_history if row.turn == record.turn), None)
        if interval is None:
            raise ResolutionError('Death reaction lost the original death turn')
        return record.controller != c.player_id and interval.player_id == c.player_id and living_source(c)

    def friendly_undead_death(c):
        record = original_death(c)
        return record.controller == c.player_id and has_any_tribe(registry, record, ('undead',))

    def other_friendly_death(c):
        record = original_death(c)
        return record.controller == c.player_id and record.entity_id != c.source_id and living_source(c)

    def shield_target(c):
        if c.event is None or c.event.kind != 'shield_lost':
            raise ResolutionError('Shield reaction requires its actual original event')
        try:
            return c.state.entities[c.event.target_id]
        except KeyError as exc:
            raise ResolutionError('Shield reaction lost its original target') from exc

    def friendly_minion_shield_lost(c):
        target = shield_target(c)
        return target.kind == CardType.MINION and target.controller == c.player_id

    def self_shield_lost(c):
        shield_target(c)
        return c.event.target_id == c.source_id

    def own_manual_power(c):
        return is_inspire(c.state, c.event, c.player_id)

    def ironborn_bonus(c):
        if not living_source(c):
            return ()
        presence = BoardPresenceReference.capture(c.state, c.source_id)
        return (BuffCapturedMinion(presence, 2, 2, c.source_id),
            GrantRandomBonusEffects(c.source_id, 1, c.source_id, presence))

    def corpse_reborn(c):
        if not living_source(c):
            return ()
        reference = MinionReference.capture(c.source)
        return (SpendCorpsesForMinion(reference, 3,
            (GrantCapturedKeyword(reference, Keyword.REBORN, c.source_id),), mode='missing_reborn'),)

    def self_health_two(c):
        return (buff_source(c, health=2),) if living_source(c) else ()

    for name, handler in (('enemy_death_own_turn', enemy_death_own_turn),
            ('friendly_undead_death', friendly_undead_death), ('other_friendly_death', other_friendly_death),
            ('friendly_minion_shield_lost', friendly_minion_shield_lost), ('self_shield_lost', self_shield_lost),
            ('own_manual_power', own_manual_power)):
        registry.register_trigger_condition(PREFIX + name, handler)
    bodies = {
        'ironborn_bonus': ironborn_bonus,
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'corpse_reborn': corpse_reborn,
        'hand_buff_five': lambda c: (RandomBuffStoredMinion(c.player_id, 5, 5, source_id=c.source_id),),
        'dragonbane_late': lambda c: (InvokeBehavior(data['original_dragonbane_inner'], c.source_id, c.player_id),),
        'self_health_two': self_health_two,
        'refresh_two': lambda c: (RefreshMana(c.player_id, 2),),
    }
    for name, handler in bodies.items():
        registry.register_behavior(PREFIX + name, handler)
    for entry in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(entry['card_id'],
            entry['event'], entry['original_behavior_id'], entry['condition_id']))
        registry.register_assemble_template(AssembleTemplate(entry['card_id'],
            AssemblePrefix(entry['event'], tuple(Keyword(key) for key in entry['keywords']),
                condition_id=entry['condition_id']),
            AssembleSuffix(entry['body_behavior_id'], tuple(entry['allowed_timings']))))
