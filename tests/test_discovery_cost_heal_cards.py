"""Real selected spell healing through the shared discovery and health pipes."""
from copy import deepcopy
from dataclasses import asdict,fields,is_dataclass,replace
import json,random,re,unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards.discovery_cost_heal_cards import KNIGHT,BODY,POOL_ID,BATCH_HASH,load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,CostSpec,Game,PlayCard,PlayerSetup,
    Scenario,SelectChoice,SnapshotError,Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.discovery import HealHeroFromDiscoveredSpell
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,
    ModifyCost,ReplaceHero,RequestChoice,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import HealthFlow,HealthOp,HealthRule,HealingKind,LimitedTriggerSpec,Rarity
from hs_sim.engine.pools import DiscoverFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash,SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import TargetValidationError,canonical_digest

P='k110.test.';YETI='CORE_CS2_182';PALADIN4='END_014';LIGHT='CORE_CS2_089';FIRE='CS2_029';ROGUE='CORE_CS2_075';ZERO='CORE_EX1_169';UNKNOWN=P+'unknown'
CTX=GenerationContext('k110-explicit-discovery-experiment','experimental');MEMBERS=(PALADIN4,LIGHT,FIRE,ROGUE,ZERO,YETI,'DREAM_01');META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


def registry(members=MEMBERS,mode=None,wound=10,pool=True):
    r=build_registry()
    if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,3,CardMetadata(True,(CardClass.PALADIN,),Rarity.COMMON,tribes=(),factions=(),subtypes=()),battlecry=False))
    for cid in members:
        if cid not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'k110-complete-explicit-fixture-v1',CTX.target_id,CTX.mode,tuple(PoolMember(c)for c in members),complete=True))
    for name,body in(('wound',lambda c:(Damage(c.state.players[1].hero_id,wound,c.source_id),)),
            ('summon',lambda c:(Summon(1,KNIGHT),)),('wound_current',lambda c:(Damage(c.state.players[1].hero_id,10,c.source_id),))):
        key=P+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=META))
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K110 deliberate follow-up failure')))
    r.register_card(CardDefinition(P+'spell_double','Spell-only healing doubler',CardType.MINION,health=5,metadata=META,
        health_rules=(HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly',healing_kinds=(HealingKind.SPELL,)),)))
    if mode:
        event='choice_selected'if mode=='fill'else'health_resolved'if mode=='fail'else'card_created'
        def eligible(c):
            if mode=='fail':return c.health_result is not None and c.health_result.flow=='healing'and c.health_result.source_card_id==KNIGHT
            return c.event.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==KNIGHT
        def watch(c):
            if mode=='fail':return(InvokeBehavior(P+'fail',c.source_id,1),)
            if mode=='fill':return(Damage(c.state.players[1].hero_id,10,c.source_id),AddToHand(1,YETI,c.source_id))
            tail=()
            if mode=='retire':tail=(Destroy(c.event.source_id,c.source_id),)
            elif mode=='control':tail=(ChangeControl(c.event.source_id,2),)
            elif mode=='hero':tail=(ReplaceHero(1,'HERO_01'),InvokeBehavior(P+'wound_current',c.source_id,1))
            before=(ModifyCost(c.event.target_id,CostSpec(set_to=0),c.source_id),)if mode=='discount'else()
            return(*before,RequestChoice(1,(ChoiceOption('ok','Continue',tail),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id))
        r.register_behavior(P+'watch',watch);r.register_trigger_condition(P+'eligible',eligible);r.register_card(CardDefinition(P+'watch','Actual outcome observer',CardType.MINION,health=5,metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,P+'watch',condition_id=P+'eligible'),)))
    r.validate();return r


def outcomes(value):
    if type(value)is HealHeroFromDiscoveredSpell:yield value;return
    from hs_sim.engine.model import GameState
    if type(value)is GameState:return
    if type(value)in(tuple,list):
        for child in value:yield from outcomes(child)
    elif is_dataclass(value):
        for field in fields(value):yield from outcomes(getattr(value,field.name))


class DiscoveryCostHealTests(unittest.TestCase):
    def game(self,hand=(KNIGHT,),board=(),members=MEMBERS,mode=None,wound=10,hero='HERO_04',pool=True,context=CTX):
        self.config=(members,mode,wound,pool)
        if mode:board=(*board,P+'watch')
        initial=(*((P+'wound',)if wound else()),*hand)
        g=Game.from_scenario(Scenario((PlayerSetup(hero,hand=initial,board=board,deck=(YETI,)*8,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',deck=(YETI,)*8)),seed=110,generation_context=context),registry(*self.config))
        if wound:self.play(g,P+'wound')
        return g
    def play(self,g,cid):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,eid,position=len(g.state.players[1].board)if g.registry.card(cid).kind==CardType.MINION else None));return eid
    def pick(self,g,cid=PALADIN4):
        q=g.state.pending_choice;key=next(x.id for x in q.options if x.card_id==cid);g.apply(SelectChoice(1,q.id,(key,)))
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def heals(self,g):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==KNIGHT and health_result(e).flow=='healing']
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry(*self.config));self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for field in('resolution_frame','rng_state','choice_result','heal_hero_by_printed_cost','pool_id','discovery'):self.assertNotIn('"'+field+'"',public)
        return other

    def test_complete_two_raw_rows_two_official_faces_and_native_core_metadata(self):
        d=load_batch();self.assertEqual(canonical_digest(d),BATCH_HASH);self.assertEqual(len(d['cards']+d['evidence_only']),2);self.assertEqual(len(d['official_observations']['observations']),2);self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated']);r=build_registry();c=r.card(KNIGHT);raw=d['cards'][0]['record'];self.assertEqual((c.cost,c.attack,c.health),(4,4,4));self.assertEqual(c.metadata,replace(metadata_from_record(raw),deck_identity='KAR_057'));self.assertEqual(c.battlecry,BODY);self.assertFalse(any(p.id==POOL_ID or p.mode=='standard'for p in r.pools.values()))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',s)
        for row in d['cards']+d['evidence_only']:self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        for o in d['official_observations']['observations']:
            f=o['face'];en=o['locale']=='en_US';self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(raw['text_en'if en else'text']));self.assertEqual((f['manaCost'],f['attack'],f['health']),(4,4,4))

    def test_only_one_definition_added_and_default311_still_exact(self):
        with patch('hs_sim.cards.discovery_cost_heal_cards.register_discovery_cost_heal_cards',lambda r:None):before=build_registry()
        after=build_registry();self.assertEqual(set(after.cards)-set(before.cards),{KNIGHT});self.assertTrue(all(asdict(before.card(cid))==asdict(after.card(cid))for cid in before.cards));self.assertEqual(dict(before.pools),dict(after.pools))
        from hs_sim.engine.representative import build_registry as default
        d=default();self.assertEqual(len(d.cards),311);self.assertEqual(d.fingerprint(),'e0322da10db3dcf3296bbaca5a8f583091f92b65fa43c334d836d8a0ffd0e667')

    def test_finite_healing_declaration_rejects_wrong_types_and_unrequested_shapes(self):
        base=DiscoverFromPool(1,POOL_ID,PoolQuery(kinds=(CardType.SPELL,),collectible=True),source_id=1,heal_hero_by_printed_cost=True)
        for changes in({'heal_hero_by_printed_cost':1},{'source_id':None},{'query':None},{'query':PoolQuery(kinds=(CardType.MINION,),collectible=True)},{'destination':'deck'},{'delivery':'after_all'},{'discoveries':2},{'count':2},{'replacement':False},{'cost':CostSpec(delta=-1)},{'expires_turn':1}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(base,**changes)
        self.assertFalse(DiscoverFromPool(1,POOL_ID).heal_hero_by_printed_cost)

    def test_paid_native_discovery_selects_spell_then_heals_once_by_printed_cost(self):
        g=self.game();source=self.play(g,KNIGHT);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,20);self.assertEqual({o.card_id for o in g.state.pending_choice.options},{PALADIN4,LIGHT});self.assertFalse(self.heals(g));self.pick(g);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);result,=self.heals(g);self.assertEqual((result.base_amount,result.healed,result.healing_kind),(4,4,'effect'));self.assertEqual(result.source_id,source);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)

    def test_pool_query_uses_current_hero_class_and_excludes_minions_and_noncollectible(self):
        g=self.game(hero='HERO_08');self.play(g,KNIGHT);self.assertEqual({x.card_id for x in g.state.pending_choice.options},{FIRE});self.pick(g,FIRE);self.assertEqual(self.heals(g)[0].base_amount,4)

    def test_zero_cost_spell_is_selected_and_has_no_positive_healing(self):
        g=self.game(hero='HERO_06',members=(ZERO,));self.play(g,KNIGHT);self.pick(g,ZERO);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,20);self.assertTrue(all(x.base_amount==x.healed==0 for x in self.heals(g)));self.assertIn(ZERO,[g.state.entities[i].card_id for i in g.state.players[1].hand])

    def test_natural_summon_neither_discovers_nor_heals_without_context(self):
        g=self.game((P+'summon',),pool=False,context=None);self.play(g,P+'summon');self.assertIsNone(g.state.pending_choice);self.assertFalse(self.heals(g));self.assertFalse(g.state.battlecry_history)

    def test_empty_and_short_pools_keep_native_no_selection_or_one_selection(self):
        g=self.game(members=());self.play(g,KNIGHT);self.assertIsNone(g.state.pending_choice);self.assertFalse(self.heals(g));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,20)
        g=self.game(members=(PALADIN4,));self.play(g,KNIGHT);self.assertEqual(len(g.state.pending_choice.options),1);self.pick(g);self.assertEqual(len(self.heals(g)),1)

    def test_eligible_unknowns_and_missing_context_fail_before_rng_and_roll_back(self):
        for members,context,pool in((*MEMBERS,UNKNOWN),CTX,True),(MEMBERS,None,True),(MEMBERS,CTX,False):
            with self.subTest(context=context,pool=pool,members=len(members)):
                g=self.game(members=members,context=context,pool=pool);saved=g.snapshot()
                with patch.object(random.Random,'randrange',side_effect=AssertionError('RNG before candidate validation'))as calls:
                    with self.assertRaises((ResolutionError,ValueError)):self.play(g,KNIGHT)
                    calls.assert_not_called()
                self.assertEqual(g.snapshot(),saved)

    def test_discovery_waiting_restore_clone_and_independent_replay(self):
        g=self.game();self.play(g,KNIGHT);other=self.portable(g);rng=g._rng.getstate();self.pick(g);self.pick(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g._rng.getstate(),rng)

    def test_acquisition_reactions_finish_before_healing_and_source_can_retire(self):
        g=self.game(mode='retire');source=self.play(g,KNIGHT);self.pick(g);self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.heals(g));self.assertTrue(tuple(outcomes(g._frame)));other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.choose(other);self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);self.portable(g)

    def test_creation_discount_does_not_replace_the_selected_printed_cost(self):
        g=self.game(mode='discount');self.play(g,KNIGHT);self.pick(g);new=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==PALADIN4);self.assertEqual(g.quote_cost(new).amount,0);self.assertFalse(self.heals(g));self.choose(g);self.assertEqual(self.heals(g)[0].base_amount,4);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24)

    def test_source_control_change_still_heals_original_actor(self):
        g=self.game(mode='control');source=self.play(g,KNIGHT);self.pick(g);self.choose(g);self.assertEqual(g.state.entities[source].controller,2);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,30)

    def test_hero_change_after_selection_uses_original_offer_and_current_actor_hero(self):
        g=self.game(mode='hero');self.play(g,KNIGHT);self.pick(g);self.choose(g);hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual(hero.card_id,'HERO_01');self.assertEqual(hero.health,14);result,=self.heals(g);self.assertEqual((result.health_before,result.healed),(10,4));self.assertEqual(result.target_id,hero.id);self.portable(g)

    def test_full_hand_burn_does_not_cancel_selected_spell_healing(self):
        g=self.game((KNIGHT,)+(YETI,)*9,mode='fill',wound=0);source=self.play(g,KNIGHT);self.pick(g);burn,=[e for e in g.events if e.kind=='card_burned'];self.assertEqual(g.state.entities[burn.target_id].card_id,PALADIN4);self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);self.assertEqual(self.heals(g)[0].source_id,source)

    def test_native_heal_cap_and_spell_only_multiplier_apply_correctly(self):
        g=self.game(wound=2,board=(P+'spell_double',));self.play(g,KNIGHT);self.pick(g);result,=self.heals(g);self.assertEqual((result.base_amount,result.healed,result.overheal),(4,2,2));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)

    def test_real_repeated_battlecry_keeps_two_selections_and_one_payment(self):
        g=self.game(board=('TIME_064',));self.play(g,KNIGHT);self.pick(g);self.assertIsNotNone(g.state.pending_choice);self.pick(g);self.assertEqual([x.base_amount for x in self.heals(g)],[4,4]);self.assertEqual(g.state.players[1].mana,46);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,28)

    def test_late_healing_failure_rolls_back_selected_delivery_and_healing(self):
        g=self.game(mode='fail');self.play(g,KNIGHT);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),saved)

    def test_tampered_selected_receipt_and_undeclared_heal_cannot_restore(self):
        g=self.game(mode='wait');self.play(g,KNIGHT);self.pick(g);outcome=next(outcomes(g._frame));codec=FrameCodec(g.mechanics,g.registry);self.assertEqual(codec.decode(codec.encode(outcome)),outcome)
        choice=outcome.discovery.choice_result.choice;bad_result=replace(outcome.discovery.choice_result,choice=replace(choice,player_id=2));bad=replace(outcome,discovery=replace(outcome.discovery,choice_result=bad_result))
        with self.assertRaises(ValueError):codec.decode(codec.encode(bad))
        spec=replace(outcome.discovery.batch.spec,heal_hero_by_printed_cost=False)
        with self.assertRaises(ValueError):replace(outcome,discovery=replace(outcome.discovery,batch=replace(outcome.discovery.batch,spec=spec)))
        saved=deepcopy(g.snapshot())
        def corrupt(value):
            if type(value)is dict:
                if value.get('type')=='hs_sim.engine.discovery.HealHeroFromDiscoveredSpell':value['fields']['context']['fields']['target_id']='wrong-target'
                for item in value.values():corrupt(item)
            elif type(value)is list:
                for item in value:corrupt(item)
        corrupt(saved);saved['state_hash']=canonical_hash({k:v for k,v in saved.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))

    def test_previous_schema322_requires_original_engine(self):
        g=self.game();self.play(g,KNIGHT);saved=g.snapshot();self.assertEqual(saved['schema_version'],SNAPSHOT_SCHEMA_VERSION);self.assertGreaterEqual(SNAPSHOT_SCHEMA_VERSION,323);saved['schema_version']=322
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(*self.config))

if __name__=='__main__':unittest.main()
