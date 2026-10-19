"""Original completed attacks, lethal growth and the existing memory lifecycle."""
from dataclasses import asdict
from functools import lru_cache
import json
import unittest

from hs_sim.cards.omen_attack_growth_card import CARD,load_batch,register_omen_attack_growth_card
from hs_sim.engine import (Attack,CardDefinition,CardType,EndTurn,Game,Keyword,PlayCard,
    PlayerSetup,Scenario,SelectChoice,SnapshotError,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.deathrattle_memory import GrowDeathrattleSummon
from hs_sim.engine.dormancy import MakeDormant,AwakenMinion
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,
    ForceAttack,InvokeBehavior,RandomDamage,RequestChoice,ReturnToHand,Silence,Transform)
from hs_sim.engine.errors import IllegalAction,ResolutionError
from hs_sim.engine.model import DeathrattleMemory,NativeDeathrattleSpec,RememberedDraw
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.resolver import CombatDamage
from hs_sim.engine.sacrifice import MinionReference

P='omen.test.'
FILL='CS2_182'
KILL,SILENCE,BOUNCE,CHANGE,GIVE,COPY,BASE,SLEEP,WAKE,FORCE,BARE,WRONG=(
    P+x for x in ('kill','silence','bounce','change','give','copy','base','sleep','wake','force','bare','wrong'))
DUMMY,FATAL,SECOND,WATCH,BONUS=(P+x for x in ('dummy','fatal','second','watch','bonus'))


@lru_cache(maxsize=None)
def registry(role,mode='normal'):
    assert role in ('writer','reader')
    r=build_registry();register_omen_attack_growth_card(r)
    def enemy(c):return c.state.players[3-c.player_id].board[0]
    def wrong(c):
        e=c.state.entities[c.target_id]
        a=next(a for a in e.abilities if a.deathrattle_memory is not None)
        return (GrowDeathrattleSummon(MinionReference.capture(e),a.id),)
    bodies={KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),
        BOUNCE:lambda c:(ReturnToHand(c.target_id),),CHANGE:lambda c:(Transform(c.target_id,FILL),),
        GIVE:lambda c:(ChangeControl(c.target_id,3-c.player_id),),COPY:lambda c:(CopyMinion(c.target_id,c.player_id),),
        BASE:lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        SLEEP:lambda c:(MakeDormant(c.target_id,1,c.source_id),),
        WAKE:lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board
            if c.state.entities[i].dormancy is not None),c.source_id),),
        FORCE:lambda c:(ForceAttack(c.target_id,enemy(c)),),BARE:lambda c:(CombatDamage(c.target_id,enemy(c)),),WRONG:wrong}
    for cid,body in bodies.items():
        r.register_behavior(cid,body)
        extra={} if cid==WAKE else {'targeting':TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))}
        r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,**extra))
    for cid,attack,health in ((DUMMY,0,40),(FATAL,6,20),(SECOND,2,5)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=health))
    r.register_card(CardDefinition(BONUS,BONUS,CardType.MINION,health=9,spell_damage=7))
    def fail(c):raise ResolutionError('Omen deliberate rollback')
    r.register_behavior(P+'fail',fail)
    if mode in ('wait','fail','cancel'):
        def watch(c):
            source=c.state.entities.get(c.event.source_id)
            if source is None or source.card_id!=CARD:return ()
            if mode=='cancel':return (Destroy(c.event.target_id,c.source_id),)
            if mode=='fail':return (InvokeBehavior(P+'fail',c.source_id,c.player_id),)
            bad=(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id))
            return (RequestChoice(c.player_id,(ChoiceOption('ok','Continue',()),ChoiceOption('bad','Fail',bad)),c.source_id),)
        r.register_behavior(WATCH,watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=9,
            triggers=(TriggerSpec('attack_declared'if mode=='cancel'else 'attack_finished',WATCH),)))
    r.validate();r.freeze();return r


