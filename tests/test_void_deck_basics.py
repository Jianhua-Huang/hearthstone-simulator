"""The independent private Void pile and one complete current Irida source."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import random
import unittest

from hs_sim.engine import (AddPlayerEffect, CardClass, CardDefinition, CardType,
    EndTurn, Game, GetFromVoid, Keyword, PlayerEffectSpec, PlayerSetup, PlayCard,
    Rarity, ResolutionError, Ruleset, Scenario, SelectChoice, SendDeckToVoid,
    SnapshotError, TriggerSpec, VoidCard, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, CopyMinion, Damage,
    Destroy, Draw, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform,
    ChangeControl)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.void_decks import POLICY
from hs_sim.engine.zones import AddToDeck, CardReference
from hs_sim.targets import canonical_digest
from opening_fixtures import deck, metadata, registry as opening_registry, setup
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

IRIDA = 'JAIL_719'
EFFECT = 'irida.void'
SOURCE = Path(__file__).resolve().parents[1] / 'data/support/void-deck-basics.json'
PIN = '3ec4bff265325f89adfd84e0f1adce9c68cbee61ae47b811b15fd0262d70687a'


def evidence():
    value = json.loads(SOURCE.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Complete Void source evidence changed')
    row = value['records'][0]
    if row['id'] != IRIDA or canonical_digest(row['data']) != row['data_sha256']:
        raise ValueError('Original Irida row changed')
    return row['data']


def registry(*, wait=False, fault=False, immediate=None):
    r = opening_registry(); raw = evidence()
    cls = CardClass.DEMON_HUNTER
    r.register_card(CardDefinition(cls.value+'.power', 'Power', CardType.HERO_POWER,
        cost=2, on_use='power', metadata=metadata(cls, collectible=False)))
    r.register_card(CardDefinition(cls.value+'.hero', 'Hero', CardType.HERO, health=30,
        initial_hero_power=cls.value+'.power', metadata=metadata(cls, collectible=False)))
    r.register_behavior('irida.begin', lambda c: (SendDeckToVoid(c.player_id, c.source_id),
        AddPlayerEffect(c.player_id, EFFECT, c.source_id)))
    r.register_behavior('irida.acquire', lambda c: (GetFromVoid(c.player_id, 2, c.source_id),)
        if c.event.player_id == c.player_id else ())
    r.register_player_effect(PlayerEffectSpec(EFFECT, IRIDA,
        triggers=(TriggerSpec('turn_started', 'irida.acquire'),)))
    r.register_card(CardDefinition(IRIDA, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        keywords=(Keyword.LIFESTEAL,), battlecry='irida.begin',
        metadata=metadata(cls, rarity=Rarity.LEGENDARY)))
    r.register_behavior('fixture.fail', lambda c: (AddToHand(c.player_id, 'unknown.after.void'),))
    def spell(name, callback):
        r.register_behavior(name, callback)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, metadata=metadata()))
    def work(c, effect, label):
        return (effect,) + ((InvokeBehavior('fixture.fail', c.source_id, c.player_id),) if immediate == label else ())
    spell('send', lambda c: work(c, SendDeckToVoid(c.player_id, c.source_id), 'send'))
    for count in (0, 1, 2, 3, 8):
        spell('get.'+str(count), lambda c, n=count: work(c, GetFromVoid(c.player_id, n, c.source_id), 'get'))
    spell('draw', lambda c: (Draw(c.player_id),))
    spell('append', lambda c: (AddToDeck(c.player_id, 'card.19', 'bottom', c.source_id),
        AddToDeck(c.player_id, 'card.20', 'bottom', c.source_id)))
    spell('hide', lambda c: (RemoveFromGame((CardReference.capture(c.state.entities[
        c.state.players[c.player_id].hand[0]]),), c.source_id),))
    spell('buff.deck', lambda c: tuple(BuffStoredCard(CardReference.capture(c.state.entities[eid]),
        attack=2, health=3, source_id=c.source_id) for eid in c.state.players[c.player_id].deck))
    def source(c):
        return next(eid for eid in c.state.players[c.player_id].board if c.state.entities[eid].card_id == IRIDA)
    for name, make in [('kill', Destroy), ('silence', Silence), ('bounce', ReturnToHand),
                       ('transform', lambda eid: Transform(eid, 'card.40')),
                       ('control', lambda eid: ChangeControl(eid, 2)),
                       ('copy', lambda eid: CopyMinion(eid, 1))]:
        spell(name, lambda c, f=make: (f(source(c)),))
    r.register_card(CardDefinition('stored.weapon', 'Stored weapon', CardType.WEAPON,
        cost=1, attack=1, durability=2, metadata=metadata()))
    r.register_card(CardDefinition('stored.location', 'Stored location', CardType.LOCATION,
        cost=1, durability=2, on_use='power', metadata=metadata()))
    if wait:
        def pause(c):
            return (RequestChoice(c.player_id, (ChoiceOption('ok', 'Continue',
                (InvokeBehavior('fixture.fail', c.source_id, c.player_id),) if fault else ()),), c.source_id),)
        r.register_behavior('void.wait', pause)
        r.register_card(CardDefinition('watch', 'Acquisition observer fixture', CardType.MINION,
            health=5, triggers=(TriggerSpec('card_moved_to_hand', 'void.wait'),)))
    return r


class VoidDeckBasicsTests(unittest.TestCase):
    def game(self, *, actor=1, cards=None, hand=('send','get.2'), wait=False, fault=False,
             immediate=None, board=None, rules=None, seed=51):
        self.options = dict(wait=wait, fault=fault, immediate=immediate)
        own = PlayerSetup('demon_hunter.hero', hero_power_card_id='demon_hunter.power',
            deck=tuple(f'card.{i}' for i in range(1,7)) if cards is None else cards,
            hand=hand, board=(('watch',) if wait else ()) if board is None else board,
            mana=10, max_mana=10)
        other = PlayerSetup('warrior.hero', hero_power_card_id='warrior.power',
            deck=tuple(f'card.{i}' for i in range(21,31)), mana=10, max_mana=10)
        return Game.from_scenario(Scenario((own,other) if actor == 1 else (other,own),
            seed=seed, active_player=actor), registry(**self.options), ruleset=rules)

    def play(self, g, cid):
        pid = g.state.active_player
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        return g.apply(PlayCard(pid, eid))

    def portable(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        restored = Game.from_snapshot(snapshot, registry(**self.options))
        cloned = g.clone(); repeated = replay(build_replay(g), registry(**self.options))
        for other in (restored, cloned, repeated):
            self.assertEqual(other.snapshot(), g.snapshot())
            for pid in (1,2):
                self.assertEqual(other.observe(pid), g.observe(pid))
                self.assertEqual(other.for_player(pid).legal_actions(), g.for_player(pid).legal_actions())
        return restored

    def cycle(self, g):
        g.apply(EndTurn(g.state.active_player)); g.apply(EndTurn(g.state.active_player))

    def choose(self, g):
        return g.apply(SelectChoice(g.state.pending_choice.player_id, g.state.pending_choice.id, ('ok',)))

    def private(self, g, pid=1):
        return tuple(v.entity_id for v in g.state.players[pid].void_cards)

    def reject(self, g, change):
        snapshot = json.loads(json.dumps(g.snapshot())); change(snapshot)
        snapshot['events_hash'] = canonical_hash(snapshot['events'])
        snapshot['state_hash'] = canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','state_hash','events','events_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, registry(**self.options))

    def test_full_current_real_source_is_pinned_and_fully_declared(self):
        raw = evidence()
        original = next(r for r in json.loads((SOURCE.parents[1]/'extracted/cards.json').read_text(encoding='utf-8')) if r['id'] == IRIDA)
        self.assertEqual(raw, original)
        self.assertEqual((raw['cost'],raw['attack'],raw['health']), (4,7,7))
        self.assertIn('except 1 card', raw['text_en'])
        card = registry().card(IRIDA)
        self.assertEqual(card.keywords, (Keyword.LIFESTEAL,))
        self.assertEqual(card.battlecry, 'irida.begin'); self.assertFalse(card.triggers)
        self.assertFalse(card.opening_hooks)

    def test_strict_private_records_and_effect_declarations(self):
        for make in (lambda:VoidCard(True,'card.1',1), lambda:VoidCard(1,'',1),
                lambda:VoidCard(1,'card.1',0), lambda:SendDeckToVoid(True),
                lambda:SendDeckToVoid(3), lambda:GetFromVoid(1,True),
                lambda:GetFromVoid(1,-1), lambda:GetFromVoid(1,1,True)):
            with self.assertRaises(ValueError):make()
        with self.assertRaises(Exception):VoidCard(1,'card.1',1).entity_id = 2

    def test_real_paid_source_keeps_one_and_preserves_physical_cards(self):
        g=self.game(hand=(IRIDA,)); before=tuple(g.state.players[1].deck)
        self.play(g,IRIDA); p=g.state.players[1]
        self.assertEqual(len(p.deck),1); self.assertEqual(len(p.void_cards),5)
        self.assertEqual(set(p.deck)|set(self.private(g)),set(before))
        self.assertEqual(self.private(g),tuple(i for i in before if i not in p.deck))
        self.assertEqual(p.mana,6); self.assertEqual(len(p.player_effects),1)
        for card in p.void_cards:
            e=g.state.entities[card.entity_id]
            self.assertEqual((e.zone,e.controller,e.owner,e.card_id,e.zone_epoch),
                (Zone.SETASIDE,1,1,card.card_id,card.zone_epoch))
        forbidden={'card_drawn','card_destroyed_in_deck','card_discarded','minion_died','cards_removed_from_game'}
        self.assertFalse(any(e.kind in forbidden for e in g.events))
        self.assertFalse(g.state.death_history); self.portable(g)

    def test_original_member_order_and_sequential_random_selection_are_deterministic(self):
        g=self.game(); ids=tuple(g.state.players[1].deck); rng=random.Random(51)
        keep=ids[rng.randrange(len(ids))]; pool=[i for i in ids if i!=keep]
        self.play(g,'send'); self.assertEqual(g.state.players[1].deck,[keep])
        selected=[]
        for _ in range(2):selected.append(pool.pop(rng.randrange(len(pool))))
        self.play(g,'get.2')
        actual=[e.target_id for e in g.events if e.kind=='void_card_taken']
        self.assertEqual(actual,selected); self.assertEqual(self.private(g),tuple(pool))
        self.assertEqual(g.snapshot()['rng_state'],json.loads(json.dumps(rng.getstate())))

    def test_empty_and_single_decks_keep_all_without_random_or_fatigue(self):
        for cards in ((),('card.1',)):
            with self.subTest(cards=cards):
                g=self.game(cards=cards); rng=g.snapshot()['rng_state']; before=g.state.players[1].deck
                self.play(g,'send'); self.play(g,'get.2')
                self.assertEqual(g.state.players[1].deck,before); self.assertFalse(self.private(g))
                self.assertEqual(g.snapshot()['rng_state'],rng); self.assertEqual(g.state.players[1].fatigue,0)
                self.portable(g)

    def test_zero_get_is_an_explicit_noop_with_a_nonempty_pile(self):
        g=self.game(hand=('send','get.0'));self.play(g,'send')
        before=self.private(g);rng=g.snapshot()['rng_state'];self.play(g,'get.0')
        self.assertEqual(self.private(g),before);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertFalse(any(e.kind=='void_card_taken' for e in g.events))

    def test_single_remaining_member_is_consumed_without_a_random_draw(self):
        g=self.game(cards=('card.1','card.2'),hand=('send','get.1'));self.play(g,'send')
        saved=g.state.players[1].void_cards[0];rng=g.snapshot()['rng_state'];self.play(g,'get.1')
        self.assertFalse(self.private(g));self.assertIn(saved.entity_id,g.state.players[1].hand)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_duplicate_faces_remain_distinct_physical_members(self):
        g=self.game(cards=('card.1',)*4,hand=('send','get.8'));ids=set(g.state.players[1].deck)
        self.play(g,'send');self.assertEqual(len(self.private(g)),3)
        self.play(g,'get.8');taken=[e.target_id for e in g.events if e.kind=='void_card_taken']
        self.assertEqual(len(set(taken)),3);self.assertTrue(set(taken)<ids)
        self.assertFalse(self.private(g));self.portable(g)

    def test_acquisition_moves_originals_and_is_not_draw_or_copy(self):
        g=self.game();self.play(g,'send');before=set(self.private(g));deck_before=g.state.players[1].deck
        old_entries={i:g.state.entities[i].hand_entry_id for i in before};self.play(g,'get.2')
        moved=[e for e in g.events if e.kind=='card_moved_to_hand']
        self.assertEqual(len(moved),2);self.assertTrue({e.target_id for e in moved}<=before)
        self.assertEqual(g.state.players[1].deck,deck_before)
        self.assertFalse(any(e.kind in ('card_created','card_drawn') for e in g.events))
        for event in moved:
            self.assertGreater(g.state.entities[event.target_id].hand_entry_id,old_entries[event.target_id] or 0)
        self.portable(g)

    def test_current_stored_stats_survive_private_residence_and_get(self):
        g=self.game(hand=('buff.deck','send','get.8'));self.play(g,'buff.deck');self.play(g,'send')
        originals=self.private(g);self.play(g,'get.8')
        for eid in originals:
            entity=g.state.entities[eid]
            self.assertEqual((entity.attack,entity.health),(6,7));self.assertEqual(entity.zone,Zone.HAND)
        self.portable(g)

    def test_other_setaside_cards_are_never_void_candidates(self):
        g=self.game(hand=('card.40','hide','send','get.8'));other=g.state.players[1].hand[0]
        self.play(g,'hide');self.play(g,'send');self.assertNotIn(other,self.private(g))
        self.play(g,'get.8');self.assertEqual(g.state.entities[other].zone,Zone.SETASIDE)
        self.assertEqual(g.state.players[1].setaside,[other]);self.portable(g)

    def test_minion_spell_weapon_and_location_follow_their_normal_hand_paths(self):
        g=self.game(cards=('card.1','coin','stored.weapon','stored.location'),hand=('send','get.8'),seed=2)
        self.play(g,'send');self.assertEqual(g.state.entities[g.state.players[1].deck[0]].card_id,'card.1')
        self.play(g,'get.8')
        for cid in ('coin','stored.weapon','stored.location'):self.play(g,cid)
        self.assertIsNotNone(g.state.players[1].weapon_id)
        self.assertTrue(any(g.state.entities[i].kind==CardType.LOCATION for i in g.state.players[1].board))
        self.portable(g)

    def test_full_hand_burn_consumes_the_member_and_creates_no_death(self):
        g=self.game(hand=('send','get.3','card.40'),rules=Ruleset(max_hand=3));self.play(g,'send')
        before=set(self.private(g));self.play(g,'get.3')
        burns=[e for e in g.events if e.kind=='card_burned']
        self.assertEqual(len(burns),1);self.assertIn(burns[0].target_id,before)
        self.assertEqual(g.state.entities[burns[0].target_id].zone,Zone.GRAVEYARD)
        self.assertEqual(len(self.private(g)),len(before)-3);self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_depleted_get_does_not_fatigue_or_recreate_consumed_cards(self):
        g=self.game(cards=('card.1','card.2'),hand=('send','get.8','get.2'));self.play(g,'send');self.play(g,'get.8')
        rng=g.snapshot()['rng_state'];count=len([e for e in g.events if e.kind=='void_card_taken'])
        self.play(g,'get.2');self.assertEqual(g.state.players[1].fatigue,0)
        self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(len([e for e in g.events if e.kind=='void_card_taken']),count)

    def test_a_later_send_appends_only_then_current_deck_cards(self):
        g=self.game(hand=('send','append','send','get.8'));self.play(g,'send')
        old=self.private(g);self.play(g,'append');deck_ids=tuple(g.state.players[1].deck)
        self.play(g,'send');self.assertEqual(self.private(g)[:len(old)],old)
        self.assertEqual(len(self.private(g)),len(old)+2)
        self.assertEqual(set(self.private(g)[len(old):]),set(deck_ids)-set(g.state.players[1].deck))
        self.play(g,'get.8');self.assertFalse(self.private(g));self.portable(g)

    def test_each_player_has_only_its_own_private_pile(self):
        for actor in (1,2):
            g=self.game(actor=actor);self.play(g,'send');self.play(g,'get.2')
            self.assertEqual(len(self.private(g,actor)),3);self.assertFalse(self.private(g,3-actor))
            self.assertFalse(g.state.players[3-actor].setaside);self.portable(g)

    def test_source_lifecycle_does_not_revoke_or_transfer_existing_player_storage(self):
        for action in ('kill','silence','bounce','transform','control','copy'):
            with self.subTest(action=action):
                g=self.game(hand=(IRIDA,action));self.play(g,IRIDA);initial=self.private(g)
                self.play(g,action);self.assertEqual(self.private(g),initial)
                self.cycle(g);self.assertEqual(len(self.private(g)),len(initial)-2)
                self.assertFalse(self.private(g,2));self.assertEqual(len(g.state.players[1].player_effects),1)
                self.portable(g)

    def test_summoned_or_copied_source_has_no_retroactive_battlecry(self):
        g=self.game(board=(IRIDA,),hand=('copy',));before=g.state.players[1].deck
        self.play(g,'copy');self.cycle(g)
        self.assertFalse(self.private(g));self.assertFalse(g.state.players[1].player_effects)
        self.assertEqual(len(g.state.players[1].deck),len(before)-1);self.portable(g)

    def test_owner_start_takes_two_then_preserves_natural_draw_and_fatigue(self):
        g=self.game(hand=(IRIDA,));self.play(g,IRIDA);kept=g.state.players[1].deck[0]
        self.cycle(g);self.assertEqual(len(self.private(g)),3);self.assertIn(kept,g.state.players[1].hand)
        self.assertEqual(g.state.players[1].fatigue,0)
        events=[e for e in g.events if e.action==g.state.action_number]
        kinds=[e.kind for e in events]
        self.assertEqual(kinds.count('void_card_taken'),2)
        self.assertLess(max(i for i,k in enumerate(kinds) if k=='void_card_taken'),kinds.index('card_drawn'))
        self.cycle(g);self.assertEqual(len(self.private(g)),1);self.assertEqual(g.state.players[1].fatigue,1)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,29);self.portable(g)

    def test_waiting_each_acquisition_restores_and_replays(self):
        g=self.game(wait=True);self.play(g,'send');self.play(g,'get.2')
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.private(g)),4)
        self.portable(g);self.choose(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.private(g)),3);self.portable(g);self.choose(g)
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_owner_start_waiting_preserves_unexecuted_natural_draw(self):
        g=self.game(hand=(IRIDA,),wait=True);self.play(g,IRIDA);kept=g.state.players[1].deck[0]
        self.cycle(g);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].deck,[kept]);self.portable(g)
        self.choose(g);self.assertEqual(g.state.players[1].deck,[kept]);self.portable(g)
        self.choose(g);self.assertFalse(g.state.players[1].deck);self.portable(g)

    def test_later_choice_failure_preserves_previous_consumption_and_waiting(self):
        g=self.game(wait=True,fault=True);self.play(g,'send');self.play(g,'get.2');before=g.snapshot()
        self.assertEqual(len(self.private(g)),4)
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_send_and_get_immediate_errors_roll_back_the_entire_failed_action(self):
        for stage in ('send','get'):
            g=self.game(immediate=stage)
            if stage=='get':self.play(g,'send')
            before=g.snapshot()
            with self.assertRaises(ResolutionError):self.play(g,'send' if stage=='send' else 'get.2')
            self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_player_interfaces_do_not_publish_private_faces_rows_or_receipts(self):
        views=[]
        for start in (1,11):
            g=self.game(cards=tuple(f'card.{i}' for i in range(start,start+6)),hand=(IRIDA,))
            self.play(g,IRIDA);views.append((g.observe(2),g.for_player(2).legal_actions(),g.player_events(2)))
            for pid in (1,2):
                value=json.dumps(g.observe(pid));log=json.dumps(g.player_events(pid))
                self.assertNotIn('void_cards',value);self.assertNotIn('void_deck_stored',log)
                self.assertNotIn('void_card_taken',log)
            self.assertEqual(g.for_player(2).legal_actions()['actions'],[{'type':'concede'}]);self.portable(g)
        self.assertEqual(views[0],views[1])

    def test_rehashed_wrong_residence_faces_identity_and_cropped_members_are_rejected(self):
        g=self.game();self.play(g,'send')
        changes=[lambda s:s['state']['players']['1']['void_cards'].clear(),
            lambda s:s['state']['players']['1']['void_cards'].append(deepcopy(s['state']['players']['1']['void_cards'][0])),
            lambda s:s['state']['players']['1']['void_cards'][0].update(zone_epoch=999),
            lambda s:s['state']['players']['1']['void_cards'][0].update(card_id='card.40'),
            lambda s:s['state']['players']['1']['void_cards'][0].update(entity_id=True),
            lambda s:s['state']['players']['1'].pop('void_cards')]
        for change in changes:
            with self.subTest(change=change):self.reject(g,change)

    def test_rehashed_original_keep_policy_and_consumption_receipts_are_rejected(self):
        g=self.game();self.play(g,'send');self.play(g,'get.2')
        def event(s,kind):return next(e for e in s['events'] if e['kind']==kind)
        for change in [lambda s:event(s,'void_deck_stored')['data'].update(kept_id=None),
                lambda s:event(s,'void_deck_stored')['data'].update(policy='guessed'),
                lambda s:event(s,'void_card_taken')['data']['card'].__setitem__(2,999),
                lambda s:s['events'].append(deepcopy(event(s,'void_card_taken')))]:
            with self.subTest(change=change):self.reject(g,change)

    def test_current_strict_layout_and_previous_versions_are_explicit(self):
        g=self.game();saved=g.snapshot()
        self.assertEqual((saved['schema_version'],g.ruleset.id,g.mechanics.version),
            (265,'prototype-v302',CORE_EFFECTS_VERSION))
        self.assertEqual(saved['state']['players']['1']['void_cards'],[])
        for version in (1,169,217,True):
            with self.subTest(version=version):self.reject(g,lambda s:s.update(schema_version=version))

    def test_constructed_opening_and_real_paid_source_restore_with_the_same_original_deck(self):
        self.options=dict(wait=False,fault=False,immediate=None);r=registry()
        own=deck(CardClass.DEMON_HUNTER,(IRIDA,*(f'card.{i}' for i in range(1,30))))
        seed=next(n for n in range(100) if self.source_in_opening(n))
        g=Game.from_decks(replace(setup(r,decks=(own,deck(CardClass.WARRIOR))),seed=seed),r)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g)
        while g.state.pending_choice:
            pending=g.state.pending_choice;g.apply(SelectChoice(pending.player_id,pending.id,()))
        while g.state.players[1].mana<4:self.cycle(g)
        original=g.state.players[1].original_deck;before=g.state.players[1].deck
        self.play(g,IRIDA);self.assertEqual(len(self.private(g)),len(before)-1)
        self.assertEqual(g.state.players[1].original_deck,original);self.portable(g)

    def source_in_opening(self,seed):
        values=list(range(30));random.Random(seed).shuffle(values)
        return 0 in values[:3]


if __name__ == '__main__':
    unittest.main()
