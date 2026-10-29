"""Complete declared source and real old effects; no coverage-filtered pools."""
from copy import deepcopy
from dataclasses import asdict,replace
from functools import lru_cache
import json,unittest
from pathlib import Path
from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata
from hs_sim.cards import build_registry,past_druid_nature_source as native
from hs_sim.cards.simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES
from hs_sim.engine.representative import build_registry as representative
from hs_sim.engine import EndTurn,Game,PlayCard,PlayerSetup,ResolutionError,Scenario
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,DestroyBatch,Draw,
    InvokeBehavior,RandomDamage,RequestChoice,Silence,Transform)
from hs_sim.engine.health_outcomes import result_from_payload
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardClass,CardDefinition,CardType,HealingKind,Keyword,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolMember,resolve_candidates
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import TargetValidationError,canonical_digest

P='k664.'
PLAIN,HURT,DRAW,KILL,KILLALL,GIVE,SILENCE,FAULT=(P+x for x in('plain','hurt','draw','kill','killall','give','silence','fault'))
OLD=('CS2_009','EX1_154','EX1_158','EX1_158t','EX1_169','WW_823','CS2_007','EX1_164')
OUT=Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k664-druid-nature-source'


@lru_cache(1)
def original():return build_registry()


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


@lru_cache(None)
def fixture(role='writer'):
    full=original();r=representative(metadata_overrides=(('EX1_158t',full.card('EX1_158t').metadata),))
    # Supply the current token metadata through the existing builder override.
    # All eight physical faces must equal the actual constructed definitions.
    for cid in OLD:
        assert asdict(r.card(cid))==asdict(full.card(cid)),cid
    r.register_card(CardDefinition(PLAIN,PLAIN,CardType.MINION,cost=1,attack=2,health=8,
        metadata=metadata(tribes=())))
    r.register_behavior(FAULT,lambda c:(_ for _ in ()).throw(ValueError('K664 deliberate rollback')))
    bodies={HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        DRAW:lambda c:(Draw(c.player_id,1,c.source_id),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        KILLALL:lambda c:(DestroyBatch(tuple(c.state.players[c.player_id].board),c.source_id),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),SILENCE:lambda c:(Silence(c.target_id),)}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(collectible=False,tribes=()),
            **({'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in(KILL,GIVE,SILENCE)else{})))
    for kind,event in(('grant','ability_granted'),('draw','card_drawn'),('heal','healed')):
        cid=P+'watch.'+kind
        def watch(c,kind=kind):
            source=c.state.entities.get(c.event.source_id)
            expected={'grant':'EX1_158','draw':'EX1_154','heal':'WW_823'}[kind]
            if source is None or source.card_id!=expected:return()
            options=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(FAULT,c.source_id,c.player_id)))]
            if kind=='grant':
                targets=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==PLAIN]
                if targets:
                    last=targets[-1]
                    options.extend((ChoiceOption('transform','Transform remaining',(Transform(last,'EX1_158t'),)),
                        ChoiceOption('control','Transfer remaining',(ChangeControl(last,3-c.player_id),))))
            return(RequestChoice(c.player_id,tuple(options),c.source_id),)
        r.register_behavior(cid,watch)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=(TriggerSpec(event,cid),),
            metadata=metadata(collectible=False,tribes=())))
    r.validate();return r


