"""Real Chromatus entry, ordinary selective removal and retained residencies."""
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.colossal_keyword_loss_cards import CARD, HEADS, FLAGS, ORDER, load_batch
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, Keyword,
    PlayerSetup, PlayCard, Rarity, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GrantKeyword, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Transform, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference, KeywordAuraSpec, LimitedTriggerSpec
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference, RemoveCapturedKeyword
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference

P = 'chromatus.test.'
FILL, WATCH, AURA = (P+x for x in ('fill','watch','aura'))
KILL, SILENCE, BOUNCE, STEAL, TRANSFORM, GRANT, BUFF, COPY, BASE, TRIGGER, SUMMON = (
    P+x for x in ('kill','silence','bounce','steal','transform','grant','buff','copy','base','trigger','summon'))


@lru_cache(maxsize=None)
def registry(mode, role):
    assert role in ('writer','reader')
    r = build_registry()
    meta = CardMetadata(collectible=False,classes=(CardClass.NEUTRAL,),rarity=Rarity.COMMON)
    r.register_card(CardDefinition(FILL,FILL,CardType.MINION,health=30,metadata=meta))
    r.register_card(CardDefinition(AURA,AURA,CardType.MINION,health=30,metadata=meta,
        keyword_auras=(KeywordAuraSpec(Keyword.TAUNT,'friendly_minions'),)))
    def copied(c,kind):
        return (CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,
            mode=kind,cause=SummonCause.capture(c)),)
    bodies = {KILL:lambda c:(Destroy(c.target_id,c.source_id),),
        SILENCE:lambda c:(Silence(c.target_id),), BOUNCE:lambda c:(ReturnToHand(c.target_id),),
        STEAL:lambda c:(ChangeControl(c.target_id,2),), TRANSFORM:lambda c:(Transform(c.target_id,FILL),),
        GRANT:lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
        BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
        COPY:lambda c:copied(c,'current'), BASE:lambda c:copied(c,'base'),
        TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)}
    for cid,body in bodies.items():
        def wrapped(c,body=body):
            effects=body(c)
            return (RemoveFromGame((MinionReference.capture(c.source),),c.source_id),*effects)
        r.register_behavior(cid,wrapped)
        r.register_card(CardDefinition(cid,cid,CardType.MINION,health=1,battlecry=cid,
            targeting=TargetSpec(),metadata=meta))
    r.register_behavior(SUMMON,lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(CARD),),SummonCause.capture(c)),))
    r.register_card(CardDefinition(SUMMON,SUMMON,CardType.SPELL,on_play=SUMMON,metadata=meta))
    def fail(c): raise ResolutionError('Chromatus deliberate choice failure')
    def reenter(c): return (SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),1),)
    r.register_behavior(P+'fail',fail); r.register_behavior(P+'reenter',reenter)
    if mode:
        event='minion_summoned' if mode=='entry' else 'keyword_removed'
        def eligible(c):
            e=c.state.entities.get(c.event.target_id)
            return e is not None and e.controller==1 and e.card_id==(ORDER[0] if mode=='entry' else CARD)
        def pause(c):
            bodies=[i for i in c.state.players[1].board if c.state.entities[i].card_id==CARD]
            target=bodies[-1]
            changed=(ReturnToHand(target),) if mode=='entry' else (
                ReturnToHand(target),InvokeBehavior(P+'reenter',c.source_id,1,target))
            return (RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Reenter original',changed),
                ChoiceOption('steal','Change controller',(ChangeControl(target,2),)),
                ChoiceOption('kill','Kill original',(Destroy(target,c.source_id),)),
                ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'pause',pause)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
            limited_triggers=(LimitedTriggerSpec(event,P+'pause',condition_id=P+'eligible'),)))
    r.validate();r.freeze();return r


