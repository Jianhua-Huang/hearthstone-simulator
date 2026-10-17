"""Held spell faces, original physical choices and independent one-turn promises."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, Damage, DamageBatch,
    GainTemporaryMana, RequestChoice, RevealHandCard)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind, HandProgressSpec,
    Keyword, PlayerEffectSpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion, GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, CopyCard, DestroyDeckCard, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p63-v1.json'
BATCH_HASH = 'f422018d5cf5793d9306aae2f106652933b899a8b602b063d50d3019e97d44d8'
PRAYER, RITUAL, LIGHT, FULL_LIGHT, GOLD, STORM, MINER, INFORMANT, ARATOR, WHELP = (
    'EDR_460', 'EDR_461', 'FIR_918', 'FIR_918t', 'JAIL_801', 'JAIL_805',
    'TLC_109', 'TIME_036', 'MEND_804', 'FIR_927')
ROOTS = (PRAYER, RITUAL, LIGHT, FULL_LIGHT, GOLD, STORM, MINER, INFORMANT, ARATOR, WHELP)
EXISTING = ('EDR_460t', 'EDR_461t', 'JAIL_801t', 'JAIL_805t', 'CS2_101t')
FORMS = dict(zip((PRAYER, RITUAL, LIGHT, GOLD, STORM), (*EXISTING[:2], FULL_LIGHT, *EXISTING[2:4])))
PREFIX, POOL_ID = 'cards.simple_followup_p63.', 'constructed.cards'
PROMISE = PREFIX + 'next_mana'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != ROOTS
            or tuple(x['record']['id'] for x in d['existing_dependencies']) != EXISTING
            or any(d[k] for k in ('dependencies', 'skipped'))):
        raise TargetValidationError('P63 complete frozen scope changed')
    if any(canonical_digest(x['record']) != x['record_sha256']
            for x in d['cards'] + d['existing_dependencies'] + d['evidence_only']):
        raise TargetValidationError('P63 complete original row changed')
    return d


def register_simple_followup_p63_cards(registry):
    d = load_batch()
    for cid, pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid))) != pin:
            raise TargetValidationError('P63 existing dependency changed')
    registry.register_trigger_condition(PREFIX + 'own_cast', lambda c: c.cast is not None and c.cast.player_id == c.player_id)

    def miner(c):
        deck = c.state.players[c.player_id].deck
        if not deck: return ()
        top = c.state.entities[deck[0]]
        rarity = registry.card(top.card_id).metadata.rarity
        if rarity is None: raise ResolutionError('Relic Miner cannot infer an unknown printed rarity')
        discover = DiscoverFromPool(c.player_id, POOL_ID,
            PoolQuery(collectible=True, class_mode='current', rarities=(rarity,)), source_id=c.source_id)
        return (DestroyDeckCard(CardReference.capture(top), c.source_id, on_destroy=(discover,)),)

    def informant(c):
        hand = c.state.players[3-c.player_id].hand
        if not hand: return ()
        target = c.state.entities[hand[-1]]
        ref = CardReference.capture(target)
        material = CapturedCardCopyMaterial.capture(c.state, target)
        options = (ChoiceOption('copy', 'Get a copy', (CopyCard(material, c.player_id, source_id=c.source_id),),
                       card_id=target.card_id),
            ChoiceOption('tax', 'Increase its Cost by (2)',
                (ModifyStoredCost(ref, CostSpec(delta=2), c.source_id),), card_id=target.card_id))
        return (RevealHandCard(target.id, viewers=(c.player_id,)), RequestChoice(c.player_id, options, c.source_id))

    def arator(c):
        group = tuple((MinionReference.capture(e), e.attack, e.health)
            for i in minions(c, registry, c.player_id) for e in (c.state.entities[i],)
            if e.card_id in d['silver_hand_recipient_ids'])
        return tuple(effect for ref, attack, health in group for effect in (
            BuffCapturedMinion(ref, attack, health, c.source_id), GrantCapturedKeyword(ref, Keyword.TAUNT, c.source_id)))

    def next_mana(c):
        instance = c.player_effect
        if instance is None: raise ResolutionError('Next-turn mana requires its original logical promise')
        if c.event is None or c.event.player_id != c.player_id or c.state.turn <= instance.created_turn: return ()
        return (ConsumePlayerEffect(c.player_id, instance, (GainTemporaryMana(c.player_id, 1),)),)

    bodies = {PRAYER: lambda c: (Damage(c.target_id, 6, c.source_id, DamageKind.SPELL),),
        RITUAL: lambda c: (GenerateFromPool(c.player_id, POOL_ID, PoolQuery(kinds=(CardType.MINION,),
            collectible=True, min_cost=3, max_cost=3), count=2, source_id=c.source_id, destination='board',
            cause=SummonCause.capture(c)),),
        LIGHT: lambda c: (Buff(c.target_id, 3, 3, c.source_id),),
        FULL_LIGHT: lambda c: (Buff(c.target_id, 3, 3, c.source_id), AddToHand(c.player_id, LIGHT, c.source_id)),
        GOLD: lambda c: (Damage(c.target_id, 4, c.source_id, DamageKind.SPELL),),
        STORM: lambda c: (DamageBatch(tuple(Damage(i, 2, c.source_id, DamageKind.SPELL)
            for i in minions(c, registry, 3-c.player_id))),),
        MINER: miner, INFORMANT: informant, ARATOR: arator,
        WHELP: lambda c: (DiscoverFromPool(c.player_id, POOL_ID,
            PoolQuery(collectible=True, class_mode='current', min_cost=5, max_cost=5), source_id=c.source_id),
            AddPlayerEffect(c.player_id, PROMISE, c.source_id)), 'next_mana': next_mana}
    for name, body in bodies.items(): registry.register_behavior(PREFIX + name, body)
    registry.register_player_effect(PlayerEffectSpec(PROMISE, WHELP,
        triggers=(TriggerSpec('turn_started', PREFIX + 'next_mana'),)))
    for row in d['cards']:
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower()); kw = {}
        kw['on_play' if kind == CardType.SPELL else 'battlecry'] = PREFIX + cid
        if cid in FORMS:
            if raw['tags']['TAG_SCRIPT_DATA_NUM_1'] != 3: raise TargetValidationError('P63 printed counter changed')
            kw['hand_progress'] = HandProgressSpec('event', 3, FORMS[cid],
                event='spell_cast_accepted', condition_id=PREFIX + 'own_cast')
        if cid in (PRAYER, LIGHT, FULL_LIGHT):
            kw['targeting'] = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))
        if cid == GOLD: kw['targeting'] = TargetSpec()
        if cid == STORM: kw['keywords'] = (Keyword.LIFESTEAL,)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')), metadata=metadata_from_record(raw), **kw)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
