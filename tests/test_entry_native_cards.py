"""Real hand-play identity, actual entry growth and a complete named family."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.entry_native_cards import FEL_BEASTS,load_batch
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,
    PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec,UseHandAction)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import CostSpec,TribeChangeSpec,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.targets import canonical_digest

SCOUT='CATA_552';FORM='CATA_552t';PARASITE='JAIL_721';MAW='TLC_479';DRAGON='CORE_NEW1_023';PLAIN='CORE_CS2_182'
def meta(tribes=()):return CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=tribes,factions=(),subtypes=())

def registry(mode=None):
    r=build_registry()
    def held(c,cid):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
    def change(c,cid,tribes):return(ChangeMinionTribes(CardReference.capture(held(c,cid)),TribeChangeSpec('set',tribes),c.source_id),)
    def copying(c):return(CopyCard(CardReference.capture(held(c,FORM)),c.player_id,Zone.HAND,source_id=c.source_id),)
    scripts=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        steal=lambda c:(ChangeControl(c.target_id,3-c.player_id),),back=lambda c:(ReturnToHand(c.target_id),),
        summon_dragon=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(DRAGON),),SummonCause.capture(c)),),
        summon_demon=lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(FEL_BEASTS[0]),),SummonCause.capture(c)),),
        hand_dragon=lambda c:change(c,PLAIN,('dragon',)),remove_dragon=lambda c:change(c,DRAGON,()),
        hand_demon=lambda c:change(c,PLAIN,('demon',)),remove_demon=lambda c:change(c,FEL_BEASTS[0],('beast',)),
        cost=lambda c:(ModifyStoredCost(CardReference.capture(held(c,SCOUT)),CostSpec(delta=-2),c.source_id),),
        copy=copying,fail=lambda c:(AddToHand(c.player_id,'missing.k51',c.source_id),),
        gift=lambda c:(AddToHand(c.player_id,SCOUT,c.source_id),),
        dragon_to_plain=lambda c:(Transform(c.source_id,PLAIN),),plain_to_dragon=lambda c:(Transform(c.source_id,DRAGON),))
    for name,body in scripts.items():
        key='k51.'+name;r.register_behavior(key,body)
        if name not in('fail','gift','dragon_to_plain','plain_to_dragon'):
            r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,requires_target=name in('kill','silence','steal','back'),metadata=meta()))
    for name,tribes,battlecry in [('gift_dragon',('dragon',),'gift'),('changing_dragon',('dragon',),'dragon_to_plain'),('changing_plain',(),'plain_to_dragon')]:
        r.register_card(CardDefinition('k51.'+name,name,CardType.MINION,attack=1,health=2,metadata=meta(tribes),battlecry='k51.'+battlecry))
    r.register_card(CardDefinition('k51.unknown','Unknown tribe fixture',CardType.MINION,attack=1,health=2,metadata=meta(None)))
    r.register_card(CardDefinition('k51.power','Spell power fixture',CardType.MINION,health=5,spell_damage=5,metadata=meta()))
    if mode:
        def watch(c):
            target=c.state.entities[c.event.target_id]
            if mode=='upgrade':
                if target.card_id!=FORM:return ()
                effects=(GainArmor(c.player_id,1),)
            elif mode=='grow_before':
                if target.card_id not in FEL_BEASTS:return ()
                return(Buff(target.id,10,10,c.source_id),)
            elif mode=='bounce_source':
                if target.card_id not in FEL_BEASTS:return ()
                source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PARASITE)
                return(ReturnToHand(source.id),)
            else:
                if target.card_id not in FEL_BEASTS:return ()
                effects=(GainArmor(c.player_id,1),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
                ChoiceOption('bad','Rollback',(InvokeBehavior('k51.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k51.watch',watch)
        r.register_card(CardDefinition('k51.watch','Original event observer',CardType.MINION,health=10,metadata=meta(),
            triggers=(TriggerSpec('hand_card_upgraded'if mode=='upgrade'else'minion_summoned','k51.watch'),)))
    return r

class EntryNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy=(),other=(),deck=(PLAIN,)*5,active=1,mode=None,seed=1051):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('test.hero',hand=other,board=enemy,deck=(PLAIN,)*5,mana=60,max_mana=60,mana_cap=60)),active_player=active,seed=seed),registry(mode)if mode else self.r)
    def entity(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(s.entities[i]for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,target=None,p=1):
        e=self.entity(g,cid,p);g.apply(PlayCard(p,e.id,target));return e.id
    def hero(self,g,p=1):s=g.state;return s.entities[s.players[p].hero_id]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g,mode=None):
        s=g.snapshot();other=Game.from_snapshot(s,registry(mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),s);return other
    def test_complete_three_roots_and_four_dependencies(self):
        data=load_batch();self.assertEqual(len(data['cards']),7);self.assertEqual(sum(x['recipe']['root']for x in data['cards']),3)
        for x in data['cards']:
            raw=x['record'];c=self.r.card(raw['id']);self.assertEqual(canonical_digest(raw),x['record_sha256'])
            self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']))
    def test_all_three_fel_beasts_keep_both_beast_and_demon_types(self):
        self.assertTrue(all(self.r.card(cid).metadata.tribes==('beast','demon')for cid in FEL_BEASTS))
    def test_basic_scout_pays_six_and_deals_its_four_attack(self):
        g=self.game((SCOUT,));source=self.play(g,SCOUT,self.hero(g,2).id)
        self.assertEqual((g.state.players[1].mana,self.hero(g,2).health),(54,26));self.assertEqual(g.state.entities[source].attack,4)
    def test_actual_own_dragon_play_upgrades_same_original_hand_entity(self):
        g=self.game((SCOUT,DRAGON));original=self.entity(g,SCOUT).id;self.play(g,DRAGON)
        e=self.entity(g,FORM);self.assertEqual((e.id,e.attack,e.max_health),(original,8,8));self.portable(g)
    def test_formed_scout_deals_eight(self):
        g=self.game((SCOUT,DRAGON));self.play(g,DRAGON);self.play(g,FORM,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,22)
    def test_non_dragon_play_does_not_upgrade(self):
        g=self.game((SCOUT,PLAIN));self.play(g,PLAIN);self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_opponent_dragon_play_does_not_upgrade_your_hand(self):
        g=self.game((SCOUT,),other=(DRAGON,),active=2);self.play(g,DRAGON,p=2);self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_direct_dragon_summon_is_not_a_dragon_hand_play(self):
        g=self.game((SCOUT,'k51.summon_dragon'));self.play(g,'k51.summon_dragon');self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_scout_in_deck_does_not_listen_to_hand_play(self):
        g=self.game((DRAGON,),deck=(SCOUT,));self.play(g,DRAGON);self.assertEqual(self.entity(g,SCOUT,zone='deck').attack,4)
    def test_dragon_battlecry_new_scout_does_not_retroactively_upgrade(self):
        g=self.game(('k51.gift_dragon',));self.play(g,'k51.gift_dragon');self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_original_dragon_identity_survives_its_later_battlecry_transformation(self):
        g=self.game((SCOUT,'k51.changing_dragon'));self.play(g,'k51.changing_dragon');self.assertEqual(self.entity(g,FORM).attack,8)
    def test_non_dragon_later_transformed_to_dragon_does_not_qualify(self):
        g=self.game((SCOUT,'k51.changing_plain'));self.play(g,'k51.changing_plain');self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_submitted_hand_tribe_enchantment_can_qualify_as_a_dragon(self):
        g=self.game((SCOUT,PLAIN,'k51.hand_dragon'));self.play(g,'k51.hand_dragon');self.play(g,PLAIN);self.assertEqual(self.entity(g,FORM).attack,8)
    def test_removed_submitted_dragon_type_does_not_qualify(self):
        g=self.game((SCOUT,DRAGON,'k51.remove_dragon'));self.play(g,'k51.remove_dragon');self.play(g,DRAGON);self.assertEqual(self.entity(g,SCOUT).attack,4)
    def test_form_upgrade_preserves_ordinary_local_cost_modifier(self):
        g=self.game((SCOUT,DRAGON,'k51.cost'));self.play(g,'k51.cost');self.play(g,DRAGON);before=g.state.players[1].mana
        self.play(g,FORM,self.hero(g,2).id);self.assertEqual(g.state.players[1].mana,before-4)
    def test_current_copy_of_actual_dragon_form_stays_eight_eight(self):
        g=self.game((SCOUT,DRAGON,'k51.copy'));self.play(g,DRAGON);self.play(g,'k51.copy')
        s=g.state;self.assertEqual(sum(s.entities[i].card_id==FORM and s.entities[i].attack==8 for i in s.players[1].hand),2)
    def test_current_attack_aura_changes_battlecry_but_spell_power_does_not(self):
        g=self.game((SCOUT,),board=('CORE_CS2_122','k51.power'));self.play(g,SCOUT,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,25)
    def test_unknown_submitted_tribe_rolls_back_without_a_blank_assumption(self):
        g=self.game((SCOUT,'k51.unknown'));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'k51.unknown')
        self.assertEqual(g.snapshot(),saved)
    def test_actual_hand_upgrade_wait_restores_clone_and_replay(self):
        g=self.game((SCOUT,DRAGON),board=('k51.watch',),mode='upgrade');self.play(g,DRAGON)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'upgrade');self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_failed_upgrade_choice_restores_wait_boundary_and_rng(self):
        g=self.game((SCOUT,DRAGON),board=('k51.watch',),mode='upgrade');self.play(g,DRAGON);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
    def test_parasite_pays_six_has_rush_and_a_real_prepare_action(self):
        g=self.game((PARASITE,));source=self.play(g,PARASITE);self.assertEqual(g.state.players[1].mana,54)
        self.assertIn(Keyword.RUSH,g.state.entities[source].keywords);self.assertEqual(self.r.card(PARASITE).hand_actions[0].kind,'prepare')
    def test_real_prepare_uses_existing_investment_lock_and_next_turn_payment(self):
        g=self.game((PARASITE,));source=self.entity(g,PARASITE).id;g.apply(UseHandAction(1,source,'prepare'))
        self.assertEqual(g.state.entities[source].preparation.mana_spent,5)
        with self.assertRaises(IllegalAction):self.play(g,PARASITE)
        with self.assertRaises(IllegalAction):g.apply(UseHandAction(1,source,'prepare'))
        self.portable(g);g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.state.players[1].mana;self.play(g,PARASITE)
        self.assertEqual(g.state.players[1].mana,before)
    def test_actual_hybrid_demon_play_adds_its_printed_stats(self):
        g=self.game((FEL_BEASTS[0],),board=(PARASITE,));self.play(g,FEL_BEASTS[0]);e=self.entity(g,PARASITE,zone='board')
        self.assertEqual((e.attack,e.max_health),(8,6));self.portable(g)
    def test_direct_demon_summon_also_counts_without_a_hand_play(self):
        g=self.game(('k51.summon_demon',),board=(PARASITE,));self.play(g,'k51.summon_demon')
        self.assertEqual(self.entity(g,PARASITE,zone='board').attack,8)
    def test_opponent_demon_summon_does_not_buff_your_parasite(self):
        g=self.game(board=(PARASITE,),other=(FEL_BEASTS[0],),active=2);self.play(g,FEL_BEASTS[0],p=2)
        self.assertEqual(self.entity(g,PARASITE,zone='board').attack,3)
    def test_non_demon_actual_summon_does_not_buff(self):
        g=self.game((PLAIN,),board=(PARASITE,));self.play(g,PLAIN);self.assertEqual(self.entity(g,PARASITE,zone='board').attack,3)
    def test_current_demon_tribe_at_entry_is_used(self):
        g=self.game((PLAIN,'k51.hand_demon'),board=(PARASITE,));self.play(g,'k51.hand_demon');self.play(g,PLAIN)
        e=self.entity(g,PARASITE,zone='board');self.assertEqual((e.attack,e.max_health),(7,8))
    def test_removed_demon_type_at_entry_does_not_qualify(self):
        g=self.game((FEL_BEASTS[0],'k51.remove_demon'),board=(PARASITE,));self.play(g,'k51.remove_demon');self.play(g,FEL_BEASTS[0])
        self.assertEqual(self.entity(g,PARASITE,zone='board').attack,3)
    def test_original_entry_stats_do_not_read_a_later_reaction_buff(self):
        g=self.game((FEL_BEASTS[0],),board=('k51.watch',PARASITE),mode='grow_before');self.play(g,FEL_BEASTS[0])
        self.assertEqual(self.entity(g,PARASITE,zone='board').attack,8);self.assertEqual(self.entity(g,FEL_BEASTS[0],zone='board').attack,15)
    def test_departed_source_cannot_buff_its_new_hand_residence(self):
        g=self.game((FEL_BEASTS[0],),board=('k51.watch',PARASITE),mode='bounce_source');self.play(g,FEL_BEASTS[0])
        self.assertEqual(self.entity(g,PARASITE).attack,3)
    def test_silenced_parasite_has_no_growth_trigger(self):
        g=self.game((FEL_BEASTS[0],'k51.silence'),board=(PARASITE,));self.play(g,'k51.silence',self.entity(g,PARASITE,zone='board').id)
        self.play(g,FEL_BEASTS[0]);self.assertEqual(self.entity(g,PARASITE,zone='board').attack,3)
    def test_maw_death_keeps_complete_family_and_original_summon_source(self):
        g=self.game(('k51.kill',),board=(MAW,));source=self.entity(g,MAW,zone='board').id;self.play(g,'k51.kill',source)
        row=g.state.card_summon_history[-1];self.assertEqual(tuple(x.card_id for x in row.request.materials),FEL_BEASTS)
        self.assertEqual(row.request.cause.source.entity_id,source);self.assertEqual(len(row.deliveries),1);self.portable(g)
    def test_all_three_explicit_fel_beasts_are_reachable(self):
        seen=set()
        for seed in range(12):
            g=self.game(('k51.kill',),board=(MAW,),seed=seed);self.play(g,'k51.kill',self.entity(g,MAW,zone='board').id)
            seen.add(g.state.card_summon_history[-1].request.materials[g.state.card_summon_history[-1].selected].card_id)
        self.assertEqual(seen,set(FEL_BEASTS))
    def test_real_maw_demon_delivery_triggers_real_parasite(self):
        g=self.game(('k51.kill',),board=(PARASITE,MAW));self.play(g,'k51.kill',self.entity(g,MAW,zone='board').id)
        s=g.state;demon=next(s.entities[i]for i in s.players[1].board if s.entities[i].card_id in FEL_BEASTS);p=self.entity(g,PARASITE,zone='board')
        self.assertEqual((p.attack,p.max_health),(3+demon.attack,3+demon.max_health))
    def test_felhorn_reborn_is_the_existing_one_health_new_entity(self):
        g=self.game(('k51.kill',),board=(FEL_BEASTS[2],));old=self.entity(g,FEL_BEASTS[2],zone='board').id;self.play(g,'k51.kill',old)
        new=self.entity(g,FEL_BEASTS[2],zone='board');self.assertNotEqual(new.id,old);self.assertEqual(new.health,1);self.assertNotIn(Keyword.REBORN,new.keywords)
    def test_felraptor_has_charge_and_cannot_be_targeted_by_a_spell(self):
        g=self.game((FEL_BEASTS[1],'k51.kill'));source=self.play(g,FEL_BEASTS[1])
        self.assertTrue(any(isinstance(a,Attack)and a.attacker_id==source and a.defender_id==self.hero(g,2).id for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):self.play(g,'k51.kill',source)
    def test_actual_maw_summon_choice_restores_the_original_selected_family(self):
        g=self.game(('k51.kill',),board=(MAW,'k51.watch'),mode='summon');self.play(g,'k51.kill',self.entity(g,MAW,zone='board').id)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'summon');self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
    def test_opponent_cannot_see_hidden_scout_form_upgrade(self):
        g=self.game((SCOUT,DRAGON));self.play(g,DRAGON)
        self.assertNotIn(FORM,json.dumps(g.for_player(2).observe(),ensure_ascii=False))

if __name__=='__main__':unittest.main()
