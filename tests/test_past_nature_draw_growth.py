"""Real past Nature entry points and their original physical/held boundaries."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json, unittest
from pathlib import Path

from card_batch_testkit import CardBatchTestMixin
from opening_fixtures import metadata, registry as opening_registry
from tools import card_batch as batch
from hs_sim.cards import build_registry, past_nature_draw_growth as native
from hs_sim.engine import EndTurn, Game, PlayCard, PlayerSetup, ResolutionError, Ruleset, Scenario
from hs_sim.engine.board_minion_costs import validate_fact
from hs_sim.engine.costs import local_cost, quote_unselected_cost
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Damage, Destroy, DestroyBatch,
    GainArmor, InvokeBehavior, RandomDamage, RequestChoice, Silence)
from hs_sim.engine.hand_progress import progress_ability
from hs_sim.engine.model import (BoardMinionCostRow, CardClass, CardDefinition, CardType,
    CastWhenDrawnSpec, CostSpec, DamageKind, Keyword, SpellSchool, TargetSpec,
    TreantBoardMinionCostSpec, TriggerSpec, Zone)
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup, DrawGroupSlot, DrawGroupReward
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.local_pool_format import build_cn37_local_pool_format
from hs_sim.targets import canonical_digest

P='k662.'
A,B,NAGA,ALL,BOTH,AUTO=(P+x for x in('seven','three','naga','all','both','automatic'))
ARMOR,FOREIGN,NOOP,PORTAL,HURT,ARMOR2,ARMOR6,ARMOR3,MODIFY,KILL,SILENCE,GIVE,DORM,FAULT=(
    P+x for x in('armor','foreign','noop','portal','hurt','armor2','armor6','armor3',
        'modify','kill','silence','give','dormant','fault'))
CTX=GenerationContext('k662-explicit-bounded-test-domain','experimental')
OUT=Path(__file__).resolve().parents[1]/'outputs/card-integration-20261014/k662-past-nature-draw-growth'


@lru_cache(1)
def original(): return build_registry()


@lru_cache(None)
def fixture(mode='normal',role='writer'):
    r=opening_registry();full=original();data=native.load_batch()
    needed={native.CORE_BODY}
    for row in data['existing_dependencies']:
        cid=row['record']['id'];c=full.card(cid)
        for name in('on_play','battlecry','deathrattle','on_use','on_launch','on_awaken'):
            if getattr(c,name,None):needed.add(getattr(c,name))
        needed.update(t.behavior_id for t in c.triggers)
        if c.hand_progress:
            needed.update(x for x in(c.hand_progress.on_progress,c.hand_progress.on_complete)if x)
            cond=c.hand_progress.condition_id
            if cond not in r._trigger_conditions:r.register_trigger_condition(cond,full.trigger_condition(cond))
        r.register_card(c)
        if cid in full.pool_cards:r.register_pool_card(full.pool_card(cid))
    for name in needed:
        if name not in r._behaviors:r.register_behavior(name,full.behavior(name))
    for name,rule in full._target_rules.items():
        if name not in r._target_rules:r.register_target_rule(name,rule)
    native.register_past_nature_draw_growth(r)
    r.register_behavior(NOOP,lambda c:())
    r.register_behavior(FAULT,lambda c:(_ for _ in()).throw(ValueError('K662 deliberate rollback')))
    for cid,cost,tribes,extra in((A,7,(),{}),(B,3,(),{}),(NAGA,1,('naga',),{}),
            (ALL,1,('all',),{}),(BOTH,0,(),dict(choose_both=True)),
            (AUTO,0,(),dict(battlecry=AUTO))):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=2,health=8,
            metadata=metadata(CardClass.DRUID,tribes=tribes),**extra))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    r.register_behavior(ARMOR,lambda c:(GainArmor(c.player_id,1),))
    r.register_behavior(AUTO,lambda c:(CastSpell(c.player_id,ARMOR,c.source_id),))
    for cid,hero in((ARMOR,CardClass.DRUID),(FOREIGN,CardClass.MAGE),(NOOP,CardClass.NEUTRAL),(PORTAL,CardClass.DRUID)):
        kw=dict(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())if cid==PORTAL else{}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=1 if cid==ARMOR else 0,
            on_play=ARMOR if cid==ARMOR else NOOP,spell_school=SpellSchool.NATURE,
            metadata=metadata(hero,tribes=()),**kw))
        r.register_pool_card(PoolCard.from_definition(r.card(cid)))
    def modify(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].deck if c.state.entities[i].card_id==A)
        return(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-2),c.source_id),)+tuple(
            ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(set_to=0),c.source_id)
            for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id=='LOOT_051')
    helpers={HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,12,c.source_id),),
        ARMOR2:lambda c:(GainArmor(c.player_id,2),),ARMOR6:lambda c:(GainArmor(c.player_id,6),),
        ARMOR3:lambda c:(GainArmor(c.player_id,3),),MODIFY:modify,
        KILL:lambda c:(DestroyBatch(tuple(i for p in(1,2)for i in c.state.players[p].board
            if not c.state.entities[i].card_id.startswith(P+'watch.')),c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),),GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        DORM:lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial('MIS_301t',dormant_turns=2),),SummonCause.capture(c)),)}
    for cid,body in helpers.items():
        r.register_behavior(cid,body)
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,
            metadata=metadata(collectible=False,tribes=()),
            **({'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}if cid in(SILENCE,GIVE)else{})))
    for kind,event in(('draw','card_drawn'),('entry','minion_summoned'),('commit','card_committed')):
        cid=P+'watch.'+kind
        def watch(c,kind=kind):
            e=c.event;source=c.state.entities.get(e.source_id)
            if kind=='commit'and(source is None or source.card_id!='DRG_314'):return()
            if kind=='entry':
                target=c.state.entities.get(e.target_id)
                if target is None or target.card_id not in('MIS_301t','SCH_612t',A):return()
            options=[ChoiceOption('continue','Continue'),ChoiceOption('fault','Fail',(
                RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(FAULT,c.source_id,c.player_id)))]
            if kind=='commit':
                targets=[i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id=='MIS_301t']
                if targets:options.append(ChoiceOption('remove','Remove a Treant',(Destroy(targets[0],c.source_id),)))
            return(RequestChoice(e.player_id if e.player_id in(1,2)else c.player_id,tuple(options),c.source_id),)
        r.register_behavior(cid,watch)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,triggers=(TriggerSpec(event,cid),),
            metadata=metadata(collectible=False,tribes=())))
    def fill_discovery(c):
        return (Damage(c.state.players[c.player_id].hero_id,12,c.source_id),
            AddToHand(c.player_id,B,c.source_id))
    cid=P+'watch.discovery';r.register_behavior(cid,fill_discovery)
    r.register_card(CardDefinition(cid,cid,CardType.MINION,health=30,
        triggers=(TriggerSpec('choice_requested',cid),),metadata=metadata(collectible=False,tribes=())))
    members=[ARMOR,FOREIGN,A]
    if mode=='empty':members=[FOREIGN,A]
    elif mode=='unknown':
        cid=P+'unimplemented'
        r.register_pool_card(PoolCard(cid,CardType.SPELL,1,metadata(CardClass.DRUID,tribes=())))
        members=[cid,FOREIGN,A]
    r.register_pool(PoolDefinition('constructed.cards','k662-bounded-'+mode,CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in members),complete=True))
    r.validate();return r


@lru_cache(None)
def host(role='writer'):return build_cn37_local_pool_format()


class NatureDrawGrowthTests(CardBatchTestMixin,unittest.TestCase):
    mode='normal'
    registry_factory=staticmethod(lambda mode,role:host(role).registry if mode=='host'else fixture(mode,role))

    def game(self,hand=(),*,board=(),enemy=(),deck=(A,)*12,other_hand=(),watch=None,player=1,mode='normal',mana=40):
        self.mode=mode
        own=PlayerSetup('mage.hero',hand=hand,board=board+((P+'watch.'+watch,)if watch else()),
            deck=deck,mana=mana,max_mana=40,mana_cap=40)
        other=PlayerSetup('mage.hero',hand=other_hand,board=enemy,deck=(B,)*12,mana=40,max_mana=40,mana_cap=40)
        return Game.from_scenario(Scenario((own,other)if player==1 else(other,own),active_player=player,
            seed=662,generation_context=CTX),fixture(mode))

    def ids(self,g,zone,player=1):return[g.state.entities[i].card_id for i in getattr(g.state.players[player],zone)]

    def hero(self,g,player=1):return g.state.entities[g.state.players[player].hero_id]

    def pick(self,g,cid=None):
        q=g.state.pending_choice;opt=q.options[0]if cid is None else next(o for o in q.options if o.card_id==cid or o.id==cid)
        self.choose(g,opt.id)

    def finish(self,g):
        for _ in range(60):
            if g.state.pending_choice is None:return g
            keys=[o.id for o in g.state.pending_choice.options]
            self.choose(g)if 'continue'in keys else self.pick(g)
        self.fail('Unexpected unbounded diagnostic choices')

    def branch(self,g,cid,branch):g.apply(PlayCard(g.state.active_player,self.entity(g,cid,g.state.active_player).id,branch_id=branch))

    def cycle(self,g):
        g.apply(EndTurn(g.state.active_player));self.finish(g)
        g.apply(EndTurn(g.state.active_player));self.finish(g)

    def test_complete_fifty_seven_rows_36_faces_and_preserved_shared_choices(self):
        d=native.load_batch();r=fixture()
        self.assertEqual(sum(len(d[k])for k in('cards','dependencies','existing_dependencies','evidence_only')),57)
        self.assertEqual((len(d['official_observations']),len(d['unconfirmed_primary_faces'])),(36,10))
        for row in d['cards']+d['dependencies']:
            cid=row['record']['id'];self.assertEqual(canonical_digest(asdict(r.card(cid))),row['definition_sha256'])
            self.assertEqual(cid in r.pool_cards,cid not in native.CHOICES)
        for cid in('REV_311t','REV_311t2'):
            self.assertEqual(r.card(cid),original().card(cid));self.assertNotIn(cid,r.pool_cards)
        old=json.loads((native.BATCH_PATH.parent/'past-summon-prices-v1.json').read_text('utf-8'))
        self.assertEqual(d['treant_member_ids'],old['treant_member_ids']);self.assertEqual(len(d['treant_member_ids']),29)

    def test_exact_jasper_delimiters_keep_both_damage_and_upgrade_rule_numbers(self):
        d=native.load_batch();rows={x['record']['id']:x['record']for x in d['cards']+d['dependencies']}
        for item in d['official_observations']:
            if item['card_id']not in('LOOT_051','LOOT_051t1'):continue
            raw=rows[item['card_id']];batch.check_face(raw,item['face'],item['locale'],{'@':''})
            changed=deepcopy(raw);changed['text_en']=changed['text_en'].replace('damage','bad damage')
            changed['text']=changed['text'].replace('伤害','其他伤害')
            with self.assertRaises(ValueError):batch.check_face(changed,item['face'],item['locale'],{'@':''})
        self.assertTrue(all(not x['official_cn_calibration']for x in d['rule_references']if 'official_cn_calibration'in x))

    def test_aeroponics_uses_full_fixed_identity_not_all_tribes_and_pays_once(self):
        for player in(1,2):
            g=self.game(('DRG_314',),board=('MIS_301t','SCH_612t',ALL),enemy=('MIS_301t',),player=player)
            before=g.state.players[player].mana;self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,'DRG_314',player)).amount,1)
            self.play(g,'DRG_314',player=player)
            p=g.state.play_history[-1];self.assertEqual((before-g.state.players[player].mana,p.cost),(1,1))
            fact=p.submitted_cost.quote.intrinsic.board_minions;self.assertEqual((fact.quantity,fact.before,fact.after),(2,5,1))
            self.assertEqual(sum(map(len,fact.boards)),4);self.assertEqual(len(self.ids(g,'hand',player)),2)

    def test_treant_board_declaration_and_complete_fact_reject_narrowing_unknown_and_forgery(self):
        g=self.game(('DRG_314',),board=('MIS_301t',)*3,enemy=(B,))
        self.play(g,'DRG_314');fact=g.state.play_history[-1].submitted_cost.quote.intrinsic.board_minions
        self.assertEqual((fact.quantity,fact.after),(3,0))
        with self.assertRaises(ValueError):TreantBoardMinionCostSpec(('x','x'))
        with self.assertRaises(ValueError):replace(fact,after=1)
        narrow=replace(fact,spec=TreantBoardMinionCostSpec(('MIS_301t',)))
        with self.assertRaises(ValueError):validate_fact(g.registry,g.registry.card('DRG_314'),narrow)
        bad=replace(fact,boards=(fact.boards[0],(replace(fact.boards[1][0],card_id='unknown.k662'),)))
        with self.assertRaises(ValueError):validate_fact(g.registry,g.registry.card('DRG_314'),bad)

    def test_treant_board_quote_is_pure_and_retains_original_payment_across_wait_and_removal(self):
        g=self.game(('DRG_314',),board=('MIS_301t','MIS_301t'),watch='commit')
        saved=g.snapshot();self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,'DRG_314')).amount,1);self.assertEqual(g.snapshot(),saved)
        self.play(g,'DRG_314');g=self.portable(g);original_cost=g.state.play_history[-1].submitted_cost
        self.choose(g,'remove');self.assertEqual(g.state.play_history[-1].submitted_cost,original_cost)
        self.assertEqual((g.state.play_history[-1].cost,self.ids(g,'board').count('MIS_301t')),(1,1))

    def test_treant_board_counts_dormant_residence_by_the_existing_board_policy(self):
        g=self.game((DORM,'DRG_314','MIS_301'));self.play(g,DORM)
        self.assertFalse(self.entity(g,'MIS_301t',zone='board').active)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.entity(g,'DRG_314')).amount,3)
        before=len(g.state.players[1].hand);self.play(g,'MIS_301')
        self.assertEqual(len(g.state.players[1].hand),before-1+2)

    def test_pendant_discovers_original_physical_minion_and_heals_original_deck_local_cost(self):
        g=self.game((HURT,MODIFY,'DEEP_026'),deck=(A,FOREIGN,A))
        originals=[i for i in g.state.players[1].deck if g.state.entities[i].card_id==A]
        self.play(g,HURT);self.play(g,MODIFY);self.play(g,'DEEP_026')
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{A});self.assertEqual(len(g.state.pending_choice.options),2)
        g=self.portable(g);opt=next(o for o in g.state.pending_choice.options if o.preview.cost==5)
        self.choose(g,opt.id);self.assertIn(originals[0],g.state.players[1].hand)
        self.assertEqual((self.hero(g).health,self.hero(g).armor),(23,0));self.assertFalse(g.state.draw_history)

    def test_pendant_empty_minion_domain_does_not_draw_or_fatigue_and_full_hand_still_heals(self):
        g=self.game(('DEEP_026',),deck=(FOREIGN,));self.play(g,'DEEP_026')
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.draw_history)
        g=self.game(('DEEP_026',)+(B,)*9,deck=(A,),watch='discovery')
        original_id=self.entity(g,A,zone='deck').id;self.play(g,'DEEP_026');self.pick(g,A)
        self.assertEqual(self.hero(g).health,25);self.assertEqual(len(g.state.players[1].hand),10)
        self.assertNotIn(original_id,g.state.players[1].hand);self.assertEqual(g.state.entities[original_id].zone,Zone.GRAVEYARD)

    def test_solar_next_manual_and_automatic_casts_twice_with_one_payment(self):
        for automatic in(False,True):
            g=self.game(('DMF_058',AUTO if automatic else ARMOR));self.play(g,'DMF_058')
            before=g.state.players[1].mana;self.play(g,AUTO if automatic else ARMOR)
            casts=[x for x in g.state.cast_history if x.card_id==ARMOR]
            self.assertEqual((len(casts),self.hero(g).armor),(2,2))
            self.assertEqual(before-g.state.players[1].mana,0 if automatic else 1)

    def test_solar_overlaps_use_max_and_actual_turn_end_expires_unused_budget(self):
        g=self.game(('DMF_058','DMF_058',ARMOR));self.play(g,'DMF_058');self.play(g,'DMF_058');self.play(g,ARMOR)
        self.assertEqual(self.hero(g).armor,2)
        g=self.game(('DMF_058',ARMOR));self.play(g,'DMF_058');self.cycle(g);self.play(g,ARMOR)
        self.assertEqual(self.hero(g).armor,1)

    def test_dew_process_stacks_for_both_players_after_source_leaves_and_restores(self):
        g=self.game(('MAW_024','MAW_024'));self.play(g,'MAW_024');self.play(g,'MAW_024')
        own=len(g.state.players[1].deck);other=len(g.state.players[2].deck)
        self.cycle(g)
        self.assertEqual((own-len(g.state.players[1].deck),other-len(g.state.players[2].deck)),(3,3))
        self.assertEqual(len(g.state.players[1].player_effects),2);self.portable(g)

    def test_beanstalk_counts_current_post_entry_treants_and_full_capacity_still_draws(self):
        g=self.game(('MIS_301',),board=('SCH_612t',ALL),watch='entry');self.play(g,'MIS_301')
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.finish(g)
        self.assertEqual(len(g.state.players[1].hand),2)
        g=self.game(('MIS_301',),board=('MIS_301t',)+(B,)*6);self.play(g,'MIS_301')
        self.assertEqual((len(g.state.players[1].board),len(g.state.players[1].hand)),(7,1))

    def test_nightshade_each_branch_uses_original_deck_entity_without_hand_payment(self):
        g=self.game(('REV_311',),deck=(A,NOOP));eid=self.entity(g,A,zone='deck').id
        self.branch(g,'REV_311','REV_311t2');self.pick(g,A)
        self.assertIn(eid,g.state.players[1].board);self.assertNotIn(eid,g.state.players[1].hand)
        g=self.game(('REV_311',),deck=(ARMOR,A));self.branch(g,'REV_311','REV_311t');self.pick(g,ARMOR)
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana),(1,32))
        self.assertEqual([x.card_id for x in g.state.cast_history],['REV_311',ARMOR])

    def test_nightshade_real_combined_two_discoveries_restore_and_full_board_keeps_original(self):
        g=self.game(('REV_311',),board=(BOTH,),deck=(A,ARMOR))
        self.branch(g,'REV_311','REV_311:combined');g=self.portable(g);self.pick(g,A)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.pick(g,ARMOR)
        self.assertEqual((self.ids(g,'board').count(A),self.hero(g).armor),(1,1))
        g=self.game(('REV_311',),board=(B,)*7,deck=(A,))
        eid=self.entity(g,A,zone='deck').id;self.branch(g,'REV_311','REV_311t2');self.pick(g,A)
        self.assertIn(eid,g.state.players[1].deck);self.assertEqual(len(g.state.players[1].board),7)

    def test_original_convoke_reuses_exact_core_body_and_all_eight_real_casts(self):
        g=self.game(('REV_365',));self.play(g,'REV_365')
        self.assertEqual([x.card_id for x in g.state.cast_history],['REV_365']+[ARMOR]*8)
        self.assertEqual((self.hero(g).armor,g.state.players[1].mana),(8,30))
        self.assertEqual(g.registry.card('REV_365').on_play,g.registry.card('CORE_REV_365').on_play)

    def test_convoke_empty_domain_and_unknown_full_member_are_explicit_and_transactional(self):
        g=self.game(('REV_365',),mode='empty');self.play(g,'REV_365');self.assertEqual(len(g.state.cast_history),1)
        g=self.game(('REV_365',),mode='unknown');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition.*k662.unimplemented'):self.play(g,'REV_365')
        self.assertEqual(g.snapshot(),saved)

    def test_runic_branches_and_fandral_combination_keep_exact_eight_attempts_and_overload(self):
        for branch,rush,owed in(('SCH_612a',False,0),('SCH_612b',True,2)):
            g=self.game(('SCH_612',));self.branch(g,'SCH_612',branch)
            self.assertEqual(len(g.state.players[1].board),4);self.assertEqual(g.state.players[1].overload_owed,owed)
            self.assertTrue(all((Keyword.RUSH in g.state.entities[i].keywords)==rush for i in g.state.players[1].board))
        g=self.game(('SCH_612',),board=(BOTH,));self.branch(g,'SCH_612','SCH_612:combined')
        tokens=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id=='SCH_612t']
        self.assertEqual((len(tokens),sum(Keyword.RUSH in e.keywords for e in tokens)),(6,2))
        self.assertEqual((len(g.state.card_summon_history),g.state.players[1].overload_owed),(8,2))

    def test_compost_multiple_attachments_real_death_group_and_silence(self):
        g=self.game(('SW_437','SW_437',KILL),board=(A,B),watch='draw')
        self.play(g,'SW_437');self.play(g,'SW_437');self.play(g,KILL)
        self.assertIsNotNone(g.state.pending_choice);g=self.portable(g);self.finish(g)
        self.assertEqual(len(g.state.players[1].hand),4)
        g=self.game(('SW_437',SILENCE,KILL),board=(A,));self.play(g,'SW_437')
        self.play(g,SILENCE,self.entity(g,A,zone='board').id);self.play(g,KILL)
        self.assertFalse(g.state.players[1].hand)

    def test_compost_follows_actual_death_controller(self):
        g=self.game(('SW_437',GIVE,KILL),board=(A,));self.play(g,'SW_437')
        self.play(g,GIVE,self.entity(g,A,zone='board').id);self.play(g,KILL)
        self.assertEqual((len(g.state.players[1].hand),len(g.state.players[2].hand)),(0,1))

    def test_jasper_actual_armor_units_upgrade_once_and_clear_only_actual_local_cost(self):
        g=self.game((MODIFY,'LOOT_051',ARMOR2,ARMOR6,ARMOR3),enemy=(A,));self.play(g,MODIFY)
        self.assertEqual(local_cost(self.entity(g,'LOOT_051'))[0],0)
        self.play(g,ARMOR2);self.assertEqual(progress_ability(self.entity(g,'LOOT_051')).progress_value,2)
        self.play(g,ARMOR6);self.assertEqual(self.entity(g,'LOOT_051t1').card_id,'LOOT_051t1')
        self.assertEqual(local_cost(self.entity(g,'LOOT_051t1'))[0],1)
        self.assertEqual(progress_ability(self.entity(g,'LOOT_051t1')).progress_value,0)
        self.play(g,ARMOR3);self.play(g,'LOOT_051t2',self.entity(g,A,2,'board').id)
        self.assertEqual(self.entity(g,A,2,'board').health,2)

    def test_kelp_held_actual_naga_or_all_type_qualifies_and_hero_bonus_expires(self):
        for minion in(NAGA,ALL):
            g=self.game(('TSC_651',minion),enemy=(A,));self.play(g,minion)
            self.play(g,'TSC_651',self.entity(g,A,2,'board').id)
            self.assertEqual((self.entity(g,A,2,'board').health,self.hero(g).attack),(4,4))
            g.apply(EndTurn(1));self.assertEqual(self.hero(g).attack,0)

    def test_kelp_opponent_naga_and_naga_played_before_acquisition_do_not_qualify(self):
        g=self.game((NAGA,),other_hand=('TSC_651',),enemy=(A,),player=2)
        self.play(g,NAGA,player=2);g.apply(EndTurn(2))
        self.play(g,'TSC_651',self.entity(g,A,1,'board').id,player=1)
        self.assertEqual(self.hero(g).attack,0)
        g=self.game((NAGA,),deck=('TSC_651',)+(B,)*10,enemy=(A,));self.play(g,NAGA);self.cycle(g)
        self.play(g,'TSC_651',self.entity(g,A,2,'board').id);self.assertEqual(self.hero(g).attack,0)

    def test_bears_have_native_start_growth_only_in_hand_and_keep_taunt_on_play(self):
        g=self.game(('WORK_024',));self.play(g,'WORK_024');self.assertEqual(self.ids(g,'hand'),['WORK_024t']*2)
        self.cycle(g);bear=self.entity(g,'WORK_024t');self.assertEqual((bear.attack,bear.health),(4,4))
        eid=self.play(g,'WORK_024t');self.assertIn(Keyword.TAUNT,g.state.entities[eid].keywords)
        self.cycle(g);self.assertEqual((g.state.entities[eid].attack,self.entity(g,'WORK_024t').attack),(4,5))

    def test_brochure_actual_faces_flip_then_reward_only_original_matching_draws(self):
        g=self.game(('WORK_050',),deck=(A,B,ARMOR));self.play(g,'WORK_050')
        self.assertEqual({e.card_id for i in g.state.players[1].hand for e in(g.state.entities[i],)},{A,B})
        self.assertTrue(all(g.state.entities[i].attack==4 for i in g.state.players[1].hand))
        g=self.game(('WORK_050',),deck=(B,ARMOR,NOOP));g.apply(EndTurn(1));self.assertEqual(self.ids(g,'hand'),['WORK_050t'])
        g.apply(EndTurn(2));self.play(g,'WORK_050t')
        self.assertEqual(local_cost(self.entity(g,ARMOR))[0],0);self.assertEqual(local_cost(self.entity(g,NOOP))[0],0)
        g=self.game(('WORK_050t',),deck=(PORTAL,A));self.play(g,'WORK_050t')
        self.assertEqual(local_cost(self.entity(g,A))[0],7)
        g=self.game(('WORK_050t',),deck=(PORTAL,ARMOR));self.play(g,'WORK_050t')
        self.assertEqual(local_cost(self.entity(g,ARMOR))[0],1)

    def test_original_spell_discount_rejects_other_tutor_shapes(self):
        reward=DrawGroupReward('cost_original_spells',1)
        DrawPhysicalGroup(1,1,(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2,reward)
        for slots in((DrawGroupSlot(),)*2,(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),),
                (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),)*2):
            with self.assertRaises(ValueError):DrawPhysicalGroup(1,1,slots,reward)

    def test_waiting_fault_rolls_back_rng_effects_and_payment_stays_at_original_boundary(self):
        g=self.game(('MIS_301',),watch='entry');self.play(g,'MIS_301');saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K662 deliberate rollback'):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertEqual(g.state.players[1].mana,37)

    def test_full_standard_host_executes_all_thirteen_sources_with_related_waiting_and_replay(self):
        fmt=host();self.mode='host'
        first=('DEEP_026','DMF_058','DRG_314','LOOT_051','MAW_024','MIS_301','TSC_651','WORK_024')
        def make(hand,deck):return Game.from_scenario(Scenario((
            PlayerSetup('HERO_06',hand=hand,board=('OG_044',),deck=deck,mana=60,max_mana=60,mana_cap=60),
            PlayerSetup('HERO_08',board=('ICC_832t4',),deck=('FP1_019t',)*20)),seed=662,generation_context=fmt.context),fmt.registry)
        g=make(first,('FP1_019t',)+('CORE_EX1_169',)*30)
        self.play(g,'DEEP_026');self.pick(g,'FP1_019t');self.play(g,'MAW_024')
        enemy=self.entity(g,'ICC_832t4',2,'board').id;self.play(g,'LOOT_051',enemy);self.play(g,'TSC_651',enemy)
        self.play(g,'MIS_301');self.play(g,'DRG_314');self.play(g,'DMF_058');self.play(g,'WORK_024');self.cycle(g)
        self.portable(g)
        second=('REV_311','REV_365','SCH_612','SW_437','WORK_050')
        g=make(second,('FP1_019t',)*5+('CORE_EX1_169',)*30)
        self.branch(g,'REV_311','REV_311:combined');g=self.portable(g);self.pick(g,'FP1_019t');self.pick(g,'CORE_EX1_169')
        self.play(g,'WORK_050');self.play(g,'SW_437');self.branch(g,'SCH_612','SCH_612:combined')
        self.play(g,'REV_365');self.finish(g)
        self.assertTrue(set(second)<=set(x.card_id for x in g.state.play_history));self.portable(g)


if __name__=='__main__':unittest.main()
