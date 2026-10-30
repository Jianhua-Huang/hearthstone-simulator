"""Real current-deck consumers, captured hand groups and named dependency."""
from dataclasses import asdict,replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from tools import card_batch as cb
from hs_sim.cards import past_highlander_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,GainArmor,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.engine.zones import CardReference,DiscardCard,ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format

RAZA,SOLIA,KRUL,KRUL2,ELISE,BRANN,RENO=native.ROOTS;KRUSH=native.KRUSH
P='k698.';A=P+'plain';B=P+'other';ALIAS=P+'alias';D1=P+'demon1';D2=P+'demon2';POWER=P+'power'
SPELL=P+'spell';DRAW=P+'draw';KILL=P+'kill';BOOST=P+'boost';COUNTER=P+'counter';SHIELD=P+'shield'
WATCH=P+'watch';FAIL=P+'fail';SUMMON_WATCH=P+'summon_watch';COPY_WATCH=P+'copy_watch'
COST_WATCH=P+'cost_watch';DAMAGE_WATCH=P+'damage_watch'
HELPERS=(A,B,ALIAS,D1,D2,POWER,SPELL,DRAW,KILL,BOOST,COUNTER,SHIELD,SUMMON_WATCH,COPY_WATCH,COST_WATCH,DAMAGE_WATCH)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    for cid,tribes,bonus,keywords in((A,(),0,()),(B,(),0,()),(ALIAS,(),0,()),
            (D1,('demon',),0,()),(D2,('demon',),0,()),(POWER,(),5,()),(SHIELD,(),0,(Keyword.DIVINE_SHIELD,))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=20,spell_damage=bonus,
            battlecry=P+'demon_bc'if cid==D1 else None,keywords=keywords,
            metadata=replace(meta,tribes=tribes,deck_identity=A if cid==ALIAS else cid)))
    r.register_behavior(P+'demon_bc',lambda c:(GainArmor(c.player_id,10),))
    def boost(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in(A,D1))
        ref=CardReference.capture(e)
        return(BuffStoredCard(ref,3,4,c.source_id),ModifyStoredCost(ref,CostSpec(set_to=0),c.source_id))
    scripts={SPELL:lambda c:(GainArmor(c.player_id,1),),DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),BOOST:boost}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3 if cid==SPELL else 1,
            on_play=cid,metadata=meta,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid==KILL else None))
    def counter(c):
        e=c.state.entities.get(c.event.source_id)
        return(CounterSpell(dict(c.event.data)['window_id']),)if(
            c.event.player_id!=c.player_id and e is not None and e.kind==CardType.SPELL)else()
    r.register_behavior(COUNTER,counter);r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=20,
        metadata=meta,triggers=(TriggerSpec('card_committed',COUNTER),)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K698 deliberate continuation failure')))
    def watch(c):
        source=c.state.entities.get(c.event.source_id);target=c.state.entities.get(c.event.target_id)
        if c.event.kind=='minion_summoned':
            if target is None or target.card_id not in(D1,D2,KRUSH):return()
        elif source is None or source.card_id not in(RAZA,SOLIA,ELISE,RENO):return()
        discard=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==D2),None)
        replace_demon=()if discard is None else(DiscardCard(CardReference.capture(discard),c.source_id),
            AddToHand(c.player_id,D2,c.source_id))
        later_spell=next((c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==SPELL),None)
        change_copy=()if later_spell is None else(ModifyStoredCost(CardReference.capture(later_spell),CostSpec(set_to=0),c.source_id),)
        retire=()if source is None or source.zone!=Zone.BOARD else(Destroy(source.id,c.source_id),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('draw','Draw a later arrival',(Draw(c.player_id,1,c.source_id),)),
            ChoiceOption('replace','Replace an original hand Demon',replace_demon),
            ChoiceOption('change','Change later original copy input',change_copy),ChoiceOption('retire','Retire source',retire),
            ChoiceOption('fault','Fail after random work',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,watch)
    for cid,event in((SUMMON_WATCH,'minion_summoned'),(COPY_WATCH,'card_created'),
            (COST_WATCH,'cost_modifier_added'),(DAMAGE_WATCH,'health_resolved')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=40,metadata=meta,triggers=(TriggerSpec(event,WATCH),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k698-current-highlander-consumers-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('TIME_013','HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_highlander_consumers(r);r.validate();return r


class PastHighlanderConsumerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,deck=(A,B),board=(),enemy=(),watch=None,real_host=False):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,deck=deck,board=board,mana=30,max_mana=30,
            mana_cap=30,hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',deck=(A,)*8,board=enemy,hero_power_card_id='HERO_08bp')),
            seed=698,generation_context=h.context if real_host else None),h.registry if real_host else fixture('writer'))

    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g):return[g.state.entities[i].card_id for i in g.state.players[1].hand]
    def board(self,g):return[g.state.entities[i].card_id for i in g.state.players[1].board]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault_atomic(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def power(self,g):g.apply(UseHeroPower(1,g.state.players[1].hero_power_ids[0],self.hero(g,2).id))

    def test_complete_source_and_actual_noncollectible_named_child(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(len(d['official_observations']),20)
        for row in d['cards']+d['dependencies']:
            self.assertEqual(cb.canonical(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        self.assertEqual(d['dependencies'][0]['record']['dbf_id'],57918)
        self.assertFalse(r.card(KRUSH).metadata.collectible);self.assertNotEqual(KRUSH,'EX1_543')
        self.assertFalse(d['complete_past_legendary_source_bound'])

    def test_all_seven_paid_entries_keep_actual_face_and_single_payment(self):
        for cid in native.ROOTS:
            g=self.game((cid,),deck=());source=self.play(g,cid);self.finish(g);card=g.registry.card(cid)
            self.assertEqual((g.state.entities[source].card_id,g.state.players[1].mana),(cid,30-card.cost))
            self.assertEqual(len(g.state.play_history),1)

    def test_all_seven_reject_actual_current_duplicate_deck(self):
        for cid in native.ROOTS:
            g=self.game((cid,SPELL,D1),deck=(A,A),enemy=(A,));self.play(g,cid)
            self.assertEqual(self.hand(g),[SPELL,D1]);self.assertEqual(self.board(g),[cid]);self.assertEqual(self.unit(g,A,2).health,20)

    def test_alias_identity_is_duplicate_and_drawn_duplicate_no_longer_blocks(self):
        g=self.game((RAZA,),deck=(A,ALIAS));self.play(g,RAZA);self.power(g);self.assertEqual(g.state.players[1].mana,23)
        g=self.game((DRAW,BRANN),deck=(A,A,B));self.play(g,DRAW);self.play(g,BRANN);self.assertIn(KRUSH,self.board(g))

    def test_raza_power_zero_persists_after_source_death_and_next_turn(self):
        g=self.game((RAZA,KILL));source=self.play(g,RAZA);self.power(g);self.assertEqual(g.state.players[1].mana,25)
        self.play(g,KILL,source);g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.state.players[1].mana;self.power(g)
        self.assertEqual(g.state.players[1].mana,before);self.assertEqual(self.hero(g,2).health,28);self.portable(g)

    def test_raza_modifier_acceptance_wait_recovers_without_duplicate_install(self):
        g=self.game((RAZA,),watch=COST_WATCH);self.play(g,RAZA);g=self.portable(g);self.fault_atomic(g);self.finish(g)
        self.power(g);self.assertEqual(g.state.players[1].mana,25);self.portable(g)

    def test_solia_free_next_spell_only_and_nonspell_does_not_consume(self):
        g=self.game((SOLIA,A,SPELL,SPELL));self.play(g,SOLIA);self.play(g,A);self.play(g,SPELL)
        self.assertEqual(g.state.players[1].mana,21);self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,18)
        self.assertEqual(self.hero(g).armor,2);self.portable(g)

    def test_solia_turn_end_expires_and_duplicate_deck_never_installs(self):
        g=self.game((SOLIA,SPELL));self.play(g,SOLIA);g.apply(EndTurn(1));g.apply(EndTurn(2));before=g.state.players[1].mana
        self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,before-3)
        g=self.game((SOLIA,SPELL),deck=(A,A));self.play(g,SOLIA);self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,20)

    def test_solia_countered_first_spell_still_consumes_original_use(self):
        g=self.game((SOLIA,SPELL,SPELL),enemy=(COUNTER,));self.play(g,SOLIA);self.play(g,SPELL)
        self.assertEqual(g.state.players[1].mana,23);self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,20)
        self.assertEqual(self.hero(g).armor,0)

    def test_krul_both_faces_move_original_hand_demons_without_battlecry_or_payment(self):
        for cid in(KRUL,KRUL2):
            g=self.game((cid,D1,SPELL,D2));ids=tuple(g.state.players[1].hand[i]for i in(1,3));rng=g.snapshot()['rng_state']
            self.play(g,cid);self.assertEqual(tuple(g.state.players[1].board[1:]),ids)
            self.assertEqual(self.hand(g),[SPELL]);self.assertEqual(self.hero(g).armor,0)
            self.assertEqual(g.state.players[1].mana,21);self.assertEqual(g.snapshot()['rng_state'],rng)

    def test_krul_preserves_original_physical_current_stats(self):
        g=self.game((BOOST,KRUL,D1));self.play(g,BOOST);original=self.entity(g,D1).id;self.play(g,KRUL)
        e=g.state.entities[original];self.assertEqual((e.zone,e.attack,e.health),(Zone.BOARD,5,24));self.portable(g)

    def test_krul_full_board_keeps_original_unsummoned_demons_in_hand(self):
        g=self.game((KRUL,D1,D2),board=(A,)*5);self.play(g,KRUL)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.hand(g),[D2])

    def test_krul_new_arrival_after_first_summon_is_not_in_original_group(self):
        g=self.game((KRUL,D1,D2),deck=(D1,A),watch=SUMMON_WATCH);self.play(g,KRUL)
        g=self.portable(g);self.fault_atomic(g);self.choose(g,'draw');self.finish(g)
        self.assertEqual(self.hand(g),[D1]);self.assertEqual(self.board(g),[KRUL,D1,D2]);self.portable(g)

    def test_krul_departed_original_is_not_replaced_by_fresh_same_card(self):
        g=self.game((KRUL,D1,D2),watch=SUMMON_WATCH);old=self.entity(g,D2).id;self.play(g,KRUL)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'replace');self.finish(g)
        self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.assertEqual(self.hand(g),[D2])
        self.assertEqual(self.board(g),[KRUL,D1]);self.assertNotEqual(self.entity(g,D2).id,old)

    def test_elise_copies_original_whole_hand_once_in_original_order(self):
        g=self.game((ELISE,A,SPELL,D1));rng=g.snapshot()['rng_state'];self.play(g,ELISE)
        self.assertEqual(self.hand(g),[A,SPELL,D1,A,SPELL,D1]);self.assertEqual(len(set(g.state.players[1].hand)),6)
        self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

    def test_elise_current_buff_cost_and_independent_material_survive(self):
        g=self.game((BOOST,ELISE,A));self.play(g,BOOST);original=self.entity(g,A).id;self.play(g,ELISE)
        copies=[g.state.entities[i]for i in g.state.players[1].hand]
        self.assertEqual([(e.attack,e.health,local_cost(e)[0])for e in copies],[(5,24,0),(5,24,0)])
        self.assertNotEqual(copies[1].id,original)

    def test_elise_captured_material_does_not_change_when_later_original_cost_changes(self):
        g=self.game((ELISE,A,SPELL),watch=COPY_WATCH);original=self.entity(g,SPELL).id;self.play(g,ELISE)
        g=self.portable(g);self.fault_atomic(g);self.choose(g,'change');self.finish(g)
        copies=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==SPELL]
        self.assertEqual([local_cost(e)[0]for e in copies],[0,3]);self.assertEqual(copies[0].id,original);self.portable(g)

    def test_elise_later_draw_is_not_copied_and_full_hand_overflow_is_ordinary(self):
        g=self.game((ELISE,A,SPELL),deck=(D1,B),watch=COPY_WATCH);self.play(g,ELISE)
        self.assertIsNotNone(g.state.pending_choice);self.choose(g,'draw');self.finish(g);self.assertEqual(self.hand(g),[A,SPELL,A,D1,SPELL])
        g=self.game((ELISE,)+(A,)*9);self.play(g,ELISE);self.assertEqual(len(self.hand(g)),10)

    def test_brann_summons_real_child_once_and_charge_attacks_without_another_payment(self):
        g=self.game((BRANN,));self.play(g,BRANN);child=self.unit(g,KRUSH)
        self.assertEqual((child.attack,child.health),(8,8));self.assertIn(Keyword.CHARGE,child.keywords)
        g.apply(Attack(1,child.id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,22)
        self.assertEqual(g.state.players[1].mana,23);self.assertEqual(len(g.state.play_history),1);self.portable(g)

    def test_brann_full_board_does_not_substitute_or_create_other_krush(self):
        g=self.game((BRANN,),board=(A,)*6);self.play(g,BRANN)
        self.assertEqual(len(g.state.players[1].board),7);self.assertNotIn(KRUSH,self.board(g))

    def test_brann_named_summon_wait_restores_exact_child_identity(self):
        g=self.game((BRANN,),watch=SUMMON_WATCH);self.play(g,BRANN);g=self.portable(g);self.fault_atomic(g);self.finish(g)
        self.assertEqual(self.board(g),[BRANN,KRUSH]);self.portable(g)

    def test_reno_ten_nonspell_packets_ignore_spell_damage_and_never_hit_heroes(self):
        g=self.game((RENO,),board=(POWER,),enemy=(A,));self.play(g,RENO)
        self.assertEqual(self.unit(g,A,2).health,10);self.assertEqual((self.hero(g).health,self.hero(g,2).health),(30,30))
        self.assertEqual(g.state.cast_history,[]);self.assertEqual(len(g.state.split_damage_history),1);self.portable(g)

    def test_reno_empty_enemy_pool_does_not_spend_rng_and_shield_consumes_one_packet(self):
        g=self.game((RENO,));rng=g.snapshot()['rng_state'];self.play(g,RENO);self.assertEqual(g.snapshot()['rng_state'],rng)
        self.assertEqual(self.hero(g,2).health,30)
        g=self.game((RENO,),enemy=(SHIELD,));self.play(g,RENO);self.assertEqual(self.unit(g,SHIELD,2).health,11)

    def test_reno_wait_preserves_accepted_budget_after_source_death_and_failed_choice(self):
        g=self.game((RENO,),enemy=(A,),watch=DAMAGE_WATCH);source=self.play(g,RENO)
        g=self.portable(g);self.fault_atomic(g);self.choose(g,'retire');self.finish(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.unit(g,A,2).health,10)
        self.portable(g)

    def test_complete_standard_host_real_paid_seven_consumers_and_actual_dependencies(self):
        g=self.game((RAZA,),real_host=True);self.play(g,RAZA);self.power(g);self.assertEqual(g.state.players[1].mana,25)
        g=self.game((SOLIA,SPELL),real_host=True);self.play(g,SOLIA);self.play(g,SPELL);self.assertEqual(g.state.players[1].mana,23)
        for cid in(KRUL,KRUL2):
            g=self.game((cid,D1),real_host=True);original=self.entity(g,D1).id;self.play(g,cid);self.assertIn(original,g.state.players[1].board)
        g=self.game((ELISE,A),real_host=True);self.play(g,ELISE);self.assertEqual(self.hand(g),[A,A])
        g=self.game((BRANN,),real_host=True);self.play(g,BRANN);self.assertEqual(self.board(g),[BRANN,KRUSH])
        g=self.game((RENO,),enemy=(A,),real_host=True);self.play(g,RENO);self.assertEqual(self.unit(g,A,2).health,10);self.portable(g)


if __name__=='__main__':unittest.main()
