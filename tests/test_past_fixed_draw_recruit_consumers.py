"""Real named deliveries and physical original draw/copy/death continuations."""
from dataclasses import replace
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_fixed_draw_recruit_consumers as native
from hs_sim.engine import EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (AddToHand,ChoiceOption,Damage,Destroy,Draw,GainArmor,InvokeBehavior,
    RandomDamage,RequestChoice,Silence)
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import CardClass,CardDefinition,CardType,DamageKind,Keyword,PaymentType,Rarity,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.registry import Registry
from hs_sim.local_pool_format import build_cn37_local_pool_format

RAFAAM,SIND,ARALON,ZZER,SUBJECT,GHUUN,WHITE,VASTANN,BARNES,VALDRIS,MAGATHA,HOGGER=native.ROOTS
LANTERN,TIMEPIECE,MIRROR,MUMMY,CHAMPION,DRAKE,GNOLL=native.DEPENDENCIES
P='k702.';A=P+'body';BC=P+'battlecry';TAUNT=P+'taunt';POWER=P+'power';LG1=P+'legend1';LG2=P+'legend2'
BOLT=P+'bolt';KILL=P+'kill';PAIN=P+'pain';ARMOR=P+'armor';HUSH=P+'silence';RAISE=P+'raise';LOW=P+'low_health'
WATCH_DRAW=P+'draw_watch';WATCH_SUMMON=P+'summon_watch';REFILL=P+'refill';FAIL=P+'fail';ALIAS=P+'secret_alias'
SECRETS=('CORE_EX1_287','CORE_EX1_289','CORE_EX1_610','CORE_EX1_611','CORE_GIL_577')
HELPERS=(A,BC,TAUNT,POWER,LG1,LG2,BOLT,KILL,PAIN,ARMOR,HUSH,RAISE,LOW,WATCH_DRAW,WATCH_SUMMON,REFILL,ALIAS)
CTX=GenerationContext('k702-explicit-small-fixture','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(collectible=False)
    r.register_behavior(P+'bc',lambda c:(GainArmor(c.player_id,5),))
    for cid in(A,BC,TAUNT,POWER,LG1,LG2):
        rarity=Rarity.LEGENDARY if cid in(LG1,LG2)else Rarity.COMMON
        m=replace(meta,collectible=cid in(LG1,LG2),rarity=rarity,classes=(CardClass.HUNTER,)if cid==LG2 else(CardClass.MAGE,))
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=12,
            battlecry=P+'bc'if cid in(BC,TAUNT)else None,keywords=(Keyword.TAUNT,)if cid==TAUNT else(),
            spell_damage=3 if cid==POWER else 0,metadata=m))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    scripts={BOLT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),
        PAIN:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        ARMOR:lambda c:(GainArmor(c.player_id,5),),HUSH:lambda c:(Silence(c.target_id),),
        RAISE:lambda c:(SetHandCapacity(c.player_id,15,'raise'),),
        LOW:lambda c:(Damage(c.state.players[c.player_id].hero_id,29,c.source_id,DamageKind.EFFECT),)}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=2 if cid==BOLT else 0,on_play=cid,
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in(BOLT,PAIN,KILL,HUSH)else None,metadata=meta))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    original=r.card(SECRETS[0]);r.register_card(replace(original,id=ALIAS))
    r.register_pool_card(PoolCard.from_definition(r.card(ALIAS),identity=SECRETS[0]))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K702 actual continuation deliberate failure')))
    def waiting(c):
        event=c.event;entity=c.state.entities.get(event.source_id)
        if event.kind=='card_drawn':
            source=c.state.entities.get(event.source_id)
            if event.player_id!=c.player_id or source is None or source.card_id not in(SUBJECT,GHUUN,MAGATHA):return()
        elif entity is None or entity.card_id not in(A,BC,TAUNT,CHAMPION,*native.SEEDS):return()
        extras=(ChoiceOption('extra','Independent reaction draw',(Draw(c.player_id,1,c.source_id),)),)if event.kind=='card_drawn'else(
            ChoiceOption('kill','Kill the new minion',(Destroy(event.source_id,c.source_id),)),)
        return(RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*extras),c.source_id),)
    r.register_behavior(P+'waiting',waiting)
    r.register_behavior(REFILL,lambda c:(AddToHand(c.player_id,A,c.source_id),)if c.state.entities[c.event.source_id].card_id==RAFAAM else())
    for cid,event,body in((WATCH_DRAW,'card_drawn',P+'waiting'),(WATCH_SUMMON,'minion_summoned',P+'waiting'),(REFILL,'minion_summoned',REFILL)):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,body),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k702-fixed-draw-recruit-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for key,condition in full._secret_conditions.items():
        if key not in r._secret_conditions:r.register_secret_condition(key,condition)
    for cid in('HERO_08','HERO_08bp',*native.EXISTING,*SECRETS,*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    native.register_past_fixed_draw_recruit_consumers(r)
    r.register_pool(PoolDefinition('constructed.cards','explicit-fixture-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in(LG1,LG2,A,BOLT,CHAMPION))))
    r.validate();return r


class PastFixedDrawRecruitTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*12,enemy_hand=(),watch=None,real_host=False,seed=702):
        self.mode='host'if real_host else'small';h=host()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=30,max_mana=30,mana_cap=30,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',board=enemy,hand=enemy_hand,deck=(A,)*12,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=seed,generation_context=h.context if real_host else CTX),h.registry if real_host else fixture())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def original_draws(self,g,source):return[x for x in g.state.draw_history if x.source_id==source and x.parent_id is None]

    def test_complete_faces_and_honest_four_missing_live_API_faces(self):
        d=native.load_batch();r=fixture();self.assertEqual(len(d['official_observations']),40)
        self.assertEqual(d['API_unavailable_artifact_ids'],[LANTERN,TIMEPIECE,MIRROR,MUMMY])
        self.assertEqual(d['artifact_member_ids'],list(native.ARTIFACTS));self.assertEqual(d['wildseed_member_ids'],list(native.SEEDS))
        for row in d['cards']+d['dependencies']:
            card=r.card(row['record']['id']);self.assertEqual(card,native.make_definition(row['record']))
            self.assertEqual(r.pool_card(card.id),PoolCard.from_definition(card))

    def test_all_nineteen_real_faces_have_paid_hand_entries(self):
        for cid in(*native.ROOTS,*native.DEPENDENCIES):
            with self.subTest(cid=cid):
                g=self.game((cid,),board=(A,));cost=fixture().card(cid).cost
                self.play(g,cid,self.unit(g,A).id if cid==LANTERN else None)
                if g.state.pending_choice is not None:self.choose(g,g.state.pending_choice.options[0].id)
                self.assertEqual(g.state.players[1].mana,30-cost)

    def test_rafaam_has_exact_three_choices_and_genuine_discovery_delivery(self):
        g=self.game((RAFAAM,));self.play(g,RAFAAM);self.assertEqual({o.card_id for o in g.state.pending_choice.options},set(native.ARTIFACTS))
        self.portable(g);self.choose(g,MIRROR);self.assertEqual(self.hand(g),[MIRROR])
        self.assertEqual(len(g.state.card_discovery_history),1);self.assertTrue(any(e.kind=='card_discovered'for e in g.events));self.portable(g)

    def test_rafaam_full_hand_still_offers_all_artifacts_then_overflows(self):
        g=self.game((RAFAAM,)+(A,)*9,watch=REFILL);self.play(g,RAFAAM)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(len(g.state.pending_choice.options),3)
        self.choose(g,LANTERN);self.assertEqual(len(g.state.players[1].hand),10);self.assertNotIn(LANTERN,self.hand(g))
        self.assertEqual(len(g.state.card_discovery_history),1)

    def test_lantern_real_enemy_minion_gain_and_illegal_hero_rollback(self):
        g=self.game((LANTERN,),enemy=(A,));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,LANTERN,self.hero(g,2).id)
        self.assertEqual(g.snapshot(),before);target=self.unit(g,A,2).id;self.play(g,LANTERN,target)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(11,22))

    def test_timepiece_uses_one_whole_spell_damage_budget(self):
        g=self.game((TIMEPIECE,),board=(POWER,));self.play(g,TIMEPIECE)
        self.assertEqual(self.hero(g,2).health,17);self.assertEqual(self.hero(g).health,30);self.portable(g)

    def test_mirror_fills_only_own_board_with_real_three_three_mummies(self):
        g=self.game((MIRROR,),board=(A,),enemy=(A,));self.play(g,MIRROR)
        self.assertEqual(self.board(g).count(MUMMY),6);self.assertEqual(self.board(g,2),[A])
        self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(3,3)for i in g.state.players[1].board if g.state.entities[i].card_id==MUMMY))

    def test_mirror_full_board_does_not_consume_rng(self):
        g=self.game((MIRROR,),board=(A,)*7);before=g.snapshot()['rng_state'];self.play(g,MIRROR)
        self.assertEqual(self.board(g),[A]*7);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_sindragosa_summons_two_actual_zero_one_champions(self):
        g=self.game((SIND,));self.play(g,SIND);self.assertEqual(self.board(g),[SIND,CHAMPION,CHAMPION])
        self.assertEqual((self.unit(g,CHAMPION).attack,self.unit(g,CHAMPION).health),(0,1))

    def test_champion_natural_death_generates_both_foreign_class_legendaries(self):
        found=set()
        for seed in range(4):
            g=self.game((KILL,),board=(CHAMPION,),seed=seed);self.play(g,KILL,self.unit(g,CHAMPION).id)
            self.assertEqual(len(self.hand(g)),1);found.update(self.hand(g))
        self.assertEqual(found,{LG1,LG2})

    def test_champion_host_uses_complete_ordinary_domain_instead_of_past_subset(self):
        h=host();pool=h.registry.pool('constructed.cards',h.context);self.assertGreater(len(pool.members),1000)
        candidates=resolve_candidates(h.registry,h.context,'constructed.cards',native.LEGENDARIES,
            current_class=CardClass.MAGE,source_card_id=CHAMPION,player_id=1,exclude_source_by_rule=True)
        past=set(native.load_batch()['original_candidate_ids']);self.assertTrue(any(x.card_id not in past for x in candidates))
        g=self.game((KILL,),board=(CHAMPION,),real_host=True);self.play(g,KILL,self.unit(g,CHAMPION).id)
        self.assertIn(self.hand(g)[0],{x.card_id for x in candidates});self.portable(g)

    def test_aralon_three_existing_dormant_seeds_and_real_waking_weapon(self):
        g=self.game((ARALON,));self.play(g,ARALON)
        self.assertEqual(self.board(g),[ARALON,*native.SEEDS]);self.assertTrue(all(not self.unit(g,cid).active for cid in native.SEEDS))
        for _ in range(3):g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertTrue(all(self.unit(g,cid).active for cid in native.SEEDS))
        weapon=g.state.entities[g.state.players[1].weapon_id];self.assertEqual((weapon.card_id,weapon.attack,weapon.durability),('REV_360t4',4,2))

    def test_aralon_declared_partial_board_policy_keeps_all_three_attempts(self):
        g=self.game((ARALON,),board=(A,)*5);self.play(g,ARALON)
        self.assertEqual(self.board(g).count(native.SEEDS[0]),1);self.assertNotIn(native.SEEDS[1],self.board(g));self.assertEqual(len(self.board(g)),7)

    def test_zzeraku_actual_own_hero_damage_summons_real_six_six(self):
        g=self.game((PAIN,),board=(ZZER,));self.play(g,PAIN,self.hero(g).id)
        self.assertEqual(self.board(g),[ZZER,DRAKE]);self.assertEqual((self.unit(g,DRAKE).attack,self.unit(g,DRAKE).health),(6,6))

    def test_zzeraku_armor_damage_counts_and_other_minion_damage_does_not(self):
        g=self.game((ARMOR,PAIN,PAIN),board=(ZZER,A));self.play(g,PAIN,self.unit(g,A).id);self.assertNotIn(DRAKE,self.board(g))
        self.play(g,ARMOR);self.play(g,PAIN,self.hero(g).id);self.assertEqual(self.hero(g).health,30);self.assertEqual(self.board(g).count(DRAKE),1)

    def test_hogger_original_self_damage_summons_taunt_and_silence_stops_it(self):
        g=self.game((PAIN,HUSH,PAIN),board=(HOGGER,));self.play(g,PAIN,self.unit(g,HOGGER).id)
        self.assertEqual(self.board(g).count(GNOLL),1);self.assertIn(Keyword.TAUNT,self.unit(g,GNOLL).keywords)
        self.play(g,HUSH,self.unit(g,HOGGER).id);self.play(g,PAIN,self.unit(g,HOGGER).id);self.assertEqual(self.board(g).count(GNOLL),1)

    def test_subject_nine_draws_five_different_original_secrets(self):
        g=self.game((SUBJECT,),deck=(*SECRETS,SECRETS[0],SECRETS[0],A));source=self.play(g,SUBJECT)
        self.assertEqual(set(self.hand(g)),set(SECRETS));self.assertEqual(len(self.hand(g)),5)
        self.assertEqual(len(g.state.players[1].deck),3);self.assertEqual(len(self.original_draws(g,source)),5)

    def test_subject_nine_excludes_existing_generation_identity_aliases(self):
        g=self.game((SUBJECT,),deck=(SECRETS[0],ALIAS,SECRETS[1]));source=self.play(g,SUBJECT)
        draws=self.original_draws(g,source);self.assertEqual(len(draws),2)
        self.assertEqual(len({fixture().pool_card(x.card_id).generation_identity for x in draws}),2)

    def test_subject_nine_empty_query_skips_without_fatigue_or_rng(self):
        g=self.game((SUBJECT,),deck=());before=g.snapshot()['rng_state'];self.play(g,SUBJECT)
        self.assertEqual(self.hero(g).health,30);self.assertFalse(g.state.draw_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_subject_nine_burned_card_still_occupies_its_distinct_identity(self):
        g=self.game((SUBJECT,)+(A,)*9,deck=(SECRETS[0],SECRETS[0],SECRETS[1]));source=self.play(g,SUBJECT)
        draws=self.original_draws(g,source);self.assertEqual(len(draws),2);self.assertEqual(len({x.card_id for x in draws}),2)
        self.assertEqual(len(g.state.players[1].deck),1);self.assertEqual(len(self.hand(g)),10)

    def test_subject_wait_preserves_original_distinct_draws_and_excludes_reaction_draw(self):
        g=self.game((SUBJECT,),deck=(SECRETS[0],SECRETS[0],SECRETS[1],SECRETS[2]),watch=WATCH_DRAW)
        source=self.play(g,SUBJECT);self.portable(g);self.fault(g);self.choose(g,'extra');self.finish(g)
        draws=self.original_draws(g,source);self.assertEqual(len(draws),len({x.card_id for x in draws}))
        self.assertTrue(any(x.source_id!=source for x in g.state.draw_history));self.portable(g)

    def test_ghuun_actual_draws_pay_health_without_changing_original_cost_or_mana(self):
        g=self.game((GHUUN,),deck=(BOLT,A));self.play(g,GHUUN);mana=g.state.players[1].mana
        self.assertEqual(local_cost(self.entity(g,BOLT)),(2,PaymentType.HEALTH));self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(g.state.players[1].mana,mana);self.assertEqual(self.hero(g).health,28);self.assertEqual(self.hero(g,2).health,28)

    def test_ghuun_insufficient_health_rejects_atomically(self):
        g=self.game((LOW,GHUUN),deck=(BOLT,A));self.play(g,LOW);self.play(g,GHUUN);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,BOLT,self.hero(g,2).id)
        self.assertEqual(g.snapshot(),before)

    def test_ghuun_wait_reward_belongs_only_to_two_original_slots(self):
        g=self.game((GHUUN,),deck=(BOLT,A,BOLT,A),watch=WATCH_DRAW);self.play(g,GHUUN)
        self.portable(g);self.fault(g);self.choose(g,'extra');self.finish(g)
        self.assertEqual(local_cost(self.entity(g,A))[1],PaymentType.MANA)
        self.assertTrue(all(local_cost(g.state.entities[i])[1]==PaymentType.HEALTH for i in g.state.players[1].hand if g.state.entities[i].card_id==BOLT));self.portable(g)

    def test_magatha_gives_only_original_drawn_spells_as_same_physical_cards(self):
        g=self.game((MAGATHA,BOLT),deck=(BOLT,A,BOLT,A,BOLT));original=tuple(g.state.players[1].deck)
        self.play(g,MAGATHA);self.assertEqual(self.hand(g).count(BOLT),1);self.assertEqual(self.hand(g,2),[BOLT]*3)
        self.assertEqual(set(g.state.players[2].hand),{original[i]for i in(0,2,4)})

    def test_magatha_wait_does_not_give_old_or_independent_reaction_spell(self):
        g=self.game((MAGATHA,BOLT),deck=(A,BOLT,BOLT,A,BOLT,A),watch=WATCH_DRAW);self.play(g,MAGATHA)
        self.portable(g);self.fault(g);self.choose(g,'extra');self.finish(g)
        self.assertEqual(self.hand(g).count(BOLT),2);self.assertEqual(self.hand(g,2),[BOLT]*2);self.portable(g)

    def test_magatha_full_opponent_hand_uses_ordinary_overflow(self):
        g=self.game((MAGATHA,),deck=(BOLT,A,BOLT,A,BOLT),enemy_hand=(A,)*10);self.play(g,MAGATHA)
        self.assertEqual(self.hand(g),[A,A]);self.assertEqual(self.hand(g,2),[A]*10)

    def test_barnes_random_physical_copy_is_one_one_without_moving_deck_or_battlecry(self):
        g=self.game((BARNES,),deck=(BC,BC));original=tuple(g.state.players[1].deck);self.play(g,BARNES)
        self.assertEqual(tuple(g.state.players[1].deck),original);copy=self.unit(g,BC)
        self.assertNotIn(copy.id,original);self.assertEqual((copy.attack,copy.health),(1,1));self.assertEqual(self.hero(g).armor,0)

    def test_barnes_empty_deck_and_full_board_do_not_consume_rng(self):
        for board,deck in(((),()),((A,)*6,(BC,BC))):
            g=self.game((BARNES,),board=board,deck=deck);before=g.snapshot()['rng_state'];self.play(g,BARNES)
            self.assertNotIn(BC,self.board(g));self.assertEqual(g.snapshot()['rng_state'],before)

    def test_barnes_selected_original_copy_wait_restores_without_resampling(self):
        g=self.game((BARNES,),deck=(BC,TAUNT),watch=WATCH_SUMMON);self.play(g,BARNES)
        self.portable(g);self.fault(g);selected=self.board(g)[-1];self.finish(g)
        self.assertEqual(self.board(g)[-1],selected);self.assertEqual(len(self.board(g)),2);self.portable(g)

    def test_vastann_natural_death_recruits_original_taunt_without_battlecry(self):
        g=self.game((KILL,),board=(VASTANN,),deck=(A,TAUNT));original=g.state.players[1].deck[1]
        self.play(g,KILL,self.unit(g,VASTANN).id);self.assertEqual(self.board(g),[TAUNT]);self.assertEqual(self.unit(g,TAUNT).id,original)
        self.assertEqual(self.hero(g).armor,0);self.assertEqual(len(g.state.players[1].deck),1)

    def test_whitemane_preserves_duplicate_physical_deaths_from_this_turn(self):
        g=self.game((KILL,KILL,WHITE),board=(A,A));self.play(g,KILL,self.unit(g,A).id);self.play(g,KILL,self.unit(g,A).id)
        self.play(g,WHITE);self.assertEqual(self.board(g),[WHITE,A,A]);self.assertEqual(len(g.state.death_history),2)

    def test_whitemane_excludes_previous_turn_and_enemy_death(self):
        g=self.game((KILL,KILL,KILL,WHITE),board=(A,A),enemy=(A,));self.play(g,KILL,self.unit(g,A).id)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,KILL,self.unit(g,A).id);self.play(g,KILL,self.unit(g,A,2).id)
        self.play(g,WHITE);self.assertEqual(self.board(g),[WHITE,A])

    def test_whitemane_wait_does_not_requery_new_reaction_deaths(self):
        g=self.game((KILL,KILL,WHITE),board=(A,A),watch=WATCH_SUMMON)
        self.play(g,KILL,self.unit(g,A).id);self.play(g,KILL,self.unit(g,A).id);self.play(g,WHITE)
        self.portable(g);self.fault(g);self.choose(g,'kill');self.finish(g)
        self.assertEqual(self.board(g),[WHITE,A]);self.assertEqual(len(g.state.death_history),3);self.portable(g)

    def test_valdris_expands_before_draw_and_preserves_capacity_after_source_death(self):
        g=self.game((VALDRIS,KILL)+(A,)*8);source=self.play(g,VALDRIS)
        self.assertEqual(g.state.players[1].hand_cap,12);self.assertEqual(len(self.hand(g)),12)
        self.assertEqual(len(self.original_draws(g,source)),4);self.play(g,KILL,source);self.assertEqual(g.state.players[1].hand_cap,12)

    def test_valdris_never_reduces_existing_larger_hand_capacity(self):
        g=self.game((RAISE,VALDRIS));self.play(g,RAISE);self.play(g,VALDRIS);self.assertEqual(g.state.players[1].hand_cap,15)

    def test_standard_host_real_artifact_draw_payment_and_recruit_entries(self):
        g=self.game((RAFAAM,),real_host=True);self.play(g,RAFAAM);self.choose(g,MIRROR);self.play(g,MIRROR)
        self.assertEqual(self.board(g).count(MUMMY),6)
        g=self.game((GHUUN,),deck=(BOLT,A),real_host=True);self.play(g,GHUUN)
        self.assertEqual(local_cost(self.entity(g,BOLT))[1],PaymentType.HEALTH)
        g=self.game((KILL,),board=(VASTANN,),deck=(TAUNT,),real_host=True);self.play(g,KILL,self.unit(g,VASTANN).id)
        self.assertEqual(self.board(g),[TAUNT])
