"""Original hand starts/completed plays and all named child effects through real actions."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata,registry as opening_registry
from hs_sim.cards import past_legendary_cast_listeners as native,trigger_source_cards as legacy
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario,UseHeroPower
from hs_sim.engine.effects import (AddCostModifier,Buff,ChoiceOption,CopyMinion,Damage,Destroy,
    InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.health_rules import spell_damage_sources
from hs_sim.engine.model import (CardDefinition,CardType,CostAuraSpec,CostSpec,DamageKind,
    Keyword,SpellRepeatSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

FJOLA,EYDIS,BEARDO,CHO,XAVIUS,GALLY,TROGGZOR,HALEH,MOZAKI,NAZJAN=native.ROOTS
SATYR,COIN,BURLY=native.DEPENDENCIES;CORE_CHO='CORE_EX1_100'
P='k686.';A=P+'plain';SMALL=P+'small';POWER=P+'power';REDUCER=P+'reducer';DOUBLE=P+'double';COUNTER=P+'counter'
NOOP=P+'noop';FREE=P+'free';BOLT=P+'bolt';HURT=P+'hurt';BOOST=P+'boost';KILL=P+'kill';HUSH=P+'hush'
BOUNCE=P+'bounce';COPY=P+'copy';MUTATE=P+'mutate';AUTO=P+'auto';WATCH=P+'watch';GIFTS=P+'gifts';SUMMONS=P+'summons';SPLIT=P+'split';FAIL=P+'fail'


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    r=opening_registry();legacy.register_trigger_source_cards(r);native.register_past_legendary_cast_listeners(r)
    for cid,health,power in((A,40,0),(SMALL,1,0),(POWER,40,9)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=health,spell_damage=power,metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(REDUCER,REDUCER,CardType.MINION,health=40,
        cost_auras=(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.SPELL,))),),metadata=metadata(collectible=False)))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=40,
        spell_repeats=(SpellRepeatSpec(2,class_mode='any'),),metadata=metadata(collectible=False)))
    r.register_behavior(COUNTER,lambda c:(CounterSpell(dict(c.event.data)['window_id']),)if c.event.player_id!=c.player_id else())
    r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=40,
        triggers=(TriggerSpec('card_committed',COUNTER),),metadata=metadata(collectible=False)))
    board=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    scripts={NOOP:lambda c:(),FREE:lambda c:(),
        BOLT:lambda c:(Damage(c.state.players[3-c.player_id].hero_id,1,c.source_id,DamageKind.SPELL),),
        HURT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        BOOST:lambda c:(Buff(c.target_id,1,1,c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        HUSH:lambda c:(Silence(c.target_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        COPY:lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        MUTATE:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-4,card_types=(CardType.SPELL,)),source_id=c.source_id),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,
            cost=0 if cid==FREE else 4 if cid==MUTATE else 3,on_play=cid,
            targeting=board if cid in(HURT,BOOST,KILL,HUSH,BOUNCE,COPY)else None,metadata=metadata(collectible=False)))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,NOOP,c.source_id),))
    r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=40,battlecry=AUTO,metadata=metadata(collectible=False)))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K686 deliberate listener rollback')))
    def wait(c):
        event=c.event
        if event.kind=='damage_dealt':
            source=c.state.entities.get(event.source_id)
            if source is None or source.card_id!=HALEH:return()
        elif event.kind=='minion_summoned':
            if c.state.entities[event.target_id].card_id!=BURLY:return()
        elif c.state.entities[event.target_id].card_id!=COIN:return()
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id)))),c.source_id),)
    r.register_behavior(WATCH,wait)
    for cid,event in((GIFTS,'card_added_to_hand'),(SUMMONS,'minion_summoned'),(SPLIT,'damage_dealt')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=40,triggers=(TriggerSpec(event,WATCH),),metadata=metadata(collectible=False)))
    r.validate();return r


class PastLegendaryCastTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))
    def game(self,hand=(),*,board=(),enemy=(),enemy_hand=(),player=1):
        self.mode='small'
        return Game.from_scenario(Scenario(tuple(PlayerSetup('mage.hero'if p==1 else'warrior.hero',
            hand=hand if p==player else enemy_hand,board=board if p==player else enemy,
            deck=('card.1',)*20,mana=20,max_mana=40,mana_cap=40,
            hero_power_card_id='mage.power'if p==1 else'warrior.power')for p in(1,2)),active_player=player,seed=686),fixture('writer'))
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def power(self,g,p=1):g.apply(UseHeroPower(p,g.state.players[p].hero_power_id))
    def magic(self,g,entity_id):
        e=g.state.entities[entity_id]
        return sum(amount for source,_,_,amount in spell_damage_sources(g.state,e.controller,g.registry)
            if source is not None and source.id==entity_id)

    def test_complete_faces_roles_zero_pins_and_three_actual_child_links(self):
        d=native.load_batch();r=fixture();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(10,3,28))
        self.assertEqual(len(d['original_candidate_ids']),732);self.assertFalse(d['complete_past_legendary_source_bound'])
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(canonical_digest(asdict(r.pool_card(cid))),row['pool_card_sha256'])
        self.assertTrue(r.card(BURLY).metadata.collectible);self.assertEqual((r.card(CHO).attack,r.card(COIN).cost),(0,0))
        self.assertEqual(r.card(CHO).triggers,r.card(CORE_CHO).triggers)
        with patch.object(native,'BATCH_HASH',''):
            with self.assertRaises(TargetValidationError):native.load_batch()

    def test_all_thirteen_faces_have_complete_ordinary_paid_entries(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(card=cid):
                g=self.game((cid,));self.play(g,cid);c=g.registry.card(cid)
                if cid==COIN:self.assertEqual(g.state.players[1].mana,21)
                else:
                    e=self.unit(g,cid);self.assertEqual((e.attack,e.health),(c.attack,c.health));self.assertEqual(g.state.players[1].mana,20-c.cost)
                self.assertEqual([x.card_id for x in g.state.play_history],[cid])

    def test_fjola_shield_is_granted_before_actual_targeted_spell_damage(self):
        g=self.game((HURT,),board=(FJOLA,));self.play(g,HURT,self.unit(g,FJOLA).id)
        self.assertEqual(self.unit(g,FJOLA).health,4);self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,FJOLA).keywords);self.portable(g)

    def test_fjola_original_target_boost_keeps_shield_after_payload(self):
        g=self.game((BOOST,),board=(FJOLA,));self.play(g,BOOST,self.unit(g,FJOLA).id)
        self.assertEqual((self.unit(g,FJOLA).attack,self.unit(g,FJOLA).health),(4,5));self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,FJOLA).keywords)

    def test_fjola_enemy_or_untargeted_spell_does_not_grant_shield(self):
        g=self.game((NOOP,),board=(FJOLA,));self.play(g,NOOP);self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,FJOLA).keywords)
        g=self.game((HURT,),enemy=(FJOLA,));self.play(g,HURT,self.unit(g,FJOLA,2).id)
        self.assertEqual(self.unit(g,FJOLA,2).health,3);self.assertNotIn(Keyword.DIVINE_SHIELD,self.unit(g,FJOLA,2).keywords)

    def test_fjola_original_start_still_fires_on_countered_targeted_spell(self):
        g=self.game((HURT,),board=(FJOLA,),enemy=(COUNTER,));self.play(g,HURT,self.unit(g,FJOLA).id)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.unit(g,FJOLA).health,4)
        self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,FJOLA).keywords);self.portable(g)

    def test_eydis_random_three_is_ability_damage_before_original_payload(self):
        g=self.game((BOOST,),board=(EYDIS,POWER),enemy=(A,));before=self.hero(g,2).health+self.unit(g,A,2).health
        self.play(g,BOOST,self.unit(g,EYDIS).id);self.assertEqual(before-self.hero(g,2).health-self.unit(g,A,2).health,3)
        self.assertEqual((self.unit(g,EYDIS).attack,self.unit(g,EYDIS).health),(4,5));self.portable(g)

    def test_eydis_other_target_or_enemy_caster_does_not_fire(self):
        g=self.game((BOOST,),board=(EYDIS,A));self.play(g,BOOST,self.unit(g,A).id);self.assertEqual(self.hero(g,2).health,30)
        g=self.game((BOOST,),enemy=(EYDIS,));self.play(g,BOOST,self.unit(g,EYDIS,2).id);self.assertEqual(self.hero(g).health,30)

    def test_original_and_core_cho_reuse_same_actual_copy_body(self):
        g=self.game((NOOP,),board=(CHO,CORE_CHO));self.play(g,NOOP)
        self.assertEqual(self.hand(g,2),[NOOP,NOOP]);self.portable(g)

    def test_cho_copy_is_base_face_not_discounted_original_payment(self):
        g=self.game((NOOP,),board=(CHO,REDUCER));self.play(g,NOOP);self.assertEqual(g.state.players[1].mana,19)
        self.assertEqual(self.entity(g,NOOP,2).cost,3);self.assertEqual(self.hand(g,2),[NOOP]);self.portable(g)

    def test_cho_countered_spell_still_copies_once_and_auto_cast_does_not(self):
        g=self.game((NOOP,),board=(CHO,),enemy=(COUNTER,));self.play(g,NOOP);self.assertEqual(self.hand(g,2),[NOOP])
        g=self.game((AUTO,),board=(CHO,));self.play(g,AUTO);self.assertEqual([x.origin for x in g.state.cast_history],['effect']);self.assertFalse(self.hand(g,2));self.portable(g)

    def test_cho_works_from_second_players_real_hand_cast(self):
        g=self.game((NOOP,),enemy=(CHO,),player=2);self.play(g,NOOP,player=2);self.assertEqual(self.hand(g,1),[NOOP]);self.portable(g)

    def test_gallywix_copies_opponent_original_spell_and_gives_real_zero_coin(self):
        g=self.game((NOOP,),enemy=(GALLY,));self.play(g,NOOP);self.assertEqual(self.hand(g),[COIN]);self.assertEqual(self.hand(g,2),[NOOP])
        self.play(g,COIN);self.assertEqual((g.state.players[1].mana,g.state.players[1].temporary_mana),(18,1))
        self.assertFalse(self.hand(g));self.assertEqual(self.hand(g,2),[NOOP]);self.portable(g)

    def test_all_gallywixes_skip_only_their_coin_without_global_spell_suppression(self):
        g=self.game((COIN,),board=(MOZAKI,),enemy=(GALLY,GALLY));self.play(g,COIN)
        self.assertFalse(self.hand(g,2));self.assertEqual(self.magic(g,self.unit(g,MOZAKI).id),1);self.assertEqual(g.state.players[1].mana,21);self.portable(g)

    def test_gallywix_does_not_copy_own_spell_and_full_receiver_hand_burns_copy(self):
        g=self.game((NOOP,),board=(GALLY,));self.play(g,NOOP);self.assertFalse(self.hand(g))
        g=self.game((NOOP,),enemy=(GALLY,),enemy_hand=(A,)*10);old=tuple(g.state.players[2].hand);self.play(g,NOOP)
        self.assertEqual(tuple(g.state.players[2].hand),old);self.assertEqual(self.hand(g),[COIN])
        self.assertEqual(sum(e.card_id==NOOP and e.owner==2 and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()),1);self.portable(g)

    def test_troggzor_summons_before_lethal_spell_and_child_does_not_retroactively_grow(self):
        g=self.game((KILL,NOOP),enemy=(TROGGZOR,));self.play(g,KILL,self.unit(g,TROGGZOR,2).id)
        self.assertEqual(self.board(g,2),[BURLY]);self.assertEqual((self.unit(g,BURLY,2).attack,self.unit(g,BURLY,2).health),(3,5))
        self.play(g,NOOP);self.assertEqual(self.unit(g,BURLY,2).attack,5);self.portable(g)

    def test_troggzor_and_existing_burly_react_to_coin_even_though_gallywix_excludes_it(self):
        g=self.game((COIN,),enemy=(TROGGZOR,BURLY,GALLY));old=self.unit(g,BURLY,2).id;self.play(g,COIN)
        self.assertEqual(g.state.entities[old].attack,5);self.assertEqual(self.board(g,2).count(BURLY),2);self.assertFalse(self.hand(g,2));self.portable(g)

    def test_troggzor_full_board_does_not_replace_old_units(self):
        g=self.game((NOOP,),enemy=(TROGGZOR,)+(A,)*6);old=tuple(g.state.players[2].board);self.play(g,NOOP)
        self.assertEqual(tuple(g.state.players[2].board),old);self.assertNotIn(BURLY,self.board(g,2))

    def test_xavius_does_not_trigger_own_entry_but_other_card_plays_summon_actual_satyr(self):
        g=self.game((XAVIUS,NOOP,A));self.play(g,XAVIUS);self.assertEqual(self.board(g),[XAVIUS]);self.play(g,NOOP);self.play(g,A)
        self.assertEqual(self.board(g).count(SATYR),2);e=self.unit(g,SATYR);self.assertEqual((e.attack,e.health),(2,1));self.portable(g)

    def test_xavius_counts_countered_physical_card_but_not_auto_cast_inside_minion_play(self):
        g=self.game((NOOP,),board=(XAVIUS,),enemy=(COUNTER,));self.play(g,NOOP);self.assertEqual(self.board(g).count(SATYR),1)
        g=self.game((AUTO,),board=(XAVIUS,));self.play(g,AUTO);self.assertEqual(self.board(g).count(SATYR),1);self.portable(g)

    def test_beardo_refreshes_actual_used_hero_power_after_own_successful_spell(self):
        g=self.game((NOOP,),board=(BEARDO,));self.power(g);self.play(g,NOOP);self.power(g)
        self.assertEqual((self.hero(g,2).health,g.state.players[1].mana),(28,13));self.portable(g)

    def test_beardo_counter_or_enemy_spell_does_not_refresh_own_power(self):
        g=self.game((NOOP,),board=(BEARDO,),enemy=(COUNTER,));self.power(g);self.play(g,NOOP);saved=deepcopy(g.snapshot())
        with self.assertRaises(IllegalAction):self.power(g)
        self.assertEqual(g.snapshot(),saved)

    def test_mozaki_grows_only_after_payload_then_modifies_next_real_spell(self):
        g=self.game((NOOP,BOLT),board=(MOZAKI,));self.play(g,NOOP);self.assertEqual(self.magic(g,self.unit(g,MOZAKI).id),1)
        self.play(g,BOLT);self.assertEqual(self.hero(g,2).health,28);self.assertEqual(self.magic(g,self.unit(g,MOZAKI).id),2);self.portable(g)

    def test_successful_personal_completion_ignores_counter_and_automatic_minion_cast(self):
        for card in(NOOP,AUTO):
            g=self.game((card,),board=(MOZAKI,NAZJAN,HALEH),enemy=(COUNTER,));self.play(g,card)
            self.assertEqual(self.magic(g,self.unit(g,MOZAKI).id),0);self.assertEqual(self.hero(g,2).health,30)

    def test_haleh_uses_four_nonspell_dynamic_unit_packets_without_spell_bonus(self):
        g=self.game((NOOP,),board=(HALEH,POWER),enemy=(A,));before=self.hero(g,2).health+self.unit(g,A,2).health;self.play(g,NOOP)
        self.assertEqual(before-self.hero(g,2).health-self.unit(g,A,2).health,4);self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_nazjan_reads_original_discounted_payment_not_printed_cost(self):
        g=self.game((NOOP,),board=(NAZJAN,REDUCER,POWER));self.play(g,NOOP)
        self.assertEqual((g.state.play_history[-1].cost,g.state.players[1].mana,self.hero(g,2).health),(1,19,29));self.portable(g)

    def test_nazjan_keeps_frozen_cost_when_payload_changes_future_quotes_and_zero_is_zero(self):
        g=self.game((MUTATE,NOOP),board=(NAZJAN,));self.play(g,MUTATE);self.assertEqual(self.hero(g,2).health,26)
        self.play(g,NOOP);self.assertEqual(g.state.play_history[-1].cost,0);self.assertEqual(self.hero(g,2).health,26)
        g=self.game((FREE,),board=(NAZJAN,POWER));self.play(g,FREE);self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_repeated_spell_payloads_keep_one_personal_completion_and_one_payment(self):
        g=self.game((NOOP,),board=(MOZAKI,NAZJAN,HALEH,DOUBLE));self.play(g,NOOP)
        self.assertEqual([x.origin for x in g.state.cast_history],['hand','repeat']);self.assertEqual(g.state.players[1].mana,17)
        self.assertEqual((self.magic(g,self.unit(g,MOZAKI).id),self.hero(g,2).health),(1,23));self.portable(g)

    def test_silence_removes_mozaki_grants_and_future_completion_listener(self):
        g=self.game((NOOP,HUSH,FREE),board=(MOZAKI,));self.play(g,NOOP);self.play(g,HUSH,self.unit(g,MOZAKI).id);self.play(g,FREE)
        self.assertEqual(self.magic(g,self.unit(g,MOZAKI).id),0);self.portable(g)

    def test_original_copy_rebinds_listener_to_its_own_source_and_bounce_resets_grants(self):
        g=self.game((COPY,NOOP,BOUNCE),board=(MOZAKI,));original=self.unit(g,MOZAKI).id;self.play(g,COPY,original)
        self.play(g,NOOP);self.assertEqual(self.board(g).count(MOZAKI),2)
        self.assertTrue(all(self.magic(g,i)>=1 for i in g.state.players[1].board))
        self.play(g,BOUNCE,original);self.play(g,MOZAKI);self.assertEqual(self.magic(g,original),0);self.portable(g)

    def test_gift_wait_preserves_original_copy_coin_and_parent_spell_with_rng_rollback(self):
        g=self.game((NOOP,),enemy=(GALLY,GIFTS));self.play(g,NOOP);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual((self.hand(g),self.hand(g,2)),([COIN],[NOOP]));self.portable(g)

    def test_trogg_summon_wait_restores_before_original_lethal_payload(self):
        g=self.game((KILL,),enemy=(TROGGZOR,SUMMONS));self.play(g,KILL,self.unit(g,TROGGZOR,2).id)
        self.assertIsNotNone(g.state.pending_choice);self.assertIn(TROGGZOR,self.board(g,2));self.assertEqual(self.unit(g,BURLY,2).attack,3)
        self.portable(g);self.choose(g);self.assertNotIn(TROGGZOR,self.board(g,2));self.assertEqual(self.unit(g,BURLY,2).attack,3);self.portable(g)

    def test_haleh_split_wait_restores_each_unit_and_choice_failure_rolls_back_rng(self):
        g=self.game((NOOP,),board=(HALEH,SPLIT));self.play(g,NOOP);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);waits=0
        while g.state.pending_choice is not None:self.choose(g);waits+=1
        self.assertEqual((waits,self.hero(g,2).health),(4,26));self.portable(g)

    def test_real_standard_host_paid_nazjan_uses_real_spell_cost_without_claiming_full_source(self):
        self.mode='host';h=host('writer');g=Game.from_scenario(Scenario((
            PlayerSetup('HERO_08',hand=(NAZJAN,'CORE_CS2_029'),deck=('CORE_CS2_182',)*20,mana=10,max_mana=10),
            PlayerSetup('HERO_08',deck=('CORE_CS2_182',)*20,mana=10,max_mana=10)),seed=686,generation_context=h.context),h.registry)
        self.play(g,NAZJAN);self.play(g,'CORE_CS2_029',self.hero(g,2).id)
        self.assertEqual((g.state.players[1].mana,self.hero(g,2).health),(4,20));self.assertNotIn('MIS_701',h.registry.cards);self.portable(g)
