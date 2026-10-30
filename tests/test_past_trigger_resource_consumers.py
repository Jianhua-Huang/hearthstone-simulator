"""Actual twelve roots, six generated dependencies and shared continuation checks."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_trigger_resource_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,Draw,EquipWeapon,GainArmor,
    InvokeBehavior,ModifyWeapon,RandomDamage,RequestChoice,Silence,Summon)
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.registry import Registry
from hs_sim.local_pool_format import build_cn37_local_pool_format

GREEN,PROF,CORN,OMU,DRED,FLURGL,NAT,LEO,OON,KRYXIS,VEREESA,GELBIN=native.ROOTS
WEAPON,EMBOLD,CHICKEN_BOT,REPAIR,POULTRY,CHICKEN=native.DEPENDENCIES
P='k701.';A=P+'large';TINY=P+'tiny';EXACT=P+'exact';BEAST=P+'beast';BEAST2=P+'beast2';BEAST3=P+'beast3'
MURL=P+'murloc';POWER=P+'power';EQUIP=P+'equip';BOLT=P+'bolt';DRAW=P+'draw';KILL=P+'kill';HUSH=P+'hush';MAKE_MURL=P+'make_murl'
WEAR=P+'wear'
WATCH_RECRUIT=P+'recruit_watch';WATCH_DAMAGE=P+'damage_watch';WATCH_ATTACK=P+'attack_watch';WATCH_INVENT=P+'invention_watch';FAIL=P+'fail'
WATCH_DISCARD=P+'discard_watch'
HELPERS=(A,TINY,EXACT,BEAST,BEAST2,BEAST3,MURL,POWER,EQUIP,BOLT,DRAW,KILL,HUSH,MAKE_MURL,
    WATCH_RECRUIT,WATCH_DAMAGE,WATCH_ATTACK,WATCH_INVENT,WEAR,WATCH_DISCARD)


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'beast',lambda c:(GainArmor(c.player_id,7),))
    for cid,attack,hp,tribes in((A,1,12,()),(TINY,1,1,()),(EXACT,1,7,()),(BEAST,4,8,('beast',)),
            (BEAST2,2,10,('beast',)),(BEAST3,3,9,('beast',)),(MURL,1,1,('murloc',)),(POWER,1,12,())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=attack,health=hp,
            battlecry=P+'beast'if cid in(BEAST,BEAST2,BEAST3)else None,spell_damage=5 if cid==POWER else 0,
            metadata=replace(meta,tribes=tribes)))
    scripts={EQUIP:lambda c:(EquipWeapon(c.player_id,WEAPON),),BOLT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),MAKE_MURL:lambda c:(Summon(c.player_id,MURL),),
        WEAR:lambda c:(ModifyWeapon(c.state.players[c.player_id].weapon_id,durability=-2,source_id=c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=meta,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in(BOLT,KILL,HUSH)else None))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K701 deliberate native continuation failure')))
    def waiting(c):
        e=c.state.entities.get(c.event.source_id)
        native_event=(c.event.kind=='minion_summoned'and e is not None and e.card_id in(BEAST,BEAST2,BEAST3,*native.INVENTIONS)
            or c.event.kind=='health_resolved'and e is not None and e.card_id==FLURGL
            or c.event.kind=='card_discarded'and e is not None and e.card_id==KRYXIS
            or c.event.kind=='attack_declared'and c.event.source_id in c.state.players[1].board
                and c.state.entities[c.event.source_id].card_id==DRED)
        if not native_event:return()
        extra=(ChoiceOption('draw','Draw after original discard',(Draw(c.player_id,1,c.source_id),)),)if c.event.kind=='card_discarded'else()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*extra),c.source_id),)
    r.register_behavior(P+'waiting',waiting)
    for cid,event in((WATCH_RECRUIT,'minion_summoned'),(WATCH_DAMAGE,'health_resolved'),
            (WATCH_ATTACK,'attack_declared'),(WATCH_INVENT,'minion_summoned'),(WATCH_DISCARD,'card_discarded')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'waiting'),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k701-native-trigger-resource-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp','TIME_013',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_trigger_resource_consumers(r);r.validate();return r


class PastTriggerResourceConsumerTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*10,enemy_hand=(),enemy_deck=(A,)*10,
            watch=None,weapon=None,real_host=False,seed=701):
        self.mode='host'if real_host else'small';h=host('writer')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp',weapon_card_id=watch or weapon),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=enemy_deck,mana=30,max_mana=30,mana_cap=30,
                hero_power_card_id='HERO_08bp')),seed=seed,generation_context=h.context if real_host else None),
            h.registry if real_host else fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def weapon(self,g,p=1):return g.state.entities[g.state.players[p].weapon_id]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        self.assertIsNotNone(g.state.pending_choice);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)

    def test_complete_faces_four_inventions_and_separate_chicken(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['official_observations']),38)
        self.assertEqual(d['invention_members'],list(native.INVENTIONS));self.assertEqual(d['invention_weights'],[1]*4)
        self.assertNotIn(CHICKEN,native.INVENTIONS);self.assertEqual(len(d['original_candidate_ids']),732)
        for row in d['cards']+d['dependencies']:self.assertEqual(r.card(row['record']['id']),native.make_definition(row['record']))
        self.assertTrue(all(r.card(cid).attack==0 for cid in native.INVENTIONS));self.assertEqual(r.card(CHICKEN).cost,0)

    def test_all_eighteen_physical_faces_have_real_paid_hand_entries(self):
        for cid in native.ROOTS+native.DEPENDENCIES:
            g=self.game((cid,));source=self.play(g,cid)
            self.assertEqual(g.state.entities[source].card_id,cid);self.assertEqual(g.state.players[1].mana,30-g.registry.card(cid).cost)
            self.assertEqual(len(g.state.play_history),1)

    def test_greenskin_buffs_original_equipped_weapon_once(self):
        g=self.game((GREEN,),weapon=WEAPON);original=self.weapon(g).id;self.play(g,GREEN)
        self.assertEqual(self.weapon(g).id,original);self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,4));self.portable(g)

    def test_greenskin_no_weapon_is_legal_and_does_not_consume_rng(self):
        g=self.game((GREEN,));before=g.snapshot()['rng_state'];self.play(g,GREEN)
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_professor_real_rush_attack_buffs_weapon_before_combat(self):
        g=self.game((PROF,),enemy=(A,),weapon=WEAPON);source=self.play(g,PROF)
        self.assertIn(Keyword.RUSH,g.state.entities[source].keywords);g.apply(Attack(1,source,self.unit(g,A,2).id))
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(3,4));self.portable(g)

    def test_other_attacker_does_not_activate_professor(self):
        g=self.game(board=(PROF,A),enemy=(A,),weapon=WEAPON);g.apply(Attack(1,self.unit(g,A).id,self.unit(g,A,2).id))
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,3))

    def test_cornelius_draws_for_its_controller_at_both_players_start_and_end(self):
        g=self.game(board=(CORN,));g.apply(EndTurn(1));self.assertEqual(len(self.hand(g)),2)
        g.apply(EndTurn(2));self.assertEqual(len(self.hand(g)),5)
        own=[x for x in g.state.draw_history if x.player_id==1];self.assertEqual(len(own),5);self.portable(g)

    def test_omu_spellburst_refreshes_after_one_actual_spell_only(self):
        g=self.game((OMU,DRAW,DRAW));self.play(g,OMU);self.assertEqual(g.state.players[1].mana,24)
        self.play(g,DRAW);self.assertEqual(g.state.players[1].mana,30)
        self.play(g,DRAW);self.assertEqual(g.state.players[1].mana,29);self.portable(g)

    def test_omu_silence_prevents_native_spellburst(self):
        g=self.game((HUSH,DRAW),board=(OMU,));self.play(g,HUSH,self.unit(g,OMU).id)
        self.play(g,DRAW);self.assertEqual(g.state.players[1].mana,28)

    def test_dred_attacks_opponent_minion_after_its_real_battlecry(self):
        g=self.game(board=(DRED,),enemy_hand=(BEAST,));g.apply(EndTurn(1));self.play(g,BEAST,player=2)
        self.assertNotIn(BEAST,self.board(g,2));self.assertEqual(self.hero(g,2).armor,7)
        self.assertEqual(self.unit(g,DRED).health,5);self.portable(g)

    def test_dred_does_not_attack_own_play_or_an_enemy_spell(self):
        g=self.game((A,),board=(DRED,),enemy_hand=(DRAW,));self.play(g,A)
        g.apply(EndTurn(1));self.play(g,DRAW,player=2);self.assertEqual(len(g.state.character_attack_history),0)

    def test_dred_forced_attack_wait_restores_across_opponent_turn_and_failure(self):
        g=self.game(board=(DRED,),enemy_hand=(BEAST,),watch=WATCH_ATTACK);g.apply(EndTurn(1));self.play(g,BEAST,player=2)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertNotIn(BEAST,self.board(g,2));self.portable(g)

    def test_flurgl_real_murloc_play_hits_all_enemies_without_spell_damage(self):
        g=self.game((MURL,),board=(FLURGL,POWER),enemy=(A,));self.play(g,MURL)
        self.assertEqual(self.hero(g,2).health,29);self.assertEqual(self.unit(g,A,2).health,11)
        self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_flurgl_self_play_plain_summon_and_opponent_murloc_do_not_activate(self):
        g=self.game((FLURGL,MAKE_MURL),enemy_hand=(MURL,));self.play(g,FLURGL);self.play(g,MAKE_MURL)
        self.assertEqual(self.hero(g,2).health,30);g.apply(EndTurn(1));self.play(g,MURL,player=2)
        self.assertEqual(self.hero(g,2).health,30)

    def test_flurgl_damage_group_wait_has_no_duplicate_packet_on_restore(self):
        g=self.game((MURL,),board=(FLURGL,),enemy=(A,),watch=WATCH_DAMAGE);self.play(g,MURL)
        g=self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual((self.hero(g,2).health,self.unit(g,A,2).health),(29,11));self.portable(g)

    def test_nat_samples_both_real_half_chance_branches_only_on_opponent_start(self):
        seen=set()
        for seed in range(8):
            g=self.game(board=(NAT,),seed=seed);g.apply(EndTurn(1))
            selected=[dict(e.data)['selected']for e in g.events if e.kind=='random_choice'and e.source_id==self.unit(g,NAT).id]
            self.assertEqual(len(selected),1);seen.add(selected[0]);self.assertEqual(len(self.hand(g,2)),2 if selected[0]=='draw'else 1)
            before=g.snapshot()['rng_state'];g.apply(EndTurn(2));self.assertEqual(g.snapshot()['rng_state'],before)
        self.assertEqual(seen,{'draw','none'})

    def test_leoroxx_recruits_three_original_beasts_without_playing_battlecries(self):
        g=self.game((LEO,BEAST,BEAST2,A,BEAST3));original=set(g.state.players[1].hand[1:]);self.play(g,LEO)
        self.assertEqual(set(self.board(g)),{LEO,BEAST,BEAST2,BEAST3});self.assertEqual(self.hand(g),[A])
        self.assertTrue(set(g.state.players[1].board[1:])<=original);self.assertEqual(self.hero(g).armor,0);self.portable(g)

    def test_leoroxx_full_board_and_empty_beast_query_do_not_sample_rng(self):
        for board,hand in(((A,)*6,(LEO,BEAST)),((),(LEO,A))):
            g=self.game(hand,board=board);before=g.snapshot()['rng_state'];self.play(g,LEO)
            self.assertEqual(g.snapshot()['rng_state'],before);self.assertEqual(self.hand(g),list(hand[1:]))

    def test_leoroxx_wait_retains_three_slot_budget_and_original_physical_deliveries(self):
        g=self.game((LEO,BEAST,BEAST2,BEAST3),watch=WATCH_RECRUIT);self.play(g,LEO)
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(len(g.state.players[1].board),4)
        self.assertEqual(self.hand(g),[]);self.portable(g)

    def test_oondasta_actual_excess_combat_recruits_one_original_beast(self):
        g=self.game((BEAST,),board=(OON,),enemy=(TINY,));original=self.entity(g,BEAST).id
        g.apply(Attack(1,self.unit(g,OON).id,self.unit(g,TINY,2).id))
        self.assertIn(original,g.state.players[1].board);self.assertEqual(self.hero(g).armor,0);self.portable(g)

    def test_oondasta_exact_kill_and_opponent_turn_counterdamage_are_not_overkill_rewards(self):
        g=self.game((BEAST,),board=(OON,),enemy=(EXACT,));g.apply(Attack(1,self.unit(g,OON).id,self.unit(g,EXACT,2).id))
        self.assertEqual(self.hand(g),[BEAST])
        g=self.game((BEAST,),board=(OON,),enemy=(TINY,));g.apply(EndTurn(1));g.apply(Attack(2,self.unit(g,TINY,2).id,self.unit(g,OON).id))
        self.assertEqual(self.hand(g),[BEAST])

    def test_kryxis_real_battlecry_discards_complete_original_hand(self):
        g=self.game((A,KRYXIS,DRAW,BEAST));self.play(g,KRYXIS)
        self.assertEqual(self.hand(g),[]);self.assertEqual(len(g.state.discard_history),3)
        self.assertEqual(self.board(g),[KRYXIS]);self.portable(g)

    def test_kryxis_natural_death_draws_three_through_ordinary_deck(self):
        g=self.game((KILL,),board=(KRYXIS,));self.play(g,KILL,self.unit(g,KRYXIS).id)
        self.assertEqual(self.hand(g),[A]*3);self.assertEqual(len(g.state.draw_history),3);self.portable(g)

    def test_kryxis_wait_keeps_original_hand_scope_and_does_not_discard_later_draw(self):
        g=self.game((A,KRYXIS,DRAW,BEAST),watch=WATCH_DISCARD);self.play(g,KRYXIS)
        g=self.portable(g);self.fault(g);self.choose(g,'draw');self.finish(g)
        self.assertEqual(self.hand(g),[A]);self.assertEqual(len(g.state.discard_history),3);self.portable(g)

    def test_vereesa_equips_actual_related_weapon_without_extra_payment(self):
        g=self.game((VEREESA,));self.play(g,VEREESA);self.assertEqual(self.weapon(g).card_id,WEAPON)
        self.assertEqual((self.weapon(g).attack,self.weapon(g).durability),(2,3))
        self.assertEqual(g.state.players[1].mana,23)

    def test_thoridal_after_hero_attack_bonus_changes_real_spell_then_expires(self):
        g=self.game((BOLT,BOLT),weapon=WEAPON);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.play(g,BOLT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,25)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,24);self.portable(g)

    def test_thoridal_last_durability_still_grants_original_attack_bonus(self):
        g=self.game((WEAR,BOLT),weapon=WEAPON);weapon=self.weapon(g).id;self.play(g,WEAR)
        self.assertEqual(self.weapon(g).durability,1);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.assertIsNone(g.state.players[1].weapon_id);self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD)
        self.play(g,BOLT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,25);self.portable(g)

    def test_thoridal_minion_attack_does_not_grant_hero_spell_damage(self):
        g=self.game((BOLT,),board=(A,),enemy=(A,),weapon=WEAPON)
        g.apply(Attack(1,self.unit(g,A).id,self.unit(g,A,2).id));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(self.hero(g,2).health,29)

    def test_gelbin_samples_only_four_complete_inventions_and_reaches_each(self):
        seen=set()
        for seed in range(12):
            g=self.game((GELBIN,),seed=seed);self.play(g,GELBIN)
            produced=[cid for cid in self.board(g)if cid!=GELBIN];self.assertEqual(len(produced),1)
            self.assertIn(produced[0],native.INVENTIONS);seen.add(produced[0])
        self.assertEqual(seen,set(native.INVENTIONS))

    def test_gelbin_full_board_uses_ordinary_capacity_without_sampling(self):
        g=self.game((GELBIN,),board=(A,)*6);before=g.snapshot()['rng_state'];self.play(g,GELBIN)
        self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_gelbin_selected_invention_wait_restores_without_sampling_again(self):
        g=self.game((GELBIN,),watch=WATCH_INVENT);self.play(g,GELBIN);selected=self.board(g)[-1]
        g=self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.board(g),[GELBIN,selected]);self.portable(g)

    def test_emboldener_can_buff_itself_at_owner_end_and_not_opponent_end(self):
        g=self.game(board=(EMBOLD,));g.apply(EndTurn(1));self.assertEqual((self.unit(g,EMBOLD).attack,self.unit(g,EMBOLD).max_health),(1,5))
        g.apply(EndTurn(2));self.assertEqual((self.unit(g,EMBOLD).attack,self.unit(g,EMBOLD).max_health),(1,5));self.portable(g)

    def test_homing_chicken_owner_start_dies_and_draws_three_plus_normal_draw(self):
        g=self.game(board=(CHICKEN_BOT,));source=self.unit(g,CHICKEN_BOT).id;g.apply(EndTurn(1))
        self.assertEqual(self.board(g),[CHICKEN_BOT]);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(self.hand(g)),4);self.portable(g)

    def test_repair_bot_heals_an_enemy_damaged_hero_with_ordinary_six_healing(self):
        g=self.game((BOLT,),board=(REPAIR,));self.play(g,BOLT,self.hero(g,2).id)
        g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_repair_bot_empty_damaged_pool_does_not_consume_rng(self):
        g=self.game(board=(REPAIR,));before=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(g.snapshot()['rng_state'],before)

    def test_poultryizer_owner_start_can_transform_itself_into_actual_zero_cost_chicken(self):
        g=self.game(board=(POULTRY,));source=self.unit(g,POULTRY).id;g.apply(EndTurn(1))
        self.assertEqual(g.state.entities[source].card_id,POULTRY);g.apply(EndTurn(2))
        self.assertEqual(g.state.entities[source].card_id,CHICKEN)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health,g.state.entities[source].cost),(1,1,0));self.portable(g)

    def test_complete_standard_host_fixed_pool_weapon_and_physical_recruit_entries(self):
        g=self.game((GELBIN,),real_host=True);self.play(g,GELBIN);self.assertIn(self.board(g)[-1],native.INVENTIONS)
        g=self.game((VEREESA,BOLT),real_host=True);self.play(g,VEREESA);g.apply(Attack(1,self.hero(g).id,self.hero(g,2).id))
        self.play(g,BOLT,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,25)
        g=self.game((LEO,BEAST),real_host=True);self.play(g,LEO);self.assertEqual(self.board(g),[LEO,BEAST]);self.portable(g)


if __name__=='__main__':unittest.main()
