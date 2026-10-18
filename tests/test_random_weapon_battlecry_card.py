"""Real two-player weapon generation, original equipment reward and native Rewind."""
from dataclasses import replace
from functools import lru_cache
import json,random,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import load_batch as candidate_batch
from hs_sim.cards.random_weapon_battlecry_card import CARD,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,IllegalAction,Keyword,PlayerSetup,PlayCard,Rarity,Scenario,SelectChoice,Zone)
from hs_sim.engine.effects import ChoiceOption,EquipWeapon,InvokeBehavior,RequestChoice,TransferWeapon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose,EquippedWeaponReference,LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.random_weapon_equipment import QUERY
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

P='announcer.test.';FILL,VANILLA,WATCH,UNKNOWN=(P+x for x in ('fill','vanilla','watch','unknown'))
TINY='JAIL_458';INFINITY='END_012';BULWARK='CORE_BT_781';MEMBERS=(BULWARK,INFINITY,TINY)
CTX=GenerationContext('announcer-explicit-experiment','experimental');POOL='constructed.cards'
ALL_WEAPONS=tuple(x['record']['id']for x in candidate_batch()['cards']if x['record']['type']=='WEAPON')


@lru_cache(maxsize=None)
def registry(mode,members,role):
    assert role in ('writer','reader')
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=30,metadata=meta))
    def current(c):return EquippedWeaponReference.capture(c.state.entities[c.state.players[1].weapon_id])
    def fail(c):raise ResolutionError('Announcer deliberate equipment continuation failure')
    r.register_behavior(P+'fail',fail)
    def menu(c):return (RequestChoice(1,(
        ChoiceOption('ok','Continue'),ChoiceOption('swap','Replace original',(EquipWeapon(1,VANILLA),)),
        ChoiceOption('transfer','Transfer original',(TransferWeapon(current(c),2,c.source_id),)),
        ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
    r.register_behavior(P+'menu',menu)
    r.register_card(CardDefinition(VANILLA,VANILLA,CardType.WEAPON,cost=1,attack=1,durability=4,
        deathrattle=P+'menu'if mode=='old'else None,metadata=meta))
    if mode in ('first','second','fail'):
        def eligible(c):return c.event.player_id==(2 if mode=='second'else 1)
        r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec('weapon_equipped',P+'fail'if mode=='fail'else P+'menu',condition_id=P+'eligible'),)))
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.WEAPON,4,replace(meta,collectible=True)))
    r.register_pool(PoolDefinition(POOL,'announcer-explicit-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(c,3 if c==BULWARK else 1)for c in members),complete=True))
    r.validate();r.freeze();return r


class RandomWeaponBattlecryTests(unittest.TestCase):
    def game(self,members=MEMBERS,mode=None,existing=False,pid=1):
        self.config=(mode,members);self.pid=pid
        players=tuple(PlayerSetup('HERO_08',hand=(CARD,)if p==pid else(),deck=(FILL,)*12,
            board=(WATCH,)if p==1 and mode in ('first','second','fail')else(),
            weapon_card_id=VANILLA if existing else None,mana=50,max_mana=50,mana_cap=50)for p in (1,2))
        g=Game.from_scenario(Scenario(players,seed=222034,generation_context=CTX),registry(mode,members,'writer'))
        if pid==2:g.apply(EndTurn(1))
        return g
    def play(self,g):
        eid=next(i for i in g.state.players[self.pid].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(self.pid,eid,position=0));return eid
    def weapon(self,g,pid=1):
        wid=g.state.players[pid].weapon_id;return g.state.entities[wid]if wid is not None else None
    def choose(self,g,key):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry(*self.config,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()))
        other=Game.from_snapshot(s,r);self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
        for pid in (1,2):
            public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
            for key in ('resolution_frame','source_allocation','rng_state','rewind_session','behavior_id'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def test_a00_complete_source_actual_rewind_and_independent_full_weapon_inventory(self):
        d=load_batch();row,=d['cards'];r=registry(None,MEMBERS,'writer');card=r.card(CARD)
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((card.cost,card.attack,card.health),(4,3,3));self.assertIn(Keyword.REWIND,card.keywords)
        self.assertEqual(card.rewind.retries,1);self.assertEqual(len(d['official_observations']),2)
        self.assertEqual(len(ALL_WEAPONS),36);self.assertTrue(all(c in r.cards for c in ALL_WEAPONS))
        self.assertFalse(d['policy']['formal_pool_complete']);self.assertFalse(d['policy']['cn_calibrated'])
    def test_a01_paid_native_battlecry_equips_both_with_only_own_bonus_and_one_payment(self):
        g=self.game(members=(TINY,));source=self.play(g)
        self.assertEqual((self.weapon(g).card_id,self.weapon(g).attack,self.weapon(g).durability),(TINY,3,4))
        self.assertEqual((self.weapon(g,2).card_id,self.weapon(g,2).attack,self.weapon(g,2).durability),(TINY,2,3))
        self.assertNotEqual(self.weapon(g).id,self.weapon(g,2).id)
        self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.choose(g,'keep')
        self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.players[1].board,[source]);self.portable(g)
    def test_a02_weighted_canonical_pool_independent_draws_and_exact_rng(self):
        g=self.game();rows=resolve_candidates(g.registry,CTX,POOL,QUERY,source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        self.assertEqual([(m.card_id,m.weight)for m in rows],[(BULWARK,3),(INFINITY,1),(TINY,1)])
        rng=random.Random();rng.setstate(g._rng.getstate());expected=[]
        for _ in (1,2):
            ticket=rng.randrange(5);expected.append(BULWARK if ticket<3 else INFINITY if ticket==3 else TINY)
        self.play(g);self.assertEqual([self.weapon(g,p).card_id for p in (1,2)],expected)
        self.assertEqual(g._rng.getstate(),rng.getstate());self.choose(g,'keep');self.portable(g)
    def test_a03_complete_36_standard_candidate_weapons_not_executable_subset(self):
        g=self.game(members=ALL_WEAPONS)
        rows=resolve_candidates(g.registry,CTX,POOL,QUERY,source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        self.assertEqual({m.card_id for m in rows},set(ALL_WEAPONS));self.play(g);self.choose(g,'keep');self.portable(g)
    def test_a04_generated_infinite_weapon_has_printed_attack_and_restriction_without_battlecry(self):
        g=self.game(members=(INFINITY,));self.play(g);self.choose(g,'keep')
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(5,3));self.assertEqual(self.weapon(g,2).attack,4)
        self.assertEqual(len(g.state.battlecry_history),1)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.portable(g)
    def test_a05_original_both_weapons_replaced_with_ordinary_death_history(self):
        g=self.game(members=(TINY,),existing=True);old=[self.weapon(g,p).id for p in (1,2)];self.play(g)
        self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in old))
        self.assertEqual(len(g.state.death_history),2);self.choose(g,'keep');self.portable(g)
    def test_b00_first_equipment_wait_before_other_delivery_restores_and_resumes(self):
        g=self.game(members=(TINY,),mode='first');self.play(g)
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,3));self.assertIsNone(self.weapon(g,2))
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for game in (g,other):self.choose(game,'ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.weapon(g).attack,3)
        self.choose(g,'keep');self.portable(g)
    def test_b01_second_equipment_wait_keeps_original_unbuffed_then_commits_bonus(self):
        g=self.game(members=(TINY,),mode='second');self.play(g);wid=self.weapon(g).id
        self.assertEqual(self.weapon(g).attack,2);self.assertIsNotNone(self.weapon(g,2));self.portable(g)
        self.choose(g,'ok');self.assertEqual((self.weapon(g).id,self.weapon(g).attack),(wid,3))
        self.choose(g,'keep');self.portable(g)
    def test_b02_replacing_own_weapon_in_first_wait_does_not_buff_later_equipment(self):
        g=self.game(members=(TINY,),mode='first');self.play(g);old=self.weapon(g).id;self.choose(g,'swap')
        self.assertNotEqual(self.weapon(g).id,old);self.assertEqual((self.weapon(g).card_id,self.weapon(g).attack,self.weapon(g).durability),(VANILLA,1,4))
        self.assertEqual(self.weapon(g,2).card_id,TINY);self.choose(g,'keep');self.portable(g)
    def test_b03_replacing_own_weapon_after_other_equipment_does_not_buff_new_slot(self):
        g=self.game(members=(TINY,),mode='second');self.play(g);self.choose(g,'swap')
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(1,4));self.choose(g,'keep');self.portable(g)
    def test_b04_transferred_original_is_not_buffed_and_other_installation_still_finishes(self):
        g=self.game(members=(TINY,),mode='first');self.play(g);old=self.weapon(g).id;self.choose(g,'transfer')
        self.assertIsNone(self.weapon(g));self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD)
        self.assertEqual((self.weapon(g,2).attack,self.weapon(g,2).durability),(2,3));self.choose(g,'keep');self.portable(g)
    def test_b05_replacement_deathrattles_pause_in_order_before_original_weapon_bonus(self):
        g=self.game(members=(TINY,),mode='old',existing=True);old_enemy=self.weapon(g,2).id;self.play(g)
        self.assertEqual(self.weapon(g,2).id,old_enemy);self.assertEqual(self.weapon(g).attack,2);self.portable(g)
        self.choose(g,'ok');self.assertNotEqual(self.weapon(g,2).id,old_enemy)
        self.assertEqual(self.weapon(g).attack,2);self.portable(g);self.choose(g,'ok')
        self.assertEqual(self.weapon(g).attack,3);self.choose(g,'keep');self.portable(g)
    def test_c00_rewind_wait_independent_restore_and_keep_matches(self):
        g=self.game(existing=True);self.play(g);other=self.portable(g)
        for game in (g,other):self.choose(game,'keep')
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)
    def test_c01_retry_restores_original_weapons_and_keeps_only_final_replacements(self):
        g=self.game(members=(TINY,),existing=True);old=[self.weapon(g,p).id for p in (1,2)];source=self.play(g)
        self.portable(g);self.choose(g,'retry');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.death_history),2);self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in old))
        self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.players[1].board,[source])
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,4));self.portable(g)
    def test_c02_retry_runs_real_random_draws_again_without_repaying(self):
        g=self.game();rng=random.Random();rng.setstate(g._rng.getstate())
        for _ in range(4):rng.randrange(5)
        self.play(g);self.choose(g,'retry');self.assertEqual(g._rng.getstate(),rng.getstate())
        self.assertEqual(g.state.players[1].mana,46);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
    def test_c03_weapon_replacement_and_retry_do_not_refund_prior_hero_attack(self):
        g=self.game(members=(TINY,),existing=True);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
        self.play(g);self.choose(g,'retry');hero=g.state.entities[g.state.players[1].hero_id]
        self.assertEqual(hero.attacks_this_turn,1)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,hero.id,g.state.players[2].hero_id))
        self.portable(g)
    def test_d00_unknown_eligible_weapon_rolls_back_whole_paid_play_before_rng(self):
        g=self.game(members=(TINY,UNKNOWN),existing=True);saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown equipment before RNG'))as calls:
            with self.assertRaises(ResolutionError):self.play(g)
            calls.assert_not_called()
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_d01_failed_equipment_observer_rolls_back_payment_rng_replacements_and_new_entities(self):
        g=self.game(mode='fail',existing=True);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved);self.portable(g)
    def test_d02_empty_pool_leaves_existing_weapons_and_consumes_no_rng(self):
        g=self.game(members=(),existing=True);old=[self.weapon(g,p).id for p in (1,2)];rng=g._rng.getstate();self.play(g)
        self.assertEqual([self.weapon(g,p).id for p in (1,2)],old);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(self.weapon(g).attack,1);self.choose(g,'keep');self.portable(g)
    def test_d03_second_player_is_caster_and_receives_the_only_bonus(self):
        g=self.game(members=(TINY,),pid=2);self.play(g);self.choose(g,'keep')
        self.assertEqual((self.weapon(g,2).attack,self.weapon(g,2).durability),(3,4))
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,3));self.assertEqual(g.state.players[2].mana,46);self.portable(g)
