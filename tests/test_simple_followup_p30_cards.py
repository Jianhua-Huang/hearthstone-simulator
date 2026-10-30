"""Native attributed pool producers over explicit experimental inventories."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p30_cards import MAZE,MONGREL,SNEED,TOOLS,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p30_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p30.test.';YETI='CORE_CS2_182';TWO='BT_156';VICAR='CORE_ONY_022';BRIGHT='CORE_EX1_189';MAGE4='CS2_029';HOLY4='CORE_CFM_604';SHADOW4='CORE_EX1_197';OLD_SNEED='GVG_114'
MEMBERS=(*ROOTS,TWO,VICAR,BRIGHT,YETI,MAGE4,HOLY4,SHADOW4);CONTEXT=GenerationContext('p30-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p30_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid in r.pool_cards:continue
        if cid.startswith(TEST+'missing.'):
            original=r.pool_card(cid[len(TEST+'missing.'):])
            r.register_pool_card(replace(original,card_id=cid,metadata=replace(original.metadata,deck_identity=cid)))
        elif cid==OLD_SNEED:
            raw=next(x['record']for x in load_batch()['evidence_only']if x['record']['id']==cid)
            r.register_pool_card(PoolCard(cid,CardType.MINION,raw['cost'],metadata_from_record(raw),battlecry=False))
        else:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p30-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for name,body in(('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'summon',lambda c:(Summon(1,MAZE),));r.register_card(CardDefinition(TEST+'summon','Natural summon',CardType.SPELL,on_play=TEST+'summon',metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P30 deliberate producer arrival failure')))
    if mode:
        def eligible(c):
            if c.event.player_id!=1:return False
            if mode=='fail_hand':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==TOOLS
            return any(root.request.cause.source.card_id==MONGREL and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode.startswith('fail'):return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',(Destroy(c.event.target_id,c.source_id),)),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Original producer arrival reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail_hand'else'minion_summoned',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP30Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=3030,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def summons(self,g,source):
        ids={d.entity.entity_id for root in g.state.card_summon_history if root.request.cause.source.entity_id==source for d in root.deliveries if d.outcome=='delivered'}
        return[e for e in g.events if e.kind=='minion_summoned'and e.target_id in ids]
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','pool_summon_history','card_summon_history','candidate_root_ids'):self.assertNotIn('"'+key+'"',public)
        return other
    def candidates(self,r,cid,actual=True):return resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[cid],source_card_id=cid,exclude_source_by_rule=actual,player_id=1)

    def test_six_complete_rows_eight_faces_current_stats_and_full_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['evidence_only']),6);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords)
            if cid!=TOOLS:self.assertEqual((c.attack,c.health),(raw['attack'],raw['health']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f.get('attack'),f.get('health')),(raw['dbf_id'],c.cost,raw['attack'],raw['health']))
        self.assertEqual((r.card(MAZE).cost,r.card(MAZE).attack,r.card(MAZE).health),(2,1,1));self.assertEqual((r.card(MONGREL).cost,r.card(MONGREL).attack,r.card(MONGREL).health),(7,8,6));self.assertEqual((r.card(SNEED).cost,r.card(SNEED).attack,r.card(SNEED).health),(7,5,7));self.assertEqual(r.card(SNEED).metadata.tribes,('mech',));self.assertEqual(r.card(MONGREL).metadata.tribes,('dragon',));self.assertIsNone(r.card(TOOLS).spell_school)

    def test_four_new_defs_old_definitions_aliases_catalog_and_families_preserved(self):
        with patch('hs_sim.cards.simple_followup_p30_cards.register_simple_followup_p30_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else row,after.pool_card(cid))
        for cid in('REV_308','GVG_114'):self.assertEqual(cid in before.cards,cid in after.cards)
        self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_exact_queries_distinguish_pure_lookup_from_actual_source_exclusion(self):
        r=registry();self.assertEqual({m.card_id for m in self.candidates(r,MAZE,False)},{MAZE,TWO,VICAR,BRIGHT});self.assertEqual({m.card_id for m in self.candidates(r,MAZE)},{TWO,VICAR,BRIGHT});self.assertEqual({m.card_id for m in self.candidates(r,MONGREL)},{YETI});self.assertEqual({m.card_id for m in self.candidates(r,SNEED)},{BRIGHT});self.assertEqual({m.card_id for m in self.candidates(r,TOOLS)},{MAGE4,HOLY4,SHADOW4})
        for q in QUERIES.values():self.assertEqual(q.class_mode,'any');self.assertTrue(q.collectible)

    def test_maze_paid_battlecry_attributed_summon_does_not_invoke_target_battlecry(self):
        g=self.game((MAZE,),members=(VICAR,));rng=random.Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,self.candidates(g.registry,MAZE),1,replacement=True);source=self.play(g,MAZE);event,=self.summons(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,expected[0]);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,48);self.assertEqual(len(g.state.battlecry_history),1);self.assertIsNone(g.state.pending_choice);root,=g.state.card_summon_history;self.assertEqual(root.request.cause.source.entity_id,source);self.assertEqual(root.status,'completed');self.portable(g)

    def test_maze_natural_summon_does_not_invoke_battlecry_without_context(self):
        g=self.game((TEST+'summon',),pool=False,context=None);self.play(g,TEST+'summon');self.assertEqual(self.first(g,MAZE,'board').card_id,MAZE);self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.card_summon_history)

    def test_mongrel_native_death_two_original_draws_independent_entities_and_cause(self):
        g=self.game((TEST+'kill',),board=(MONGREL,),members=(YETI,));source=self.first(g,MONGREL,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());expected=sample_candidates(rng,self.candidates(g.registry,MONGREL),2,replacement=True);self.play(g,TEST+'kill',source);events=self.summons(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],list(expected));self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g._rng.getstate(),rng.getstate());root,=g.state.pool_summon_history;self.assertEqual(root.selected,tuple(expected));self.assertEqual(root.spec.cause.source.entity_id,source);self.assertEqual(root.status,'completed');self.assertEqual(len(root.entry_root_ids),2);death,=g.state.deathrattle_history;self.assertEqual(death.capture.ability.deathrattle_card_id,MONGREL);self.assertTrue(death.completed)

    def test_sneed_native_death_excludes_self_and_other_printing_of_same_source(self):
        g=self.game((TEST+'kill',),board=(SNEED,),members=(SNEED,OLD_SNEED,BRIGHT));self.assertIn(OLD_SNEED,g.registry.cards);source=self.first(g,SNEED,'board').id;self.play(g,TEST+'kill',source);event,=self.summons(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,BRIGHT);self.assertFalse(g.state.battlecry_history);self.assertFalse(self.created(g,source));root,=g.state.card_summon_history;self.assertEqual(root.request.cause.source.entity_id,source);self.assertEqual([m.card_id for m in root.request.pool_basis.candidates],[BRIGHT]);self.portable(g)

    def test_sneed_source_family_only_is_empty_before_implementation_and_rng(self):
        g=self.game((TEST+'kill',),board=(SNEED,),members=(SNEED,OLD_SNEED));source=self.first(g,SNEED,'board').id;saved_rng=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Excluded source-only pool consumed RNG'))as calls:self.play(g,TEST+'kill',source);calls.assert_not_called()
        self.assertFalse(self.summons(g,source));self.assertEqual(g._rng.getstate(),saved_rng);self.assertFalse(g.state.players[1].board);self.assertTrue(g.state.deathrattle_history[0].completed)

    def test_full_board_maze_skips_one_draw_but_keeps_native_payment(self):
        g=self.game((MAZE,),board=(YETI,)*6,members=(TWO,));saved_rng=g._rng.getstate();source=self.play(g,MAZE);self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.summons(g,source));self.assertEqual(g._rng.getstate(),saved_rng);self.assertEqual(g.state.players[1].mana,48)

    def test_mongrel_one_slot_presamples_both_entries_then_records_capacity_failure(self):
        g=self.game((TEST+'kill',),board=(MONGREL,)+(YETI,)*6,members=(YETI,));source=self.first(g,MONGREL,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());sample_candidates(rng,self.candidates(g.registry,MONGREL),2,replacement=True);self.play(g,TEST+'kill',source);self.assertEqual(len(self.summons(g,source)),1);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(g._rng.getstate(),rng.getstate());root,=g.state.pool_summon_history;self.assertEqual(root.selected,(YETI,YETI));self.assertEqual([d.outcome for r in g.state.card_summon_history for d in r.deliveries],['delivered','board_full'])

    def test_tools_paid_three_two_independent_permanent_minus_two_instances(self):
        g=self.game((TOOLS,MAGE4),members=(MAGE4,));old=self.first(g,MAGE4).id;source=self.play(g,TOOLS);events=self.created(g,source);self.assertEqual(len(events),2);self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g.state.players[1].mana,47);self.assertEqual(g.quote_cost(old).amount,4)
        for event in events:
            new=g.state.entities[event.target_id];self.assertEqual((new.card_id,new.base_cost,g.quote_cost(new.id).amount),(MAGE4,4,2));self.assertTrue(any(e.cost==-2 and e.set_cost is None and e.expires_turn is None for e in new.enchantments))
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertTrue(all(g.quote_cost(e.target_id).amount==2 for e in events));self.portable(g)

    def test_tools_full_hand_one_arrival_one_burn_retains_creation_discount(self):
        g=self.game((TOOLS,)+(YETI,)*9,members=(HOLY4,));source=self.play(g,TOOLS);events=self.created(g,source);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(len(events),2);self.assertIn(burn.target_id,{e.target_id for e in events});self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.entities[burn.target_id].card_id,HOLY4);self.assertTrue(any(e.cost==-2 and e.set_cost is None for e in g.state.entities[burn.target_id].enchantments))

    def test_missing_context_or_pool_errors_roll_back_summon_and_hand_generation(self):
        for cid in(MAZE,TOOLS):
            for context,pool in((None,True),(CONTEXT,False)):
                with self.subTest(cid=cid,context=context,pool=pool):
                    g=self.game((cid,),context=context,pool=pool);saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,cid)
                    self.assertEqual(g.snapshot(),saved)

    def test_real_filter_facts_with_missing_definitions_fail_before_rng_including_full_board(self):
        for cid,known in((MAZE,'CATA_614'),(MONGREL,'CAP_005'),(SNEED,'BE_036'),(TOOLS,'CATA_567')):
            unknown=TEST+'missing.'+known
            with self.subTest(cid=cid):
                death=cid in(MONGREL,SNEED);g=self.game((TEST+'kill',)if death else(cid,),board=(cid,)if death else(YETI,)*6 if cid==MAZE else(),members=(*MEMBERS,unknown));self.assertNotIn(unknown,g.registry.cards);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligible validation'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,cid,'board').id)if death else self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_first_batch_arrival_wait_restore_replay_bad_choice_and_original_second_draw(self):
        g=self.game((TEST+'kill',),board=(MONGREL,),members=(YETI,),mode='wait');source=self.first(g,MONGREL,'board').id;self.play(g,TEST+'kill',source);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(self.summons(g,source)),1);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);rng=g._rng.getstate();other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng);self.assertEqual(len(self.summons(g,source)),2);self.assertEqual(g.state.pool_summon_history[0].selected,(YETI,YETI));self.assertTrue(g.state.deathrattle_history[0].completed);self.portable(g)

    def test_late_arrival_errors_roll_back_original_cast_or_whole_death_batch(self):
        for spell in(True,False):
            with self.subTest(spell=spell):
                g=self.game((TOOLS,)if spell else(TEST+'kill',),board=()if spell else(MONGREL,),members=(YETI,MAGE4),mode='fail_hand'if spell else'fail_board');saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,TOOLS)if spell else self.play(g,TEST+'kill',self.first(g,MONGREL,'board').id)
                self.assertEqual(g.snapshot(),saved)

    def test_silence_removes_both_native_deathrattles_without_pool(self):
        for cid in(MONGREL,SNEED):
            with self.subTest(cid=cid):
                g=self.game((TEST+'silence',TEST+'kill'),board=(cid,),pool=False,context=None);source=self.first(g,cid,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source);self.assertFalse(g.state.deathrattle_history);self.assertFalse(self.summons(g,source))

if __name__=='__main__':unittest.main()