class DruidNatureSourceTests(CardBatchTestMixin,unittest.TestCase):
    mode='small'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(PLAIN,)*20,watch=None,mana=10,maximum=10):
        self.mode='small'
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board+((P+'watch.'+watch,)if watch else()),
            deck=deck,mana=mana,max_mana=maximum),PlayerSetup('HERO_08',board=enemy,deck=(PLAIN,)*20)),seed=664),fixture())

    def actual_host(self,hand,*,hero='HERO_06',board=(WO,),other_hand=(),seed=18):
        self.mode='host';h=host();deck=('CORE_EX1_169',)*25
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('HERO_08',hand=other_hand,deck=deck,mana=10,max_mana=10)),seed=seed,generation_context=h.context),h.registry)

    def finish(self,g):
        for _ in range(40):
            if g.state.pending_choice is None:return
            q=g.state.pending_choice;keys=[o.id for o in q.options]
            self.choose(g,'continue'if 'continue'in keys else keys[0])
        self.fail('Unbounded diagnostic continuation')

    def cycle(self,g):
        for _ in range(2):g.apply(EndTurn(g.state.active_player));self.finish(g)

    def ids(self,g,zone='board',player=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]

    def wrath(self,g,branch,target):
        e=self.entity(g,'EX1_154');g.apply(PlayCard(1,e.id,target,branch_id=branch));return e.id

    def test_full_85_raw_identities_native_pins_and_five_metadata_additions(self):
        d=native.load_batch();r=original()
        self.assertEqual((len(d['member_records']),len(d['native_pins']),len(d['official_observations'])),(85,85,16))
        self.assertEqual(d['metadata_ids'],list(native.METADATA_IDS));self.assertFalse(d['new_standard_roots'])
        self.assertEqual(native.checked_metadata(r,d),())
        self.assertNotIn('EX1_158t',r.pool_cards)
        for row in d['existing_dependencies']:
            self.assertEqual(canonical_digest(asdict(r.card(row['record']['id']))),row['definition_sha256'])
        self.assertFalse(d['formal_pool_complete']);self.assertFalse(d['cn_calibrated'])

    def test_full_host_85_ordered_candidates_and_original_unit_weights(self):
        h=host();d=native.load_batch();pool=h.registry.pool(NATURE_PAST_POOL,h.context)
        values=resolve_candidates(h.registry,h.context,pool.id,QUERIES[WO],current_class=CardClass.DRUID,
            source_card_id=WO,exclude_source_by_rule=True)
        self.assertEqual([x.card_id for x in values],d['member_ids'])
        self.assertEqual([x.weight for x in values],[1]*85)
        self.assertEqual(pool.members[:85],tuple(PoolMember(cid)for cid in d['member_ids']))
        self.assertEqual(pool.members[85:],(PoolMember('TSC_209'),))
        self.assertTrue(set(native.METADATA_IDS)<=set(x.card_id for x in values))

    def test_source_registration_rejects_cropped_reweighted_reordered_or_borrowed_pool(self):
        h=host();pool=h.registry.pool(NATURE_PAST_POOL,h.context)
        class Proxy:
            def __getattr__(self,name):return getattr(h.registry,name)
            def pool(self,*args):return self.changed
        for patch in ({'members':pool.members[:-1]}, {'members':tuple(reversed(pool.members))},
                {'members':(replace(pool.members[0],weight=2),)+pool.members[1:]},
                {'complete':False},{'version':'borrowed'},{'target_id':'another-context'}):
            with self.subTest(patch=tuple(patch)):
                p=Proxy();p.changed=replace(pool,**patch)
                from hs_sim.cards.past_priest_nature_source import local_pool
                with self.assertRaises(TargetValidationError):native.register_scope(p,h.context,reviewed_pool=local_pool(h.registry,h.context))

    def test_metadata_late_member_failure_installs_nothing_and_never_crops_domain(self):
        r=original();last=native.load_batch()['member_ids'][-1];calls=[]
        class Proxy:
            pool_cards={k:v for k,v in r.pool_cards.items()if k not in native.METADATA_IDS}
            def __getattr__(self,name):return getattr(r,name)
            def card(self,cid):return replace(r.card(cid),cost=r.card(cid).cost+1)if cid==last else r.card(cid)
            def register_pool_card(self,row):calls.append(row)
        with self.assertRaises(TargetValidationError):native.register_past_druid_nature_metadata(Proxy())
        self.assertEqual(calls,[])

    def test_mark_real_two_three_and_taunt_survive_spell_source_leaving(self):
        g=self.game(('CS2_009',),board=(PLAIN,));target=g.state.players[1].board[0]
        source=self.play(g,'CS2_009',target);e=g.state.entities[target]
        self.assertEqual((e.attack,e.health),(4,11));self.assertIn(Keyword.TAUNT,e.keywords)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

    def test_wrath_all_real_branches_damage_draw_and_original_source(self):
        for branch,damage,count in(('damage',3,0),('draw',1,1),('both',4,1)):
            with self.subTest(branch=branch):
                g=self.game(('EX1_154',),enemy=(PLAIN,),board=('OG_044',)if branch=='both'else())
                target=g.state.players[2].board[0]
                source=self.wrath(g,branch,target)
                self.assertEqual(g.state.entities[target].health,8-damage)
                self.assertEqual(len(g.state.draw_history),count)
                if count:self.assertEqual(g.state.draw_history[-1].source_id,source)
                self.assertEqual(g.state.players[1].mana,8)

    def test_wrath_original_draw_notice_wait_restores_and_failed_resume_rolls_back(self):
        g=self.game(('EX1_154',),enemy=(PLAIN,),watch='draw');target=g.state.players[2].board[0]
        source=self.wrath(g,'draw',target);self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.draw_history[-1].source_id,source);self.portable(g)
        before=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.finish(g)

    def test_forest_stacks_actual_treants_without_replacing_old_body_or_token(self):
        g=self.game(('EX1_158','EX1_158',KILLALL),board=(PLAIN,PLAIN))
        self.play(g,'EX1_158');self.play(g,'EX1_158')
        for eid in g.state.players[1].board:self.assertEqual(len(active_abilities(g.state.entities[eid],'deathrattle')),2)
        self.play(g,KILLALL);self.assertEqual(self.ids(g),['EX1_158t']*4)
        for eid in g.state.players[1].board:self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(2,2))
        self.portable(g)

    def test_forest_silence_removes_grant_and_death_uses_current_controller(self):
        g=self.game(('EX1_158',SILENCE,GIVE,KILLALL,KILL),board=(PLAIN,PLAIN))
        self.play(g,'EX1_158');first,second=g.state.players[1].board
        self.play(g,SILENCE,first);self.play(g,GIVE,second);self.play(g,KILL,second);self.play(g,KILLALL)
        self.assertEqual(self.ids(g),[]);self.assertEqual(self.ids(g,player=2),['EX1_158t'])

    def test_forest_original_group_refs_do_not_follow_transformation_or_control_change(self):
        for operation in('transform','control'):
            with self.subTest(operation=operation):
                g=self.game(('EX1_158',),board=(PLAIN,PLAIN),watch='grant');second=g.state.players[1].board[1]
                self.play(g,'EX1_158');self.assertIsNotNone(g.state.pending_choice)
                self.portable(g);self.choose(g,operation);self.finish(g)
                self.assertEqual(active_abilities(g.state.entities[second],'deathrattle'),())

    def test_forest_pending_grant_failure_preserves_rng_queue_and_first_accepted_attachment(self):
        g=self.game(('EX1_158',),board=(PLAIN,PLAIN),watch='grant');self.play(g,'EX1_158')
        before=deepcopy(g.snapshot());self.assertIsNotNone(g.state.pending_choice)
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(before,g.snapshot());self.finish(g)

    def test_innervate_zero_cost_gives_only_one_temporary_mana_above_cap(self):
        g=self.game(('EX1_169',));self.play(g,'EX1_169');p=g.state.players[1]
        self.assertEqual((p.mana,p.max_mana,p.temporary_mana),(11,10,1))
        g.apply(EndTurn(1));self.assertEqual(g.state.players[1].temporary_mana,0)

    def test_rehydrate_drawn_quickdraw_and_held_normal_heal_are_spell_packets(self):
        g=self.game((HURT,DRAW),deck=('WW_823',)+(PLAIN,)*15)
        self.play(g,HURT);self.play(g,DRAW);source=self.play(g,'WW_823',self.hero(g).id)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(25,10))
        result=result_from_payload(g.state.healing_history[-1].result)
        self.assertEqual((result.source_id,result.healing_kind),(source,HealingKind.SPELL.value))
        g=self.game(('WW_823',HURT));self.play(g,HURT);self.cycle(g)
        self.play(g,'WW_823',self.hero(g).id)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(25,8))

    def test_rehydrate_waiting_keeps_original_quickdraw_reward_after_heal(self):
        g=self.game((HURT,DRAW),deck=('WW_823',)+(PLAIN,)*15,watch='heal')
        self.play(g,HURT);self.play(g,DRAW);self.play(g,'WW_823',self.hero(g).id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,8)
        self.portable(g);self.finish(g);self.assertEqual(g.state.players[1].mana,10)

    def test_other_legacy_healing_touch_is_already_a_real_spell_packet(self):
        g=self.game((HURT,'CS2_007'));self.play(g,HURT);source=self.play(g,'CS2_007',self.hero(g).id)
        self.assertEqual((self.hero(g).health,g.state.players[1].mana),(26,7))
        result=result_from_payload(g.state.healing_history[-1].result)
        self.assertEqual((result.source_id,result.healing_kind),(source,HealingKind.SPELL.value))

    def test_other_legacy_nourish_all_branches_keep_original_draw_source(self):
        for branch,draws,growth in(('mana',0,2),('draw',3,0),('both',3,2)):
            with self.subTest(branch=branch):
                g=self.game(('EX1_164',),mana=8,maximum=8,board=('OG_044',)if branch=='both'else())
                e=self.entity(g,'EX1_164');cost=fixture().card('EX1_164').cost
                g.apply(PlayCard(1,e.id,branch_id=branch));p=g.state.players[1]
                self.assertEqual((p.max_mana,p.mana),(8+growth,8-cost+growth))
                self.assertEqual(len(g.state.draw_history),draws)
                self.assertTrue(all(row.source_id==e.id for row in g.state.draw_history))

    def test_actual_wo_discovers_from_full_85_then_generated_old_mark_really_plays(self):
        g=self.actual_host(('CORE_EX1_169',),board=(WO,'FP1_019t'));self.play(g,'CORE_EX1_169')
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual([o.card_id for o in g.state.pending_choice.options],['DMF_732','CS2_009','SCH_333'])
        opponent=json.dumps(g.for_player(2).observe())
        self.assertNotIn('CS2_009',opponent);self.assertNotIn(NATURE_PAST_POOL,opponent)
        self.portable(g);q=g.state.pending_choice;self.choose(g,next(o.id for o in q.options if o.card_id=='CS2_009'))
        self.assertNotIn('CS2_009',json.dumps(g.for_player(2).observe()))
        target=self.entity(g,'FP1_019t',zone='board').id;before=g.state.entities[target].attack
        self.play(g,'CS2_009',target);self.assertEqual(g.state.entities[target].attack,before+2)
        self.assertIsNotNone(g.state.pending_choice);self.finish(g);self.portable(g)

    def test_actual_wo_other_class_is_explicit_atomic_unbound_view(self):
        g=self.actual_host(('CORE_EX1_169',),hero='HERO_02');before=deepcopy(g.snapshot())
        with self.assertRaises(ResolutionError):self.play(g,'CORE_EX1_169')
        self.assertEqual(g.snapshot(),before)

    def test_actual_wo_opponent_spell_and_source_removed_before_completion_do_not_discover(self):
        g=self.actual_host((),other_hand=('CORE_EX1_169',));g.apply(EndTurn(1))
        self.play(g,'CORE_EX1_169',player=2);self.assertIsNone(g.state.pending_choice)
        g=self.actual_host(('FP1_019',));target=self.entity(g,WO,zone='board').id
        self.play(g,'FP1_019');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)


if __name__=='__main__':unittest.main()
