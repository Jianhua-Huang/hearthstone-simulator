"""Persistent fatal transitions, death consumers and incarnation boundaries."""
import json
import unittest
from dataclasses import FrozenInstanceError, replace

from hs_sim.engine import (Attack, CardDefinition, CardType, EndTurn, Game, Keyword,
    PlayCard, PlayerSetup, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellRepeatSpec, TriggerSpec, was_honorably_killed)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, EquipWeapon, GainArmor, Heal, ModifyWeapon, RequestChoice,
    ReturnToHand, SetStats, Silence, Summon, Transform, TriggerDeathrattles)
from hs_sim.engine.health_loss import LoseHealth
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class DeathCauseTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('death-causes-tests-v1')
        self.r.register_card(CardDefinition('hero','hero',CardType.HERO,health=30))
        for name,attack,health in [('body',1,3),('weak',1,1),('large',3,3)]:
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=attack,health=health,keywords=(Keyword.CHARGE,)))
        for name,kw in [('poison',Keyword.POISONOUS),('shield',Keyword.DIVINE_SHIELD),('immune',Keyword.IMMUNE),('reborn',Keyword.REBORN)]:
            self.r.register_card(CardDefinition(name,name,CardType.MINION,attack=1,health=3,keywords=(kw,Keyword.CHARGE)))
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=5,spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        self.r.register_card(CardDefinition('weapon','weapon',CardType.WEAPON,attack=3,durability=1))
        self.script('hit',lambda c:[Damage(c.target_id,3,c.source_id)],target=True)
        self.script('kill',lambda c:[Destroy(c.target_id,c.source_id)],target=True)

    def script(self,name,fn,target=False,**kw):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,requires_target=target,**kw))
    def deferred(self,name,fn):
        self.script(name,lambda c:fn(c) if c.state.spell_repeats[-1].completed==0 else [],target=True)
    def game(self,hand=(),board=(),enemy=('body',),weapon=None,active=1):
        return Game.from_scenario(Scenario((PlayerSetup('hero',hand=hand,board=board,deck=('body',)*5,mana=10,max_mana=10,weapon_card_id=weapon),
            PlayerSetup('hero',hand=hand,board=enemy,deck=('body',)*5,mana=10,max_mana=10)),seed=70,active_player=active),self.r)
    def play(self,g,name,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(p,eid,target));return eid
    def body(self,g,p=2,i=0):return g.state.players[p].board[i]
    def deaths(self,g,cid='body'):return [d for d in g.state.death_history if d.card_id==cid]
    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)
    def choose(self,g):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(c.options[0].id,)))
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
    def pause(self,c,*effects):return RequestChoice(1,(ChoiceOption('ok','continue',effects),),c.source_id)

    def test_exact_damage_persists_source_and_packet_result(self):
        g=self.game(hand=('hit',));victim=self.body(g);source=self.play(g,'hit',victim);d=self.deaths(g)[0]
        self.assertTrue(was_honorably_killed(d));self.assertEqual(d.cause.source_id,source)
        self.assertEqual(d.cause.health_result.health_before,3);self.assertEqual(d.cause.target_id,victim)
        self.assertIsNone(g.state.entities[victim].death_cause);self.check(g)

    def test_overkill_is_not_honorable_even_after_later_health_changes(self):
        self.script('excess',lambda c:[Damage(c.target_id,4,c.source_id)],target=True)
        g=self.game(hand=('excess',));self.play(g,'excess',self.body(g));d=self.deaths(g)[0]
        self.assertEqual(d.cause.kind,'damage');self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_nonlethal_damage_has_no_persistent_fatal_cause(self):
        self.script('one',lambda c:[Damage(c.target_id,1,c.source_id)],target=True)
        g=self.game(hand=('one',));i=self.body(g);self.play(g,'one',i)
        self.assertIsNone(g.state.entities[i].death_cause);self.assertFalse(self.deaths(g));self.check(g)

    def test_poison_without_numeric_lethal_is_separate(self):
        self.script('poisonhit',lambda c:[Damage(c.target_id,1,c.state.players[1].board[0])],target=True)
        g=self.game(hand=('poisonhit',),board=('poison',));self.play(g,'poisonhit',self.body(g));d=self.deaths(g)[0]
        self.assertEqual((d.cause.kind,d.cause.health_result.health_after),('poison',2))
        self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_poisonous_numeric_exact_hit_retains_damage_cause(self):
        self.script('exact',lambda c:[Damage(c.target_id,3,c.state.players[1].board[0])],target=True)
        g=self.game(hand=('exact',),board=('poison',));self.play(g,'exact',self.body(g))
        self.assertTrue(was_honorably_killed(self.deaths(g)[0]));self.check(g)

    def test_poison_requires_successful_damage_and_does_not_destroy_heroes(self):
        self.script('poisonzero', lambda c: [Damage(
            c.state.players[2].board[0], 0, c.state.players[1].board[0])])
        self.script('poisonhit', lambda c: [Damage(
            c.state.players[2].board[0], 1, c.state.players[1].board[0])])
        self.script('poisonhero', lambda c: [Damage(
            c.state.players[2].hero_id, 1, c.state.players[1].board[0])])
        for card, spell in (('body', 'poisonzero'), ('shield', 'poisonhit'),
                            ('immune', 'poisonhit')):
            with self.subTest(card=card, spell=spell):
                g = self.game(hand=(spell,), board=('poison',), enemy=(card,))
                victim, source = self.body(g), self.body(g, 1)
                self.play(g, spell)
                target = g.state.entities[victim]
                self.assertIn(victim, g.state.players[2].board)
                self.assertEqual(target.health, 3)
                self.assertFalse(target.doomed)
                self.assertIsNone(target.death_cause)
                self.assertFalse(g.state.death_history)
                self.assertFalse(any(e.kind == 'damage_dealt' and e.source_id == source
                                     and e.target_id == victim for e in g.events))
                self.check(g)
        g = self.game(hand=('poisonhit',), board=('poison',))
        self.play(g, 'poisonhit')
        self.assertEqual(self.deaths(g)[0].cause.kind, 'poison')
        self.check(g)
        g = self.game(hand=('poisonhero',), board=('poison',))
        self.play(g, 'poisonhero')
        hero = g.state.entities[g.state.players[2].hero_id]
        self.assertEqual((hero.health, g.state.status), (29, 'playing'))
        self.assertFalse(hero.doomed)
        self.assertIsNone(hero.death_cause)
        self.check(g)

    def test_later_exact_hit_cannot_replace_prior_poison(self):
        self.script('batch',lambda c:[DamageBatch((Damage(c.target_id,1,c.state.players[1].board[0]),Damage(c.target_id,2,c.source_id)))],target=True)
        g=self.game(hand=('batch',),board=('poison',));self.play(g,'batch',self.body(g));d=self.deaths(g)[0]
        self.assertEqual(d.cause.kind,'poison');self.assertEqual(d.cause.health_result.packet_index,1)
        self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_later_damage_cannot_overwrite_first_fatal_packet(self):
        self.script('batch',lambda c:[DamageBatch((Damage(c.target_id,3,c.source_id),Damage(c.target_id,9,c.source_id)))],target=True)
        g=self.game(hand=('batch',));self.play(g,'batch',self.body(g));d=self.deaths(g)[0]
        self.assertEqual(d.damage,12);self.assertEqual(d.cause.health_result.health_lost,3)
        self.assertTrue(was_honorably_killed(d));self.check(g)

    def test_wounded_target_uses_remaining_health_before_final_hit(self):
        self.script('batch',lambda c:[DamageBatch((Damage(c.target_id,1,c.source_id),Damage(c.target_id,2,c.source_id)))],target=True)
        g=self.game(hand=('batch',));self.play(g,'batch',self.body(g));d=self.deaths(g)[0]
        self.assertEqual(d.cause.health_result.packet_index,2);self.assertTrue(was_honorably_killed(d));self.check(g)

    def test_prevented_hits_do_not_create_cause(self):
        self.script('area',lambda c:[Damage(c.state.players[2].board[0],3,c.source_id)])
        for card in ('shield','immune'):
            g=self.game(hand=('area',),enemy=(card,));i=self.body(g);self.play(g,'area')
            self.assertIsNone(g.state.entities[i].death_cause);self.assertFalse(g.state.death_history);self.check(g)

    def test_sourceless_numeric_death_does_not_invent_killer(self):
        self.script('neutral',lambda c:[Damage(c.target_id,3)],target=True)
        g=self.game(hand=('neutral',));self.play(g,'neutral',self.body(g));d=self.deaths(g)[0]
        self.assertIsNone(d.cause.source_id);self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_friendly_exact_damage_does_not_claim_enemy_honorable_kill(self):
        g=self.game(hand=('hit',),board=('body',));self.play(g,'hit',self.body(g,1))
        self.assertFalse(was_honorably_killed(self.deaths(g)[0]));self.check(g)

    def test_offturn_source_does_not_claim_honorable_kill(self):
        self.script('off',lambda c:[Damage(c.target_id,3,c.state.players[2].board[0])],target=True)
        g=self.game(hand=('off',),board=('body',),enemy=('large',));self.play(g,'off',self.body(g,1))
        self.assertFalse(was_honorably_killed(self.deaths(g)[0]));self.check(g)

    def test_last_weapon_hit_captures_equipment_before_durability_death(self):
        g=self.game(weapon='weapon');w=g.state.players[1].weapon_id;g.apply(Attack(1,g.state.players[1].hero_id,self.body(g)))
        d=self.deaths(g)[0];self.assertEqual(d.cause.health_result.weapon_id,w);self.assertTrue(was_honorably_killed(d))
        self.assertEqual(self.deaths(g,'weapon')[0].cause.kind,'durability');self.check(g)

    def test_simultaneous_minion_combat_preserves_dead_source(self):
        g=self.game(board=('large',),enemy=('large',));source=self.body(g,1);g.apply(Attack(1,source,self.body(g)))
        ds=self.deaths(g,'large');self.assertEqual(sum(was_honorably_killed(d) for d in ds),1)
        enemy=next(d for d in ds if d.controller==2);self.assertEqual(enemy.cause.source_id,source);self.check(g)

    def test_hero_terminal_keeps_cause_without_fabricating_minion_record(self):
        self.script('fatal',lambda c:[Damage(c.state.players[2].hero_id,30,c.source_id)])
        g=self.game(hand=('fatal',));self.play(g,'fatal');h=g.state.entities[g.state.players[2].hero_id]
        self.assertEqual(h.death_cause.kind,'damage');self.assertFalse(g.state.death_history);self.check(g)

    def test_destroy_is_not_numeric_kill_and_captures_optional_source(self):
        g=self.game(hand=('kill',));source=self.play(g,'kill',self.body(g));d=self.deaths(g)[0]
        self.assertEqual((d.cause.kind,d.cause.source_id),('destroy',source));self.assertIsNone(d.cause.health_result)
        self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_direct_health_loss_is_not_damage(self):
        self.script('loss',lambda c:[LoseHealth(c.target_id,3,c.source_id)],target=True)
        g=self.game(hand=('loss',));self.play(g,'loss',self.body(g));d=self.deaths(g)[0]
        self.assertEqual(d.cause.kind,'health_loss');self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_hero_maximum_loss_preserves_explicit_source_without_damage(self):
        from hs_sim.engine.health_loss import ChangeHeroMaxHealth
        self.script('maximum',lambda c:[ChangeHeroMaxHealth(2,-30,c.source_id)])
        g=self.game(hand=('maximum',));source=self.play(g,'maximum');hero=g.state.entities[g.state.players[2].hero_id]
        self.assertEqual((hero.death_cause.kind,hero.death_cause.reason,hero.death_cause.source_id),('health_state','maximum_health_change',source))
        self.assertIsNone(hero.death_cause.health_result);self.check(g)

    def test_hero_health_transfer_keeps_donor_cause_and_living_recipient(self):
        from hs_sim.engine.health_loss import StealHeroHealth
        self.script('transfer',lambda c:[StealHeroHealth(1,2,30,c.source_id)])
        g=self.game(hand=('transfer',));source=self.play(g,'transfer')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].death_cause.source_id,source)
        self.assertIsNone(g.state.entities[g.state.players[1].hero_id].death_cause);self.check(g)

    def test_zero_health_set_has_explicit_non_damage_cause(self):
        self.script('zero',lambda c:[SetStats(c.target_id,health=0,source_id=c.source_id)],target=True)
        g=self.game(hand=('zero',));source=self.play(g,'zero',self.body(g));d=self.deaths(g)[0]
        self.assertEqual((d.cause.kind,d.cause.reason),('health_state','SetStats'))
        self.assertEqual(d.cause.source_id,source)
        self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_negative_health_buff_records_non_damage_death(self):
        # Signed health deltas became supported in v127; retain a lethal-cause check.
        self.script('shrink',lambda c:[Buff(c.target_id,health=-3,source_id=c.source_id)],target=True)
        g=self.game(hand=('shrink',));target=self.body(g)
        source=self.play(g,'shrink',target);d=self.deaths(g)[0]
        self.assertEqual((d.entity_id,d.max_health,d.damage),(target,0,0))
        self.assertEqual((d.cause.kind,d.cause.reason,d.cause.source_id),('health_state','Buff',source))
        self.assertEqual(d.enchantments[-1].health,-3)
        self.assertIsNone(d.cause.health_result)
        self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_silence_removing_health_aura_has_non_damage_cause(self):
        from hs_sim.engine import AuraSpec
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=3,auras=(AuraSpec(health=1),)))
        self.script('zero',lambda c:[SetStats(c.target_id,health=0)],target=True)
        self.script('silence',lambda c:[Silence(c.target_id)],target=True)
        g=self.game(hand=('zero','silence'),enemy=('aura','body'));self.play(g,'zero',self.body(g,2,1));self.play(g,'silence',self.body(g))
        self.assertEqual(self.deaths(g)[0].cause.reason,'Silence');self.check(g)

    def test_aura_provider_death_does_not_credit_its_damage_to_secondary_death(self):
        from hs_sim.engine import AuraSpec
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=3,auras=(AuraSpec(health=1),)))
        self.script('zero',lambda c:[SetStats(c.target_id,health=0)],target=True)
        g=self.game(hand=('zero','hit'),enemy=('aura','body'));self.play(g,'zero',self.body(g,2,1));self.play(g,'hit',self.body(g))
        d=self.deaths(g)[0];self.assertEqual(d.cause.kind,'health_state')
        self.assertIsNone(d.cause.source_id);self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_temporary_health_expiry_has_new_non_damage_cause(self):
        self.deferred('temporary',lambda c:[SetStats(c.target_id,health=0),Buff(c.target_id,health=3,expires_turn=c.state.turn)])
        g=self.game(hand=('temporary',),board=('repeat',));i=self.body(g);self.play(g,'temporary',i)
        self.assertIsNone(g.state.entities[i].death_cause);g.apply(EndTurn(1))
        d=self.deaths(g)[0];self.assertEqual(d.cause.kind,'health_state');self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_source_transformation_after_fatal_hit_cannot_rewrite_source_identity(self):
        self.deferred('sourcechange',lambda c:[Damage(c.target_id,3,c.state.players[1].board[1]),Transform(c.state.players[1].board[1],'weak')])
        g=self.game(hand=('sourcechange',),board=('repeat','large'));source=self.body(g,1,1);self.play(g,'sourcechange',self.body(g));d=self.deaths(g)[0]
        self.assertEqual((d.cause.source_id,d.cause.source_card_id,d.cause.source_zone_epoch),(source,'large',0))
        self.assertEqual(g.state.entities[source].card_id,'weak');self.check(g)

    def test_copying_dying_body_does_not_copy_its_killer(self):
        self.deferred('copydead',lambda c:[Damage(c.target_id,3,c.source_id),CopyMinion(c.target_id,1)])
        g=self.game(hand=('copydead',),board=('repeat',));self.play(g,'copydead',self.body(g));ds=self.deaths(g)
        self.assertEqual(len(ds),2);copy=next(d for d in ds if d.controller==1)
        self.assertEqual(copy.cause.kind,'health_state');self.assertIsNone(copy.cause.source_id);self.check(g)

    def test_intrinsic_lifesteal_rescues_hero_without_stale_death_cause(self):
        self.r.register_card(CardDefinition('lifeweapon','lifeweapon',CardType.WEAPON,attack=3,durability=2,keywords=(Keyword.LIFESTEAL,)))
        self.script('wound',lambda c:[Damage(c.state.players[1].hero_id,29,c.source_id)])
        g=self.game(hand=('wound',),weapon='lifeweapon');self.play(g,'wound');hero=g.state.players[1].hero_id
        g.apply(Attack(1,hero,self.body(g)));self.assertEqual(g.state.entities[hero].health,3)
        self.assertIsNone(g.state.entities[hero].death_cause);self.assertEqual(g.state.status,'playing');self.check(g)

    def test_rewind_replaces_first_attempt_cause_with_final_attempt(self):
        from hs_sim.engine import RewindSpec
        self.script('rewind',lambda c:[Damage(c.target_id,3+c.rewind_attempt,c.source_id)],target=True,keywords=(Keyword.REWIND,),rewind=RewindSpec())
        g=self.game(hand=('rewind',));self.play(g,'rewind',self.body(g));self.assertTrue(was_honorably_killed(self.deaths(g)[0]))
        choice=g.state.pending_choice;g.apply(SelectChoice(1,choice.id,('retry',)))
        self.assertEqual(len(self.deaths(g)),1);self.assertFalse(was_honorably_killed(self.deaths(g)[0]));self.check(g)

    def test_deferred_healing_clears_fatal_cause_and_later_kill_is_new(self):
        self.deferred('rescue',lambda c:[Damage(c.target_id,3,c.source_id),Heal(c.target_id,3,c.source_id)])
        g=self.game(hand=('rescue','hit'),board=('repeat',));i=self.body(g);self.play(g,'rescue',i)
        self.assertIsNone(g.state.entities[i].death_cause);self.assertFalse(self.deaths(g))
        source=self.play(g,'hit',i);self.assertEqual(self.deaths(g)[0].cause.source_id,source);self.check(g)

    def test_deferred_transform_resets_cause_even_same_physical_id(self):
        self.deferred('morph',lambda c:[Damage(c.target_id,3,c.source_id),Transform(c.target_id,'weak'),Destroy(c.target_id,c.source_id)])
        g=self.game(hand=('morph',),board=('repeat',));self.play(g,'morph',self.body(g));d=self.deaths(g,'weak')[0]
        self.assertEqual(d.cause.kind,'destroy');self.assertEqual(d.cause.target_zone_epoch,1);self.check(g)

    def test_deferred_return_to_hand_removes_old_cause(self):
        self.deferred('bounce',lambda c:[Damage(c.target_id,3,c.source_id),ReturnToHand(c.target_id)])
        g=self.game(hand=('bounce',),board=('repeat',));i=self.body(g);self.play(g,'bounce',i)
        self.assertIn(i,g.state.players[2].hand);self.assertIsNone(g.state.entities[i].death_cause);self.check(g)

    def test_deferred_control_change_keeps_captured_controller(self):
        self.deferred('steal',lambda c:[Damage(c.target_id,3,c.source_id),ChangeControl(c.target_id,1)])
        g=self.game(hand=('steal',),board=('repeat',));self.play(g,'steal',self.body(g));d=self.deaths(g)[0]
        self.assertEqual((d.controller,d.cause.target_controller),(1,2));self.assertTrue(was_honorably_killed(d));self.check(g)

    def test_reborn_creates_fresh_entity_without_old_cause(self):
        g=self.game(hand=('hit',),enemy=('reborn',));old=self.body(g);self.play(g,'hit',old);new=self.body(g)
        self.assertNotEqual(old,new);self.assertIsNone(g.state.entities[new].death_cause)
        self.assertTrue(was_honorably_killed(self.deaths(g,'reborn')[0]));self.check(g)

    def test_deathrattle_choice_retains_immutable_cause_after_source_leaves(self):
        self.r.register_behavior('death',lambda c:[self.pause(c,GainArmor(2,7 if was_honorably_killed(c.death) else 2))])
        self.r.register_card(CardDefinition('dr','dr',CardType.MINION,health=3,deathrattle='death'))
        g=self.game(hand=('hit',),enemy=('dr',));self.play(g,'hit',self.body(g));self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,7);self.check(g)

    def test_pending_deferred_fatal_state_survives_snapshot(self):
        self.deferred('pending',lambda c:[Damage(c.target_id,3,c.source_id),self.pause(c,Heal(c.target_id,3,c.source_id))])
        g=self.game(hand=('pending',),board=('repeat',));i=self.body(g);self.play(g,'pending',i)
        self.assertEqual(g.state.entities[i].death_cause.kind,'damage');self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertIsNone(g.state.entities[i].death_cause);self.check(g)

    def test_failed_effect_rolls_back_fatal_records_and_rng(self):
        self.script('bad',lambda c:[Damage(c.target_id,3,c.source_id),Summon(1,'unknown')],target=True)
        g=self.game(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad',self.body(g))
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_failed_choice_preserves_previous_committed_death(self):
        self.r.register_behavior('death',lambda c:[self.pause(c,Summon(1,'unknown'))])
        self.r.register_card(CardDefinition('dr','dr',CardType.MINION,health=3,deathrattle='death'))
        # Unknown branches are validated before the choice, so use a registered failing callback.
        self.r.register_behavior('fail',lambda c:[Summon(1,'unknown')])
        from hs_sim.engine.effects import InvokeBehavior
        self.r.register_behavior('pendingdeath',lambda c:[self.pause(c,InvokeBehavior('fail',c.source_id,1))])
        self.r.register_card(CardDefinition('pendingdr','pendingdr',CardType.MINION,health=3,deathrattle='pendingdeath'))
        g=self.game(hand=('hit',),enemy=('pendingdr',));self.play(g,'hit',self.body(g));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_triggering_living_deathrattle_has_no_fabricated_death_record(self):
        self.r.register_behavior('death',lambda c:[GainArmor(1,2 if c.death is None and not was_honorably_killed(c.death) else 99)])
        self.r.register_card(CardDefinition('dr','dr',CardType.MINION,health=3,deathrattle='death'))
        self.script('trigger',lambda c:[TriggerDeathrattles(c.target_id)],target=True)
        g=self.game(hand=('trigger',),board=('dr',));self.play(g,'trigger',self.body(g,1))
        self.assertFalse(g.state.death_history);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2);self.check(g)

    def test_weapon_replacement_is_explicit_and_not_damage(self):
        self.script('equip',lambda c:[EquipWeapon(1,'weapon')])
        g=self.game(hand=('equip',),weapon='weapon');old=g.state.players[1].weapon_id;self.play(g,'equip');d=self.deaths(g,'weapon')[0]
        self.assertEqual(d.entity_id,old);self.assertEqual(d.cause.kind,'replaced');self.assertFalse(was_honorably_killed(d));self.check(g)

    def test_weapon_durability_effect_preserves_source(self):
        self.script('wear',lambda c:[ModifyWeapon(c.state.players[1].weapon_id,durability=-1,source_id=c.source_id)])
        g=self.game(hand=('wear',),weapon='weapon');source=self.play(g,'wear');d=self.deaths(g,'weapon')[0]
        self.assertEqual((d.cause.kind,d.cause.source_id),('durability',source));self.check(g)

    def test_tampered_cause_identity_kind_and_source_rejected_after_rehash(self):
        g=self.game(hand=('hit',));self.play(g,'hit',self.body(g))
        for key,value in [('target_id',999),('target_card_id','weak'),('source_id',None),('turn',99),('kind','destroy'),('source_zone_epoch',999),('target_zone_epoch',999)]:
            s=g.snapshot();s['state']['death_history'][0]['cause'][key]=value
            with self.subTest(key=key):self.reject(s)

    def test_missing_or_duplicate_frozen_result_fields_rejected(self):
        g=self.game(hand=('hit',));self.play(g,'hit',self.body(g))
        for duplicate in (False,True):
            s=g.snapshot();rows=s['state']['death_history'][0]['cause']['result']
            if duplicate:rows.append(rows[0])
            else:rows.pop()
            self.reject(s)

    def test_pending_fatal_entity_cannot_drop_its_cause(self):
        self.deferred('pending',lambda c:[Damage(c.target_id,3,c.source_id),self.pause(c)])
        g=self.game(hand=('pending',),board=('repeat',));i=self.body(g);self.play(g,'pending',i)
        s=g.snapshot();s['state']['entities'][str(i)]['death_cause']=None;self.reject(s)

    def test_frozen_cause_and_result_cannot_be_mutated(self):
        g=self.game(hand=('hit',));self.play(g,'hit',self.body(g));d=self.deaths(g)[0]
        with self.assertRaises(FrozenInstanceError):d.cause.kind='destroy'
        with self.assertRaises(FrozenInstanceError):d.cause.health_result.health_before=99
        with self.assertRaises(ValueError):was_honorably_killed(d.cause)

    def test_private_cause_does_not_enter_player_observation(self):
        g=self.game(hand=('hit',));self.play(g,'hit',self.body(g))
        for player in (1,2):
            text=json.dumps(g.observe(player))
            for field in ('death_cause','target_zone_epoch','source_zone_epoch','health_packet','health_resolved'):
                self.assertNotIn(field,text)
        self.check(g)

    def test_unknown_destroy_source_rejected_without_state_change(self):
        self.script('badsource',lambda c:[Destroy(c.target_id,99999)],target=True)
        g=self.game(hand=('badsource',));s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'badsource',self.body(g))
        self.assertEqual(g.snapshot(),s)


class KorrakRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
    def game(self,fn,enemy=('AV_143',)):
        self.r.register_behavior('probe',fn)
        self.r.register_card(CardDefinition('probe','probe',CardType.SPELL,on_play='probe'))
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('probe',),mana=10,max_mana=10),
            PlayerSetup('HERO_08',board=enemy))),self.r)
    def play(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]))
    def check(self,g):self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_frozen_card_metadata(self):
        c=self.r.card('AV_143');self.assertEqual((c.name,c.cost,c.attack,c.health),('血怒者科尔拉克',4,3,5))
        self.assertEqual(c.deathrattle,'m5.korrak')
    def test_direct_destroy_resummons_baseline_entity(self):
        g=self.game(lambda c:[Buff(c.state.players[2].board[0],attack=7),Destroy(c.state.players[2].board[0],c.source_id)])
        old=g.state.players[2].board[0];self.play(g);new=g.state.entities[g.state.players[2].board[0]]
        self.assertNotEqual(new.id,old);self.assertEqual((new.attack,new.health),(3,5));self.assertIsNone(new.death_cause);self.check(g)
    def test_exact_damage_stops_resummon(self):
        g=self.game(lambda c:[Damage(c.state.players[2].board[0],5,c.source_id)]);self.play(g)
        self.assertFalse(g.state.players[2].board);self.assertTrue(was_honorably_killed(g.state.death_history[0]));self.check(g)
    def test_live_deathrattle_resummons_without_fabricated_death(self):
        g=self.game(lambda c:[TriggerDeathrattles(c.state.players[2].board[0])]);self.play(g)
        self.assertEqual(len(g.state.players[2].board),2);self.assertFalse(g.state.death_history);self.check(g)
    def test_transferred_deathrattle_still_summons_korrak(self):
        from hs_sim.engine.effects import GrantDeathrattle
        g=self.game(lambda c:[GrantDeathrattle(c.state.players[2].board[0],'m5.korrak',c.source_id),
            Destroy(c.state.players[2].board[0],c.source_id)],enemy=('CS2_182',));self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].board],['AV_143']);self.check(g)
    def test_representative_player_scenario_and_pending_recovery(self):
        from examples.death_attribution import run
        g,s=run();self.assertIsNotNone(s['state']['pending_choice']);self.assertEqual(len(g.history),7)
        self.assertEqual(len(g.state.death_history),2)


if __name__=='__main__':unittest.main()
