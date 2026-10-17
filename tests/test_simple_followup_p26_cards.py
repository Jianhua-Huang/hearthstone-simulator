"""Explicit experimental format inventory for Legendary and native end-body generators."""
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from dataclasses import asdict,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p26_cards import BRIGHT,SENTRY,PIXIE,TOTEM,ROOTS,DEPENDENCIES,QUERIES,ZERO_ATTACK,PREFIX,POOL_ID,load_batch,register_simple_followup_p26_cards
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,SpellSchool,TargetSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence,Summon
from hs_sim.engine.end_turns import TriggerEndTurnEffects
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import EndTurnRequest,EndTurnSelector,LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
TEST='p26.test.';YETI='CORE_CS2_182';HOLY='CORE_CFM_604';HOLY2='CORE_CS2_089';NATURE='CS2_009';SHADOW='CORE_EX1_197';FIRE='CS2_029';UNKNOWN_LEG=TEST+'unknown_legendary';UNKNOWN_HOLY=TEST+'unknown_holy'
OTHER_LEG='CATA_155'
MEMBERS=(BRIGHT,OTHER_LEG,HOLY,NATURE,SHADOW,FIRE,YETI);CONTEXT=GenerationContext('p26-explicit-experiment','experimental');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())

def registry(members=MEMBERS,mode=None,pool=True):
    r=build_registry()
    if not all(cid in r.cards for cid in ROOTS):register_simple_followup_p26_cards(r)
    for cid in members:
        if cid in r.pool_cards:continue
        if cid in(UNKNOWN_LEG,UNKNOWN_HOLY):r.register_pool_card(PoolCard(cid,CardType.MINION if cid==UNKNOWN_LEG else CardType.SPELL,3,
            CardMetadata(True,(CardClass.NEUTRAL,),Rarity.LEGENDARY if cid==UNKNOWN_LEG else Rarity.COMMON,tribes=(),factions=(),subtypes=()),spell_school=None if cid==UNKNOWN_LEG else SpellSchool.HOLY))
        else:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p26-complete-explicit-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True))
    r.register_behavior(TEST+'summon',lambda c:(Summon(1,BRIGHT),))
    r.register_card(CardDefinition(TEST+'summon','Natural summon',CardType.SPELL,on_play=TEST+'summon',metadata=META))
    def extra(c):return(TriggerEndTurnEffects(c.player_id,EndTurnRequest(EndTurnSelector('selected',(c.player_id,),('minion',),(c.target_id,))),c.source_id),)
    for name,body in(('extra',extra),('silence',lambda c:(Silence(c.target_id),)),('give',lambda c:(ChangeControl(c.target_id,2),))):
        key=TEST+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))))
    r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P26 deliberate generation failure')))
    if mode:
        def eligible(c):return c.event.player_id==1 and c.state.entities[c.event.target_id].card_id in members
        def watch(c):
            if mode=='fail':return(InvokeBehavior(TEST+'fail',c.source_id,1),)
            extra=()
            if mode=='retire':
                target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==SENTRY);extra=(Destroy(target,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',extra),ChoiceOption('bad','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Actual school acquisition reaction',CardType.MINION,health=9,metadata=META,
            limited_triggers=(LimitedTriggerSpec('card_added_to_hand'if mode=='fail'else'card_created',TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

class SimpleFollowupP26Tests(unittest.TestCase):
    def game(self,hand=(),board=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,active=1):
        self.members=members;self.mode=mode;self.pool=pool
        if mode:board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50)),seed=2626,generation_context=context,active_player=active),registry(members,mode,pool))
    def first(self,g,cid,p=1,zone='hand'):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None):
        eid=self.first(g,cid).id;g.apply(PlayCard(1,eid,target,len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def generated(self,g,p=1):return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id in(BRIGHT,OTHER_LEG,HOLY,HOLY2,NATURE,SHADOW)]
    def price(self,g,eid):return quote_cost(g.state,g.registry,g.state.entities[eid]).amount
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(self.members,self.mode,self.pool));self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.members,self.mode,self.pool)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','pool_id','EndTurnCapture','behavior_id'):self.assertNotIn('"'+key+'"',public)
        return other

    def test_five_complete_raw_rows_eight_faces_and_individual_reviewed_zero_attack(self):
        d=load_batch();r=registry();self.assertEqual(len(d['cards']+d['evidence_only']),5);self.assertEqual(len(d['official_observations']['observations']),8);self.assertTrue(d['required_generation_context']);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);self.assertEqual(d['reviewed_zero_attack'],{PIXIE:0,TOTEM:0})
        def norm(s):return re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']:
            raw=row['record'];cid=raw['id'];card=r.card(cid);self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual(card.metadata,replace(metadata_from_record(raw),deck_identity='EX1_189'if cid==BRIGHT else cid));self.assertEqual(card.attack,0 if cid in ZERO_ATTACK else raw['attack']);self.assertEqual(card.health,raw['health'])
            for o in(o for o in d['official_observations']['observations']if o['card_id']==cid):
                f=o['face'];en=o['locale'].lower().replace('_','-')=='en-us';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['id'],f['manaCost'],f['attack'],f['health']),(raw['dbf_id'],raw['cost'],card.attack,raw['health']))
            if cid in ZERO_ATTACK:self.assertIsNone(raw['attack']);self.assertNotIn('ATK',raw['tags'])
        self.assertEqual((r.card(BRIGHT).cost,r.card(BRIGHT).attack,r.card(BRIGHT).health),(2,3,2));self.assertEqual(r.card(BRIGHT).metadata.tribes,('dragon',));self.assertEqual(r.card(TOTEM).metadata.tribes,('totem',));self.assertEqual(set(r.card(TOTEM).metadata.classes),{CardClass.PRIEST,CardClass.SHAMAN})
        for cid in(SENTRY,PIXIE,TOTEM):self.assertIsNone(r.card(cid).battlecry);self.assertEqual(r.card(cid).triggers[0].end_turn.turn_scope,'controller')

    def test_only_four_defs_added_no_production_pool_or_alias_change(self):
        with patch('hs_sim.cards.simple_followup_p26_cards.register_simple_followup_p26_cards',lambda r:None):before=build_registry()
        after=build_registry()
        if not all(cid in after.cards for cid in ROOTS):register_simple_followup_p26_cards(after)
        self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS));self.assertFalse(DEPENDENCIES);self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools));self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in after.pools.values()));self.assertEqual('EX1_189'in before.cards,'EX1_189'in after.cards)

    def test_default311_complete_fingerprint_unchanged(self):
        from hs_sim.engine.representative import build_registry as default
        r=default();self.assertEqual(len(r.cards),311);self.assertEqual(r.fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_queries_filter_legendary_minions_and_exact_spell_schools_any_class(self):
        r=registry();expected={BRIGHT:{BRIGHT,OTHER_LEG},SENTRY:{HOLY},PIXIE:{NATURE},TOTEM:{SHADOW}}
        for cid in ROOTS:
            with self.subTest(cid=cid):self.assertEqual({m.card_id for m in resolve_candidates(r,CONTEXT,POOL_ID,QUERIES[cid],player_id=1)},expected[cid]);self.assertEqual(QUERIES[cid].class_mode,'any');self.assertTrue(QUERIES[cid].collectible)

    def test_brightwing_paid_native_battlecry_gets_new_legendary_once(self):
        g=self.game((BRIGHT,));source=self.play(g,BRIGHT);new,=self.generated(g);self.assertEqual(new.card_id,OTHER_LEG);self.assertNotEqual(new.id,source);self.assertEqual(g.state.players[1].mana,48);self.assertEqual(len(g.state.battlecry_history),1);self.assertTrue(all(e.source_id==source for e in g.events if e.kind in('card_created','card_added_to_hand')));self.portable(g)

    def test_brightwing_natural_summon_does_not_invoke_battlecry_or_require_pool(self):
        g=self.game((TEST+'summon',),pool=False,context=None);self.play(g,TEST+'summon');self.assertFalse(self.generated(g));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[BRIGHT]);self.assertFalse(g.state.battlecry_history)

    def test_each_school_source_only_own_natural_end_and_no_battlecry(self):
        for cid,spell in((SENTRY,HOLY),(PIXIE,NATURE),(TOTEM,SHADOW)):
            with self.subTest(cid=cid):
                g=self.game(board=(cid,),active=2);g.apply(EndTurn(2));self.assertFalse(self.generated(g));g.apply(EndTurn(1));new,=self.generated(g);self.assertEqual(new.card_id,spell);source=self.first(g,cid,zone='board').id;self.assertTrue(any(e.kind=='card_added_to_hand'and e.target_id==new.id and e.source_id==source for e in g.events));self.assertFalse(g.state.battlecry_history)

    def test_sentry_permanent_delta_minus_three_with_floor_not_set_to_three(self):
        for spell,expected in((HOLY,1),(HOLY2,0)):
            with self.subTest(spell=spell):
                g=self.game(board=(SENTRY,),members=(spell,));g.apply(EndTurn(1));new,=self.generated(g);self.assertEqual(self.price(g,new.id),expected);self.assertEqual(new.base_cost,g.registry.card(spell).cost);self.assertTrue(any(e.cost==-3 and e.set_cost is None and e.expires_turn is None for e in new.enchantments));g.apply(EndTurn(2));self.assertEqual(self.price(g,new.id),expected)

    def test_pixie_totem_do_not_add_creation_discounts(self):
        for cid,spell in((PIXIE,NATURE),(TOTEM,SHADOW)):
            with self.subTest(cid=cid):
                g=self.game(board=(cid,));g.apply(EndTurn(1));new,=self.generated(g);self.assertEqual(self.price(g,new.id),g.registry.card(spell).cost);self.assertFalse([e for e in new.enchantments if e.cost!=0 or e.set_cost is not None])

    def test_shared_extra_end_effect_executes_without_natural_event_or_turn_advance(self):
        g=self.game((TEST+'extra',),board=(SENTRY,));source=self.first(g,SENTRY,zone='board').id;before=(g.state.turn,g.state.active_player,len(g.state.owner_turn_history));self.play(g,TEST+'extra',source);self.assertEqual((g.state.turn,g.state.active_player,len(g.state.owner_turn_history)),before);new,=self.generated(g);self.assertEqual(new.card_id,HOLY);self.assertEqual(self.price(g,new.id),1);self.assertFalse([e for e in g.events if e.kind=='turn_ended']);self.portable(g)

    def test_real_end_repeat_generates_each_actual_repetition_with_discount(self):
        g=self.game(board=('TIME_064',SENTRY));g.apply(EndTurn(1));new=self.generated(g);self.assertEqual(len(new),2);self.assertTrue(all(e.card_id==HOLY and self.price(g,e.id)==1 for e in new));self.assertEqual(len({e.id for e in new}),2)

    def test_silence_and_control_transfer_use_native_owner_end_scope(self):
        g=self.game((TEST+'silence',),board=(PIXIE,));self.play(g,TEST+'silence',self.first(g,PIXIE,zone='board').id);g.apply(EndTurn(1));self.assertFalse(self.generated(g))
        g=self.game((TEST+'give',),board=(TOTEM,));source=self.first(g,TOTEM,zone='board').id;self.play(g,TEST+'give',source);g.apply(EndTurn(1));self.assertFalse(self.generated(g));g.apply(EndTurn(2));new,=self.generated(g,2);self.assertEqual(new.card_id,SHADOW);self.assertEqual(g.state.entities[source].controller,2)

    def test_missing_context_or_pool_rolls_back_paid_battlecry_and_natural_end(self):
        for bright in(False,True):
            for context,pool in((None,True),(CONTEXT,False)):
                with self.subTest(bright=bright,context=context,pool=pool):
                    g=self.game((BRIGHT,)if bright else(),board=()if bright else(SENTRY,),context=context,pool=pool);saved=g.snapshot()
                    with self.assertRaises((ResolutionError,ValueError)):
                        if bright:self.play(g,BRIGHT)
                        else:g.apply(EndTurn(1))
                    self.assertEqual(g.snapshot(),saved)

    def test_eligible_unknowns_fail_before_rng_for_battlecry_and_end(self):
        for bright,unknown in((True,UNKNOWN_LEG),(False,UNKNOWN_HOLY)):
            with self.subTest(bright=bright):
                g=self.game((BRIGHT,)if bright else(),board=()if bright else(SENTRY,),members=(*MEMBERS,unknown));saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before eligible content validation'))as rng_calls:
                    with self.assertRaises((ResolutionError,ValueError)):
                        if bright:self.play(g,BRIGHT)
                        else:g.apply(EndTurn(1))
                    rng_calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_full_hand_end_generation_burns_material_and_retains_discount(self):
        g=self.game((YETI,)*10,board=(SENTRY,));source=self.first(g,SENTRY,zone='board').id;g.apply(EndTurn(1));self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(self.generated(g));burn,=[e for e in g.events if e.kind=='card_burned'];new=g.state.entities[burn.target_id];self.assertEqual(new.card_id,HOLY);self.assertTrue(any(e.cost==-3 and e.set_cost is None for e in new.enchantments));self.assertTrue(any(e.kind=='card_created'and e.target_id==new.id and e.source_id==source for e in g.events))

    def test_end_creation_wait_restore_replay_bad_choice_and_source_retirement(self):
        g=self.game(board=(SENTRY,),mode='retire');source=self.first(g,SENTRY,zone='board').id;g.apply(EndTurn(1));self.assertIsNotNone(g.state.pending_choice);other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());new,=self.generated(g);self.assertEqual((new.card_id,self.price(g,new.id)),(HOLY,1));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.active_player,2);self.portable(g)

    def test_late_generation_failure_rolls_back_whole_end_action_and_rng(self):
        g=self.game(board=(SENTRY,),mode='fail');saved=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(),saved)

if __name__=='__main__':unittest.main()
