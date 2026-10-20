"""Original student delivery and ordinary past-spell memory discovery/CAST."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.highborne_student_cards import CARD,PUPIL,GIFT,OVERFLOW,POOL_ID,PROFILE,load_batch
from hs_sim.engine import (CardDefinition,CardType,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,
    ResolutionError,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.carved_spells import CarvedSpellProfile
from hs_sim.engine.effects import AddToHand,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.student_teaching import StudentTeachingTarget
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard
from tools.card_batch import check_face

P='fixture.student.';UNIT=P+'unit';WATCH=P+'watch';PYRO='EX1_279'
CONTEXT=GenerationContext('explicit-student-experiment','experimental')


@lru_cache(maxsize=None)
def fixture(mode='normal'):
    r=build_registry();meta=replace(r.card('CORE_EX1_012').metadata,collectible=False,tribes=())
    r.register_card(CardDefinition(UNIT,UNIT,CardType.MINION,attack=1,health=8,metadata=meta))
    r.register_behavior(P+'damage',lambda c:(Damage(c.target_id,5,c.source_id),))
    r.register_card(replace(r.card(PYRO),id=P+'damage',name=P+'damage',cost=0,on_play=P+'damage'))
    for key,kind in(('copy','current'),('base','base')):
        r.register_behavior(P+key,lambda c,kind=kind:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,mode=kind,source_id=c.source_id),))
        r.register_card(CardDefinition(P+key,P+key,CardType.SPELL,on_play=P+key,targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,))))
    def fail(c):raise ResolutionError('Student actual teaching reaction failure')
    r.register_behavior(P+'fail',fail)
    def watch(c):
        event=c.event
        if mode=='fail' and event.kind=='student_spell_taught':return(InvokeBehavior(P+'fail',c.source_id,c.player_id),)
        if event.kind=='card_committed' and mode=='overflow' and c.state.entities[event.source_id].card_id==CARD:
            return(AddToHand(event.player_id,UNIT,c.source_id),)
        if event.kind!='card_added_to_hand':return ()
        entity=c.state.entities.get(event.target_id);source=c.state.entities.get(event.source_id)
        if entity is None or entity.card_id!=PUPIL or source is None or source.card_id!=CARD:return ()
        if mode=='wait':return(RequestChoice(event.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)
        if mode=='copy_first':return(CopyCard(CardReference.capture(entity),event.player_id,source_id=c.source_id),)
        if mode=='discard':return(DiscardCard(CardReference.capture(entity),c.source_id),)
        if mode=='kill_source':return(Destroy(event.source_id,c.source_id),)
        return ()
    r.register_behavior(P+'watch',watch);r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=meta,
        triggers=tuple(TriggerSpec(e,P+'watch')for e in('card_added_to_hand','card_committed','student_spell_taught'))))
    members=[GIFT,OVERFLOW,PYRO]
    if mode=='unknown':
        r.register_pool_card(replace(r.pool_card(OVERFLOW),card_id=P+'unknown'));members.append(P+'unknown')
    if mode=='empty':members=[PYRO]
    if mode!='missing':r.register_pool(PoolDefinition(POOL_ID,'explicit-test-past-v1',CONTEXT.target_id,CONTEXT.mode,
        tuple(PoolMember(cid)for cid in members),complete=mode!='incomplete'))
    r.validate();return r


def rehash(s):
    s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()if k not in('schema_version','events','events_hash','state_hash')});return s


def targets(value):
    if isinstance(value,dict):
        if value.get('type','').endswith('.StudentTeachingTarget'):yield value['fields']
        for child in value.values():yield from targets(child)
    elif isinstance(value,list):
        for child in value:yield from targets(child)


class HighborneStudentTests(unittest.TestCase):
    def game(self,hand=(CARD,),mode='normal',hero='HERO_06',active=1,board=()):
        setups=[]
        for p in(1,2):
            setups.append(PlayerSetup(hero if p==active else'HERO_08',hand=hand if p==active else(),deck=(UNIT,)*10,
                board=board if p==active else((WATCH,)if mode in('wait','copy_first','discard','kill_source','overflow','fail')else()),max_mana=10,mana=10))
        return Game.from_scenario(Scenario(tuple(setups),active_player=active,seed=171,generation_context=CONTEXT),fixture(mode))
    def play(self,g,cid=CARD,target=None):
        p=g.state.active_player;i=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid);g.apply(PlayCard(p,i,target));return i
    def pupils(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id==PUPIL]
    def value(self,e):return next(a.carved_spell_id for a in e.abilities if a.kind=='battlecry')
    def pick(self,g,cid=GIFT):
        q=g.state.pending_choice;o=next(o for o in q.options if o.card_id==cid);g.apply(SelectChoice(q.player_id,q.id,(o.id,)))
    def portable(self,g,mode='normal',fresh=False):
        s=g.snapshot();r=fixture.__wrapped__(mode)if fresh else fixture(mode)
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(replay(build_replay(g),r).snapshot(),s);return s

    def test_complete_two_native_faces_and_real_past_dependencies_are_strict(self):
        d=load_batch();self.assertEqual(len(d['official_observations']),10);self.assertTrue(PROFILE.teaching)
        rows={x['record']['id']:x['record']for x in(*d['cards'],*d['dependencies'],*d['existing_dependencies'])}
        for obs in d['official_observations']:
            raw=rows[obs['card_id']];decl={'{0}':''}if raw['id']==PUPIL else None
            check_face(raw,obs['face'],obs['locale'],decl)
            if raw['id']==PUPIL:
                with self.assertRaises(ValueError):check_face(raw,obs['face'],obs['locale'])
                bad=deepcopy(obs['face']);bad['text']+=' Draw a card.'
                with self.assertRaises(ValueError):check_face(raw,bad,obs['locale'],decl)
                bad=deepcopy(raw);bad['health']=3
                with self.assertRaises(ValueError):check_face(bad,obs['face'],obs['locale'],decl)
        self.assertEqual((fixture().card(CARD).cost,fixture().card(CARD).attack,fixture().card(CARD).health),(7,6,6))
        self.assertEqual((fixture().card(PUPIL).cost,fixture().card(PUPIL).attack,fixture().card(PUPIL).health),(2,2,2))
        self.assertFalse(any(k[0]==POOL_ID for k in build_registry().pools))
        with self.assertRaises(ValueError):CarvedSpellProfile(PUPIL,CARD,teaching='yes')

    def test_student_is_physically_in_hand_before_discovery_and_spell_is_not_gained(self):
        g=self.game();n=len(g.state.entities);self.play(g);pupil=self.pupils(g)[0]
        self.assertEqual((len(g.state.entities),g.state.players[1].mana),(n+1,3));self.assertIsNone(self.value(pupil))
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{GIFT,OVERFLOW});self.pick(g)
        self.assertEqual(self.pupils(g)[0].id,pupil.id);self.assertEqual(self.value(self.pupils(g)[0]),GIFT)
        self.assertEqual(len(g.state.entities),n+1);self.assertEqual(len(g.state.card_discovery_history),1);self.portable(g)

    def test_actual_pupil_casts_past_gift_without_eight_mana_payment(self):
        g=self.game(board=(UNIT,));self.play(g);self.pick(g);i=self.play(g,PUPIL)
        self.assertEqual(g.state.players[1].mana,1);self.assertEqual(g.state.entities[i].attack,4)
        self.assertTrue(all(Keyword.TAUNT in g.state.entities[j].keywords for j in g.state.players[1].board))
        self.assertEqual(g.state.cast_history[-1].card_id,GIFT);self.portable(g)

    def test_actual_pupil_overflow_heals_all_characters_before_real_five_draws(self):
        g=self.game(hand=(CARD,P+'damage',P+'damage'))
        for p in(1,2):self.play(g,P+'damage',g.state.players[p].hero_id)
        self.play(g);self.pick(g,OVERFLOW);self.play(g,PUPIL)
        self.assertEqual([g.state.entities[g.state.players[p].hero_id].health for p in(1,2)],[30,30])
        self.assertEqual(len(g.state.players[1].deck),5);self.assertEqual(len(g.state.players[1].hand),5);self.portable(g)

    def test_foreign_mentor_uses_current_mage_pool_and_pupil_forwards_real_target(self):
        g=self.game(hero='HERO_08');self.play(g);self.assertEqual([o.card_id for o in g.state.pending_choice.options],[PYRO])
        self.pick(g,PYRO);self.play(g,PUPIL,g.state.players[2].hero_id)
        self.assertEqual(g.state.players[1].mana,1);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,20)
        self.assertEqual(g.state.cast_history[-1].card_id,PYRO);self.portable(g)

    def test_original_creation_reaction_can_wait_and_recover_before_discovery_starts(self):
        g=self.game(mode='wait');self.play(g);self.assertEqual(g.state.pending_choice.options[0].id,'ok')
        self.assertIsNone(self.value(self.pupils(g)[0]));self.portable(g,'wait',fresh=True)
        q=g.state.pending_choice;g.apply(SelectChoice(1,q.id,('ok',)));self.portable(g,'wait',fresh=True)
        self.pick(g);self.assertEqual(self.value(self.pupils(g)[0]),GIFT);self.portable(g,'wait')

    def test_same_original_student_is_taught_while_early_copy_remains_empty(self):
        g=self.game(mode='copy_first');self.play(g);self.assertEqual(len(self.pupils(g)),2)
        original=self.pupils(g)[0].id;self.pick(g);self.assertEqual([self.value(e)for e in self.pupils(g)],[GIFT,None])
        self.assertEqual(self.pupils(g)[0].id,original);self.portable(g,'copy_first')

    def test_discarded_original_is_not_replaced_but_real_discovery_still_completes(self):
        g=self.game(mode='discard');self.play(g);self.assertFalse(self.pupils(g));self.pick(g)
        self.assertFalse(self.pupils(g));self.assertEqual(len(g.state.card_discovery_history),1)
        self.assertFalse(dict(next(e for e in g.events if e.kind=='student_spell_taught').data)['taught']);self.portable(g,'discard')

    def test_source_death_keeps_original_student_and_player_in_second_seat(self):
        g=self.game(mode='kill_source',active=2);i=self.play(g);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.pick(g);self.assertEqual(self.value(self.pupils(g,2)[0]),GIFT);self.portable(g,'kill_source')

    def test_full_hand_burn_uses_original_overflow_without_teaching_a_replacement(self):
        g=self.game(hand=(CARD,)+(UNIT,)*9,mode='overflow');self.play(g);self.assertFalse(self.pupils(g));self.pick(g)
        self.assertFalse(self.pupils(g));self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(sum(e.kind=='card_burned'for e in g.events),1);self.portable(g,'overflow')

    def test_current_copy_keeps_taught_spell_and_base_copy_is_empty(self):
        g=self.game(hand=(CARD,P+'copy',P+'base'));self.play(g);self.pick(g);original=self.pupils(g)[0]
        self.play(g,P+'copy',original.id);self.play(g,P+'base',original.id)
        self.assertEqual([self.value(e)for e in self.pupils(g)],[GIFT,GIFT,None]);self.portable(g)

    def test_missing_incomplete_and_unknown_qualified_domains_roll_back_before_creation(self):
        for mode in('missing','incomplete','unknown'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);before=g.snapshot()
                with self.assertRaises((ValueError,ResolutionError)):self.play(g)
                self.assertEqual(g.snapshot(),before)

    def test_empty_current_class_domain_retains_ordinary_empty_discovery_policy(self):
        g=self.game(mode='empty');self.play(g);self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.pupils(g)),1)
        self.assertIsNone(self.value(self.pupils(g)[0]));self.portable(g,'empty')

    def test_bad_choice_and_teaching_reaction_failure_restore_exact_original_wait(self):
        g=self.game(mode='fail');self.play(g);saved=g.snapshot();q=g.state.pending_choice
        with self.assertRaises(IllegalAction):g.apply(SelectChoice(2,q.id,(q.options[0].id,)))
        self.assertEqual(g.snapshot(),saved)
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),saved);self.assertIsNone(self.value(self.pupils(g)[0]));self.portable(g,'fail')

    def test_rehashed_target_cannot_borrow_another_student_source_or_acceptance(self):
        g=self.game(mode='copy_first');self.play(g);saved=g.snapshot();second=self.pupils(g)[1].id
        for kind in('event','creator','allocation'):
            with self.subTest(kind=kind):
                bad=deepcopy(saved);nodes=list(targets(bad));self.assertTrue(nodes)
                for node in nodes:
                    if kind=='event':node['event_id']+=1
                    elif kind=='creator':node['battlecry_id']+=100
                    else:node['allocation']['fields']['entity_id']=second
                with self.assertRaises(SnapshotError):Game.from_snapshot(rehash(bad),fixture('copy_first'))

    def test_owner_sees_taught_spell_without_leaking_pool_marker_or_opponent_hand_value(self):
        g=self.game();self.play(g);self.pick(g)
        own=json.dumps(g.for_player(1).observe());opponent=json.dumps(g.for_player(2).observe());self.assertIn(GIFT,own);self.assertNotIn(GIFT,opponent)
        for text in(own,opponent):
            for hidden in('student_teaching_accepted','allocation_json','past.spells','rng_before'):self.assertNotIn(hidden,text)
        self.portable(g)

    def test_player_command_selects_a_spell_through_existing_discovery_refs(self):
        g=self.game();self.play(g);api=g.for_player(1);listing=api.legal_actions();action=next(a for a in listing['actions']if a['type']=='select_choice')
        self.assertTrue(api.submit({'revision':listing['revision'],'action':action})['accepted']);self.assertIsNotNone(self.value(self.pupils(g)[0]));self.portable(g)


if __name__=='__main__':unittest.main()
