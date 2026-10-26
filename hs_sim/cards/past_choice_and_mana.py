"""Actual past spells: two Choose One roots, three choices and Mana accounts."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import (ChangeManaCrystals, ChoiceOption, DestroyAllManaCrystals,
    Draw, GainArmor, InvokeBehavior, RefreshMana, RequestChoice)
from hs_sim.engine.model import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    CostSpec, Keyword)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOTS = ('DEEP_028', 'ETC_373', 'OG_195', 'VAC_907', 'BAR_539')
TOKENS = ('DEEP_028t', 'ETC_373t', 'OG_195c')
CHOICES = ('ETC_373a', 'ETC_373b', 'OG_195a', 'OG_195b',
    'VAC_907t1', 'VAC_907t2', 'VAC_907t3')
DEPENDENCIES = ('DEEP_028t', 'ETC_373a', 'ETC_373b', 'ETC_373t',
    'OG_195a', 'OG_195b', 'OG_195c', 'VAC_907t1', 'VAC_907t2', 'VAC_907t3')
EVIDENCE = ('BAR_539e', 'ETC_373be', 'OG_195e')
PREFIX = 'cards.past_choice_mana.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-choice-and-mana-v1.json'
BATCH_HASH = 'e28bfefa0954fe8f0cbbf58fa4e34e288103dad9dd7d0f2f6a246740e4a995c1'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            tuple(x['record']['id'] for x in value['cards']) != ROOTS or
            tuple(x['record']['id'] for x in value['dependencies']) != DEPENDENCIES or
            tuple(x['record']['id'] for x in value['evidence_only']) != EVIDENCE or
            len(value['official_faces']) != 22 or
            value['numeric_normalizations'] != {'OG_195c': {'cost': 0}} or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            any(canonical_digest(x['record']) != x['record_sha256'] for key in
                ('cards', 'dependencies', 'evidence_only') for x in value[key])):
        raise TargetValidationError('Past choice/Mana spells lost their complete reviewed native scope')
    return value


def register_past_choice_and_mana(registry):
    data = load_batch(); rows = {x['record']['id']: x['record']
        for key in ('cards', 'dependencies') for x in data[key]}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Past choice/Mana cards cannot replace existing native identities')

    def summon(c, token, count):
        if not count: return ()
        cast = active_cast(c.state, c.source_id, c.player_id)
        if cast is None or not cast.payload_started or cast.card_id not in ROOTS:
            raise UnsupportedDefinitionError('Past choice summon requires its original active CAST')
        cause = SummonCause.capture(replace(c, cast=cast))
        request = SummonByCard(c.player_id, (SummonEntryMaterial(token),), cause)
        return (request,)*count

    def buff(c, attack, health, taunt=False):
        effects = []
        for eid in minions(c, registry, c.player_id):
            ref = MinionReference.capture(c.state.entities[eid])
            effects.append(BuffCapturedMinion(ref, attack, health, c.source_id))
            if taunt: effects.append(GrantCapturedKeyword(ref, Keyword.TAUNT, c.source_id))
        return tuple(effects)

    def both(c, root, token, count):
        # The grant must see the actual minions after every summon and reaction.
        return (*summon(c, token, count), InvokeBehavior(PREFIX+root+'_buff', c.source_id, c.player_id))

    def cluster(c):
        player = c.state.players[c.player_id]
        overflow = 3-min(3, max(0, player.mana_cap-player.max_mana))
        return (ChangeManaCrystals(c.player_id, 3), *summon(c, 'DEEP_028t', overflow))

    def stored_costs(c):
        player = c.state.players[c.player_id]
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[eid]),
            CostSpec(set_to=1), c.source_id) for zone in (player.hand, player.deck) for eid in zone)

    def stars(c):
        effects = (Draw(c.player_id, 2, c.source_id), GainArmor(c.player_id, 5), RefreshMana(c.player_id, 3))
        options = tuple(ChoiceOption(cid, rows[cid]['name'], (effect,), card_id=cid)
            for cid, effect in zip(CHOICES[-3:], effects))
        return tuple(RequestChoice(c.player_id, options, c.source_id,
            prompt=rows['VAC_907']['name']+'（'+str(index)+' / 3）',
            repeat_key=PREFIX+'VAC_907:'+str(index)) for index in (1, 2, 3))

    bodies = {
        'DEEP_028': cluster,
        'ETC_373a': lambda c: summon(c, 'ETC_373t', 5),
        'ETC_373b': lambda c: buff(c, 2, 4, True),
        'ETC_373_buff': lambda c: buff(c, 2, 4, True),
        'ETC_373:combined': lambda c: both(c, 'ETC_373', 'ETC_373t', 5),
        'OG_195a': lambda c: summon(c, 'OG_195c', 7),
        'OG_195b': lambda c: buff(c, 2, 2),
        'OG_195_buff': lambda c: buff(c, 2, 2),
        'OG_195:combined': lambda c: both(c, 'OG_195', 'OG_195c', 7),
        'VAC_907': stars,
        'BAR_539': lambda c: (DestroyAllManaCrystals(c.player_id),
            InvokeBehavior(PREFIX+'stored_costs', c.source_id, c.player_id)),
        'stored_costs': stored_costs,
    }
    for name, body in bodies.items(): registry.register_behavior(PREFIX+name, body)
    for cid, raw in rows.items():
        choice = cid in CHOICES; kind = CardType(raw['type'].lower()); fields = {}
        if kind==CardType.MINION:
            fields.update(attack=raw['attack'], health=raw['health'],
                keywords=(Keyword.TAUNT,) if cid=='DEEP_028t' else ())
        elif cid in ('ETC_373', 'OG_195'):
            first, second = cid+'a', cid+'b'
            fields['choose_one'] = ChooseOneSpec(tuple(ChooseBranch(i, rows[i]['name'], PREFIX+i)
                for i in (first, second)), ChooseBranch(cid+':combined', '兼得', PREFIX+cid+':combined'))
        elif not choice: fields['on_play'] = PREFIX+cid
        cost = 0 if choice or cid=='OG_195c' else raw['cost']
        card = CardDefinition(cid, raw['name'], kind, cost=cost, choice_only=choice,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        if not choice: registry.register_pool_card(PoolCard.from_definition(card))
