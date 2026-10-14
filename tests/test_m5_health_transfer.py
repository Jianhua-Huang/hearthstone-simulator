"""R-099 provisional maximum-health operations through transactional actions."""
import json
import unittest

from hs_sim.engine import (Game, Registry, CardDefinition, CardType, CardClass, CardMetadata,
    PlayerSetup, Scenario, PlayCard, SelectChoice, EndTurn, Zone, Keyword, TriggerSpec,
    HealthFlow, HealthOp, HealthLayer, HealthRule, HealthLossReplacementSpec,
    ChangeHeroMaxHealth, StealHeroHealth, LoseHealth, GainMaxHealth,
    ResolutionError, SnapshotError, SpellRepeatSpec, RewindSpec, CastSpell)
from hs_sim.engine.effects import (Damage, Heal, GainArmor, GrantKeyword, Summon,
    Destroy, Silence, Transform, ReturnToHand, ChangeControl, ReplaceHero,
    ChoiceOption, RequestChoice, InvokeBehavior)
from hs_sim.engine.replay import build_replay, replay


class HealthTransferTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('health-transfer-tests-v1')
        for cid, cls in (('mage', CardClass.MAGE), ('warrior', CardClass.WARRIOR)):
            self.r.register_card(CardDefinition(cid,cid,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        self.minion('plain',health=4)
        self.script(lambda c:[StealHeroHealth(c.player_id,3-c.player_id,10,c.source_id)])

    def minion(self,cid,**kw):
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,**kw))
    def script(self,fn,cid='transfer',kind=CardType.SPELL,**kw):
        self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,kind,on_play=cid,**kw))
    def game(self,hand=('transfer',),board=(),enemy=(),armor=0,enemy_armor=0,enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('mage',hand=hand,board=board,armor=armor,deck=('plain',)*8,mana=10,max_mana=10),
            PlayerSetup('warrior',hand=enemy_hand,board=enemy,armor=enemy_armor,deck=('plain',)*8,mana=10,max_mana=10)),seed=59),self.r)
    def play(self,g,cid='transfer'):
        p=g.state.active_player
        eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid));return eid
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def events(self,g,kind):return [e for e in g.events if e.kind==kind]
    def check(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,self.r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),snap)
    def choose(self,g,option=None):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option or c.options[0].id,)))
    def wound(self,amount=7,p=1):
        self.script(lambda c:[LoseHealth(c.state.players[p].hero_id,amount)],'wound')
    def watch(self,fn,event='max_health_lost'):
        self.r.register_behavior('watch',fn)
        self.minion('watch',health=4,triggers=(TriggerSpec(event,'watch'),))

    def test_full_heroes_transfer_both_current_and_maximum(self):
        g=self.game();self.play(g)
        self.assertEqual([(self.hero(g,p).health,self.hero(g,p).max_health) for p in (1,2)],[(40,40),(20,20)])
        self.check(g)

    def test_both_missing_health_deficits_preserved(self):
        self.script(lambda c:[LoseHealth(c.state.players[1].hero_id,7),LoseHealth(c.state.players[2].hero_id,4)],'wound')
        g=self.game(hand=('wound','transfer'));self.play(g,'wound');self.play(g)
        self.assertEqual([(self.hero(g,p).health,self.hero(g,p).damage) for p in (1,2)],[(33,7),(16,4)])
        self.check(g)

    def test_reversed_player_and_opponent_turn(self):
        g=self.game(hand=(),enemy_hand=('transfer',));g.apply(EndTurn(1));self.play(g)
        self.assertEqual((self.hero(g).max_health,self.hero(g,2).max_health),(20,40));self.check(g)

    def test_armor_untouched(self):
        g=self.game(armor=13,enemy_armor=27);self.play(g)
        self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(13,27))
        self.assertEqual(self.hero(g,2).health,20)

    def test_immunity_and_shield_are_not_consumed(self):
        self.script(lambda c:[GrantKeyword(c.state.players[2].hero_id,k) for k in (Keyword.IMMUNE,Keyword.DIVINE_SHIELD)],'protect')
        g=self.game(hand=('protect','transfer'));self.play(g,'protect');self.play(g)
        self.assertTrue({Keyword.IMMUNE,Keyword.DIVINE_SHIELD} <= self.hero(g,2).keywords)
        self.assertEqual(self.hero(g,2).health,20);self.assertFalse(self.events(g,'shield_lost'))

    def test_damage_and_healing_rules_do_not_modify_transfer(self):
        for flow in (HealthFlow.DAMAGE,HealthFlow.HEALING):
            for op,amount in ((HealthOp.SCALE,3),(HealthOp.PREVENT,0),(HealthOp.CONVERT,0)):
                with self.subTest(flow=flow,op=op):
                    self.setUp();self.minion('rule',health=4,spell_damage=9,health_rules=(HealthRule(flow,op,amount),))
                    g=self.game(board=('rule',));self.play(g)
                    self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20))

    def test_damage_redirection_does_not_move_transfer(self):
        self.minion('redirect',health=8,health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.REDIRECT,
            layer=HealthLayer.TARGET,target_kinds=(CardType.HERO,),target_relation='friendly',redirect_to='self'),))
        g=self.game(enemy=('redirect',));self.play(g)
        self.assertEqual(self.hero(g,2).health,20)
        self.assertEqual(g.state.entities[g.state.players[2].board[0]].health,8)

    def test_lifesteal_and_poisonous_do_not_create_extra_effects(self):
        self.wound();self.script(lambda c:[StealHeroHealth(1,2,10,c.source_id)],'drain',keywords=(Keyword.LIFESTEAL,Keyword.POISONOUS))
        g=self.game(hand=('wound','drain'));self.play(g,'wound');self.play(g,'drain')
        self.assertEqual(self.hero(g).health,33)
        for event in ('damage_dealt','healed','lifesteal','health_spent'):self.assertFalse(self.events(g,event))
        self.assertEqual(len(self.events(g,'health_lost')),1)  # only the setup wound

    def test_loss_replacement_does_not_intercept_max_transfer(self):
        self.minion('guard',health=4,health_loss_replacements=(HealthLossReplacementSpec(own_turn_only=False),))
        g=self.game(board=('guard',),enemy=('guard',));self.play(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20))
        self.assertFalse(self.events(g,'health_loss_replaced'));self.check(g)

    def test_direct_loss_still_replaced_after_max_reduction(self):
        self.minion('guard',health=4,health_loss_replacements=(HealthLossReplacementSpec(own_turn_only=False),))
        self.script(lambda c:[LoseHealth(c.state.players[2].hero_id,3)],'loss')
        g=self.game(hand=('transfer','loss'),enemy=('guard',));self.play(g);self.play(g,'loss')
        self.assertEqual((self.hero(g,2).health,self.hero(g,2).max_health),(23,23))
        self.assertEqual(self.events(g,'health_loss_replaced')[0].amount,3)

    def test_healing_restores_deficits_but_not_stolen_maximum(self):
        self.wound(4,2);self.script(lambda c:[Heal(c.state.players[2].hero_id,99)],'heal')
        g=self.game(hand=('wound','transfer','heal'));self.play(g,'wound');self.play(g);self.play(g,'heal')
        self.assertEqual((self.hero(g,2).health,self.hero(g,2).max_health),(20,20))
        self.assertEqual(self.events(g,'healed')[0].amount,4);self.check(g)

    def test_transfer_not_capped_by_current_health_and_lethal_is_atomic(self):
        self.wound(25,2);g=self.game(hand=('wound','transfer'));self.play(g,'wound');self.play(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,-5))
        self.assertEqual((g.state.status,g.state.winner),('finished',1));self.check(g)

    def test_transfer_capped_by_available_maximum_and_floored_at_zero(self):
        self.script(lambda c:[ChangeHeroMaxHealth(2,-25)],'shrink')
        g=self.game(hand=('shrink','transfer'));self.play(g,'shrink');self.play(g)
        self.assertEqual((self.hero(g).max_health,self.hero(g,2).max_health),(35,0))
        self.assertEqual(self.events(g,'hero_health_stolen')[0].amount,5)
        self.assertEqual(dict(self.events(g,'hero_health_stolen')[0].data)['requested'],10);self.check(g)

    def test_lethal_stops_following_effects_and_reactions(self):
        self.watch(lambda c:[GainArmor(1,99)])
        self.script(lambda c:[StealHeroHealth(1,2,30),GainArmor(1,77)],'lethal')
        g=self.game(hand=('lethal',),board=('watch',));self.play(g,'lethal')
        self.assertEqual(self.hero(g).health,60);self.assertEqual(self.hero(g).armor,0);self.check(g)

    def test_zero_transfer_has_no_attachments_events_or_randomness(self):
        self.script(lambda c:[StealHeroHealth(1,2,0)],'zero')
        g=self.game(hand=('zero',));before=g.snapshot()['rng_state'];self.play(g,'zero')
        self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertFalse(self.hero(g).enchantments);self.assertFalse(self.hero(g,2).enchantments)
        self.assertFalse(self.events(g,'hero_health_stolen'))

    def test_both_mutations_visible_to_first_event_observer(self):
        self.watch(lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].max_health+
            c.state.entities[c.state.players[2].hero_id].max_health)])
        g=self.game(board=('watch',));self.play(g)
        self.assertEqual(self.hero(g).armor,60);self.check(g)

    def test_three_public_events_follow_one_atomic_transfer(self):
        g=self.game();self.play(g)
        kinds=('max_health_lost','max_health_gained','hero_health_stolen')
        events=[e for e in g.events if e.kind in kinds]
        self.assertEqual([e.kind for e in events],list(kinds))
        self.assertEqual([e.amount for e in events],[10,10,10])

    def test_reaction_may_pause_after_both_changes_and_restore(self):
        self.watch(lambda c:[RequestChoice(2,(ChoiceOption('ok','ok',(GainArmor(2,2),)),))])
        g=self.game(board=('watch',));self.play(g);self.check(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20))
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_source_destroyed_in_first_reaction_keeps_both_changes(self):
        self.script(lambda c:[StealHeroHealth(1,2,10,c.source_id)],'body',kind=CardType.MINION,health=5)
        self.watch(lambda c:[Destroy(c.event.source_id)])
        g=self.game(hand=('body',),board=('watch',));source=self.play(g,'body')
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20));self.check(g)

    def test_lifecycle_of_source_does_not_revoke_permanent_changes(self):
        for operation in (Silence,ReturnToHand,lambda i:Transform(i,'plain'),lambda i:ChangeControl(i,2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.script(lambda c:[StealHeroHealth(1,2,10,c.source_id)],'body',kind=CardType.MINION,health=5)
                self.script(lambda c:[operation(c.state.players[1].board[0])],'change')
                g=self.game(hand=('body','change'));self.play(g,'body');self.play(g,'change')
                self.assertEqual((self.hero(g).max_health,self.hero(g,2).max_health),(40,20));self.check(g)

    def test_summoning_source_does_not_execute_battlecry(self):
        self.script(lambda c:[StealHeroHealth(1,2,10,c.source_id)],'body',kind=CardType.MINION,health=5)
        self.script(lambda c:[Summon(1,'body')],'summon');g=self.game(hand=('summon',));self.play(g,'summon')
        self.assertEqual(self.hero(g).health,30);self.assertFalse(self.events(g,'hero_health_stolen'));self.check(g)

    def test_repeated_transfer_creates_independent_attachments(self):
        g=self.game(hand=('transfer','transfer'));self.play(g);self.play(g)
        attachments=[a for p in (1,2) for a in self.hero(g,p).enchantments]
        self.assertEqual(len({a.id for a in attachments}),4)
        self.assertEqual((self.hero(g).max_health,self.hero(g,2).max_health),(50,10));self.check(g)

    def test_hero_replacement_copies_permanent_changes_with_new_ids(self):
        self.script(lambda c:[ReplaceHero(1,'warrior'),ReplaceHero(2,'mage')],'replace')
        g=self.game(hand=('transfer','replace'));self.play(g)
        old=[self.hero(g,p).enchantments[0].id for p in (1,2)];self.play(g,'replace')
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20))
        self.assertFalse(set(old)&{self.hero(g,p).enchantments[0].id for p in (1,2)});self.check(g)

    def test_transfer_resolves_replaced_heroes_when_executed(self):
        self.script(lambda c:[ReplaceHero(2,'mage'),StealHeroHealth(1,2,10,c.source_id)],'replace')
        g=self.game(hand=('replace',));old=self.hero(g,2).id;self.play(g,'replace')
        self.assertEqual(g.state.entities[old].max_health,30)
        self.assertEqual(self.hero(g,2).max_health,20);self.check(g)

    def test_signed_maximum_change_preserves_missing_health(self):
        self.wound();self.script(lambda c:[ChangeHeroMaxHealth(1,-10)],'shrink')
        g=self.game(hand=('wound','shrink'));self.play(g,'wound');self.play(g,'shrink')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g).damage),(13,20,7));self.check(g)

    def test_clamp_current_growth_does_not_restore_health(self):
        self.wound();self.script(lambda c:[ChangeHeroMaxHealth(1,10,health_policy='clamp_current')],'grow')
        g=self.game(hand=('wound','grow'));self.play(g,'wound');self.play(g,'grow')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(23,40));self.check(g)

    def test_clamp_current_reduction_below_current_caps_health(self):
        self.wound();self.script(lambda c:[ChangeHeroMaxHealth(1,-10,health_policy='clamp_current')],'shrink')
        g=self.game(hand=('wound','shrink'));self.play(g,'wound');self.play(g,'shrink')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(20,20));self.check(g)

    def test_clamp_current_reduction_above_current_keeps_health(self):
        self.wound(15);self.script(lambda c:[ChangeHeroMaxHealth(1,-10,health_policy='clamp_current')],'shrink')
        g=self.game(hand=('wound','shrink'));self.play(g,'wound');self.play(g,'shrink')
        self.assertEqual((self.hero(g).health,self.hero(g).max_health),(15,20))

    def test_reduction_floors_maximum_and_can_end_game(self):
        self.script(lambda c:[ChangeHeroMaxHealth(1,-100)],'shrink')
        g=self.game(hand=('shrink',));self.play(g,'shrink')
        self.assertEqual(self.hero(g).max_health,0);self.assertEqual(g.state.winner,2)
        self.assertEqual(self.events(g,'max_health_lost')[0].amount,30);self.check(g)

    def test_growth_legacy_entry_point_matches_signed_entry_point(self):
        self.script(lambda c:[GainMaxHealth(1,7),ChangeHeroMaxHealth(2,7)],'grow')
        g=self.game(hand=('grow',));self.play(g,'grow')
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(37,37));self.check(g)

    def test_zero_maximum_change_has_no_attachments(self):
        self.script(lambda c:[ChangeHeroMaxHealth(1,0)],'zero')
        g=self.game(hand=('zero',));self.play(g,'zero')
        self.assertFalse(self.hero(g).enchantments);self.assertFalse(self.events(g,'max_health_gained'))

    def test_max_reduction_is_not_intercepted_by_loss_replacement(self):
        self.minion('guard',health=4,health_loss_replacements=(HealthLossReplacementSpec(),))
        self.script(lambda c:[ChangeHeroMaxHealth(1,-10)],'shrink')
        g=self.game(hand=('shrink',),board=('guard',));self.play(g,'shrink')
        self.assertEqual(self.hero(g).max_health,20);self.assertFalse(self.events(g,'health_loss_replaced'))

    def test_pending_typed_effects_round_trip_before_execution(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(
            ChangeHeroMaxHealth(1,4,c.source_id,'clamp_current'),StealHeroHealth(1,2,7,c.source_id))),))],'choose')
        g=self.game(hand=('choose',));self.play(g,'choose');self.check(g)
        restored=Game.from_snapshot(json.loads(json.dumps(g.snapshot())),self.r)
        for match in (g,restored):self.choose(match)
        self.assertEqual((self.hero(g).health,self.hero(g).max_health,self.hero(g,2).max_health),(37,41,23))
        self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_error_after_transfer_rolls_back_whole_action(self):
        self.script(lambda c:[StealHeroHealth(1,2,10),Summon(1,'missing')],'bad')
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_error_after_resumed_transfer_keeps_choice_checkpoint(self):
        self.r.register_behavior('late.fail',lambda c:[Summon(1,'missing')])
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(
            StealHeroHealth(1,2,10),InvokeBehavior('late.fail',c.source_id,1))),))],'bad')
        g=self.game(hand=('bad',));self.play(g,'bad');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_invalid_source_even_at_zero_rolls_back(self):
        for effect in (ChangeHeroMaxHealth(1,0,99999),StealHeroHealth(1,2,0,99999)):
            with self.subTest(effect=effect):
                self.setUp();self.script(lambda c:[effect],'bad');g=self.game(hand=('bad',));before=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,'bad')
                self.assertEqual(g.snapshot(),before)

    def test_strict_effect_arguments(self):
        factories=(lambda:StealHeroHealth(1,1,0),lambda:StealHeroHealth(1,3,1),
            lambda:StealHeroHealth(True,2,1),lambda:StealHeroHealth(1,2,-1),lambda:StealHeroHealth(1,2,True),
            lambda:ChangeHeroMaxHealth(0,1),lambda:ChangeHeroMaxHealth(1,True),
            lambda:ChangeHeroMaxHealth(1,1.5),lambda:ChangeHeroMaxHealth(1,1,health_policy='heal'))
        for fn in factories:
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()

    def test_corrupted_pending_effect_is_rejected(self):
        self.script(lambda c:[RequestChoice(1,(ChoiceOption('ok','ok',(StealHeroHealth(1,2,10),)),))],'choose')
        g=self.game(hand=('choose',));self.play(g,'choose')
        # Mutate the encoded amount regardless of the scheduler's frame layout.
        def corrupt(value):
            if isinstance(value,dict):
                if value.get('type','').endswith('.StealHeroHealth'):value['fields']['amount']=-1;return True
                return any(corrupt(v) for v in value.values())
            return any(corrupt(v) for v in value) if isinstance(value,list) else False
        snapshot=g.snapshot();self.assertTrue(corrupt(snapshot))
        with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,self.r)

    def test_automatic_cast_uses_common_transfer(self):
        self.script(lambda c:[CastSpell(1,'transfer',c.source_id)],'auto')
        g=self.game(hand=('auto',));self.play(g,'auto')
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20));self.check(g)

    def test_spell_repeat_runs_transfer_twice_for_one_play(self):
        self.minion('repeat',health=4,spell_repeats=(SpellRepeatSpec(class_mode='any'),))
        g=self.game(board=('repeat',));self.play(g)
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(50,10))
        self.assertEqual(len(g.state.play_history),1);self.check(g)

    def test_rewind_restores_both_heroes_and_attachments_before_retry(self):
        self.script(lambda c:[StealHeroHealth(1,2,10,c.source_id)],'retry',keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('retry',));self.play(g,'retry');self.check(g);self.choose(g,'retry')
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(40,20))
        self.assertEqual(len(self.hero(g).enchantments),1);self.assertEqual(len(self.hero(g,2).enchantments),1)
        self.check(g)

    def test_player_port_and_public_events_do_not_expose_internal_ids(self):
        g=self.game(enemy_hand=('plain',));port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        for p in (1,2):
            public=g.player_events(p)
            for kind in ('max_health_lost','max_health_gained','hero_health_stolen'):
                self.assertEqual([e['amount'] for e in public if e['kind']==kind],[10])
            for key in ('enchantment_id','recipient_id','donor_player_id','requested'):
                self.assertNotIn(key,json.dumps(public))
        self.assertNotIn('plain',json.dumps(g.observe(1)));self.check(g)


class SnakeRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,hand=('WW_001t25',),enemy=(),armor=0):
        from hs_sim.engine import GenerationContext
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,mana=10,max_mana=10),
            PlayerSetup('HERO_01',board=enemy,armor=armor)),seed=59,
            generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)
    def play(self,g,cid='WW_001t25',target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,eid,target));return eid
    def hero(self,g,p):return g.state.entities[g.state.players[p].hero_id]
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_frozen_snake_has_ten_health_battlecry(self):
        card=self.r.card('WW_001t25');self.assertEqual((card.cost,card.attack,card.health),(4,5,5))
        g=self.game(armor=99);self.play(g)
        self.assertEqual((self.hero(g,1).max_health,self.hero(g,2).max_health,self.hero(g,2).armor),(40,20,99));self.check(g)

    def test_snake_bounce_and_replay_stacks_permanent_changes(self):
        self.r.register_behavior('bounce',lambda c:[ReturnToHand(c.target_id)])
        self.r.register_card(CardDefinition('bounce','bounce',CardType.SPELL,on_play='bounce',requires_target=True))
        g=self.game(hand=('WW_001t25','bounce'));source=self.play(g)
        self.play(g,'bounce',source);self.play(g)
        self.assertEqual((self.hero(g,1).health,self.hero(g,2).health),(50,10));self.check(g)

    def test_fourth_warlock_excavation_rewards_executable_snake(self):
        from hs_sim.engine import Excavate
        self.r.register_card(CardDefinition('warlock','warlock',CardType.HERO,health=30,
            metadata=CardMetadata(False,(CardClass.WARLOCK,),None)))
        self.r.register_behavior('dig',lambda c:[ReplaceHero(1,'warlock'),Excavate(1,c.source_id,count=4)])
        self.r.register_card(CardDefinition('dig','dig',CardType.SPELL,on_play='dig'))
        g=self.game(hand=('dig',));self.play(g,'dig')
        self.assertEqual(g.state.excavation_history[-1].card_id,'WW_001t25');self.play(g)
        self.assertEqual(self.hero(g,2).max_health,20);self.check(g)

    def test_onyxia_replacement_does_not_intercept_snake_under_r099(self):
        g=self.game(enemy=('CATA_155',));self.play(g)
        self.assertEqual(self.hero(g,2).max_health,20)
        self.assertFalse(any(e.kind=='health_loss_replaced' for e in g.events));self.check(g)

    def test_sample_rewards_are_executable_but_pools_still_incomplete(self):
        from hs_sim.engine import GenerationContext
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS,EXCAVATE_EIGHT_POOL_ID
        self.assertEqual(len(EXCAVATE_CLASS_REWARDS),7)
        self.assertTrue(set(EXCAVATE_CLASS_REWARDS.values()) <= set(self.r.cards))
        self.assertFalse(self.r.pool(EXCAVATE_EIGHT_POOL_ID,GenerationContext('local-2026-09-23','experimental')).complete)

    def test_real_example_repeats_battlecry_and_finishes_through_armor(self):
        from examples.excavate_health_transfer import run
        g,snapshot=run();self.assertEqual((g.state.status,g.state.winner),('finished',1))
        self.assertEqual(self.hero(g,2).armor,99)
        self.assertEqual(snapshot['schema_version'],266)


if __name__=='__main__':unittest.main()
