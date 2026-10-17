"""Printed pools, paid mana snapshots and post-discovery physical hand discounts."""
from dataclasses import asdict
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p36_cards import RELIC,SCAVENGER,REAVER,ROOTS,DEPENDENCIES,EXISTING_DEPENDENCIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p36_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,Zone
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,SpendMana,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest

TEST='p36.test.';YETI='CORE_CS2_182';ONE='JAIL_460';WISP='CORE_CS2_231';FIRE='CORE_CS2_029';BIG='CORE_EX1_279';FOREIGN='CORE_EX1_312';EIGHT_MINION='CORE_RLK_506';SEVEN='CORE_CS2_032';WEAPON='CORE_DAL_720';ZERO='CORE_EX1_145';FEL='CORE_BT_035';OTHER_FEL='CORE_SW_088';FEL_ONE='CATA_528'
MEMBERS=(*ROOTS,YETI,ONE,WISP,FIRE,BIG,FOREIGN,EIGHT_MINION,SEVEN,WEAPON,ZERO,FEL,OTHER_FEL,FEL_ONE)
CONTEXT=GenerationContext('p36-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p36_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p36-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for name,fn in(('later',lambda c:(AddToHand(c.player_id,FEL,c.source_id),)),('fail',lambda c:(_ for _ in()).throw(ResolutionError('P36 deliberate cost continuation failure')))):
        r.register_behavior(TEST+name,fn);r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META))
    for cid in(SCAVENGER,REAVER):
        key=TEST+'natural.'+cid;r.register_behavior(key,lambda c,card=cid:(Summon(c.player_id,card),));r.register_card(CardDefinition(key,'Natural summon',CardType.SPELL,on_play=key,metadata=META))
    if mode:
        def eligible(c):return (mode=='fail_cost'or c.event.player_id==1)and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            if mode=='fail_cost':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            tail=(SpendMana(1,source_id=c.source_id),)if mode=='mana_wait'else(Destroy(c.event.source_id,c.source_id),AddToHand(1,FEL,c.source_id))if mode=='depart'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual creation/cost reaction',CardType.MINION,health=9,metadata=META,limited_triggers=(LimitedTriggerSpec('cost_modified'if mode=='fail_cost'else'choice_selected'if mode=='fill'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP36Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08',mana=50,deck=(YETI,)*8):
        self.config=(members,mode,pool)
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=mana,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=3636,generation_context=context),registry(*self.config))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,cid=None,key=None):
        q=g.state.pending_choice;selected=key if key is not None else next(o.id for o in q.options if cid is None or o.card_id==cid);g.apply(SelectChoice(q.player_id,q.id,(selected,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def actual(self,g,cid,query=None):return resolve_candidates(g.registry,CONTEXT,POOL_ID,query or QUERIES[cid],current_class=g.state.players[1].hero_class,source_card_id=cid,exclude_source_by_rule=True,player_id=1)
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','pool_basis','behavior_id','candidate_root_ids'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_three_complete_rows_six_faces_exact_metadata_and_native_types(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']),3);self.assertEqual(len(d['official_observations']['observations']),6);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertTrue(d['required_generation_context'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,raw['cost']);self.assertFalse(c.keywords);self.assertIsNone(c.spell_school);self.assertEqual(c.kind,CardType.SPELL if cid==RELIC else CardType.MINION);self.assertEqual(c.on_play is not None,cid==RELIC);self.assertEqual(c.battlecry is not None,cid!=RELIC)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
        self.assertEqual(r.card(REAVER).metadata.classes,(CardClass.DEMON_HUNTER,));self.assertEqual((r.card(SCAVENGER).attack,r.card(SCAVENGER).health),(1,1));self.assertEqual((r.card(REAVER).attack,r.card(REAVER).health),(4,4));self.assertIsNone(r.card(REAVER).deathrattle)

    def test_three_new_defs_preserve_all_old_definitions_pool_metadata_and_families(self):
        with patch('hs_sim.cards.simple_followup_p36_cards.register_simple_followup_p36_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertFalse(EXISTING_DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.generation_families),dict(after.generation_families));self.assertEqual(dict(before.pools),dict(after.pools))

    def test_default311_fingerprint_and_production_formal_pools_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667');self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in batch_registry().pools.values()))

    def test_relic_printed_eight_plus_spell_pool_any_class_not_seven_or_minion(self):
        for hero in('HERO_08','HERO_01'):
            with self.subTest(hero=hero):
                g=self.game(members=(BIG,FOREIGN,SEVEN,EIGHT_MINION),hero=hero);self.assertEqual({m.card_id for m in self.actual(g,RELIC)},{BIG,FOREIGN});self.assertEqual(QUERIES[RELIC].class_mode,'any')

    def test_relic_paid_selection_sets_only_new_same_card_to_one_permanently(self):
        g=self.game((RELIC,FOREIGN),members=(FOREIGN,));old=self.first(g,FOREIGN).id;source=self.play(g,RELIC);self.assertEqual(g.state.players[1].mana,43);self.choose(g);event,=self.created(g,source);new=event.target_id;self.assertNotEqual(new,old);self.assertEqual(g.quote_cost(new).amount,1);self.assertEqual(g.quote_cost(old).amount,8);self.assertTrue(any(e.set_cost==1 and e.expires_turn is None for e in g.state.entities[new].enchantments));g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual(g.quote_cost(new).amount,1);self.assertEqual(g.quote_cost(old).amount,8);self.assertEqual(len(g.state.cast_history),1);self.assertFalse(g.state.battlecry_history);self.portable(g)

    def test_relic_full_hand_burns_selected_instance_without_changing_old_cards(self):
        g=self.game((RELIC,)+(YETI,)*9,members=(FOREIGN,),mode='fill');source=self.play(g,RELIC);self.choose(g);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(g.state.entities[burn.target_id].card_id,FOREIGN);self.assertEqual(g.state.entities[burn.target_id].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),10);self.assertTrue(all(g.quote_cost(i).amount==4 for i in g.state.players[1].hand));self.assertEqual(len(self.created(g,source)),1);self.portable(g)

    def test_relic_empty_pool_has_no_choice_or_rng_but_pays_once(self):
        g=self.game((RELIC,),members=(SEVEN,EIGHT_MINION));rng=g._rng.getstate();source=self.play(g,RELIC);self.assertFalse(self.created(g,source));self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng);self.assertEqual(g.state.players[1].mana,43)

    def test_relic_private_offer_wait_restore_clone_and_independent_replay(self):
        g=self.game((RELIC,),members=(BIG,FOREIGN));source=self.play(g,RELIC);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});other=self.portable(g)
        for game in(g,other):self.choose(game,FOREIGN)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.quote_cost(self.created(g,source)[0].target_id).amount,1);self.portable(g)

    def test_scavenger_native_battlecry_uses_current_available_after_payment_any_type(self):
        g=self.game((SCAVENGER,),members=(YETI,FIRE,WEAPON),mana=5);self.play(g,SCAVENGER);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{YETI,FIRE});self.assertEqual(g.state.players[1].mana,4);self.choose(g,FIRE);self.assertEqual(len(g.state.battlecry_history),1);self.assertFalse(g.state.cast_history)
        g=self.game((SCAVENGER,),members=(YETI,FIRE,WEAPON),mana=5,hero='HERO_03');self.play(g,SCAVENGER);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{YETI,WEAPON});self.choose(g,WEAPON);self.assertEqual(self.first(g,WEAPON).kind,CardType.WEAPON)

    def test_scavenger_zero_remaining_discovers_printed_zero_neutral_and_current_spell(self):
        g=self.game((SCAVENGER,),members=(WISP,ZERO,ONE),mana=1,hero='HERO_03');source=self.play(g,SCAVENGER);self.assertEqual(g.state.players[1].mana,0);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{WISP,ZERO});self.choose(g,ZERO);self.assertEqual(g.quote_cost(self.created(g,source)[0].target_id).amount,0);self.portable(g)

    def test_scavenger_original_printed_pool_not_existing_relic_one_cost_instance(self):
        g=self.game((RELIC,SCAVENGER),members=(FOREIGN,ONE),mana=9);source=self.play(g,RELIC);self.choose(g);new=self.created(g,source)[0].target_id;self.assertEqual(g.quote_cost(new).amount,1);self.play(g,SCAVENGER);self.assertEqual(g.state.players[1].mana,1);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{ONE});self.choose(g);self.assertEqual(g.quote_cost(new).amount,1)

    def test_scavenger_frozen_offer_survives_wait_and_later_mana_spend_before_delivery(self):
        g=self.game((SCAVENGER,),members=(YETI,WISP),mana=5,mode='mana_wait');source=self.play(g,SCAVENGER);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{YETI});self.choose(g,YETI);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        for game in(g,other):self.choose(game,key='ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.players[1].mana,0);self.assertEqual(g.state.entities[self.created(g,source)[0].target_id].card_id,YETI);self.assertEqual(g.quote_cost(self.created(g,source)[0].target_id).amount,4);self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_scavenger_native_source_only_one_cost_is_excluded_before_rng(self):
        g=self.game((SCAVENGER,),members=(SCAVENGER,),mana=2);rng=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Source sampled'))as calls:self.play(g,SCAVENGER);calls.assert_not_called()
        self.assertEqual(g._rng.getstate(),rng);self.assertIsNone(g.state.pending_choice)

    def test_reaver_current_hero_fel_pool_not_printed_demon_hunter_class_or_other_schools(self):
        for hero,expected in(('HERO_10',{FEL}),('HERO_07',{OTHER_FEL}),('HERO_08',set())):
            with self.subTest(hero=hero):
                g=self.game(members=(FEL,OTHER_FEL,FIRE),hero=hero);self.assertEqual({m.card_id for m in self.actual(g,REAVER)},expected)

    def test_reaver_discovery_then_reduces_existing_and_new_fel_of_any_class_only(self):
        g=self.game((REAVER,FEL,OTHER_FEL,FIRE,TEST+'later'),members=(FEL,OTHER_FEL,FIRE),hero='HERO_10',deck=(FEL,)*4);old=self.first(g,FEL).id;foreign=self.first(g,OTHER_FEL).id;fire=self.first(g,FIRE).id;deck=list(g.state.players[1].deck);source=self.play(g,REAVER);self.assertEqual(g.quote_cost(old).amount,2);self.assertEqual(g.quote_cost(foreign).amount,4);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{FEL});self.choose(g,FEL);new=self.created(g,source)[0].target_id;self.assertEqual([g.quote_cost(i).amount for i in(old,foreign,fire,new)],[1,3,4,1]);self.assertTrue(all(quote_cost(g.state,g.registry,g.state.entities[i]).amount==2 for i in deck));self.assertFalse(g.state.cast_history);self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(g.state.players[1].mana,46)
        self.play(g,TEST+'later');later=g.state.players[1].hand[-1];self.assertEqual(g.state.entities[later].card_id,FEL);self.assertEqual(g.quote_cost(later).amount,2);g.apply(EndTurn(1));g.apply(EndTurn(2));self.assertEqual([g.quote_cost(i).amount for i in(old,foreign,new,later)],[1,3,1,2]);self.portable(g)

    def test_reaver_delta_is_flat_one_with_zero_floor_and_no_expiry(self):
        g=self.game((REAVER,FEL_ONE),members=(FEL_ONE,),hero='HERO_10');old=self.first(g,FEL_ONE).id;source=self.play(g,REAVER);self.choose(g);new=self.created(g,source)[0].target_id
        for eid in(old,new):self.assertEqual(g.quote_cost(eid).amount,0);self.assertEqual(len([e for e in g.state.entities[eid].enchantments if e.cost==-1 and e.expires_turn is None]),1)

    def test_reaver_empty_discovery_still_reduces_existing_fel_without_rng(self):
        g=self.game((REAVER,FEL,OTHER_FEL),members=(FIRE,),hero='HERO_10');rng=g._rng.getstate();source=self.play(g,REAVER);self.assertIsNone(g.state.pending_choice);self.assertFalse(self.created(g,source));self.assertEqual(g.quote_cost(self.first(g,FEL).id).amount,1);self.assertEqual(g.quote_cost(self.first(g,OTHER_FEL).id).amount,3);self.assertEqual(g._rng.getstate(),rng)

    def test_reaver_actual_creation_wait_bad_resume_source_death_and_fresh_hand_read(self):
        g=self.game((REAVER,FEL),members=(FEL,),hero='HERO_10',mode='depart');old=self.first(g,FEL).id;source=self.play(g,REAVER);self.choose(g,FEL);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.quote_cost(old).amount,2);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved)
        for game in(g,other):self.choose(game,key='ok')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),3);self.assertTrue(all(g.quote_cost(i).amount==1 for i in g.state.players[1].hand));self.portable(g)

    def test_reaver_late_first_cost_failure_rolls_back_choice_delivery_and_all_discounts(self):
        g=self.game((REAVER,FEL,OTHER_FEL),members=(FEL,),hero='HERO_10',mode='fail_cost');self.play(g,REAVER);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,FEL)
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.quote_cost(self.first(g,FEL).id).amount,2);self.assertEqual(g.quote_cost(self.first(g,OTHER_FEL).id).amount,4);self.assertEqual(g.state.players[1].mana,46)

    def test_natural_summon_minions_has_no_battlecry_discovery_or_discount(self):
        for cid in(SCAVENGER,REAVER):
            with self.subTest(cid=cid):
                key=TEST+'natural.'+cid;g=self.game((key,FEL),pool=False,context=None);self.play(g,key);self.assertFalse(g.state.battlecry_history);self.assertIsNone(g.state.pending_choice);self.assertEqual(g.quote_cost(self.first(g,FEL).id).amount,2);self.portable(g)

    def test_unknown_eligible_full_pool_fails_before_rng_and_native_payment_rolls_back(self):
        for cid,unknown,hero,mana in((RELIC,'DINO_424','HERO_08',50),(SCAVENGER,'CATA_483','HERO_08',5),(REAVER,'FIR_902','HERO_10',50)):
            with self.subTest(cid=cid):
                g=self.game((cid,FEL),members=(*MEMBERS,unknown),hero=hero,mana=mana);saved=g.snapshot();self.assertNotIn(unknown,g.registry.cards)
                with patch.object(random.Random,'randrange',side_effect=AssertionError('Unknown sampled'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_missing_generation_context_or_pool_rolls_back_all_three_entries(self):
        for cid in ROOTS:
            for missing in('context','pool'):
                with self.subTest(cid=cid,missing=missing):
                    g=self.game((cid,),context=None if missing=='context'else CONTEXT,pool=missing!='pool',hero='HERO_10',mana=5 if cid==SCAVENGER else 50);saved=g.snapshot()
                    with self.assertRaises(ResolutionError):self.play(g,cid)
                    self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
