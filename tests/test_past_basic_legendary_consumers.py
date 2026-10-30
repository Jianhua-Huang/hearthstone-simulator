"""Actual ten legendary consumers and their necessary public contracts."""
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from tools import card_batch as cb
from hs_sim.cards import past_basic_legendary_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import ChoiceOption,Damage,Destroy,GainArmor,InvokeBehavior,RandomDamage,RequestChoice,Silence
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.local_pool_format import build_cn37_local_pool_format

SOG,OCTO,KATH,MOSH,ANO,MUKLA,HUHU,VOL,RHY,SHAW=native.ROOTS;BANANA=native.BANANA
P='k699.';A=P+'a';B=P+'b';BEAST=P+'beast';BEAST2=P+'beast2';POWER=P+'power';MIRROR='EX1_294'
KILL=P+'kill';HIT=P+'hit';HUSH=P+'hush';SECRET=P+'secret';FAIL=P+'fail';WATCH=P+'watch'
DRAW_WATCH=P+'draw_watch';STATS_WATCH=P+'stats_watch';SECRET_WATCH=P+'secret_watch';DAMAGE_WATCH=P+'damage_watch'
HELPERS=(A,B,BEAST,BEAST2,POWER,KILL,HIT,HUSH,SECRET,DRAW_WATCH,STATS_WATCH,SECRET_WATCH,DAMAGE_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,tribes,bonus in((A,(),0),(B,(),0),(BEAST,('beast',),0),(BEAST2,('beast',),0),(POWER,(),5)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=20,spell_damage=bonus,
            battlecry=P+'beast_bc'if cid==BEAST else None,metadata=replace(meta,tribes=tribes)))
    r.register_behavior(P+'beast_bc',lambda c:(GainArmor(c.player_id,10),))
    for cid,body in((KILL,lambda c:(Destroy(c.target_id,c.source_id),)),(HIT,lambda c:(Damage(c.target_id,1,c.source_id),)),
            (HUSH,lambda c:(Silence(c.target_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=meta,
            targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_secret_condition(SECRET,lambda c:True);r.register_behavior(SECRET,lambda c:(GainArmor(c.player_id,1),))
    r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,cost=1,metadata=meta,keywords=(Keyword.SECRET,),
        secret=SecretSpec(SECRET,('turn_ended',),SECRET,SECRET,turn='owner')))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K699 deliberate original continuation failure')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id)
        if source is None or source.card_id not in(OCTO,ANO,VOL,SECRET):return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail after random work',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((DRAW_WATCH,'card_drawn'),(STATS_WATCH,'stats_changed'),(SECRET_WATCH,'secret_revealed'),(DAMAGE_WATCH,'health_resolved')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=50,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k699-real-basic-legendary-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for key,body in full._secret_conditions.items():r.register_secret_condition(key,body)
    for cid in(BANANA,'TIME_013','HERO_08','HERO_08bp',MIRROR,*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_basic_legendary_consumers(r);r.validate();return r


class PastBasicLegendaryConsumerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*10,enemy_hand=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,
            mana_cap=30,hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*10,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=699,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault_atomic(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_ten_faces_banana_link_and_native_secret_profile(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['original_candidate_ids']),732);self.assertEqual(len(d['official_observations']),24)
        for row in d['cards']:self.assertEqual(cb.canonical(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        self.assertEqual(d['existing_dependencies'][0]['record']['dbf_id'],1694)
        self.assertEqual(r.native_secret_repeat_profiles[RHY].executions,2);self.assertFalse(d['complete_past_legendary_source_bound'])

    def test_all_ten_real_paid_entries_keep_printed_face_and_one_payment(self):
        for cid in native.ROOTS:
            g=self.game((cid,),deck=());source=self.play(g,cid);card=g.registry.card(cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.players[1].mana),(cid,30-card.cost))
            self.assertEqual(len(g.state.play_history),1)

    def test_soggoth_native_elusive_blocks_spell_arrow_and_taunt_blocks_enemy_face(self):
        g=self.game((HIT,),board=(SOG,),enemy=(A,));source=self.unit(g,SOG).id
        with self.assertRaises(IllegalAction):self.play(g,HIT,source)
        g.apply(EndTurn(1));enemy=self.unit(g,A,2).id
        with self.assertRaises(IllegalAction):g.apply(Attack(2,enemy,self.hero(g).id))
        g.apply(Attack(2,enemy,source));self.assertEqual(g.state.entities[source].health,7)

    def test_soggoth_remains_targetable_by_actual_minion_battlecry(self):
        g=self.game((VOL,),enemy=(SOG,));source=self.play(g,VOL,self.unit(g,SOG,2).id)
        self.assertEqual(g.state.entities[source].health,9);self.assertEqual(self.unit(g,SOG,2).health,2)

    def test_octosari_natural_death_draws_eight_original_cards(self):
        g=self.game((KILL,),board=(OCTO,),deck=(A,)*8);self.play(g,KILL,self.unit(g,OCTO).id)
        self.assertEqual(self.hand(g),[A]*8);self.assertEqual(g.state.players[1].deck,[]);self.assertEqual(len(g.state.draw_history),8);self.portable(g)

    def test_octosari_full_hand_and_fatigue_follow_normal_draw_contract(self):
        g=self.game((KILL,)+(A,)*9,board=(OCTO,),deck=(A,)*8);self.play(g,KILL,self.unit(g,OCTO).id)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual(len(g.state.draw_history),8)
        g=self.game((KILL,),board=(OCTO,),deck=(A,A));self.play(g,KILL,self.unit(g,OCTO).id)
        self.assertEqual(self.hero(g).health,9);self.assertEqual(self.hand(g),[A,A])

    def test_octosari_draw_wait_restores_original_eight_and_rolls_back_fault(self):
        g=self.game((KILL,),board=(OCTO,),deck=(A,)*8,watch=DRAW_WATCH);self.play(g,KILL,self.unit(g,OCTO).id)
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(self.hand(g),[A]*8);self.portable(g)

    def test_kathrena_paid_battlecry_and_natural_death_recruit_original_beasts(self):
        g=self.game((KATH,KILL),deck=(BEAST,A,BEAST2));original={i for i in g.state.players[1].deck if g.state.entities[i].card_id in(BEAST,BEAST2)}
        source=self.play(g,KATH);first=next(i for i in g.state.players[1].board if i!=source)
        self.play(g,KILL,source);self.assertEqual(set(g.state.players[1].board),original)
        self.assertEqual(g.state.players[1].board[-1],first);self.assertEqual(self.hero(g).armor,0)
        self.assertEqual(g.state.players[1].mana,21);self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_kathrena_empty_beast_pool_keeps_nonbeasts_and_rng(self):
        g=self.game((KATH,),deck=(A,A));before=g.snapshot()['rng_state'];self.play(g,KATH)
        self.assertEqual(len(g.state.players[1].deck),2);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_mosh_destroys_both_damaged_sides_and_keeps_healthy_minions(self):
        g=self.game((HIT,HIT,MOSH),board=(A,A),enemy=(B,));damaged=g.state.players[1].board[0];healthy=g.state.players[1].board[1];enemy=self.unit(g,B,2).id
        self.play(g,HIT,damaged);self.play(g,HIT,enemy);self.play(g,MOSH)
        self.assertEqual((g.state.entities[damaged].zone,g.state.entities[enemy].zone),(Zone.GRAVEYARD,Zone.GRAVEYARD))
        self.assertIn(healthy,g.state.players[1].board);self.assertEqual(self.board(g,2),[])

    def test_anomalus_natural_death_deals_eight_to_both_minion_sides_without_spell_bonus(self):
        g=self.game((KILL,),board=(ANO,A,POWER),enemy=(B,));self.play(g,KILL,self.unit(g,ANO).id)
        self.assertEqual((self.unit(g,A).health,self.unit(g,POWER).health,self.unit(g,B,2).health),(12,12,12))
        self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30));self.portable(g)

    def test_anomalus_health_wait_preserves_one_group_and_atomic_failure(self):
        g=self.game((KILL,),board=(ANO,A),enemy=(B,),watch=DAMAGE_WATCH);self.play(g,KILL,self.unit(g,ANO).id)
        g=self.portable(g);self.fault_atomic(g);self.finish(g)
        self.assertEqual((self.unit(g,A).health,self.unit(g,B,2).health),(12,12));self.portable(g)

    def test_mukla_two_actual_bananas_go_to_self_and_real_spell_buffs(self):
        g=self.game((MUKLA,),board=(A,));self.play(g,MUKLA);self.assertEqual(self.hand(g),[BANANA,BANANA]);self.assertEqual(self.hand(g,2),[])
        self.play(g,BANANA,self.unit(g,A).id);self.assertEqual((self.unit(g,A).attack,self.unit(g,A).health),(3,21))
        self.assertEqual(g.state.players[1].mana,23);self.portable(g)

    def test_mukla_ordinary_full_hand_overflow_keeps_one_free_slot(self):
        g=self.game((MUKLA,)+(A,)*9);self.play(g,MUKLA);self.assertEqual(len(self.hand(g)),10);self.assertEqual(self.hand(g).count(BANANA),1)

    def test_huhuran_activates_actual_friendly_deathrattle_without_killing_carrier(self):
        g=self.game((HUHU,),board=(OCTO,),deck=(A,)*8);source=self.unit(g,OCTO).id;self.play(g,HUHU,source)
        self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(self.hand(g),[A]*8)
        self.assertEqual(g.state.death_history,[]);self.portable(g)

    def test_huhuran_player_actions_use_only_public_deathrattle_presence(self):
        g=self.game((HUHU,),board=(OCTO,A));actions=g.for_player(1).legal_actions()
        self.assertIsNone(actions['error']);self.assertTrue(any('play'in a['type']for a in actions['actions']))
        visible=actions['observation']['players'][0]['board']
        self.assertEqual([x['has_deathrattle']for x in visible],[True,False])

    def test_huhuran_live_kathrena_recruits_right_of_original_carrier(self):
        g=self.game((HUHU,),board=(KATH,),deck=(BEAST,));self.play(g,HUHU,self.unit(g,KATH).id)
        self.assertEqual(self.board(g),[KATH,BEAST,HUHU]);self.assertEqual(self.hero(g).armor,0)

    def test_huhuran_rejects_enemy_or_silenced_deathrattle_and_has_optional_empty_target(self):
        g=self.game((HUHU,),enemy=(OCTO,))
        with self.assertRaises(IllegalAction):self.play(g,HUHU,self.unit(g,OCTO,2).id)
        self.play(g,HUHU);self.assertEqual(self.hand(g),[])
        g=self.game((HUSH,HUHU),board=(OCTO,));self.play(g,HUSH,self.unit(g,OCTO).id)
        with self.assertRaises(IllegalAction):self.play(g,HUHU,self.unit(g,OCTO).id)
        self.play(g,HUHU)

    def test_voljin_real_health_exchange_uses_remaining_health_and_preserves_attack(self):
        g=self.game((HIT,VOL),enemy=(B,));target=self.unit(g,B,2).id;self.play(g,HIT,target);source=self.play(g,VOL,target)
        self.assertEqual((g.state.entities[source].health,g.state.entities[source].attack),(19,6))
        self.assertEqual((g.state.entities[target].health,g.state.entities[target].attack),(2,2));self.portable(g)

    def test_voljin_stats_wait_observes_both_already_changed_and_recovers(self):
        g=self.game((VOL,),enemy=(B,),watch=STATS_WATCH);target=self.unit(g,B,2).id;source=self.play(g,VOL,target)
        self.assertEqual((g.state.entities[source].health,g.state.entities[target].health),(20,2))
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(g.state.entities[source].health,20)

    def test_rhyssa_real_native_profile_repeats_once_and_multiple_sources_do_not_multiply(self):
        for count in(1,2):
            g=self.game((SECRET,),board=(RHY,)*count);self.play(g,SECRET);g.apply(EndTurn(1));self.assertEqual(self.hero(g).armor,2)

    def test_rhyssa_silence_removes_native_contribution(self):
        g=self.game((HUSH,SECRET),board=(RHY,));self.play(g,HUSH,self.unit(g,RHY).id);self.play(g,SECRET);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).armor,1)

    def test_rhyssa_secret_wait_preserves_real_source_profile_and_original_extra(self):
        g=self.game((SECRET,),board=(RHY,),watch=SECRET_WATCH);self.play(g,SECRET);g.apply(EndTurn(1))
        g=self.portable(g);self.fault_atomic(g);self.finish(g);self.assertEqual(self.hero(g).armor,2);self.portable(g)

    def test_shaw_gives_other_current_and_new_friendly_minions_rush_but_not_self(self):
        g=self.game((A,),board=(SHAW,),enemy=(B,));source=self.unit(g,SHAW).id;other=self.play(g,A)
        self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords);self.assertIn(Keyword.RUSH,g.state.entities[other].keywords)
        with self.assertRaises(IllegalAction):g.apply(Attack(1,other,self.hero(g,2).id))
        g.apply(Attack(1,other,self.unit(g,B,2).id));self.assertEqual(self.unit(g,B,2).health,18)

    def test_shaw_retirement_removes_only_continuous_rush(self):
        g=self.game((KILL,),board=(SHAW,A));other=self.unit(g,A).id;self.assertIn(Keyword.RUSH,g.state.entities[other].keywords)
        self.play(g,KILL,self.unit(g,SHAW).id);self.assertNotIn(Keyword.RUSH,g.state.entities[other].keywords);self.portable(g)

    def test_complete_standard_host_real_consumers_and_actual_mirror_entity_extra(self):
        g=self.game((MUKLA,),board=(A,),real_host=True);self.play(g,MUKLA);self.play(g,BANANA,self.unit(g,A).id)
        self.assertEqual(self.unit(g,A).health,21)
        g=self.game((KATH,KILL),deck=(BEAST,BEAST2),real_host=True);source=self.play(g,KATH);self.play(g,KILL,source)
        self.assertEqual(len(g.state.players[1].board),2)
        g=self.game((VOL,),enemy=(B,),real_host=True);source=self.play(g,VOL,self.unit(g,B,2).id);self.assertEqual(g.state.entities[source].health,20)
        g=self.game((MIRROR,),board=(RHY,),enemy_hand=(A,),real_host=True);self.play(g,MIRROR);g.apply(EndTurn(1));self.play(g,A,player=2)
        self.assertEqual(self.board(g).count(A),2);self.portable(g)


if __name__=='__main__':unittest.main()
