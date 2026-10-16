"""Real printed providers and whole-group rewards use original physical bodies."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.cards.summon_beneficiary_cards import load_batch
from hs_sim.engine import CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerSpec
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,CopyMinion,Destroy,GainArmor,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Transform
from hs_sim.engine.errors import ResolutionError,SnapshotError
from hs_sim.engine.group_bonus import GroupBonusFact
from hs_sim.engine.model import SummonQuantitySpec,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

HUSK='EDR_810';LEECH='EDR_810t';TYR='TLC_240';FISH='TLC_240t';PLAIN='CORE_CS2_182'

def registry(mode=None):
    r=build_registry()
    scripts=dict(kill=lambda c:(Destroy(c.target_id,c.source_id),),silence=lambda c:(Silence(c.target_id),),
        steal=lambda c:(ChangeControl(c.target_id,3-c.player_id),),transform=lambda c:(Transform(c.target_id,PLAIN),),
        copy=lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        fail=lambda c:(AddToHand(c.player_id,'missing.k50',c.source_id),),
        reenter=lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),))
    for name,body in scripts.items():
        key='k50.'+name;r.register_behavior(key,body)
        if name not in('fail','reenter'):r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,requires_target=True))
    r.register_card(CardDefinition('k50.double','Summon quantity provider',CardType.MINION,health=8,summon_quantities=(SummonQuantitySpec(),)))
    if mode:
        def watch(c):
            if not c.state.ordered_group_history:return ()
            group=c.state.ordered_group_history[-1]
            if mode=='bonus':
                if len(group.bonus_receipts)!=1 or c.event.target_id!=group.bonus_receipts[0].beneficiary.entity_id:return ()
                effects=(GainArmor(1,1),)
            else:
                count=sum(x.card_id==FISH for x in c.state.successful_summon_history)
                if c.state.entities[c.event.target_id].card_id!=FISH or count!=1:return ()
                effects=(ReturnToHand(c.event.target_id),InvokeBehavior('k50.reenter',c.source_id,c.player_id,c.event.target_id))if mode=='reenter'else(GainArmor(1,1),)
            return(RequestChoice(c.player_id,(ChoiceOption('ok','Continue',effects),
                ChoiceOption('bad','Roll back',(InvokeBehavior('k50.fail',c.source_id,c.player_id),))),c.source_id),)
        r.register_behavior('k50.watch',watch)
        r.register_card(CardDefinition('k50.watch','Original group observer',CardType.MINION,health=8,
            triggers=(TriggerSpec('ability_granted'if mode=='bonus'else'minion_summoned','k50.watch'),)))
    return r

class SummonBeneficiaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.registry=registry()
    def game(self,hand=(),*,board=(),enemy=(PLAIN,),mode=None,active=1,seed=1050):
        return Game.from_scenario(Scenario((PlayerSetup('test.hero',hand=hand,board=board,deck=(PLAIN,)*6,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('test.hero',board=enemy,deck=(PLAIN,)*6,hand=('k50.kill',),mana=40,max_mana=40,mana_cap=40)),active_player=active,seed=seed),registry(mode)if mode else self.registry)
    def play(self,g,cid,target=None,player=1):
        s=g.state;eid=next(i for i in s.players[player].hand if s.entities[i].card_id==cid)
        g.apply(PlayCard(player,eid,target));return eid
    def hero(self,g,p=1):s=g.state;return s.entities[s.players[p].hero_id]
    def bodies(self,g,cid,p=1):s=g.state;return[e for i in s.players[p].board for e in(s.entities[i],)if e.card_id==cid]
    def choose(self,g,option='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g,mode=None):
        s=g.snapshot();other=Game.from_snapshot(s,registry(mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(mode)).snapshot(),s);return other
    def kill_tyr(self,g):return self.play(g,'k50.kill',self.bodies(g,TYR)[0].id)
    def test_complete_source_faces_dependencies_and_runes(self):
        data=load_batch();self.assertEqual(sum(x['recipe']['root']for x in data['cards']),2)
        for row in data['cards']:
            raw=row['record'];card=self.registry.card(raw['id']);self.assertEqual(canonical_digest(raw),row['record_sha256'])
            self.assertEqual((card.cost,card.attack,card.health),(raw['cost'],raw['attack'],raw['health']))
        self.assertEqual(self.registry.card(FISH).metadata.tribes,('murloc',))
        self.assertEqual(self.registry.card(HUSK).metadata.runes.blood,1)
    def test_real_husk_pays_six_and_summons_two_real_leeches(self):
        g=self.game((HUSK,));source=self.play(g,HUSK)
        self.assertEqual(g.state.players[1].mana,34);self.assertEqual([(e.attack,e.health)for e in self.bodies(g,LEECH)],[(0,2)]*2)
        self.assertTrue(all(x.request.cause.source.entity_id==source for x in g.state.card_summon_history));self.portable(g)
    def test_husk_battlecry_respects_actual_one_free_slot(self):
        g=self.game((HUSK,),board=(PLAIN,)*5);self.play(g,HUSK);self.assertEqual(len(self.bodies(g,LEECH)),1)
    def test_single_husk_increases_both_actual_leech_bodies(self):
        g=self.game((HUSK,));self.play(g,HUSK);g.apply(EndTurn(1));self.assertEqual(self.hero(g).max_health,34)
        self.assertEqual(self.bodies(g,PLAIN,2)[0].health,1);self.portable(g)
    def test_two_current_friendly_providers_stack(self):
        g=self.game(board=(HUSK,HUSK,LEECH));g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,33)
    def test_enemy_provider_does_not_increase_your_leeches(self):
        g=self.game(board=(LEECH,),enemy=(HUSK,));g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,31)
    def test_silence_removes_only_the_continuous_extra_amount(self):
        g=self.game(('k50.silence',),board=(HUSK,LEECH));self.play(g,'k50.silence',self.bodies(g,HUSK)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,31)
    def test_dead_husk_no_longer_supplies_extra_amount(self):
        g=self.game(('k50.kill',),board=(HUSK,LEECH));self.play(g,'k50.kill',self.bodies(g,HUSK)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,31)
    def test_transformed_provider_no_longer_supplies_extra_amount(self):
        g=self.game(('k50.transform',),board=(HUSK,LEECH));self.play(g,'k50.transform',self.bodies(g,HUSK)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,31)
    def test_transferred_provider_follows_current_controller(self):
        g=self.game(('k50.steal',),board=(HUSK,LEECH),enemy=(LEECH,));self.play(g,'k50.steal',self.bodies(g,HUSK)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,31)
        before=self.hero(g,2).max_health;g.apply(EndTurn(2));self.assertEqual(self.hero(g,2).max_health,before+2)
    def test_existing_current_copy_of_provider_supplies_another_increment(self):
        g=self.game(('k50.copy',),board=(HUSK,LEECH));self.play(g,'k50.copy',self.bodies(g,HUSK)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,33)
    def test_silenced_leech_has_no_end_trigger(self):
        g=self.game(('k50.silence',),board=(HUSK,LEECH));self.play(g,'k50.silence',self.bodies(g,LEECH)[0].id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g).health,30)
    def test_tyrannogill_pays_and_retains_native_rush(self):
        g=self.game((TYR,));eid=self.play(g,TYR);self.assertEqual(g.state.players[1].mana,34)
        self.assertIn(Keyword.RUSH,g.state.entities[eid].keywords)
    def test_real_death_summons_three_then_rewards_only_original_bodies(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g);fish=self.bodies(g,FISH)
        self.assertEqual([(e.attack,e.max_health)for e in fish],[(2,1)]*3);self.assertTrue(all(len(e.keywords)==1 for e in fish))
        root=g.state.ordered_group_history[-1];self.assertEqual((root.status,len(root.entry_root_ids),len(root.bonus_receipts)),('completed',3,3))
        self.assertEqual([f.beneficiary.entity_id for f in root.bonus_receipts],[e.id for e in fish])
        summons=[e.sequence for e in g.events if e.kind=='minion_summoned'];grants=[e.sequence for e in g.events if e.kind=='ability_granted']
        self.assertLess(max(summons),min(grants));self.portable(g)
    def test_plain_dinoloc_is_not_given_an_invented_bonus(self):
        g=self.game((FISH,));self.play(g,FISH);self.assertEqual(self.bodies(g,FISH)[0].keywords,set())
    def test_one_free_death_slot_rewards_one_success_not_three_attempts(self):
        g=self.game(('k50.kill',),board=(TYR,)+(PLAIN,)*6);self.kill_tyr(g)
        self.assertEqual(len(self.bodies(g,FISH)),1);self.assertEqual(len(g.state.ordered_group_history[-1].bonus_receipts),1)
    def test_opponent_turn_uses_shared_bonus_pool_without_rush(self):
        g=self.game(board=(TYR,),active=2);self.play(g,'k50.kill',self.bodies(g,TYR)[0].id,2)
        self.assertTrue(all(Keyword.RUSH not in f.candidates for f in g.state.ordered_group_history[-1].bonus_receipts))
    def test_owner_turn_uses_shared_bonus_pool_including_new_minion_rush(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g)
        self.assertTrue(all(Keyword.RUSH in f.candidates for f in g.state.ordered_group_history[-1].bonus_receipts))
    def test_existing_quantity_plan_rewards_each_actual_extra_body(self):
        g=self.game(('k50.kill',),board=('k50.double',TYR));self.kill_tyr(g)
        self.assertEqual(len(self.bodies(g,FISH)),6);self.assertEqual(len(g.state.ordered_group_history[-1].bonus_receipts),6);self.portable(g)
    def test_first_summon_choice_restores_complete_owed_group_and_rewards(self):
        g=self.game(('k50.kill',),board=(TYR,'k50.watch'),mode='summon');self.kill_tyr(g)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g,'summon')
        self.choose(g);self.choose(other);self.assertEqual(other.snapshot(),g.snapshot());self.assertEqual(len(g.state.ordered_group_history[-1].bonus_receipts),3)
    def test_reentered_same_id_is_not_the_original_bonus_beneficiary(self):
        g=self.game(('k50.kill',),board=(TYR,'k50.watch'),mode='reenter');self.kill_tyr(g)
        first=self.bodies(g,FISH)[0].id;self.choose(g);root=g.state.ordered_group_history[-1]
        self.assertEqual(root.bonus_receipts[0].outcome,'stale');self.assertEqual(g.state.entities[first].keywords,set())
        self.assertEqual(sum(bool(e.keywords)for e in self.bodies(g,FISH)),2);self.portable(g,'reenter')
    def test_bonus_reaction_wait_keeps_original_pick_and_exact_remaining_rewards(self):
        g=self.game(('k50.kill',),board=(TYR,'k50.watch'),mode='bonus');self.kill_tyr(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.ordered_group_history[-1].bonus_receipts),1)
        other=self.portable(g,'bonus');self.choose(g);self.choose(other);self.assertEqual(other.snapshot(),g.snapshot());self.portable(g,'bonus')
    def test_bad_bonus_choice_rolls_back_wait_boundary_and_rng(self):
        g=self.game(('k50.kill',),board=(TYR,'k50.watch'),mode='bonus');self.kill_tyr(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
    def test_saved_reward_prefix_cannot_be_deleted_while_original_events_remain(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g);saved=deepcopy(g.snapshot())
        saved['state']['ordered_group_history'][-1]['bonus_receipts']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_saved_original_beneficiary_order_cannot_be_reversed(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g);saved=deepcopy(g.snapshot())
        saved['state']['ordered_group_history'][-1]['bonus_receipts'].reverse()
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())
    def test_saved_bonus_rng_cannot_be_replaced(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g);fact=g.state.ordered_group_history[-1].bonus_receipts[0]
        with self.assertRaises(ValueError):replace(fact,selected=None)
        with self.assertRaises(ValueError):replace(fact,selected=fact.selected.value)
    def test_player_projections_do_not_include_private_group_receipts(self):
        g=self.game(('k50.kill',),board=(TYR,));self.kill_tyr(g)
        for p in(1,2):
            dto=json.dumps(g.for_player(p).observe(),ensure_ascii=False)
            for key in('bonus_receipts','rng_before','next_ordered_group_id','ordered_group_history'):self.assertNotIn(key,dto)
    def test_husk_hero_theft_does_not_become_damage_or_healing(self):
        g=self.game(board=(HUSK,LEECH),enemy=());g.apply(EndTurn(1));self.assertEqual(self.hero(g).max_health,32)
        self.assertFalse(any(x.health_result.source_card_id==LEECH for x in g.state.damage_history))

if __name__=='__main__':unittest.main()
