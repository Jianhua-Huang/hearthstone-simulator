"""Real Ward of Earth uses existing pre-entry keyword material and pool proof."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.pool_entry_keyword_cards import WARD,POOL_ID,QUERY,load_batch
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,SnapshotError,Zone
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Rarity,SpellSchool,SummonQuantitySpec,TargetMode,TargetSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,SummonFromPool,resolve_candidates
from hs_sim.engine.pool_summons import validate_weighted_request
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import canonical_digest

P='k116.test.';PLAIN='CORE_ICC_032';CURATOR='CORE_KAR_061';YETI='CORE_CS2_182';UNKNOWN=P+'unknown_foreign'
CTX=GenerationContext('k116-explicit-experiment','experimental');MEMBERS=(PLAIN,CURATOR,YETI,WARD)
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=(),factions=(),subtypes=())

def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,5,replace(META,collectible=True,classes=(CardClass.MAGE,),rarity=Rarity.COMMON)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k116-explicit-weighted-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c,3 if c==PLAIN else 1)for c in members),complete=True))
    r.register_card(CardDefinition(P+'twice','Existing quantity source',CardType.MINION,health=5,metadata=META,summon_quantities=(SummonQuantitySpec(),)))
    for name,body in(('plain',lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(PLAIN),),SummonCause.capture(c)),)),('silence',lambda c:(Silence(c.target_id),)),('fail',lambda c:(_ for _ in()).throw(ResolutionError('K116 deliberate entry failure')))):
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.SPELL,on_play=P+name,metadata=META,
            targeting=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))if name=='silence'else None))
    if mode:
        def eligible(c):return any(root.request.cause.source.card_id==WARD and any(d.outcome=='delivered'and d.entity.entity_id==c.event.target_id for d in root.deliveries)for root in c.state.card_summon_history)
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible)
        r.register_card(CardDefinition(P+'watch','Original entry observer',CardType.MINION,health=6,metadata=META,
            limited_triggers=(LimitedTriggerSpec('minion_summoned',P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r

class PoolEntryKeywordTests(unittest.TestCase):
    def game(self,hand=(WARD,),board=(),members=MEMBERS,mode=None,pool=True,context=CTX):
        self.config=(members,mode,pool)
        if mode:board=(*board,P+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_06',hand=hand,board=board,deck=(YETI,)*8,mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=116,generation_context=context),registry(*self.config))
    def play(self,g,cid=WARD,target=None):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,eid,target));return eid
    def root(self,g):return next(x for x in g.state.card_summon_history if x.request.cause.source.card_id==WARD)
    def body(self,g):return g.state.entities[self.root(g).deliveries[0].entity.entity_id]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('entry_keywords','pool_basis','card_summon_history','resolution_frame','rng_state','PoolSummonBasis'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_complete_two_rows_primary_faces_native_spell_and_evidence_only_enchantment(self):
        data=load_batch();r=registry();raw=data['cards'][0]['record'];c=r.card(WARD);self.assertEqual((c.cost,c.kind,c.spell_school),(5,CardType.SPELL,SpellSchool.NATURE));self.assertEqual(c.metadata,metadata_from_record(raw));self.assertFalse(c.keywords)
        self.assertEqual(len(data['cards']+data['evidence_only']),2);self.assertEqual(len(data['official_observations']['observations']),2)
        for row in data['cards']+data['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for o in data['official_observations']['observations']:
            en=o['locale']=='en_US';self.assertEqual(o['face']['name'],raw['name_en'if en else'name']);self.assertEqual(norm(o['face']['text']),norm(raw['text_en'if en else'text']))
        self.assertFalse(data['formal_pool_complete']);self.assertFalse(data['cn_calibrated']);self.assertNotIn('EDR_060e',r.cards)

    def test_native_spell_gains_five_armor_then_random_non_taunt_gets_actual_grant(self):
        g=self.game(members=(PLAIN,));source=self.play(g);body=self.body(g);root=self.root(g)
        self.assertEqual((body.card_id,g.state.entities[g.state.players[1].hero_id].armor,g.state.players[1].mana),(PLAIN,5,15));self.assertNotIn(Keyword.TAUNT,g.registry.card(PLAIN).keywords);self.assertIn(Keyword.TAUNT,body.keywords)
        self.assertTrue(any(a.kind=='keyword'and a.keyword==Keyword.TAUNT and a.source_id==source for a in body.abilities));self.assertEqual(root.request.pool_basis.entry_keywords,(Keyword.TAUNT,));self.assertEqual(root.request.materials,(SummonEntryMaterial(PLAIN,keywords=(Keyword.TAUNT,)),));self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_exact_printed_cost_pool_keeps_non_taunts_and_weighted_ticket(self):
        g=self.game();rows=resolve_candidates(g.registry,CTX,POOL_ID,QUERY,source_card_id=WARD,exclude_source_by_rule=True,player_id=1);self.assertEqual([(m.card_id,m.weight)for m in rows],[(PLAIN,3),(CURATOR,1)]);self.assertEqual(QUERY.class_mode,'any');self.assertFalse(QUERY.keywords_all)
        rng=random.Random();rng.setstate(g._rng.getstate());expected=PLAIN if rng.randrange(4)<3 else CURATOR;self.play(g);self.assertEqual(self.body(g).card_id,expected);self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_printed_battlecry_minion_summon_does_not_execute_battlecry(self):
        g=self.game(members=(CURATOR,));deck=list(g.state.players[1].deck);self.play(g);self.assertEqual(self.body(g).card_id,CURATOR);self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.players[1].deck,deck);self.portable(g)

    def test_quantity_extras_inherit_same_accepted_entry_grant(self):
        g=self.game(board=(P+'twice',),members=(PLAIN,));source=self.play(g);root=self.root(g);self.assertEqual(root.plan.total,2);bodies=[g.state.entities[d.entity.entity_id]for d in root.deliveries];self.assertEqual(len({e.id for e in bodies}),2)
        self.assertTrue(all(Keyword.TAUNT in e.keywords and any(a.source_id==source and a.keyword==Keyword.TAUNT for a in e.abilities)for e in bodies));self.assertEqual(g.state.players[1].mana,15);self.portable(g)

    def test_actual_summon_observer_sees_grant_wait_restore_and_failed_resume(self):
        g=self.game(members=(PLAIN,),mode='wait');self.play(g);self.assertIsNotNone(g.state.pending_choice);self.assertIn(Keyword.TAUNT,self.body(g).keywords);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):game.apply(SelectChoice(1,game.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),other.snapshot());self.portable(g)

    def test_existing_and_later_minions_are_unaffected_and_original_grant_is_permanent(self):
        g=self.game(hand=(WARD,P+'plain'),board=(PLAIN,),members=(PLAIN,));old=g.state.players[1].board[0];self.play(g);body=self.body(g);self.play(g,P+'plain');later=g.state.players[1].board[-1]
        self.assertNotIn(Keyword.TAUNT,g.state.entities[old].keywords);self.assertNotIn(Keyword.TAUNT,g.state.entities[later].keywords);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertIn(Keyword.TAUNT,g.state.entities[body.id].keywords);self.portable(g)

    def test_silence_removes_granted_taunt_using_existing_lifecycle(self):
        g=self.game(hand=(WARD,P+'silence'),members=(PLAIN,));self.play(g);body=self.body(g);self.play(g,P+'silence',body.id);self.assertNotIn(Keyword.TAUNT,g.state.entities[body.id].keywords);self.assertTrue(g.state.entities[body.id].silenced);self.portable(g)

    def test_full_board_and_empty_pool_keep_armor_without_summon_rng(self):
        for board,members in(((YETI,)*7,(PLAIN,)),((),(YETI,))):
            with self.subTest(full=bool(board)):
                g=self.game(board=board,members=members);rng=g._rng.getstate();self.play(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,5);self.assertEqual(g._rng.getstate(),rng);self.assertFalse(self.root(g).deliveries);self.portable(g)

    def test_unknown_foreign_five_cost_or_missing_context_rolls_back_armor_before_rng(self):
        for board,mode in(((),'unknown'),((YETI,)*7,'unknown'),((),'context'),((),'pool')):
            with self.subTest(mode=mode,full=bool(board)):
                g=self.game(board=board,members=(*MEMBERS,UNKNOWN)if mode=='unknown'else MEMBERS,context=None if mode=='context'else CTX,pool=mode!='pool');saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown before pool draw'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_late_entry_failure_rolls_back_armor_grant_entities_payment_and_rng(self):
        g=self.game(members=(PLAIN,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_basis_and_material_keyword_must_match_complete_original_pool_proof(self):
        g=self.game(members=(PLAIN,),mode='wait');self.play(g);request=self.root(g).request;validate_weighted_request(g.state,g.registry,request)
        for changed in(replace(request,materials=(SummonEntryMaterial(PLAIN),)),replace(request,pool_basis=replace(request.pool_basis,entry_keywords=()))):
            with self.assertRaises(ValueError):validate_weighted_request(g.state,g.registry,changed)
        saved=json.loads(json.dumps(g.snapshot()));saved['state']['card_summon_history'][0]['request']['pool_basis']['entry_keywords']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))

    def test_finite_request_and_real_codec_reject_unsupported_or_unattributed_grants(self):
        g=self.game(members=(PLAIN,));source=self.play(g);spec=SummonFromPool(1,POOL_ID,QUERY,source_id=source,cause=self.root(g).request.cause,entry_keywords=(Keyword.TAUNT,));codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(spec)),spec)
        for changes in({'entry_keywords':[Keyword.TAUNT]},{'entry_keywords':('taunt',)},{'entry_keywords':(Keyword.DIVINE_SHIELD,)},{'entry_keywords':(Keyword.TAUNT,Keyword.TAUNT)},{'cause':None},{'source_id':None}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):replace(spec,**changes)
        self.assertEqual(SummonFromPool(1,POOL_ID).entry_keywords,())

    def test_default_311_identity_and_old_schema327_are_explicit(self):
        from hs_sim.engine.representative import build_registry as defaults
        r=defaults();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT);self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,328);g=self.game();saved=g.snapshot();saved['schema_version']=327
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))

if __name__=='__main__':unittest.main()
