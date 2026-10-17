"""Actual history and native combat batches; explicit complete experimental pools."""
from dataclasses import asdict,replace
from functools import lru_cache
import json,random,re,unittest
from unittest.mock import patch
from registry_identity_fixtures import DEFAULT_REPRESENTATIVE_FINGERPRINT
from hs_sim.cards import build_registry
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.simple_followup_p49_cards import (DECIMATION,KNOCKBACK,SCULLERY,DISCIPLE,WATCHMAN,
    HOUND,SABER,ROOTS,SKIPPED,POOL_ID,load_batch,register_simple_followup_p49_cards)
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,
    PlayerSetup,Ruleset,Scenario,SelectChoice,EndTurn,TargetSpec,UseHandAction,Zone)
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.deck_shuffles import capture_cost,shuffled
from hs_sim.engine.effects import (AddToHand,Buff,ChoiceOption,Damage,Destroy,ForceAttack,
    InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,KindredProfile,LimitedTriggerSpec,RewindSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery,SummonFromPool
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import AddToDeck,CardReference,ModifyStoredCost
from hs_sim.engine.model import CostSpec
from hs_sim.targets import canonical_digest

TEST='p49.test.';YETI='CORE_CS2_182';TWO='CORE_GVG_085';THREE='EDR_781';ONE='CORE_ICC_038';DRAGON='EDR_451'
MEMBERS=(ONE,TWO,THREE,YETI);META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
CONTEXT=GenerationContext('p49-explicit-complete-fixture','experimental')

def batch_registry():
    with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
    present=tuple(i in r.cards for i in ROOTS)
    if not any(present):register_simple_followup_p49_cards(r)
    elif not all(present):raise AssertionError('P49 central assembly must contain the complete supported group')
    register_candidate_pool_metadata(r);r.validate();return r

def registry(members=MEMBERS,mode=None,pool=True):
    r=batch_registry()
    for i in members:
        if i not in r.pool_cards:r.register_pool_card(PoolCard.from_definition(r.card(i)))
    if pool:r.register_pool(PoolDefinition(POOL_ID,'p49-complete-explicit-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(i)for i in members),complete=True))
    def prices(c):
        return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=3),c.source_id)
            for i in c.state.players[1].hand)
    def fill_probe(c):
        return tuple(SummonFromPool(2,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1),
            source_id=c.source_id,cause=SummonCause.capture(c))for _ in range(7))
    def kindred_prepare(c):
        if c.kindred is None or not c.kindred.condition.matched:raise ResolutionError('Probe requires a real matched native Kindred acceptance')
        options=tuple(ChoiceOption(str(i),'Original enemy minion')for i in c.state.players[2].board)
        return(RequestChoice(1,options,c.source_id,min_count=0,max_count=0,sample_size=2,on_select=TEST+'kindred_selected'),)
    def kindred_selected(c):
        if c.kindred is None:raise ResolutionError('Sampled native Kindred group callback lost original activation')
        return()
    scripts={'kill':lambda c:(Destroy(c.target_id,c.source_id),),'discount':prices,
        'hero':lambda c:(Buff(c.state.players[1].hero_id,1,source_id=c.source_id,expires_turn=c.state.turn),),
        'force_hero':lambda c:(ForceAttack(c.state.players[1].hero_id,c.state.players[2].hero_id),),
        'shuffle_two':lambda c:shuffled(c,(AddToDeck(1,YETI,source_id=c.source_id),AddToDeck(1,TWO,source_id=c.source_id))),
        'opponent_shuffle':lambda c:shuffled(c,(AddToDeck(1,YETI,source_id=c.source_id),)),
        'top':lambda c:(AddToDeck(1,YETI,'top',c.source_id),),
        'unknown_shuffle':lambda c:(AddToDeck(1,YETI,source_id=c.source_id),),

        'board_discount':lambda c:(ModifyStoredCost(CardReference.capture(c.state.entities[c.target_id]),CostSpec(set_to=3),c.source_id),),
        'reenter':lambda c:(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.state.entities[c.target_id].controller,cause=SummonCause.capture(c)),),
        'force_pair':lambda c:(ForceAttack(capture_board_presence(c.state,c.state.players[1].board[0]),capture_board_presence(c.state,c.state.players[2].board[0])),),
        'enemy_add':lambda c:(Summon(2,TEST+'beast'),Summon(2,TEST+'beast')),
        'noop':lambda c:(),
        'fail':lambda c:(_ for _ in()).throw(ResolutionError('P49 deliberate continuation failure')),
        'rewind_shuffle':lambda c:()if c.rewind_attempt else shuffled(c,(AddToDeck(1,YETI,source_id=c.source_id),)),
        'split_probe':lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,3),),
        'kindred_prepare':kindred_prepare,'kindred_selected':kindred_selected}
    for name,body in scripts.items():
        r.register_behavior(TEST+name,body);kwargs={}
        if name in('kill','trigger'):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if name=='board_discount':kwargs['targeting']=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')
        if name=='rewind_shuffle':kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        r.register_card(CardDefinition(TEST+name,name,CardType.SPELL,on_play=TEST+name,metadata=META,**kwargs))
    r.register_card(CardDefinition(TEST+'fill_probe','Fixed seven counterexample',CardType.MINION,health=1,
        battlecry=TEST+'fill',metadata=META));r.register_behavior(TEST+'fill',fill_probe)
    r.register_card(CardDefinition(TEST+'beast','Kindred previous-type witness',CardType.MINION,health=1,metadata=replace(META,tribes=('beast',))))
    r.register_card(CardDefinition(TEST+'kindred_probe','Native Kindred transport probe',CardType.MINION,health=4,
        battlecry=TEST+'kindred_wrapper',metadata=replace(META,tribes=('beast','elemental'))))
    r.register_behavior(TEST+'kindred_wrapper',lambda c:());r.register_kindred_profile(KindredProfile(TEST+'kindred_probe','body',
        wrapper=TEST+'kindred_wrapper',prepare=TEST+'kindred_prepare',active=TEST+'noop'))
    if mode:
        def eligible(c):
            e=c.event
            if mode=='watch_damage':return e.player_id==1
            if mode=='defender_reentry':return dict(e.data).get('forced')is True
            if mode=='cancel':return e.source_id==c.state.players[1].hero_id
            if mode=='combat_wait':return dict(e.data).get('forced')is True
            if mode=='death_wait':return e.player_id==1
            return False
        def watch(c):
            if mode=='defender_reentry':return(ReturnToHand(c.event.target_id),InvokeBehavior(TEST+'reenter',c.source_id,1,c.event.target_id))
            if mode=='cancel':return(Destroy(c.event.target_id,c.source_id),)
            return(RequestChoice(1,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',
                (InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
        event={'watch_damage':'damage_dealt','death_wait':'minion_died'}.get(mode,'attack_declared')
        r.register_behavior(TEST+'watch',watch);r.register_trigger_condition(TEST+'eligible',eligible)
        r.register_card(CardDefinition(TEST+'watch','Ordinary original-window witness',CardType.WEAPON if mode=='death_wait'else CardType.MINION,
            **({'durability':5}if mode=='death_wait'else{'health':20}),metadata=META,
            limited_triggers=(LimitedTriggerSpec(event,TEST+'watch',condition_id=TEST+'eligible'),)))
    r.validate();return r

@lru_cache(maxsize=None)
def shared_registry(members,mode,pool):return registry(members,mode,pool)

class SimpleFollowupP49Tests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),enemy_hand=(),members=MEMBERS,mode=None,pool=True,context=CONTEXT,rules=None,mana=50):
        self.config=(members,mode,pool)
        if mode and mode!='death_wait':board=(*board,TEST+'watch')
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=(YETI,)*8,
            mana=mana,max_mana=50,mana_cap=50,weapon_card_id=TEST+'watch'if mode=='death_wait'else None),PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*8,
            mana=50,max_mana=50,mana_cap=50)),seed=4949,generation_context=context),shared_registry(*self.config),rules)
    def first(self,g,cid,zone='hand',p=1):return next(g.state.entities[i]for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid,target=None,side=None,p=1):
        e=self.first(g,cid,p=p);dest=p if side is None else side
        g.apply(PlayCard(p,e.id,target,position=len(g.state.players[dest].board)if e.kind==CardType.MINION else None,board_player_id=side));return e.id
    def choose(self,g,key='ok'):g.apply(SelectChoice(1,g.state.pending_choice.id,(key,)))
    def ids(self,g,p=1):return[g.state.entities[i].card_id for i in g.state.players[p].board]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry(*self.config))
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),registry(*self.config)).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('rng_state','resolution_frame','character_attack_history','pool_id','behavior_id','source_json'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_ten_complete_rows_twenty_full_primary_faces_and_all_typed_metadata(self):
        d=load_batch();r=batch_registry();self.assertEqual((len(d['cards']),len(d['skipped']),len(d['official_observations'])),(4,6,20))
        norm=lambda s:re.sub(r'\s+|<[^>]+>|\[x\]|[$#&_]','',s)
        for row in d['cards']+d['skipped']:
            raw=row['record'];self.assertEqual(canonical_digest(raw),row['record_sha256'])
            observations=[o for o in d['official_observations']if o['card_id']==raw['id']];self.assertEqual(len(observations),2)
            for o in observations:
                f=o['face'];en=o['locale']=='en_US';text=raw['text_en'if en else'text']
                if raw['id']in(DECIMATION,KNOCKBACK,SCULLERY):text=text.replace('@','')
                self.assertEqual(f['name'],raw['name_en'if en else'name']);self.assertEqual(norm(f['text']),norm(text))
                self.assertEqual((f['id'],f['manaCost']),(raw['dbf_id'],raw['cost']))
                self.assertFalse(re.match(r'^[A-Za-z]:',o['response_file']))
            if raw['id']in ROOTS:
                c=r.card(raw['id']);self.assertEqual(c.metadata,metadata_from_record(raw));self.assertEqual(c.cost,raw['cost'])
                self.assertEqual(c.spell_school.value if c.spell_school else None,row['spell_school'])
        self.assertFalse(d['scope']['cn_calibrated']);self.assertFalse(d['scope']['formal_pool_complete'])

    def test_all_old_definitions_pool_rows_families_default_and_native_aura_kept(self):
        with patch('hs_sim.cards.simple_followup_p49_cards.register_simple_followup_p49_cards',lambda r:None):before=build_registry()
        after=batch_registry();self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS))
        for i,c in before.cards.items():self.assertEqual(asdict(c),asdict(after.card(i)))
        self.assertEqual(dict(before.pool_cards),dict(after.pool_cards));self.assertEqual(dict(before.pools),dict(after.pools))
        self.assertEqual(dict(before.generation_families),dict(after.generation_families))
        self.assertEqual(before.card('TTN_851'),after.card('TTN_851'));self.assertEqual(before.card('TIME_019'),after.card('TIME_019'))
        from hs_sim.engine.representative import build_registry as default
        self.assertEqual(default().fingerprint(),DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_decimation_one_original_scene_value_and_spell_power_simultaneous_batch(self):
        g=self.game((DECIMATION,),board=(YETI,),enemy=(YETI,),pool=False,context=None);self.play(g,DECIMATION)
        self.assertEqual(self.first(g,YETI,'board').health,2);self.assertEqual(self.first(g,YETI,'board',2).health,2)
        rows=[r.health_result for r in g.state.damage_history];self.assertTrue(all(r.base_amount==3 for r in rows))
        g=self.game((DECIMATION,),board=('CORE_EX1_012',YETI),enemy=(YETI,),pool=False,context=None);self.play(g,DECIMATION)
        rows=[r.health_result for r in g.state.damage_history];self.assertTrue(all((r.base_amount,r.spell_bonus)==(4,1)for r in rows))
        g=self.game((DECIMATION,),pool=False,context=None);self.play(g,DECIMATION);self.assertFalse(g.state.damage_history)

    def test_decimation_dormant_minion_counts_as_board_presence_without_becoming_a_damage_target(self):
        g=self.game((DECIMATION,),board=(YETI,'BT_004'),enemy=(YETI,),pool=False,context=None)
        dormant=self.first(g,'BT_004','board');self.assertFalse(dormant.active);self.play(g,DECIMATION)
        rows=[r.health_result for r in g.state.damage_history]
        self.assertEqual(len(rows),2);self.assertTrue(all(r.base_amount==4 for r in rows))
        self.assertNotIn(dormant.id,[r.target_id for r in rows])
        self.assertEqual(g.state.entities[dormant.id].health,dormant.health)
        self.assertFalse(g.state.entities[dormant.id].active)



    def test_scullery_uses_complete_actual_hero_combat_history_not_minion_attacks_or_other_turn_counters(self):
        g=self.game((TEST+'hero',SCULLERY));self.play(g,TEST+'hero')
        g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,SCULLERY);self.assertEqual(self.ids(g),[THREE,THREE])
        self.assertEqual(len(g.state.character_attack_history),1);self.assertEqual(g.state.character_attack_history[0].source_kind,CardType.HERO)
        g=self.game((SCULLERY,),board=(YETI,));g.apply(Attack(1,self.first(g,YETI,'board').id,g.state.players[2].hero_id))
        self.play(g,SCULLERY);self.assertEqual(self.ids(g).count(TWO),2)

    def test_scullery_cancelled_hero_declaration_does_not_count_and_forced_hero_producer_explicitly_rejects(self):
        g=self.game((TEST+'hero',SCULLERY),enemy=(YETI,),mode='cancel');self.play(g,TEST+'hero')
        g.apply(Attack(1,g.state.players[1].hero_id,self.first(g,YETI,'board',2).id));row,=g.state.character_attack_history
        self.assertIsNone(row.combat);self.play(g,SCULLERY);self.assertEqual(self.ids(g).count(TWO),2)
        g=self.game((TEST+'hero',TEST+'force_hero'));self.play(g,TEST+'hero');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'requires a minion attacker'):self.play(g,TEST+'force_hero')
        self.assertEqual(g.snapshot(),saved)

    def test_scullery_unknown_eligible_pool_before_random_and_atomic_rollback(self):
        r=batch_registry();unknown=next(c.card_id for c in r.pool_cards.values()if c.card_id not in r.cards
            and c.kind==CardType.MINION and c.cost==2 and c.metadata.collectible)
        g=self.game((SCULLERY,),members=(TWO,unknown));saved=g.snapshot();calls=[];original=random.Random.randrange
        def spy(r,*a,**kw):calls.append(a);return original(r,*a,**kw)
        with patch.object(random.Random,'randrange',autospec=True,side_effect=spy):
            with self.assertRaises(ResolutionError):self.play(g,SCULLERY)
        self.assertFalse(calls);self.assertEqual(g.snapshot(),saved)

    def test_disciple_current_held_dragons_capture_repeat_count_exclude_self_and_requery_after_each_death(self):
        for held,remaining in((0,2),(1,1),(2,0)):
            with self.subTest(held=held):
                g=self.game((DISCIPLE,)+(DRAGON,)*held,enemy=(YETI,YETI,YETI),pool=False,context=None)
                source=self.play(g,DISCIPLE);self.assertEqual(len(g.state.players[2].board),remaining)
                self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.assertEqual(len(g.state.death_history),1+held)
        g=self.game((DISCIPLE,),pool=False,context=None);rng=g._rng.getstate();self.play(g,DISCIPLE);self.assertEqual(g._rng.getstate(),rng)

    def test_disciple_real_death_wait_restore_replay_and_bad_continuation_rolls_back(self):
        g=self.game((DISCIPLE,DRAGON),board=(YETI,YETI),mode='death_wait',pool=False,context=None)
        self.play(g,DISCIPLE);other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.death_history),2)

    def test_watchman_both_play_sides_damage_entered_side_twice_and_only_pays_original_actor(self):
        for side in(1,2):
            with self.subTest(side=side):
                g=self.game((WATCHMAN,),board=(YETI,),enemy=(YETI,),pool=False,context=None)
                source=self.play(g,WATCHMAN,side=side);self.assertEqual(g.state.entities[source].controller,side)
                self.assertEqual(self.first(g,YETI,'board',side).health,3)
                self.assertEqual(self.first(g,YETI,'board',3-side).health,5)
                self.assertEqual(g.state.entities[source].health,4);self.assertEqual((g.state.players[1].mana,g.state.players[2].mana),(48,50))






    def test_real_split_spell_power_immunity_gap_probe_preserves_whole_bone_flurry_missing(self):
        g=self.game((TEST+'split_probe',),board=('CORE_EX1_012',),pool=False,context=None);self.play(g,TEST+'split_probe')
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26)
        root,=g.state.split_damage_history;self.assertEqual((root.quote.spell_bonus,root.quote.budget),(1,4))
        self.assertNotIn('JAIL_445',g.registry.cards)
        raw=next(x['record']for x in load_batch()['skipped']if x['record']['id']=='JAIL_445');self.assertEqual(raw['tags']['349'],1)

    def test_real_fill_seven_probe_does_not_fill_actual_eight_capacity(self):
        g=self.game((TEST+'fill_probe',),members=(ONE,),rules=Ruleset(max_board=8));self.play(g,TEST+'fill_probe')
        self.assertEqual(len(g.state.players[2].board),7);self.assertEqual(g.ruleset.max_board,8)
        self.assertNotIn('TIME_872',g.registry.cards)

    def test_real_native_kindred_sample_callback_drops_required_original_activation(self):
        g=self.game((TEST+'beast',TEST+'kindred_probe'),enemy=(YETI,YETI),pool=False,context=None)
        self.play(g,TEST+'beast');g.apply(EndTurn(1));g.apply(EndTurn(2));saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'callback lost original activation'):self.play(g,TEST+'kindred_probe')
        self.assertEqual(g.snapshot(),saved);self.assertNotIn('DINO_413',g.registry.cards)

    def test_real_shuffle_rewind_gap_rolls_back_retry_instead_of_retiring_diagnostic_insertions(self):
        g=self.game((TEST+'shuffle_two',TEST+'top'),pool=False,context=None)
        self.play(g,TEST+'shuffle_two');self.play(g,TEST+'top');self.assertEqual(capture_cost(g.state,1).quantity,1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,2)
        g=self.game((TEST+'rewind_shuffle',),pool=False,context=None);self.play(g,TEST+'rewind_shuffle');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Insertion names an unknown shuffle operation'):self.choose(g,'retry')
        self.assertEqual(g.snapshot(),saved);self.assertNotIn(KNOCKBACK,g.registry.cards)

    def test_historical_defender_gap_is_now_guarded_through_the_actual_attack_window(self):
        g=self.game((TEST+'force_pair',),board=(YETI,),enemy=(YETI,),mode='defender_reentry',pool=False,context=None)
        old=self.first(g,YETI,'board',2);self.play(g,TEST+'force_pair');current=g.state.entities[old.id]
        self.assertNotEqual(current.board_presence_id,old.board_presence_id)
        self.assertEqual(current.health,5)
        self.assertIn(HOUND,SKIPPED);self.assertIn(SABER,SKIPPED)  # Original P49 deferrals remain historical.
        self.assertIsNotNone(g.registry.card(HOUND).battlecry);self.assertIsNotNone(g.registry.card(SABER).battlecry)

    def test_watchman_first_damage_wave_wait_restore_and_replay_keeps_second_wave_once(self):
        g=self.game((WATCHMAN,),board=(YETI,),mode='watch_damage',pool=False,context=None);self.play(g,WATCHMAN)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'deliberate'):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved)
        for x in(g,other):self.choose(x)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(self.first(g,YETI,'board').health,3)

if __name__=='__main__':unittest.main()
