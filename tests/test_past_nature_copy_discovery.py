"""Real copies/discoveries and their original physical-material boundaries."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import json, unittest
from pathlib import Path

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import build_registry, past_nature_copy_discovery as native
from hs_sim.cards.simple_followup_p89_cards import WO, PAST_POOL, QUERIES
from hs_sim.engine import EndTurn, Game, PlayerSetup, PlayCard, ResolutionError, Ruleset, Scenario
from hs_sim.engine.adapt import SPORES_BEHAVIOR
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import (Buff, ChoiceOption, Damage, Destroy, DestroyBatch,
    GrantKeyword, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand)
from hs_sim.engine.jade import CLASSIC
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec,
    Keyword, SpellSchool, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember, resolve_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, CopyCard
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

P = 'k661.'
A,B,C,TWO,MAGE_TWO,HIGH,TEN,OVER,DORM,BOTH,DEAD,RATTLE = (P+x for x in
    ('druid3','druid4','druid5','neutral2','mage2','nine','ten','eleven','dormant','both','death_wait','death_summon'))
S1,S2,SH,PORTAL,NOOP,TAUNT,BOOST,REENTER,KILL,AUTO,FAIL = (P+x for x in
    ('mage3','mage_nature4','shaman_nature3','draw_cast','noop','taunt','boost','reenter','kill','automatic_plague','failure'))
CTX = GenerationContext('k661-explicit-test-domain','experimental')
OUT = Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k661-past-nature-copy-discovery'


def prompt(c, player, target=None):
    options = [ChoiceOption('continue','Continue'),ChoiceOption('fail','Fail',(
        RandomDamage((c.state.players[3-player].hero_id,),1,c.source_id),InvokeBehavior(FAIL,c.source_id,player)))]
    if target is not None:
        options.append(ChoiceOption('reenter','Return and re-enter',(
            ReturnToHand(target),InvokeBehavior(REENTER,c.source_id,player))))
    return RequestChoice(player,tuple(options),c.source_id)


@lru_cache(1)
def full(): return build_registry()


@lru_cache(None)
def fixture(role='writer', mode='normal'):
    r = opening_registry(); original = full()
    for cid in native.SHARED:
        r.register_card(original.card(cid))
        if cid in original.pool_cards:r.register_pool_card(original.pool_card(cid))
    r.register_behavior(SPORES_BEHAVIOR,original.behavior(SPORES_BEHAVIOR))
    r.register_jade_family(original.jade_families[CLASSIC])
    native.register_past_nature_copy_discovery(r)
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(FAIL,lambda c:(_ for _ in ()).throw(ValueError('K661 deliberate rollback')))
    r.register_behavior(DEAD,lambda c:(prompt(c,c.player_id),))
    r.register_behavior(RATTLE,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(TWO),),SummonCause.capture(c)),))
    for cid,cost,hero,kw,extra in ((A,3,CardClass.DRUID,(),{}),(B,4,CardClass.DRUID,(),{}),
            (C,5,CardClass.DRUID,(),{}),(TWO,2,CardClass.NEUTRAL,(Keyword.DIVINE_SHIELD,),{}),
            (MAGE_TWO,2,CardClass.MAGE,(),{}),(HIGH,9,CardClass.NEUTRAL,(),{}),
            (TEN,10,CardClass.NEUTRAL,(),{}),(OVER,11,CardClass.NEUTRAL,(),{}),
            (DORM,2,CardClass.NEUTRAL,(),dict(dormant_turns=2)),
            (BOTH,3,CardClass.NEUTRAL,(),dict(choose_both=True)),
            (DEAD,3,CardClass.NEUTRAL,(),dict(deathrattle=DEAD)),
            (RATTLE,3,CardClass.NEUTRAL,(),dict(deathrattle=RATTLE))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=6,
            keywords=kw,metadata=metadata(hero,tribes=()),**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    for cid,cost,hero,school in ((S1,3,CardClass.MAGE,SpellSchool.ARCANE),
            (S2,4,CardClass.MAGE,SpellSchool.NATURE),(SH,3,CardClass.SHAMAN,SpellSchool.NATURE),
            (PORTAL,0,CardClass.MAGE,SpellSchool.NATURE)):
        extra=dict(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec()) if cid==PORTAL else {}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,on_play=NOOP,
            spell_school=school,metadata=metadata(hero,tribes=()),**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    members = [] if mode=='empty' else [A,B,C,TWO,MAGE_TWO,S1,S2,SH]
    if mode=='unknown':
        missing=P+'unimplemented'
        r.register_pool_card(PoolCard(missing,CardType.MINION,2,metadata(CardClass.DRUID,tribes=()),attack=2))
        members.append(missing)
    r.register_pool(PoolDefinition(native.POOL,'k661-explicit-'+mode,CTX.target_id,CTX.mode,
        tuple(PoolMember(cid) for cid in members),complete=True))
    def reenter(c):
        e=next(c.state.entities[i] for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==A)
        return (SummonStoredCard(CardReference.capture(e),c.player_id,cause=SummonCause.capture(c)),
            GrantKeyword(e.id,Keyword.TAUNT,c.source_id))
    helpers={TAUNT:lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
        BOOST:lambda c:(Buff(c.target_id,3,0,c.source_id),),REENTER:reenter,
        KILL:lambda c:(DestroyBatch(tuple(c.state.players[c.player_id].board),c.source_id),),
        AUTO:lambda c:(CastSpell(c.player_id,'ICC_054',c.source_id),)}
    from hs_sim.engine.model import TargetSpec
    for cid,body in helpers.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=metadata(collectible=False,tribes=()),
            **({'targeting':TargetSpec()} if cid in (TAUNT,BOOST) else {})))
    for mode in ('stats_wait','stats_taunt','entry_wait','kill_enemy','kill_first_scarab','entry_fail','draw_discard'):
        cid=P+'watch.'+mode
        def watch(c, mode=mode):
            event=c.event;target=c.state.entities.get(event.target_id);source=c.state.entities.get(event.source_id)
            if target is None:return ()
            if event.kind=='stats_changed' and source is not None and source.card_id=='BAR_549':
                if mode=='stats_wait':return(prompt(c,target.controller,target.id),)
                if mode=='stats_taunt':return(GrantKeyword(target.id,Keyword.TAUNT,c.source_id),)
            if mode=='draw_discard' and event.kind in ('card_drawn','card_discarded') and source is not None and source.card_id=='BT_128':
                return(prompt(c,target.controller),)
            if event.kind!='minion_summoned':return ()
            if mode=='entry_wait' and target.card_id in (A,'ICC_832t4',TWO,MAGE_TWO):
                return(prompt(c,target.controller),)
            if target.card_id!='ICC_832t4':return ()
            roots=[x for x in c.state.card_summon_history if x.request.cause.source.card_id=='ICC_054']
            if len(roots)!=1:return ()
            if mode=='kill_enemy':
                enemy=next(i for i in c.state.players[3-target.controller].board if c.state.entities[i].card_id==A)
                return(Destroy(enemy,c.source_id),)
            if mode=='kill_first_scarab':return(Destroy(target.id,c.source_id),)
            if mode=='entry_fail':return(RandomDamage((c.state.players[3-target.controller].hero_id,),1,c.source_id),
                InvokeBehavior(FAIL,c.source_id,target.controller))
            return ()
        r.register_behavior(cid,watch)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,metadata=metadata(collectible=False,tribes=()),
            triggers=tuple(TriggerSpec(event,cid) for event in ('stats_changed','minion_summoned','card_drawn','card_discarded'))))
    r.validate();return r


@lru_cache(None)
def host(role='writer'): return build_cn37_local_pool_format()


class NatureCopyDiscoveryTests(CardBatchTestMixin,unittest.TestCase):
    mode='mini'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host' else fixture(role,mode))

    def game(self,hand,*,board=(),enemy=(),deck=(A,)*8,mana=20,maximum=20,watch=None,player=1,mode='normal',cap=None):
        self.mode=mode
        own=PlayerSetup('mage.hero',hand=hand,board=board+((P+'watch.'+watch,) if watch else ()),
            deck=deck,mana=mana,max_mana=maximum,mana_cap=cap or maximum)
        other=PlayerSetup('mage.hero',board=enemy,deck=(A,)*8)
        return Game.from_scenario(Scenario((own,other) if player==1 else (other,own),active_player=player,
            seed=661,generation_context=CTX),fixture(mode=mode))

    def cards(self,g,zone,player=1):return [g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]

    def pick(self,g,want=None):
        q=g.state.pending_choice
        option=q.options[0] if want is None else next(o for o in q.options if o.id==want or o.card_id==want or o.label==want)
        self.choose(g,option.id)

    def finish(self,g):
        while g.state.pending_choice:
            g=self.portable(g)
            keys=[o.id for o in g.state.pending_choice.options]
            if 'continue' in keys:self.choose(g)
            else:self.pick(g)
        return g

    def branch(self,g,key,player=1):
        g.apply(PlayCard(player,self.entity(g,'TTN_955',player).id,branch_id=key))

    def test_complete_forty_one_raw_rows_thirty_verified_faces_and_seventeen_native_definitions(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(len(d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']),41)
        self.assertEqual(len(d['official_observations']),30)
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(cid in r.pool_cards,cid not in native.CHOICES)
        self.assertEqual(len(d['complete_druid_Nature_inventory']),85);self.assertFalse(d['source_scope_bound'])

    def test_both_original_jade_blossom_and_old_swarmer_complete_alternate_faces_validate(self):
        m=batch.read(OUT/'manifest-01.json');rows=batch.pinned_rows(m,Path.cwd());index=batch.catalog_index(m['official_catalogs'],Path.cwd())
        for cid in ('CFM_713','CFM_691'):
            for locale in ('zh_CN','en_US'):
                batch.catalog_official(rows[cid],locale,index,display_normalizations={'{0}':''} if locale=='zh_CN' else {})

    def test_pinned_jade_display_cannot_drop_other_effects_change_identity_numbers_or_normalize_globally(self):
        d=native.load_batch();raw=next(v['record'] for v in d['cards'] if v['record']['id']=='CFM_713')
        face=next(v['face'] for v in d['official_observations'] if v['card_id']=='CFM_713' and v['locale']=='en_US')
        for key,value in [('text_en',raw['text_en'].replace('empty','filled')),('id','other'),('cost',2)]:
            changed=deepcopy(raw);changed[key]=value
            with self.assertRaises(ValueError):batch.check_face(changed,face,'en_US',{})
        with self.assertRaises(ValueError):batch.check_face(raw,face,'en_US',{'@':'','{0}':'','{1}':''})

    def test_spikeshell_current_Taunt_qualifies_but_hand_copy_uses_printed_base(self):
        g=self.game((TAUNT,'BAR_549'),board=(A,));target=self.entity(g,A,zone='board').id
        self.play(g,TAUNT,target);self.play(g,'BAR_549',target)
        copy=self.entity(g,A);self.assertNotEqual(copy.id,target)
        self.assertEqual((copy.attack,copy.max_health),(2,6));self.assertNotIn(Keyword.TAUNT,copy.keywords)
        self.assertEqual((g.state.entities[target].attack,g.state.entities[target].max_health),(4,8))
        self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords)
        no=self.game(('BAR_549',),board=(A,));self.play(no,'BAR_549',no.state.players[1].board[0])
        self.assertEqual(self.cards(no,'hand'),[]);self.portable(g)

    def test_spikeshell_checks_taunt_after_buff_reactions(self):
        g=self.game(('BAR_549',),board=(A,),watch='stats_taunt')
        self.play(g,'BAR_549',self.entity(g,A,zone='board').id)
        self.assertIn(Keyword.TAUNT,self.entity(g,A,zone='board').keywords)
        self.assertNotIn(Keyword.TAUNT,self.entity(g,A).keywords)

    def test_spikeshell_waiting_keyword_copy_rejects_same_entity_new_board_residence(self):
        g=self.game((TAUNT,'BAR_549'),board=(A,),watch='stats_wait');target=self.entity(g,A,zone='board').id
        self.play(g,TAUNT,target);self.play(g,'BAR_549',target)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.choose(g,'reenter')
        self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords)
        self.assertEqual(self.cards(g,'hand'),[]);self.portable(g)

    def test_germination_current_copy_has_taunt_before_entry_reactions_without_changing_original(self):
        g=self.game((BOOST,'BT_129'),board=(A,),watch='entry_wait');original=self.entity(g,A,zone='board').id
        self.play(g,BOOST,original);self.play(g,'BT_129',original)
        self.assertIsNotNone(g.state.pending_choice)
        copied=next(g.state.entities[i] for i in g.state.players[1].board if g.state.entities[i].card_id==A and i!=original)
        self.assertEqual((copied.attack,copied.max_health),(5,6));self.assertIn(Keyword.TAUNT,copied.keywords)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[original].keywords);self.finish(g)

    def test_fungal_fortunes_discards_only_original_minion_arrivals_after_three_draws(self):
        g=self.game(('BT_128',),deck=(A,S1,B));self.play(g,'BT_128')
        self.assertEqual(self.cards(g,'hand'),[S1]);self.assertEqual(len(g.state.draw_history),3)
        self.assertEqual([x.card_id for x in g.state.discard_history],[A,B]);self.portable(g)

    def test_fungal_fortunes_keeps_cwd_child_minion_and_discards_the_later_original_minion(self):
        g=self.game(('BT_128',),deck=(PORTAL,A,S1,B));self.play(g,'BT_128')
        self.assertEqual(self.cards(g,'hand'),[A,S1]);self.assertEqual([x.card_id for x in g.state.discard_history],[B])
        self.portable(g)

    def test_fungal_full_hand_burn_is_not_discard_and_empty_deck_still_fatigues_three_times(self):
        g=self.game(('BT_128',)+(S1,)*9,deck=(A,S2,B));self.play(g,'BT_128')
        self.assertEqual(self.cards(g,'hand'),[S1]*9);self.assertEqual([x.card_id for x in g.state.discard_history],[A])
        empty=self.game(('BT_128',),deck=());self.play(empty,'BT_128')
        self.assertEqual(empty.state.entities[empty.state.players[1].hero_id].health,24)

    def test_fungal_draw_and_discard_waits_restore_and_replay_the_same_original_group(self):
        g=self.game(('BT_128',),deck=(A,S1,B),watch='draw_discard');self.play(g,'BT_128');g=self.finish(g)
        self.assertEqual(self.cards(g,'hand'),[S1]);self.assertEqual(len(g.state.discard_history),2)

    def test_embiggen_buffs_only_own_physical_deck_minions_and_only_adds_cost_below_ten(self):
        g=self.game(('DRG_315',A),deck=(A,HIGH,TEN,OVER,S1));ids=list(g.state.players[1].deck)
        self.play(g,'DRG_315')
        self.assertEqual([local_cost(g.state.entities[i])[0] for i in ids],[4,10,10,11,3])
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health) for i in ids[:4]],[(4,8)]*4)
        self.assertEqual(self.entity(g,A).attack,2);self.portable(g)

    def test_jade_blossom_uses_existing_shared_counter_and_gains_empty_crystals_without_overflow(self):
        g=self.game(('CFM_713','CFM_713'),mana=6,maximum=6,cap=10)
        self.play(g,'CFM_713');self.play(g,'CFM_713')
        self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].max_health) for i in g.state.players[1].board],[(1,1),(2,2)])
        self.assertEqual((g.state.players[1].max_mana,g.state.players[1].mana),(8,0));self.portable(g)

    def test_jade_blossom_full_board_still_gains_its_empty_crystal(self):
        g=self.game(('CFM_713',),board=(A,)*7,mana=6,maximum=6,cap=10);self.play(g,'CFM_713')
        self.assertEqual((len(g.state.players[1].board),g.state.players[1].max_mana),(7,7))

    def test_poison_seeds_destroys_one_batch_waits_for_deaths_then_uses_original_side_counts(self):
        g=self.game(('FP1_019',),board=(A,DEAD),enemy=(A,));self.play(g,'FP1_019')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((self.cards(g,'board'),self.cards(g,'board',2)),([],[]))
        g=self.finish(g)
        self.assertEqual(self.cards(g,'board'),['FP1_019t']*2);self.assertEqual(self.cards(g,'board',2),['FP1_019t'])

    def test_poison_seeds_finishes_old_deathrattle_summons_before_named_treant_replacement(self):
        g=self.game(('FP1_019',),board=(RATTLE,));self.play(g,'FP1_019')
        self.assertEqual(self.cards(g,'board'),[TWO,'FP1_019t']);self.portable(g)

    def test_plague_repeats_effect_without_extra_payment_or_cast_records(self):
        g=self.game(('ICC_054',),enemy=(A,)*3);self.play(g,'ICC_054')
        self.assertEqual(self.cards(g,'board'),['ICC_832t4']*3)
        self.assertEqual((g.state.players[1].mana,len(g.state.cast_history)),(14,1))
        roots=g.state.card_summon_history;self.assertEqual(len(roots),3)
        self.assertTrue(all(x.request.materials[0].followup_policy=='original_delivery' for x in roots));self.portable(g)

    def test_plague_rechecks_actual_enemy_after_each_entry_and_ignores_dormant_minions(self):
        g=self.game(('ICC_054',),enemy=(A,)*3,watch='kill_enemy');self.play(g,'ICC_054')
        self.assertEqual(self.cards(g,'board').count('ICC_832t4'),1)
        dormant=self.game(('ICC_054',),enemy=(A,A,DORM));self.play(dormant,'ICC_054')
        self.assertEqual(self.cards(dormant,'board'),['ICC_832t4']*2)

    def test_plague_original_delivery_continues_even_if_first_scarab_dies_during_entry(self):
        g=self.game(('ICC_054',),enemy=(A,)*3,watch='kill_first_scarab');self.play(g,'ICC_054')
        self.assertEqual(self.cards(g,'board').count('ICC_832t4'),2)
        self.assertEqual(len(g.state.card_summon_history),3);self.portable(g)

    def test_plague_automatic_full_board_failure_has_no_recursive_retry(self):
        g=self.game((AUTO,),board=(A,)*6+(DORM,),enemy=(A,)*7);self.play(g,AUTO)
        self.assertEqual(self.cards(g,'board').count('ICC_832t4'),0)
        self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)

    def test_plague_waiting_entries_restore_and_late_random_failure_rolls_back_complete_action(self):
        g=self.game(('ICC_054',),enemy=(A,)*3,watch='entry_wait');self.play(g,'ICC_054');g=self.finish(g)
        self.assertEqual(self.cards(g,'board').count('ICC_832t4'),2)
        bad=self.game(('ICC_054',),enemy=(A,)*3,watch='entry_fail');before=bad.snapshot()
        with self.assertRaises(ResolutionError):self.play(bad,'ICC_054')
        self.assertEqual(bad.snapshot(),before)

    def test_crystalsong_uses_explicit_druid_scope_and_no_choice_keep_three_when_hand_has_no_minions(self):
        g=self.game(('DAL_352',));self.play(g,'DAL_352')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(set(self.cards(g,'hand')),{A,B,C})
        one=self.game(('DAL_352',TWO));self.play(one,'DAL_352');one=self.portable(one)
        self.assertEqual(len(one.state.pending_choice.options),3);self.pick(one,A)
        self.assertEqual(self.cards(one,'hand'),[TWO,A]);self.portable(one)

    def test_unknown_pool_member_is_not_cropped_or_silently_generated_as_blank(self):
        g=self.game(('DAL_352',),mode='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'DAL_352')
        self.assertEqual(g.snapshot(),before)

    def test_planted_evidence_chosen_discount_expires_at_the_actual_turn_end(self):
        g=self.game(('REV_313',));self.play(g,'REV_313');g=self.portable(g);self.pick(g,S1)
        self.assertEqual(local_cost(self.entity(g,S1))[0],1)
        g.apply(EndTurn(1));self.assertEqual(local_cost(self.entity(g,S1))[0],3);self.portable(g)

    def test_nature_studies_next_spell_discount_survives_turn_and_minion_play_then_consumes_once(self):
        g=self.game(('SCH_333',A,S1));self.play(g,'SCH_333');self.pick(g,S2)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,A)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,S1)).amount,2)
        mana=g.state.players[1].mana;self.play(g,S1)
        self.assertEqual(mana-g.state.players[1].mana,2)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,S2)).amount,4);self.portable(g)

    def test_lifebinders_real_branches_and_combined_reduce_successful_new_arrivals_once(self):
        g=self.game(('TTN_955',));self.branch(g,'TTN_955A')
        self.assertEqual(len(g.state.players[1].hand),2);self.assertEqual(native.NATURE.class_mode,'any')
        self.assertTrue(all(fixture().card(cid).spell_school==SpellSchool.NATURE for cid in self.cards(g,'hand')))
        discount=self.game(('TTN_955',S1,S2,A));self.branch(discount,'TTN_955B')
        self.assertEqual([local_cost(self.entity(discount,cid))[0] for cid in (S1,S2,A)],[2,3,3])
        both=self.game(('TTN_955',S1),board=(BOTH,));self.branch(both,'TTN_955:combined')
        for i in both.state.players[1].hand:
            e=both.state.entities[i];self.assertEqual(local_cost(e)[0],fixture().card(e.card_id).cost-1)
        self.assertEqual((len(both.state.cast_history),both.state.players[1].mana),(1,18));self.portable(both)

    def test_evolving_spores_one_choice_adapts_both_original_targets_and_preserves_private_menu(self):
        g=self.game(('UNG_103',),board=(A,A));original=list(g.state.players[1].board)
        self.play(g,'UNG_103');self.assertEqual(len(g.state.pending_choice.options),3)
        g=self.portable(g);self.pick(g)
        values=[(g.state.entities[i].attack,g.state.entities[i].max_health,tuple(sorted(g.state.entities[i].keywords)),len(g.state.entities[i].abilities)) for i in original]
        self.assertEqual(values[0],values[1]);self.assertNotEqual(values[0],(2,6,(),0));self.portable(g)

    def test_cactus_keeps_actual_selected_card_and_has_one_two_copy_ready_before_entry(self):
        g=self.game(('WW_818',),watch='entry_wait');self.play(g,'WW_818');g=self.portable(g);self.pick(g,TWO)
        self.assertIsNotNone(g.state.pending_choice)
        hand=self.entity(g,TWO);copy=self.entity(g,TWO,zone='board')
        self.assertNotEqual(hand.id,copy.id);self.assertEqual((hand.attack,hand.max_health),(2,6))
        self.assertEqual((copy.attack,copy.max_health),(1,2));self.assertIn(Keyword.DIVINE_SHIELD,copy.keywords)
        self.finish(g)

    def test_public_condition_and_original_delivery_declarations_reject_unbound_or_unknown_policies(self):
        g=self.game((A,));ref=CardReference.capture(self.entity(g,A))
        with self.assertRaises(ValueError):CopyCard(ref,1,required_keyword=Keyword.TAUNT,source_id=ref.entity_id)
        with self.assertRaises(ValueError):SummonEntryMaterial('ICC_832t4',followup_policy='original_delivery')
        with self.assertRaises(ValueError):SummonEntryMaterial('ICC_832t4',on_summon='x',followup_policy='unknown')
        from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup,DrawGroupReward,DrawGroupSlot
        with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,(DrawGroupSlot(),),DrawGroupReward('discard_drawn_minions'))

    def test_second_player_generated_nature_hand_is_hidden_from_opponent(self):
        g=self.game(('TTN_955',),player=2);self.branch(g,'TTN_955A',player=2)
        view=json.dumps(g.for_player(1).observe())+json.dumps(g.player_events(1))
        for card in self.cards(g,'hand',2):self.assertNotIn(card,view)
        self.portable(g)

    def test_real_standard_host_copy_deck_jade_replacement_plague_and_group_adapt_execute(self):
        self.mode='host';f=host()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('BT_132','BAR_549','BT_129','DRG_315','BT_128','CFM_713','ICC_054','FP1_019','UNG_103'),
            board=('CORE_CS2_182',),deck=('CORE_CS2_182','CS2_013t','CORE_CS2_182'),mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('HERO_08',board=('CORE_CS2_182',)*3)),seed=661,generation_context=f.context),f.registry)
        target=g.state.players[1].board[0]
        for cid in ('BT_132','BAR_549','BT_129'):self.play(g,cid,target)
        for cid in ('DRG_315','BT_128','CFM_713','ICC_054','FP1_019','UNG_103'):self.play(g,cid)
        self.assertIsNotNone(g.state.pending_choice);g=self.finish(g)
        self.assertTrue(g.state.players[1].board)
        with self.assertRaises(UnsupportedDefinitionError):resolve_candidates(f.registry,f.context,PAST_POOL,QUERIES[WO],
            current_class=CardClass.DRUID,source_card_id=WO,exclude_source_by_rule=True)

    def test_real_standard_host_discovery_and_actual_fandral_combined_use_full_bound_domains(self):
        self.mode='host';f=host()
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=('DAL_352','REV_313','SCH_333','TTN_955','WW_818'),
            board=('OG_044',),mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08')),seed=662,generation_context=f.context),f.registry)
        self.play(g,'DAL_352');self.assertEqual(len(g.state.players[1].hand),7)
        for cid in ('REV_313','SCH_333'):
            self.play(g,cid)
            while g.state.pending_choice:self.pick(g)
        mana=g.state.players[1].mana;self.branch(g,'TTN_955:combined')
        self.assertEqual(mana-g.state.players[1].mana,1)
        self.play(g,'WW_818')
        saved=json.loads(json.dumps(g.snapshot()))
        restored=Game.from_snapshot(saved,host('independent-reader').registry)
        self.assertEqual(restored.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved);g=restored
        while g.state.pending_choice:self.pick(g)
        self.assertGreaterEqual(len(g.state.players[1].board),2);self.portable(g)
