"""Complete older conditional grants and independent Colossal dependencies."""
import json
from pathlib import Path

from hs_sim.engine.effects import EquipWeapon, GainArmor
from hs_sim.engine.model import AppendageSpec, CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember, OrderedSummonGroupSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position, minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p74-v1.json'
BATCH_HASH = '4b17a857e4b3466c845cbe8a42ba10e45d2dfca1e935416f0f58748a8e933417'
GOLDWING, HYDRALODON, HEAD, RIGHT_HEAD, CLAW, WEAPON, RIGHT_CLAW, SHELL, HAND, RIGHT_HAND = (
    'NX2_022', 'TSC_950', 'TSC_950t', 'TSC_950t2', 'TSC_937t', 'TSC_937t2', 'TSC_937t3',
    'TSC_026t', 'TID_712t', 'TID_712t2')
COLLECTIBLE_ROOTS = ()
DEPENDENCIES = (GOLDWING, HYDRALODON, HEAD, RIGHT_HEAD, CLAW, WEAPON, RIGHT_CLAW, SHELL, HAND, RIGHT_HAND)
ROOTS = DEPENDENCIES
PREFIX = 'cards.simple_followup_p74.'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or d['cards'] or d['collectible_candidate_roots']
            or d['existing_dependencies'] or d['skipped']
            or tuple(x['record']['id'] for x in d['dependencies']) != DEPENDENCIES):
        raise TargetValidationError('P74 complete dependency scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for key in ('dependencies', 'evidence_only') for x in d[key]):
        raise TargetValidationError('P74 complete source row changed')
    return d


def register_simple_followup_p74_cards(registry):
    d = load_batch()

    def goldwing(c):
        if not living_source(c) or not any(c.state.entities[i].kind == CardType.MINION
                and has_any_tribe(registry, c.state.entities[i], ('mech',))
                for i in c.state.players[c.player_id].hand):
            return ()
        return (GrantCapturedKeyword(MinionReference.capture(c.source), Keyword.WINDFURY, c.source_id),)

    def hydralodon(c):
        return tuple(GrantCapturedKeyword(MinionReference.capture(c.state.entities[i]), Keyword.RUSH, c.source_id)
            for i in minions(c, registry, c.player_id) if c.state.entities[i].card_id in (HEAD, RIGHT_HEAD))

    def heads(c):
        if not any(c.state.entities[i].card_id == HYDRALODON for i in minions(c, registry, c.player_id)):
            return ()
        position = deathrattle_position(c)
        members = tuple(OrderedGroupMember('head-' + str(i), SummonEntryMaterial(HEAD),
            None if position is None else position+i) for i in range(2))
        return (SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id, SummonCause.capture(c), members)),)

    for name, body in dict(goldwing=goldwing, hydralodon=hydralodon, heads=heads,
            claw=lambda c: (EquipWeapon(c.player_id, WEAPON),),
            shell=lambda c: (GainArmor(c.player_id, 8),)).items():
        registry.register_behavior(PREFIX + name, body)
    for item in d['dependencies']:
        raw = item['record']; cid = raw['id']; kw = {}
        if cid == GOLDWING: kw.update(keywords=(Keyword.RUSH,), battlecry=PREFIX+'goldwing')
        if cid == HYDRALODON:
            kw.update(keywords=(Keyword.COLOSSAL,), battlecry=PREFIX+'hydralodon',
                colossal=(AppendageSpec(HEAD, 'left'), AppendageSpec(RIGHT_HEAD, 'right')))
        if cid in (HEAD, RIGHT_HEAD): kw['deathrattle'] = PREFIX+'heads'
        if cid in (CLAW, RIGHT_CLAW): kw.update(keywords=(Keyword.RUSH,), deathrattle=PREFIX+'claw')
        if cid == SHELL: kw.update(keywords=(Keyword.TAUNT,), deathrattle=PREFIX+'shell')
        if cid in (HAND, RIGHT_HAND): kw['keywords'] = (Keyword.IMMUNE_WHILE_ATTACKING,)
        weapon = cid == WEAPON
        definition = CardDefinition(cid, raw['name'], CardType.WEAPON if weapon else CardType.MINION,
            cost=raw['cost'], attack=0 if cid == SHELL else raw['attack'],
            health=0 if weapon else raw['health'], durability=raw['health'] if weapon else 0,
            metadata=metadata_from_record(raw), **kw)
        registry.register_card(definition)
        if cid not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(definition))