class OmenGrowthTests(unittest.TestCase):
    def game(self,hand=(CARD,KILL),*,board=(),enemy=(DUMMY,SECOND),enemy_hand=(),mode='normal'):
        if mode in ('wait','fail','cancel'):board=(WATCH,*board)
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,
            deck=(FILL,)*25,mana=30,max_mana=30,mana_cap=30),PlayerSetup('HERO_08',hand=enemy_hand,
            board=enemy,deck=(FILL,)*25,mana=30,max_mana=30,mana_cap=30)),seed=252421),registry('writer',mode))
    def entity(self,g,cid,pid=1,zone='board'):
        return next(g.state.entities[i] for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
    def play(self,g,cid=CARD,target=None,pid=None):
        pid=g.state.active_player if pid is None else pid
        eid=self.entity(g,cid,pid,'hand').id;g.apply(PlayCard(pid,eid,target));return eid
    def memory(self,g,eid):
        return next(a.deathrattle_memory for a in g.state.entities[eid].abilities if a.deathrattle_memory is not None)
    def attack(self,g,eid,target=None):
        pid=g.state.active_player
        if target is None:target=g.state.players[3-pid].board[0]
        g.apply(Attack(pid,eid,target))
    def hp(self,g,pid):return g.state.entities[g.state.players[pid].hero_id].health
    def portable(self,g,mode='normal'):
        s=g.snapshot();self.assertEqual(Game.from_snapshot(s,registry('reader',mode)).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry('reader',mode)).snapshot(),s)

    def test_a00_complete_original_face_and_full_assembly_match(self):
        from hs_sim.cards import build_registry as complete
        row=load_batch()['cards'][0];r=registry('writer')
        self.assertEqual(asdict(r.card(CARD)),asdict(complete().card(CARD)))
        self.assertEqual(r.card(CARD).metadata.tribes,('beast','demon'))
        self.assertEqual(set(r.card(CARD).keywords),{Keyword.RUSH,Keyword.WINDFURY})
        self.assertEqual(row['record']['tags']['TAG_SCRIPT_DATA_NUM_1'],1)
    def test_a01_memory_shapes_and_old_schema_are_strict(self):
        spec=NativeDeathrattleSpec('attack_damage_growth')
        self.assertEqual(DeathrattleMemory(spec,2).growth_steps,2)
        for kwargs in ({'growth_steps':True},{'growth_steps':-1},{'draws':(RememberedDraw(1,1,1,1),)},
                {'discard_ids':(1,)},{'growth_steps':1,'discoveries':('bad',)}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):DeathrattleMemory(spec,**kwargs)
        with self.assertRaises(ValueError):NativeDeathrattleSpec('attack_damage_growth',attack=1)
        s=self.game().snapshot();s['schema_version']=426
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,registry('reader'))
    def test_b00_initial_death_is_one_to_every_enemy_without_spell_bonus(self):
        g=self.game(board=(BONUS,FILL));eid=self.play(g);self.play(g,KILL,eid)
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(30,29))
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[39,4])
        self.assertEqual(self.entity(g,FILL).health,5);self.portable(g)
    def test_b01_two_real_rush_attacks_grow_once_each_then_death_is_three(self):
        g=self.game();eid=self.play(g);self.attack(g,eid);self.attack(g,eid)
        self.assertEqual(self.memory(g,eid).growth_steps,2)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):self.attack(g,eid)
        self.assertEqual(g.snapshot(),before)
        self.play(g,KILL,eid);self.assertEqual(self.hp(g,2),27)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[25,2]);self.portable(g)
    def test_b02_fatal_second_attack_is_included_in_frozen_deathrattle(self):
        g=self.game(enemy=(FATAL,SECOND));eid=self.play(g);self.attack(g,eid);self.attack(g,eid)
        self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.assertEqual(self.hp(g,2),27)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board],[5,2]);self.portable(g)
    def test_b03_defending_does_not_grow(self):
        g=self.game(board=(CARD,),enemy=(SECOND,),enemy_hand=(KILL,));eid=self.entity(g,CARD).id
        g.apply(EndTurn(1));self.attack(g,self.entity(g,SECOND,2).id,eid)
        self.assertEqual(self.memory(g,eid).growth_steps,0);self.play(g,KILL,eid)
        self.assertEqual(self.hp(g,2),29)
    def test_b04_real_forced_attack_grows_but_bare_damage_exchange_does_not(self):
        g=self.game((CARD,FORCE,BARE));eid=self.play(g)
        self.play(g,FORCE,eid);self.assertEqual(self.memory(g,eid).growth_steps,1)
        self.play(g,BARE,eid);self.assertEqual(self.memory(g,eid).growth_steps,1);self.portable(g)
    def test_b05_cancelled_declaration_does_not_grow(self):
        g=self.game(mode='cancel');eid=self.play(g);self.attack(g,eid)
        self.assertEqual(self.memory(g,eid).growth_steps,0)
        self.assertEqual(g.state.character_attack_history[-1].terminal.status,'cancelled');self.portable(g,'cancel')
    def test_c00_current_copy_retains_value_and_grows_independently(self):
        g=self.game((CARD,COPY,FORCE));eid=self.play(g);self.attack(g,eid);self.play(g,COPY,eid)
        other=next(i for i in g.state.players[1].board if i!=eid)
        self.assertEqual(self.memory(g,other).growth_steps,1);self.play(g,FORCE,other)
        self.assertEqual((self.memory(g,eid).growth_steps,self.memory(g,other).growth_steps),(1,2));self.portable(g)
    def test_c01_base_copy_and_bounce_start_fresh(self):
        g=self.game((CARD,BASE,BOUNCE));eid=self.play(g);self.attack(g,eid);self.play(g,BASE,eid)
        other=next(i for i in g.state.players[1].board if i!=eid);self.assertEqual(self.memory(g,other).growth_steps,0)
        self.play(g,BOUNCE,eid);self.assertEqual(self.memory(g,eid).growth_steps,0)
        self.play(g);self.assertEqual(self.memory(g,eid).growth_steps,0);self.portable(g)
    def test_c02_silence_and_transform_remove_native_growth_and_deathrattle(self):
        for cid in (SILENCE,CHANGE):
            with self.subTest(cid=cid):
                g=self.game((CARD,cid,KILL));eid=self.play(g);self.attack(g,eid);self.play(g,cid,eid)
                self.assertFalse(any(a.deathrattle_memory for a in g.state.entities[eid].abilities))
                self.play(g,KILL,eid);self.assertEqual(self.hp(g,2),30)
    def test_c03_dormancy_and_awakening_preserve_original_damage(self):
        g=self.game((CARD,SLEEP,WAKE,KILL));eid=self.play(g);self.attack(g,eid);self.play(g,SLEEP,eid)
        self.assertEqual(self.memory(g,eid).growth_steps,1);self.portable(g)
        self.play(g,WAKE);self.assertEqual(self.memory(g,eid).growth_steps,1)
        self.play(g,KILL,eid);self.assertEqual(self.hp(g,2),28);self.portable(g)
    def test_c04_control_transfer_retains_damage_and_uses_current_enemy(self):
        g=self.game((CARD,GIVE),enemy_hand=(KILL,));eid=self.play(g);self.attack(g,eid);self.play(g,GIVE,eid)
        g.apply(EndTurn(1));self.play(g,KILL,eid)
        self.assertEqual((self.hp(g,1),self.hp(g,2)),(28,30));self.portable(g)
    def test_c05_other_native_growth_effect_cannot_change_omen_memory(self):
        g=self.game((CARD,WRONG));eid=self.play(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,WRONG,eid)
        self.assertEqual(g.snapshot(),s)
    def test_d00_completed_attack_wait_restores_growth_and_replays_once(self):
        g=self.game(mode='wait');eid=self.play(g);self.attack(g,eid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.memory(g,eid).growth_steps,1)
        self.portable(g,'wait');waiting=g.snapshot();restored=Game.from_snapshot(waiting,registry('reader','wait'))
        for x in (g,restored):x.apply(SelectChoice(1,x.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.memory(g,eid).growth_steps,1)
    def test_d01_fatal_attack_wait_has_original_grown_death_capture(self):
        g=self.game(enemy=(FATAL,SECOND),mode='wait');eid=self.play(g);self.attack(g,eid)
        g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)));self.attack(g,eid)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD)
        self.portable(g,'wait');s=g.snapshot();restored=Game.from_snapshot(s,registry('reader','wait'))
        for x in (g,restored):x.apply(SelectChoice(1,x.state.pending_choice.id,('ok',)))
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.hp(g,2),27)
    def test_d02_choice_failure_rolls_back_rng_and_keeps_original_growth(self):
        g=self.game(mode='wait');eid=self.play(g);self.attack(g,eid);s=g.snapshot()
        with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,g.state.pending_choice.id,('bad',)))
        self.assertEqual(g.snapshot(),s);g.apply(SelectChoice(1,g.state.pending_choice.id,('ok',)))
        self.assertEqual(self.memory(g,eid).growth_steps,1);self.portable(g,'wait')
    def test_d03_immediate_failure_rolls_back_attack_and_retry_grows_once(self):
        g=self.game((CARD,SILENCE),mode='fail');eid=self.play(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.attack(g,eid)
        self.assertEqual(g.snapshot(),s);self.play(g,SILENCE,self.entity(g,WATCH).id);self.attack(g,eid)
        self.assertEqual(self.memory(g,eid).growth_steps,1);self.portable(g,'fail')
    def test_e00_current_damage_is_public_without_private_memory(self):
        g=self.game((CARD,SILENCE));eid=self.play(g);self.attack(g,eid)
        for pid in (1,2):
            v=g.observe(pid);row=next(x for x in v['players'][0]['board']if x['card_id']==CARD)
            self.assertEqual(v['version'],'player-view-v97');self.assertEqual(row['deathrattle_damages'],[2])
            for private in ('deathrattle_memory','growth_steps','ability_id','character_attack_history'):
                self.assertNotIn(private,json.dumps(v))
        self.play(g,SILENCE,eid)
        self.assertNotIn('deathrattle_damages',g.observe(2)['players'][0]['board'][0])
    def test_e01_opponent_hand_does_not_reveal_damage_or_card(self):
        g=self.game();text=json.dumps(g.observe(2)['players'][0]['hand'])
        self.assertNotIn(CARD,text);self.assertNotIn('deathrattle_damages',text)
