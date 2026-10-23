"""Historical one-cost consumers of original mana, Overload and hand-play facts."""
import json
from pathlib import Path

from hs_sim.engine.effects import GainArmor, RefreshMana, SpendMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.play_history import played_cards, play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record


VALISHJ, ANCIENT, TROGG, ARTIFICER = 'TSC_828', 'OG_051', 'LOE_018', 'LOOT_231'
LEAVES = DEPENDENCIES = (VALISHJ, ANCIENT, TROGG, ARTIFICER)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_one_cost_mana_overload.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-mana-overload-v1.json'
BATCH_HASH = 'd8767965151bcf0b0061b688145b9d145936881bb5ea932b6b030ccfee825805'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != LEAVES or
            data['display_normalizations'] != {VALISHJ: {'@': ''}} or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped', 'numeric_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in data['dependencies'])):
        raise TargetValidationError('Historical mana consumers lost complete source facts')
    return data


def register_past_one_cost_mana_overload_cards(registry):
    def valishj(c):
        count = len(played_cards(c.state, c.player_id, turn=c.state.turn, kind=CardType.SPELL))
        return (RefreshMana(c.player_id, count),) if count else ()

    def ancient(c):
        original = MinionReference.capture(c.source) if living_source(c) else None
        return (SpendMana(c.player_id, None, c.source_id, source_growth=original),)

    def trogg(c):
        event = c.event
        if event is None or event.kind != 'overload_added':
            raise ResolutionError('Trogg requires its original actual Overload notification')
        row = next((x for x in c.state.overload_history if x.event_sequence == event.sequence), None)
        if row is None or (row.player_id, row.amount) != (event.player_id, event.amount):
            raise ResolutionError('Trogg lost its exact committed Overload increment')
        return (BuffCapturedMinion(MinionReference.capture(c.source), attack=row.amount, source_id=c.source_id),) \
            if row.player_id == c.player_id and living_source(c) else ()

    def artificer(c):
        event = c.event
        if event is None or event.kind != 'spell_cast_started':
            raise ResolutionError('Artificer requires the original accepted manual spell')
        row = cast_record(c.state, dict(event.data)['cast_id'])
        if (row.source_id, row.player_id, row.target_id) != (event.source_id, event.player_id, event.target_id):
            raise ResolutionError('Artificer changed its original spell acceptance')
        if row.player_id != c.player_id or row.origin != 'hand' or row.iteration != 1 or not living_source(c):
            return ()
        play = play_record(c.state, row.play_id)
        if ((play.source_id, play.player_id, play.kind) != (row.source_id, row.player_id, CardType.SPELL) or
                play.submitted_cost is None):
            raise ResolutionError('Artificer lost the original immutable hand price')
        amount = play.submitted_cost.quote.amount
        return (GainArmor(c.player_id, amount),) if amount else ()

    bodies = {VALISHJ: valishj, ANCIENT: ancient, TROGG: trogg, ARTIFICER: artificer}
    for cid, body in bodies.items(): registry.register_behavior(PREFIX+cid, body)
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or raw['collectible'] is not True or
                type(raw['attack']) is not int or type(raw['health']) is not int):
            raise TargetValidationError('Historical mana consumer lost its complete native minion')
        fields = ({'battlecry': PREFIX+cid} if cid in (VALISHJ, ANCIENT) else
            {'triggers': (TriggerSpec('overload_added' if cid == TROGG else 'spell_cast_started', PREFIX+cid),)})
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
