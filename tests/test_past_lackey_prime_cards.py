"""Real Lackey bodies, semantic Prime shuffle and current-controller protection."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from card_batch_testkit import CardBatchTestMixin
from tools import card_batch as batch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_past_entry_grant_cards import FLASHBACK,register_native_past_entry_grant_cards
from hs_sim.cards.native_past_entry_grant_cards import POOL_ID as FLASHBACK_POOL
from hs_sim.cards.past_lackey_prime_cards import (SLURPER,RELIQUARY,PRIME,LACKEYS,
    FACELESS,KOBOLD,WITCHY,GOBLIN,ETHEREAL,TITANIC,DRACONIC,DEPENDENCIES,
    OPPONENT_TURN,POOL_ID,load_batch,register_past_lackey_prime_cards)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,
    Game,Keyword,KeywordAuraSpec,PlayCard,PlayerSetup,QueueTurns,Rarity,Scenario,
    SkipTurns,SnapshotError,TargetMode,TargetSpec,TriggerSpec,UseHeroPower,Zone)
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,CopyMinion,
    Damage,Destroy,GainArmor,GrantKeyword,Heal,InvokeBehavior,RequestChoice,
    ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.model import DamageKind,EndTurnSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,sample_candidates
from hs_sim.engine.representative import build_registry as defaults

P='k480.';TARGET=P+'target';TWO=P+'two';THREE=P+'three';FILLER=P+'filler';WATCH=P+'watch'
DRAGONS=(P+'dragon-neutral',P+'dragon-mage',P+'dragon-priest')
SPELLS=(P+'spell-neutral',P+'spell-mage',P+'spell-priest',P+'spell-uncollectible')
META=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=defaults();register_past_lackey_prime_cards(r);register_native_past_entry_grant_cards(r)
    r._version='k480-'+mode
    def fail(c):raise ResolutionError('K480 deliberate late failure')
    r.register_behavior(P+'fail',fail)
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'two-battlecry',lambda c:(Damage(c.state.players[3-c.player_id].hero_id,9,c.source_id),))
    r.register_card(CardDefinition(TWO,TWO,CardType.MINION,cost=2,attack=3,health=2,metadata=META,battlecry=P+'two-battlecry'))
    r.register_card(CardDefinition(THREE,THREE,CardType.MINION,cost=3,attack=4,health=5,metadata=META))
    r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=8,attack=1,health=30,metadata=META))
    r.register_card(CardDefinition(P+'spell-power','Diagnostic spell power',CardType.MINION,
        health=9,spell_damage=3,metadata=META))
    for cid,cls in zip(DRAGONS,(CardClass.NEUTRAL,CardClass.MAGE,CardClass.PRIEST)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=4,health=4,
            metadata=replace(META,classes=(cls,),tribes=('dragon',))))
    for cid,cls in zip(SPELLS,(CardClass.NEUTRAL,CardClass.MAGE,CardClass.PRIEST,CardClass.MAGE)):
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=P+'noop',
            metadata=replace(META,classes=(cls,),collectible=cid!=SPELLS[-1])))
    def primes(c):return tuple(i for p in c.state.players.values()for i in p.board if c.state.entities[i].card_id==PRIME)
    scripts={
        'ping':lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'give':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,TWO),),
        'copy':lambda c:(CopyMinion(c.target_id,3-c.player_id),),
        'grant':lambda c:(GrantKeyword(c.target_id,Keyword.ELUSIVE,c.source_id),),
        'silence-prime':lambda c:tuple(Silence(i)for i in primes(c)),
        'sleep-prime':lambda c:tuple(MakeDormant(i,None)for i in primes(c)),
        'wake-prime':lambda c:tuple(AwakenMinion(i)for i in primes(c)),
        'hurt':lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        'kill-prime':lambda c:tuple(Destroy(i,c.source_id)for i in primes(c)),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'skip':lambda c:(SkipTurns(3-c.player_id,1,c.source_id),),
        'summon-slurper':lambda c:(Summon(c.player_id,SLURPER),),
    }
    for key,body in scripts.items():
        r.register_behavior(P+key,body)
        r.register_card(CardDefinition(P+key,key,CardType.SPELL,on_play=P+key,metadata=META,
            targeting=TargetSpec()if key in('ping','kill','silence','give','bounce','transform','copy','grant')else None))
    def wait(c):
        e=c.event
        if (mode=='late-generation'and e.kind=='card_added_to_hand'and e.source_id is not None
                and c.state.entities[e.source_id].card_id==SLURPER):
            return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        matches=(mode=='after-generation'and e.kind=='card_added_to_hand'and e.source_id is not None
            and c.state.entities[e.source_id].card_id==SLURPER or
            mode=='after-shuffle'and e.kind=='card_added_to_deck'and c.state.entities[e.target_id].card_id==PRIME or
            mode=='end-wait'and e.kind=='turn_ended'and e.player_id==1 or
            mode=='start-wait'and e.kind=='turn_started'and e.player_id==2)
        if not matches:return ()
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(WATCH,wait)
    r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,metadata=META,
        triggers=tuple(TriggerSpec(k,WATCH)for k in('card_added_to_hand','card_added_to_deck','turn_ended','turn_started'))))
    pool=(TWO,THREE,*DRAGONS,*SPELLS)
    for cid in pool:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if mode=='missing-pool':
        r.register_pool_card(PoolCard(P+'missing',CardType.MINION,2,META,battlecry=False,
            deathrattle=False,choose_one=False,attack=2));pool=(*pool,P+'missing')
    if mode=='empty':pool=()
    r.register_pool(PoolDefinition(POOL_ID,'v1',TARGET,'experimental',tuple(PoolMember(c)for c in pool)))
    raw=next(x['record']for x in load_batch()['evidence_only']if x['record']['id']=='DRG_303')
    r.register_pool_card(PoolCard('DRG_303',CardType.MINION,1,metadata_from_record(raw),
        keywords=(Keyword.INVOKE,),battlecry=True,deathrattle=False,choose_one=False,attack=1))
    r.register_pool(PoolDefinition('constructed.past.cards','v1',TARGET,'experimental',
        tuple(PoolMember(c)for c in(SLURPER,RELIQUARY,'DRG_303'))))
    # This diagnostic pool follows Flashback's current explicit source binding;
    # the old general-past fixture (including its Invoke evidence) stays intact.
    r.register_pool(PoolDefinition(FLASHBACK_POOL,'v1',TARGET,'experimental',
        tuple(PoolMember(c)for c in(SLURPER,RELIQUARY))))
    if mode=='missing-fixed':r._cards.pop(DRACONIC)
    r.validate();return r


class PastLackeyPrimeTests(CardBatchTestMixin,unittest.TestCase):
    registry_factory=staticmethod(fixture)

    def game(self,hand=(),*,board=(),enemy=(FILLER,),enemy_hand=(),mode='normal',seed=480):
        self.mode=mode
        if mode in('after-generation','after-shuffle','end-wait','start-wait','late-generation'):board=(WATCH,*board)
        deck=(FILLER,)*4
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=40,max_mana=40,mana_cap=40,hero_power_card_id='HERO_08bp'),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=deck,mana=40,max_mana=40,
                mana_cap=40,hero_power_card_id='HERO_08bp')),seed=seed,
            generation_context=GenerationContext(TARGET,'experimental',(deck,deck))),fixture(mode))

    def protected(self,g,eid,expected=True):
        self.assertEqual(Keyword.ELUSIVE in g.state.entities[eid].keywords,expected)

    def targets(self,g,cid,player=1):
        eid=self.entity(g,cid,player).id
        return {a.target_id for a in g.legal_actions()if isinstance(a,PlayCard)and a.entity_id==eid}

    def created(self,g,cids):
        return [g.state.entities[e.target_id]for e in g.events if e.kind=='card_created'
            and g.state.entities[e.target_id].card_id in cids]

    def test_full_twelve_rows_twenty_two_primary_faces_and_provider_separation(self):
        data=load_batch();raw={x['record']['id']:x['record']for x in data['dependencies']+data['evidence_only']}
        self.assertEqual((len(data['dependencies']),len(data['evidence_only']),len(data['official_observations'])),(10,2,22))
        for face in data['official_observations']:
            self.assertEqual(batch.sha(face['response_file']),face['response_sha256'])
            batch.check_face(raw[face['card_id']],face['face'],face['locale'])
        self.assertNotIn('SCH_199t19',LACKEYS);self.assertNotIn('DRG_303',DEPENDENCIES)
        self.assertTrue(all(raw[c]['tags']['MARK_OF_EVIL']==1 for c in LACKEYS))
        self.assertNotIn('MARK_OF_EVIL',raw['SCH_199t19']['tags'])
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated'])

    def test_complete_printed_material_and_native_conditional_keyword(self):
        r=fixture()
        for cid in LACKEYS:
            with self.subTest(cid=cid):
                c=r.card(cid);self.assertEqual((c.cost,c.attack,c.health),(1,1,1))
                self.assertEqual(c.metadata.subtypes,('lackey',));self.assertFalse(c.metadata.collectible)
                self.assertIsNotNone(c.battlecry)
        self.assertEqual(r.card(SLURPER).metadata.tribes,('murloc',))
        self.assertEqual(r.card(PRIME).keyword_auras,(OPPONENT_TURN,))
        self.assertNotIn(Keyword.ELUSIVE,r.card(PRIME).keywords)
        self.assertEqual(r.card(PRIME).keywords,(Keyword.TAUNT,Keyword.LIFESTEAL))

    def test_fixed_lackey_generation_reaches_each_real_member(self):
        seeds={}
        for seed in range(256):
            cid,=sample_candidates(random.Random(seed),tuple(PoolMember(c)for c in sorted(LACKEYS)),1,replacement=True)
            seeds.setdefault(cid,seed)
            if len(seeds)==7:break
        self.assertEqual(set(seeds),set(LACKEYS))
        for cid,seed in seeds.items():
            g=self.game((SLURPER,),seed=seed);source=self.play(g,SLURPER);token,=self.created(g,LACKEYS)
            self.assertEqual(token.card_id,cid);self.assertIn(token.id,g.state.players[1].hand)
            self.assertEqual(g.state.players[1].overload_owed,1);self.assertEqual(g.state.players[1].mana,39)
            self.assertFalse(g.state.card_discovery_history)

    def test_slurper_battlecry_repeat_does_not_repeat_printed_overload(self):
        g=self.game((SLURPER,),board=('LOE_077',));self.play(g,SLURPER)
        self.assertEqual(len(self.created(g,LACKEYS)),2);self.assertEqual(g.state.players[1].overload_owed,1)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.state.players[1].overload_locked,1)
        self.portable(g)

    def test_effect_summon_and_real_flashback_do_not_invoke_battlecry_or_overload(self):
        g=self.game((P+'summon-slurper',FLASHBACK));self.play(g,P+'summon-slurper');self.play(g,FLASHBACK)
        self.assertFalse(self.created(g,LACKEYS));self.assertEqual(g.state.players[1].overload_owed,0)
        self.assertEqual(len(g.state.players[1].board),3);self.assertNotIn('DRG_303',[g.state.entities[i].card_id for i in g.state.players[1].board])
        self.portable(g)

    def test_missing_fixed_candidate_fails_even_with_full_hand_and_rolls_back(self):
        g=self.game((SLURPER,)+(FILLER,)*9,mode='missing-fixed');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition'):self.play(g,SLURPER)
        self.assertEqual(g.snapshot(),before)

    def test_full_hand_acquisition_burn_uses_normal_creation_path(self):
        g=self.game((SLURPER,)+(FILLER,)*9,board=('LOE_077',));self.play(g,SLURPER)
        tokens=self.created(g,LACKEYS);self.assertEqual(len(tokens),2)
        self.assertEqual([t.zone for t in tokens],[Zone.HAND,Zone.GRAVEYARD])

    def test_generation_wait_restore_and_late_failure_are_one_paid_transaction(self):
        g=self.game((SLURPER,),mode='after-generation');self.play(g,SLURPER)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,39)
        saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.created(g,LACKEYS)),1);self.portable(g)

    def test_late_generation_failure_restores_payment_overload_and_rng(self):
        g=self.game((SLURPER,),mode='late-generation');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,SLURPER)
        self.assertEqual(g.snapshot(),before)

    def test_faceless_summons_native_two_cost_without_its_battlecry(self):
        g=self.game((FACELESS,));self.play(g,FACELESS)
        summoned=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==TWO]
        self.assertEqual(len(summoned),1);self.assertEqual((summoned[0].attack,summoned[0].health),(3,2))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_faceless_full_board_and_empty_pool_follow_shared_capacity_policy(self):
        for mode,board in(('normal',(FILLER,)*6),('empty',())):
            g=self.game((FACELESS,),board=board,mode=mode);self.play(g,FACELESS)
            self.assertEqual(len(g.state.players[1].board),len(board)+1)

    def test_missing_eligible_pool_member_is_not_silently_removed(self):
        g=self.game((FACELESS,),mode='missing-pool');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition'):self.play(g,FACELESS)
        self.assertEqual(g.snapshot(),before)

    def test_kobold_minion_damage_does_not_scale_with_spell_power(self):
        g=self.game((KOBOLD,),board=(P+'spell-power',));target=g.state.players[2].board[0]
        self.play(g,KOBOLD,target);self.assertEqual(g.state.entities[target].health,28)

    def test_goblin_and_titanic_grant_real_separate_buffs_and_keywords(self):
        g=self.game((GOBLIN,TITANIC),board=(FILLER,));target=g.state.players[1].board[0]
        self.play(g,GOBLIN,target);self.play(g,TITANIC,target)
        e=g.state.entities[target];self.assertEqual((e.attack,e.health),(2,32))
        self.assertTrue({Keyword.RUSH,Keyword.TAUNT}<=e.keywords)

    def test_friendly_target_domain_excludes_enemies_and_the_source(self):
        for cid in(GOBLIN,TITANIC,WITCHY):
            g=self.game((cid,),board=(TWO,));target=g.state.players[1].board[0]
            self.assertEqual(self.targets(g,cid),{target});self.play(g,cid,target)
            self.assertEqual(len(g.state.players[1].board),2)

    def test_no_friendly_target_still_plays_without_fabricating_one(self):
        for cid in(GOBLIN,TITANIC,WITCHY):
            g=self.game((cid,),enemy=());self.assertEqual(self.targets(g,cid),{None})
            self.play(g,cid);self.assertEqual(len(g.state.players[1].board),1)

    def test_witchy_transforms_original_friendly_minion_one_printed_tier_up(self):
        g=self.game((WITCHY,),board=(TWO,));target=g.state.players[1].board[0]
        self.play(g,WITCHY,target);e=g.state.entities[target]
        self.assertEqual((e.card_id,e.attack,e.health),(THREE,4,5));self.assertFalse(g.state.death_history)
        self.portable(g)

    def test_both_discoveries_use_current_class_and_correct_types(self):
        for cid,expected in((ETHEREAL,set(SPELLS[:2])),(DRACONIC,set(DRAGONS[:2]))):
            g=self.game((cid,));self.play(g,cid);choice=g.state.pending_choice
            self.assertIsNotNone(choice);self.assertEqual({o.card_id for o in choice.options},expected)
            self.portable(g);self.choose(g,choice.options[0].id);self.assertEqual(len(g.state.card_discovery_history),1)
            self.assertTrue(self.created(g,expected));self.portable(g)

    def test_reliquary_death_shuffles_one_new_prime_with_original_controller(self):
        g=self.game((P+'kill',),board=(RELIQUARY,));source=g.state.players[1].board[0]
        self.play(g,P+'kill',source);prime,=self.created(g,(PRIME,))
        self.assertEqual((prime.owner,prime.controller,prime.zone),(1,1,Zone.DECK))
        self.assertNotEqual(prime.id,source);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.portable(g)

    def test_reliquary_repeat_silence_and_transfer_use_existing_death_rules(self):
        g=self.game((P+'kill',),board=(RELIQUARY,'FP1_031'))
        self.play(g,P+'kill',g.state.players[1].board[0]);self.assertEqual(len(self.created(g,(PRIME,))),2)
        g=self.game((P+'silence',P+'kill'),board=(RELIQUARY,));source=g.state.players[1].board[0]
        self.play(g,P+'silence',source);self.play(g,P+'kill',source);self.assertFalse(self.created(g,(PRIME,)))
        g=self.game((P+'give',),board=(RELIQUARY,),enemy_hand=(P+'kill',));source=g.state.players[1].board[0]
        self.play(g,P+'give',source);g.apply(EndTurn(1));self.play(g,P+'kill',source,player=2)
        self.assertEqual(self.created(g,(PRIME,))[0].controller,2)

    def test_prime_shuffle_wait_restore_and_failed_selection_rollback(self):
        g=self.game((P+'kill',),board=(RELIQUARY,),mode='after-shuffle');source=g.state.players[1].board[1]
        self.play(g,P+'kill',source);saved=g.snapshot();other=self.portable(g)
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.created(g,(PRIME,))),1);self.portable(g)

    def test_prime_blocks_spell_and_power_only_during_opponent_actual_turn(self):
        g=self.game((P+'ping',),board=(PRIME,),enemy_hand=(P+'ping',KOBOLD));prime=g.state.players[1].board[0]
        self.protected(g,prime,False);self.play(g,P+'ping',prime);g.apply(EndTurn(1));self.protected(g,prime)
        self.assertNotIn(prime,self.targets(g,P+'ping',2));self.assertIn(prime,self.targets(g,KOBOLD,2))
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,P+'ping',prime,player=2)
        with self.assertRaises(IllegalAction):g.apply(UseHeroPower(2,g.state.players[2].hero_power_id,prime))
        self.assertEqual(g.snapshot(),before);self.play(g,KOBOLD,prime,player=2)
        self.assertEqual(g.state.entities[prime].health,5);g.apply(EndTurn(2));self.protected(g,prime,False);self.portable(g)

    def test_prime_taunt_combat_and_lifesteal_share_normal_engine(self):
        g=self.game((P+'hurt',),board=(PRIME,));prime=g.state.players[1].board[0]
        self.play(g,P+'hurt');target=g.state.players[2].board[0];g.apply(Attack(1,prime,target))
        self.assertEqual(g.state.entities[target].health,24)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)
        g.apply(EndTurn(1));self.assertNotIn(g.state.players[1].hero_id,
            {a.defender_id for a in g.legal_actions()if isinstance(a,Attack)})

    def test_control_transfer_rechecks_current_controller_immediately(self):
        g=self.game((P+'give',),board=(PRIME,));prime=g.state.players[1].board[0]
        self.play(g,P+'give',prime);self.protected(g,prime);g.apply(EndTurn(1));self.protected(g,prime,False)
        self.portable(g)

    def test_silence_and_dormancy_remove_protection_and_waking_rechecks_turn(self):
        for spell in('silence-prime','sleep-prime'):
            g=self.game(board=(PRIME,),enemy_hand=(P+spell,P+'wake-prime'))
            prime=g.state.players[1].board[0];g.apply(EndTurn(1));self.protected(g,prime)
            self.play(g,P+spell,player=2);self.protected(g,prime,False)
            if spell=='sleep-prime':self.play(g,P+'wake-prime',player=2);self.protected(g,prime)
            self.portable(g)

    def test_return_transform_and_current_copy_do_not_retain_old_turn_cache(self):
        for spell in('bounce','transform','copy'):
            g=self.game((P+spell,),board=(PRIME,));prime=g.state.players[1].board[0]
            self.play(g,P+spell,prime)
            if spell=='copy':
                copy=g.state.players[2].board[-1];self.protected(g,copy);self.protected(g,prime,False)
            else:self.protected(g,prime,False)
            self.portable(g)

    def test_independent_elusive_grant_is_not_removed_when_native_condition_expires(self):
        g=self.game((P+'grant',),board=(PRIME,));prime=g.state.players[1].board[0]
        self.play(g,P+'grant',prime);self.protected(g,prime)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.protected(g,prime);self.portable(g)

    def test_extra_and_skipped_turns_use_actual_active_player(self):
        for spell in('extra','skip'):
            g=self.game((P+spell,),board=(PRIME,));prime=g.state.players[1].board[0]
            self.play(g,P+spell);g.apply(EndTurn(1));self.assertEqual(g.state.active_player,1)
            self.protected(g,prime,False);self.portable(g)

    def test_end_and_start_waits_preserve_correct_boundary_and_recovery(self):
        for mode in('end-wait','start-wait'):
            g=self.game(board=(PRIME,),mode=mode);prime=g.state.players[1].board[1]
            g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice)
            self.protected(g,prime,mode=='start-wait');self.portable(g)
            self.choose(g);self.protected(g,prime);self.portable(g)

    def test_native_profile_is_finite_and_cannot_be_arbitrarily_granted(self):
        for kwargs in({'keyword':Keyword.RUSH},{'target':'friendly_hero'},
                {'include_self':True},{'adjacent_only':True},{'card_ids':('x',)},{'tribes_any':('dragon',)}):
            values={'keyword':Keyword.ELUSIVE,'target':'self','condition':'controller_opponent_turn'}|kwargs
            with self.assertRaises(ValueError):KeywordAuraSpec(**values)
        with self.assertRaises(ValueError):GrantKeywordAura(1,OPPONENT_TURN)

    def test_snapshot_rejects_altered_native_condition_and_invalid_keyword_cache(self):
        g=self.game(board=(PRIME,));prime=g.state.players[1].board[0];g.apply(EndTurn(1))
        snap=g.snapshot();bad=deepcopy(snap)
        ability=next(a for a in bad['state']['entities'][str(prime)]['abilities']if a['kind']=='keyword_aura')
        ability['keyword_aura']['condition']='always'
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture())
        bad=deepcopy(snap);bad['state']['entities'][str(prime)]['conditional_keywords']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(bad,fixture())

    def test_player_views_do_not_expose_native_aura_or_private_deck_history(self):
        g=self.game((P+'kill',),board=(RELIQUARY,PRIME));self.play(g,P+'kill',g.state.players[1].board[0])
        for player in(1,2):
            view=json.dumps(g.for_player(player).observe())
            for key in('controller_opponent_turn','keyword_auras','conditional_keywords','deck_shuffle_history','source_sha256'):
                self.assertNotIn(key,view)

    def test_central_assembly_contains_ten_new_definitions_without_wild_invoke(self):
        r=build_registry()
        self.assertTrue(all(cid in r.cards for cid in DEPENDENCIES));self.assertNotIn('DRG_303',r.cards)
        self.assertIsNone(r.invoke_profile)


if __name__=='__main__':unittest.main()
