"""Real Beast notifications retain original identities through public effects."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.beast_trigger_native_cards import load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,ForceAttack,Freeze,GainArmor,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.model import BoardPresenceReference,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

BASHER='DINO_400';PAT='TIME_046';THRESHER='TLC_256';TUNNEL='TLC_840';PLAIN='CORE_CS2_182'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())
def registry(mode=None):
    r=build_registry()
    scripts=dict(armor=lambda c:(GainArmor(c.player_id,5),),zero=lambda c:(GainArmor(c.player_id,0),),
        two=lambda c:(GainArmor(c.player_id,1),GainArmor(c.player_id,1)),enemy_armor=lambda c:(GainArmor(3-c.player_id,5),),
        noop=lambda c:(),hit=lambda c:(Damage(c.target_id,1,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        freeze=lambda c:(Freeze(c.target_id,c.source_id),),
        auto=lambda c:(CastSpell(c.player_id,'k52.noop',c.source_id),),
        force=lambda c:(ForceAttack(BoardPresenceReference.capture(c.state,next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==TUNNEL)),c.state.players[3-c.player_id].hero_id),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k52',c.source_id),),
        reenter=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.state.entities[c.target_id].controller,cause=SummonCause.capture(c)),))
    for name,body in scripts.items():
        key='k52.'+name;r.register_behavior(key,body)
        if name not in('fail','reenter'):r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,requires_target=name in('hit','silence','freeze')))
    for cid,attack,health,extra in [('target',1,30,{}),('hard',4,20,{}),('power',0,8,dict(spell_damage=5))]:
        r.register_card(CardDefinition('k52.'+cid,cid,CardType.MINION,attack=attack,health=health,metadata=META,**extra))
    r.register_card(CardDefinition('k52.caster','Automatic spell source',CardType.MINION,health=3,metadata=META,battlecry='k52.auto'))
    if mode:
        def watch(c):
            event=c.event
            if event.kind=='stats_changed':
                if c.state.entities[event.target_id].card_id!=BASHER:return ()
                if mode=='new_enemy':
                    return(SummonByCard(3-c.player_id,(SummonEntryMaterial('k52.target'),),SummonCause.capture(c)),)
                if mode=='source_reentry':effects=(ReturnToHand(event.target_id),InvokeBehavior('k52.reenter',c.source_id,c.player_id,event.target_id))
                elif mode=='source_transfer':effects=(ChangeControl(event.target_id,3-c.player_id),)
                else:effects=(GainArmor(c.player_id,0),)
            else:
                if event.source_id is None or c.state.entities[event.source_id].card_id!=BASHER:return ()
                target=dict(event.data)['defender_id']
                effects=(ReturnToHand(target),InvokeBehavior('k52.reenter',c.source_id,c.player_id,target))if mode=='target_reentry'else(GainArmor(c.player_id,0),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k52.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k52.watch',watch)
        event='random_choice'if mode in('target_reentry','random_wait')else'stats_changed'
        r.register_card(CardDefinition('k52.watch','Original attack observer',CardType.MINION,health=8,metadata=META,triggers=(TriggerSpec(event,'k52.watch'),)))
    return r

class BeastTriggerNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),other=(),active=1,mode=None):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('test.hero',hand=other,board=enemy,deck=(PLAIN,)*8,mana=60,max_mana=60,mana_cap=60)),active_player=active,seed=1052),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='board'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        e=self.entity(g,cid,p,'hand');g.apply(PlayCard(p,e.id,target));return e.id
    def hero(self,g,p=1):s=g.state;return s.entities[s.players[p].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        s=g.snapshot();other=Game.from_snapshot(s,registry(mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),s);return other
    def attacks(self,g):return g.state.character_attack_history
    def test_complete_four_printed_faces_and_native_metadata(self):
        data=load_batch();self.assertEqual(len(data['cards']),4)
        for row in data['cards']:
            raw=row['record'];c=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(self.r.card(PAT).metadata.tribes,('beast','mech'))
    def test_all_four_real_cards_pay_their_native_three_cost(self):
        for cid in(BASHER,PAT,THRESHER,TUNNEL):
            g=self.game((cid,));self.play(g,cid);self.assertEqual(g.state.players[1].mana,57)
    def test_patriarch_is_inactive_for_the_first_two_actual_owner_starts(self):
        g=self.game((PAT,));source=self.play(g,PAT);self.assertFalse(g.state.entities[source].active)
        for _ in range(2):
            g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertFalse(g.state.entities[source].active)
        self.portable(g)
    def test_patriarch_wakes_on_third_owner_start_with_taunt_and_full_stats(self):
        g=self.game((PAT,));source=self.play(g,PAT)
        for _ in range(3):g.apply(EndTurn(1));g.apply(EndTurn(2))
        e=g.state.entities[source];self.assertTrue(e.active);self.assertEqual((e.attack,e.health),(3,12));self.assertIn(Keyword.TAUNT,e.keywords);self.portable(g)
    def test_dormant_taunt_does_not_block_an_enemy_hero_attack(self):
        g=self.game(board=(PAT,),enemy=('k52.target',),active=2);source=self.entity(g,'k52.target',2).id
        self.assertTrue(any(isinstance(a,Attack)and a.attacker_id==source and a.defender_id==self.hero(g).id for a in g.legal_actions()))
    def test_thresher_gains_shield_after_an_actual_own_spell(self):
        g=self.game(('k52.noop',),board=(THRESHER,));self.play(g,'k52.noop');self.assertIn(Keyword.DIVINE_SHIELD,self.entity(g,THRESHER).keywords);self.portable(g)
    def test_thresher_does_not_trigger_for_an_opponent_spell(self):
        g=self.game(board=(THRESHER,),other=('k52.noop',),active=2);self.play(g,'k52.noop',p=2);self.assertNotIn(Keyword.DIVINE_SHIELD,self.entity(g,THRESHER).keywords)
    def test_automatic_spell_from_a_minion_is_not_an_own_physical_spell_play(self):
        g=self.game(('k52.caster',),board=(THRESHER,));self.play(g,'k52.caster');self.assertTrue(g.state.cast_history)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.entity(g,THRESHER).keywords)
    def test_nested_effect_cast_does_not_add_an_extra_shield_grant(self):
        g=self.game(('k52.auto',),board=(THRESHER,));self.play(g,'k52.auto');target=self.entity(g,THRESHER).id
        self.assertEqual(sum(e.kind=='ability_granted'and e.target_id==target for e in g.events),1)
    def test_countered_manual_spell_does_not_grant_shield(self):
        g=self.game(('k52.noop',),board=(THRESHER,),other=('CORE_EX1_287',),active=2)
        self.play(g,'CORE_EX1_287',p=2);g.apply(EndTurn(2));self.play(g,'k52.noop');self.assertTrue(g.state.play_history[-1].countered)
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.entity(g,THRESHER).keywords)
    def test_two_spell_grants_do_not_create_two_consumable_shields(self):
        g=self.game(('k52.noop','k52.noop'),board=(THRESHER,),other=('k52.hit',));self.play(g,'k52.noop');self.play(g,'k52.noop')
        g.apply(EndTurn(1));target=self.entity(g,THRESHER).id;self.play(g,'k52.hit',target,p=2)
        self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords);self.assertEqual(g.state.entities[target].health,3)
    def test_silenced_thresher_does_not_receive_a_new_shield(self):
        g=self.game(('k52.silence','k52.noop'),board=(THRESHER,));self.play(g,'k52.silence',self.entity(g,THRESHER).id);self.play(g,'k52.noop')
        self.assertNotIn(Keyword.DIVINE_SHIELD,self.entity(g,THRESHER).keywords)
    def test_basher_gets_one_two_two_increment_for_five_armor(self):
        g=self.game(('k52.armor',),board=(BASHER,));self.play(g,'k52.armor');e=self.entity(g,BASHER)
        self.assertEqual((e.attack,e.max_health),(6,5));self.assertEqual(self.hero(g).armor,5);self.assertFalse(self.attacks(g))
    def test_zero_armor_does_not_buff_attack_or_consume_rng(self):
        g=self.game(('k52.zero',),board=(BASHER,),enemy=('k52.target',));before=g.snapshot()['rng_state'];self.play(g,'k52.zero')
        self.assertEqual(self.entity(g,BASHER).attack,4);self.assertEqual(g.snapshot()['rng_state'],before);self.assertFalse(self.attacks(g))
    def test_opponent_armor_does_not_trigger_your_basher(self):
        g=self.game(('k52.enemy_armor',),board=(BASHER,),enemy=('k52.target',));self.play(g,'k52.enemy_armor')
        self.assertEqual(self.entity(g,BASHER).attack,4);self.assertFalse(self.attacks(g))
    def test_actual_forced_attack_uses_the_new_six_attack_and_real_retaliation(self):
        g=self.game(('k52.armor',),board=(BASHER,),enemy=('k52.target',));self.play(g,'k52.armor')
        self.assertEqual((self.entity(g,BASHER).attack,self.entity(g,BASHER).health),(6,4))
        self.assertEqual(self.entity(g,'k52.target',2).health,24);self.assertTrue(self.attacks(g)[0].declaration.forced);self.portable(g)
    def test_two_separate_armor_notifications_buff_and_attack_twice(self):
        g=self.game(('k52.two',),board=(BASHER,),enemy=('k52.target',));self.play(g,'k52.two')
        self.assertEqual(self.entity(g,BASHER).attack,8);self.assertEqual(len(self.attacks(g)),2);self.assertEqual(self.entity(g,'k52.target',2).health,16)
    def test_enemy_turn_armor_can_force_the_original_controllers_minion_attack(self):
        g=self.game(board=(BASHER,),enemy=('k52.target',),other=('k52.enemy_armor',),active=2);self.play(g,'k52.enemy_armor',p=2)
        self.assertEqual(self.entity(g,BASHER).attack,6);self.assertEqual(len(self.attacks(g)),1)
    def test_frozen_and_newly_summoned_basher_use_the_existing_forced_policy(self):
        g=self.game((BASHER,'k52.freeze','k52.armor'),enemy=('k52.target',));source=self.play(g,BASHER);self.play(g,'k52.freeze',source);self.play(g,'k52.armor')
        self.assertEqual(len(self.attacks(g)),1);self.assertEqual(self.entity(g,'k52.target',2).health,24)
    def test_silenced_basher_has_no_armor_listener(self):
        g=self.game(('k52.silence','k52.armor'),board=(BASHER,),enemy=('k52.target',));self.play(g,'k52.silence',self.entity(g,BASHER).id);self.play(g,'k52.armor')
        self.assertEqual(self.entity(g,BASHER).attack,4);self.assertFalse(self.attacks(g))
    def test_no_enemy_minion_keeps_growth_without_rng_or_hero_attack(self):
        g=self.game(('k52.armor',),board=(BASHER,));before=g.snapshot()['rng_state'];self.play(g,'k52.armor')
        self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.hero(g,2).health,30)
    def test_new_enemy_created_during_growth_reaction_is_in_the_actual_pool(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),mode='new_enemy');self.play(g,'k52.armor')
        self.assertEqual(len(self.attacks(g)),1);self.assertEqual(self.entity(g,'k52.target',2).health,24)
    def test_growth_wait_preserves_original_random_attack_request_and_restore(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='buff_wait');self.play(g,'k52.armor')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'buff_wait');self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_source_return_and_same_id_reentry_cannot_borrow_the_original_attack(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='source_reentry');source=self.entity(g,BASHER).id
        self.play(g,'k52.armor');self.choose(g);self.assertEqual(self.entity(g,BASHER).id,source);self.assertFalse(self.attacks(g));self.portable(g,'source_reentry')
    def test_source_transfer_invalidates_the_original_players_attack(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='source_transfer');self.play(g,'k52.armor');self.choose(g)
        self.assertEqual(self.entity(g,BASHER,2).attack,6);self.assertFalse(self.attacks(g))
    def test_random_target_wait_does_not_redraw_after_restore(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target','k52.hard'),mode='random_wait');self.play(g,'k52.armor')
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'random_wait');before=g.snapshot()['rng_state'];self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.snapshot()['rng_state'],before)
    def test_selected_defender_return_and_reentry_is_not_retargeted(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='target_reentry');self.play(g,'k52.armor');self.choose(g)
        self.assertFalse(self.attacks(g));self.assertEqual(self.entity(g,'k52.target',2).health,30);self.portable(g,'target_reentry')
    def test_bad_pending_choice_restores_original_wait_and_rng(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='random_wait');self.play(g,'k52.armor');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
    def test_bound_random_request_codec_accepts_only_real_allocated_residence(self):
        g=self.game(board=(BASHER,));ref=BoardPresenceReference.capture(g.state,self.entity(g,BASHER).id)
        effect=AttackRandomEnemyMinion(ref,1,ref.entity_id);codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(effect)),effect)
        with self.assertRaises(ValueError):codec.encode(replace(effect,attacker=replace(ref,presence_id=g.state.next_order)))
        with self.assertRaises(ValueError):codec.encode(replace(effect,source_id=999999))
    def test_tunneler_has_native_stealth_and_attacking_hero_adds_two(self):
        g=self.game(board=(TUNNEL,));source=self.entity(g,TUNNEL).id;self.assertIn(Keyword.STEALTH,g.state.entities[source].keywords)
        g.apply(Attack(1,source,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,26);self.assertNotIn(Keyword.STEALTH,g.state.entities[source].keywords);self.portable(g)
    def test_tunneler_attacking_a_minion_still_damages_the_enemy_hero(self):
        g=self.game(board=(TUNNEL,),enemy=('k52.target',));g.apply(Attack(1,self.entity(g,TUNNEL).id,self.entity(g,'k52.target',2).id))
        self.assertEqual(self.hero(g,2).health,28)
    def test_tunneler_defending_does_not_count_as_its_attack(self):
        g=self.game(board=(TUNNEL,),enemy=('k52.target',));source=self.entity(g,TUNNEL).id;g.apply(Attack(1,source,self.hero(g,2).id));g.apply(EndTurn(1))
        g.apply(Attack(2,self.entity(g,'k52.target',2).id,source));self.assertEqual(self.hero(g,2).health,26)
    def test_fatal_tunneler_attack_has_no_new_live_source_followup(self):
        g=self.game(board=(TUNNEL,),enemy=('k52.hard',));source=self.entity(g,TUNNEL).id;g.apply(Attack(1,source,self.entity(g,'k52.hard',2).id))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hero(g,2).health,30)
    def test_forced_tunneler_attack_is_a_real_attack_and_ability_is_not_spell_damage(self):
        g=self.game((TUNNEL,'k52.force'),board=('k52.power',));self.play(g,TUNNEL);self.play(g,'k52.force')
        self.assertEqual(self.hero(g,2).health,26);self.assertTrue(self.attacks(g)[0].declaration.forced)
    def test_silenced_tunneler_keeps_only_ordinary_combat_damage(self):
        g=self.game(('k52.silence',),board=(TUNNEL,));source=self.entity(g,TUNNEL).id;self.play(g,'k52.silence',source);g.apply(Attack(1,source,self.hero(g,2).id))
        self.assertEqual(self.hero(g,2).health,28)
    def test_player_observation_excludes_private_residence_and_work_queue(self):
        g=self.game(('k52.armor',),board=(BASHER,'k52.watch'),enemy=('k52.target',),mode='buff_wait');self.play(g,'k52.armor')
        for p in(1,2):
            dto=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            for key in('AttackRandomEnemyMinion','presence_id','resolution_frame','rng_state'):self.assertNotIn(key,dto)

if __name__=='__main__':unittest.main()
