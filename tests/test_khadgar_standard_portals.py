"""Standard Goldpetal/Imbue/Portal attribution through actual draw casts."""
from copy import deepcopy
import json
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,GenerationContext,
    PlayCard,PlayerSetup,RewindSpec,Scenario,SelectChoice,SnapshotError,TriggerSpec,UseHeroPower,Keyword)
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,Draw,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.zones import AddToDeck

KHAD='CORE_DAL_575';DRAKE='EDR_451';PORTAL='EDR_445pt3';POWER='EDR_445p';YETI='CORE_CS2_182';DRAW='CORE_CS2_023'
CTX=GenerationContext('local-2026-09-23','experimental')


def registry(mode=None):
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())
    r.register_behavior('k26b.draw1',lambda c:(Draw(c.player_id,source_id=c.source_id),))
    r.register_card(CardDefinition('k26b.draw1','Single draw fixture',CardType.SPELL,on_play='k26b.draw1',metadata=meta))
    r.register_behavior('k26b.retry',lambda c:(AddToDeck(c.player_id,PORTAL,position='top',source_id=c.source_id),Draw(c.player_id,source_id=c.source_id)))
    r.register_card(CardDefinition('k26b.retry','Portal retry fixture',CardType.SPELL,on_play='k26b.retry',
        keywords=(Keyword.REWIND,),rewind=RewindSpec(),metadata=meta))
    r.register_behavior('k26b.fail',lambda c:(AddToHand(c.player_id,'missing.k26b'),))
    if mode:
        def watch(c):
            prefix=()
            if mode=='entry':
                roots=c.state.card_summon_history
                if not roots or not roots[-1].deliveries or roots[-1].deliveries[-1].index!=0:return ()
                prefix=tuple(Destroy(i,c.source_id)for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KHAD)
            elif c.state.entities[c.event.target_id].card_id!=PORTAL:return ()
            return (*prefix,RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(
                InvokeBehavior('k26b.fail',c.source_id,c.player_id),))),c.source_id))
        r.register_behavior('k26b.watch',watch)
        r.register_card(CardDefinition('k26b.watch','Portal boundary observer',CardType.MINION,health=8,metadata=meta,
            triggers=(TriggerSpec('minion_summoned'if mode=='entry'else'card_drawn','k26b.watch'),)))
    return r


class KhadgarStandardPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,*,hand=('k26b.draw1',),deck=(PORTAL,YETI,YETI),board=(KHAD,),enemy=(),power=POWER,mode=None,context=CTX):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_04',hand=hand,deck=deck,board=board,hero_power_card_id=power,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup('HERO_08',board=enemy)),seed=4262,generation_context=context),registry(mode)if mode else self.r)
    def play(self,g,cid='k26b.draw1'):
        i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(1,i));return i
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def cards(self,g,zone='board'):return [g.state.entities[i].card_id for i in getattr(g.state.players[1],zone)]
    def portable(self,g):
        s=g.snapshot();other=Game.from_snapshot(s,registry(self.mode));self.assertEqual(other.snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry(self.mode)).snapshot(),s);return other
    def reject(self,s):
        s['events_hash']=canonical_hash(s['events'])
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry(self.mode))

    def test_real_standard_root_installs_power_produces_portals_and_draws_them(self):
        g=self.game(hand=(KHAD,DRAKE,DRAW),deck=(),board=(),power='HERO_04bp')
        self.play(g,KHAD);self.play(g,DRAKE)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,POWER)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(self.cards(g,'deck'),[PORTAL,PORTAL])
        self.play(g,DRAW);self.assertEqual(len(self.cards(g)),6);self.assertEqual(len(g.state.card_summon_history),2)
        self.assertEqual([r.plan.total for r in g.state.card_summon_history],[2,2])
        expected=20-sum(g.registry.card(c).cost for c in (KHAD,DRAKE,DRAW,POWER))
        self.assertEqual(g.state.players[1].mana,expected);self.portable(g)

    def test_drawn_portal_freezes_its_own_cast_and_full_pool_basis(self):
        g=self.game();draw=self.play(g);root=g.state.card_summon_history[0];cause=root.request.cause
        self.assertEqual(cause.source.card_id,PORTAL);self.assertNotEqual(cause.source.entity_id,draw)
        self.assertEqual(cause.origin,'spell_cast');cast=next(c for c in g.state.cast_history if c.id==cause.cast_id)
        self.assertEqual((cast.source_id,cast.card_id),(cause.source.entity_id,PORTAL))
        self.assertEqual(root.plan.total,2);self.assertIsNotNone(root.request.pool_basis)
        self.assertEqual(self.cards(g).count('BRM_004'),2);self.assertEqual(self.cards(g,'hand'),[YETI]);self.portable(g)

    def test_portal_without_quantity_source_still_uses_complete_attribution(self):
        g=self.game(board=());self.play(g);root=g.state.card_summon_history[0]
        self.assertEqual(root.plan.total,1);self.assertEqual(self.cards(g),['BRM_004']);self.portable(g)

    def test_enemy_khadgar_does_not_multiply_casters_portal(self):
        g=self.game(board=(),enemy=(KHAD,));self.play(g)
        self.assertEqual(self.cards(g),['BRM_004']);self.assertEqual(g.state.card_summon_history[0].plan.total,1)

    def test_two_current_sources_multiply_the_one_selected_dragon(self):
        g=self.game(board=(KHAD,KHAD));self.play(g)
        self.assertEqual(g.state.card_summon_history[0].plan.total,4);self.assertEqual(self.cards(g).count('BRM_004'),4)

    def test_full_board_validates_and_skips_without_sampling(self):
        g=self.game(board=(KHAD,)+(YETI,)*6);before=g._rng.getstate();self.play(g)
        root=g.state.card_summon_history[0];self.assertIsNone(root.selected);self.assertEqual(root.status,'skipped')
        self.assertIsNotNone(root.request.pool_basis);self.assertEqual(g._rng.getstate(),before);self.assertEqual(len(self.cards(g)),7)

    def test_one_remaining_slot_retains_second_failed_attempt_and_original_plan(self):
        g=self.game(board=(KHAD,)+(YETI,)*5);self.play(g);root=g.state.card_summon_history[0]
        self.assertEqual(root.plan.total,2);self.assertEqual([d.outcome for d in root.deliveries],['delivered','board_full'])
        self.assertEqual(len(self.cards(g)),7);self.portable(g)

    def test_first_entry_wait_preserves_selected_dragon_after_source_death(self):
        g=self.game(board=(KHAD,'k26b.watch'),mode='entry');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertNotIn(KHAD,self.cards(g));root=g.state.card_summon_history[0]
        self.assertEqual(root.plan.total,2);restored=self.portable(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before)
        for branch in (g,restored):self.choose(branch);self.assertEqual(self.cards(branch).count('BRM_004'),2)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_pre_cast_draw_wait_restores_before_accepting_quantity(self):
        g=self.game(board=(KHAD,'k26b.watch'),mode='draw');self.play(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(g.state.card_summon_history)
        restored=self.portable(g)
        for branch in (g,restored):self.choose(branch);self.assertEqual(self.cards(branch).count('BRM_004'),2)
        self.assertEqual(g.snapshot(),restored.snapshot())

    def test_missing_generation_context_is_explicit_and_rolls_back(self):
        g=self.game(context=None);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_rehashed_wrong_cause_cannot_borrow_the_outer_draw_cast(self):
        g=self.game();draw=self.play(g);s=g.snapshot();cause=s['state']['card_summon_history'][0]['request']['cause']
        cause['source']['entity_id']=draw;self.reject(s)

    def test_queries_do_not_export_full_pool_or_original_cast_operands(self):
        g=self.game();self.play(g);before=g.snapshot()
        for player in (1,2):
            public=json.dumps(g.observe(player))+json.dumps(g.for_player(player).legal_actions())
            for key in ('pool_basis','card_summon_history','summon_quantity','original_rng','source_allocation'):
                self.assertNotIn('"'+key+'"',public)
        self.assertEqual(g.snapshot(),before)

    def test_retry_reuses_cast_number_but_history_keeps_original_physical_cast(self):
        g=self.game(hand=('k26b.retry',),deck=(YETI,));self.play(g,'k26b.retry');old=g.state.card_summon_history[0].request.cause
        restored=self.portable(g)
        for branch in (g,restored):
            q=branch.state.pending_choice;branch.apply(SelectChoice(1,q.id,(next(o.id for o in q.options if 'retry'in o.id),)))
            current=branch.state.card_summon_history[0].request.cause
            self.assertEqual(current.cast_id,old.cast_id);self.assertNotEqual(current.source.entity_id,old.source.entity_id)
            self.assertEqual(self.cards(branch).count('BRM_004'),2)
        self.assertEqual(g.snapshot(),restored.snapshot());self.portable(g)

    def test_rewound_historical_receipt_cannot_borrow_outer_cast_after_rehash(self):
        g=self.game(hand=('k26b.retry',),deck=(YETI,));self.play(g,'k26b.retry');old_root=g.state.card_summon_history[0].id
        q=g.state.pending_choice;g.apply(SelectChoice(1,q.id,(next(o.id for o in q.options if 'retry'in o.id),)))
        s=g.snapshot();changed=0
        for event in s['events']:
            if event['kind']not in ('card_summon_accepted','card_summon_finished'):continue
            data=dict(event['data']);root=json.loads(data['root'])
            if root['id']!=old_root:continue
            root['request']['cause']['cast_id']=1
            data['root']=json.dumps(root,ensure_ascii=False,sort_keys=True,separators=(',',':'));event['data']=list(data.items());changed+=1
        self.assertEqual(changed,2);self.reject(s)
