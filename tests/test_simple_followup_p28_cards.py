"""Explicit experimental format pools assembled before the complete catalog pass."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import candidate_pool_rows,register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p28_cards import WITCH,DRAGON,CHAMPION,MENDER,ROOTS,DEPENDENCIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p28_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p28.test.';YETI='CORE_CS2_182';SHAMAN='CORE_EX1_238';MAGE='CS2_029';HOLY='CORE_CFM_604';SHADOW='CORE_EX1_197';BRIGHT='CORE_EX1_189';SMALL='CATA_556';ALL='DINO_435';DUAL='CATA_155'
MEMBERS=(*ROOTS,SHAMAN,MAGE,HOLY,SHADOW,BRIGHT,SMALL,ALL,DUAL,YETI);CONTEXT=GenerationContext('p28-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p28_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p28-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for name,body in(('kill',lambda c:(Destroy(c.target_id,c.source_id),)),('silence',lambda c:(Silence(c.target_id),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'summon',lambda c:(Summon(1,WITCH),));r.register_card(CardDefinition(TEST+'summon','Natural summon',CardType.SPELL,on_play=TEST+'summon',metadata=META))
    r.register_behavior(TEST+'kill_end',lambda c:(Destroy(c.state.players[1].board[0],c.source_id),));r.register_card(CardDefinition(TEST+'end','Natural death fixture',CardType.MINION,health=2,triggers=(TriggerSpec('turn_ended',TEST+'kill_end'),),metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P28 deliberate acquisition failure')))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id==(SHADOW if mode=='fail'else HOLY)
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual acquisition reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP28Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=2828,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def created(self,g,source=None):return[e for e in g.events if e.kind=='card_created'and(source is None or e.source_id==source)]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','deathrattle_history','candidate_root_ids'):self.assertNotIn('"'+key+'"',public)
        return other
    def candidates(self,r,key):return{m.card_id for m in resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[key],player_id=1)}

    def test_five_complete_raw_rows_eight_faces_individual_zero_recipe_and_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertEqual(d['reviewed_zero_cost'],{WITCH:0});self.assertEqual(d['reviewed_zero_attack'],{WITCH:0})
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity='GIL_531'if cid==WITCH else cid));self.assertEqual((c.cost,c.attack,c.health),(0 if cid==WITCH else raw['cost'],0 if cid==WITCH else raw['attack'],raw['health']));self.assertEqual(c.keywords,(Keyword.TAUNT,)if cid in(WITCH,DRAGON)else())
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],c.cost,c.attack,c.health))
            if cid==WITCH:self.assertIsNone(raw['cost']);self.assertIsNone(raw['attack']);self.assertNotIn('COST',raw['tags']);self.assertNotIn('ATK',raw['tags'])
        self.assertEqual(r.card(WITCH).metadata.tribes,('beast',));self.assertEqual(r.card(DRAGON).metadata.tribes,('dragon',));self.assertEqual(r.card(CHAMPION).metadata.tribes,());self.assertEqual(r.card(CHAMPION).metadata.runes.frost,1);self.assertEqual(r.card(CHAMPION).metadata.runes.total,1)

    def test_four_new_defs_final_catalog_order_old_defs_and_pools_preserved(self):
        with patch('hs_sim.cards.simple_followup_p28_cards.register_simple_followup_p28_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(set(before.pool_cards),set(after.pool_cards));self.assertEqual('GIL_531'in before.cards,'GIL_531'in after.cards)
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity='GIL_531'))if cid==WITCH else row,after.pool_card(cid))
        self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_exact_class_tribe_all_dual_rarity_and_separate_school_queries(self):
        r=registry();self.assertEqual(self.candidates(r,WITCH),{SHAMAN});self.assertEqual(self.candidates(r,DRAGON),{DRAGON,BRIGHT,SMALL,ALL,DUAL});self.assertEqual(self.candidates(r,CHAMPION),{BRIGHT,DUAL});self.assertEqual(self.candidates(r,MENDER+'.holy'),{HOLY});self.assertEqual(self.candidates(r,MENDER+'.shadow'),{SHADOW});self.assertEqual(QUERIES[WITCH].classes,(CardClass.SHAMAN,));self.assertEqual(QUERIES[WITCH].class_mode,'specified')

    def test_witch_zero_cost_paid_battlecry_fixed_shaman_under_mage_hero(self):
        g=self.game((WITCH,),members=(SHAMAN,MAGE));source=self.play(g,WITCH);self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE);self.assertEqual(g.state.players[1].mana,50);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,SHAMAN);self.assertNotEqual(event.target_id,source);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_natural_summon_witch_excludes_battlecry_without_context_or_pool(self):
        g=self.game((TEST+'summon',),context=None,pool=False);self.play(g,TEST+'summon');self.assertEqual(self.first(g,WITCH,'board').card_id,WITCH);self.assertFalse(g.state.battlecry_history);self.assertFalse(self.created(g))

    def test_each_native_deathrattle_identity_source_and_expected_type(self):
        for cid,members,expected in((DRAGON,(SMALL,),[SMALL]),(CHAMPION,(BRIGHT,),[BRIGHT]),(MENDER,(HOLY,SHADOW),[HOLY,SHADOW])):
            with self.subTest(cid=cid):
                g=self.game((TEST+'kill',),board=(cid,),members=members);source=self.first(g,cid,'board').id;self.play(g,TEST+'kill',source);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],expected);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);record,=g.state.deathrattle_history;self.assertEqual(record.capture.origin,'death');self.assertEqual(record.capture.ability.deathrattle_card_id,cid);self.assertTrue(record.completed)

    def test_dragon_permanent_minus_two_not_set_to_two_and_zero_floor(self):
        for spell,expected in(('CORE_EX1_043',2),(SMALL,0)):
            with self.subTest(card=spell):
                g=self.game((TEST+'kill',),board=(DRAGON,),members=(spell,));source=self.first(g,DRAGON,'board').id;self.play(g,TEST+'kill',source);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertEqual(g.quote_cost(new.id).amount,expected);self.assertEqual(new.base_cost,g.registry.card(spell).cost);self.assertTrue(any(e.cost==-2 and e.set_cost is None and e.expires_turn is None for e in new.enchantments));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,expected)

    def test_champion_paid_one_and_permanent_minus_one_new_instance_only(self):
        g=self.game((CHAMPION,BRIGHT,TEST+'kill'),members=(BRIGHT,));source=self.play(g,CHAMPION);self.assertEqual(g.state.players[1].mana,49);old=self.first(g,BRIGHT).id;self.play(g,TEST+'kill',source);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertNotEqual(new.id,old);self.assertEqual(g.quote_cost(old).amount,2);self.assertEqual(g.quote_cost(new.id).amount,1);self.assertEqual(new.base_cost,2);self.assertTrue(any(e.cost==-1 and e.set_cost is None and e.expires_turn is None for e in new.enchantments));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new.id).amount,1);self.portable(g)

    def test_mender_holy_then_shadow_independent_rng_requests_and_no_discount(self):
        g=self.game((TEST+'kill',),board=(MENDER,));source=self.first(g,MENDER,'board').id;rng=random.Random();rng.setstate(g._rng.getstate());expected=[]
        for key in(MENDER+'.holy',MENDER+'.shadow'):expected.extend(sample_candidates(rng,resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[key],player_id=1),1,replacement=True))
        self.play(g,TEST+'kill',source);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],expected);self.assertEqual(expected,[HOLY,SHADOW]);self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertTrue(all(not g.state.entities[e.target_id].enchantments for e in events))

    def test_silence_removes_all_three_deathrattles_without_context(self):
        for cid in(DRAGON,CHAMPION,MENDER):
            with self.subTest(cid=cid):
                g=self.game((TEST+'silence',TEST+'kill'),board=(cid,),context=None,pool=False);source=self.first(g,cid,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source);self.assertFalse(self.created(g));self.assertFalse(g.state.deathrattle_history)

    def test_missing_context_or_pool_rolls_back_battlecry_and_natural_death(self):
        for bc in(True,False):
            for context,pool in((None,True),(CONTEXT,False)):
                with self.subTest(bc=bc,context=context,pool=pool):
                    g=self.game((WITCH,)if bc else(TEST+'kill',),board=()if bc else(MENDER,),context=context,pool=pool);saved=g.snapshot()
                    with self.assertRaises((ResolutionError,ValueError)):
                        if bc:self.play(g,WITCH)
                        else:self.play(g,TEST+'kill',self.first(g,MENDER,'board').id)
                    self.assertEqual(g.snapshot(),saved)

    def test_real_unimplemented_eligible_catalog_rows_fail_before_rng(self):
        for cid,unknown in((WITCH,'CATA_567'),(DRAGON,'CATA_484'),(CHAMPION,'BE_036'),(MENDER,'CORE_KAR_077')):
            with self.subTest(cid=cid):
                bc=cid==WITCH;g=self.game((WITCH,)if bc else(TEST+'kill',),board=()if bc else(cid,),members=(*MEMBERS,unknown));self.assertIn(unknown,g.registry.pool_cards);self.assertNotIn(unknown,g.registry.cards);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligible validation'))as calls:
                    with self.assertRaises(ResolutionError):
                        if bc:self.play(g,WITCH)
                        else:self.play(g,TEST+'kill',self.first(g,cid,'board').id)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_unknown_second_shadow_request_rolls_back_first_holy_rng_and_death(self):
        g=self.game((TEST+'kill',),board=(MENDER,),members=(HOLY,'CAP_001'));source=self.first(g,MENDER,'board').id;saved=g.snapshot()
        original=random.Random.randrange
        with patch.object(random.Random,'randrange',autospec=True,side_effect=original)as calls:
            with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',source)
            self.assertEqual(calls.call_count,1)
        self.assertEqual(g.snapshot(),saved)

    def test_mender_full_hand_creates_then_burns_one_of_each_school(self):
        g=self.game((YETI,)*10,board=(MENDER,TEST+'end'),members=(HOLY,SHADOW));source=self.first(g,MENDER,'board').id;g.apply(EndTurn(1));events=self.created(g,source);burns=[e for e in g.events if e.kind=='card_burned'];self.assertEqual([g.state.entities[e.target_id].card_id for e in events],[HOLY,SHADOW]);self.assertEqual({e.target_id for e in events},{e.target_id for e in burns});self.assertEqual(len(g.state.players[1].hand),10)

    def test_dragon_full_hand_burn_material_keeps_permanent_creation_discount(self):
        g=self.game((YETI,)*10,board=(DRAGON,TEST+'end'),members=(SMALL,));source=self.first(g,DRAGON,'board').id;g.apply(EndTurn(1));event,=self.created(g,source);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(event.target_id,burn.target_id);new=g.state.entities[event.target_id];self.assertEqual(new.card_id,SMALL);self.assertTrue(any(e.cost==-2 and e.set_cost is None and e.expires_turn is None for e in new.enchantments))

    def test_mender_first_creation_wait_restore_replay_bad_choice_and_later_shadow(self):
        g=self.game((TEST+'kill',),board=(MENDER,),members=(HOLY,SHADOW),mode='wait');source=self.first(g,MENDER,'board').id;self.play(g,TEST+'kill',source);self.assertIsNotNone(g.state.pending_choice);self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],[HOLY]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([g.state.entities[e.target_id].card_id for e in self.created(g,source)],[HOLY,SHADOW]);self.assertTrue(g.state.deathrattle_history[0].completed);self.portable(g)

    def test_second_arrival_failure_rolls_back_first_generation_whole_death_and_rng(self):
        g=self.game((TEST+'kill',),board=(MENDER,),members=(HOLY,SHADOW),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,TEST+'kill',self.first(g,MENDER,'board').id)
        self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
