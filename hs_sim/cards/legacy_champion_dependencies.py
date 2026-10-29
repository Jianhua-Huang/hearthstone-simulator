"""Exact legacy champions reachable from the still-incomplete faction source."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.effects import ChangeControl, ChoiceOption, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import card_summon
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position, minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/legacy-champion-dependencies-v1.json'
BATCH_HASH = '2423823df804b949c9157ee1240881bd86e414aa671e6f07a6c9b6691580e3ac'
CARDS = ('EX1_383', 'EX1_559', 'EX1_414', 'EX1_110', 'EX1_016', 'RLK_593')
REUSED = dict(zip(CARDS[:4], ('CORE_EX1_383', 'CORE_EX1_559', 'CORE_EX1_414', 'CORE_EX1_110')))
PREFIX = 'cards.legacy_champion.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or
            tuple(v['record']['id'] for v in d['cards']) != CARDS or
            [v['record']['id'] for v in d['existing_dependencies']] != ['EX1_383t', 'EX1_110t', 'CS2_029'] or
            len(d['official_observations']) != 12 or
            any(d[k] for k in ('dependencies', 'evidence_only', 'new_standard_roots',
                'formal_pool_complete', 'cn_calibrated', 'membership_uses_executable_coverage'))):
        raise TargetValidationError('Legacy champions require complete original faces and explicit dependency scope')
    for row in (*d['cards'], *d['existing_dependencies'], d['source_parent']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Legacy champion lost its complete original record')
    if (d['source_parent']['record']['id'] != 'WON_113' or
            d['source_parent']['child_ids'] != [2760, 890, 1080, 2949, 9, 338, 1721, 420, 86383, 62176, 1730, 318] or
            not {v['record']['dbf_id'] for v in d['cards']} <= set(d['source_parent']['child_ids'])):
        raise TargetValidationError('Legacy dependency changed its actual faction-source provenance')
    return d


def prepared_cards(registry):
    d = load_batch()
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Legacy champion lost an unchanged named dependency: ' + cid)
    result = []
    for row in d['cards']:
        raw = row['record']; cid = raw['id']; recipe = row['recipe']
        if raw['type'] != 'MINION' or raw['collectible'] is not True:
            raise TargetValidationError('Legacy champion requires its original collectible minion face')
        if cid in REUSED:
            original = registry.card(REUSED[cid])
            if (recipe['kind'] != 'complete_native_face' or recipe['native_card_id'] != original.id or
                    canonical_digest(asdict(original)) != recipe['native_definition_sha256'] or
                    canonical_digest(recipe['native_definition']) != recipe['native_definition_sha256']):
                raise TargetValidationError('Legacy face cannot borrow a changed or partial Core implementation')
            card = replace(original, id=cid, name=raw['name'], metadata=metadata_from_record(raw))
            if cid == 'EX1_110':
                if recipe.get('deathrattle_override') != PREFIX + 'baine':
                    raise TargetValidationError('Legacy Cairne requires its explicit original death position')
                card = replace(card, deathrattle=PREFIX + 'baine')
        else:
            kind = 'random_enemy_control' if cid == 'EX1_016' else 'current_original_deck_minion_stat_double'
            if recipe['kind'] != kind:
                raise TargetValidationError('Unreviewed native legacy champion effect')
            extra = {'deathrattle': PREFIX + 'control'} if cid == 'EX1_016' else {'on_play': PREFIX + 'double_deck'}
            card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
                attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), **extra)
        if (any(getattr(card, k) != raw[k] for k in ('cost', 'attack', 'health')) or
                canonical_digest(asdict(card)) != row['definition_sha256']):
            raise TargetValidationError('Legacy champion differs from its complete reviewed native definition')
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Legacy champion cannot overwrite an existing identity: ' + cid)
        result.append(card)
    return tuple(result)


def register_legacy_champion_dependencies(registry):
    cards = prepared_cards(registry)

    def control(c):
        choices = tuple(ChoiceOption(json.dumps(asdict(BoardPresenceReference.capture(c.state, eid)), sort_keys=True),
            '随机敌方随从') for eid in minions(c, registry, 3 - c.player_id))
        return (RequestChoice(c.player_id, choices, c.source_id, min_count=0, max_count=0,
            sample_size=1, on_select=PREFIX + 'take_control'),) if choices else ()

    def take_control(c):
        if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options) != 1:
            raise ResolutionError('Sylvanas requires its original one automatically sampled board presence')
        ref = BoardPresenceReference(**json.loads(c.choice.choice.options[0].id))
        entity = resolve_board_presence(c.state, ref)
        if (entity is None or not entity.active or entity.health <= 0 or entity.doomed or
                entity.controller != 3 - c.player_id):
            return ()
        return (ChangeControl(entity.id, c.player_id),)

    def double_deck(c):
        # Capture the original ordered residences and current operands before
        # any notification can move, replace or buff another deck card.
        return tuple(BuffStoredCard(CardReference.capture(entity), entity.attack, entity.health, c.source_id)
            for eid in c.state.players[c.player_id].deck for entity in (c.state.entities[eid],)
            if entity.kind == CardType.MINION)

    def baine(c):
        return (card_summon(c, c.player_id, 'EX1_110t', position=deathrattle_position(c)),)

    for name, body in (('control', control), ('take_control', take_control), ('double_deck', double_deck), ('baine', baine)):
        registry.register_behavior(PREFIX + name, body)
    for card in cards:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
