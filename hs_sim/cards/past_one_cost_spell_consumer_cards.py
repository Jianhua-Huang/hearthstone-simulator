"""Historical spell generation and original hand-play/Combo consumers."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardDefinition, CardType, DamageKind, Keyword, SpellSchool, TargetMode, TargetSpec, Zone
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.physical_draw_groups import DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record


BOOK, BURGLAR, WINNER, FROG, THIEF, TRACKER, CRYSTALSMITH, FROSTBREAKER, HERALD, PLUNDERER = (
    'KAR_009', 'KAR_069', 'DMF_122', 'YOG_524', 'SCH_350',
    'NX2_014', 'RLK_814', 'RLK_110', 'TRL_522', 'DMF_519')
LEAVES = (BOOK, BURGLAR, WINNER, FROG, THIEF, TRACKER, CRYSTALSMITH, FROSTBREAKER, HERALD, PLUNDERER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_spell_consumers.'
COUNT_FIELD = 'spells_played_this_turn'
COUNT_RULE = PREFIX + 'played_two_spells'
POOL_ID = 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-spell-consumers-v1.json'
BATCH_HASH = 'd6763c05a32be40ca9f634027c7afffb8aad4a4705b5c634f907165fbfa2892f'
MAGE_SPELLS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='specified', classes=(CardClass.MAGE,), include_neutral=False)
SECRETS = PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current', keywords_all=(Keyword.SECRET,))
OTHER_CLASS = PoolQuery(collectible=True, class_mode='other', include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    identities = tuple(row['record']['id'] for row in data['evidence_only'])
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            any(data[key] for key in ('cards', 'existing_dependencies', 'choice_only', 'skipped', 'numeric_normalizations')) or
            len(identities) != 98 or len(set(identities)) != 98 or identities != tuple(data['printed_overload_ids']) or
            set(identities) & set(LEAVES) or
            any(type(row['record']['tags'].get('OVERLOAD')) is not int or row['record']['tags']['OVERLOAD'] <= 0
                for row in data['evidence_only']) or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['dependencies'] + data['evidence_only'])):
        raise TargetValidationError('Historical spell consumers lost complete roots or printed Overload facts')
    return data


def register_past_one_cost_spell_consumer_cards(registry):
    data = load_batch()
    overload = PoolQuery(collectible=True, card_ids=tuple(data['printed_overload_ids']))

    def held(c, school):
        return tuple(i for i in c.state.players[c.player_id].hand
            if c.state.entities[i].kind == CardType.SPELL and
            registry.card(c.state.entities[i].card_id).spell_school == school)

    def crystal(c):
        return (BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),) if held(c, SpellSchool.SHADOW) else ()

    def frost(c):
        count = len(held(c, SpellSchool.FROST))
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack=count, source_id=c.source_id),) if count else ()

    def herald(c):
        count = len(played_cards(c.state, c.player_id, turn=c.state.turn, kind=CardType.SPELL))
        return (Damage(c.target_id, 2, c.source_id, DamageKind.MINION_ABILITY),) if count >= 2 and c.target_id is not None else ()

    def plunderer(c):
        if c.combo is None:
            raise ResolutionError('Prize Plunderer requires its original independent Combo')
        original_play = c.play.id if c.play is not None else c.combo.play_id
        count = sum(p.id != original_play for p in played_cards(c.state, c.player_id, turn=c.state.turn))
        return (Damage(c.target_id, count, c.source_id, DamageKind.MINION_ABILITY),) if count and c.target_id is not None else ()

    registry.register_player_target_rule(PlayerTargetRuleSpec(COUNT_RULE, 'v1'),
        lambda c: c.observation['players'][c.player_id - 1][COUNT_FIELD] >= 2)
    bodies = {
        BOOK: lambda c: (GenerateFromPool(c.player_id, POOL_ID, MAGE_SPELLS, source_id=c.source_id),),
        BURGLAR: lambda c: (GenerateFromPool(c.player_id, POOL_ID, OTHER_CLASS, source_id=c.source_id),),
        WINNER: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, SECRETS, source_id=c.source_id),),
        FROG: lambda c: (GenerateFromPool(c.player_id, POOL_ID, overload, source_id=c.source_id),),
        THIEF: lambda c: (DiscoverFromPool(c.player_id, POOL_ID, MAGE_SPELLS, source_id=c.source_id),),
        TRACKER: lambda c: (DrawPhysicalGroup(c.player_id, c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,)), current_cost=1),)),),
        CRYSTALSMITH: crystal, FROSTBREAKER: frost, HERALD: herald, PLUNDERER: plunderer,
    }
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical spell consumer lost its complete native body')
        fields = {'combo': PREFIX + cid, 'keywords': (Keyword.COMBO,)} if cid in (THIEF, PLUNDERER) else {'battlecry': PREFIX + cid}
        if cid == PLUNDERER:
            fields.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE, (Zone.BOARD,), (CardType.MINION,),
                exclude_source=False), target_condition='combo')
        elif cid == HERALD:
            fields.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE, exclude_source=False), target_rule=COUNT_RULE)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