class ColossalKeywordLossTests(unittest.TestCase):
    def game(self,hand=(),board=(),enemy=(),mode=None):
        self.mode=mode
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(FILL,)*12,mana=50,max_mana=50,mana_cap=50),
            PlayerSetup('HERO_08',board=((WATCH,) if mode else ())+enemy,deck=(FILL,)*12,
                mana=50,max_mana=50,mana_cap=50)),seed=432),registry(mode,'writer'))
    def ids(self,g,cid,pid=1,zone='board'):
        return [i for i in getattr(g.state.players[pid],zone) if g.state.entities[i].card_id==cid]
    def play(self,g,cid,target=None):
        eid=self.ids(g,cid,zone='hand')[0]
        e=g.state.entities[eid]
        g.apply(PlayCard(1,eid,target_id=target,position=len(g.state.players[1].board) if e.kind==CardType.MINION else None))
        return eid
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        r=registry(self.mode,'reader');self.assertIsNot(r,g.registry)
        self.assertEqual(r.fingerprint(),g.registry.fingerprint())
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,r).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),r).snapshot(),snap)
        for p in (1,2):
            visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('colossal_history','resolution_frame','beneficiary','zone_epoch','rng_state'):
                self.assertNotIn('"'+key+'"',visible)
    def test_a00_native_paid_entry_has_five_true_bodies_and_all_four_printed_flags(self):
        g=self.game((CARD,));body=self.play(g,CARD)
        row=g.state.colossal_history[0]
        self.assertEqual(g.state.players[1].mana,42)
        self.assertEqual(tuple(g.state.entities[i].card_id for i in row.limbs),ORDER)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],
            [ORDER[0],ORDER[1],CARD,ORDER[2],ORDER[3]])
        self.assertTrue(set(FLAGS)<=set(g.state.entities[body].keywords))
        for cid,flag in zip(HEADS,FLAGS):
            e=g.state.entities[self.ids(g,cid)[0]]
            self.assertEqual((e.attack,e.max_health),(2,3));self.assertIn(flag,e.keywords)
        self.portable(g)
    def test_a01_three_existing_minions_omit_green_without_removing_body_taunt(self):
        g=self.game((CARD,),board=(FILL,)*3);body=self.play(g,CARD)
        self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(self.ids(g,HEADS[0]))
        self.assertEqual(g.state.colossal_history[0].limbs[-1],None)
        self.assertTrue(set(FLAGS)<=set(g.state.entities[body].keywords));self.portable(g)
    def test_a02_six_existing_minions_preserve_all_body_keywords_without_heads(self):
        g=self.game((CARD,),board=(FILL,)*6);body=self.play(g,CARD)
        self.assertEqual(g.state.colossal_history[0].limbs,(None,)*4)
        self.assertTrue(set(FLAGS)<=set(g.state.entities[body].keywords));self.portable(g)
    def test_b00_each_real_head_death_removes_only_its_flag(self):
        for cid,flag in zip(HEADS,FLAGS):
            with self.subTest(head=cid):
                g=self.game((KILL,),board=(CARD,cid));body=self.ids(g,CARD)[0]
                self.play(g,KILL,self.ids(g,cid)[0])
                self.assertEqual(set(FLAGS)&set(g.state.entities[body].keywords),set(FLAGS)-{flag})
                self.assertEqual((g.state.entities[body].attack,g.state.entities[body].max_health),(8,8))
        self.portable(g)
    def test_b01_silencing_head_prevents_its_deathrattle(self):
        g=self.game((SILENCE,KILL),board=(CARD,HEADS[0]));head=self.ids(g,HEADS[0])[0]
        self.play(g,SILENCE,head);self.play(g,KILL,head)
        self.assertIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD)[0]].keywords);self.portable(g)
    def test_b02_bouncing_or_transforming_head_is_not_its_death(self):
        for tool in (BOUNCE,TRANSFORM):
            g=self.game((tool,),board=(CARD,HEADS[0]));self.play(g,tool,self.ids(g,HEADS[0])[0])
            self.assertIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD)[0]].keywords)
            self.assertFalse(g.state.death_history)
        self.portable(g)
    def test_b03_natural_death_uses_head_death_controller(self):
        g=self.game((STEAL,KILL),board=(CARD,HEADS[0]),enemy=(CARD,))
        head=self.ids(g,HEADS[0])[0];self.play(g,STEAL,head);self.play(g,KILL,head)
        self.assertIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD)[0]].keywords)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD,2)[0]].keywords);self.portable(g)
    def test_b04_current_friendly_named_bodies_do_not_require_an_invented_parent_link(self):
        g=self.game((KILL,),board=(CARD,CARD,HEADS[0]),enemy=(CARD,))
        self.play(g,KILL,self.ids(g,HEADS[0])[0])
        self.assertTrue(all(Keyword.TAUNT not in g.state.entities[i].keywords for i in self.ids(g,CARD)))
        self.assertIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD,2)[0]].keywords);self.portable(g)
    def test_b05_head_without_friendly_named_body_does_not_touch_enemy(self):
        g=self.game((KILL,),board=(HEADS[0],),enemy=(CARD,));self.play(g,KILL,self.ids(g,HEADS[0])[0])
        self.assertIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD,2)[0]].keywords);self.portable(g)
    def test_b06_body_transformation_does_not_retarget_a_different_card(self):
        g=self.game((TRANSFORM,KILL),board=(CARD,HEADS[0]));body=self.ids(g,CARD)[0]
        self.play(g,TRANSFORM,body);self.play(g,KILL,self.ids(g,HEADS[0])[0])
        self.assertEqual((g.state.entities[body].card_id,g.state.entities[body].max_health),(FILL,30));self.portable(g)
    def test_c00_duplicate_taunt_is_removed_without_stat_or_other_keyword_loss(self):
        g=self.game((GRANT,BUFF,KILL,GRANT),board=(CARD,HEADS[0]));body=self.ids(g,CARD)[0]
        self.play(g,GRANT,body);self.play(g,BUFF,body);self.play(g,KILL,self.ids(g,HEADS[0])[0])
        e=g.state.entities[body];self.assertNotIn(Keyword.TAUNT,e.keywords)
        self.assertEqual((e.attack,e.max_health),(10,11));self.assertTrue(set(FLAGS[1:])<=set(e.keywords))
        self.play(g,GRANT,body);self.assertIn(Keyword.TAUNT,g.state.entities[body].keywords);self.portable(g)
    def test_c01_current_copy_retains_removed_flag_but_base_copy_has_printed_flag(self):
        for tool,expected in ((COPY,False),(BASE,True)):
            g=self.game((KILL,tool),board=(CARD,HEADS[0]));original=self.ids(g,CARD)[0]
            self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.play(g,tool,original)
            copy=next(i for i in self.ids(g,CARD) if i!=original)
            self.assertEqual(Keyword.TAUNT in g.state.entities[copy].keywords,expected)
            self.assertEqual(len(g.state.colossal_history),1)
            self.portable(g)
    def test_c02_bounce_and_paid_reentry_restore_printed_body_flag(self):
        g=self.game((KILL,BOUNCE),board=(CARD,HEADS[0]));body=self.ids(g,CARD)[0]
        self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.play(g,BOUNCE,body);self.play(g,CARD)
        self.assertIn(Keyword.TAUNT,g.state.entities[body].keywords);self.portable(g)
    def test_c03_attributed_summon_expands_without_inventing_battlecry(self):
        g=self.game((SUMMON,));self.play(g,SUMMON)
        self.assertEqual(len(g.state.colossal_history),1);self.assertEqual(len(g.state.players[1].board),5)
        self.assertFalse(g.state.battlecry_history);self.portable(g)
    def test_c04_manual_head_deathrattle_removes_flag_without_killing_head(self):
        g=self.game((TRIGGER,),board=(CARD,HEADS[0]));head=self.ids(g,HEADS[0])[0]
        self.play(g,TRIGGER,head);self.assertEqual(g.state.entities[head].zone,Zone.BOARD)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[self.ids(g,CARD)[0]].keywords);self.portable(g)
    def test_c05_attributed_current_copy_restores_between_its_own_appendages(self):
        g=self.game((KILL,COPY),board=(CARD,HEADS[0]),mode='entry');original=self.ids(g,CARD)[0]
        self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.play(g,COPY,original)
        self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
        copied=next(i for i in self.ids(g,CARD) if i!=original)
        self.assertNotIn(Keyword.TAUNT,g.state.entities[copied].keywords)
        row=g.state.colossal_history[0];self.assertEqual(row.entity_id,copied)
        self.assertEqual((row.reason,row.origin_id,row.copy_mode),('copy',original,'current'))
        self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)
    def test_d00_pending_entry_restores_and_body_departure_cancels_later_heads(self):
        g=self.game((CARD,),mode='entry');body=self.play(g,CARD);self.assertIsNotNone(g.state.pending_choice)
        self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'change')
        row=g.state.colossal_history[0];self.assertTrue(row.completed and row.canceled)
        self.assertEqual(row.attempted,1);self.assertEqual(g.state.entities[body].zone,Zone.HAND);self.portable(g)
    def test_d01_pending_second_removal_does_not_follow_same_entity_reentry(self):
        g=self.game((KILL,),board=(CARD,CARD,HEADS[0]),mode='removal');bodies=self.ids(g,CARD)
        self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved);self.choose(g,'change')
        self.assertNotIn(Keyword.TAUNT,g.state.entities[bodies[0]].keywords)
        self.assertIn(Keyword.TAUNT,g.state.entities[bodies[1]].keywords);self.portable(g)
    def test_d02_pending_second_removal_does_not_follow_control_transfer(self):
        g=self.game((KILL,),board=(CARD,CARD,HEADS[0]),mode='removal');target=self.ids(g,CARD)[-1]
        self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.choose(g,'steal')
        self.assertEqual(g.state.entities[target].controller,2)
        self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords);self.portable(g)
    def test_e00_independent_aura_survives_ordinary_flag_consumption(self):
        g=self.game((KILL,KILL),board=(CARD,HEADS[0],AURA));body=self.ids(g,CARD)[0]
        self.play(g,KILL,self.ids(g,HEADS[0])[0]);self.assertIn(Keyword.TAUNT,g.state.entities[body].keywords)
        self.play(g,KILL,self.ids(g,AURA)[0]);self.assertNotIn(Keyword.TAUNT,g.state.entities[body].keywords);self.portable(g)
    def test_z00_complete_sources_and_selective_keyword_request_limits(self):
        data=load_batch();self.assertEqual(len(data['official_observations']),10)
        self.assertEqual(tuple(x['record']['id'] for x in data['dependencies']),HEADS)
        ref=MinionReference(3,1,CARD,1,1)
        for flag in FLAGS:RemoveCapturedKeyword(ref,flag)
        for flag in (Keyword.COLOSSAL,Keyword.REBORN,'taunt',None):
            with self.assertRaises(ValueError):RemoveCapturedKeyword(ref,flag)


if __name__=='__main__':unittest.main()
