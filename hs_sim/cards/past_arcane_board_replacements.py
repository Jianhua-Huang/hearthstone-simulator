"""Original Arcane hand, named board and cost-based replacement consumers."""
import json
from pathlib import Path

from hs_sim.engine.cross_zone import cost_value
from hs_sim.engine.effects import AddToHand, ChangeManaCrystals, Destroy, Draw, InvokeBehavior, RefreshMana
from hs_sim.engine.model import (CardDefinition, CardType, HandDerivativeSpec, Keyword, SpellSchool, TargetSpec, Zone)
from hs_sim.engine.named_transform_groups import TransformMinionsToCard
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-arcane-board-replacements-v1.json'
BATCH_HASH = '85afd88eb38e1ed82f9791f2d5d86bbf621332134d6fda7b8a3fdda7406d032f'
LEAVES = ('AT_043', 'AV_218', 'DAL_177')
TOKENS = ('CS2_013t', 'AV_218t', 'DAL_177ts')
DEPENDENCIES = LEAVES+TOKENS
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_arcane_board_replacements.'
MINION = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or canonical_digest(reference) != data['reference_canonical_sha256'] or
            tuple(data['collectible_leaf_ids']) != LEAVES or tuple(row['record']['id']for row in data['dependencies']) != DEPENDENCIES or
            len(data['official_observations']) != 12 or not set(LEAVES) <= set(reference['candidate_ids']) or
            data['numeric_normalizations'] != {'CS2_013t':{'cost':0}} or
            any(data[k]for k in ('cards', 'existing_dependencies', 'evidence_only', 'skipped', 'display_normalizations',
                'source_scope_bound', 'formal_pool_complete', 'cn_calibrated')) or
            any(canonical_digest(row['record']) != row['record_sha256']for row in data['dependencies'])):
        raise TargetValidationError('Original Arcane replacements changed their complete pinned sources')
    return data


def register_past_arcane_board_replacements(registry):
    prepared = []
    for row in load_batch()['dependencies']:
        raw = row['record']; cid = raw['id']
        if cid in registry.cards:
            raise TargetValidationError('Original Arcane replacements cannot overwrite '+cid)
        if cid == 'AV_218t':
            fields = dict(attack=raw['attack'], health=raw['health'])
        else:
            fields = dict(on_play=PREFIX+('calling' if cid in ('DAL_177', 'DAL_177ts') else cid),
                spell_school=SpellSchool.ARCANE if cid != 'CS2_013t' else None)
            if cid in ('DAL_177', 'DAL_177ts'): fields['targeting'] = MINION
            if cid == 'DAL_177': fields.update(keywords=(Keyword.TWINSPELL,),
                hand_derivatives=(HandDerivativeSpec(Keyword.TWINSPELL, 'DAL_177ts'),))
        card = CardDefinition(cid, raw['name'], CardType(raw['type'].lower()),
            cost=0 if cid == 'CS2_013t' else raw['cost'], metadata=metadata_from_record(raw), **fields)
        registry._validate_card(card)
        if cid in registry.pool_cards and registry.pool_card(cid) != PoolCard.from_definition(card):
            raise TargetValidationError('Original Arcane replacements differ from printed metadata: '+cid)
        prepared.append(card)

    def communion(c):
        refs = tuple(CardReference.capture(c.state.entities[i]) for i in c.state.players[c.player_id].hand)
        return (*tuple(DiscardCard(ref, c.source_id) for ref in refs), InvokeBehavior(PREFIX+'communion_mana', c.source_id, c.player_id))
    def communion_mana(c):
        player = c.state.players[c.player_id]
        if max(player.max_mana, player.mana) >= player.mana_cap:
            return (AddToHand(c.player_id, 'CS2_013t', c.source_id),)
        growth = min(10, max(0, player.mana_cap-player.max_mana))
        return (ChangeManaCrystals(c.player_id, 10, filled=True),) + ((RefreshMana(c.player_id, 10-growth),) if growth < 10 else ())
    def polymorph(c):
        refs = tuple(MinionReference.capture(e) for player in (c.player_id, 3-c.player_id)
            for i in c.state.players[player].board for e in (c.state.entities[i],)
            if e.kind == CardType.MINION and e.active and not e.doomed and e.health > 0)
        return (TransformMinionsToCard(refs, 'AV_218t', c.source_id),)
    def calling(c):
        target = c.state.entities[c.target_id]
        cost = cost_value(registry, target, 'local')
        query = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost, max_cost=cost)
        request = SummonFromPool(target.controller, 'constructed.cards', query, source_id=c.source_id,
            cause=SummonCause.capture(c))
        return (Destroy(target.id, c.source_id), request, request)
    bodies = {'AT_043':communion, 'communion_mana':communion_mana, 'AV_218':polymorph, 'calling':calling,
        'CS2_013t':lambda c:(Draw(c.player_id, 1, c.source_id),)}
    for key, body in bodies.items(): registry.register_behavior(PREFIX+key, body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
