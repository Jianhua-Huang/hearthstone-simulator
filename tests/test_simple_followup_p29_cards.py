"""Private ordinary discoveries over explicit experimental inventories."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
from types import SimpleNamespace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p29_cards import WHELP,VICAR,NETHER,PEDDLER,ROOTS,DEPENDENCIES,IDENTITIES,QUERIES,PREFIX,POOL_ID,load_batch,register_simple_followup_p29_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,TriggerBattlecry,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,Destroy,InvokeBehavior,ReplaceHero,RequestChoice,Summon
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates,sample_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import canonical_digest
TEST='p29.test.';YETI='CORE_CS2_182';MAGE1='EX1_277';WARLOCK1='EX1_308';PALADIN1='EX1_130';WEAPON1='CS2_091';NEUTRAL1='JAIL_460';HOLY='CORE_CS2_089';PRIEST_HOLY='CORE_CFM_604';DEMON='CORE_CS2_065';NEUTRAL_DEMON='BT_156';MAGE_DEMON='BT_004';ALL='DINO_435'
MEMBERS=(*ROOTS,MAGE1,WARLOCK1,PALADIN1,WEAPON1,NEUTRAL1,HOLY,PRIEST_HOLY,DEMON,NEUTRAL_DEMON,MAGE_DEMON,ALL,YETI);CONTEXT=GenerationContext('p29-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p29_cards(r)
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for cid in members:
        if cid.startswith(TEST+'unimplemented_metadata.'):
            original=cid[len(TEST+'unimplemented_metadata.'):]
            r.register_pool_card(replace(r.pool_card(original),card_id=cid))
        elif cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p29-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    for cid in ROOTS:
        key=TEST+'summon.'+cid;r.register_behavior(key,lambda c,card=cid:(Summon(1,card),));r.register_card(CardDefinition(key,'Natural summon',CardType.SPELL,on_play=key,metadata=META))
    for name,body in(('hero',lambda c:(ReplaceHero(1,'HERO_04'),)),('wound',lambda c:(Damage(c.state.players[1].hero_id,5,c.source_id),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P29 deliberate discovery arrival failure')))
    def full(c):
        source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==WHELP)
        return(AddToHand(1,YETI,c.source_id),TriggerBattlecry(MinionReference.capture(c.state.entities[source]),c.source_id,choices='player'))
    r.register_behavior(TEST+'full',full);r.register_card(CardDefinition(TEST+'full','Fill then activate native Battlecry',CardType.SPELL,on_play=TEST+'full',metadata=META))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            if mode=='fill':return(AddToHand(1,YETI,c.source_id),)
            tail=(Destroy(c.event.source_id,c.source_id),)if mode=='retire'else()
            return(RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Real discovery acquisition reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP29Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,hero='HERO_08'):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=2929,generation_context=context),registry(members,mode,pool))
    def first(self,g,cid):return next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
    def play(self,g,cid):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def choose(self,g,card=None,key=None):
        q=g.state.pending_choice;selected=key if key is not None else next(o.id for o in q.options if card is None or o.card_id==card);g.apply(SelectChoice(q.player_id,q.id,(selected,)))
    def created(self,g,source):return[e for e in g.events if e.kind=='card_created'and e.source_id==source]
    def health(self,g):return g.state.entities[g.state.players[1].hero_id].health
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','behavior_id','candidate_root_ids','heal_hero_by_printed_cost'):self.assertNotIn('"'+key+'"',public)
        return other
    def candidates(self,r,cid,current=CardClass.PALADIN):return{m.card_id for m in resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[cid],current_class=current,player_id=1)}

    def test_seven_complete_rows_eight_faces_metadata_and_ordinary_defaults(self):
        d=load_batch();r=batch_registry();self.assertEqual(len(d['cards']+d['evidence_only']),7);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];c=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]));self.assertEqual((c.cost,c.attack,c.health),(raw['cost'],raw['attack'],raw['health']));self.assertFalse(c.keywords);self.assertIsNone(c.on_play);self.assertIsNone(c.deathrattle)
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],c.cost,c.attack,c.health))
            effect,=r.behavior(c.battlecry)(SimpleNamespace(player_id=1,source_id=42));self.assertIsInstance(effect,DiscoverFromPool);self.assertEqual((effect.count,effect.discoveries,effect.destination,effect.delivery,effect.replacement),(3,1,'hand','after_each',True));self.assertFalse(effect.heal_hero_by_printed_cost);self.assertIsNone(effect.gift_pool);self.assertIsNone(effect.cost);self.assertEqual(effect.source_id,42)
        self.assertEqual(r.card(WHELP).metadata.tribes,('dragon',));self.assertEqual(r.card(WHELP).metadata.subtypes,('whelp',));self.assertEqual(r.card(VICAR).metadata.tribes,('draenei',));self.assertEqual(r.card(NETHER).metadata.tribes,());self.assertEqual(r.card(PEDDLER).metadata.tribes,('undead',))

    def test_four_new_defs_old_definitions_aliases_and_pool_filters_preserved(self):
        with patch('hs_sim.cards.simple_followup_p29_cards.register_simple_followup_p29_cards',lambda r:None), \
                patch('hs_sim.cards.assemble_hand_generation_fragments.register_assemble_hand_generation_fragments',lambda r:None):
            before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertEqual(set(before.pool_cards),set(after.pool_cards))
        for cid,row in before.pool_cards.items():self.assertEqual(replace(row,metadata=replace(row.metadata,deck_identity=IDENTITIES[cid]))if cid in ROOTS else row,after.pool_card(cid))
        for alias in('ONY_022','BT_321','WON_096'):self.assertEqual(alias in before.cards,alias in after.cards)
        self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()))

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_exact_queries_any_class_current_class_neutral_all_and_any_card_kind(self):
        r=registry();self.assertEqual(self.candidates(r,WHELP),{MAGE1,WARLOCK1,PALADIN1});self.assertEqual(self.candidates(r,VICAR),{HOLY});self.assertEqual(self.candidates(r,VICAR,CardClass.PRIEST),{PRIEST_HOLY});self.assertEqual(self.candidates(r,NETHER,CardClass.WARLOCK),{DEMON,NEUTRAL_DEMON,ALL});self.assertEqual(self.candidates(r,NETHER,CardClass.MAGE),{MAGE_DEMON,NEUTRAL_DEMON,ALL});self.assertEqual(self.candidates(r,PEDDLER),{PALADIN1,WEAPON1,NEUTRAL1});self.assertEqual(QUERIES[PEDDLER].kinds,())
        for cid in(VICAR,NETHER,PEDDLER):self.assertEqual(QUERIES[cid].class_mode,'current');self.assertTrue(QUERIES[cid].include_neutral)

    def test_whelp_paid_battlecry_exact_distinct_private_offers_and_selected_new_identity(self):
        g=self.game((TEST+'wound',WHELP));self.play(g,TEST+'wound');health=self.health(g);rng=random.Random();rng.setstate(g._rng.getstate());rows=resolve_candidates(g.registry,CONTEXT,POOL_ID,QUERIES[WHELP],player_id=1);expected=sample_candidates(rng,rows,3,replacement=False);source=self.play(g,WHELP);self.assertEqual([o.card_id for o in g.state.pending_choice.options],list(expected));self.assertEqual(len(set(expected)),3);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(g.state.players[1].mana,49);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1});self.assertFalse(self.created(g,source));other=self.portable(g);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,expected[0]);self.assertNotEqual(event.target_id,source);self.assertEqual(self.health(g),health);self.assertFalse([e for e in g.events if e.kind=='health_resolved'and health_result(e).flow=='healing']);self.assertIsNone(g.observe(2)['players'][0]['hand'][0]['card_id']);self.portable(g)

    def test_vicar_uses_current_priest_not_printed_paladin_and_never_heals(self):
        g=self.game((TEST+'wound',VICAR),hero='HERO_09');self.play(g,TEST+'wound');health=self.health(g);source=self.play(g,VICAR);self.assertEqual([o.card_id for o in g.state.pending_choice.options],[PRIEST_HOLY]);self.choose(g);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,PRIEST_HOLY);self.assertEqual(self.health(g),health)

    def test_nether_current_mage_accepts_neutral_all_demon_excludes_printed_dh(self):
        g=self.game((TEST+'wound',NETHER));self.play(g,TEST+'wound');health=self.health(g);source=self.play(g,NETHER);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{MAGE_DEMON,NEUTRAL_DEMON,ALL});self.choose(g,ALL);event,=self.created(g,source);self.assertEqual(g.state.entities[event.target_id].card_id,ALL);self.assertEqual(self.health(g),health)

    def test_peddler_replaced_current_hero_offers_minion_spell_weapon_and_selects_weapon(self):
        g=self.game((TEST+'hero',TEST+'wound',PEDDLER));self.play(g,TEST+'hero');self.play(g,TEST+'wound');health=self.health(g);self.assertEqual(g.state.players[1].hero_class,CardClass.PALADIN);source=self.play(g,PEDDLER);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{NEUTRAL1,PALADIN1,WEAPON1});self.choose(g,WEAPON1);event,=self.created(g,source);new=g.state.entities[event.target_id];self.assertEqual(new.card_id,WEAPON1);self.assertIn(new.id,g.state.players[1].hand);self.assertEqual(g.registry.card(new.card_id).kind,CardType.WEAPON);self.assertEqual(self.health(g),health)

    def test_natural_summons_do_not_discover_or_require_context_pool(self):
        for cid in ROOTS:
            with self.subTest(cid=cid):
                spell=TEST+'summon.'+cid;g=self.game((spell,),context=None,pool=False);self.play(g,spell);self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.battlecry_history)

    def test_missing_context_or_pool_rolls_back_paid_discovery(self):
        for context,pool in((None,True),(CONTEXT,False)):
            with self.subTest(context=context,pool=pool):
                g=self.game((WHELP,),context=context,pool=pool);saved=g.snapshot()
                with self.assertRaises(ResolutionError):self.play(g,WHELP)
                self.assertEqual(g.snapshot(),saved)

    def test_real_eligible_unimplemented_members_fail_before_rng_not_clipped(self):
        for cid,original,hero in((WHELP,'CAP_002','HERO_08'),(VICAR,'CORE_KAR_077','HERO_04'),(NETHER,'EDR_102','HERO_07'),(PEDDLER,'CATA_621','HERO_04')):
            with self.subTest(cid=cid):
                unknown=TEST+'unimplemented_metadata.'+original
                g=self.game((cid,),members=(*MEMBERS,unknown),hero=hero);self.assertIn(unknown,g.registry.pool_cards);self.assertNotIn(unknown,g.registry.cards);saved=g.snapshot()
                self.assertIn(original,g.registry.cards)
                self.assertEqual(replace(g.registry.pool_card(unknown),card_id=original),g.registry.pool_card(original))
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before complete eligible validation'))as calls:
                    with self.assertRaises(ResolutionError):self.play(g,cid)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_empty_eligible_inventory_no_rng_no_choice_but_native_payment(self):
        g=self.game((WHELP,),members=(YETI,));saved_rng=g._rng.getstate()
        with patch.object(random.Random,'randrange',side_effect=AssertionError('Empty discovery consumed RNG'))as calls:self.play(g,WHELP);calls.assert_not_called()
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),saved_rng);self.assertEqual(g.state.players[1].mana,49);self.assertEqual(len(g.state.battlecry_history),1)

    def test_delivery_capacity_burns_selected_new_card_preserving_source(self):
        g=self.game((TEST+'full',)+(YETI,)*9,board=(WHELP,),members=(MAGE1,));source=next(i for i in g.state.players[1].board if g.state.entities[i].card_id==WHELP);self.play(g,TEST+'full');self.assertEqual(len(g.state.players[1].hand),10);self.choose(g);event,=self.created(g,source);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(event.target_id,burn.target_id);self.assertEqual(g.state.entities[burn.target_id].card_id,MAGE1);self.assertEqual(len(g.state.players[1].hand),10);self.assertIsNone(g.state.pending_choice)

    def test_selection_creation_wait_restore_clone_replay_bad_resume_and_source_retirement(self):
        g=self.game((WHELP,),members=(MAGE1,),mode='retire');source=self.play(g,WHELP);self.choose(g);self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,key='bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g,key='ok');self.choose(other,key='ok');self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);event,=self.created(g,source);self.assertIn(event.target_id,g.state.players[1].hand);self.portable(g)

    def test_late_selected_arrival_failure_preserves_committed_offer_and_rng(self):
        g=self.game((WHELP,),members=(MAGE1,),mode='fail');self.play(g,WHELP);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),saved);self.assertEqual([o.card_id for o in g.state.pending_choice.options],[MAGE1])

    def test_invalid_choice_leaves_original_private_offer_unchanged(self):
        g=self.game((WHELP,));self.play(g,WHELP);saved=g.snapshot()
        with self.assertRaises(IllegalAction):self.choose(g,key='not-an-offered-key')
        self.assertEqual(g.snapshot(),saved);self.assertEqual(g.observe(2)['pending_choice'],{'player_id':1})

if __name__=='__main__':unittest.main()
