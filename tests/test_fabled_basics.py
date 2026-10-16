"""Independent complete Fabled construction, with one finite real family."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardType, DeckValidationError,
    EndTurn, FabledSpec, Game, OpeningHook, PlayCard, PlayerSetup, Rarity,
    ResolutionError, Ruleset, Scenario, SelectChoice, SnapshotError, Zone,
    expand_fabled_cards, validate_deck)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, DamageBatch,
    Destroy, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.play_history import played_cards
from hs_sim.engine.pools import (DiscoverFromPool, GenerationContext, PoolCard,
    PoolDefinition, PoolMember, PoolQuery)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, policy, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

ROOT = 'TIME_609'
COMPANIONS = ('TIME_609t1', 'TIME_609t2')
SPEC = FabledSpec(ROOT, COMPANIONS)
PATH = Path(__file__).resolve().parents[1] / 'data/support/fabled-basics.json'
PIN = 'ef85a8237aa0098d3013f657d9da68f15409dc6ad1ae9f2d331b6945ec106075'
CONTEXT = GenerationContext('synthetic-test-target', 'experimental')


def evidence():
    value = json.loads(PATH.read_text('utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Full Fabled evidence changed')
    result = {}
    for row in value['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Original Fabled raw changed')
        result[row['id']] = row['data']
    return result


def registry(*, declaration=True, wait=False, fault=False):
    r = opening_registry()
    cls = CardClass.HUNTER
    r.register_card(CardDefinition('hunter.power', 'Power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(cls, collectible=False)))
    r.register_card(CardDefinition('hunter.hero', 'Hero', CardType.HERO, health=30,
        initial_hero_power='hunter.power', metadata=metadata(cls, collectible=False)))
    r.register_behavior('fixture.noop', lambda c: ())
    for i in range(3):
        cid = 'spell.'+str(i)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1,
            on_play='fixture.noop', metadata=metadata(cls)))
        r.register_pool_card(PoolCard(cid, CardType.SPELL, 1, r.card(cid).metadata, battlecry=False))
    r.register_pool(PoolDefinition('fabled.spells', 'finite-v1', CONTEXT.target_id,
        CONTEXT.mode, tuple(PoolMember('spell.'+str(i)) for i in range(3))))
    # Only this necessary real family is adapted. The finite spell pool and
    # played-instance repeat/material policies are experimental, pending CN.
    def body(cid, c):
        others = {ROOT, *COMPANIONS} - {cid}
        history = played_cards(c.state, c.player_id, kind=CardType.MINION,
            before_id=c.play.id if c.play is not None else None)
        count = 1 + sum(p.card_id in others for p in history)
        if cid == COMPANIONS[0]:
            return (DiscoverFromPool(c.player_id, 'fabled.spells',
                PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current'),
                source_id=c.source_id, discoveries=count),)
        if cid == COMPANIONS[1]:
            cards = tuple(c.state.entities[eid] for eid in c.state.players[c.player_id].deck
                if c.state.entities[eid].kind == CardType.MINION)
            return tuple(BuffStoredCard(CardReference.capture(e), attack=1, health=1,
                source_id=c.source_id) for _ in range(count) for e in cards)
        enemy = c.state.players[3-c.player_id]
        targets = (enemy.hero_id, *(eid for eid in enemy.board
            if c.state.entities[eid].kind == CardType.MINION))
        return tuple(DamageBatch(tuple(Damage(eid, 2, c.source_id) for eid in targets))
            for _ in range(count))
    for cid, raw in evidence().items():
        r.register_behavior(cid+'.body', lambda c, cid=cid: body(cid, c))
        r.register_card(CardDefinition(cid, raw['name'], CardType.MINION,
            cost=raw['cost'], attack=raw['attack'], health=raw['health'], battlecry=cid+'.body',
            metadata=metadata(cls, collectible=raw['collectible'],
                rarity=Rarity.LEGENDARY if raw['tags'].get('RARITY') == 5 else None)))
    if declaration:
        r.register_fabled(SPEC)
    scripts = {
        'create.root': lambda c: (AddToHand(c.player_id, ROOT, c.source_id),),
        'lose.root': lambda c: (Destroy(next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == ROOT)),),
        'bounce.root': lambda c: (ReturnToHand(next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == ROOT)),),
        'silence.root': lambda c: (Silence(next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == ROOT)),),
        'transform.root': lambda c: (Transform(next(eid for eid in c.state.players[c.player_id].board
            if c.state.entities[eid].card_id == ROOT), 'card.1'),),
    }
    for cid, callback in scripts.items():
        r.register_behavior(cid, callback)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=metadata()))
    if wait:
        r.register_behavior('opening.fail', lambda c: (AddToHand(c.player_id, 'unknown.after.bundle'),))
        r.register_behavior('opening.wait', lambda c: (RequestChoice(c.player_id,
            (ChoiceOption('ok', 'Continue'),), c.source_id),) +
            ((InvokeBehavior('opening.fail', c.source_id, c.player_id),) if fault else ()))
        r.register_card(CardDefinition('opening.wait', 'Opening fixture', CardType.SPELL,
            on_play='fixture.noop', opening_hooks=(OpeningHook('before_deal', 'opening.wait'),),
            metadata=metadata()))
    return r


def physical(*extras, r=None):
    r = r or registry()
    selected = (ROOT, *extras, *(f'card.{n}' for n in range(1, 28-len(extras))))
    return expand_fabled_cards(selected, r)


class FabledConstructionTests(unittest.TestCase):
    def report(self, cards=None, *, cls=CardClass.HUNTER, r=None, p=None):
        r = r or registry()
        return validate_deck(deck(cls, physical(r=r) if cards is None else cards), r, p or policy(r))

    def codes(self, report):
        return tuple(i.code for i in report.issues)

    def test_full_raw_root_and_companions_are_pinned(self):
        rows = evidence()
        originals = {r['id']: r for r in json.loads((PATH.parents[1]/'extracted/cards.json').read_text('utf-8'))}
        self.assertEqual(tuple(rows), (ROOT, *COMPANIONS))
        for cid, row in rows.items():
            self.assertEqual(row, originals[cid])
            self.assertEqual((row['cost'], row['attack'], row['health']), (3, 2, 4))
            self.assertEqual(row['tags']['ELITE'], 1)
        self.assertEqual(rows[ROOT]['related_dbf_ids'], [119705, 119706])
        self.assertEqual(rows[ROOT]['tags']['FABLED'], 1)
        self.assertTrue(all(rows[c]['tags']['IS_FABLED_BUNDLE_CARD']==1 for c in COMPANIONS))

    def test_builder_expands_exact_group_without_mutating_selection(self):
        r = registry();selected = ('card.1', ROOT, 'card.2')
        self.assertEqual(expand_fabled_cards(selected,r), ('card.1', ROOT, *COMPANIONS, 'card.2'))
        self.assertEqual(selected, ('card.1', ROOT, 'card.2'))
        self.assertEqual(expand_fabled_cards(('card.1',),r), ('card.1',))

    def test_builder_rejects_direct_partial_or_unknown_companions(self):
        r = registry()
        for ids in ((ROOT,COMPANIONS[0]), COMPANIONS, ('unknown',), [ROOT], (True,)):
            with self.subTest(ids=ids), self.assertRaises(ValueError):expand_fabled_cards(ids,r)

    def test_physical_companions_take_existing_thirty_slots(self):
        r=registry();cards=physical(r=r)
        self.assertEqual(len(cards),30);self.assertTrue(self.report(cards,r=r).valid)
        self.assertIn('deck_size',self.codes(self.report(cards+('card.28','card.29'),r=r)))
        self.assertIn('deck_size',self.codes(self.report(cards[:-1],r=r)))

    def test_root_requires_all_companions_exactly_once(self):
        cards=physical()
        for bad in ((ROOT,*cards[3:],'card.28','card.29'),
                    (ROOT,COMPANIONS[0],*cards[3:],'card.28'),
                    (ROOT,COMPANIONS[0],COMPANIONS[0],*cards[3:])):
            with self.subTest(bad=bad[:3]):self.assertIn('fabled_bundle',self.codes(self.report(bad)))

    def test_orphans_remain_uncollectible_without_the_original_root(self):
        cards=('card.28',*physical()[1:])
        self.assertIn('uncollectible',self.codes(self.report(cards)))

    def test_unregistered_source_does_not_grant_companion_permission(self):
        r=registry(declaration=False)
        self.assertEqual(expand_fabled_cards((ROOT,),r),(ROOT,))
        self.assertIn('uncollectible',self.codes(self.report(physical(),r=r)))

    def test_root_format_class_and_member_bans_remain_strict(self):
        r=registry()
        for p in (policy(r,banned_card_ids=(ROOT,)),policy(r,banned_card_ids=(COMPANIONS[0],)),
                  replace(policy(r),allowed_card_ids=tuple(c for c in r.cards if c!=COMPANIONS[1]))):
            with self.subTest(policy=p):self.assertIn('format_legality',self.codes(self.report(r=r,p=p)))
        self.assertIn('class',self.codes(self.report(cls=CardClass.MAGE,r=r)))
        self.assertIn('uncollectible',self.codes(self.report(cls=CardClass.MAGE,r=r)))

    def test_copies_and_deck_identity_are_not_bypassed(self):
        r=registry();cards=physical(r=r)
        self.assertIn('copy_limit',self.codes(self.report((ROOT,*cards[:-1]),r=r)))
        changed=replace(r.card(COMPANIONS[0]),metadata=replace(r.card(COMPANIONS[0]).metadata,deck_identity=ROOT))
        r._cards[COMPANIONS[0]]=changed
        self.assertIn('copy_limit',self.codes(self.report(r=r)))

    def test_unrelated_uncollectible_face_is_not_authorized(self):
        r=registry();r.register_card(CardDefinition('unrelated', 'Not a companion',CardType.MINION,
            attack=1,health=1,metadata=metadata(CardClass.HUNTER,collectible=False,rarity=Rarity.LEGENDARY)))
        cards=(*physical(r=r)[:-1],'unrelated')
        self.assertIn('uncollectible',self.codes(self.report(cards,r=r)))

    def test_specs_are_strict_immutable_and_registry_is_frozen(self):
        for args in (('',COMPANIONS),(ROOT,[]),(ROOT,()),(ROOT,(ROOT,)),(ROOT,COMPANIONS*2),
                     (ROOT,(' ',)),(ROOT,COMPANIONS,'future')):
            with self.subTest(args=args),self.assertRaises(ValueError):FabledSpec(*args)
        with self.assertRaises(FrozenInstanceError):SPEC.version='future'
        r=registry()
        with self.assertRaises(TypeError):r.fabled[ROOT]=SPEC
        with self.assertRaises(ValueError):r.register_fabled(SPEC)
        r.freeze()
        with self.assertRaises(ValueError):r.register_fabled(replace(SPEC,source_card_id='other'))

    def test_unknown_collectible_foreign_and_shared_members_reject(self):
        r=registry(declaration=False)
        r.register_fabled(replace(SPEC,companion_card_ids=('unknown',)))
        with self.assertRaises(ValueError):r.validate()
        for member in ('card.1','coin'):
            r=registry(declaration=False);r.register_fabled(replace(SPEC,companion_card_ids=(member,)))
            with self.subTest(member=member),self.assertRaises(ValueError):r.validate()
        r=registry();r.register_card(replace(r.card(ROOT),id='another.root'))
        r.register_fabled(FabledSpec('another.root',COMPANIONS))
        with self.assertRaises(ValueError):r.validate()

    def test_invalid_import_rejects_before_freeze_or_opening(self):
        r=registry();own=deck(CardClass.HUNTER,(ROOT,*(f'card.{i}' for i in range(1,30))))
        with self.assertRaises(DeckValidationError):Game.from_decks(setup(r,decks=(own,deck(CardClass.WARRIOR))),r)
        r.register_behavior('still.mutable',lambda c: ())

    def test_fingerprint_includes_nonempty_declaration_only(self):
        from unittest.mock import patch
        import hs_sim.engine.registry as registry_module
        payloads=[];dumps=registry_module.json.dumps;empty=opening_registry()
        def capture(payload,*args,**kwargs):
            payloads.append(payload);return dumps(payload,*args,**kwargs)
        with patch.object(registry_module.json,'dumps',side_effect=capture):empty.fingerprint()
        self.assertEqual(len(payloads),1);self.assertFalse(empty.fabled)
        self.assertNotIn('fabled',payloads[0])
        r=registry(declaration=False);plain=r.fingerprint();r.register_fabled(SPEC)
        self.assertNotEqual(r.fingerprint(),plain)
        changed=registry(declaration=False)
        changed.register_fabled(replace(SPEC,companion_card_ids=COMPANIONS[::-1]))
        self.assertNotEqual(changed.fingerprint(),r.fingerprint())


class FabledRuntimeTests(unittest.TestCase):
    def constructed(self, *, wait=False, fault=False, first=1):
        self.options=dict(wait=wait,fault=fault)
        r=registry(**self.options);cards=physical(*(('opening.wait',) if wait else ()),r=r)
        own=deck(CardClass.HUNTER,cards)
        return Game.from_decks(setup(r,first=first,decks=(own,deck(CardClass.WARRIOR))),r)

    def scenario(self,hand=(),stored=(),board=()):
        self.options={}
        return Game.from_scenario(Scenario((PlayerSetup('hunter.hero',hand=hand,deck=stored,board=board,
            mana=10,max_mana=10),PlayerSetup('warrior.hero')),seed=7,
            generation_context=replace(CONTEXT,starting_decks=(tuple(stored),()))),registry())

    def choose(self,g,mulligan=False):
        c=g.state.pending_choice
        return g.apply(SelectChoice(c.player_id,c.id,() if mulligan else (c.options[0].id,)))

    def play(self,g,cid):
        eid=next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
        return g.apply(PlayCard(1,eid))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,registry(**self.options))
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry(**self.options)).snapshot(),saved)
        for actor in (1,2):self.assertEqual(restored.observe(actor),g.observe(actor))

    def test_full_original_members_use_ordinary_entities_and_mulligans(self):
        for first in (1,2):
            with self.subTest(first=first):
                g=self.constructed(first=first);cards=g.state.players[1].original_deck
                self.assertEqual(cards,physical());self.assertEqual(len(cards),30)
                ids=g.state.opening.original_entities[0]
                self.assertEqual(tuple(g.state.entities[e].card_id for e in ids),cards)
                self.assertEqual(len(set(ids)),30);self.portable(g)
                while g.state.pending_choice:self.choose(g,mulligan=True)
                self.portable(g);self.assertEqual(g.state.players[1].original_deck,cards)
                self.assertEqual(g._generation_context.starting_decks[0],cards)

    def test_before_deal_choice_preserves_every_original_member(self):
        g=self.constructed(wait=True);self.portable(g)
        self.assertEqual(len(g.state.players[1].deck),30)
        self.choose(g);self.portable(g)
        while g.state.pending_choice:self.choose(g,mulligan=True)
        self.portable(g)

    def test_failed_opening_resume_rolls_back_without_rebuilding_bundle(self):
        g=self.constructed(wait=True,fault=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)

    def test_real_source_uses_ordinary_paid_battlecry_without_creating_companions(self):
        g=self.scenario((ROOT,),('card.1',));before=set(g.state.entities)
        self.play(g,ROOT)
        self.assertEqual(g.state.players[1].mana,7)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)
        self.assertEqual(set(g.state.entities),before)
        self.assertEqual(g.state.players[1].original_deck,('card.1',));self.portable(g)

    def test_real_companions_keep_ordinary_buff_and_discovery_behaviors(self):
        g=self.scenario((COMPANIONS[1],COMPANIONS[0]),('card.1',))
        self.play(g,COMPANIONS[1]);stored=g.state.entities[g.state.players[1].deck[0]]
        self.assertEqual((stored.attack,stored.max_health),(5,5));self.play(g,COMPANIONS[0])
        self.assertEqual(g.state.players[1].mana,4)
        choices=0
        while g.state.pending_choice:
            self.portable(g);self.choose(g);choices+=1
        self.assertEqual(choices,2);self.portable(g)
        self.assertEqual(tuple(g.state.entities[e].card_id for e in g.state.players[1].deck),('card.1',))

    def test_source_silence_bounce_transform_and_death_do_not_revoke_originals(self):
        for cid in ('silence.root','bounce.root','transform.root','lose.root'):
            with self.subTest(cid=cid):
                g=self.scenario((ROOT,cid),COMPANIONS);original=g.state.players[1].original_deck
                self.play(g,ROOT);self.play(g,cid)
                self.assertEqual(g.state.players[1].original_deck,original)
                self.assertEqual(tuple(g.state.entities[e].card_id for e in g.state.players[1].deck),COMPANIONS)
                self.portable(g)

    def test_created_root_never_adds_a_starting_group(self):
        g=self.scenario(('create.root',),('card.1',));self.play(g,'create.root')
        self.assertEqual(tuple(g.state.entities[e].card_id for e in g.state.players[1].hand),(ROOT,))
        self.play(g,ROOT)
        self.assertEqual(tuple(g.state.entities[e].card_id for e in g.state.players[1].deck),('card.1',))
        self.assertEqual(g.state.players[1].original_deck,('card.1',));self.portable(g)

    def test_actual_constructed_paid_root_leaves_without_requalifying_bundle(self):
        self.options={};r=registry();cards=physical('lose.root',r=r)
        def starts_with_both(seed):
            values=list(cards);random.Random(seed).shuffle(values)
            return ROOT in values[:3] and 'lose.root' in values[:3]
        seed=next(n for n in range(3000) if starts_with_both(n))
        own=deck(CardClass.HUNTER,cards)
        g=Game.from_decks(setup(r,seed=seed,decks=(own,deck(CardClass.WARRIOR))),r)
        while g.state.pending_choice:self.choose(g,mulligan=True)
        while g.state.active_player!=1 or g.state.players[1].mana<3:
            g.apply(EndTurn(g.state.active_player))
        self.play(g,ROOT);self.play(g,'lose.root')
        self.assertEqual(g.state.players[1].original_deck,cards)
        self.assertEqual(g._match_setup.decks[0].cards,cards)
        self.assertEqual(g.state.entities[g.state.opening.original_entities[0][0]].zone,Zone.GRAVEYARD)
        self.portable(g)

    def test_complete_host_setup_round_trips_without_new_layout(self):
        g=self.constructed();s=g.snapshot()
        self.assertEqual((g.ruleset.id,g.mechanics.version,s['schema_version']),('prototype-v302',CORE_EFFECTS_VERSION,SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual(s['match_setup']['decks'][0]['cards'],list(physical()))
        self.assertNotIn('fabled',s['state']['players']['1'])
        self.portable(g)

    def test_rehashed_original_crop_or_class_change_is_rejected(self):
        g=self.constructed();saved=g.snapshot()
        for change in (lambda s:s['state']['players']['1']['original_deck'].__setitem__(0,'card.28'),
                       lambda s:s['state']['players']['1'].__setitem__('deck_class','mage'),
                       lambda s:s['match_setup']['decks'][0]['cards'].__setitem__(1,'card.28')):
            with self.subTest(change=change):
                bad=deepcopy(saved);change(bad);bad['state_hash']=canonical_hash(bad['state'])
                with self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())

    def test_changed_declaration_and_previous_rules_are_explicitly_rejected(self):
        g=self.constructed();r=registry(declaration=False);r.register_fabled(replace(SPEC,companion_card_ids=COMPANIONS[::-1]))
        with self.assertRaises(SnapshotError):Game.from_snapshot(g.snapshot(),r)
        s=g.snapshot();s['ruleset']['id']='prototype-v178'
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry())

    def test_opponent_hidden_originals_and_bundle_mapping_are_not_published(self):
        g=self.constructed();r=registry();other=deck(CardClass.WARRIOR,tuple(f'card.{i}' for i in range(2,32)))
        h=Game.from_decks(setup(r,decks=(deck(CardClass.HUNTER,physical(r=r)),other)),r)
        self.assertEqual(g.observe(1),h.observe(1))
        observation=json.dumps(g.observe(2))
        self.assertNotIn('companion_card_ids',observation);self.assertNotIn('original_deck',observation)
        self.assertNotIn('fabled-v2',observation)
