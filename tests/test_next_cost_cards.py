"""Real original-neighbor discounts, conditional health and tribal finite uses."""
from copy import deepcopy
from dataclasses import replace
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.next_cost_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,
    PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.costs import capture_cost_input,capture_quote_fact,capture_generated_quote_fact,quote_cost
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,Heal,InvokeBehavior,
    RequestChoice,Summon)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import PaymentType
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.targets import canonical_digest


def registry(mode=None):
    r=build_registry();neutral=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    for name,tribes in (('plain',()),('demon',('demon',)),('beast',('beast',)),('all',('all',)),('unknown',None)):
        r.register_card(CardDefinition('k10.'+name,name,CardType.MINION,cost=3,attack=2,health=6,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes)))
    r.register_card(CardDefinition('k10.weapon','Weapon',CardType.WEAPON,cost=3,attack=1,durability=2,metadata=neutral))
    r.register_behavior('k10.noop',lambda c:())
    r.register_card(CardDefinition('k10.location','Location',CardType.LOCATION,cost=3,durability=2,on_use='k10.noop',metadata=neutral))
    def hero(c,p=1):return c.state.players[p].hero_id
    scripts={
        'wound':lambda c:(Damage(hero(c),4,c.source_id),),
        'heal':lambda c:(Heal(hero(c),1,c.source_id),),
        'enemy_heal':lambda c:(Heal(hero(c,2),1,c.source_id),),
        'summon_demon':lambda c:(Summon(1,'k10.demon'),),
        'mana_override':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.MANA,card_ids=('CORE_ETC_523',)),source_id=c.source_id),),
    }
    for name,body in scripts.items():
        r.register_behavior('k10.'+name,body)
        r.register_card(CardDefinition('k10.'+name,name,CardType.SPELL,on_play='k10.'+name,metadata=neutral))
    if mode is not None:
        r.register_behavior('k10.fail',lambda c:(AddToHand(1,'missing.k10.after.payment'),))
        def watch(c):
            source=c.state.entities[c.event.source_id]
            if source.card_id not in ('DINO_137','CORE_ETC_523'):return ()
            play=next(p for p in reversed(c.state.play_history)if p.source_id==source.id)
            if source.card_id=='DINO_137' and mode=='shift':
                left=play.hand_neighbors[0]
                return (MoveCard(CardReference(left.entity_id,1,Zone.HAND,left.card_id,left.zone_epoch),1,Zone.DECK),
                    AddToHand(1,'k10.plain'))
            return (RequestChoice(1,(ChoiceOption('keep','Continue'),ChoiceOption('bad','Rollback',(
                InvokeBehavior('k10.fail',c.source_id,1),))),c.source_id),)
        r.register_behavior('k10.watch',watch)
        r.register_card(CardDefinition('k10.watch','Observer',CardType.MINION,health=6,
            triggers=(TriggerSpec('card_committed','k10.watch'),),metadata=neutral))
    return r


class NextCostCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),board=(),enemy=(),mode=None,mana=30):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=('k10.plain',)*4,
            mana=mana,max_mana=mana,mana_cap=30),PlayerSetup('test.hero',board=enemy)),seed=101),registry(mode) if mode else self.r)
    def eid(self,g,cid):return next(e for e in g.state.players[1].hand if g.state.entities[e].card_id==cid)
    def quote(self,g,cid):return quote_cost(g.state,g.registry,g.state.entities[self.eid(g,cid)])
    def play(self,g,cid,target=None):
        e=self.eid(g,cid);g.apply(PlayCard(1,e,target_id=target));return e
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other
    def choose(self,g,option='keep'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

    def test_five_complete_pinned_roots_and_missing_zero_tag_are_explicit(self):
        data=load_batch();self.assertEqual(len(data['cards']),5)
        for row in data['cards']:
            self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
            self.assertEqual(self.r.card(row['record']['id']).cost,row['recipe']['cost'])
        prep=next(x for x in data['cards']if x['record']['id']=='CORE_EX1_145')
        self.assertIsNone(prep['record']['cost']);self.assertEqual(prep['recipe']['cost'],0)

    def test_original_neighbors_include_spell_weapon_location_and_preserve_order(self):
        for left,right in (('k10.plain','k10.heal'),('k10.weapon','k10.location')):
            g=self.game((left,'DINO_137',right));original=list(g.state.players[1].hand)
            self.play(g,'DINO_137')
            self.assertEqual([x.entity_id for x in g.state.play_history[0].hand_neighbors],[original[0],original[2]])
            self.assertEqual(self.quote(g,left).amount,self.r.card(left).cost-1 if self.r.card(left).cost else 0)
            self.assertEqual(self.quote(g,right).amount,self.r.card(right).cost-1 if self.r.card(right).cost else 0)
            self.portable(g)

    def test_first_last_and_only_hand_slot_do_not_wrap(self):
        for hand in (('DINO_137','k10.plain'),('k10.plain','DINO_137'),('DINO_137',)):
            g=self.game(hand);self.play(g,'DINO_137')
            self.assertEqual(len(g.state.play_history[0].hand_neighbors),len(hand)-1)
            if len(hand)==2:self.assertEqual(self.quote(g,'k10.plain').amount,2)
            self.portable(g)

    def test_pre_battlecry_hand_shift_does_not_discount_replacement(self):
        g=self.game(('k10.weapon','DINO_137','k10.beast'),board=('k10.watch',),mode='shift')
        left=g.state.players[1].hand[0];self.play(g,'DINO_137')
        self.assertIn(left,g.state.players[1].deck);self.assertEqual(self.quote(g,'k10.beast').amount,2)
        self.assertEqual(self.quote(g,'k10.plain').amount,3);self.portable(g)

    def test_paid_neighbor_wait_restore_and_bad_choice_keep_one_payment(self):
        g=self.game(('k10.plain','DINO_137','k10.beast'),board=('k10.watch',),mode='wait')
        self.play(g,'DINO_137');self.assertEqual(g.state.players[1].mana,27);self.assertEqual(self.quote(g,'k10.plain').amount,3)
        s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),s);other=self.portable(g)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.quote(g,'k10.plain').amount,2);self.assertEqual(g.state.players[1].mana,27)

    def test_rehashed_deleted_neighbor_is_rejected_even_if_card_cost_is_unchanged(self):
        g=self.game(('k10.plain','DINO_137','k10.beast'));self.play(g,'DINO_137')
        s=g.snapshot();s['state']['play_history'][0]['hand_neighbors'].pop();self.reject(s)

    def test_next_demon_quotes_are_pure_and_other_cards_do_not_consume(self):
        g=self.game(('CORE_BT_416','k10.plain','k10.heal','k10.demon'));self.play(g,'CORE_BT_416')
        s=g.snapshot();self.assertEqual(self.quote(g,'k10.demon').amount,1)
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,'k10.demon').amount,1)
        self.assertEqual(g.snapshot(),s)
        self.play(g,'k10.plain');self.play(g,'k10.heal');self.assertEqual(self.quote(g,'k10.demon').amount,1)
        self.play(g,'k10.demon');self.assertEqual(g.state.play_history[-1].cost,1)
        self.assertEqual(g.state.players[1].cost_modifiers,[]);self.portable(g)

    def test_all_tribes_match_and_multiple_next_sources_stack_independently(self):
        g=self.game(('CORE_BT_416','CORE_BT_416','k10.all'));self.play(g,'CORE_BT_416');self.play(g,'CORE_BT_416')
        self.assertEqual(self.quote(g,'k10.all').amount,0);self.play(g,'k10.all')
        self.assertEqual(g.state.players[1].cost_modifiers,[]);self.portable(g)

    def test_unknown_current_tribes_are_not_silently_skipped(self):
        g=self.game(('CORE_BT_416','k10.unknown'));self.play(g,'CORE_BT_416')
        from hs_sim.engine.registry import UnsupportedDefinitionError
        with self.assertRaises(UnsupportedDefinitionError):self.quote(g,'k10.unknown')

    def test_summoned_demon_does_not_consume_a_paid_hand_discount(self):
        g=self.game(('CORE_BT_416','k10.summon_demon','k10.demon'));self.play(g,'CORE_BT_416');self.play(g,'k10.summon_demon')
        self.assertEqual(self.quote(g,'k10.demon').amount,1);self.assertEqual(len(g.state.players[1].cost_modifiers),1)

    def test_frightened_flunky_damage_and_next_beast_turn_expiry(self):
        g=self.game(('TLC_823','k10.beast'),enemy=('k10.plain',));target=g.state.players[2].board[0]
        self.play(g,'TLC_823',target);self.assertEqual(g.state.entities[target].health,3)
        self.assertEqual(self.quote(g,'k10.beast').amount,1)
        g.apply(EndTurn(1));self.assertEqual(self.quote(g,'k10.beast').amount,3);self.portable(g)

    def test_preparation_reduces_one_actual_hand_spell_and_is_not_spent_by_queries(self):
        g=self.game(('CORE_EX1_145','TLC_823','k10.plain'),enemy=('k10.plain',));self.play(g,'CORE_EX1_145')
        self.assertEqual(self.quote(g,'TLC_823').amount,0);self.play(g,'k10.plain')
        self.assertEqual(self.quote(g,'TLC_823').amount,0);self.play(g,'TLC_823',g.state.players[2].board[0])
        self.assertEqual(g.state.play_history[-1].cost,0);self.portable(g)

    def test_unhealed_and_zero_healing_knight_pay_mana(self):
        g=self.game(('CORE_ETC_523','k10.heal'));self.play(g,'k10.heal')
        self.assertEqual((self.quote(g,'CORE_ETC_523').amount,self.quote(g,'CORE_ETC_523').payment),(3,PaymentType.MANA))
        self.play(g,'CORE_ETC_523');self.assertEqual(g.state.play_history[-1].payment,PaymentType.MANA);self.portable(g)

    def test_actual_hero_healing_changes_payment_account_without_discounting_amount(self):
        g=self.game(('CORE_ETC_523','k10.wound','k10.heal'));self.play(g,'k10.wound');self.play(g,'k10.heal')
        q=self.quote(g,'CORE_ETC_523');self.assertEqual((q.amount,q.payment),(3,PaymentType.HEALTH))
        self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,'CORE_ETC_523').payment,PaymentType.HEALTH)
        self.play(g,'CORE_ETC_523');self.assertEqual(g.state.players[1].mana,30)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);self.portable(g)

    def test_other_hero_healing_and_new_turn_do_not_qualify(self):
        g=self.game(('CORE_ETC_523','k10.enemy_heal'));self.play(g,'k10.enemy_heal')
        self.assertEqual(self.quote(g,'CORE_ETC_523').payment,PaymentType.MANA)
        g=self.game(('CORE_ETC_523','k10.wound','k10.heal'));self.play(g,'k10.wound');self.play(g,'k10.heal')
        g.apply(EndTurn(1));self.assertEqual(self.quote(g,'CORE_ETC_523').payment,PaymentType.MANA)

    def test_local_external_account_override_follows_intrinsic_health_condition(self):
        g=self.game(('CORE_ETC_523','k10.wound','k10.heal','k10.mana_override'))
        for cid in ('k10.wound','k10.heal','k10.mana_override'):self.play(g,cid)
        self.assertEqual(self.quote(g,'CORE_ETC_523').payment,PaymentType.MANA)
        self.play(g,'CORE_ETC_523');self.assertEqual(g.state.players[1].mana,27);self.portable(g)

    def test_health_payment_wait_preserves_original_quote_and_no_second_debit(self):
        g=self.game(('CORE_ETC_523','k10.wound','k10.heal'),board=('k10.watch',),mode='wait')
        self.play(g,'k10.wound');self.play(g,'k10.heal');self.play(g,'CORE_ETC_523')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)

    def test_player_views_hide_original_neighbor_and_healing_quote_proofs(self):
        g=self.game(('k10.plain','DINO_137','k10.beast'));self.play(g,'DINO_137')
        import json
        for p in (1,2):
            s=json.dumps(g.for_player(p).observe())+json.dumps(g.player_events(p))
            for field in ('hand_neighbors','condition_facts','payment_state'):self.assertNotIn('"'+field+'"',s)


if __name__=='__main__':unittest.main()
