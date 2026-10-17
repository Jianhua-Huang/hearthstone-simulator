"""Explicit experimental format inventory; never claims formal standard generation."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p25_cards import RAIDER,MACAW,GREENFIN,WHELP,ROOTS,DEPENDENCIES,TRIBES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p25_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p25.test.';YETI='CORE_CS2_182';ALL='DINO_435';DRAGON4='CORE_EX1_043';MULTI='CORE_ICC_220';UNKNOWN=TEST+'unimplemented';UNKNOWN_META=TEST+'unknown_metadata';BANNED=TEST+'titan'
SMALL_DRAGON='CORE_EX1_189'
CONTEXT=GenerationContext('p25-explicit-experimental-inventory','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(members=(*ROOTS,ALL,SMALL_DRAGON),mode=None,pool=True):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p25_cards(r)
    for cid in(UNKNOWN,UNKNOWN_META,BANNED):
        if cid in members:r.register_pool_card(PoolCard(cid,CardType.MINION,1,CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=None if cid==UNKNOWN_META else('pirate',),factions=(),subtypes=()),keywords=(Keyword.TITAN,)if cid==BANNED else()))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p25-explicit-experiment-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for cid in ROOTS:
        key=TEST+'summon_'+cid;r.register_behavior(key,lambda c,cid=cid:(Summon(c.player_id,cid),));r.register_card(CardDefinition(key,'Effect summon',CardType.SPELL,on_play=key,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P25 deliberate generation failure')))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id in members
        def watch(c):
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            extra=()
            if mode=='retire':
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id in ROOTS);extra=(Destroy(target,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        event='minion_summoned'if mode=='fill'else'card_added_to_hand'if mode in('arrival','fail')else'card_created'
        r.register_card(CardDefinition(TEST+'watch','Actual acquisition boundary',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP25Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=(*ROOTS,ALL,SMALL_DRAGON),mode=None,pool=True,context=CONTEXT):
        self.members=members;self.mode=mode;self.pool=pool;self.context=context
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2525,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid,p=1,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,None,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def hand(self,g):return[g.state.entities[i]for i in g.state.players[1].hand]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','generation_identity','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_six_complete_rows_eight_official_faces_and_full_metadata_core_identities(self):
        d=load_batch();r=registry();self.assertEqual(len(d['cards']+d['evidence_only']),6);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];card=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual((card.cost,card.attack,card.health),(1,1,1 if cid==GREENFIN else 2));self.assertIsNotNone(card.battlecry);self.assertIsNone(card.targeting);self.assertEqual(card.metadata.tribes,(TRIBES[cid],))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health'],f['classId']),(raw['dbf_id'],1,1,raw['health'],raw['tags']['CLASS']))
        self.assertEqual(r.card(RAIDER).metadata.classes,(CardClass.WARRIOR,));self.assertEqual(r.card(MACAW).metadata.classes,(CardClass.HUNTER,));self.assertEqual(r.card(WHELP).metadata.subtypes,('whelp',));self.assertEqual(r.card(GREENFIN).metadata.classes,(CardClass.NEUTRAL,))
        for cid in ROOTS:self.assertEqual((QUERIES[cid].class_mode,QUERIES[cid].collectible,QUERIES[cid].max_cost),('any',True,3 if cid==WHELP else None))

    def test_only_four_defs_added_no_alias_or_production_pool_registered(self):
        with patch('hs_sim.cards.simple_followup_p25_cards.register_simple_followup_p25_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p25_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))
        for cid in('DRG_024','UNG_912'):self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_each_paid_battlecry_uses_any_class_pool_and_creates_new_physical_card(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                g=self.game((cid,));source=self.play(g,cid);new,=self.hand(g);self.assertEqual(new.card_id,SMALL_DRAGON if cid==WHELP else ALL);self.assertNotEqual(source,new.id);self.assertEqual(g.state.players[1].mana,49);self.assertEqual(len(g.state.battlecry_history),1);self.assertFalse(g.state.cast_history)
                created=[e for e in g.events if e.kind in('card_created','card_added_to_hand')];self.assertTrue(created);self.assertTrue(all(e.source_id==source and e.target_id==new.id for e in created));self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE)

    def test_natural_effect_summons_do_not_execute_battlecry_or_require_pool(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                script=TEST+'summon_'+cid;g=self.game((script,),pool=False,context=None);self.play(g,script);self.assertFalse(self.hand(g));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[cid]);self.assertFalse(g.state.battlecry_history)

    def test_queries_use_complete_all_multitribe_and_printed_dragon_cost_boundary(self):
        members=(*ROOTS,ALL,DRAGON4,MULTI);r=registry(members);expected={RAIDER:{RAIDER,ALL},MACAW:{MACAW,ALL},GREENFIN:{GREENFIN,ALL,MULTI},WHELP:{WHELP}}
        for cid in ROOTS:
            with self.subTest(cid=cid):self.assertEqual({m.card_id for m in resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[cid],player_id=1)},expected[cid])

    def test_actual_canonical_rng_matches_shared_query_including_all_type(self):
        members=(*ROOTS,ALL);g=self.game((RAIDER,),members=members);candidates=resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[RAIDER],player_id=1,source_card_id=RAIDER,exclude_source_by_rule=True);rng=random.Random();rng.setstate(g._rng.getstate());expected=candidates[rng.randrange(len(candidates))].card_id;self.play(g,RAIDER);self.assertEqual(self.hand(g)[0].card_id,expected);self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_missing_wrong_context_or_matching_pool_rejects_entire_action(self):
        for context,pool in((None,True),(CONTEXT,False),(GenerationContext('different-target','experimental'),True),(GenerationContext(CONTEXT.target_id,'standard'),True)):
            with self.subTest(context=context,pool=pool):
                g=self.game((RAIDER,),context=context,pool=pool);saved=g.snapshot()
                with self.assertRaises((ResolutionError,ValueError)):self.play(g,RAIDER)
                self.assertEqual(g.snapshot(),saved)

    def test_empty_eligible_pool_does_not_sample_or_invent_fallback(self):
        g=self.game((RAIDER,),members=(MACAW,));rng=g._rng.getstate();self.play(g,RAIDER);self.assertFalse(self.hand(g));self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,49)

    def test_every_eligible_unimplemented_or_unknown_metadata_fails_before_rng_even_full(self):
        for unknown,full in((UNKNOWN,False),(UNKNOWN,True),(UNKNOWN_META,False)):
            with self.subTest(unknown=unknown,full=full):
                g=self.game((RAIDER,)+(YETI,)*9 if full else(RAIDER,),members=(RAIDER,unknown),mode='fill'if full else None);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligible validation'))as rng_calls:
                    with self.assertRaises((ResolutionError,ValueError)):self.play(g,RAIDER)
                    rng_calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_shared_special_ban_excludes_titan_before_missing_executable_check(self):
        g=self.game((RAIDER,),members=(RAIDER,ALL,BANNED));self.play(g,RAIDER);self.assertEqual([e.card_id for e in self.hand(g)],[ALL]);self.assertNotIn(BANNED,g.registry.cards)

    def test_full_hand_overflow_burns_generated_identity_with_actual_source(self):
        g=self.game((RAIDER,)+(YETI,)*9,mode='fill');source=self.play(g,RAIDER);self.assertEqual(len(self.hand(g)),10);self.assertTrue(all(e.card_id==YETI for e in self.hand(g)));burn,=[e for e in g.events if e.kind=='card_burned'];self.assertNotEqual(burn.target_id,source);self.assertEqual(g.state.entities[burn.target_id].card_id,ALL);self.assertTrue(any(e.kind=='card_created'and e.target_id==burn.target_id and e.source_id==source for e in g.events));self.portable(g)

    def test_real_battlecry_repeat_creates_two_independent_hand_entities_one_payment(self):
        g=self.game((RAIDER,),board=('TIME_064',));source=self.play(g,RAIDER);cards=self.hand(g);self.assertEqual([e.card_id for e in cards],[ALL,ALL]);self.assertEqual(len({source,*(e.id for e in cards)}),3);self.assertEqual(g.state.players[1].mana,49)

    def test_actual_creation_and_arrival_wait_restore_replay_and_bad_resume_rollback(self):
        for mode in('created','arrival'):
            with self.subTest(mode=mode):
                g=self.game((RAIDER,),mode=mode);self.play(g,RAIDER);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.choose(g,'bad')
                self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual([e.card_id for e in self.hand(g)],[ALL]);self.assertEqual(g.state.players[1].mana,49);self.portable(g)

    def test_late_generation_failure_rolls_back_paid_play_creation_and_rng(self):
        g=self.game((RAIDER,),members=(*ROOTS,ALL),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,RAIDER)
        self.assertEqual(g.snapshot(),saved)

    def test_accepted_generation_finishes_after_original_source_retires(self):
        g=self.game((RAIDER,),mode='retire');source=self.play(g,RAIDER);self.assertIsNotNone(g.state.pending_choice);self.choose(g);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);new,=self.hand(g);self.assertEqual(new.card_id,ALL);self.assertNotEqual(new.id,source);self.assertTrue(any(e.kind=='card_added_to_hand'and e.target_id==new.id and e.source_id==source for e in g.events));self.portable(g)

if __name__=='__main__':unittest.main()
