"""Actual conditions, original keyword tutors, continuous sources and native damage."""
from functools import lru_cache
import unittest
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import past_condition_tutor_aura_consumers as native
from hs_sim.engine import Attack,EndTurn,Game,IllegalAction,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,Draw,GainArmor,InvokeBehavior,
    Overload,RandomDamage,RequestChoice,Silence)
from hs_sim.engine.hand_keywords import GrantStoredKeyword
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (AuraSpec,BoardPresenceReference,CardClass,CardDefinition,CardType,DamageKind,
    Keyword,PlayerEffectSpec,SpellSchool,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup,FROST_FOLLOWUP,SOURCE_KEYWORDS
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.registry import Registry
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.zones import CardReference
from hs_sim.local_pool_format import build_cn37_local_pool_format

TYRANT,OZRUK,TURALYON,MAL,VESSINA,YIP,CATRINA,FRIG,SESELI,VARIAN,ASHMORE,RAS=native.ROOTS
P='k705.';A=P+'plain';ZERO=P+'zero';TEN=P+'ten';ELEVEN=P+'eleven';DEMON=P+'demon';ELEM=P+'elemental';ALL=P+'all';UNDEAD=P+'undead';DORMANT=P+'dormant'
RUSH=P+'rush';TAUNT=P+'taunt';SHIELD=P+'shield';MULTI=P+'multi';POWER=P+'power';NATURE_POWER=P+'nature_power';BOOST=P+'boost_minion';BOOST_SPEC=P+'next_bonus'
FROST=P+'frost';ARCANE=P+'arcane';LIFE_SPELL=P+'lifesteal_spell';DR_WEAPON=P+'deathrattle_weapon'
KILL=P+'kill';HUSH=P+'silence';GIVE=P+'give';LOAD=P+'overload';ARMOR4=P+'armor4';ARMOR14=P+'armor14';DECK_RUSH=P+'deck_rush';QUEUE=P+'queued_native_damage';FAIL=P+'fail'
WATCH_DRAW=P+'draw_watch';WATCH_KEYWORD=P+'keyword_watch';WATCH_DAMAGE=P+'damage_watch';WATCH_STATS=P+'stats_watch'
HELPERS=(A,ZERO,TEN,ELEVEN,DEMON,ELEM,ALL,UNDEAD,DORMANT,RUSH,TAUNT,SHIELD,MULTI,POWER,NATURE_POWER,BOOST,
    FROST,ARCANE,LIFE_SPELL,DR_WEAPON,KILL,HUSH,GIVE,LOAD,ARMOR4,ARMOR14,DECK_RUSH,QUEUE,WATCH_DRAW,WATCH_KEYWORD,WATCH_DAMAGE,WATCH_STATS)
CTX=GenerationContext('k705-explicit-small-fixture','experimental')


@lru_cache(None)
def host(role='writer'):
    h=build_cn37_local_pool_format();r=h.registry;meta=metadata(CardClass.MAGE,collectible=False)
    r.register_behavior(P+'boost',lambda c:(AddPlayerEffect(c.player_id,BOOST_SPEC,c.source_id),))
    for cid,attack,hp,cost,tribes,keys in((A,2,12,3,(),()),(ZERO,1,4,0,(),()),(TEN,4,7,10,(),()),(ELEVEN,4,7,11,(),()),
            (DEMON,4,6,3,('demon',),()),(ELEM,1,2,0,('elemental',),()),(ALL,1,2,0,('all',),()),(UNDEAD,1,5,2,('undead',),()),
            (DORMANT,2,12,3,(),()),(RUSH,2,4,3,(),(Keyword.RUSH,)),(TAUNT,3,5,4,(),(Keyword.TAUNT,)),
            (SHIELD,1,5,1,(),(Keyword.DIVINE_SHIELD,)),(MULTI,2,2,2,(),(Keyword.RUSH,Keyword.TAUNT,Keyword.DIVINE_SHIELD)),
            (POWER,1,4,1,(),()),(NATURE_POWER,1,4,1,(),()),(BOOST,1,4,1,(),())):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=hp,
            metadata=metadata(CardClass.MAGE,tribes=tribes,collectible=cid in(ZERO,A,TEN,ELEVEN)),keywords=keys,
            dormant_turns=2 if cid==DORMANT else 0,spell_damage=3 if cid==POWER else 7 if cid==NATURE_POWER else 0,
            spell_damage_schools=(SpellSchool.NATURE,)if cid==NATURE_POWER else(),battlecry=P+'boost'if cid==BOOST else None))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_player_effect(PlayerEffectSpec(BOOST_SPEC,BOOST,kind='next_spell_damage_until_cast',spell_damage=5))
    r.register_behavior(FAIL,lambda c:(_ for _ in()).throw(ResolutionError('K705 intentional original continuation failure')))
    def menu(c,extra=()):
        return RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),ChoiceOption('fault','Failure',(
            RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,c.player_id))),*extra),c.source_id)
    def waiting(c):
        source=c.state.entities.get(c.event.source_id);extra=()
        if c.event.kind=='card_drawn':
            if source is None or source.card_id not in(FRIG,VARIAN,ASHMORE):return()
            extra=(ChoiceOption('extra','Independent draw',(Draw(c.player_id,1,c.source_id),)),
                ChoiceOption('remove','Destroy original source',(Destroy(source.id,c.source_id),)))
        elif c.event.kind=='ability_granted':
            target=c.state.entities[c.event.target_id]
            if target.card_id!=VARIAN:return()
            extra=(ChoiceOption('remove','Return original source',(
                ReturnCapturedMinion(MinionReference.capture(target),c.source_id),)),)
        elif c.event.kind=='damage_dealt':
            if source is None or source.card_id not in(RAS,FRIG):return()
        elif source is None or source.card_id!=TURALYON:return()
        return(menu(c,extra),)
    r.register_behavior(P+'wait',waiting)
    def queued(c):
        source=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==RAS)
        power=next(c.state.entities[i]for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==POWER)
        return(menu(c,(ChoiceOption('remove','Remove provider',(Destroy(power.id,c.source_id),)),)),
            Damage(c.state.players[2].hero_id,1,source.id,DamageKind.MINION_ABILITY,affected_by_spell_damage=True))
    def deck_rush(c):
        return tuple(GrantStoredKeyword(CardReference.capture(c.state.entities[i]),Keyword.RUSH,c.source_id)
            for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==A)
    scripts={FROST:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        ARCANE:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        LIFE_SPELL:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        KILL:lambda c:(Destroy(c.target_id,c.source_id),),HUSH:lambda c:(Silence(c.target_id),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),LOAD:lambda c:(Overload(c.player_id,2),),
        ARMOR4:lambda c:(GainArmor(c.player_id,4),),ARMOR14:lambda c:(GainArmor(c.player_id,14),),DECK_RUSH:deck_rush,QUEUE:queued}
    for cid,body in scripts.items():
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,metadata=meta,
            spell_school=SpellSchool.FROST if cid==FROST else SpellSchool.ARCANE,
            keywords=(Keyword.LIFESTEAL,)if cid==LIFE_SPELL else(),
            targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))if cid in(FROST,ARCANE,LIFE_SPELL,KILL,HUSH,GIVE)else None))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(P+'weapon_death',lambda c:(GainArmor(c.player_id,2),))
    r.register_card(CardDefinition(DR_WEAPON,DR_WEAPON,CardType.WEAPON,cost=2,attack=1,durability=3,metadata=meta,deathrattle=P+'weapon_death'))
    r.register_pool_card(PoolCard.from_definition(r.card(DR_WEAPON)))
    for cid,event in((WATCH_DRAW,'card_drawn'),(WATCH_KEYWORD,'ability_granted'),(WATCH_DAMAGE,'damage_dealt'),(WATCH_STATS,'stats_changed')):
        r.register_card(CardDefinition(cid,cid,CardType.WEAPON,durability=20,metadata=meta,triggers=(TriggerSpec(event,P+'wait'),)))
    r.validate();return h


