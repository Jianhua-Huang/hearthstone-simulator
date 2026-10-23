"""Real one-use gifts at their distinct original entry/material windows."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.past_next_tribal_entry_buff_cards import (
    MUSIC, STAR, PROGRAMS, load_batch, register_past_next_tribal_entry_buff_cards)
from hs_sim.engine import (Attack, CardClass, CardDefinition, CardMetadata, CardType, CounterMinion,
    AppendageSpec, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Scenario, SetSecret, SnapshotError, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy, GainArmor,
    InvokeBehavior, RefreshMana, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec, SecretSpec, SummonStats
from hs_sim.engine.representative import build_registry as defaults
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_entry_stats import ACCEPTED, APPLIED, ENTRY, SummonEntryStatsProfile
from hs_sim.engine.summon_completions import AFTER, CLOSED
from hs_sim.engine.zones import CardReference
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE as PHYSICAL_PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards

P = 'k484.'
COPY_SELF, GIANT, LIMB = (P+x for x in ('copy_self','giant','limb'))
QUANTITY=P+'quantity'
BEAST, DRAENEI, PLAIN, READER, MAGNET, HOST, DORMANT, REBORN, UNKNOWN, WATCH, SECRET = (
    P+x for x in ('beast', 'draenei', 'plain', 'reader', 'magnet', 'host', 'dormant', 'reborn', 'unknown', 'watch', 'secret'))
META = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())


def meta(tribes): return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = defaults(); register_past_next_tribal_entry_buff_cards(r); r._version = P+mode
    def reader(c):
        body=(GainArmor(c.player_id,c.source.attack),)
        return (*menu(c),*body) if mode=='physical_wait' and c.physical is not None else body
    r.register_behavior(P+'read', reader)
    for cid, attack, health, tribes, extra in ((BEAST, 2, 3, ('beast',), {}),
            (DRAENEI, 1, 2, ('draenei',), {}), (PLAIN, 0, 6, ('pirate',), {}),
            (READER, 2, 3, ('all',), {'on_play':P+'read', 'battlecry':P+'read'}),
            (MAGNET, 1, 2, ('all',), {'keywords':(Keyword.MAGNETIC,), 'magnetic_tribes':('mech',)}),
            (HOST, 3, 4, ('mech',), {}), (DORMANT, 2, 3, ('beast',), {'dormant_turns':2}),
            (REBORN, 2, 3, ('beast',), {'keywords':(Keyword.REBORN,)})):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=1, attack=attack,
            health=health, metadata=meta(tribes), **extra))
    r.register_card(CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, attack=1, health=2))
    r.register_behavior(P+'copy-self',lambda c:(CopyMinion(c.source_id,c.player_id),))
    r.register_card(CardDefinition(COPY_SELF,COPY_SELF,CardType.MINION,cost=1,attack=2,health=3,
        metadata=meta(('beast',)),battlecry=P+'copy-self'))
    r.register_card(CardDefinition(LIMB,LIMB,CardType.MINION,attack=1,health=1,metadata=meta(('beast',))))
    r.register_card(CardDefinition(GIANT,GIANT,CardType.MINION,cost=1,attack=3,health=5,metadata=meta(('beast',)),
        keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB,side='left'),AppendageSpec(LIMB,side='right'))))
    r.register_card(CardDefinition(QUANTITY,QUANTITY,CardType.MINION,health=9,metadata=META,
        summon_quantities=(SummonQuantitySpec(),)))
    def fail(c): raise ResolutionError('K484 deliberate entry failure')
    r.register_behavior(P+'fail', fail)
    def menu(c):
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fail', 'Fail', (InvokeBehavior(P+'fail', c.source_id, c.player_id),))), c.source_id),)
    def recruit(c):
        source = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == BEAST)
        return (SummonStoredCard(CardReference.capture(source), c.player_id),)
    scripts = {'fuel':lambda c:(RefreshMana(c.player_id,1),),
        'make-beast':lambda c:(Summon(c.player_id,BEAST),),
        'two-beasts':lambda c:(Summon(c.player_id,BEAST),Summon(c.player_id,BEAST)),
        'make-draenei':lambda c:(Summon(c.player_id,DRAENEI),),
        'make-dormant':lambda c:(Summon(c.player_id,DORMANT),),
        'make-unknown':lambda c:(Summon(c.player_id,UNKNOWN),),
        'fill':lambda c:tuple(Summon(c.player_id,PLAIN) for _ in range(7)),
        'recruit':recruit,
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'morph':lambda c:(Transform(c.target_id,BEAST),),
        'arm':lambda c:(SetSecret(3-c.player_id,SECRET),),
        'rerun-minions':lambda c:(ReplayWholeCards(c.player_id,c.source_id,
            WholeCardHistoryQuery(c.player_id,len(c.state.play_history)+1,kinds=(CardType.MINION,),
                exclude_card_ids=(MUSIC,STAR)),choices='player',physical_profile=PHYSICAL_PROFILE),),
    }
    for key, body in scripts.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec() if key in('copy','kill','silence','give','bounce','morph')else None))
    r.register_secret_condition(P+'counter-condition',lambda c:c.window is not None and
        c.window.kind=='minion'and not c.window.countered and c.window.player_id!=c.player_id)
    r.register_behavior(P+'counter',lambda c:(CounterMinion(c.window.id),))
    r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,keywords=(Keyword.SECRET,),metadata=META,
        secret=SecretSpec(SECRET,('minion_counter_check',),P+'counter-condition',P+'counter')))
    def eligible(c):
        if mode in('added_wait','removed_wait','removed_fail'):
            return dict(c.event.data).get('effect_key') in PROGRAMS.values()
        target=c.state.entities.get(c.event.source_id)
        return target is not None and target.card_id in ((MUSIC,)if mode=='refill_music'else(BEAST,DRAENEI,READER,MAGNET))
    def watch(c):
        if mode=='fill_pending':return tuple(Summon(c.player_id,PLAIN)for _ in range(7))
        if mode=='refill_music':return(RefreshMana(c.player_id,1),)
        if mode=='removed_fail':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        return menu(c)
    event=('player_effect_added'if mode=='added_wait'else'player_effect_removed'if mode in('removed_wait','removed_fail')
        else'minion_counter_check'if mode=='fill_pending'else'minion_summoned')
    r.register_behavior(WATCH,watch);r.register_trigger_condition(P+'eligible',eligible)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
        limited_triggers=(LimitedTriggerSpec(event,WATCH,condition_id=P+'eligible'),)))
    r.validate();return r


def rehash(value):
    value['events_hash']=canonical_hash(value['events'])
    value['state_hash']=canonical_hash({k:v for k,v in value.items()if k not in
        ('schema_version','events','events_hash','state_hash')})
    return value


class PastNextTribalEntryBuffTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(),mana=40,mode='normal'):
        self.mode=mode
        if mode not in('normal','physical_wait'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(PLAIN,)*8,
            mana=mana,max_mana=40,mana_cap=40),PlayerSetup('HERO_08',board=enemy,deck=(PLAIN,)*8,
            mana=40,max_mana=40,mana_cap=40)),seed=484),fixture(mode))

    def gifts(self,g,cid=None,player=1):
        return tuple(x for x in g.state.players[player].player_effects
            if x.spec_id in ((PROGRAMS[cid],)if cid else PROGRAMS.values()))
    def stats(self,g,source,attack,health):
        e=g.state.entities[source];self.assertEqual((e.attack,e.max_health),(attack,health))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor

    def test_complete_two_rows_four_faces_and_independent_profiles(self):
        d=load_batch();rows={x['record']['id']:x['record']for x in d['dependencies']}
        self.assertEqual((len(rows),len(d['official_observations'])),(2,4))
        for o in d['official_observations']:
            self.assertEqual(batch.sha(o['response_file']),o['response_sha256']);batch.check_face(rows[o['card_id']],o['face'],o['locale'])
        r=fixture();self.assertEqual(r.card(MUSIC).metadata.tribes,('quilboar',));self.assertEqual(r.card(STAR).metadata.tribes,('draenei',))
        self.assertNotIn(PROGRAMS[MUSIC],r.summon_entry_stats_profiles)
        self.assertEqual(r.summon_entry_stats_profiles[PROGRAMS[STAR]].mode,'next_play_add')
        self.assertEqual(tuple(t.event for t in r.player_effect(PROGRAMS[MUSIC]).triggers),(AFTER,))
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_finale_uses_original_payment_and_nonfinale_creates_no_gift(self):
        for mana,count in((1,1),(2,0)):
            with self.subTest(mana=mana):
                g=self.game((MUSIC,),mana=mana);source=self.play(g,MUSIC)
                self.stats(g,source,1,3);self.assertEqual(len(self.gifts(g)),count)

    def test_finale_is_not_recomputed_after_entry_refills_mana(self):
        g=self.game((MUSIC,),mana=1,mode='refill_music');self.play(g,MUSIC)
        self.assertEqual(g.state.players[1].mana,1);self.assertEqual(len(self.gifts(g)),1);self.portable(g)

    def test_beast_buff_follows_generic_on_play_and_battlecry(self):
        g=self.game((MUSIC,P+'fuel',READER),mana=1,mode='entry_wait');self.play(g,MUSIC)
        self.play(g,P+'fuel');source=self.play(g,READER);self.stats(g,source,2,3)
        self.assertEqual(len(self.gifts(g)),1);self.assertEqual(self.armor(g),0)
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.assertEqual(self.armor(g),4);self.stats(g,source,3,4);self.assertFalse(self.gifts(g))

    def test_two_summons_only_first_original_beast_gets_bonus(self):
        g=self.game((MUSIC,P+'two-beasts'),mana=1);self.play(g,MUSIC);self.play(g,P+'two-beasts')
        bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==BEAST]
        self.assertEqual([(x.attack,x.max_health)for x in bodies],[(3,4),(2,3)]);self.assertFalse(self.gifts(g))

    def test_stored_physical_beast_entry_receives_bonus_once(self):
        g=self.game((MUSIC,BEAST,P+'recruit'),mana=1);self.play(g,MUSIC);source=self.entity(g,BEAST).id
        self.play(g,P+'recruit');self.stats(g,source,3,4);self.assertFalse(self.gifts(g));self.portable(g)

    def test_dormant_beast_does_not_receive_or_consume_future_buff(self):
        g=self.game((MUSIC,P+'make-dormant',P+'make-beast'),mana=1);self.play(g,MUSIC);self.play(g,P+'make-dormant')
        source=self.entity(g,DORMANT,zone='board');self.assertIsNotNone(source.dormancy)
        self.stats(g,source.id,2,3);self.assertEqual(len(self.gifts(g)),1)
        self.play(g,P+'make-beast');self.stats(g,self.entity(g,BEAST,zone='board').id,3,4);self.assertFalse(self.gifts(g))

    def test_battlecry_self_copy_completes_before_original_parent(self):
        g=self.game((MUSIC,P+'fuel',COPY_SELF),mana=1);self.play(g,MUSIC);self.play(g,P+'fuel')
        parent=self.play(g,COPY_SELF);children=[i for i in g.state.players[1].board if g.state.entities[i].card_id==COPY_SELF and i!=parent]
        self.assertEqual(len(children),1);self.stats(g,parent,2,3);self.stats(g,children[0],3,4)
        self.assertFalse(self.gifts(g));self.portable(g)

    def test_colossal_appendage_completes_before_original_parent(self):
        g=self.game((MUSIC,P+'fuel',GIANT),mana=1);self.play(g,MUSIC);self.play(g,P+'fuel');parent=self.play(g,GIANT)
        limbs=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==LIMB]
        self.assertEqual([(x.attack,x.max_health)for x in limbs],[(2,2),(1,1)])
        self.stats(g,parent,3,5);self.assertFalse(self.gifts(g));self.portable(g)

    def test_actual_reborn_uses_bonus_after_original_one_health_material(self):
        g=self.game((MUSIC,P+'kill'),board=(REBORN,),mana=1);old=self.entity(g,REBORN,zone='board').id
        self.play(g,MUSIC);self.play(g,P+'kill',old);source=self.entity(g,REBORN,zone='board')
        self.assertNotEqual(source.id,old);self.assertEqual((source.attack,source.health),(3,2));self.assertFalse(self.gifts(g));self.portable(g)

    def test_transform_is_not_a_new_summon(self):
        g=self.game((MUSIC,P+'morph',P+'make-beast'),board=(PLAIN,),mana=1);source=self.entity(g,PLAIN,zone='board').id
        self.play(g,MUSIC);self.play(g,P+'morph',source);self.stats(g,source,2,3);self.assertEqual(len(self.gifts(g)),1)
        self.play(g,P+'make-beast');new=g.state.players[1].board[-1];self.stats(g,new,3,4);self.assertFalse(self.gifts(g))

    def test_failed_full_board_summon_preserves_original_gift(self):
        g=self.game((MUSIC,P+'fill',P+'make-beast',P+'kill',P+'make-beast'),mana=1)
        self.play(g,MUSIC);self.play(g,P+'fill');self.play(g,P+'make-beast');self.assertEqual(len(self.gifts(g)),1)
        self.play(g,P+'kill',self.entity(g,PLAIN,zone='board').id);self.play(g,P+'make-beast')
        self.stats(g,self.entity(g,BEAST,zone='board').id,3,4);self.assertFalse(self.gifts(g))

    def test_source_silence_death_and_turn_change_do_not_cancel_future_gift(self):
        g=self.game((MUSIC,P+'silence',P+'kill',P+'make-beast'),mana=1);source=self.play(g,MUSIC)
        self.play(g,P+'silence',source);self.play(g,P+'kill',source);g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.assertEqual(len(self.gifts(g)),1);self.play(g,P+'make-beast');self.assertFalse(self.gifts(g))
        self.stats(g,self.entity(g,BEAST,zone='board').id,3,4)

    def test_two_real_finales_install_two_independent_once_only_bonuses(self):
        g=self.game((MUSIC,P+'fuel',MUSIC,P+'make-beast'),mana=1);self.play(g,MUSIC);self.play(g,P+'fuel');self.play(g,MUSIC)
        self.assertEqual(len(self.gifts(g)),2);self.play(g,P+'make-beast');self.stats(g,self.entity(g,BEAST,zone='board').id,4,5)
        self.assertFalse(self.gifts(g))

    def test_countered_source_creates_neither_battlecry_nor_finale_gift(self):
        for cid in(MUSIC,STAR):
            with self.subTest(card=cid):
                g=self.game((P+'arm',cid),mana=1);self.play(g,P+'arm');self.play(g,cid);self.assertFalse(self.gifts(g))

    def test_countered_beast_preserves_then_actual_summon_consumes(self):
        g=self.game((MUSIC,P+'arm',P+'fuel',BEAST,P+'make-beast'),mana=1);self.play(g,MUSIC);self.play(g,P+'arm')
        self.play(g,P+'fuel');self.play(g,BEAST);self.assertEqual(len(self.gifts(g)),1)
        self.play(g,P+'make-beast');self.stats(g,self.entity(g,BEAST,zone='board').id,3,4);self.assertFalse(self.gifts(g))

    def test_next_draenei_bonus_precedes_generic_on_play_and_battlecry(self):
        g=self.game((STAR,READER));self.play(g,STAR);source=self.play(g,READER)
        self.stats(g,source,4,4);self.assertEqual(self.armor(g),8);self.assertFalse(self.gifts(g));self.portable(g)

    def test_summon_and_current_board_copy_do_not_consume_next_play(self):
        g=self.game((STAR,P+'make-draenei',P+'copy',DRAENEI));source=self.play(g,STAR)
        self.play(g,P+'make-draenei');self.play(g,P+'copy',source);self.assertEqual(len(self.gifts(g)),1)
        target=self.play(g,DRAENEI);self.stats(g,target,3,3);self.assertFalse(self.gifts(g))

    def test_same_physical_creator_reentry_can_consume_old_gift_before_new_install(self):
        g=self.game((STAR,P+'bounce'));source=self.play(g,STAR);self.play(g,P+'bounce',source)
        self.assertEqual(self.play(g,STAR),source);self.stats(g,source,4,2);self.assertEqual(len(self.gifts(g)),1);self.portable(g)

    def test_actual_brann_creates_two_original_gifts_consumed_by_one_paid_target(self):
        g=self.game((STAR,DRAENEI),board=('LOE_077',));self.play(g,STAR);self.assertEqual(len(self.gifts(g)),2)
        target=self.play(g,DRAENEI);self.stats(g,target,5,4);self.assertFalse(self.gifts(g));self.portable(g)

    def test_original_all_tribe_magnetic_material_gets_bonus_before_merge(self):
        g=self.game((STAR,MAGNET),board=(HOST,));self.play(g,STAR)
        source=self.entity(g,MAGNET).id;host=self.entity(g,HOST,zone='board').id
        g.apply(PlayCard(1,source,position=0));row,=g.state.magnetic_history
        self.assertEqual((row.source_id,row.target_id,row.attack,row.health),(source,host,3,3))
        self.stats(g,host,6,7);self.assertFalse(self.gifts(g));self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_countered_paid_draenei_preserves_gift_for_next_accepted_play(self):
        g=self.game((STAR,P+'arm',DRAENEI,DRAENEI));self.play(g,STAR);self.play(g,P+'arm')
        self.play(g,DRAENEI);self.assertEqual(len(self.gifts(g)),1)
        target=self.play(g,DRAENEI);self.stats(g,target,3,3);self.assertFalse(self.gifts(g))

    def test_initially_full_board_illegal_play_does_not_consume_or_pay(self):
        g=self.game((STAR,P+'fill',DRAENEI));self.play(g,STAR);self.play(g,P+'fill');saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,DRAENEI)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(len(self.gifts(g)),1)

    def test_postpayment_full_board_entry_failure_does_not_consume(self):
        g=self.game((STAR,DRAENEI),mode='fill_pending');self.play(g,STAR);mana=g.state.players[1].mana
        self.play(g,DRAENEI);self.assertEqual(g.state.players[1].mana,mana-1)
        self.assertEqual(g.state.play_history[-1].minion_result,'board_full');self.assertEqual(len(self.gifts(g)),1);self.portable(g)

    def test_transferred_source_does_not_transfer_original_players_gift(self):
        g=self.game((STAR,P+'give',DRAENEI));source=self.play(g,STAR);self.play(g,P+'give',source)
        self.assertFalse(self.gifts(g,player=2));target=self.play(g,DRAENEI);self.stats(g,target,3,3);self.assertFalse(self.gifts(g))

    def test_unknown_required_tribes_fail_and_roll_back_instead_of_nonmatching(self):
        for cid,script in((MUSIC,P+'make-unknown'),(STAR,UNKNOWN)):
            with self.subTest(card=cid):
                g=self.game((cid,script),mana=1);self.play(g,cid);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,script)
                self.assertEqual(g.snapshot(),saved);self.assertEqual(len(self.gifts(g)),1)

    def test_pending_new_program_restores_and_public_views_hide_receipts(self):
        g=self.game((STAR,DRAENEI),mode='added_wait');self.play(g,STAR);other=self.portable(g)
        for pid in(1,2):
            view=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))
            for key in('target_allocation',ACCEPTED,APPLIED,ENTRY,AFTER,CLOSED,'instance_id'):self.assertNotIn(key,view)
        self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        self.play(g,DRAENEI);self.assertFalse(self.gifts(g))

    def test_paid_material_already_committed_at_removal_choice_and_resumes_once(self):
        g=self.game((STAR,READER),mode='removed_wait');self.play(g,STAR);target=self.play(g,READER)
        self.stats(g,target,4,4);self.assertFalse(self.gifts(g));self.assertEqual(self.armor(g),0)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.armor(g),8)

    def test_generated_whole_minion_waits_for_body_before_summon_bonus(self):
        g=self.game((READER,MUSIC,P+'rerun-minions'),mana=2,mode='physical_wait')
        self.play(g,READER);self.play(g,MUSIC);self.assertEqual(self.armor(g),4)
        self.play(g,P+'rerun-minions');self.assertIsNotNone(g.state.pending_choice)
        child=g.state.whole_card_replay_ledger.children[0];target=child.physical.source.entity_id
        self.stats(g,target,2,3);self.assertEqual(len(self.gifts(g)),1)
        other=self.portable(g)
        for branch in(g,other):
            for _ in range(3):
                if branch.state.pending_choice is None:break
                self.choose(branch)
            self.assertIsNone(branch.state.pending_choice)
        self.assertEqual(g.snapshot(),other.snapshot());self.stats(g,target,3,4)
        self.assertEqual(self.armor(g),8);self.assertFalse(self.gifts(g));self.portable(g)

    def test_generated_quantity_extra_finishes_independently_of_primary_body(self):
        g=self.game((READER,MUSIC,P+'rerun-minions'),board=(QUANTITY,),mana=2)
        self.play(g,READER);self.play(g,MUSIC);self.play(g,P+'rerun-minions')
        body=g.state.whole_card_replay_ledger.children[0].physical
        root=g.state.card_summon_history[body.summon_root_id-1]
        self.assertEqual(len(root.deliveries),2)
        primary,extra=(d.entity.entity_id for d in root.deliveries)
        self.assertEqual(body.source.entity_id,primary)
        self.stats(g,primary,2,3);self.stats(g,extra,3,4)
        self.assertEqual(self.armor(g),8);self.assertFalse(self.gifts(g));self.portable(g)

    def test_after_summon_removal_wait_resumes_before_next_summon(self):
        g=self.game((MUSIC,P+'two-beasts'),mana=1,mode='removed_wait')
        self.play(g,MUSIC);self.play(g,P+'two-beasts')
        beasts=[i for i in g.state.players[1].board if g.state.entities[i].card_id==BEAST]
        self.assertEqual(len(beasts),1);self.stats(g,beasts[0],2,3);self.assertFalse(self.gifts(g))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot())
        beasts=[i for i in g.state.players[1].board if g.state.entities[i].card_id==BEAST]
        self.stats(g,beasts[0],3,4);self.stats(g,beasts[1],2,3)
        for pid in(1,2):
            view=json.dumps(g.observe(pid))+json.dumps(g.player_events(pid))
            for private in(AFTER,CLOSED,'_summon_birth','_summon_completion'):self.assertNotIn(private,view)

    def test_rehashed_missing_after_notification_is_rejected(self):
        g=self.game((MUSIC,P+'make-beast'),mana=1);self.play(g,MUSIC);self.play(g,P+'make-beast')
        saved=deepcopy(g.snapshot());event=next(e for e in saved['events']if e['kind']==AFTER)
        event['kind']='k484_ignored_after_summon';event['data']={}
        with self.assertRaisesRegex(SnapshotError,'after-summon notification'):
            Game.from_snapshot(rehash(saved),fixture('normal','reader'))

    def test_pending_paid_minion_cannot_drop_its_after_summon_tail(self):
        g=self.game((MUSIC,P+'fuel',READER),mana=1,mode='entry_wait')
        self.play(g,MUSIC);self.play(g,P+'fuel');self.play(g,READER)
        saved=deepcopy(g.snapshot());work=saved['resolution_frame']['fields']['continuation']['tuple']
        before=len(work);work[:]=[w for w in work if not w.get('type','').endswith('.CompleteMinionSummon')]
        self.assertEqual(len(work),before-1)
        with self.assertRaisesRegex(SnapshotError,'after-summon completion'):
            Game.from_snapshot(rehash(saved),fixture('entry_wait','reader'))

    def test_late_removal_reaction_failure_rolls_back_payment_source_and_program(self):
        for cid,target in((MUSIC,P+'make-beast'),(STAR,DRAENEI)):
            with self.subTest(card=cid):
                g=self.game((cid,target),mana=1 if cid==MUSIC else 40,mode='removed_fail');self.play(g,cid);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,target)
                self.assertEqual(g.snapshot(),saved);self.assertEqual(len(self.gifts(g)),1)

    def test_rehashed_missing_application_and_boolean_original_origin_are_rejected(self):
        g=self.game((STAR,DRAENEI));self.play(g,STAR);self.play(g,DRAENEI)
        saved=deepcopy(g.snapshot());event=next(e for e in saved['events']if e['kind']==APPLIED)
        event['kind']='k484_ignored_application';event['data']={}
        with self.assertRaisesRegex(SnapshotError,'original application'):Game.from_snapshot(rehash(saved),fixture('normal','reader'))
        saved=deepcopy(g.snapshot());event=next(e for e in saved['events']if e['kind']==ACCEPTED)
        data=dict(event['data']);data['battlecry_id']=True;event['data']=data
        with self.assertRaisesRegex(SnapshotError,'Unknown entry program Battlecry'):Game.from_snapshot(rehash(saved),fixture('normal','reader'))

    def test_profile_modes_are_finite_and_default_representative_is_preserved(self):
        with self.assertRaises(ValueError):SummonEntryStatsProfile('a','b',('beast',),SummonStats(1,1),'invented')
        self.assertEqual(defaults().fingerprint(),'b2167d3328df10bb4336983812adfd12220d2644b7bcc86b517f5e335028eb4a')
        r=build_registry();self.assertNotIn(PROGRAMS[MUSIC],r.summon_entry_stats_profiles)
        self.assertEqual(r.summon_entry_stats_profiles[PROGRAMS[STAR]].mode,'next_play_add')
