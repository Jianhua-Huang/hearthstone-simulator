"""Original cast target facts survive actual payload movement and type changes."""
from copy import deepcopy
from dataclasses import replace
import json,re,unittest
from types import SimpleNamespace

from hs_sim.cards import build_registry
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.native_cast_target_cards import FRAGMENT,load_batch
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,
    RewindSpec,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Destroy,Draw,InvokeBehavior,
    RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import RedirectSpellTarget
from hs_sim.engine.model import CastWhenDrawnSpec,SpellRepeatSpec,TargetSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell,CastStoredSpell,validate_target_origins
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CardReference
from hs_sim.targets import canonical_digest

P='k101.';VICTIM=P+'victim';YETI='CORE_CS2_182';CHAR=TargetSpec(zones=(Zone.BOARD,Zone.HERO),kinds=(CardType.MINION,CardType.HERO))


def registry():
    r=build_registry()
    def victim(c):return next(i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id==VICTIM)
    def fragment(c):return next(i for p in(1,2)for i in c.state.players[p].board if c.state.entities[i].card_id==FRAGMENT)
    def to_spell(c):return(TransformStoredCard(CardReference.capture(c.state.entities[c.target_id]),P+'plain',c.source_id),)
    def change(c):return(ReturnToHand(c.target_id),InvokeBehavior(P+'to_spell',c.source_id,c.player_id,c.target_id))
    def wait(c):
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Return original minion and change stored type',change(c)),
            ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
        ),c.source_id),)
    def stored(c):
        e=next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==P+'target')
        return(CastStoredSpell(CardReference.capture(e),c.player_id,c.source_id,targeting='explicit',target_id=victim(c)),)
    scripts={
        'plain':lambda c:(),'target':lambda c:(),'minion':lambda c:(),
        'change':change,'to_spell':to_spell,'kill':lambda c:(Destroy(c.target_id,c.source_id),),'wait':wait,
        'generated':lambda c:(CastSpell(c.player_id,P+'change',c.source_id,targeting='explicit',target_id=victim(c)),),
        'stored':stored,
        'history':lambda c:(RecastSpell(c.player_id,1,c.source_id,targeting='explicit',target_id=victim(c)),),
        'invalid':lambda c:(CastSpell(c.player_id,P+'minion',c.source_id,targeting='explicit',target_id=c.state.players[2].hero_id),),
        'missing':lambda c:(CastSpell(c.player_id,P+'minion',c.source_id),),
        'draw':lambda c:(Draw(c.player_id,source_id=c.source_id),),'portal':lambda c:(),
        'kill_fragment':lambda c:(Destroy(fragment(c),c.source_id),),
        'silence_fragment':lambda c:(Silence(fragment(c)),),
        'give_fragment':lambda c:(ChangeControl(fragment(c),2),),
        'summon_fragment':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(FRAGMENT),),SummonCause.capture(c)),),
        'late_fail':lambda c:(*change(c),InvokeBehavior(P+'fail',c.source_id,c.player_id)),
        'rewind':lambda c:(),
    }
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('Deliberate K101 late failure')))
    targeted={'target','change','kill','wait','late_fail','rewind','kill_fragment','silence_fragment','give_fragment','summon_fragment'}
    for name,body in scripts.items():
        key=P+name;r.register_behavior(key,body);kwargs={}
        if name in targeted:kwargs['targeting']=CHAR
        if name in('minion','portal'):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')
        if name=='portal':kwargs.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        if name=='rewind':kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        r.register_card(CardDefinition(key,name,CardType.SPELL,cost=1,on_play=key,**kwargs))
    r.register_card(CardDefinition(VICTIM,'Original minion',CardType.MINION,attack=1,health=3))
    r.register_card(CardDefinition(P+'repeat','Original repeat',CardType.MINION,health=5,spell_repeats=(SpellRepeatSpec(2,class_mode='any'),)))
    def redirect(c,kind):
        if c.state.entities[c.event.source_id].card_id!=P+'target':return ()
        target=c.state.players[2].hero_id if kind=='hero'else victim(c)
        return(RedirectSpellTarget(dict(c.event.data)['window_id'],target),)
    def start_change(c):
        if c.state.entities[c.event.source_id].card_id!=P+'target':return ()
        return change(replace(c,target_id=c.event.target_id))
    def finish_wait(c):
        if c.state.entities[c.event.source_id].card_id!=P+'target':return ()
        return(RequestChoice(c.player_id,(
            ChoiceOption('continue','Continue',()),
            ChoiceOption('kill','Retire original Fragment',(Destroy(fragment(c),c.source_id),)),
        ),c.source_id),)
    for name,event,body in [('redirect_hero','spell_targeted',lambda c:redirect(c,'hero')),
            ('redirect_minion','spell_targeted',lambda c:redirect(c,'minion')),
            ('start_change','spell_cast_started',start_change),('finish_wait','spell_cast_finished',finish_wait)]:
        r.register_behavior(P+name,body);r.register_card(CardDefinition(P+name,name,CardType.MINION,health=5,triggers=(TriggerSpec(event,P+name),)))
    r.validate();return r


class NativeCastTargetCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(P+'target',),board=(FRAGMENT,),enemy=(VICTIM,),deck=(YETI,)*12,enemy_hand=(),active=1):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,mana=40,max_mana=40,mana_cap=40),
            PlayerSetup('HERO_08',hand=enemy_hand,board=enemy,deck=(YETI,)*12,mana=40,max_mana=40,mana_cap=40)),seed=101,active_player=active),self.r)
    def eid(self,g,cid,p=1,zone='board'):return next(i for i in getattr(g.state.players[p],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,name,target=None):
        cid=name if name==FRAGMENT else P+name;p=g.state.active_player;source=self.eid(g,cid,p,'hand')
        g.apply(PlayCard(p,source,target,len(g.state.players[p].board)if cid==FRAGMENT else None));return source
    def draws(self,g):return[d for d in g.state.draw_history if g.state.entities[d.source_id].card_id==FRAGMENT]if g.state.draw_history else[]
    def choose(self,g,key='continue'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(s,registry())
        self.assertEqual(other.snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        for p in(1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in('target_origin','SourceAllocationFact','cast_history','resolution_frame','recorded_event','next_entity_id'):
                self.assertNotIn('"'+key+'"',public)
        return other
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as raised:Game.from_snapshot(s,registry())
        self.assertNotIn('digest mismatch',str(raised.exception))

    def test_full_source_two_primary_faces_dual_classes_and_complete_metadata(self):
        d=load_batch();raw=d['cards'][0]['record'];self.assertEqual(canonical_digest(raw),d['cards'][0]['record_sha256'])
        self.assertEqual(self.r.card(FRAGMENT).metadata,replace(metadata_from_record(raw),deck_identity=FRAGMENT));self.assertEqual(len(d['official_observations']),2)
        for o in d['official_observations']:
            f=o['face'];cn=o['locale'].startswith('zh');self.assertEqual(f['name'],raw['name'if cn else'name_en'])
            self.assertEqual(re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',f['text']),re.sub(r'\s+|<[^>]+>|\[x\]|[$&_]','',raw['text'if cn else'text_en']))
        self.assertFalse(d['cn_calibrated']);self.assertFalse(d['formal_pool_complete'])

    def test_real_paid_fragment_and_actual_spell_target_draw(self):
        g=self.game((FRAGMENT,P+'target'),board=());source=self.play(g,FRAGMENT)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.players[1].mana),(3,6,36))
        target=self.eid(g,VICTIM,2);self.play(g,'target',target);self.assertEqual(len(self.draws(g)),1)
        self.assertEqual(g.state.cast_history[0].target_origin.kind,CardType.MINION);self.portable(g)

    def test_original_minion_still_qualifies_after_payload_return_and_cross_type_change(self):
        g=self.game((P+'change',));target=self.eid(g,VICTIM,2);self.play(g,'change',target)
        row=g.state.cast_history[0];self.assertEqual((row.target_id,row.target_origin.card_id,row.target_origin.kind,row.target_origin.zone),(target,VICTIM,CardType.MINION,Zone.BOARD))
        self.assertEqual(g.state.entities[target].kind,CardType.SPELL);self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_original_target_death_does_not_remove_after_cast_qualification(self):
        g=self.game((P+'kill',));target=self.eid(g,VICTIM,2);self.play(g,'kill',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.death_history),1);self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_original_hero_and_untargeted_casts_do_not_draw(self):
        g=self.game((P+'target',P+'plain'));self.play(g,'target',g.state.players[2].hero_id);self.play(g,'plain')
        self.assertEqual([c.target_origin.kind if c.target_origin else None for c in g.state.cast_history],[CardType.HERO,None]);self.assertFalse(self.draws(g));self.portable(g)

    def test_opponent_cast_and_own_source_removed_during_payload_do_not_draw(self):
        g=self.game((),enemy_hand=(P+'target',),active=2);self.play(g,'target',self.eid(g,VICTIM,2));self.assertFalse(self.draws(g))
        for name in('kill_fragment','silence_fragment','give_fragment'):
            g=self.game((P+name,));self.play(g,name,self.eid(g,VICTIM,2));self.assertFalse(self.draws(g));self.portable(g)

    def test_countered_original_minion_attempt_keeps_target_fact_without_finish_reward(self):
        # Install a real secret through the normal generated spell payload.
        from hs_sim.engine.secrets import SetSecret
        r=registry();r.register_behavior(P+'secret',lambda c:(SetSecret(2,'CORE_EX1_287'),));r.register_card(CardDefinition(P+'secret','Set Counterspell',CardType.SPELL,on_play=P+'secret'))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(P+'secret',P+'target'),board=(FRAGMENT,),deck=(YETI,)*4,mana=10,max_mana=10),PlayerSetup('HERO_08',board=(VICTIM,)))),r)
        self.play(g,'secret');self.play(g,'target',self.eid(g,VICTIM,2));row=g.state.cast_history[-1]
        self.assertEqual((row.failure,row.target_origin.kind),('countered',CardType.MINION));self.assertFalse(self.draws(g));self.assertFalse(any(e.kind=='spell_cast_finished'and e.source_id==row.source_id for e in g.events))
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())

    def test_real_manual_redirection_captures_final_target_kind_instead_of_declared_target(self):
        for watcher,declared,expected in [('redirect_hero','minion',CardType.HERO),('redirect_minion','hero',CardType.MINION)]:
            g=self.game(board=(P+watcher,FRAGMENT));target=self.eid(g,VICTIM,2)if declared=='minion'else g.state.players[2].hero_id
            self.play(g,'target',target);row=g.state.cast_history[-1];self.assertEqual(row.target_origin.kind,expected)
            self.assertNotEqual(row.target_id,g.state.play_history[-1].target_id);self.assertEqual(len(self.draws(g)),int(expected==CardType.MINION));self.portable(g)

    def test_cast_started_reaction_cannot_rewrite_accepted_original_target_type(self):
        g=self.game(board=(P+'start_change',FRAGMENT));target=self.eid(g,VICTIM,2);self.play(g,'target',target)
        self.assertEqual(g.state.entities[target].kind,CardType.SPELL);self.assertEqual(g.state.cast_history[-1].target_origin.kind,CardType.MINION)
        self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_payload_wait_has_no_early_draw_then_restores_original_target_and_completion(self):
        g=self.game((P+'wait',));target=self.eid(g,VICTIM,2);self.play(g,'wait',target);self.assertFalse(self.draws(g));self.assertFalse(g.state.cast_history[0].completed)
        other=self.portable(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),saved)
        for current in(g,other):self.choose(current)
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.draws(g)),1);self.assertEqual(g.state.entities[target].kind,CardType.SPELL)

    def test_already_captured_after_cast_reward_survives_later_original_source_retirement(self):
        g=self.game(board=(P+'finish_wait',FRAGMENT));self.play(g,'target',self.eid(g,VICTIM,2));self.assertFalse(self.draws(g));other=self.portable(g)
        for current in(g,other):self.choose(current,'kill')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(self.draws(g)),1)

    def test_effect_and_stored_casts_accept_original_targets_independently(self):
        for name in('generated','stored'):
            g=self.game((P+name,P+'target'));target=self.eid(g,VICTIM,2);self.play(g,name)
            self.assertEqual([c.origin for c in g.state.cast_history],['hand','effect']);self.assertIsNone(g.state.cast_history[0].target_origin)
            self.assertEqual((g.state.cast_history[1].target_origin.entity_id,g.state.cast_history[1].target_origin.kind),(target,CardType.MINION));self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_historical_recast_records_new_original_target_and_one_new_reward(self):
        g=self.game((P+'target',P+'history'));target=self.eid(g,VICTIM,2);self.play(g,'target',g.state.players[2].hero_id);self.play(g,'history')
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','hand','history']);self.assertEqual(g.state.cast_history[0].target_origin.kind,CardType.HERO)
        self.assertEqual(g.state.cast_history[-1].target_origin.entity_id,target);self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_each_hand_repetition_has_its_own_original_target_acceptance(self):
        g=self.game(board=(P+'repeat',FRAGMENT));target=self.eid(g,VICTIM,2);self.play(g,'target',target)
        self.assertEqual([c.origin for c in g.state.cast_history],['hand','repeat']);self.assertEqual(len(self.draws(g)),2);self.assertTrue(all(c.target_origin.entity_id==target for c in g.state.cast_history));self.assertEqual(g.state.players[1].mana,39);self.portable(g)

    def test_required_missing_or_invalid_automatic_target_cannot_get_completion_reward(self):
        for name in('missing','invalid'):
            g=self.game((P+name,),enemy=());self.play(g,name);row=g.state.cast_history[-1]
            self.assertEqual(row.failure,'no_target'if name=='missing'else'invalid_target');self.assertFalse(self.draws(g))
            self.assertEqual(row.target_origin.kind if row.target_origin else None,None if name=='missing'else CardType.HERO);self.portable(g)

    def test_cast_when_drawn_uses_same_actual_target_fact_and_native_draw_chain(self):
        g=self.game((P+'draw',),deck=(P+'portal',YETI,YETI));self.play(g,'draw')
        row=next(c for c in g.state.cast_history if c.origin=='draw');self.assertEqual(row.target_origin.kind,CardType.MINION)
        self.assertEqual(len(self.draws(g)),1);self.assertTrue(all(c.completed for c in g.state.cast_history));self.portable(g)

    def test_new_fragment_summoned_by_targeted_payload_can_observe_its_completion(self):
        g=self.game((P+'summon_fragment',),board=());self.play(g,'summon_fragment',self.eid(g,VICTIM,2))
        self.assertEqual(len(self.draws(g)),1);self.portable(g)

    def test_late_error_rolls_back_payment_target_material_cast_and_physical_movement(self):
        g=self.game((P+'late_fail',));saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'late_fail',self.eid(g,VICTIM,2))
        self.assertEqual(g.snapshot(),saved)

    def test_actual_rewind_retry_keeps_one_effective_target_start_and_one_reward(self):
        g=self.game((P+'rewind',));target=self.eid(g,VICTIM,2);self.play(g,'rewind',target);self.assertEqual(len(self.draws(g)),1)
        self.assertIsNotNone(g.state.pending_choice);other=self.portable(g)
        for current in(g,other):self.choose(current,'retry')
        self.assertEqual(g.snapshot(),other.snapshot());self.assertEqual(len(g.state.cast_history),1);self.assertEqual(len(self.draws(g)),1)
        self.assertEqual(g.state.cast_history[0].target_origin.entity_id,target);validate_target_origins(g);self.portable(g)

    def test_rehashed_target_type_forgery_without_original_start_receipt_is_rejected(self):
        g=self.game();self.play(g,'target',self.eid(g,VICTIM,2));s=g.snapshot();origin=s['state']['cast_history'][0]['target_origin']
        origin.update(card_id=P+'plain',kind='spell');self.reject(s)

    def test_rehashed_missing_future_owner_and_foreign_target_materials_are_rejected(self):
        g=self.game();self.play(g,'target',self.eid(g,VICTIM,2));saved=g.snapshot()
        for key in('missing','future','owner','entity','bool'):
            with self.subTest(key=key):
                s=deepcopy(saved);row=s['state']['cast_history'][0];origin=row['target_origin']
                if key=='missing':row['target_origin']=None
                elif key=='future':origin['next_order']=g.state.next_order+100
                elif key=='owner':origin['owner']=1
                elif key=='entity':origin['entity_id']=g.state.players[2].hero_id
                else:origin['zone_epoch']=True
                self.reject(s)

    def test_original_start_receipts_are_complete_unique_and_bound_to_real_cast(self):
        g=self.game();self.play(g,'target',self.eid(g,VICTIM,2));events=list(g.events);start=next(e for e in events if e.kind=='spell_cast_started')
        self.assertIn('target_origin',dict(start.data));validate_target_origins(g)
        variants=[ [e for e in events if e is not start],events+[start],
            [replace(e,target_id=g.state.players[2].hero_id)if e is start else e for e in events] ]
        for altered in variants:
            with self.assertRaises(ValueError):validate_target_origins(SimpleNamespace(_events=altered,_state=g.state))


if __name__=='__main__':unittest.main()