@lru_cache(None)
def fixture(role='writer'):
    full=host(role).registry;r=Registry('k705-condition-tutor-aura-v1')
    for bid,body in full._behaviors.items():
        if bid not in r._behaviors and not bid.startswith(native.PREFIX):r.register_behavior(bid,body)
    for cid in('HERO_08','HERO_08bp',*HELPERS):
        r.register_card(full.card(cid))
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    r.register_player_effect(full.player_effect(BOOST_SPEC));native.register_past_condition_tutor_aura_consumers(r)
    r.register_pool(PoolDefinition('constructed.cards','explicit-fixture-v1',CTX.target_id,CTX.mode,tuple(PoolMember(cid)for cid in(ZERO,A,TEN,ELEVEN))))
    r.validate();return r


class PastConditionTutorAuraTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*12,enemy_hand=(),watch=None,crystals=30,real_host=False,seed=705):
        self.mode='host'if real_host else'small';h=host()
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=crystals,max_mana=crystals,mana_cap=30,
            hero_power_card_id='HERO_08bp',weapon_card_id=watch),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(A,)*12,mana=30,max_mana=30,mana_cap=30,hero_power_card_id='HERO_08bp')),
            seed=seed,generation_context=h.context if real_host else CTX),h.registry if real_host else fixture())
    def hero(self,g,p=1):return g.state.entities[g.state.players[p].hero_id]
    def unit(self,g,cid,p=1):return self.entity(g,cid,p,'board')
    def hand(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].hand]
    def board(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def finish(self,g):
        while g.state.pending_choice is not None:self.choose(g)
    def fault(self,g):
        before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before)
    def own_turn(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
    def original_draws(self,g,source):return[x for x in g.state.draw_history if x.source_id==source and x.parent_id is None]

    def test_twelve_complete_faces_and_entire_original_past_source(self):
        d=native.load_batch();self.assertEqual(len(d['official_observations']),26);self.assertEqual(len(d['original_candidate_ids']),732)
        self.assertEqual(d['dependencies'],[])
        for row in d['cards']:
            cid=row['record']['id'];self.assertEqual(fixture().card(cid),native.make_definition(row['record']))
            self.assertEqual(fixture().pool_card(cid),PoolCard.from_definition(fixture().card(cid)))

    def test_all_twelve_have_one_actual_normal_paid_hand_entry(self):
        for cid in native.ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));self.play(g,cid);self.assertEqual(g.state.players[1].mana,30-fixture().card(cid).cost)
                self.assertEqual(sum(x.card_id==cid and x.player_id==1 for x in g.state.play_history),1)

    def test_tyrant_threshold_uses_crystals_not_remaining_mana(self):
        g=self.game((TYRANT,),crystals=10);source=self.play(g,TYRANT);self.assertEqual(g.state.players[1].mana,4)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(14,14))
        g=self.game((TYRANT,),crystals=9);self.play(g,TYRANT);self.assertEqual(self.unit(g,TYRANT).attack,7)

    def test_tyrant_printed_taunt_and_elusive_protect_actual_spell_target(self):
        g=self.game((TYRANT,ARCANE));self.play(g,TYRANT);source=self.unit(g,TYRANT).id;before=g.snapshot()
        self.assertTrue({Keyword.TAUNT,Keyword.ELUSIVE}<=g.state.entities[source].keywords)
        with self.assertRaises(IllegalAction):self.play(g,ARCANE,source)
        self.assertEqual(g.snapshot(),before)

    def test_ozruk_counts_each_original_previous_owner_turn_elemental_and_all(self):
        g=self.game((ELEM,ELEM,ALL,OZRUK));self.play(g,ELEM);self.play(g,ELEM);self.play(g,ALL);self.own_turn(g);self.play(g,OZRUK)
        self.assertEqual(self.unit(g,OZRUK).health,23)

    def test_ozruk_excludes_current_turn_summons_and_opponent_plays(self):
        g=self.game((ELEM,OZRUK),board=(ELEM,),enemy_hand=(ELEM,));self.play(g,ELEM);self.play(g,OZRUK)
        self.assertEqual(self.unit(g,OZRUK).health,8)
        g=self.game((OZRUK,),enemy_hand=(ELEM,));g.apply(EndTurn(1));self.play(g,ELEM,player=2);g.apply(EndTurn(2));self.play(g,OZRUK)
        self.assertEqual(self.unit(g,OZRUK).health,8)

    def test_turalyon_sets_original_minion_before_his_real_rush_combat(self):
        g=self.game((TURALYON,),enemy=(TEN,));source=self.play(g,TURALYON);target=self.unit(g,TEN,2).id;g.apply(Attack(1,source,target))
        self.assertEqual(g.state.entities[target].health,0);self.assertEqual(g.state.entities[source].health,9)

    def test_turalyon_excludes_other_attacker_and_hero_targets(self):
        g=self.game(board=(TURALYON,A),enemy=(TEN,));g.apply(Attack(1,self.unit(g,A).id,self.unit(g,TEN,2).id))
        self.assertEqual(self.unit(g,TEN,2).attack,4)
        g=self.game(board=(TURALYON,));g.apply(Attack(1,self.unit(g,TURALYON).id,self.hero(g,2).id));self.assertEqual(self.hero(g,2).health,27)

    def test_turalyon_attack_stat_wait_restores_replays_and_rolls_back_failure(self):
        g=self.game(board=(TURALYON,),enemy=(TEN,),watch=WATCH_STATS)
        g.apply(Attack(1,self.unit(g,TURALYON).id,self.unit(g,TEN,2).id));self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.unit(g,TURALYON).health,9);self.portable(g)

    def test_malganis_continuous_other_current_demons_and_hero_immunity(self):
        g=self.game((MAL,ARCANE),board=(DEMON,ALL,A));self.play(g,MAL)
        self.assertEqual((self.unit(g,DEMON).attack,self.unit(g,DEMON).health),(6,8));self.assertEqual(self.unit(g,ALL).attack,3)
        self.assertEqual(self.unit(g,A).attack,2);self.assertEqual(self.unit(g,MAL).attack,9)
        self.assertIn(Keyword.IMMUNE,self.hero(g).keywords);self.play(g,ARCANE,self.hero(g).id);self.assertEqual(self.hero(g).health,30)

    def test_malganis_silence_and_control_change_retire_or_redirect_both_auras(self):
        g=self.game((HUSH,),board=(MAL,DEMON));self.play(g,HUSH,self.unit(g,MAL).id)
        self.assertEqual(self.unit(g,DEMON).attack,4);self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords)
        g=self.game((GIVE,),board=(MAL,DEMON),enemy=(DEMON,));self.play(g,GIVE,self.unit(g,MAL).id)
        self.assertEqual(self.unit(g,DEMON).attack,4);self.assertEqual(self.unit(g,DEMON,2).attack,6)
        self.assertNotIn(Keyword.IMMUNE,self.hero(g).keywords);self.assertIn(Keyword.IMMUNE,self.hero(g,2).keywords)

    def test_vessina_tracks_pending_locked_and_naturally_cleared_overload(self):
        g=self.game((LOAD,),board=(VESSINA,A));self.assertEqual(self.unit(g,A).attack,2);self.play(g,LOAD)
        self.assertEqual(self.unit(g,A).attack,4);self.assertEqual(self.unit(g,VESSINA).attack,2);self.own_turn(g)
        self.assertEqual(g.state.players[1].overload_locked,2);self.assertEqual(self.unit(g,A).attack,4);self.own_turn(g)
        self.assertEqual(g.state.players[1].overload_locked,0);self.assertEqual(self.unit(g,A).attack,2)

    def test_vessina_current_controller_not_former_overloaded_owner_and_silence(self):
        g=self.game((LOAD,GIVE),board=(VESSINA,A),enemy=(A,));self.play(g,LOAD);self.play(g,GIVE,self.unit(g,VESSINA).id)
        self.assertEqual(self.unit(g,A).attack,2);self.assertEqual(self.unit(g,A,2).attack,2)
        g=self.game((LOAD,HUSH),board=(VESSINA,A));self.play(g,LOAD);self.play(g,HUSH,self.unit(g,VESSINA).id)
        self.assertEqual(self.unit(g,A).attack,2);self.portable(g)

    def test_yip_uses_actual_armor_zero_and_caps_above_ten_at_own_end(self):
        g=self.game(board=(YIP,));g.apply(EndTurn(1));self.assertEqual(self.board(g),[YIP,ZERO])
        g=self.game((ARMOR14,),board=(YIP,));self.play(g,ARMOR14);g.apply(EndTurn(1));self.assertEqual(self.board(g),[YIP,TEN])
        g.apply(EndTurn(2));self.assertEqual(self.board(g),[YIP,TEN])

    def test_yip_full_board_does_not_sample_a_generation_candidate(self):
        g=self.game(board=(YIP,)+(A,)*6);before=g.snapshot()['rng_state'];g.apply(EndTurn(1))
        self.assertEqual(len(self.board(g)),7);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_yip_real_host_queries_complete_actual_cost_domain(self):
        h=host();query=PoolQuery(kinds=(CardType.MINION,),min_cost=4,max_cost=4,collectible=True)
        expected=resolve_candidates(h.registry,h.context,'constructed.cards',query,source_card_id=YIP,player_id=1,exclude_source_by_rule=True)
        self.assertGreater(len(expected),10);g=self.game((ARMOR4,),board=(YIP,),real_host=True);self.play(g,ARMOR4);g.apply(EndTurn(1))
        generated=[i for i in g.state.players[1].board if g.state.entities[i].card_id!=YIP]
        self.assertEqual(len(generated),1);self.assertIn(g.state.entities[generated[0]].card_id,{x.card_id for x in expected})

    def test_catrina_resurrects_original_friendly_undead_not_other_minions(self):
        g=self.game((KILL,KILL),board=(CATRINA,UNDEAD,A));dead=self.unit(g,UNDEAD).id
        self.play(g,KILL,dead);self.play(g,KILL,self.unit(g,A).id);g.apply(EndTurn(1))
        self.assertEqual(self.board(g),[CATRINA,UNDEAD]);self.assertNotEqual(self.unit(g,UNDEAD).id,dead)

    def test_catrina_empty_or_enemy_only_history_has_no_randomness(self):
        g=self.game((KILL,),board=(CATRINA,),enemy=(UNDEAD,));self.play(g,KILL,self.unit(g,UNDEAD,2).id)
        before=g.snapshot()['rng_state'];g.apply(EndTurn(1));self.assertEqual(self.board(g),[CATRINA]);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_frigidara_two_original_frost_spells_damage_all_enemies_without_spell_bonus(self):
        g=self.game((FRIG,),board=(POWER,),enemy=(A,),deck=(FROST,FROST,A));source=self.play(g,FRIG)
        self.assertEqual(self.hand(g),[FROST,FROST]);self.assertEqual(len(self.original_draws(g,source)),2)
        self.assertEqual(self.hero(g,2).health,28);self.assertEqual(self.unit(g,A,2).health,10)

    def test_frigidara_mixed_or_missing_second_spell_does_not_trigger_condition(self):
        for deck in((FROST,ARCANE),(FROST,A),()):
            with self.subTest(deck=deck):
                g=self.game((FRIG,),deck=deck);self.play(g,FRIG);self.assertEqual(self.hero(g,2).health,30)
                self.assertEqual(self.hero(g).health,30)

    def test_frigidara_original_burned_frost_still_qualifies(self):
        g=self.game((FRIG,)+(A,)*9,deck=(FROST,FROST));source=self.play(g,FRIG)
        self.assertEqual(len(self.hand(g)),10);self.assertEqual({x.outcome for x in self.original_draws(g,source)},{'hand','burned'})
        self.assertEqual(self.hero(g,2).health,28)

    def test_frigidara_independent_frost_draw_does_not_replace_missing_original_slot(self):
        g=self.game((FRIG,),deck=(FROST,FROST,A),watch=WATCH_DRAW);source=self.play(g,FRIG)
        self.portable(g);self.fault(g);self.choose(g,'extra');self.finish(g)
        self.assertEqual(self.hand(g),[FROST,FROST]);self.assertEqual(len(self.original_draws(g,source)),1)
        self.assertEqual(self.hero(g,2).health,30);self.portable(g)

    def test_frigidara_original_draw_wait_continues_after_source_natural_death(self):
        g=self.game((FRIG,),deck=(FROST,FROST),watch=WATCH_DRAW);self.play(g,FRIG);self.portable(g)
        self.choose(g,'remove');self.finish(g);self.assertEqual(self.hero(g,2).health,28);self.portable(g)

    def test_seseli_real_death_draws_original_minion_and_discounts_only_it(self):
        g=self.game((KILL,A),board=(SESELI,),deck=(TEN,FROST));source=self.unit(g,SESELI).id;self.play(g,KILL,source)
        self.assertEqual(self.hand(g),[A,TEN]);self.assertEqual(local_cost(self.entity(g,TEN))[0],2)
        self.assertEqual(local_cost(self.entity(g,A))[0],3);self.assertEqual(len(self.original_draws(g,source)),1)

    def test_varian_each_current_keyword_tutor_grants_exact_corresponding_keyword(self):
        g=self.game((VARIAN,),deck=(MULTI,TAUNT,SHIELD));source=self.play(g,VARIAN)
        self.assertEqual(self.hand(g),[MULTI,TAUNT,SHIELD]);self.assertEqual(len(self.original_draws(g,source)),3)
        self.assertTrue({Keyword.RUSH,Keyword.TAUNT,Keyword.DIVINE_SHIELD}<=g.state.entities[source].keywords)

    def test_varian_missing_slots_never_grant_their_keywords_or_fatigue(self):
        g=self.game((VARIAN,),deck=(SHIELD,));self.play(g,VARIAN);source=self.unit(g,VARIAN)
        self.assertIn(Keyword.DIVINE_SHIELD,source.keywords);self.assertNotIn(Keyword.RUSH,source.keywords);self.assertNotIn(Keyword.TAUNT,source.keywords)
        g=self.game((VARIAN,),deck=());before=g.snapshot()['rng_state'];self.play(g,VARIAN)
        self.assertFalse(g.state.draw_history);self.assertEqual(g.snapshot()['rng_state'],before)

    def test_varian_reads_actual_granted_current_deck_rush(self):
        g=self.game((DECK_RUSH,VARIAN),deck=(A,));original=g.state.players[1].deck[0];self.play(g,DECK_RUSH);self.play(g,VARIAN)
        self.assertEqual(self.entity(g,A).id,original);self.assertIn(Keyword.RUSH,self.unit(g,VARIAN).keywords)

    def test_varian_keyword_grant_wait_precedes_next_slot_and_keeps_original_source(self):
        g=self.game((VARIAN,),deck=(RUSH,TAUNT,SHIELD),watch=WATCH_KEYWORD);source=self.play(g,VARIAN)
        self.assertEqual(len(self.original_draws(g,source)),1);self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords);self.portable(g);self.fault(g)
        self.choose(g,'remove');self.finish(g);self.assertEqual(len(self.original_draws(g,source)),3)
        self.assertEqual(self.entity(g,VARIAN).id,source);self.assertFalse({Keyword.RUSH,Keyword.TAUNT,Keyword.DIVINE_SHIELD}&self.entity(g,VARIAN).keywords)
        self.portable(g)

    def test_varian_burned_original_matches_still_grant_source_keywords(self):
        g=self.game((VARIAN,)+(A,)*9,deck=(RUSH,TAUNT,SHIELD));source=self.play(g,VARIAN)
        self.assertEqual([x.outcome for x in self.original_draws(g,source)],['hand','burned','burned'])
        self.assertTrue({Keyword.RUSH,Keyword.TAUNT,Keyword.DIVINE_SHIELD}<=g.state.entities[source].keywords)

    def test_ashmore_broad_lifesteal_spell_and_deathrattle_weapon_are_real_physical_draws(self):
        g=self.game((ASHMORE,),deck=(RUSH,LIFE_SPELL,DR_WEAPON,A));original=set(g.state.players[1].deck);source=self.play(g,ASHMORE)
        self.assertEqual(self.hand(g),[RUSH,LIFE_SPELL,DR_WEAPON]);self.assertTrue(set(g.state.players[1].hand)<=original)
        self.assertEqual(len(self.original_draws(g,source)),3);self.assertEqual(self.hero(g).armor,0)

    def test_ashmore_current_keyword_and_draw_wait_restore_without_duplicate_draws(self):
        g=self.game((DECK_RUSH,ASHMORE),deck=(A,LIFE_SPELL,DR_WEAPON),watch=WATCH_DRAW);self.play(g,DECK_RUSH);source=self.play(g,ASHMORE)
        self.portable(g);self.fault(g);self.finish(g);self.assertEqual(self.hand(g),[A,LIFE_SPELL,DR_WEAPON])
        self.assertEqual(len(self.original_draws(g,source)),3);self.portable(g)

    def test_ras_ordinary_unschooled_spell_bonus_retains_minion_damage_and_no_cast(self):
        g=self.game(board=(RAS,POWER,NATURE_POWER),enemy=(A,));before=len(g.state.cast_history);g.apply(EndTurn(1))
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual(self.unit(g,A,2).health,8);self.assertEqual(len(g.state.cast_history),before)
        results=[health_result(e)for e in g.events if e.kind=='health_resolved'and e.source_id==self.unit(g,RAS).id]
        self.assertEqual(len(results),2)
        for r in results:self.assertEqual((r.base_amount,r.spell_bonus,r.damage_kind),(1,3,DamageKind.MINION_ABILITY.value))

    def test_ras_does_not_claim_pending_next_spell_bonus_or_run_at_enemy_end(self):
        g=self.game((BOOST,ARCANE),board=(RAS,));self.play(g,BOOST);g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,29)
        self.assertEqual(len(g.state.players[1].player_effects),1);g.apply(EndTurn(2));self.assertEqual(self.hero(g,2).health,29)
        self.play(g,ARCANE,self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,23)
        self.assertFalse(g.state.players[1].player_effects)

    def test_ras_silence_removes_end_source_and_provider_removal_changes_later_numeric_quote(self):
        g=self.game((HUSH,),board=(RAS,POWER));self.play(g,HUSH,self.unit(g,RAS).id);g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,30)
        g=self.game((QUEUE,),board=(RAS,POWER));self.play(g,QUEUE);restored=self.portable(g);self.fault(g)
        self.choose(g,'remove');self.choose(restored,'remove');self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hero(g,2).health,29)

    def test_ras_real_damage_wait_restores_and_replays_original_bonus_once(self):
        g=self.game(board=(RAS,POWER),enemy=(A,),watch=WATCH_DAMAGE);g.apply(EndTurn(1));self.portable(g);self.fault(g);self.finish(g)
        self.assertEqual(self.hero(g,2).health,26);self.assertEqual(self.unit(g,A,2).health,8);self.portable(g)

    def test_public_profiles_reject_non_native_keyword_frost_aura_or_damage_shapes(self):
        g=self.game(board=(VARIAN,));ref=BoardPresenceReference.capture(g.state,self.unit(g,VARIAN).id)
        invalid=(lambda:DrawGroupSlot(None,current_keywords_all=(Keyword.RUSH,)),
            lambda:DrawGroupSlot(PoolQuery(),current_keywords_all=(Keyword.RUSH,Keyword.TAUNT)),
            lambda:DrawGroupSlot(PoolQuery(),current_keywords_all=('rush',)),
            lambda:DrawPhysicalGroup(1,ref.entity_id,(DrawGroupSlot(),)*3,DrawGroupReward(SOURCE_KEYWORDS,source=ref)),
            lambda:DrawPhysicalGroup(1,ref.entity_id,(DrawGroupSlot(),)*2,DrawGroupReward(FROST_FOLLOWUP,behavior_id=native.PREFIX+'frost_damage')),
            lambda:AuraSpec(2,include_self=True,condition='controller_overloaded').__post_init__(),
            lambda:Damage(self.hero(g,2).id,1,ref.entity_id,DamageKind.EFFECT,affected_by_spell_damage=True),
            lambda:Damage(self.hero(g,2).id,1,ref.entity_id,DamageKind.MINION_ABILITY,affected_by_spell_damage=1))
        for create in invalid:
            with self.subTest(create=create),self.assertRaises(ValueError):create()

    def test_standard_host_real_frost_keyword_and_native_spell_bonus_entries(self):
        g=self.game((FRIG,),deck=(FROST,FROST),real_host=True);self.play(g,FRIG);self.assertEqual(self.hero(g,2).health,28)
        g=self.game((VARIAN,),deck=(RUSH,TAUNT,SHIELD),real_host=True);self.play(g,VARIAN);self.assertIn(Keyword.DIVINE_SHIELD,self.unit(g,VARIAN).keywords)
        g=self.game(board=(RAS,POWER),real_host=True);g.apply(EndTurn(1));self.assertEqual(self.hero(g,2).health,26)
