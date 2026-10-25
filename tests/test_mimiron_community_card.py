"""Actual Mimiron entry and bounded public-information community recommendations."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import build_registry
from hs_sim.cards.mimiron_community_card import ROOT, BODY, load_policy, scores, recommend
from hs_sim.cards.past_discovery_copy_card import SCOUT
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayerSetup, Rarity, Scenario, TargetMode, TargetSpec,
    TriggerSpec, Zone)
from hs_sim.engine.battlecry_sources import TriggerBattlecry
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import CostSpec, TribeChangeSpec
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes, has_any_tribe
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P = 'fixture.mimiron_community.'
MECH, UNIT, LEGEND, BEAST, DORM, WATCH, TRIBE, DISCOUNT, REPEAT, KILL, FAIL = (
    P+x for x in ('mech','unit','legend','beast','dormant','watch','tribe','discount','repeat','kill','fail'))
META = CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(maxsize=None)
def fixture(mode='normal', role='writer'):
    r = build_registry(); r._version += '.k539.'+mode
    for cid,attack,health,meta,extra in (
            (MECH,2,3,replace(META,tribes=('mech',)),{}),
            (UNIT,1,3,META,{}),
            (LEGEND,8,8,replace(META,rarity=Rarity.LEGENDARY),{}),
            (BEAST,5,5,replace(META,tribes=('beast',)),{}),
            (DORM,2,3,replace(META,tribes=('mech',)),{'dormant_turns':2})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health,metadata=meta,**extra))
    def fail(c): raise ResolutionError('K539 deliberate late delivery failure')
    r.register_behavior(FAIL,fail)
    bodies = {
        TRIBE:lambda c:(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),
            TribeChangeSpec('add',('mech',)),c.source_id),),
        DISCOUNT:lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=0,
            card_ids=('AV_135',)),uses_remaining=1,source_id=c.source_id),),
        REPEAT:lambda c:(TriggerBattlecry(MinionReference.capture(c.state.entities[c.target_id]),c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),
    }
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        targeting = TargetSpec(TargetMode.REQUIRED,zones=(Zone.HAND,),
            kinds=(CardType.MINION,),relation='friendly') if cid == TRIBE else (
            TargetSpec(TargetMode.REQUIRED,kinds=(CardType.MINION,)) if cid in (REPEAT,KILL) else None)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=targeting,metadata=META))
    def watch(c):
        source = c.state.entities.get(c.event.source_id)
        if source is None or source.card_id != ROOT:return ()
        if mode == 'return_source' and c.event.kind == 'battlecry_started':
            return (ReturnToHand(source.id),)
        if mode == 'fill' and c.event.kind == 'choice_selected':
            return (AddToHand(c.player_id,'GAME_005',c.source_id),)
        if c.event.kind != 'card_discovered':return ()
        if mode == 'fail':return (InvokeBehavior(FAIL,c.source_id,c.player_id),)
        if mode == 'wait':return (RequestChoice(c.player_id,(
            ChoiceOption('go','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(FAIL,c.source_id,c.player_id),))),c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=5,metadata=META,
        triggers=tuple(TriggerSpec(event,P+'watch') for event in
            ('battlecry_started','choice_selected','card_discovered'))))
    r.validate();return r


class MimironCommunityTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, *, mode='normal', own=(MECH,), enemy=(), hand=(ROOT,), mana=10,
            enemy_armor=0, enemy_hand=(), enemy_deck=('GAME_005',)*6):
        self.mode = mode
        if mode != 'normal':own = (*own,WATCH)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=hand,board=own,
            deck=('GAME_005',)*6,mana=mana,max_mana=mana),
            PlayerSetup('HERO_08',hand=enemy_hand,deck=enemy_deck,board=enemy,armor=enemy_armor)),
            seed=17),fixture(mode))

    def menu(self,g):return tuple(o.card_id for o in g.state.pending_choice.options)

    def pick_card(self,g,cid):
        self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id == cid))

    def test_full_original_root_thirteen_complete_dependencies_and_explicit_local_scope(self):
        r = fixture();data = load_policy();raw = data['root']['record'];card = r.card(ROOT)
        self.assertEqual((card.cost,card.attack,card.health,card.battlecry),(1,2,1,BODY))
        self.assertNotIn('mech',card.metadata.tribes)
        self.assertEqual(raw['id'],ROOT);self.assertEqual(len(data['candidates']),13)
        self.assertFalse(data['official_pool_complete']);self.assertFalse(data['official_ranking_verified'])
        for row in data['candidates']:
            self.assertEqual(canonical_digest(asdict(r.card(row['card_id']))),row['definition_sha256'])
        self.assertNotIn('CORE_REV_023',{row['card_id'] for row in data['candidates']})

    def test_no_own_active_mech_no_discovery_but_original_play_still_pays(self):
        for own,enemy in (((),()),((),(MECH,)),((DORM,),())):
            with self.subTest(own=own,enemy=enemy):
                g = self.game(own=own,enemy=enemy);rng = g.snapshot()['rng_state']
                self.play(g,ROOT)
                self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,9)
                self.assertEqual(g.state.card_discovery_history,[]);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_current_mech_source_from_real_hand_tribe_grant_satisfies_condition(self):
        g = self.game(own=(),hand=(TRIBE,ROOT))
        self.play(g,TRIBE,self.entity(g,ROOT).id);source = self.play(g,ROOT)
        self.assertTrue(has_any_tribe(g.registry,g.state.entities[source],('mech',)))
        self.assertEqual(len(self.menu(g)),3)

    def test_real_paid_menu_genuine_discovery_restore_replay_and_selection_rng(self):
        g = self.game();self.play(g,ROOT);offered = self.menu(g)
        self.assertEqual(len(set(offered)),3);self.assertEqual(g.state.players[1].mana,9)
        self.assertEqual(g.state.card_discovery_history,[])
        enemy_view = json.dumps(g.for_player(2).observe())
        for cid in offered:self.assertNotIn(cid,enemy_view)
        restored = self.portable(g);saved = g.snapshot();rng = saved['rng_state']
        with self.assertRaises(IllegalAction):self.choose(g,'not-an-offered-tech')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):self.pick_card(current,offered[0])
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(self.entity(g,offered[0]).card_id,offered[0])
        self.assertEqual(sum(e.kind == 'card_discovered' for e in g.events),1)
        self.portable(g)

    def test_visible_armor_and_legendary_threat_produce_real_usable_counters(self):
        g = self.game(enemy=(LEGEND,),enemy_armor=40);self.play(g,ROOT)
        self.assertIn('DRG_069',self.menu(g));self.assertIn('AV_138',self.menu(g))
        self.pick_card(g,'DRG_069');self.play(g,'DRG_069')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual(g.state.players[1].mana,4)

    def test_current_quotes_affect_payable_slots_without_consuming_discount(self):
        g = self.game(hand=(DISCOUNT,ROOT));self.play(g,DISCOUNT)
        before = g.snapshot()
        rows = scores(g.registry,g.state,1);row = next(r for r in rows if r.card_id == 'AV_135')
        self.assertEqual((row.quoted_cost,row.payable_now),(0,True));self.assertEqual(g.snapshot(),before)
        self.play(g,ROOT);self.assertIn('AV_135',self.menu(g));self.pick_card(g,'AV_135')
        self.play(g,'AV_135');self.assertEqual(g.state.players[1].mana,9)

    def test_hidden_opponent_cards_do_not_change_recommendations(self):
        a = self.game(enemy=(LEGEND,),enemy_hand=('GAME_005',),enemy_deck=('GAME_005',)*6)
        b = self.game(enemy=(LEGEND,),enemy_hand=('AV_138','DRG_069'),enemy_deck=('TSC_926',)*6)
        self.play(a,ROOT);self.play(b,ROOT)
        self.assertEqual(self.menu(a),self.menu(b))
        self.assertEqual(len(self.menu(a)),3)

    def test_real_scout_receives_one_extra_copy_from_genuine_discovery(self):
        g = self.game(own=(MECH,SCOUT));self.play(g,ROOT);cid = self.menu(g)[0]
        self.pick_card(g,cid)
        copies = [g.state.entities[i] for i in g.state.players[1].hand if g.state.entities[i].card_id == cid]
        self.assertEqual(len(copies),2);self.assertNotEqual(copies[0].id,copies[1].id)
        self.assertEqual(len(g.state.card_discovery_history),1)

    def test_indirect_battlecry_rechecks_mech_after_original_has_completed(self):
        g = self.game(hand=(ROOT,REPEAT,KILL));source = self.play(g,ROOT);self.choose(g,'tech-1')
        self.play(g,KILL,self.entity(g,MECH,zone='board').id)
        self.play(g,REPEAT,source)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertEqual(g.state.players[1].mana,9)

    def test_original_source_return_does_not_replace_already_accepted_battlecry(self):
        g = self.game(mode='return_source');source = self.play(g,ROOT)
        self.assertEqual(g.state.entities[source].zone,Zone.HAND)
        self.assertEqual(len(self.menu(g)),3);self.choose(g,'tech-1')
        self.assertEqual(len(g.state.card_discovery_history),1)

    def test_full_hand_burn_and_late_failure_preserve_shared_transaction_boundaries(self):
        g = self.game(mode='fill',hand=(ROOT,)+('GAME_005',)*9)
        self.play(g,ROOT);cid = self.menu(g)[0];self.choose(g,'tech-1')
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(any(e.card_id == cid and e.zone == Zone.GRAVEYARD for e in g.state.entities.values()))
        g = self.game(mode='fail');self.play(g,ROOT);before = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'tech-1')
        self.assertEqual(g.snapshot(),before)

    def test_nested_completion_wait_restores_and_bad_continuation_rolls_back(self):
        g = self.game(mode='wait');self.play(g,ROOT);self.choose(g,'tech-1')
        self.assertEqual(len(g.state.card_discovery_history),1)
        restored = self.portable(g);saved = g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for current in (g,restored):self.choose(current,'go')
        self.assertEqual(g.snapshot(),restored.snapshot())
