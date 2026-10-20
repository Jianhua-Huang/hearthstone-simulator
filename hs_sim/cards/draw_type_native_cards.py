"""Four native consumers share original draws, board copies and combat effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.cross_zone import TransformMinionIntoCopy
from hs_sim.engine.effects import Damage, InvokeBehavior, RandomDestroy, RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, Zone
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

DOMINATOR, WELLSPRING, MAGE, BOMB, WATER = 'BE_093', 'BE_251', 'BE_270', 'BE_554', 'CS2_033'
ROOTS = (DOMINATOR, WELLSPRING, MAGE, BOMB)
PREFIX = 'cards.draw_type_native.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/draw-type-native-followups-v1.json'
BATCH_HASH = 'cee9daec1eba2f5ba7968d9f869bfc30154a62e113592ee479bab7e4ca0482bc'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (WATER,) or
            any(data[k] for k in ('dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards']+data['existing_dependencies'])):
        raise TargetValidationError('Native draw-type consumers require their complete reviewed sources')
    return data


def register_draw_type_native_cards(registry):
    data = load_batch(); dependency, = data['existing_dependencies']
    if canonical_digest(asdict(registry.card(WATER))) != dependency['definition_sha256']:
        raise TargetValidationError('Icewheel Mage requires the original complete Water Elemental')

    def dominator(c):
        source = c.source
        if (source.zone != Zone.BOARD or not source.active or source.health <= 0 or source.doomed):
            return ()
        board = c.state.players[c.player_id].board
        if source.id not in board: return ()
        index = board.index(source.id); material = MinionReference.capture(source)
        eligible = set(minions(c, registry, c.player_id))
        return tuple(TransformMinionIntoCopy(MinionReference.capture(c.state.entities[board[i]]), material, c.source_id)
            for i in (index-1, index+1) if 0 <= i < len(board) and board[i] in eligible)

    def draws(c, count, reward):
        return (DrawPhysicalGroup(c.player_id, c.source_id, (DrawGroupSlot(),)*count,
            DrawGroupReward('non_minion_followup', behavior_id=PREFIX+reward)),)

    def original(c):
        row = c.draw
        if (row is None or row.card_id is None or (row.source_id, row.player_id) != (c.source_id, c.player_id) or
                not row.completed or registry.card(row.card_id).kind == CardType.MINION):
            raise ResolutionError('Native draw reward requires its original completed non-minion attempt')

    def water(c):
        original(c)
        return (SummonByCard(c.player_id, (SummonEntryMaterial(WATER),), SummonCause.capture(c)),)

    def refresh(c):
        original(c)
        return (RefreshMana(c.player_id, 2),)

    def wave(c):
        return (RandomDestroy(minions(c, registry, 3-c.player_id), c.source_id),
            Damage(c.state.players[3-c.player_id].hero_id, 3, c.source_id, DamageKind.SPELL))

    def repeat(c):
        if any(has_any_tribe(registry, c.state.entities[eid], ('mech',))
                for eid in minions(c, registry, c.player_id)):
            return wave(c)
        return ()

    registry.register_behavior(PREFIX+'dominator', lambda c: (
        InvokeBehavior(PREFIX+'dominator.now', c.source_id, c.player_id),))
    registry.register_behavior(PREFIX+'dominator.now', dominator)
    registry.register_behavior(PREFIX+'wellspring', lambda c: draws(c, 1, 'refresh'))
    registry.register_behavior(PREFIX+'mage', lambda c: draws(c, 2, 'water'))
    registry.register_behavior(PREFIX+'refresh', refresh)
    registry.register_behavior(PREFIX+'water', water)
    registry.register_behavior(PREFIX+'bomb', lambda c: (*wave(c),
        InvokeBehavior(PREFIX+'bomb.repeat', c.source_id, c.player_id)))
    registry.register_behavior(PREFIX+'bomb.repeat', repeat)
    for item in data['cards']:
        raw = item['record']; cid = raw['id']; fields = {}
        if cid == WELLSPRING:
            if (raw['type'], raw['cost'], raw['health']) != ('LOCATION', 3, 2):
                raise TargetValidationError('Wellspring requires its actual Location face')
            kind = CardType.LOCATION; fields.update(durability=raw['health'], on_use=PREFIX+'wellspring')
        elif cid == BOMB:
            if (raw['type'], raw['cost'], raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 5, 2):
                raise TargetValidationError('Bomb requires its complete Fire spell face')
            kind = CardType.SPELL; fields.update(on_play=PREFIX+'bomb', spell_school=SCHOOLS[2])
        else:
            if (raw['type'] != 'MINION' or raw['tags'].get('BATTLECRY') != 1 or
                    (raw['cost'], raw['attack'], raw['health']) != ((5, 4, 5) if cid == DOMINATOR else (5, 2, 4))):
                raise TargetValidationError('Native draw/copy Battlecry face changed')
            kind = CardType.MINION
            fields.update(attack=raw['attack'], health=raw['health'],
                battlecry=PREFIX+('dominator' if cid == DOMINATOR else 'mage'))
        definition = CardDefinition(cid, raw['name'], kind, cost=raw['cost'], metadata=metadata_from_record(raw), **fields)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
