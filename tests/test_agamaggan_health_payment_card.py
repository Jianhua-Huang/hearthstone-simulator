"""Real bounded next-card payment, actual debtor and original payment boundaries."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards.agamaggan_health_payment_card import CARD, LIMIT, load_batch, register_agamaggan_health_payment_card
from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.costs import payment_error, quote_cost
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChangeControl, ChoiceOption, GrantKeyword,
    InvokeBehavior, RandomDamage, RequestChoice, Summon)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.health_loss import SetHeroHealth
from hs_sim.engine.model import CostModifier, CostSpec, PaymentType
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.serialization import canonical_hash

P = 'agamaggan.test.'
FILL = 'CS2_182'
SPELL, ZERO, TEN, ELEVEN, WEAPON, LOCATION, HERO, CHOICE, SETUP, DISCOUNT, SUMMON, GIVE, WATCH, KILLER, WEAKEN, SELF_WEAKEN = (
    P+x for x in ('spell','zero','ten','eleven','weapon','location','hero','choice','setup','discount','summon','give','watch','killer','weaken','self_weaken'))


@lru_cache(maxsize=None)
def registry(role, mode='normal'):
    assert role in ('writer','reader')
    r = build_registry()
    register_agamaggan_health_payment_card(r)
    def fail(c):
        raise ResolutionError('Agamaggan deliberate rollback')
    r.register_behavior(P+'fail', fail)
    r.register_behavior(P+'none', lambda c: ())
    r.register_behavior(P+'choice', lambda c: (RequestChoice(c.player_id, (
        ChoiceOption('ok','Continue',()),
        ChoiceOption('bad','Fail',(RandomDamage((c.state.players[c.player_id].hero_id,),1,c.source_id),
            InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),))
    r.register_behavior(SETUP, lambda c: (
        GrantKeyword(c.state.players[3-c.player_id].hero_id,Keyword.IMMUNE,c.source_id),
        GrantKeyword(c.state.players[3-c.player_id].hero_id,Keyword.DIVINE_SHIELD,c.source_id)))
    r.register_behavior(DISCOUNT, lambda c: (AddCostModifier(c.player_id,
        CostSpec(delta=-3,card_ids=(ELEVEN,)),source_id=c.source_id),))
    r.register_behavior(SUMMON, lambda c: (Summon(c.player_id,CARD),))
    r.register_behavior(WEAKEN, lambda c: (SetHeroHealth(c.state.players[3-c.player_id].hero_id,6,c.source_id),))
    r.register_behavior(SELF_WEAKEN, lambda c: (SetHeroHealth(c.state.players[c.player_id].hero_id,1,c.source_id),))
    r.register_behavior(GIVE, lambda c: (ChangeControl(next(i for i in c.state.players[3-c.player_id].board
        if c.state.entities[i].card_id==CARD),c.player_id),))
    for cid,cost,body in ((SPELL,3,P+'none'),(ZERO,0,P+'none'),(TEN,10,P+'none'),
            (ELEVEN,11,P+'none'),(CHOICE,4,P+'choice'),(SETUP,0,SETUP),(DISCOUNT,0,DISCOUNT),
            (SUMMON,0,SUMMON),(GIVE,0,GIVE),(WEAKEN,0,WEAKEN),(SELF_WEAKEN,0,SELF_WEAKEN)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=body))
    r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,cost=2,attack=1,durability=2))
    r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=2,durability=2,on_use=P+'none'))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,cost=7,health=30,
        hero_card=True,hero_armor=3,initial_hero_power='HERO_08bp',keep_hero_class=True,battlecry=P+'none'))
    r.register_card(CardDefinition(KILLER,KILLER,CardType.MINION,attack=9,health=40))
    if mode in ('wait','fail'):
        r.register_behavior(WATCH, lambda c: (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            if mode=='fail' else (RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(
                    RandomDamage((c.state.players[c.player_id].hero_id,),1,c.source_id),
                    InvokeBehavior(P+'fail',c.source_id,c.player_id)))),c.source_id),))
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=8,
            triggers=(TriggerSpec('opponent_health_spent',WATCH),)))
    r.validate()
    r.freeze()
    return r


class AgamagganPaymentTests(unittest.TestCase):
    def game(self, hand=(CARD,SPELL), *, mode='normal', mana=10, enemy_armor=0,
             enemy=(), enemy_hand=(), board=()):
        if mode in ('wait','fail'):
            board = (WATCH,*board)
        g = Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(FILL,)*30,mana=mana,max_mana=mana,mana_cap=mana,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,armor=enemy_armor,
                deck=(FILL,)*30,mana=mana,max_mana=mana,mana_cap=mana,hero_power_card_id='HERO_08bp')),seed=253489),registry('writer',mode))
        return g
    def entity(self,g,cid,pid=None,zone='hand'):
        pid = g.state.active_player if pid is None else pid
        return next(g.state.entities[i] for i in getattr(g.state.players[pid],zone) if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,pid=None):
        pid = g.state.active_player if pid is None else pid
        eid = self.entity(g,cid,pid).id
        g.apply(PlayCard(pid,eid))
        return eid
    def quote(self,g,cid,pid=None):
        return quote_cost(g.state,g.registry,self.entity(g,cid,pid))
    def hp(self,g,pid):
        return g.state.entities[g.state.players[pid].hero_id].health
    def mods(self,g,pid=1):
        return [m for m in g.state.players[pid].cost_modifiers if m.spec.payment==PaymentType.OPPONENT_HEALTH]
    def portable(self,g,mode='normal'):
        s = g.snapshot()
        self.assertEqual(Game.from_snapshot(s,registry('reader',mode)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),s)
    def choose(self,g,key='ok'):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id,pending.id,(key,)))

    def test_a00_complete_source_faces_and_assembled_definition_match(self):
        from hs_sim.cards import build_registry as complete
        r = registry('writer')
        self.assertEqual(asdict(r.card(CARD)),asdict(complete().card(CARD)))
        self.assertEqual(len(load_batch()['evidence_only']),2)
        self.assertEqual(r.card(CARD).metadata.tribes,('beast',))
        self.assertEqual(r.card(CARD).metadata.classes,('warlock',))
    def test_a01_opponent_account_requires_a_finite_bounded_original_source(self):
        spec = CostSpec(payment=PaymentType.OPPONENT_HEALTH)
        good = dict(id=1,spec=spec,source_id=2,uses_remaining=1,maximum_cost=10)
        CostModifier(**good)
        for key,value in (('source_id',None),('uses_remaining',None),('maximum_cost',None),
                ('maximum_cost',True),('maximum_cost',-1)):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                CostModifier(**(good|{key:value}))
        with self.assertRaises(ValueError):
            CostModifier(**(good|{'spec':CostSpec(delta=-1,payment=PaymentType.OPPONENT_HEALTH)}))
        s = self.game().snapshot()
        s['schema_version'] = 427
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(s,registry('reader'))
    def test_b00_actual_battlecry_installs_once_after_its_own_mana_payment(self):
        g = self.game()
        eid = self.play(g)
        self.assertEqual((g.state.players[1].mana,self.hp(g,1),self.hp(g,2)),(0,30,30))
        self.assertEqual([(m.source_id,m.maximum_cost,m.uses_remaining) for m in self.mods(g)],[(eid,LIMIT,1)])
        self.portable(g)
    def test_b01_card_plays_with_no_mana_and_spends_opponent_health_only(self):
        g = self.game(enemy_armor=50)
        self.play(g)
        self.play(g,SPELL)
        self.assertEqual((g.state.players[1].mana,self.hp(g,1),self.hp(g,2)),(0,30,27))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,50)
        self.assertFalse(self.mods(g))
        row = g.state.hero_health_change_history[-1]
        self.assertEqual((row.player_id,row.active_player,row.event_kind),(2,1,'opponent_health_spent'))
        self.portable(g)
    def test_b02_zero_cost_still_consumes_next_card_account(self):
        g = self.game((CARD,ZERO,SPELL),mana=30)
        self.play(g)
        self.play(g,ZERO)
        self.assertFalse(self.mods(g))
        self.assertEqual(self.hp(g,2),30)
        self.play(g,SPELL)
        self.assertEqual((g.state.players[1].mana,self.hp(g,2)),(17,30))
    def test_b03_above_limit_is_illegal_even_with_enough_mana_and_preserves_use(self):
        g = self.game((CARD,ELEVEN,SPELL),mana=30)
        self.play(g)
        q = self.quote(g,ELEVEN)
        self.assertEqual((q.amount,q.payment),(11,PaymentType.OPPONENT_HEALTH))
        self.assertIn('limit',payment_error(g.state,q))
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.play(g,ELEVEN)
        self.assertEqual(g.snapshot(),before)
        self.play(g,SPELL)
        self.assertEqual(self.hp(g,2),27)
    def test_b04_final_current_cost_not_printed_price_determines_limit_and_debit(self):
        g = self.game((DISCOUNT,CARD,ELEVEN))
        self.play(g,DISCOUNT)
        self.play(g)
        self.assertEqual(self.quote(g,ELEVEN).amount,8)
        self.play(g,ELEVEN)
        self.assertEqual(self.hp(g,2),22)
        self.portable(g)
    def test_b05_ten_is_legal_without_clamping_other_prices(self):
        g = self.game((CARD,TEN))
        self.play(g)
        self.play(g,TEN)
        self.assertEqual(self.hp(g,2),20)
        self.portable(g)
    def test_b06_armor_immunity_and_shield_do_not_block_health_payment(self):
        g = self.game((SETUP,CARD,SPELL),enemy_armor=50)
        self.play(g,SETUP)
        self.play(g)
        cursor = len(g.events)
        self.play(g,SPELL)
        hero = g.state.entities[g.state.players[2].hero_id]
        self.assertEqual((hero.health,hero.armor),(27,50))
        self.assertTrue({Keyword.IMMUNE,Keyword.DIVINE_SHIELD} <= hero.keywords)
        self.assertFalse(any(e.kind in ('damage_dealt','damage_prevented','shield_lost') for e in g.events[cursor:]))
        self.portable(g)
    def test_b07_all_five_played_card_types_share_payment_without_new_executors(self):
        for cid,kind in ((FILL,CardType.MINION),(SPELL,CardType.SPELL),(WEAPON,CardType.WEAPON),
                (LOCATION,CardType.LOCATION),(HERO,CardType.HERO)):
            with self.subTest(kind=kind):
                g = self.game((CARD,cid))
                self.play(g)
                cost = self.quote(g,cid).amount
                self.play(g,cid)
                self.assertEqual(self.hp(g,2),30-cost)
                self.assertFalse(self.mods(g))
    def test_b08_hero_power_remains_mana_and_does_not_consume_account(self):
        g = self.game()
        self.play(g)
        power = g.state.entities[g.state.players[1].hero_power_id]
        q = quote_cost(g.state,g.registry,power)
        self.assertEqual(q.payment,PaymentType.MANA)
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            g.apply(UseHeroPower(1,power.id))
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(len(self.mods(g)),1)
    def test_b09_payment_can_kill_opponent_below_cost_despite_armor_and_immunity(self):
        g = self.game((WEAKEN,SETUP,CARD,TEN),enemy_armor=50)
        self.play(g,WEAKEN)
        self.play(g,SETUP)
        self.play(g)
        self.play(g,TEN)
        self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual(self.hp(g,2),-4)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,50)
        self.assertFalse(self.mods(g))
        self.portable(g)
    def test_b10_players_own_low_health_does_not_restrict_opponent_payment(self):
        g = self.game((SELF_WEAKEN,CARD,TEN))
        self.play(g,SELF_WEAKEN)
        self.play(g)
        self.play(g,TEN)
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(1,20))
        self.assertEqual(g.state.status,'playing')
    def test_c00_ordinary_summon_does_not_install_battlecry_account(self):
        g = self.game((SUMMON,SPELL))
        self.play(g,SUMMON)
        self.assertFalse(self.mods(g))
        self.play(g,SPELL)
        self.assertEqual(self.hp(g,2),30)
    def test_c01_source_death_and_later_owner_turn_do_not_remove_account(self):
        g = self.game(enemy=(KILLER,))
        eid = self.play(g)
        g.apply(EndTurn(1))
        g.apply(Attack(2,self.entity(g,KILLER,2,'board').id,eid))
        g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.play(g,SPELL)
        self.assertEqual(self.hp(g,2),27)
        self.portable(g)
    def test_c02_source_control_change_does_not_change_original_modifier_owner(self):
        g = self.game(enemy_hand=(GIVE,))
        self.play(g)
        g.apply(EndTurn(1))
        self.play(g,GIVE)
        g.apply(EndTurn(2))
        self.assertEqual(self.entity(g,CARD,2,'board').controller,2)
        self.play(g,SPELL)
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(30,27))
        self.portable(g)
    def test_c03_second_real_battlecry_installs_a_new_source_after_previous_payment(self):
        g = self.game((CARD,CARD,SPELL),mana=30)
        first = self.play(g)
        second = self.play(g)
        self.assertNotEqual(first,second)
        self.assertEqual(self.hp(g,2),20)
        self.assertEqual([m.source_id for m in self.mods(g)],[second])
        self.play(g,SPELL)
        self.assertEqual(self.hp(g,2),17)
        self.portable(g)
    def test_c04_second_player_debits_first_players_hero(self):
        g = self.game((),enemy_hand=(CARD,SPELL))
        g.apply(EndTurn(1))
        self.play(g)
        self.play(g,SPELL)
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(27,30))
        self.assertEqual(g.state.hero_health_change_history[-1].player_id,1)
        self.portable(g)
    def test_d00_spent_event_wait_restores_consumed_source_without_repaying(self):
        g = self.game(mode='wait')
        self.play(g)
        self.play(g,SPELL)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(self.hp(g,2),27)
        self.assertFalse(self.mods(g))
        self.portable(g,'wait')
        restored = Game.from_snapshot(g.snapshot(),registry('reader','wait'))
        for x in (g,restored):
            self.choose(x)
        self.assertEqual(g.snapshot(),restored.snapshot())
        self.assertEqual(self.hp(g,2),27)
    def test_d01_card_body_wait_restores_original_payment_and_late_failure_rolls_back(self):
        g = self.game((CARD,CHOICE))
        self.play(g)
        self.play(g,CHOICE)
        self.assertEqual(self.hp(g,2),26)
        self.portable(g)
        waiting = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g,'bad')
        self.assertEqual(g.snapshot(),waiting)
        self.choose(g)
        self.assertEqual(self.hp(g,2),26)
        self.portable(g)
    def test_d02_immediate_failure_rolls_back_health_quote_use_history_and_mana(self):
        g = self.game(mode='fail')
        self.play(g)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(g,SPELL)
        self.assertEqual(g.snapshot(),before)
    def test_e00_public_quote_names_opponent_account_without_private_receipts(self):
        g = self.game()
        self.play(g)
        before = g.snapshot()
        for _ in range(3):
            q = self.quote(g,SPELL)
            self.assertEqual(q.payment,PaymentType.OPPONENT_HEALTH)
            view = g.observe(1)
            row = next(x for x in view['players'][0]['hand'] if x['card_id']==SPELL)
            self.assertEqual(row['cost'],{'amount':3,'payment':'opponent_health'})
            self.assertEqual(view['version'],'player-view-v98')
            for private in ('CostQuoteFact','CostUseReceipt','hero_health_transition','maximum_cost'):
                self.assertNotIn(private,json.dumps(view))
        self.assertEqual(g.snapshot(),before)
        self.assertNotIn(SPELL,json.dumps(g.observe(2)['players'][0]['hand']))
    def test_e01_rehashed_spent_event_cannot_claim_the_debited_hero_is_the_actor(self):
        g = self.game()
        self.play(g)
        self.play(g,SPELL)
        bad = deepcopy(g.snapshot())
        event = next(e for e in bad['events'] if e['kind']=='opponent_health_spent')
        event['player_id'] = 2
        bad['events_hash'] = canonical_hash(bad['events'])
        bad['state_hash'] = canonical_hash({k:v for k,v in bad.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(bad,registry('reader'))
