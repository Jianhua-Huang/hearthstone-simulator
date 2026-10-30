"""Original Shaman ranged damage, ranked spells and physical hand upgrades.

All execution composes existing effects; the complete past source stays unbound.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption, CopyMinion, Damage, DamageBatch, Overload
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.mana_ranks import ManaRankFamily
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, DamageKind, HandProgressSpec, SpellSchool, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.captured_minion_spell_groups import DamageCapturedMinionGroup
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-shaman-ranks-overload-v1.json'
BATCH_HASH = '6880727ff9d5901e41e7927adc2f3ea0086893a1d504ef16328829c9b3365d78'
ROOTS = ('AT_051', 'BAR_044', 'DAL_009', 'EX1_251', 'GVG_038', 'LOOT_064')
RANKS = ('BAR_044', 'BAR_044t', 'BAR_044t2')
STONES = ('LOOT_064', 'LOOT_064t1', 'LOOT_064t2')
DEPENDENCIES = (*RANKS[1:], *STONES[1:])
PREFIX = 'cards.past_shaman_ranks_overload.'
RANK_FAMILY = ManaRankFamily(PREFIX + 'chain_lightning.ranks-v1', RANKS)
SCHEME_PROGRESS = HandProgressSpec('event', 1, on_complete=PREFIX + 'scheme_tick',
    repeat=True, event='turn_started', condition_id=PREFIX + 'own_start')


def make_definition(raw):
    cid = raw['id']
    if (cid not in ROOTS + DEPENDENCIES or raw['type'] != 'SPELL'
            or raw['collectible'] is not (cid in ROOTS) or type(raw['cost']) is not int
            or raw['tags'].get('SPELL_SCHOOL') != 4):
        raise TargetValidationError('Shaman ranked consumers require complete original spell faces')
    fields = {}
    if cid in RANKS + STONES:
        fields['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,),
            relation='friendly' if cid in STONES else 'any')
    elif cid == 'GVG_038':
        fields['targeting'] = TargetSpec()
    if cid == 'EX1_251':
        fields['use_rule'] = PREFIX + 'enemy_minion'
    if cid == 'DAL_009':
        if raw['tags'].get('TAG_SCRIPT_DATA_NUM_1') != 1:
            raise TargetValidationError('Hagatha Scheme lost its original base number')
        fields['hand_progress'] = SCHEME_PROGRESS
    if cid in STONES[:2]:
        if raw['tags'].get('TAG_SCRIPT_DATA_NUM_2') != 3:
            raise TargetValidationError('Sapphire Spellstone requires three actual overloaded crystals')
        fields['hand_progress'] = HandProgressSpec('event', 3, STONES[STONES.index(cid) + 1],
            event='overload_added', condition_id=PREFIX + 'own_overload',
            amount_basis='event_amount', upgrade_cost_policy='clear_local')
    return CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=PREFIX + cid, spell_school=SpellSchool.NATURE,
        metadata=metadata_from_record(raw), **fields)


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1
            or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES
            or d['evidence_only'] or [x['record']['id'] for x in d['existing_dependencies']] != ['TIME_013']
            or len(d['official_observations']) != 22
            or any(d[k] for k in ('complete_shaman_source_bound', 'new_standard_roots',
                'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Shaman ranked consumers changed original roles or claimed a partial source complete')
    for key in ('cards', 'dependencies', 'existing_dependencies'):
        for row in d[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('Shaman ranked consumers lost a complete original row')
    source = (ROOT / d['full_union_source_document']).resolve()
    if not source.is_relative_to(ROOT) or hashlib.sha256(source.read_bytes()).hexdigest() != d['full_union_source_sha256']:
        raise TargetValidationError('Shaman ranked consumers changed their complete original reference')
    return d


def register_past_shaman_ranks_overload(registry):
    d = load_batch()
    prepared = []
    for row in d['cards'] + d['dependencies']:
        card = make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Shaman ranked consumers cannot replace an original face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id) != PoolCard.from_definition(card):
            raise TargetValidationError('Shaman ranked consumers changed complete pool metadata')
        prepared.append(card)

    def minions(c, player_id=None):
        return tuple(sorted((c.state.entities[eid] for pid in ((1, 2) if player_id is None else (player_id,))
            for eid in c.state.players[pid].board
            if c.state.entities[eid].kind == CardType.MINION and c.state.entities[eid].active
            and c.state.entities[eid].health > 0 and not c.state.entities[eid].doomed),
            key=lambda e: (e.entered_order, e.id)))

    def elemental(c):
        # Freeze original recipients; existing branches and captured single-target
        # health effects retain independent rolls and ordinary reaction windows.
        refs = tuple(MinionReference.capture(e) for e in minions(c))
        choices = tuple(ChooseRandomEffects(c.player_id, c.source_id, tuple(
            ChoiceOption(str(n), str(n), (DamageCapturedMinionGroup((ref,), (n,), c.source_id),))
            for n in (4, 5))) for ref in refs)
        return (*choices, Overload(c.player_id, 2))

    def chain(c, amount):
        primary = c.state.entities[c.target_id]
        living = {e.id for e in minions(c, primary.controller)}
        if primary.id not in living:
            return ()
        board = c.state.players[primary.controller].board
        index = board.index(primary.id)
        near = tuple(eid for i in (index - 1, index + 1)
            if 0 <= i < len(board) and (eid := board[i]) in living)
        main = MinionReference.capture(primary)
        groups = tuple(DamageCapturedMinionGroup((main, MinionReference.capture(c.state.entities[eid])),
            (amount, amount), c.source_id) for eid in near)
        if len(groups) == 2:
            return (ChooseRandomEffects(c.player_id, c.source_id,
                tuple(ChoiceOption(str(eid), str(eid), (work,)) for eid, work in zip(near, groups))),)
        return groups if groups else (DamageCapturedMinionGroup((main,), (amount,), c.source_id),)

    def scheme(c):
        ability = progress_ability(c.source)
        if ability is None or ability.hand_progress != SCHEME_PROGRESS:
            raise ResolutionError('Hagatha Scheme requires its original physical held counter')
        return (DamageBatch(tuple(Damage(e.id, 1 + ability.progress_completions, c.source_id, DamageKind.SPELL)
            for e in minions(c))),)

    def own_overload(c):
        if c.event is None or c.event.kind != 'overload_added':
            raise ResolutionError('Sapphire requires an actual original overload increment')
        row = next((v for v in c.state.overload_history if v.event_sequence == c.event.sequence), None)
        if row is None or (row.player_id, row.amount, row.action) != (c.event.player_id, c.event.amount, c.event.action):
            raise ResolutionError('Sapphire lost its actual original overload ledger witness')
        return row.player_id == c.player_id

    def enemy_minion(c):
        enemy = next(p for p in c.observation['players'] if p['id'] == 3 - c.player_id)
        return any(e.get('kind') == CardType.MINION.value and e.get('health', 0) > 0
            and e.get('dormancy') is None and not e.get('interactable') for e in enemy['board'])

    def fork(c):
        from hs_sim.engine.effects import RandomDamageBatch
        return (RandomDamageBatch(tuple(e.id for e in minions(c, 3 - c.player_id)), 2, 2, c.source_id, DamageKind.SPELL),
            Overload(c.player_id, 2))

    def crackle(c):
        return (ChooseRandomEffects(c.player_id, c.source_id, tuple(ChoiceOption(str(n), str(n),
            (Damage(c.target_id, n, c.source_id, DamageKind.SPELL),)) for n in range(3, 7))), Overload(c.player_id, 1))

    def copies(c, count):
        original = BoardPresenceReference.capture(c.state, c.target_id)
        cause = SummonCause.capture(c)
        return tuple(CopyMinion(original, c.player_id, cause=cause) for _ in range(count))

    registry.register_trigger_condition(PREFIX + 'own_start', lambda c: c.event is not None and c.event.player_id == c.player_id)
    registry.register_trigger_condition(PREFIX + 'own_overload', own_overload)
    registry.register_use_rule(PREFIX + 'enemy_minion', enemy_minion, visibility='player')
    registry.register_behavior(PREFIX + 'scheme_tick', lambda c: ())
    for cid, body in (('AT_051', elemental), ('DAL_009', scheme), ('EX1_251', fork), ('GVG_038', crackle)):
        registry.register_behavior(PREFIX + cid, body)
    for n, cid in enumerate(RANKS, 2):
        registry.register_behavior(PREFIX + cid, lambda c, n=n: chain(c, n))
    for n, cid in enumerate(STONES, 1):
        registry.register_behavior(PREFIX + cid, lambda c, n=n: copies(c, n))
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_mana_rank_family(RANK_FAMILY)
