"""Independent Invoke state, real Shaman representatives and isolated routing probes."""
from dataclasses import replace
from pathlib import Path
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, EndTurn,
    Game, Keyword, PlayCard, PlayerSetup, Rarity, Registry, ResolutionError, Scenario,
    SelectChoice, SnapshotError, UnsupportedDefinitionError, Zone)
from hs_sim.engine.effects import (AddToHand, Buff, ChoiceOption, EquipWeapon, GainArmor, GrantKeyword,
    ReplaceHero, ReplaceHeroPower, RequestChoice, Summon)
from hs_sim.engine.invoke import (CLASSES, GalakrondFamily, Invoke, InvokeProfile,
    VERSION, invoke_count, main_for)
from hs_sim.engine.model import TriggerSpec
from hs_sim.engine.player_target_inputs import capture as capture_observation, decode as decode_observation, canonical
from hs_sim.engine.pools import (GenerationContext, PoolCard, PoolDefinition,
    PoolMember, PoolQuery, resolve_candidates)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference, CopyCard, DestroyDeckCard, MoveCard
from hs_sim.targets import canonical_digest


FIXTURE = Path(__file__).resolve().parents[1] / 'data/support/invoke-basics.json'
PIN = 'e955ec4ffecb5efaa86196f555a4133e10647b0098ae04783139224fd9eac26f'
SHAMAN = ('DRG_620', 'DRG_620t2', 'DRG_620t3')
STORMS = ('DRG_620t4', 'DRG_620t5', 'DRG_620t6')
FURY, ELEMENTAL, CLAW = 'DRG_238p4', 'DRG_238t14t3', 'DRG_238ht'
SHIELD, ELEMENTALIST, RITUAL = 'DRG_242', 'DRG_218', 'DRG_021'
CONTEXT = GenerationContext('invoke-validation-only', 'experimental')


def evidence():
    data = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if canonical_digest(data) != PIN:
        raise ValueError('Invoke complete raw pin changed')
    for row in data['records']:
        if row['id'] != row['data']['id'] or canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Invoke original record changed')
    return {row['id']: row['data'] for row in data['records']}


def probe_forms(cls):
    return tuple(f'probe.{cls.value}.{n}' for n in range(3))


def profile():
    return InvokeProfile(VERSION, tuple(GalakrondFamily(cls,
        SHAMAN if cls == CardClass.SHAMAN else probe_forms(cls), f'gift.{cls.value}')
        for cls in sorted(CLASSES)))


