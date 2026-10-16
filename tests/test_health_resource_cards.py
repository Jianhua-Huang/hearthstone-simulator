"""Real hand conditions, fresh armor/Kindred followups and Lifesteal spells."""
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.health_resource_cards import load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,TriggerSpec,UseHeroPower)
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (AddCostModifier,AddToHand,ChoiceOption,Damage,
    GainArmor,InvokeBehavior,ModifyCost,ReplaceHeroPower,RequestChoice)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import CostSpec,SpellSchool,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.targets import canonical_digest

FIRE='FIR_923';ADVANCE='TIME_750';FORTIFY='TLC_620';ABLATING='TLC_447';BLOOD='JAIL_441';STRIKE='RLK_024'
ROOTS=(FIRE,ADVANCE,FORTIFY,ABLATING,BLOOD,STRIKE);YETI='CORE_CS2_182'


def registry():
    r=build_registry();meta=replace(r.card(YETI).metadata,collectible=False,tribes=(),deck_identity=None)
    for key,cost,health,extra in (
        ('big',0,12,{}),('huge',0,100,{}),('eight',8,12,{}),('seven',7,12,{}),
        ('five',5,12,{}),('four',4,12,{}),('small',0,2,{}),
        ('reborn',0,2,dict(keywords=(Keyword.REBORN,))),
        ('shield',0,12,dict(keywords=(Keyword.DIVINE_SHIELD,))),
        ('immune',0,12,dict(keywords=(Keyword.IMMUNE,))),
        ('sleep',0,12,dict(dormant_turns=3)),('bonus',0,2,dict(spell_damage=1)),
    ):
        r.register_card(CardDefinition('h41.'+key,key,CardType.MINION,cost=cost,attack=1,health=health,metadata=meta,**extra))
    r.register_behavior('h41.fail',lambda c:(AddToHand(c.player_id,'missing.h41'),))
    def modify(c,amount):
        eid=next(i for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.MINION)
        return (ModifyCost(eid,CostSpec(set_to=amount),c.source_id),)
    bodies=dict(noop=lambda c:(),eight_spell=lambda c:(),fel=lambda c:(),frost=lambda c:(),
        wound=lambda c:(Damage(c.state.players[c.player_id].hero_id,10,c.source_id),),
        mod_once=lambda c:(AddCostModifier(c.player_id,CostSpec(delta=1,card_types=(CardType.MINION,)),uses_remaining=1,source_id=c.source_id),),
        power=lambda c:(GainArmor(c.player_id,1),),power2=lambda c:(),
        auto_fire=lambda c:(CastSpell(c.player_id,FIRE,c.source_id),),
        auto_strike=lambda c:(CastSpell(c.player_id,STRIKE,c.source_id,c.target_id,targeting='explicit'),))
    for amount in(4,5,7,8):bodies['cost'+str(amount)]=lambda c,n=amount:modify(c,n)
    for key,body in bodies.items():
        r.register_behavior('h41.'+key,body)
        if key.startswith('power'):
            r.register_card(CardDefinition('h41.'+key,key,CardType.HERO_POWER,cost=2,on_use='h41.'+key,metadata=meta))
        else:
            r.register_card(CardDefinition('h41.'+key,key,CardType.SPELL,cost=8 if key=='eight_spell'else 0,
                on_play='h41.'+key,spell_school=SpellSchool.FEL if key=='fel'else SpellSchool.FROST if key=='frost'else None,
                requires_target=key=='auto_strike',metadata=meta))
    def wait(c,effects=()):
        return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),ChoiceOption('leave','Leave',()),
            ChoiceOption('bad','Rollback',(InvokeBehavior('h41.fail',c.source_id,c.player_id),))),c.source_id),)
    def damage_wait(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None:return ()
        if source.card_id==ADVANCE:return wait(c,(AddToHand(c.player_id,'h41.eight',c.source_id),))
        if source.card_id==BLOOD:return wait(c)
        return ()
    def armor_wait(c):
        return wait(c,(GainArmor(c.player_id,2),)) if c.event.player_id==c.player_id and c.event.amount==3 else ()
    def death_wait(c):
        target=c.state.entities[c.event.target_id]
        return wait(c)if target.card_id=='h41.reborn'and sum(d.card_id=='h41.reborn'for d in c.state.death_history)==1 else ()
    def late(c):
        source=c.state.entities.get(c.event.source_id)
        return (InvokeBehavior('h41.fail',c.source_id,c.player_id),)if source is not None and source.card_id==FIRE else ()
    def replace_power(c):
        source=c.state.entities.get(c.event.source_id)
        return (ReplaceHeroPower(c.player_id,'h41.power2'),)if source is not None and source.card_id==BLOOD else ()
    for key,event,body in (('wait','damage_dealt',damage_wait),('armor_wait','armor_gained',armor_wait),
        ('death_wait','minion_died',death_wait),('late','damage_dealt',late),('replace_power','damage_dealt',replace_power)):
        r.register_behavior('h41.'+key,body)
        r.register_card(CardDefinition('h41.'+key,key,CardType.MINION,health=12,metadata=meta,
            triggers=(TriggerSpec(event,'h41.'+key),)))
    return r


class HealthResourceCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=('h41.huge',),deck=(YETI,)*6,armor=0,power=False,seed=711,hand_cap=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40,armor=armor,
                hero_power_card_id='h41.power'if power else None,hand_cap=hand_cap),
            PlayerSetup('HERO_08',board=enemy,deck=(YETI,)*6,mana=40,max_mana=40,mana_cap=40)),seed=seed),self.registry)
    def play(self,g,cid,target=None):
        s=g.state;eid=next(i for i in s.players[1].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def rows(self,g,cid):return [health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==cid]
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def prior(self,g,primer='h41.fel'):
        self.play(g,primer);g.apply(EndTurn(1));g.apply(EndTurn(2))
    def use_power(self,g):
        s=g.state;g.apply(UseHeroPower(1,s.players[1].hero_power_id))

    def test_six_complete_faces_lifesteal_school_and_blood_runes(self):
        data=load_batch();self.assertEqual({x['record']['id']for x in data['cards']},set(ROOTS))
        for row in data['cards']:
            raw=row['record'];card=self.registry.card(raw['id'])
            self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.cost,raw['cost'])
            self.assertEqual(Keyword.LIFESTEAL in card.keywords,raw['tags'].get('LIFESTEAL')==1)
        self.assertEqual(self.registry.card(FIRE).spell_school,SpellSchool.FIRE)
        self.assertEqual(self.registry.card(ABLATING).spell_school,SpellSchool.FEL)
        self.assertEqual(self.registry.card(BLOOD).spell_school,SpellSchool.SHADOW)
        for cid in(BLOOD,STRIKE):self.assertEqual(self.registry.card(cid).metadata.runes.blood,1)

    def test_fire_four_or_eight_from_current_held_cards_any_type(self):
        for held,damage in ((None,4),('h41.seven',4),('h41.eight',8),('h41.eight_spell',8)):
            with self.subTest(held=held):
                g=self.game((FIRE,)+(held,)if held else(FIRE,));self.play(g,FIRE)
                self.assertEqual(self.rows(g,FIRE)[0].damage_dealt,damage)
                self.assertEqual(len(g.state.players[1].hand),int(held is not None))

    def test_fire_current_cost_instead_of_printed_cost_after_local_modification(self):
        for held,operation,expected in(('h41.eight','h41.cost7',4),('h41.seven','h41.cost8',8)):
            with self.subTest(held=held):
                g=self.game((operation,FIRE,held));self.play(g,operation);self.play(g,FIRE)
                self.assertEqual(self.rows(g,FIRE)[0].damage_dealt,expected)

    def test_fire_random_enemy_minion_domain_and_spell_bonus(self):
        g=self.game((FIRE,'h41.eight'),board=('h41.bonus',),enemy=('h41.huge','h41.big','h41.sleep'))
        s=g.state;before=g._rng.getstate();self.play(g,FIRE);rows=self.rows(g,FIRE)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].damage_dealt,9)
        self.assertIn(rows[0].target_id,s.players[2].board[:2]);self.assertNotEqual(g._rng.getstate(),before)
        self.assertEqual(rows[0].spell_bonus,1)

    def test_fire_empty_or_only_dormant_has_no_damage_or_rng(self):
        for enemy in((),('h41.sleep',)):
            g=self.game((FIRE,'h41.eight'),enemy=enemy);before=g._rng.getstate();self.play(g,FIRE)
            self.assertEqual(g._rng.getstate(),before);self.assertFalse(self.rows(g,FIRE))

    def test_advance_requires_current_five_cost_minion_not_a_spell(self):
        for held,draws in(('h41.four',0),('h41.five',1),('h41.eight_spell',0)):
            with self.subTest(held=held):
                g=self.game((ADVANCE,held),deck=('h41.noop',YETI,'h41.eight_spell'));s=g.state
                physical=s.players[1].deck[1];self.play(g,ADVANCE,s.players[2].hero_id);s=g.state
                self.assertEqual(len(s.draw_history),draws)
                if draws:self.assertIn(physical,s.players[1].hand)

    def test_advance_current_local_cost_and_pure_one_use_quote(self):
        for held,operation,draws in(('h41.five','h41.cost4',0),('h41.four','h41.cost5',1)):
            with self.subTest(held=held):
                g=self.game((operation,ADVANCE,held));self.play(g,operation);s=g.state
                self.play(g,ADVANCE,s.players[2].hero_id);self.assertEqual(len(g.state.draw_history),draws)
        g=self.game(('h41.mod_once',ADVANCE,'h41.four'));self.play(g,'h41.mod_once');s=g.state
        self.play(g,ADVANCE,s.players[2].hero_id);s=g.state
        self.assertEqual(len(s.draw_history),1);self.assertEqual(s.players[1].cost_modifiers[0].uses_remaining,1)
        held=next(s.entities[i]for i in s.players[1].hand if s.entities[i].card_id=='h41.four')
        self.assertEqual(quote_unselected_cost(s,g.registry,held).amount,5)

    def test_advance_damage_then_new_hand_condition_wait_restore_and_rollback(self):
        g=self.game((ADVANCE,),board=('h41.wait',));s=g.state
        self.play(g,ADVANCE,s.players[2].hero_id);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.draw_history),1)

    def test_advance_no_qualifier_after_damage_skips_and_shield_still_checks(self):
        g=self.game((ADVANCE,),board=('h41.wait',));s=g.state;self.play(g,ADVANCE,s.players[2].hero_id)
        self.choose(g,'leave');self.assertFalse(g.state.draw_history)
        g=self.game((ADVANCE,'h41.five'),enemy=('h41.shield',));self.play(g,ADVANCE,g.state.players[2].board[0])
        self.assertEqual(self.rows(g,ADVANCE)[0].damage_dealt,0);self.assertEqual(len(g.state.draw_history),1)

    def test_advance_no_matching_minion_or_empty_deck_does_not_fatigue(self):
        for deck in((),('h41.noop',)):
            g=self.game((ADVANCE,'h41.five'),deck=deck);s=g.state;self.play(g,ADVANCE,s.players[2].hero_id)
            self.assertFalse(g.state.draw_history);self.assertEqual(g.state.entities[s.players[1].hero_id].health,30)

    def test_fortify_adds_armor_then_deals_current_total_plus_spell_bonus(self):
        g=self.game((FORTIFY,),board=('h41.bonus',),armor=4);s=g.state;target=s.players[2].board[0]
        self.play(g,FORTIFY,target);s=g.state;rows=self.rows(g,FORTIFY)
        self.assertEqual(s.entities[s.players[1].hero_id].armor,7)
        self.assertEqual((rows[0].base_amount,rows[0].spell_bonus,rows[0].damage_dealt),(7,1,8))
        self.assertEqual(s.entities[target].health,92)

    def test_fortify_armor_wait_uses_new_total_portable_and_atomic(self):
        g=self.game((FORTIFY,),board=('h41.armor_wait',),armor=4);target=g.state.players[2].board[0]
        self.play(g,FORTIFY,target);self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.rows(g,FORTIFY))
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.rows(g,FORTIFY)[0].damage_dealt,9)

    def test_fortify_friendly_target_rejected_and_shield_does_not_remove_armor(self):
        g=self.game((FORTIFY,),board=('h41.big',),enemy=('h41.shield',));s=g.state;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,FORTIFY,s.players[1].board[0])
        self.assertEqual(g.snapshot(),before);self.play(g,FORTIFY,s.players[2].board[0]);s=g.state
        self.assertEqual(s.entities[s.players[1].hero_id].armor,3);self.assertEqual(self.rows(g,FORTIFY)[0].damage_dealt,0)

    def test_ablating_only_prior_owner_fel_qualifies(self):
        for mode in('none','current','previous_frost','previous_fel'):
            with self.subTest(mode=mode):
                primer='h41.frost'if mode=='previous_frost'else'h41.fel'
                g=self.game((primer,ABLATING),enemy=('h41.small','h41.big'))
                if mode.startswith('previous'):self.prior(g,primer)
                elif mode=='current':self.play(g,primer)
                target=g.state.players[2].board[0];self.play(g,ABLATING,target);s=g.state
                self.assertEqual(s.entities[target].zone,Zone.GRAVEYARD)
                self.assertEqual(len(self.rows(g,ABLATING)),int(mode=='previous_fel'))

    def test_ablating_fresh_reborn_body_both_sides_bonus_and_single_batch(self):
        g=self.game(('h41.fel',ABLATING),board=('h41.big','h41.bonus'),enemy=('h41.reborn','h41.big','h41.sleep'))
        self.prior(g);target=g.state.players[2].board[0];self.play(g,ABLATING,target);s=g.state;rows=self.rows(g,ABLATING)
        self.assertEqual(len(rows),4);self.assertEqual(len({r.batch_id for r in rows}),1)
        self.assertTrue(all(r.spell_bonus==1 for r in rows));self.assertFalse(any(r.target_id==target for r in rows))
        self.assertFalse(any(s.entities[i].card_id=='h41.reborn'for i in s.players[2].board))
        self.assertEqual([s.entities[i].health for i in s.players[2].board],[9,12])

    def test_ablating_destroy_choice_keeps_original_kindred_then_requeries_board(self):
        g=self.game(('h41.fel',ABLATING),board=('h41.death_wait',),enemy=('h41.reborn','h41.big'))
        self.prior(g);self.play(g,ABLATING,g.state.players[2].board[0]);self.assertIsNotNone(g.state.pending_choice)
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());s=g.state
        self.assertFalse(any(s.entities[i].card_id=='h41.reborn'for i in s.players[2].board))
        self.assertEqual(len(self.rows(g,ABLATING)),3)

    def test_ablating_shield_is_destroyed_without_kindred_and_friendly_rejected(self):
        g=self.game((ABLATING,),board=('h41.big',),enemy=('h41.shield',));s=g.state;before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,ABLATING,s.players[1].board[0])
        self.assertEqual(g.snapshot(),before);target=s.players[2].board[0];self.play(g,ABLATING,target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertFalse(self.rows(g,ABLATING))

    def test_blood_lifesteal_then_refresh_reallows_current_hero_power(self):
        g=self.game(('h41.wound',BLOOD),power=True);self.play(g,'h41.wound');self.use_power(g);s=g.state
        self.assertEqual(s.entities[s.players[1].hero_power_id].uses_this_turn,1)
        self.play(g,BLOOD,s.players[2].board[0]);s=g.state
        self.assertEqual(s.entities[s.players[1].hero_id].health,23)
        self.assertEqual(s.entities[s.players[1].hero_power_id].uses_this_turn,0)
        self.assertEqual(s.players[1].hero_power_uses_this_turn,1)
        self.use_power(g);self.assertEqual(g.state.players[1].hero_power_uses_this_turn,2)

    def test_blood_shield_still_refreshes_without_healing_and_no_power_is_valid(self):
        g=self.game(('h41.wound',BLOOD),enemy=('h41.shield',),power=True);self.play(g,'h41.wound');self.use_power(g)
        s=g.state;self.play(g,BLOOD,s.players[2].board[0]);s=g.state
        self.assertEqual(s.entities[s.players[1].hero_id].health,20)
        self.assertEqual(s.entities[s.players[1].hero_power_id].uses_this_turn,0)
        g=self.game((BLOOD,));self.play(g,BLOOD,g.state.players[2].board[0])
        self.assertEqual(self.rows(g,BLOOD)[0].damage_dealt,3)

    def test_blood_waiting_damage_refresh_restore_clone_replay_and_bad_choice(self):
        g=self.game(('h41.wound',BLOOD),board=('h41.wait',),power=True);self.play(g,'h41.wound');self.use_power(g)
        s=g.state;self.play(g,BLOOD,s.players[2].board[0]);before=g.snapshot()
        self.assertEqual(g.state.entities[s.players[1].hero_power_id].uses_this_turn,1)
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);other=self.portable(g)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());s=g.state
        self.assertEqual(s.entities[s.players[1].hero_power_id].uses_this_turn,0)
        self.assertEqual(s.entities[s.players[1].hero_id].health,23)

    def test_blood_refreshes_power_current_after_damage_replacement(self):
        g=self.game((BLOOD,),board=('h41.replace_power',),power=True);self.use_power(g);s=g.state;old=s.players[1].hero_power_id
        self.play(g,BLOOD,s.players[2].board[0]);s=g.state;new=s.players[1].hero_power_id
        self.assertNotEqual(old,new);self.assertEqual(s.entities[new].card_id,'h41.power2')
        self.assertEqual([e.target_id for e in g.events if e.kind=='hero_power_refreshed'],[new])

    def test_death_strike_six_damage_lifesteal_and_bonus_once(self):
        for bonus,damage in((False,6),(True,7)):
            g=self.game(('h41.wound',STRIKE),board=('h41.bonus',)if bonus else());self.play(g,'h41.wound')
            s=g.state;self.play(g,STRIKE,s.players[2].board[0]);s=g.state
            self.assertEqual(self.rows(g,STRIKE)[0].damage_dealt,damage)
            self.assertEqual(s.entities[s.players[1].hero_id].health,20+damage)
            self.assertEqual(sum(e.kind=='lifesteal'for e in g.events),1)

    def test_lifesteal_spells_minion_targets_only(self):
        for cid in(BLOOD,STRIKE):
            g=self.game((cid,));s=g.state;before=g.snapshot()
            with self.assertRaises(IllegalAction):self.play(g,cid,s.players[2].hero_id)
            self.assertEqual(g.snapshot(),before)

    def test_automatic_spell_entry_preserves_hand_condition_and_lifesteal(self):
        g=self.game(('h41.auto_fire','h41.eight'));self.play(g,'h41.auto_fire')
        self.assertEqual(self.rows(g,FIRE)[0].damage_dealt,8)
        g=self.game(('h41.wound','h41.auto_strike'));self.play(g,'h41.wound');s=g.state
        self.play(g,'h41.auto_strike',s.players[2].board[0]);self.assertEqual(g.state.entities[s.players[1].hero_id].health,26)

    def test_late_failure_rolls_back_payment_random_damage_and_knowledge(self):
        g=self.game((FIRE,'h41.eight'),board=('h41.late',),enemy=('h41.big','h41.huge'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,FIRE)
        self.assertEqual(g.snapshot(),before)

    def test_opponent_cannot_see_qualifying_hand_card_or_cost_proof(self):
        g=self.game((FIRE,'h41.eight'));self.play(g,FIRE)
        visible=json.dumps(g.observe(2))+json.dumps(g.player_events(2))
        for token in('h41.eight','CostQuoteFact','quote_input','candidates','rng_state'):self.assertNotIn(token,visible)


if __name__=='__main__':unittest.main()
