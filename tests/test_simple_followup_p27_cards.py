"""Explicit experimental inventories; no formal format pool or runtime fallback."""
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p27_cards import BOOK,PIRATE,NURSE,CAKE,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,POOL_ID,load_batch,register_simple_followup_p27_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChoiceOption,Destroy,InvokeBehavior,ModifyCost,ReplaceHero,RequestChoice,Silence,Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Rarity,TriggerSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p27.test.';YETI='CORE_CS2_182';MAGE1='EX1_277';MAGE4='CS2_029';ROGUE1='CORE_CS2_075';WEAPON='CS2_106';DUAL='END_025';DUAL_WEAPON='END_001';TOKEN='DREAM_01';UNKNOWN=TEST+'unknown'
MEMBERS=(*ROOTS,MAGE1,MAGE4,ROGUE1,WEAPON,YETI,DUAL,DUAL_WEAPON,TOKEN);CONTEXT=GenerationContext('p27-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(members=MEMBERS,mode=None,pool=True,unknown_kind=CardType.SPELL):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p27_cards(r)
    for cid in members:
        if cid in r.pool_cards:continue
        if cid==UNKNOWN:r.register_pool_card(PoolCard(cid,unknown_kind,1,CardMetadata(True,(CardClass.MAGE,),Rarity.COMMON,tribes=(),factions=(),subtypes=())))
        else:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p27-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    def price(c):
        return tuple(ModifyCost(i,CostSpec(set_to=7 if c.state.entities[i].card_id==ROGUE1 else 1),c.source_id)for i in c.state.players[1].hand if c.state.entities[i].card_id in(ROGUE1,MAGE4))
    for name,body,target in(('kill',lambda c:(Destroy(c.target_id,c.source_id),),True),('silence',lambda c:(Silence(c.target_id),),True),
            ('hero',lambda c:(ReplaceHero(1,'HERO_01'),),False),('price',price,False)):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if target else None))
    for cid in(BOOK,PIRATE,NURSE):
        key=TEST+'summon.'+cid;r.register_behavior(key,lambda c,card=cid:(Summon(1,card),));r.register_card(CardDefinition(key,'Natural summon',CardType.SPELL,on_play=key,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P27 deliberate generation failure')))
    r.register_behavior(TEST+'kill_end',lambda c:(Destroy(c.state.players[1].board[0],c.source_id),))
    r.register_card(CardDefinition(TEST+'end','End death fixture',CardType.MINION,health=2,triggers=(TriggerSpec('turn_ended',TEST+'kill_end'),),metadata=META))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id in members
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            effects=()
            if mode=='retire':effects=(Destroy(next(i for i in c.state.players[1].board if c.state.entities[i].card_id==BOOK),c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',effects),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Acquisition reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP27Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08',unknown_kind=CardType.SPELL):
        self.members=members;self.mode=mode;self.pool=pool;self.unknown_kind=unknown_kind
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=2727,generation_context=context),registry(members,mode,pool,unknown_kind))
    def first(self,g,cid,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[1],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def created(self,g,source=None):return[e for e in g.events if e.kind=='card_created'and(source is None or e.source_id==source)]
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool,self.unknown_kind));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool,self.unknown_kind)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','deathrattle_history'):self.assertNotIn('"'+key+'"',public)
        return other
    def candidates(self,r,key,current=None):return{m.card_id for m in resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[key],current_class=current,player_id=1)}

    def test_six_complete_raw_rows_eight_faces_and_full_metadata(self):
        d=load_batch();r=registry();self.assertEqual(len(d['cards']+d['evidence_only']),6);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']))
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],c.cost,c.attack,c.health))
        self.assertEqual(r.card(PIRATE).metadata.tribes,('pirate',));self.assertEqual(r.card(CAKE).metadata.tribes,('mech',));self.assertFalse(r.card(CAKE).keywords);self.assertNotEqual(d['cards'][0]['record']['name'],d['evidence_only'][0]['record']['name'])

    def test_only_four_defs_added_aliases_and_production_pools_unchanged(self):
        with patch('hs_sim.cards.simple_followup_p27_cards.register_simple_followup_p27_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p27_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))
        for cid in('EDR_001','KAR_069'):self.assertEqual(cid in before.cards,cid in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_exact_class_kind_and_printed_one_cost_queries(self):
        r=registry();self.assertEqual(self.candidates(r,BOOK+'.bc'),{MAGE1,MAGE4,DUAL});self.assertEqual(self.candidates(r,NURSE+'.bc'),{PIRATE,NURSE,CAKE});self.assertEqual(self.candidates(r,NURSE+'.dr'),{MAGE1,ROGUE1});self.assertEqual(self.candidates(r,CAKE+'.dr'),{WEAPON,DUAL_WEAPON})
        other=self.candidates(r,PIRATE+'.bc',CardClass.MAGE);self.assertEqual(other,{PIRATE,NURSE,ROGUE1,WEAPON,DUAL_WEAPON});self.assertEqual(QUERIES[PIRATE+'.bc'].kinds,());self.assertEqual(QUERIES[BOOK+'.bc'].classes,(CardClass.MAGE,))

    def test_bookcase_two_replacement_draws_exact_rng_new_entities_and_source(self):
        g=self.game((BOOK,),members=(MAGE1,));rng=random.Random();rng.setstate(g._rng.getstate());rows=resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[BOOK+'.bc'],player_id=1);expected=sample_candidates(rng,rows,2,replacement=True);source=self.play(g,BOOK);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],list(expected));self.assertEqual(len({e.target_id for e in events}),2);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,47);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_bookcase_fixed_mage_filter_under_other_current_hero(self):
        g=self.game((TEST+'hero',BOOK),members=(MAGE1,WEAPON,ROGUE1,DUAL));self.play(g,TEST+'hero');self.assertEqual(g.state.players[1].hero_class,CardClass.WARRIOR);source=self.play(g,BOOK);events=self.created(g,source);self.assertEqual(len(events),2);self.assertTrue(all(g.state.entities[e.target_id].card_id in(MAGE1,DUAL)for e in events))

    def test_swashburglar_current_replaced_hero_not_printed_rogue_and_all_kinds(self):
        g=self.game((TEST+'hero',PIRATE));self.play(g,TEST+'hero');eligible=self.candidates(g.registry,PIRATE+'.bc',g.state.players[1].hero_class);self.assertIn(PIRATE,eligible);self.assertIn(DUAL_WEAPON,eligible);self.assertIn(MAGE1,eligible);self.assertNotIn(WEAPON,eligible);self.assertNotIn(CAKE,eligible);rng=random.Random();rng.setstate(g._rng.getstate());rows=resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[PIRATE+'.bc'],current_class=CardClass.WARRIOR,player_id=1,source_card_id=PIRATE,exclude_source_by_rule=True);expected=sample_candidates(rng,rows,1,replacement=True);source=self.play(g,PIRATE);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,expected[0]);self.assertEqual(g._rng.getstate(),rng.getstate());self.portable(g)

    def test_nurse_paid_battlecry_then_native_deathrattle_separate_types(self):
        g=self.game((NURSE,TEST+'kill'),members=(PIRATE,ROGUE1));source=self.play(g,NURSE);first,=self.created(g,source);self.assertEqual(g.state.entities[first.target_id].card_id,PIRATE);self.play(g,TEST+'kill',source);events=self.created(g,source);self.assertEqual([g.state.entities[e.target_id].card_id for e in events],[PIRATE,ROGUE1]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);record,=g.state.deathrattle_history;self.assertEqual(record.capture.origin,'death');self.assertEqual(record.capture.ability.deathrattle_card_id,NURSE);self.assertTrue(record.completed);self.portable(g)

    def test_cake_native_deathrattle_gets_weapon_without_battlecry(self):
        g=self.game((CAKE,TEST+'kill'),members=(WEAPON,));source=self.play(g,CAKE);self.assertFalse(self.created(g));self.assertFalse(g.state.battlecry_history);self.play(g,TEST+'kill',source);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,WEAPON);self.assertIn(event.target_id,g.state.players[1].hand);record,=g.state.deathrattle_history;self.assertEqual(record.capture.ability.deathrattle_card_id,CAKE);self.assertTrue(record.completed)

    def test_natural_summon_excludes_all_three_battlecries_without_context(self):
        for cid in(BOOK,PIRATE,NURSE):
            with self.subTest(cid=cid):
                spell=TEST+'summon.'+cid;g=self.game((spell,),context=None,pool=False);self.play(g,spell);self.assertEqual(self.first(g,cid,'board').card_id,cid);self.assertFalse(g.state.battlecry_history);self.assertFalse(self.created(g))

    def test_silence_removes_actual_deathrattles_without_requiring_pool(self):
        for cid in(NURSE,CAKE):
            with self.subTest(cid=cid):
                g=self.game((TEST+'silence',TEST+'kill'),board=(cid,),context=None,pool=False);source=self.first(g,cid,'board').id;self.play(g,TEST+'silence',source);self.play(g,TEST+'kill',source);self.assertFalse(self.created(g));self.assertFalse(g.state.deathrattle_history)

    def test_nurse_spell_filter_uses_printed_not_existing_instance_cost(self):
        g=self.game((TEST+'price',ROGUE1,MAGE4,TEST+'kill'),board=(NURSE,),members=(ROGUE1,MAGE4));self.play(g,TEST+'price');self.assertEqual(g.quote_cost(self.first(g,ROGUE1).id).amount,7);self.assertEqual(g.quote_cost(self.first(g,MAGE4).id).amount,1);source=self.first(g,NURSE,'board').id;self.play(g,TEST+'kill',source);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertEqual(new.card_id,ROGUE1);self.assertEqual(g.quote_cost(new.id).amount,1);self.assertNotEqual(new.id,self.first(g,ROGUE1).id)

    def test_missing_context_or_pool_rolls_back_paid_battlecry_and_natural_death(self):
        for bc in(True,False):
            for context,pool in((None,True),(CONTEXT,False)):
                with self.subTest(bc=bc,context=context,pool=pool):
                    g=self.game((BOOK,)if bc else(TEST+'kill',),board=()if bc else(CAKE,),context=context,pool=pool);saved=g.snapshot()
                    with self.assertRaises((ResolutionError,ValueError)):
                        if bc:self.play(g,BOOK)
                        else:self.play(g,TEST+'kill',self.first(g,CAKE,'board').id)
                    self.assertEqual(g.snapshot(),saved)

    def test_all_eligible_unknowns_fail_before_rng_and_roll_back(self):
        for cid,kind,bc in((BOOK,CardType.SPELL,True),(NURSE,CardType.SPELL,False),(CAKE,CardType.WEAPON,False)):
            with self.subTest(cid=cid):
                g=self.game((cid,)if bc else(TEST+'kill',),board=()if bc else(cid,),members=(*MEMBERS,UNKNOWN),unknown_kind=kind);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete validation'))as rng_calls:
                    with self.assertRaises((ResolutionError,ValueError)):
                        if bc:self.play(g,cid)
                        else:self.play(g,TEST+'kill',self.first(g,cid,'board').id)
                    rng_calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_bookcase_capacity_one_arrives_one_burns_with_source(self):
        g=self.game((BOOK,)+(YETI,)*9,members=(MAGE1,));source=self.play(g,BOOK);events=self.created(g,source);self.assertEqual(len(events),2);self.assertEqual(len(g.state.players[1].hand),10);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertIn(burn.target_id,{e.target_id for e in events});self.assertEqual(g.state.entities[burn.target_id].card_id,MAGE1);self.assertEqual(len({e.target_id for e in events}&set(g.state.players[1].hand)),1)

    def test_cake_full_hand_burns_new_weapon_after_native_death(self):
        g=self.game((YETI,)*10,board=(CAKE,TEST+'end'),members=(WEAPON,));source=self.first(g,CAKE,'board').id;g.apply(EndTurn(1));event,=self.created(g,source);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(event.target_id,burn.target_id);self.assertEqual(g.state.entities[burn.target_id].card_id,WEAPON);self.assertEqual(len(g.state.players[1].hand),10)

    def test_two_draw_creation_wait_restore_replay_bad_choice_and_source_retirement(self):
        g=self.game((BOOK,),members=(MAGE1,),mode='retire');source=self.play(g,BOOK);self.assertIsNotNone(g.state.pending_choice);rng=g._rng.getstate();other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());events=self.created(g,source);self.assertEqual(len(events),2);self.assertTrue(all(g.state.entities[e.target_id].card_id==MAGE1 for e in events));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g._rng.getstate(),rng);self.portable(g)

    def test_native_death_generation_wait_restore_clone_replay_and_privacy(self):
        g=self.game((TEST+'kill',),board=(CAKE,),members=(WEAPON,),mode='wait');source=self.first(g,CAKE,'board').id;self.play(g,TEST+'kill',source);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,WEAPON);self.assertTrue(g.state.deathrattle_history[0].completed);self.portable(g)

    def test_late_generation_failure_rolls_back_paid_play_and_death_rng(self):
        for bc in(True,False):
            with self.subTest(bc=bc):
                g=self.game((BOOK,)if bc else(TEST+'kill',),board=()if bc else(CAKE,),members=(MAGE1,WEAPON),mode='fail');saved=g.snapshot()
                with self.assertRaises(ResolutionError):
                    if bc:self.play(g,BOOK)
                    else:self.play(g,TEST+'kill',self.first(g,CAKE,'board').id)
                self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
