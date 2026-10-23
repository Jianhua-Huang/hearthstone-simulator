"""Actual passive entry points, qualified original facts, and recovery."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_passive_armor_spirit_cards import (
    DEAD, RHINO, ROCKSTAR, load_batch, register_past_passive_armor_spirit_cards)
from hs_sim.engine import (AppendageSpec, Attack, CardClass, CardDefinition, CardMetadata,
    CardType, EndTurn, Game, Keyword, PlayerSetup, RewindSpec, Scenario, SnapshotError,
    TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.armor_gains import ArmorGainBonusProfile, EVENT
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    Destroy, Draw, GainArmor, GrantKeyword, InvokeBehavior, RequestChoice, Silence, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import KeywordAuraSpec, LimitedTriggerSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import DrawMatching

P='k486.'
RUSH, PLAIN, FILLER, GIANT, LIMB, OBSERVER, HERO, WATCH=(P+x for x in
    ('rush-body','plain-body','filler','giant','limb','armor-observer','hero-card','watch'))
RUSH_AURA=P+'rush-aura'
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_passive_armor_spirit_cards(r);r._version=P+mode
    for cid,attack,health,cost,extra in((RUSH,2,4,1,{'keywords':(Keyword.RUSH,)}),
            (PLAIN,2,3,3,{}),(FILLER,0,6,0,{}),(LIMB,1,1,0,{}),
            (GIANT,3,5,1,{'keywords':(Keyword.RUSH,Keyword.COLOSSAL),
                'colossal':(AppendageSpec(LIMB),AppendageSpec(LIMB))}),
            (RUSH_AURA,0,6,1,{'keyword_auras':(KeywordAuraSpec(Keyword.RUSH,'friendly_minions',True),)})):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=META,**extra))
    r.register_behavior(P+'power',lambda c:())
    r.register_card(CardDefinition(P+'power',P+'power',CardType.HERO_POWER,cost=2,on_use=P+'power',metadata=META))
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,hero_card=True,health=30,hero_armor=5,
        initial_hero_power=P+'power',metadata=META))
    r.register_behavior(OBSERVER,lambda c:(Buff(c.state.players[c.player_id].hero_id,c.event.amount,0,c.source_id),)
        if c.event.player_id==c.player_id and c.event.amount>0 else())
    r.register_card(CardDefinition(OBSERVER,OBSERVER,CardType.MINION,health=9,metadata=META,
        triggers=(TriggerSpec(EVENT,OBSERVER),)))
    def fail(c):raise ResolutionError('K486 deliberate late failure')
    r.register_behavior(P+'fail',fail)
    targeted={'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'damage':lambda c:(Damage(c.target_id,1,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,2,3,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'rush':lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),),
        'reborn':lambda c:(GrantKeyword(c.target_id,Keyword.REBORN,c.source_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,1,c.source_id),),
        'rewind-kill':lambda c:(Destroy(c.target_id,c.source_id),)}
    scripts=dict(targeted,**{'armor':lambda c:(GainArmor(c.player_id,5),),
        'zero':lambda c:(GainArmor(c.player_id,0),),
        'enemy-armor':lambda c:(GainArmor(3-c.player_id,5),),
        'two-gains':lambda c:(GainArmor(c.player_id,1),GainArmor(c.player_id,1)),
        'spawn-rush':lambda c:(Summon(c.player_id,RUSH),),
        'fetch':lambda c:(DrawMatching(c.player_id,PoolQuery(card_ids=(PLAIN,)),'skip',source_id=c.source_id),),
        'draw':lambda c:(Draw(c.player_id,1,c.source_id),)})
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        extra=dict(keywords=(Keyword.REWIND,),rewind=RewindSpec())if key=='rewind-kill'else{}
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec()if key in targeted else None,**extra))
    def eligible(c):
        if mode in('armor_wait','bonus_wait'):
            row=dict(dict(c.event.data)['record'])
            return row['amount']>0 and (row['bonus_parent_id']is not None)==(mode=='bonus_wait')
        if mode=='armor_fail':return c.event.amount==2
        if mode=='limb_damage':return c.state.entities[c.event.target_id].card_id==LIMB
        if mode=='rush_wait':return c.state.entities[c.event.target_id].card_id==RUSH
        if mode in('copy_wait','copy_fail'):return c.state.entities[c.event.target_id].card_id==PLAIN
        return False
    def watch(c):
        if mode in('armor_fail','copy_fail'):return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if mode=='limb_damage':return(Damage(c.state.colossal_history[-1].entity_id,1,c.source_id),)
        options=(ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',
            (InvokeBehavior(P+'fail',c.source_id,c.player_id),)))
        if mode=='armor_wait':
            target=next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ROCKSTAR)
            options=(*options,ChoiceOption('kill','Kill source',(Destroy(target,c.source_id),)),
                ChoiceOption('give','Transfer source',(ChangeControl(target,3-c.player_id),)))
        return(RequestChoice(c.player_id,options,c.source_id),)
    event=(EVENT if mode in('armor_wait','bonus_wait')else'armor_gained'if mode=='armor_fail'
        else'card_added_to_deck'if mode in('copy_wait','copy_fail')else'minion_summoned')
    r.register_behavior(WATCH,watch);r.register_trigger_condition(P+'eligible',eligible)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
        limited_triggers=(LimitedTriggerSpec(event,WATCH,condition_id=P+'eligible'),)))
    r.validate();return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return value


class PastPassiveArmorSpiritTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),deck_size=12,mode='normal'):
        self.mode=mode
        if mode!='normal':board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(FILLER,)*deck_size,mana=40,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,
            deck=(FILLER,)*12,mana=40,max_mana=40,mana_cap=40)),seed=486),fixture(mode),Ruleset(max_hand=40))

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]
    def immune(self,g,eid):return Keyword.IMMUNE in g.state.entities[eid].keywords
    def copy_in_deck(self,g,card=PLAIN,player=1):
        return tuple(g.state.entities[i]for i in g.state.players[player].deck if g.state.entities[i].card_id==card)

    def test_complete_rows_primary_faces_and_explicit_printed_zeroes(self):
        d=load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(3,6))
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256'])
            batch.check_face(rows[o['card_id']],o['face'],o['locale'],
                numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
        r=build_registry();self.assertEqual((r.card(RHINO).attack,r.card(DEAD).attack),(0,0))
        self.assertTrue(all(cid in r.cards for cid in rows));self.assertFalse(d['cn_calibrated'])

    def test_one_rockstar_adds_one_real_child_grant(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,));self.play(g,P+'armor')
        self.assertEqual(self.hero(g).armor,7);rows=g.state.armor_gain_history
        self.assertEqual([x.amount for x in rows],[5,2]);self.assertEqual(rows[1].bonus_parent_id,rows[0].id)
        self.assertEqual(rows[1].bonus_source.card_id,ROCKSTAR)

    def test_two_rockstars_stack_without_self_or_cross_recursion(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,ROCKSTAR));before=g._rng.getstate();self.play(g,P+'armor')
        self.assertEqual(self.hero(g).armor,9);rows=g.state.armor_gain_history
        self.assertEqual([x.amount for x in rows],[5,2,2]);self.assertEqual({x.bonus_parent_id for x in rows[1:]},{1})
        self.assertEqual(len({x.bonus_source.entity_id for x in rows[1:]}),2);self.assertEqual(g._rng.getstate(),before)

    def test_each_original_occurrence_has_its_own_reward(self):
        g=self.game((P+'two-gains',),board=(ROCKSTAR,));self.play(g,P+'two-gains')
        self.assertEqual(self.hero(g).armor,6)
        self.assertEqual([x.amount for x in g.state.armor_gain_history],[1,2,1,2])

    def test_bonus_stays_visible_to_other_real_armor_consumers(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,OBSERVER));self.play(g,P+'armor')
        self.assertEqual((self.hero(g).armor,self.hero(g).attack),(7,7))

    def test_zero_and_opponent_gains_do_not_feed_friendly_listener(self):
        g=self.game((P+'zero',P+'enemy-armor'),board=(ROCKSTAR,));self.play(g,P+'zero');self.play(g,P+'enemy-armor')
        self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(0,5));self.assertEqual(len(g.state.armor_gain_history),2)

    def test_new_hero_armor_is_one_original_grant(self):
        g=self.game((HERO,),board=(ROCKSTAR,));self.play(g,HERO)
        self.assertEqual(self.hero(g).armor,7);rows=g.state.armor_gain_history
        self.assertEqual([r.origin for r in rows],['hero_card','gain_armor']);self.assertEqual(rows[1].bonus_parent_id,1)

    def test_source_silence_or_death_stops_future_roots(self):
        for operation in('silence','kill'):
            with self.subTest(operation=operation):
                g=self.game((P+operation,P+'armor'),board=(ROCKSTAR,));source=self.entity(g,ROCKSTAR,zone='board').id
                self.play(g,P+operation,source);self.play(g,P+'armor');self.assertEqual(self.hero(g).armor,5)

    def test_current_control_selects_original_gain_receiver(self):
        g=self.game((P+'give',P+'armor',P+'enemy-armor'),board=(ROCKSTAR,))
        self.play(g,P+'give',self.entity(g,ROCKSTAR,zone='board').id);self.play(g,P+'armor');self.play(g,P+'enemy-armor')
        self.assertEqual((self.hero(g).armor,self.hero(g,2).armor),(5,7))

    def test_accepted_reward_survives_source_departure_and_restores(self):
        for option in('kill','give'):
            with self.subTest(option=option):
                g=self.game((P+'armor',),board=(ROCKSTAR,),mode='armor_wait');self.play(g,P+'armor')
                self.assertEqual(self.hero(g).armor,5);other=self.portable(g)
                self.choose(g,option);self.choose(other,option);self.assertEqual(g.snapshot(),other.snapshot())
                self.assertEqual(self.hero(g).armor,7)

    def test_committed_child_wait_restores_and_does_not_repeat(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,),mode='bonus_wait');self.play(g,P+'armor')
        self.assertEqual(self.hero(g).armor,7);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.armor_gain_history),2)

    def test_late_bonus_observer_failure_rolls_back_original_and_child(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,),mode='armor_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'armor')
        self.assertEqual(g.snapshot(),saved)

    def test_rehashed_recursive_parent_and_boolean_actor_are_rejected(self):
        g=self.game((P+'armor',),board=(ROCKSTAR,));self.play(g,P+'armor')
        for operation in('parent','actor'):
            bad=deepcopy(g.snapshot());row=bad['state']['armor_gain_history'][1]
            if operation=='parent':row['bonus_parent_id']=row['id']
            else:row['bonus_source']['controller']=True
            with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('normal','reader'))

    def test_rhino_protects_new_rush_combat_and_expires_at_turn_change(self):
        g=self.game((RHINO,RUSH),enemy=(PLAIN,));spirit=self.play(g,RHINO);source=self.play(g,RUSH)
        self.assertTrue(self.immune(g,source));enemy=self.entity(g,PLAIN,2,'board').id
        g.apply(Attack(1,source,enemy));self.assertEqual(g.state.entities[source].health,4)
        g.apply(EndTurn(1));self.assertFalse(self.immune(g,source));self.assertIn(Keyword.STEALTH,g.state.entities[spirit].keywords)
        g.apply(EndTurn(2));self.assertNotIn(Keyword.STEALTH,g.state.entities[spirit].keywords)

    def test_old_rush_does_not_become_fresh_when_spirit_enters_later(self):
        g=self.game((RUSH,RHINO));source=self.play(g,RUSH);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,RHINO);self.assertFalse(self.immune(g,source))

    def test_awakening_does_not_reset_original_rush_birth_turn(self):
        g=self.game((RHINO,RUSH,P+'sleep'));self.play(g,RHINO);source=self.play(g,RUSH);self.play(g,P+'sleep',source)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIsNone(g.state.entities[source].dormancy)
        self.assertEqual(g.state.entities[source].summoned_turn,g.state.turn);self.assertFalse(self.immune(g,source))

    def test_control_sickness_does_not_reset_original_birth_turn(self):
        g=self.game((RUSH,P+'give'),enemy=(RHINO,));source=self.play(g,RUSH)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,P+'give',source)
        self.assertEqual(g.state.entities[source].controller,2);self.assertFalse(self.immune(g,source))

    def test_current_copy_has_a_new_original_birth(self):
        g=self.game((RHINO,RUSH,P+'copy'));self.play(g,RHINO);source=self.play(g,RUSH)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,P+'copy',source)
        copies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==RUSH and i!=source]
        self.assertEqual(len(copies),1);self.assertTrue(self.immune(g,copies[0]));self.assertFalse(self.immune(g,source))

    def test_actual_reborn_is_new_and_uses_one_health_material(self):
        g=self.game((RHINO,RUSH,P+'reborn',P+'kill'));self.play(g,RHINO);source=self.play(g,RUSH)
        self.play(g,P+'reborn',source);self.play(g,P+'kill',source)
        target=self.entity(g,RUSH,zone='board');self.assertNotEqual(target.id,source)
        self.assertTrue(self.immune(g,target.id));self.assertEqual(target.health,1)

    def test_native_source_removal_clears_only_its_aura(self):
        g=self.game((RHINO,RUSH,P+'silence'));spirit=self.play(g,RHINO);source=self.play(g,RUSH)
        self.play(g,P+'silence',spirit);self.assertFalse(self.immune(g,source));self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)

    def test_rush_gain_and_silence_recompute_from_fresh_keywords(self):
        g=self.game((RHINO,PLAIN,P+'rush',P+'silence'));self.play(g,RHINO);source=self.play(g,PLAIN)
        self.assertFalse(self.immune(g,source));self.play(g,P+'rush',source);self.assertTrue(self.immune(g,source))
        self.play(g,P+'silence',source);self.assertFalse(self.immune(g,source))

    def test_ordinary_rush_aura_is_an_input_and_its_loss_does_not_leave_immunity(self):
        g=self.game((RHINO,PLAIN,RUSH_AURA,P+'kill'));self.play(g,RHINO);source=self.play(g,PLAIN)
        aura=self.play(g,RUSH_AURA);self.assertTrue(self.immune(g,source))
        self.play(g,P+'kill',aura);self.assertFalse(self.immune(g,source));self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords)

    def test_colossal_parent_is_protected_before_limb_callbacks(self):
        g=self.game((RHINO,GIANT),mode='limb_damage');self.play(g,RHINO);source=self.play(g,GIANT)
        self.assertTrue(self.immune(g,source));self.assertEqual(g.state.entities[source].health,5)

    def test_first_summon_observer_sees_immunity_and_wait_restores(self):
        g=self.game((RHINO,RUSH),mode='rush_wait');self.play(g,RHINO);source=self.play(g,RUSH)
        self.assertTrue(self.immune(g,source));other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertTrue(self.immune(g,source))

    def test_spirit_dead_uses_base_recipe_and_actual_one_mana_draw(self):
        g=self.game((P+'buff',P+'damage',P+'kill',P+'fetch'),board=(DEAD,PLAIN))
        source=self.entity(g,PLAIN,zone='board').id;self.play(g,P+'buff',source);self.play(g,P+'damage',source)
        self.play(g,P+'kill',source);copies=self.copy_in_deck(g);self.assertEqual(len(copies),1)
        self.assertEqual((copies[0].base_attack,copies[0].base_health,copies[0].damage),(2,3,0))
        self.assertNotEqual(copies[0].id,source);self.assertEqual(copies[0].origin_entity_id,source)
        self.play(g,P+'fetch');target=self.entity(g,PLAIN).id;before=g.state.players[1].mana;self.play(g,PLAIN)
        self.assertEqual(g.state.players[1].mana,before-1);self.assertEqual(g.state.entities[target].attack,2)
        self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_enemy_death_is_excluded_and_no_source_self_copy(self):
        g=self.game((P+'kill',),board=(DEAD,),enemy=(PLAIN,));self.play(g,P+'kill',self.entity(g,PLAIN,2,'board').id)
        self.assertFalse(self.copy_in_deck(g))
        g=self.game((P+'kill',),board=(DEAD,));self.play(g,P+'kill',self.entity(g,DEAD,zone='board').id)
        self.assertFalse(self.copy_in_deck(g,DEAD))

    def test_two_spirits_each_keep_one_independent_death_copy(self):
        g=self.game((P+'kill',),board=(DEAD,DEAD,PLAIN));self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id)
        self.assertEqual(len(self.copy_in_deck(g)),2)
        self.assertEqual(len(g.state.deck_shuffle_history),2)

    def test_silence_stops_future_death_copies(self):
        g=self.game((P+'silence',P+'kill'),board=(DEAD,PLAIN));self.play(g,P+'silence',self.entity(g,DEAD,zone='board').id)
        self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id);self.assertFalse(self.copy_in_deck(g))

    def test_sparse_rewind_death_id_still_copies_the_exact_original_record(self):
        g=self.game((P+'rewind-kill',),board=(DEAD,PLAIN));source=self.entity(g,PLAIN,zone='board').id
        self.play(g,P+'rewind-kill',source);self.assertIsNotNone(g.state.pending_choice);self.choose(g,'retry')
        self.assertGreater(g.state.death_history[0].id,len(g.state.death_history))
        self.assertEqual(len(self.copy_in_deck(g)),1);self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g)

    def test_full_deck_is_shared_admission_failure_without_allocation(self):
        g=self.game((P+'kill',),board=(DEAD,PLAIN),deck_size=99);before=g.state.next_entity_id
        self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id)
        self.assertEqual(len(g.state.players[1].deck),99);self.assertEqual(g.state.next_entity_id,before)
        self.assertFalse(g.state.deck_shuffle_history)

    def test_copied_deck_entry_wait_restores_and_keeps_one_shuffle(self):
        g=self.game((P+'kill',),board=(DEAD,PLAIN),mode='copy_wait');self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id)
        self.assertEqual(len(self.copy_in_deck(g)),1);other=self.portable(g);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.deck_shuffle_history),1)

    def test_late_copy_failure_rolls_back_death_shuffle_and_rng(self):
        g=self.game((P+'kill',),board=(DEAD,PLAIN),mode='copy_fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id)
        self.assertEqual(g.snapshot(),saved)

    def test_finite_profiles_preserve_defaults_and_private_proofs(self):
        with self.assertRaises(ValueError):ArmorGainBonusProfile('a','b',3)
        with self.assertRaises(ValueError):KeywordAuraSpec(Keyword.CHARGE,'friendly_minions',True,condition='rush_summon_turn')
        self.assertEqual(defaults().fingerprint(),'b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a')
        g=self.game((P+'armor',),board=(ROCKSTAR,));self.play(g,P+'armor')
        for pid in(1,2):
            view=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))
            for private in('bonus_parent_id','bonus_source','armor_gain_history',EVENT):self.assertNotIn(private,view)
