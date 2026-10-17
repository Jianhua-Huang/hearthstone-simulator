"""Six native card entries and one unchanged complete fixed-summon dependency."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p33_cards import STONE,INVOCATION,MACHINE,CLASH,WIZARD,HOOK,CANNON,ROOTS,DEPENDENCIES,EXISTING_DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p33_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import ChoicePurpose,LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p33.test.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';FOUR='CORE_CS2_179';ONE='JAIL_460';BRIGHT='CORE_EX1_189';WITCH='CORE_GIL_531';PIRATE='CORE_DRG_024';ALL='DINO_435';REGROWTH='TIME_033';MAGE='CS2_029';DUAL='END_025';NEUTRAL='TIME_EVENT_999';REWIND_SPELL='TIME_000';UNKNOWN_PIRATE=TEST+'unknown_pirate';UNKNOWN_BC=TEST+'unknown_battlecry_fact'
MEMBERS=(*ROOTS,YETI,TWO,FOUR,ONE,BRIGHT,WITCH,PIRATE,ALL,REGROWTH,MAGE,DUAL,NEUTRAL,REWIND_SPELL);CONTEXT=GenerationContext('p33-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p33_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid in r.pool_cards:continue
        if cid=='UNG_072':
            raw=next(x['record']for x in load_batch()['evidence_only']if x['record']['id']==cid)
            r.register_pool_card(PoolCard(cid,CardType.MINION,raw['cost'],metadata_from_record(raw),keywords=(Keyword.TAUNT,),battlecry=True))
        elif cid in(UNKNOWN_PIRATE,UNKNOWN_BC):r.register_pool_card(PoolCard(cid,CardType.MINION,2,CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=('pirate',)if cid==UNKNOWN_PIRATE else(),factions=(),subtypes=()),battlecry=False if cid==UNKNOWN_PIRATE else None))
        else:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p33-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_behavior(TEST+'kill',lambda c:(Destroy(c.target_id,c.source_id),));r.register_card(CardDefinition(TEST+'kill','Native death fixture',CardType.SPELL,on_play=TEST+'kill',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=META))
    for cid in(STONE,WIZARD):
        key=TEST+'summon.'+cid;r.register_behavior(key,lambda c,card=cid:(Summon(1,card),));r.register_card(CardDefinition(key,'Natural summon',CardType.SPELL,on_play=key,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P33 deliberate fixed/pool continuation failure')))
    if mode:
        def eligible(c):
            expected=HOOK if mode in('wait','fail_hook')else CLASH
            return c.event.player_id==1 and any(root.request.cause.source.card_id==expected and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.startswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Original summon reaction',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP33Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08'):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=3333,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,card=None,key=None):
        q=g.state.pending_choice;chosen=key if key is not None else next(o.id for o in q.options if card is None or o.card_id==card);g.apply(SelectChoice(q.player_id,q.id,(chosen,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def summons(self,g,source):
        ids={d.entity.entity_id for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered'}
        return[e for e in g.events if e.kind=='minion_summoned'and e.target_id in ids]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','rewind_session','candidate_root_ids','card_summon_history'):self.assertNotIn('"'+key+'"',public)
        return other
    def actual(self,g,cid,key=None):return resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[key or cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)

    def test_nine_complete_rows_twelve_faces_exact_case_metadata_and_dependency(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['existing_dependencies']+d['evidence_only']),9);self.assertEqual(len(d['official_observations']['observations']),12);self.assertEqual(STONE,'Core_UNG_072');self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,raw['cost']);self.assertEqual(c.keywords,(Keyword.TAUNT,)if cid in(STONE,MACHINE)else(Keyword.REWIND,)if cid==WIZARD else())
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],c.cost))
        dependency,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(r.card(CANNON))),dependency['definition_sha256']);self.assertEqual(canonical_digest(dependency['definition']),dependency['definition_sha256']);self.assertEqual(r.card(MACHINE).metadata.tribes,('mech',));self.assertIsNone(r.card(MACHINE).rewind);self.assertIsNone(r.card(INVOCATION).battlecry);self.assertEqual(QUERIES[INVOCATION].ability.basis,'printed')

    def test_six_new_defs_complete_old_defs_catalog_families_and_cannon_preserved(self):
        with patch('hs_sim.cards.simple_followup_p33_cards.register_simple_followup_p33_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertEqual(EXISTING_DEPENDENCIES,(CANNON,));self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(asdict(before.card(CANNON)),asdict(after.card(CANNON)));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else row,after.pool_card(cid))
        for cid in('UNG_072','GIL_836'):self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default311_fingerprint_and_no_formal_pool(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_exact_taunt_printed_battlecry_rewind_anykind_and_class_without_neutral(self):
        g=self.game();self.assertEqual({m.card_id for m in self.actual(g,STONE)},{TWO,FOUR,MACHINE});self.assertEqual({m.card_id for m in self.actual(g,INVOCATION)},{STONE,WIZARD,BRIGHT});self.assertEqual({m.card_id for m in self.actual(g,MACHINE)},{WIZARD,REGROWTH,REWIND_SPELL,NEUTRAL});self.assertEqual({m.card_id for m in self.actual(g,WIZARD)},{MAGE,DUAL,REWIND_SPELL});self.assertFalse(QUERIES[WIZARD].include_neutral);self.assertEqual(QUERIES[MACHINE].kinds,());self.assertEqual({m.card_id for m in self.actual(g,HOOK)},{ALL})

    def test_stone_paid_native_battlecry_distinct_private_taunt_offers(self):
        g=self.game((STONE,),members=(TWO,FOUR,STONE));source=self.play(g,STONE);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{TWO,FOUR});self.assertEqual(g.state.players[1].mana,47);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});self.choose(g,TWO);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,TWO);self.assertNotEqual(event.target_id,source);self.assertEqual(len(g.state.battlecry_history),1)

    def test_stone_source_and_old_edition_only_empty_before_rng_and_execution(self):
        g=self.game((STONE,),members=(STONE,'UNG_072'));self.assertNotIn('UNG_072',g.registry.cards);before=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Excluded source editions consumed RNG'))as calls:self.play(g,STONE);calls.assert_not_called()
        self.assertEqual(g._rng.getstate(),before);self.assertIsNone(g.state.pending_choice)

    def test_invocation_printed_bc_discount_flat_minus_one_permanent_and_zero_floor(self):
        for card,expected in((BRIGHT,1),(WITCH,0)):
            with self.subTest(card=card):
                g=self.game((INVOCATION,card),members=(card,),hero='HERO_02');old=self.first(g,card).id;source=self.play(g,INVOCATION);self.choose(g);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertEqual(g.quote_cost(new.id).amount,expected);self.assertEqual(g.quote_cost(old).amount,g.registry.card(card).cost);self.assertTrue(any(e.cost==-1 and e.set_cost is None and e.expires_turn is None for e in new.enchantments));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,expected)

    def test_unknown_printed_battlecry_fact_is_not_inferred_or_silently_filtered(self):
        g=self.game((INVOCATION,),members=(BRIGHT,UNKNOWN_BC));saved=g.snapshot()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown ability sampled'))as calls:
            with self.assertRaises(ResolutionError):self.play(g,INVOCATION)
            calls.assert_not_called()
        self.assertEqual(g.snapshot(),saved)

    def test_machine_native_death_gets_minion_or_spell_rewind_without_own_rewind(self):
        for card in(REGROWTH,REWIND_SPELL):
            with self.subTest(card=card):
                g=self.game((TEST+'kill',),board=(MACHINE,),members=(card,));source=self.first(g,MACHINE,'board').id;self.play(g,TEST+'kill',source);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,card);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.deathrattle_history[0].capture.ability.deathrattle_card_id,MACHINE)

    def test_clash_three_ordered_pool_requests_and_exactly_one_overload_lock(self):
        g=self.game((CLASH,),members=(STONE,TWO,ONE));source=self.play(g,CLASH);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[STONE,TWO,ONE]);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.players[1].overload_owed,1);self.assertEqual(len(g.state.overload_history),1);self.assertFalse(g.state.battlecry_history);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual((g.state.players[1].overload_locked,g.state.players[1].overload_owed,g.state.players[1].mana),(1,0,49))

    def test_clash_capacity_checked_per_request_last_skips_rng_but_overload_still_one(self):
        g=self.game((CLASH,),board=(YETI,)*5,members=(STONE,TWO,ONE));rng=random.Random();rng.setstate(g._rng.getstate())
        for n in(3,2):sample_candidates(rng,self.actual(g,CLASH,CLASH+'.'+str(n)),1,replacement=True)
        source=self.play(g,CLASH);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[STONE,TWO]);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].overload_owed,1);self.assertEqual(g.state.card_summon_history[-1].status,'skipped')

    def test_wizard_current_priest_gets_two_dual_spells_no_neutral_then_keep(self):
        g=self.game((WIZARD,),members=(MAGE,DUAL,NEUTRAL),hero='HERO_09');source=self.play(g,WIZARD);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],[DUAL,DUAL]);self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g.state.players[1].mana,45);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.REWIND);self.choose(g,key='keep');self.assertFalse(g.state.cast_history)

    def test_wizard_retry_replaces_two_hand_identities_and_commits_one_payment(self):
        g=self.game((WIZARD,),members=(MAGE,));source=self.play(g,WIZARD);old=set(g.state.players[1].hand);self.choose(g,key='retry');self.assertIsNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].hand),2);self.assertTrue(old.isdisjoint(g.state.players[1].hand));self.assertEqual(g.state.players[1].mana,45);self.assertEqual(g.state.players[1].board,[source]);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_wizard_full_hand_burns_second_new_instance_before_keep(self):
        g=self.game((WIZARD,)+(YETI,)*9,members=(MAGE,));source=self.play(g,WIZARD);self.assertEqual(len(self.created(g,source)),2);self.assertEqual(len([e for e in g.events if e.kind=='card_burned']),1);self.assertEqual(len(g.state.players[1].hand),10);self.choose(g,key='keep')

    def test_natural_summon_stone_or_wizard_skips_battlecry_and_rewind_without_pool(self):
        for cid in(STONE,WIZARD):
            with self.subTest(cid=cid):
                key=TEST+'summon.'+cid;g=self.game((key,),pool=False,context=None);self.play(g,key);self.assertFalse(g.state.battlecry_history);self.assertIsNone(g.state.pending_choice)

    def test_hook_waits_for_discovery_then_two_original_cannons_keep_real_endturn_effect(self):
        g=self.game((HOOK,),members=(PIRATE,),hero='HERO_01');source=self.play(g,HOOK);self.assertFalse(self.summons(g,source));self.assertIsNotNone(g.state.pending_choice);self.choose(g);events=self.summons(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],[CANNON,CANNON]);self.assertEqual(len({e.target_id for e in events}),2);self.assertTrue(all(g.state.entities[e.target_id].attack==g.state.entities[e.target_id].max_health==1 for e in events));self.assertEqual(g.state.players[1].mana,48);self.assertFalse(g.state.battlecry_history);self.assertTrue(all(r.request.cause.source.entity_id==source and r.request.cause.cast_card_id==HOOK for r in g.state.card_summon_history));g.apply(EndTurn(1));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,28)

    def test_hook_empty_discovery_still_summons_two_fixed_cannons(self):
        g=self.game((HOOK,),members=(YETI,));source=self.play(g,HOOK);self.assertIsNone(g.state.pending_choice);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.summons(g,source)],[CANNON,CANNON]);self.assertFalse(self.created(g,source))

    def test_hook_full_board_keeps_selected_card_and_skips_both_fixed_summons(self):
        g=self.game((HOOK,),board=(YETI,)*7,members=(PIRATE,),hero='HERO_01');source=self.play(g,HOOK);self.choose(g);self.assertEqual(len(self.created(g,source)),1);self.assertFalse(self.summons(g,source));self.assertEqual([r.status for r in g.state.card_summon_history],['skipped','skipped'])

    def test_unknown_matching_candidates_fail_before_rng_and_roll_back_entries(self):
        for cid,unknown in((STONE,'TIME_041'),(INVOCATION,'CATA_186'),(MACHINE,'CORE_EDR_004_2026'),(WIZARD,'DINO_414'),(HOOK,UNKNOWN_PIRATE)):
            with self.subTest(cid=cid):
                death=cid==MACHINE;g=self.game((TEST+'kill',)if death else(cid,),board=(cid,)if death else(),members=(*MEMBERS,unknown));saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown candidate reached RNG'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,cid,'board').id)if death else self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_clash_unknown_second_group_rolls_back_first_summon_and_no_overload(self):
        g=self.game((CLASH,),members=(STONE,'CAP_104',ONE));saved=g.snapshot();original=random.Random.randrange
        with patch.object(random.Random,'randrange',autospec=True,side_effect=original)as calls:
            with self.assertRaises(ResolutionError):self.play(g,CLASH)
            self.assertTrue(calls.called)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.state.players[1].overload_owed,0)

    def test_missing_context_or_matching_pool_rolls_back_native_entries(self):
        for cid in(STONE,INVOCATION,CLASH,WIZARD,HOOK):
            with self.subTest(cid=cid):
                g=self.game((cid,),context=None);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,cid)
                self.assertEqual(g.snapshot(),saved)
        g=self.game((HOOK,),pool=False);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,HOOK)
        self.assertEqual(g.snapshot(),saved)

    def test_hook_first_fixed_summon_wait_restore_clone_replay_bad_resume_and_second(self):
        g=self.game((HOOK,),members=(PIRATE,),hero='HERO_01',mode='wait');source=self.play(g,HOOK);self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.summons(g,source)),1);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key='ok');self.choose(other,key='ok');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.summons(g,source)),2);self.portable(g)

    def test_late_clash_summon_failure_rolls_back_payment_summon_and_overload(self):
        g=self.game((CLASH,),members=(STONE,TWO,ONE),mode='fail_clash');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,CLASH)
        self.assertEqual(g.snapshot(),saved)

    def test_late_hook_after_choice_failure_preserves_committed_offer_and_cause(self):
        g=self.game((HOOK,),members=(PIRATE,),hero='HERO_01',mode='fail_hook');self.play(g,HOOK);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual([o.card_id for o in g.state.pending_choice.options],[PIRATE])

if __name__=='__main__':unittest.main()