def registry(extras=(), omitted=None, gift=None, listener=False):
    r = Registry('invoke-basic-tests-' + VERSION)
    r.register_invoke_profile(profile())
    for cls in (CardClass.MAGE, *sorted(CLASSES)):
        r.register_card(CardDefinition('hero.' + cls.value, cls.value, CardType.HERO, health=40,
            metadata=CardMetadata(False, (cls,), None)))
    for family in profile().families:
        if family.hero_class == CardClass.SHAMAN:
            r.register_behavior(family.gift_behavior, gift or (lambda c: (Summon(c.player_id, ELEMENTAL),)))
            continue
        # Synthetic probes test family routing only, never stand in for real random pools.
        r.register_behavior(family.gift_behavior,
            lambda c, cls=family.hero_class: (GainArmor(c.player_id,
                                                    tuple(sorted(CLASSES)).index(cls) + 1),))
        for cid in family.forms:
            r.register_card(CardDefinition(cid, cid, CardType.HERO, cost=7, health=30,
                hero_card=True, initial_hero_power='dummy.power',
                metadata=CardMetadata(False, (family.hero_class,), None)))
    r.register_behavior('dummy.power', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('dummy.power', 'Dummy power', CardType.HERO_POWER,
        cost=2, on_use='dummy.power'))
    r.register_card(CardDefinition('body', 'body', CardType.MINION, attack=1, health=4))
    r.register_behavior('once', lambda c: (Invoke(c.player_id, c.source_id),))
    r.register_behavior('twice', lambda c: (Invoke(c.player_id, c.source_id, 2),))
    r.register_behavior('none', lambda c: (Invoke(c.player_id, c.source_id, 0),))
    for cid in ('once', 'twice', 'none'):
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, keywords=(Keyword.INVOKE,)))
    raw = evidence()
    for n, cid in enumerate(SHAMAN):
        row, tags = raw[cid], raw[cid]['tags']
        r.register_behavior('battlecry.' + cid, lambda c, n=n: (
            Summon(c.player_id, STORMS[n]), Summon(c.player_id, STORMS[n]),
            *((EquipWeapon(c.player_id, CLAW),) if n == 2 else ())))
        r.register_card(CardDefinition(cid, row['name'], CardType.HERO, cost=tags['COST'],
            health=tags['HEALTH'], hero_card=True, hero_armor=tags['ARMOR'], initial_hero_power=FURY,
            battlecry='battlecry.' + cid,
            metadata=CardMetadata(row['collectible'], (CardClass.SHAMAN,), Rarity.LEGENDARY)))
    for cid in (*STORMS, ELEMENTAL):
        row, tags = raw[cid], raw[cid]['tags']
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION, cost=tags['COST'],
            attack=tags['ATK'], health=tags['HEALTH'], keywords=(Keyword.RUSH,),
            metadata=CardMetadata(False, (CardClass.SHAMAN,), None, tribes=('elemental',))))
    r.register_behavior('power.fury', lambda c: (Summon(c.player_id, ELEMENTAL),))
    r.register_card(CardDefinition(FURY, raw[FURY]['name'], CardType.HERO_POWER, cost=2,
        on_use='power.fury', metadata=CardMetadata(False, (CardClass.SHAMAN,), None)))
    r.register_card(CardDefinition(CLAW, raw[CLAW]['name'], CardType.WEAPON,
        cost=raw[CLAW]['cost'], attack=5, durability=2))
    row = raw[RITUAL]
    r.register_card(CardDefinition(RITUAL, row['name'], CardType.WEAPON, cost=row['cost'],
        attack=row['attack'], durability=row['health'], battlecry='once', keywords=(Keyword.INVOKE,),
        metadata=CardMetadata(True, (CardClass.WARRIOR,), Rarity.RARE)))
    for cid, behavior in ((SHIELD, 'once'), (ELEMENTALIST, 'twice')):
        row, tags = raw[cid], raw[cid]['tags']
        r.register_card(CardDefinition(cid, row['name'], CardType.MINION,
            cost=tags['COST'], attack=tags['ATK'], health=tags['HEALTH'], battlecry=behavior,
            keywords=(Keyword.INVOKE, *((Keyword.TAUNT,) if cid == SHIELD else ())),
            metadata=CardMetadata(True, (CardClass.NEUTRAL if cid == SHIELD else CardClass.SHAMAN,),
                Rarity.COMMON if cid == SHIELD else Rarity.RARE,
                tribes=('demon',) if cid == SHIELD else ())))
    if listener:
        r.register_behavior('heard.invoke', lambda c: (
            GainArmor(c.player_id, invoke_count(c.state, c.player_id)),))
        r.register_card(CardDefinition('listener', 'listener', CardType.MINION, health=4,
            triggers=(TriggerSpec('galakrond_invoked', 'heard.invoke'),)))
    for cid, fn in extras:
        r.register_behavior(cid, lambda c, fn=fn: fn(c, r))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))
    if omitted is not None:
        if omitted in r._cards:
            r._cards.pop(omitted)
        else:
            r._behaviors.pop(omitted)
    return r


