"""Ten original Nature Choose One cards with explicit real combined bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import ChangeManaCrystals, Damage, Draw, Heal, InvokeBehavior
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, ChooseBranch,
    ChooseOneSpec, DamageKind, HealingKind, Keyword, SpellSchool, TargetMode, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/past-nature-choose-one-v1.json'
BATCH_HASH = 'ef7370297678b0926f57e398327b202a67e498f5e0d94ae6552b17977f489819'
POLICY = 'cn37-local-past-nature-choose-one-v1'
PREFIX = 'cards.past_nature_choose.'
LAYOUT = {
    'AT_037': dict(branches=['AT_037a', 'AT_037b'], targets=['character', 'none'], space=[False, True],
        both_target='character', both_space=False, order=['damage2', 'saplings2']),
    'DAL_350': dict(branches=['DAL_350a', 'DAL_350b'], targets=['minion', 'character'], space=[False, False],
        both_target='character', both_space=False, order=['minion_only_damage2', 'heal5']),
    'DRG_311': dict(branches=['DRG_311b', 'DRG_311a'], targets=['minion', 'none'], space=[False, True],
        both_target='optional_minion', both_space=False, order=['treant1', 'original_minion_health2_taunt']),
    'EX1_155': dict(branches=['EX1_155a', 'EX1_155b'], targets=['minion', 'minion'], space=[False, False],
        both_target='minion', both_space=False, order=['original_minion_attack4_health4_taunt']),
    'GVG_041': dict(branches=['GVG_041b', 'GVG_041a'], targets=['none', 'minion'], space=[True, False],
        both_target='optional_minion', both_space=False, order=['wisps5', 'original_minion_attack5_health5_taunt']),
    'SW_422': dict(branches=['SW_422b', 'SW_422a'], targets=['none', 'none'], space=[False, True],
        both_target='none', both_space=False, order=['treant1', 'actual_friendly_minions_attack1']),
    'TRL_254': dict(branches=['TRL_254a', 'TRL_254b'], targets=['minion', 'none'], space=[False, True],
        both_target='optional_minion', both_space=False, order=['raptors2', 'original_minion_attack2_health4_taunt']),
    'TSC_650': dict(branches=['TSC_650a', 'TSC_650d'], targets=['none', 'none'], space=[True, True],
        both_target='none', both_space=True, order=['orca1', 'otters6']),
    'ULD_135': dict(branches=['ULD_135a', 'ULD_135b'], targets=['none', 'character'], space=[True, False],
        both_target='character', both_space=False, order=['ancient1', 'heal12']),
    'WON_014': dict(branches=['WON_014s', 'WON_014s2'], targets=['none', 'none'], space=[False, False],
        both_target='none', both_space=False, order=['empty_crystal1', 'draw1']),
}
ROOTS = tuple(LAYOUT)
CHOICES = tuple(cid for layout in LAYOUT.values() for cid in layout['branches'])
TOKENS = ('DRG_311t', 'CS2_231', 'SW_422t', 'TRL_254t', 'ULD_135at')
EXISTING = ('AT_037t', 'TSC_650t', 'TSC_650t4')
EVIDENCE = ('DRG_311e', 'EX1_155ae', 'EX1_155be', 'GVG_041c', 'SW_422e', 'TRL_254ae')


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            tuple(v['record']['id'] for v in d['cards']) != ROOTS or
            tuple(v['record']['id'] for v in d['dependencies']) != (*CHOICES, *TOKENS) or
            tuple(v['record']['id'] for v in d['existing_dependencies']) != EXISTING or
            tuple(v['record']['id'] for v in d['evidence_only']) != EVIDENCE or
            d['branch_layout'] != LAYOUT or len(d['official_observations']) != 22 or
            len(d['complete_druid_Nature_inventory']) != 85 or
            not set(ROOTS) <= set(d['original_missing_native_ids']) or
            any(d[k] for k in ('new_standard_roots', 'membership_uses_executable_coverage',
                'source_scope_bound', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Nature Choose One requires complete real faces and explicit reviewed branches')
    for row in d['cards'] + d['dependencies'] + d['existing_dependencies'] + d['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Nature Choose One lost a complete original record')
    return d


def target_spec(domain):
    if domain == 'none':
        return None
    if domain == 'character':
        return TargetSpec()
    if domain not in ('minion', 'optional_minion'):
        raise TargetValidationError('Unknown reviewed Nature branch target domain')
    return TargetSpec(mode=TargetMode.IF_AVAILABLE if domain == 'optional_minion' else TargetMode.REQUIRED,
        zones=(Zone.BOARD,), kinds=(CardType.MINION,))


def register_past_nature_choose_one(registry):
    d = load_batch()
    for row in d['existing_dependencies']:
        cid = row['record']['id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Nature choice changed its complete original named minion: ' + cid)
    raws = {row['record']['id']: row['record'] for row in d['cards'] + d['dependencies']}
    prepared = []
    for row in d['cards'] + d['dependencies']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); fields = {}
        if cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Nature choice cannot replace a different native identity: ' + cid)
        if cid in ROOTS:
            if kind != CardType.SPELL or not raw['collectible'] or raw['tags'].get('CHOOSE_ONE') != 1:
                raise TargetValidationError('Nature choice lost its original collectible Choose One root')
            layout = LAYOUT[cid]
            branches = tuple(ChooseBranch(branch, raws[branch]['name'], PREFIX + branch,
                targeting=target_spec(domain), requires_board_space=space)
                for branch, domain, space in zip(layout['branches'], layout['targets'], layout['space']))
            fields.update(on_play='engine.choose_one', choose_one=ChooseOneSpec(branches,
                ChooseBranch(cid + ':combined', '两者兼得', PREFIX + cid + ':combined',
                    targeting=target_spec(layout['both_target']), requires_board_space=layout['both_space'])))
        elif cid in CHOICES:
            if kind != CardType.SPELL or raw['collectible']:
                raise TargetValidationError('Nature choice display faces must keep their original nonphysical role')
            fields['choice_only'] = True
        else:
            if kind != CardType.MINION or raw['text_en'] != ('<b>Taunt</b>' if cid == 'ULD_135at' else ''):
                raise TargetValidationError('Nature choice requires its exact original plain named minion')
            fields.update(attack=raw['attack'], health=raw['health'],
                keywords=(Keyword.TAUNT,) if cid == 'ULD_135at' else ())
        if kind == CardType.SPELL:
            fields['spell_school'] = SpellSchool.NATURE if raw['tags'].get('SPELL_SCHOOL') == 4 else None
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'] or 0,
            metadata=metadata_from_record(raw), **fields)
        if canonical_digest(asdict(card)) != row['definition_sha256']:
            raise TargetValidationError('Nature branch native material differs from its complete reviewed face')
        prepared.append(card)

    def summon(c, token, count):
        cause = SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(token),), cause) for _ in range(count))

    def buff(c, attack=0, health=0, taunt=False):
        if c.target_id is None:
            return ()
        original = BoardPresenceReference.capture(c.state, c.target_id)
        return (BuffCapturedMinion(original, attack, health, c.source_id),) + (
            (GrantCapturedKeyword(original, Keyword.TAUNT, c.source_id),) if taunt else ())

    def sow_buff(c):
        return tuple(BuffCapturedMinion(BoardPresenceReference.capture(c.state, eid), attack=1,
            source_id=c.source_id) for eid in minions(c, registry, c.player_id))

    def crystal_both(c):
        target = c.state.entities[c.target_id]
        damage = (Damage(target.id, 2, c.source_id, DamageKind.SPELL),) if target.kind == CardType.MINION else ()
        return (*damage, Heal(target.id, 5, c.source_id, HealingKind.SPELL))

    bodies = {
        'AT_037a': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        'AT_037b': lambda c: summon(c, 'AT_037t', 2),
        'AT_037:combined': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL), *summon(c, 'AT_037t', 2)),
        'DAL_350a': lambda c: (Damage(c.target_id, 2, c.source_id, DamageKind.SPELL),),
        'DAL_350b': lambda c: (Heal(c.target_id, 5, c.source_id, HealingKind.SPELL),),
        'DAL_350:combined': crystal_both,
        'DRG_311a': lambda c: summon(c, 'DRG_311t', 1),
        'DRG_311b': lambda c: buff(c, health=2, taunt=True),
        'DRG_311:combined': lambda c: (*summon(c, 'DRG_311t', 1), *buff(c, health=2, taunt=True)),
        'EX1_155a': lambda c: buff(c, attack=4),
        'EX1_155b': lambda c: buff(c, health=4, taunt=True),
        'EX1_155:combined': lambda c: buff(c, 4, 4, True),
        'GVG_041a': lambda c: buff(c, 5, 5, True),
        'GVG_041b': lambda c: summon(c, 'CS2_231', 5),
        'GVG_041:combined': lambda c: (*summon(c, 'CS2_231', 5), *buff(c, 5, 5, True)),
        'SW_422a': lambda c: summon(c, 'SW_422t', 1),
        'SW_422b': sow_buff,
        'SW_422:combined': lambda c: (*summon(c, 'SW_422t', 1), InvokeBehavior(PREFIX + 'sow_buff', c.source_id, c.player_id)),
        'TRL_254a': lambda c: buff(c, 2, 4, True),
        'TRL_254b': lambda c: summon(c, 'TRL_254t', 2),
        'TRL_254:combined': lambda c: (*summon(c, 'TRL_254t', 2), *buff(c, 2, 4, True)),
        'TSC_650a': lambda c: summon(c, 'TSC_650t', 1),
        'TSC_650d': lambda c: summon(c, 'TSC_650t4', 6),
        'TSC_650:combined': lambda c: (*summon(c, 'TSC_650t', 1), *summon(c, 'TSC_650t4', 6)),
        'ULD_135a': lambda c: summon(c, 'ULD_135at', 1),
        'ULD_135b': lambda c: (Heal(c.target_id, 12, c.source_id, HealingKind.SPELL),),
        'ULD_135:combined': lambda c: (*summon(c, 'ULD_135at', 1), Heal(c.target_id, 12, c.source_id, HealingKind.SPELL)),
        'WON_014s': lambda c: (ChangeManaCrystals(c.player_id, 1),),
        'WON_014s2': lambda c: (Draw(c.player_id, 1, c.source_id),),
        'WON_014:combined': lambda c: (ChangeManaCrystals(c.player_id, 1), Draw(c.player_id, 1, c.source_id)),
        'sow_buff': sow_buff,
    }
    for key, behavior in bodies.items():
        registry.register_behavior(PREFIX + key, behavior)
    for card in prepared:
        registry.register_card(card)
        if not card.choice_only:
            registry.register_pool_card(PoolCard.from_definition(card))
