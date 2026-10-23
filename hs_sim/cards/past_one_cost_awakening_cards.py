"""Historical damage, awakening and host-pool consumers of public effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import EquipWeapon
from hs_sim.engine.jade import CLASSIC, SummonJadeGolem
from hs_sim.engine.model import (
    CardDefinition, CardType, Keyword, LimitedTriggerSpec, SpellSchool, TriggerSpec,
)
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.spell_casts import cast_spells
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters, deathrattle_position


ENVOY, EGG, SUNGILL, GANARG, SWARMER, SWAMP, CAT, METAMORFIN, RAIDER, MACAW, CRIER, MERCHANT = (
    'BAR_843', 'BRM_022', 'BT_009', 'BT_121', 'CFM_691', 'GIL_816',
    'ULD_186', 'SW_451', 'DRG_024', 'UNG_912', 'GIL_580', 'ULD_282')
LEAVES = (ENVOY, EGG, SUNGILL, GANARG, SWARMER, SWAMP, CAT, METAMORFIN, RAIDER, MACAW, CRIER, MERCHANT)
WHELP, STREAMRUNNER, AXE = 'BRM_022t', 'BT_009t', 'CS2_106'
JADE_FORMS = ('CFM_712_t01', 'CFM_712_t04', 'CFM_712_t07', 'CFM_712_t20')
DEPENDENCIES = LEAVES + (WHELP, STREAMRUNNER)
EXISTING = (AXE,) + JADE_FORMS
COLLECTIBLE_ROOTS = ()
POOL_ID = 'constructed.cards'
PREFIX = 'cards.past_one_cost_awakening.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-one-cost-awakening-v1.json'
BATCH_HASH = '94cfcecb1995be229ff6cc758dab9378e8baac0207d6479af7fc63323784ed8d'
QUERIES = {
    SWAMP: PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('dragon',)),
    CAT: PoolQuery(kinds=(CardType.MINION,), collectible=True, keywords_all=(Keyword.REBORN,)),
    RAIDER: PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('pirate',)),
    MACAW: PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('beast',)),
    MERCHANT: PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=1, max_cost=1),
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(row['record']['id'] for row in data['dependencies']) != DEPENDENCIES or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != EXISTING or
            any(data[key] for key in ('cards', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {EGG: {'attack': 0}, SWAMP: {'attack': 0}} or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['dependencies'] + data['existing_dependencies'])):
        raise TargetValidationError('Historical awakening consumers lost their complete pinned sources')
    return data


def register_past_one_cost_awakening_cards(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Historical awakening requires its unchanged named Axe and Jade templates')
    if registry.jade_families[CLASSIC].forms != JADE_FORMS:
        raise TargetValidationError('Jade Swarmer requires the original shared classic artwork family')

    def envoy(c):
        count = sum(c.state.entities[i].health < c.state.entities[i].max_health
            for player in (1, 2) for i in characters(c, registry, player))
        return (BuffCapturedMinion(MinionReference.capture(c.source), count, 0, c.source_id),) if count else ()

    def egg(c):
        if c.event.target_id != c.source_id or c.event.amount <= 0:
            return ()
        return (SummonByCard(c.player_id, (SummonEntryMaterial(WHELP),), SummonCause.capture(c)),)

    def sungill(c):
        summon = SummonByCard(c.player_id, (SummonEntryMaterial(STREAMRUNNER),), SummonCause.capture(c))
        return (summon, summon)

    def metamorfin(c):
        if not living_source(c):
            return ()
        fel = any(registry.card(row.card_id).spell_school == SpellSchool.FEL
            for row in cast_spells(c.state, c.player_id, turn=c.state.turn, successful=True))
        return (BuffCapturedMinion(MinionReference.capture(c.source), 2, 2, c.source_id),) if fel else ()

    bodies = {
        ENVOY: envoy, EGG: egg, SUNGILL: sungill,
        GANARG: lambda c: (EquipWeapon(c.player_id, AXE),),
        SWARMER: lambda c: (SummonJadeGolem(c.player_id, c.source_id,
            position=deathrattle_position(c)),),
        METAMORFIN: metamorfin,
        CRIER: lambda c: (DrawMatching(c.player_id, PoolQuery(kinds=(CardType.MINION,),
            keywords_all=(Keyword.RUSH,)), 'skip', source_id=c.source_id),),
    }
    for cid, query in QUERIES.items():
        bodies[cid] = lambda c, query=query: (GenerateFromPool(c.player_id, POOL_ID,
            query, source_id=c.source_id),)
    for cid, body in bodies.items():
        registry.register_behavior(PREFIX + cid, body)

    for item in data['dependencies']:
        raw = item['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['cost'] != 1 or
                raw['collectible'] != (cid in LEAVES) or type(raw['health']) is not int or
                cid not in (EGG, SWAMP) and type(raw['attack']) is not int):
            raise TargetValidationError('Historical awakening lost its complete native minion body')
        fields = {}
        if cid == ENVOY:
            fields.update(keywords=(Keyword.FRENZY,), limited_triggers=(LimitedTriggerSpec.frenzy(PREFIX + cid),))
        elif cid == EGG:
            fields['triggers'] = (TriggerSpec('damage_dealt', PREFIX + cid),)
        elif cid in (SUNGILL, GANARG):
            fields.update(dormant_turns=2, on_awaken=PREFIX + cid)
        elif cid == SWARMER:
            fields.update(keywords=(Keyword.STEALTH,), deathrattle=PREFIX + cid)
        elif cid in (SWAMP, MERCHANT):
            fields['deathrattle'] = PREFIX + cid
        elif cid in (CAT, RAIDER, MACAW, CRIER, METAMORFIN):
            fields['battlecry'] = PREFIX + cid
            if cid == METAMORFIN:
                fields['keywords'] = (Keyword.TAUNT,)
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=0 if cid in (EGG, SWAMP) else raw['attack'], health=raw['health'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