class InvokeBasicsTests(unittest.TestCase):
    def setUp(self):
        self.extras = []
        self.gift = None

    def script(self, cid, fn):
        self.extras.append((cid, fn))

    def game(self, hand=('once', SHAMAN[0]), deck=(), board=(), cls=CardClass.SHAMAN,
             enemy_hand=(), enemy_deck=(), omitted=None, listener=False):
        r = registry(self.extras, omitted, self.gift, listener)
        return Game.from_scenario(Scenario((PlayerSetup('hero.' + cls.value,
            hand=hand, deck=deck, board=board, max_mana=10, mana=10,
            hero_power_card_id='dummy.power'), PlayerSetup('hero.mage',
            hand=enemy_hand, deck=enemy_deck, max_mana=10, mana=10)), seed=8,
            generation_context=CONTEXT), r)

    def play(self, g, cid, pid=1):
        eid = next(i for i in g.state.players[pid].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(pid, eid))
        return eid

    def main(self, g, pid=1):
        return main_for(g.state, g.registry, pid)

    def check(self, g, listener=False):
        snap = g.snapshot()
        fresh = lambda: registry(self.extras, gift=self.gift, listener=listener)
        self.assertEqual(Game.from_snapshot(snap, fresh()).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), fresh()).snapshot(), snap)
        for pid in (1, 2):
            self.assertEqual(Game.from_snapshot(snap, fresh()).observe(pid), g.observe(pid))

    def rejected(self, g, mutate):
        s = g.snapshot()
        mutate(s)
        s['events_hash'] = canonical_hash(s['events'])
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s, registry(self.extras, gift=self.gift))

    def test_no_galakrond_is_no_reward_no_success_no_rng(self):
        g = self.game(hand=('once',))
        rng = g.snapshot()['rng_state']
        self.play(g, 'once')
        self.assertIsNone(self.main(g))
        self.assertEqual(invoke_count(g.state, 1), 0)
        self.assertEqual(g.state.invoke_history[0].main_id, None)
        self.assertEqual(g.state.players[1].board, [])
        self.assertEqual(g.snapshot()['rng_state'], rng)
        self.check(g)

    def test_zero_invokes_is_true_no_op(self):
        g = self.game(hand=('none', SHAMAN[0]))
        self.play(g, 'none')
        self.assertEqual(g.state.invoke_history, [])
        self.assertEqual(self.main(g).galakrond_invocations, 0)

    def test_real_shield_pays_once_and_summons_actual_rush_elemental(self):
        g = self.game(hand=(SHIELD, SHAMAN[0]))
        eid = self.play(g, SHIELD)
        self.assertEqual(g.state.players[1].mana, 5)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [SHIELD, ELEMENTAL])
        self.assertEqual((self.main(g).galakrond_invocations, invoke_count(g.state, 1)), (1, 1))
        self.assertEqual(g.state.invoke_history[0].source_id, eid)
        self.assertEqual((len(g.state.play_history), len(g.state.hero_power_history)), (1, 0))
        self.check(g)

    def test_real_elementalist_invokes_twice_with_two_independent_rewards(self):
        g = self.game(hand=(ELEMENTALIST, SHAMAN[0]))
        self.play(g, ELEMENTALIST)
        self.assertEqual(self.main(g).card_id, SHAMAN[1])
        self.assertEqual([x.progress_after for x in g.state.invoke_history], [1, 2])
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
                         [ELEMENTALIST, ELEMENTAL, ELEMENTAL])
        self.assertEqual(g.state.players[1].mana, 5)
        self.check(g)

    def test_real_ritual_chopper_invokes_once_without_using_current_power(self):
        g = self.game(hand=(RITUAL, SHAMAN[0]), cls=CardClass.WARRIOR)
        eid = self.play(g, RITUAL)
        self.assertEqual(g.state.players[1].weapon_id, eid)
        self.assertEqual((g.state.entities[eid].attack, g.state.entities[eid].durability), (1, 2))
        self.assertEqual(g.state.players[1].mana, 8)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board], [ELEMENTAL])
        self.assertEqual(invoke_count(g.state, 1), 1)
        self.assertEqual(g.state.hero_power_history, [])
        self.check(g)

    def test_invoke_effect_contract_and_missing_profile_are_explicit(self):
        for fields in ({'player_id': True}, {'player_id': 3}, {'player_id': 1, 'count': True},
                       {'player_id': 1, 'count': -1}, {'player_id': 1, 'source_id': 0}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                Invoke(**fields)
        r = Registry('no-invoke-profile')
        r.register_card(CardDefinition('h', 'h', CardType.HERO, health=30))
        r.register_behavior('try', lambda c: (Invoke(c.player_id, c.source_id),))
        r.register_card(CardDefinition('try', 'try', CardType.SPELL, on_play='try'))
        g = Game.from_scenario(Scenario((PlayerSetup('h', hand=('try',)), PlayerSetup('h'))), r)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'try')
        self.assertEqual(g.snapshot(), before)

    def test_bare_invoke_keyword_grant_cannot_fabricate_an_effect(self):
        self.script('grant', lambda c, r: (GrantKeyword(c.state.players[1].board[0], Keyword.INVOKE),))
        g = self.game(hand=('grant', SHAMAN[0]), board=('body',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, 'grant')
        self.assertEqual(g.snapshot(), before)

    def test_hand_four_then_fifth_invokes_upgrade_at_two_four_only(self):
        g = self.game(hand=('once',) * 5 + (SHAMAN[0],))
        eid = self.main(g).id
        for count, face in enumerate((SHAMAN[0], SHAMAN[1], SHAMAN[1], SHAMAN[2], SHAMAN[2]), 1):
            self.play(g, 'once')
            self.assertEqual((self.main(g).id, self.main(g).card_id, self.main(g).galakrond_invocations),
                             (eid, face, min(4, count)))
        self.assertEqual(invoke_count(g.state, 1), 5)
        self.check(g)

    def test_deck_upgrade_preserves_order_physical_id_and_no_draw(self):
        g = self.game(hand=('twice', 'twice'), deck=('body', SHAMAN[0], 'body'))
        deck, eid = list(g.state.players[1].deck), self.main(g).id
        self.play(g, 'twice'); self.play(g, 'twice')
        self.assertEqual((self.main(g).id, self.main(g).zone, self.main(g).card_id), (eid, Zone.DECK, SHAMAN[2]))
        self.assertEqual(g.state.players[1].deck, deck)
        self.assertEqual(g.state.draw_history, [])
        self.check(g)

    def test_existing_upgraded_face_starts_at_its_printed_minimum(self):
        for cid, count in ((SHAMAN[1], 2), (SHAMAN[2], 4)):
            with self.subTest(cid=cid):
                g = self.game(hand=('once', cid))
                self.assertEqual(self.main(g).galakrond_invocations, count)
                self.play(g, 'once')
                self.assertEqual(self.main(g).galakrond_invocations, min(4, count + 1))
                self.assertEqual(invoke_count(g.state, 1), 1)

    def test_current_hero_class_does_not_select_gift_when_main_is_shaman(self):
        g = self.game(cls=CardClass.WARRIOR)
        self.play(g, 'once')
        self.assertEqual(g.state.players[1].hero_class, CardClass.WARRIOR)
        self.assertEqual(g.state.entities[g.state.players[1].board[0]].card_id, ELEMENTAL)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 0)

    def test_five_class_profile_routes_using_main_family_synthetic_probes(self):
        for cls in sorted(CLASSES):
            with self.subTest(cls=cls):
                cid = SHAMAN[0] if cls == CardClass.SHAMAN else probe_forms(cls)[0]
                g = self.game(hand=('once', cid), cls=CardClass.MAGE)
                self.play(g, 'once')
                self.assertEqual(g.state.invoke_history[0].hero_class, cls)
                self.assertEqual(self.main(g).galakrond_invocations, 1)
                if cls != CardClass.SHAMAN:
                    self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,
                                     tuple(sorted(CLASSES)).index(cls) + 1)

    def test_initial_selection_prefers_class_over_earlier_foreign_card(self):
        g = self.game(deck=(probe_forms(CardClass.ROGUE)[0], SHAMAN[0]))
        self.assertEqual(self.main(g).card_id, SHAMAN[0])
        self.play(g, 'once')
        rogue = next(e for e in g.state.entities.values() if e.card_id == probe_forms(CardClass.ROGUE)[0])
        self.assertEqual(rogue.galakrond_invocations, 0)

    def test_no_class_match_uses_first_physical_card(self):
        rogue = probe_forms(CardClass.ROGUE)[0]
        g = self.game(hand=('once', SHAMAN[0]), deck=(rogue,), cls=CardClass.MAGE)
        self.assertEqual(self.main(g).card_id, rogue)
        self.play(g, 'once')
        self.assertEqual(self.main(g).card_id, rogue)

    def test_main_persists_when_later_matching_class_card_arrives(self):
        rogue = probe_forms(CardClass.ROGUE)[0]
        self.script('add', lambda c, r: (AddToHand(1, SHAMAN[0]),))
        g = self.game(hand=('add', 'once'), deck=(rogue,))
        eid = self.main(g).id
        self.play(g, 'add'); self.play(g, 'once')
        self.assertEqual(self.main(g).id, eid)
        self.assertEqual(self.main(g).galakrond_invocations, 1)

    def test_destroyed_main_reselects_remaining_card_without_copying_progress(self):
        self.script('remove', lambda c, r: (DestroyDeckCard(CardReference.capture(main_for(c.state, r, 1))),))
        g = self.game(hand=('once', 'remove', 'once', SHAMAN[0]), deck=(SHAMAN[0],))
        first = self.main(g).id
        self.play(g, 'once'); self.play(g, 'remove')
        self.assertNotEqual(self.main(g).id, first)
        self.assertEqual(self.main(g).galakrond_invocations, 0)
        self.play(g, 'once')
        self.assertEqual((self.main(g).galakrond_invocations, invoke_count(g.state, 1)), (1, 2))
        self.check(g)

    def test_missing_after_destruction_causes_next_invoke_no_effect(self):
        self.script('remove', lambda c, r: (DestroyDeckCard(CardReference.capture(main_for(c.state, r, 1))),))
        g = self.game(hand=('once', 'remove', 'once'), deck=(SHAMAN[0],))
        self.play(g, 'once'); self.play(g, 'remove'); self.play(g, 'once')
        self.assertIsNone(self.main(g))
        self.assertEqual(invoke_count(g.state, 1), 1)
        self.check(g)

    def test_stolen_main_binds_new_controller_and_not_original_owner(self):
        self.script('steal', lambda c, r: (MoveCard(CardReference.capture(
            c.state.entities[c.state.players[2].deck[0]]), 1, Zone.HAND),))
        g = self.game(hand=('steal', 'once'), enemy_deck=(SHAMAN[0],))
        self.play(g, 'steal'); self.play(g, 'once')
        self.assertEqual((self.main(g).owner, self.main(g).controller), (2, 1))
        self.assertIsNone(self.main(g, 2))
        self.assertEqual((invoke_count(g.state, 1), invoke_count(g.state, 2)), (1, 0))
        self.check(g)

    def test_base_hero_played_stops_upgrades_but_still_rewards(self):
        g = self.game(hand=(SHAMAN[0], 'twice', 'twice'))
        eid = self.play(g, SHAMAN[0])
        self.play(g, 'twice'); self.play(g, 'twice')
        self.assertEqual((self.main(g).id, self.main(g).card_id, self.main(g).galakrond_invocations),
                         (eid, SHAMAN[0], 0))
        self.assertEqual(invoke_count(g.state, 1), 4)
        self.assertEqual([x.main_zone for x in g.state.invoke_history], [Zone.HERO] * 4)
        self.assertEqual(len(g.state.hero_power_history), 0)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0)
        self.check(g)

    def test_each_real_hero_face_has_actual_battlecry_power_armor_and_final_claw(self):
        for n, cid in enumerate(SHAMAN):
            with self.subTest(cid=cid):
                g = self.game(hand=(cid,))
                self.play(g, cid)
                p = g.state.players[1]
                self.assertEqual(p.mana, 3)
                self.assertEqual(g.state.entities[p.hero_id].armor, 5)
                self.assertEqual(g.state.entities[p.hero_power_id].card_id, FURY)
                self.assertEqual([g.state.entities[i].card_id for i in p.board], [STORMS[n]] * 2)
                self.assertEqual([g.state.entities[i].attack for i in p.board], [2 << n] * 2)
                self.assertEqual(p.weapon_id is not None, n == 2)
                if n == 2:
                    self.assertEqual((g.state.entities[p.weapon_id].card_id,
                        g.state.entities[p.weapon_id].attack, g.state.entities[p.weapon_id].durability),
                        (CLAW, 5, 2))
                self.check(g)

    def test_played_other_galakrond_becomes_main(self):
        rogue = probe_forms(CardClass.ROGUE)[0]
        g = self.game(hand=(rogue, 'once', SHAMAN[0]))
        self.assertEqual(self.main(g).card_id, SHAMAN[0])
        eid = self.play(g, rogue); self.play(g, 'once')
        self.assertEqual((self.main(g).id, self.main(g).card_id), (eid, rogue))
        self.assertEqual(g.state.invoke_history[0].hero_class, CardClass.ROGUE)
        self.assertEqual(next(e.galakrond_invocations for e in g.state.entities.values()
                              if e.card_id == SHAMAN[0]), 0)

    def test_replacing_galakrond_with_ordinary_hero_removes_presence(self):
        self.script('replace', lambda c, r: (ReplaceHero(1, 'hero.mage'),))
        g = self.game(hand=(SHAMAN[0], 'replace', 'once'))
        self.play(g, SHAMAN[0]); self.play(g, 'replace'); self.play(g, 'once')
        self.assertIsNone(self.main(g))
        self.assertEqual(invoke_count(g.state, 1), 0)
        self.check(g)

    def test_changed_current_power_does_not_change_gift_or_use_power(self):
        self.script('power', lambda c, r: (ReplaceHeroPower(1, 'dummy.power'),))
        g = self.game(hand=(SHAMAN[0], 'power', 'once'))
        self.play(g, SHAMAN[0]); self.play(g, 'power'); self.play(g, 'once')
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id, 'dummy.power')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
                         [STORMS[0], STORMS[0], ELEMENTAL])
        self.assertEqual(g.state.players[1].mana, 3)
        self.assertEqual(g.state.hero_power_history, [])

    def test_full_board_still_counts_and_upgrades(self):
        g = self.game(hand=('twice', SHAMAN[0]), board=('body',) * 7)
        self.play(g, 'twice')
        self.assertEqual((self.main(g).card_id, invoke_count(g.state, 1)), (SHAMAN[1], 2))
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(sum(e.kind == 'summon_failed' for e in g.events), 2)
        self.check(g)

    def test_progress_is_committed_before_invoke_reactions(self):
        g = self.game(hand=('twice', SHAMAN[0]), board=('listener',), listener=True)
        self.play(g, 'twice')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.check(g, listener=True)

    def test_current_card_copy_preserves_half_progress_base_copy_does_not(self):
        self.script('copy', lambda c, r: tuple(CopyCard(CardReference.capture(main_for(c.state, r, 1)),
                                                       1, mode=mode) for mode in ('current', 'base')))
        g = self.game(hand=('once', 'copy', SHAMAN[0]))
        original = self.main(g).id
        self.play(g, 'once'); self.play(g, 'copy')
        cards = [e for e in g.state.entities.values() if e.card_id == SHAMAN[0]]
        self.assertEqual([e.galakrond_invocations for e in cards], [1, 1, 0])
        self.assertEqual(self.main(g).id, original)
        self.assertEqual(invoke_count(g.state, 1), 1)
        self.check(g)

    def test_deck_to_hand_keeps_existing_physical_progress(self):
        self.script('drawmain', lambda c, r: (MoveCard(CardReference.capture(main_for(c.state, r, 1)),
                                                      1, Zone.HAND, draw=True),))
        g = self.game(hand=('once', 'drawmain', 'once'), deck=(SHAMAN[0],))
        eid = self.main(g).id
        self.play(g, 'once'); self.play(g, 'drawmain'); self.play(g, 'once')
        self.assertEqual((self.main(g).id, self.main(g).zone, self.main(g).card_id), (eid, Zone.HAND, SHAMAN[1]))
        self.check(g)

    def test_reset_stored_card_resets_half_progress_without_changing_global_history(self):
        self.script('reset', lambda c, r: (MoveCard(CardReference.capture(main_for(c.state, r, 1)),
                                                   1, Zone.DECK, reset=True),))
        g = self.game(hand=('once', 'reset', SHAMAN[0]))
        self.play(g, 'once'); self.play(g, 'reset')
        self.assertEqual((self.main(g).galakrond_invocations, invoke_count(g.state, 1)), (0, 1))
        self.check(g)

    def test_each_player_has_independent_main_progress_and_history(self):
        g = self.game(hand=('once', SHAMAN[0]), enemy_hand=('once', SHAMAN[0]))
        self.play(g, 'once'); g.apply(EndTurn(1)); self.play(g, 'once', 2)
        self.assertEqual((invoke_count(g.state, 1), invoke_count(g.state, 2)), (1, 1))
        self.assertEqual([self.main(g, pid).galakrond_invocations for pid in (1, 2)], [1, 1])
        self.check(g)

    def test_waiting_gift_resumes_original_first_use_then_second_use(self):
        self.gift = lambda c: (RequestChoice(c.player_id, (
            ChoiceOption('gift', 'gift', (Summon(c.player_id, ELEMENTAL),)),), source_id=c.source_id),)
        g = self.game(hand=(ELEMENTALIST, SHAMAN[0]))
        self.play(g, ELEMENTALIST)
        for count in (1, 2):
            self.assertEqual((len(g.state.invoke_history), invoke_count(g.state, 1)), (count, count))
            self.assertIsNotNone(g.state.pending_choice)
            self.check(g)
            choice = g.state.pending_choice
            g.apply(SelectChoice(1, choice.id, ('gift',)))
        self.assertEqual(self.main(g).card_id, SHAMAN[1])
        self.assertEqual(len(g.state.players[1].board), 3)
        self.check(g)

    def test_original_action_failure_rolls_back_upgrade_history_rng_and_payment(self):
        self.gift = lambda c: (Summon(c.player_id, 'unimplemented.gift'),)
        g = self.game(hand=(ELEMENTALIST, SHAMAN[0]))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g, ELEMENTALIST)
        self.assertEqual(g.snapshot(), before)

    def test_missing_gift_or_upgrade_form_is_an_error_before_progress(self):
        for missing in ('gift.shaman', SHAMAN[1]):
            with self.subTest(missing=missing):
                g = self.game(hand=('twice', SHAMAN[0]), omitted=missing)
                before = g.snapshot()
                with self.assertRaises(ResolutionError):
                    self.play(g, 'twice')
                self.assertEqual(g.snapshot(), before)

    def test_owner_sees_hand_progress_enemy_does_not_see_hidden_main_or_count(self):
        g = self.game(hand=('twice', SHAMAN[0]))
        self.play(g, 'twice')
        own, enemy = g.observe(1), g.observe(2)
        mine = next(p for p in own['players'] if p['id'] == 1)
        hidden = next(p for p in enemy['players'] if p['id'] == 1)
        self.assertEqual(mine['invoke_count'], 2)
        self.assertEqual(mine['hand'][0]['invoke_progress'], 2)
        self.assertNotIn('invoke_count', hidden)
        self.assertNotIn('invoke_progress', hidden['hand'][0])
        self.assertNotIn(SHAMAN[1], json.dumps(enemy))
        events = g.player_events(2)
        invocations = [e for e in events if e['kind'] == 'galakrond_invoked']
        self.assertEqual(len(invocations), 2)
        self.assertFalse(any('invoke_id' in e or 'main_id' in e for e in invocations))
        self.check(g)

    def test_deck_progress_never_projects_as_trackable_deck_entity(self):
        g = self.game(hand=('twice',), deck=(SHAMAN[0],))
        self.play(g, 'twice')
        for pid in (1, 2):
            view = json.dumps(g.observe(pid))
            self.assertNotIn(SHAMAN[1], view)
            self.assertNotIn('galakrond_mains', view)
            self.assertNotIn('main_epoch', view)
        self.check(g)

    def test_paid_observation_accepts_private_invoke_fields(self):
        g = self.game(hand=('once', SHAMAN[0]))
        self.play(g, 'once')
        source = g._state.entities[self.main(g).id]
        proof = capture_observation(g, g._state, source)
        self.assertEqual(decode_observation(proof), g.observe(1))

    def test_paid_observation_without_profile_does_not_require_private_counter(self):
        r = Registry('ordinary-observation')
        r.register_card(CardDefinition('h', 'h', CardType.HERO, health=30))
        r.register_card(CardDefinition('s', 's', CardType.SPELL))
        g = Game.from_scenario(Scenario((PlayerSetup('h', hand=('s',)), PlayerSetup('h'))), r)
        source = g._state.entities[g.state.players[1].hand[0]]
        proof = capture_observation(g, g._state, source)
        self.assertEqual(decode_observation(proof), g.observe(1))
        self.assertTrue(all('invoke_count' not in p for p in g.observe(1)['players']))

    def test_paid_observation_rejects_foreign_or_noninteger_private_invoke_count(self):
        g = self.game(hand=('once', SHAMAN[0]))
        self.play(g, 'once')
        proof = capture_observation(g, g._state, g._state.entities[self.main(g).id])
        for owner, value in ((1, True), (1, -1), (1, 1.5), (2, 0)):
            view = json.loads(proof.observation_json)
            view['players'][owner - 1]['invoke_count'] = value
            with self.subTest(owner=owner, value=value), self.assertRaises(ValueError):
                decode_observation(replace(proof, observation_json=canonical(view)))

    def test_paid_observation_rejects_invalid_visible_invoke_progress(self):
        g = self.game(hand=('once', SHAMAN[0]))
        self.play(g, 'once')
        proof = capture_observation(g, g._state, g._state.entities[self.main(g).id])
        for value in (True, -1, 5, 1.0):
            view = json.loads(proof.observation_json)
            view['players'][0]['hand'][0]['invoke_progress'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_observation(replace(proof, observation_json=canonical(view)))

    def test_basic_keyword_observation_fields_keep_original_projection(self):
        from hs_sim.engine import UseHandAction
        from hs_sim.engine.model import HandActionSpec
        for kind in ('prepare', 'disguised'):
            with self.subTest(kind=kind):
                r = Registry('single-keyword-observation-' + kind)
                r.register_card(CardDefinition('h', 'h', CardType.HERO, health=30))
                fields = {'hand_actions': (HandActionSpec('prepare', 'prepare', 1),)} if kind == 'prepare' else {'disguised': True}
                r.register_card(CardDefinition('s', 's', CardType.MINION, cost=5, health=2, **fields))
                g = Game.from_scenario(Scenario((PlayerSetup('h', hand=('s',), max_mana=3, mana=3),
                                                PlayerSetup('h'))), r)
                eid = g.state.players[1].hand[0]
                if kind == 'prepare':
                    g.apply(UseHandAction(1, eid, 'prepare'))
                proof = capture_observation(g, g._state, g._state.entities[eid])
                self.assertEqual(decode_observation(proof), g.observe(1))

    def test_strict_snapshot_rejects_progress_binding_and_history_tampering(self):
        g = self.game(hand=('twice', SHAMAN[0]))
        self.play(g, 'twice')
        eid = str(self.main(g).id)
        mutations = (
            lambda s: s['state']['entities'][eid].update(galakrond_invocations=True),
            lambda s: s['state']['entities'][eid].update(galakrond_invocations=4),
            lambda s: s['state']['galakrond_mains'].update({'1': None}),
            lambda s: s['state']['galakrond_mains']['1'].update(hero_class='rogue'),
            lambda s: s['state']['invoke_history'][1].update(count_before=0),
            lambda s: s['state']['invoke_history'][1].update(card_after=SHAMAN[2]),
            lambda s: s['state']['invoke_history'][0].update(profile_version='future'),
            lambda s: s['state']['invoke_history'][0].update(main_zone='graveyard'),
            lambda s: s['state']['invoke_history'][0].update(progress_after=True),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.rejected(g, mutation)

    def test_new_snapshot_fields_required_and_old_schema_rejected(self):
        g = self.game()
        for field in ('invoke_history', 'galakrond_mains'):
            self.rejected(g, lambda s, field=field: s['state'].pop(field))
        for version in (1, 149, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 217, True):
            s = g.snapshot(); s['schema_version'] = version
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(s, registry())

    def test_invoke_events_cannot_be_removed_reordered_or_retargeted(self):
        g = self.game(hand=('twice', SHAMAN[0]))
        self.play(g, 'twice')
        indexes = [i for i, e in enumerate(g.snapshot()['events']) if e['kind'] == 'galakrond_invoked']
        mutations = (
            lambda s: s['events'].pop(indexes[0]),
            lambda s: s['events'][indexes[0]].update(player_id=2),
            lambda s: s['events'][indexes[0]].update(amount=2),
            lambda s: s['events'][indexes[0]]['data'].update(invoke_id=2),
            lambda s: s['events'][indexes[0]]['data'].update(main_id=self.main(g).id),
            lambda s: s['state']['invoke_history'].pop(),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.rejected(g, mutate)

    def test_profile_shape_freeze_and_fingerprint_are_explicit(self):
        p = profile()
        with self.assertRaises(ValueError):
            replace(p, families=p.families[:-1])
        with self.assertRaises(ValueError):
            replace(p.families[0], forms=('x', 'x', 'z'))
        r = registry()
        with self.assertRaises(ValueError):
            r.register_invoke_profile(p)
        old = r.fingerprint()
        r._invoke_profile = replace(p, version='invoke-v2')
        self.assertNotEqual(r.fingerprint(), old)
        r.freeze()
        with self.assertRaises(ValueError):
            r.register_invoke_profile(p)

    def test_random_pool_bans_invoke_and_collectible_galakrond_before_adapter_lookup(self):
        r = Registry('invoke-pool-ban-only')
        ordinary = CardDefinition('ordinary', 'ordinary', CardType.MINION, health=1,
            metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON))
        r.register_card(ordinary)
        blocked = CardDefinition('unknown.invoke', 'unknown.invoke', CardType.SPELL,
            keywords=(Keyword.INVOKE,), metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.COMMON))
        gal = CardDefinition('DRG_620', 'Galakrond', CardType.HERO, cost=7, health=30,
            hero_card=True, initial_hero_power='not.adapted.power',
            metadata=CardMetadata(True, (CardClass.SHAMAN,), Rarity.LEGENDARY))
        for d in (ordinary, blocked, gal):
            r.register_pool_card(PoolCard.from_definition(d))
        r.register_pool(PoolDefinition('cards', 'v1', CONTEXT.target_id, CONTEXT.mode,
            tuple(PoolMember(d.id) for d in (ordinary, blocked, gal))))
        empty_origin = replace(CONTEXT, starting_decks=((), ()))
        self.assertEqual(tuple(x.card_id for x in resolve_candidates(r, empty_origin, 'cards', PoolQuery(), player_id=1)),
                         ('ordinary',))
        # A genuinely eligible unknown still errors: no filtering by coverage.
        unknown = replace(ordinary, id='unknown.ordinary')
        r.register_pool_card(PoolCard.from_definition(unknown))
        r.register_pool(PoolDefinition('other', 'v1', CONTEXT.target_id, CONTEXT.mode,
            (PoolMember('unknown.ordinary'),)))
        with self.assertRaises(UnsupportedDefinitionError):
            resolve_candidates(r, CONTEXT, 'other', PoolQuery())


if __name__ == '__main__':
    unittest.main()
