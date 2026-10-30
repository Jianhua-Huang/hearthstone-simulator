"""Current-controller turn immunity is a live native aura, not a timed grant."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from hs_sim.engine import (CardDefinition,CardType,EndTurn,Game,Keyword,KeywordAuraSpec,PlayCard,
    PlayerSetup,QueueTurns,Registry,ResolutionError,Scenario,SelectChoice,SkipTurns,SnapshotError,TriggerSpec)
from hs_sim.engine.dormancy import AwakenMinion,MakeDormant
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,Draw,
    GainArmor,InvokeBehavior,ReplaceHero,RequestChoice,ReturnToHand,Silence,Summon,Transform)
from hs_sim.engine.keyword_auras import GrantKeywordAura
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.replay import build_replay,replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='ede01db4b999817d82f42b2d97fed309f01397e9e11767944e03f72d8d912ba0'
ILLUSIONIST='KAR_712'
AURA=KeywordAuraSpec(Keyword.IMMUNE,condition='controller_turn')

def evidence():
    p=json.loads((ROOT/'data/support/controller-turn-keyword-aura-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Controller-turn full raw changed')
    return p

def registry():
    r=Registry('isolated-controller-turn-hero-immunity-v1'); raw=evidence()['records'][0]
    for name in ('hero','other-hero'): r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.HERO,health=60,metadata=metadata()))
    r.register_card(CardDefinition(ILLUSIONIST,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keyword_auras=(AURA,),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,health=6,metadata=metadata()))
    def body(c): return (Damage(c.state.players[c.player_id].hero_id,4,c.source_id),)
    def ending(c):
        return body(c) if dict(c.event.data).get('player_id',c.event.player_id)==c.player_id else ()
    def starting(c):
        if c.event.player_id!=c.player_id: return ()
        h=c.state.entities[c.state.players[c.player_id].hero_id]
        return (GainArmor(c.player_id,1 if Keyword.IMMUNE in h.keywords else 0),Damage(h.id,4,c.source_id))
    r.register_behavior('ending',ending); r.register_behavior('starting',starting)
    r.register_card(CardDefinition('watcher','Diagnostic boundary watcher',CardType.MINION,health=6,
        triggers=(TriggerSpec('turn_started','starting'),TriggerSpec('turn_ended','ending')),metadata=metadata()))
    def fail(c): raise ResolutionError('Diagnostic turn-immunity failure')
    r.register_behavior('fault',fail)
    def source(c): return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==ILLUSIONIST)
    def waiting(c): return (RequestChoice(c.player_id,(
        ChoiceOption('hurt','Hurt',(Damage(c.state.players[c.player_id].hero_id,4,c.source_id),)),
        ChoiceOption('silence','Silence and hurt',(Silence(source(c)),Damage(c.state.players[c.player_id].hero_id,4,c.source_id))),
        ChoiceOption('fault','Fail',(Silence(source(c)),InvokeBehavior('fault',c.source_id,c.player_id))),
    ),c.source_id),)
    targeted={'silence':lambda c:(Silence(c.target_id),), 'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),), 'transform':lambda c:(Transform(c.target_id,'plain'),),
        'control':lambda c:(ChangeControl(c.target_id,2),), 'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),)}
    scripts={'hurt':body, 'wait':waiting,'draw':lambda c:(Draw(c.player_id),),
        'summon':lambda c:(Summon(c.player_id,ILLUSIONIST),),
        'replace-hero':lambda c:(ReplaceHero(c.player_id,'other-hero'),),
        'extra':lambda c:(QueueTurns((c.player_id,),c.source_id),),
        'skip':lambda c:(SkipTurns(2,1,c.source_id),),
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy)),),
        'fault':lambda c:(Silence(source(c)),InvokeBehavior('fault',c.source_id,c.player_id))}
    for name,fn in {**targeted,**scripts}.items():
        r.register_behavior('diag.'+name,fn)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play='diag.'+name,
            requires_target=name in targeted,metadata=metadata()))
    return r

class ControllerTurnKeywordAuraTests(unittest.TestCase):
    def game(self,hand=('hurt',),board=(ILLUSIONIST,),enemy=(),enemy_hand=('hurt',),deck=('plain',)*5):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=deck,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=deck,mana=10,max_mana=10),
        ),seed=131),registry())
    def hero(self,g,p=1): return g.state.entities[g.state.players[p].hero_id]
    def immune(self,g,p=1): return Keyword.IMMUNE in self.hero(g,p).keywords
    def card(self,g,name,p=1): return next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==name)
    def play(self,g,name,target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s); return s

    def test_full_native_raw_and_no_claim_of_exhaustive_scope(self):
        p=evidence(); self.assertEqual(p['records'][0]['id'],ILLUSIONIST); self.assertFalse(p['CN_calibrated'])
        self.assertEqual(p['new_combinations'],0); self.assertEqual((registry().card(ILLUSIONIST).cost,registry().card(ILLUSIONIST).attack),(3,4))

    def test_native_controller_condition_is_closed_and_cannot_be_arbitrarily_granted(self):
        self.assertEqual(replace(AURA,keyword=Keyword.WINDFURY).keyword,Keyword.WINDFURY)
        for fields in ({'target':'self'},{'target':'friendly_minions'},{'keyword':Keyword.MEGA_WINDFURY},
                {'include_self':True},{'adjacent_only':True},{'condition':True}):
            with self.subTest(fields=fields),self.assertRaises(ValueError): replace(AURA,**fields)
        with self.assertRaises(ValueError): GrantKeywordAura(3,AURA)
        with self.assertRaises(ValueError): GrantKeywordAura(3,replace(AURA,keyword=Keyword.WINDFURY))

    def test_own_turn_immunity_blocks_damage_and_never_protects_opponent(self):
        g=self.game(); self.assertTrue(self.immune(g)); self.assertFalse(self.immune(g,2))
        self.play(g,'hurt'); self.assertEqual(self.hero(g).health,60); self.portable(g)
        g.apply(EndTurn(1)); self.assertFalse(self.immune(g)); self.play(g,'hurt'); self.assertEqual(self.hero(g,2).health,56); self.portable(g)

    def test_each_player_hero_follows_current_controller_actual_turn(self):
        g=self.game(enemy=(ILLUSIONIST,)); self.assertEqual((self.immune(g),self.immune(g,2)),(True,False))
        g.apply(EndTurn(1)); self.assertEqual((self.immune(g),self.immune(g,2)),(False,True))
        g.apply(EndTurn(2)); self.assertEqual((self.immune(g),self.immune(g,2)),(True,False)); self.portable(g)

    def test_actual_turn_start_refreshes_before_boundary_context_and_fatigue(self):
        g=self.game(board=(ILLUSIONIST,'watcher'),deck=()); g.apply(EndTurn(1)); self.assertEqual(self.hero(g).health,60)
        g.apply(EndTurn(2)); self.assertTrue(self.immune(g)); self.assertEqual(self.hero(g).health,60)
        self.assertEqual((self.hero(g).armor,g.state.players[1].fatigue),(1,1)); self.portable(g)

    def test_turn_ending_effects_keep_old_controller_immunity(self):
        g=self.game(board=(ILLUSIONIST,'watcher')); g.apply(EndTurn(1))
        self.assertEqual(self.hero(g).health,60); self.assertFalse(self.immune(g)); self.portable(g)

    def test_fatigue_damage_remains_prevented_and_fatigue_counter_still_advances(self):
        g=self.game(hand=('draw','draw'),deck=()); self.play(g,'draw'); self.play(g,'draw')
        self.assertEqual((self.hero(g).health,g.state.players[1].fatigue),(60,2)); self.portable(g)

    def test_hand_source_and_played_or_summoned_live_source_use_same_lifetime(self):
        for method in ('play','summon'):
            with self.subTest(method=method):
                g=self.game(hand=(ILLUSIONIST,'summon','hurt'),board=()); self.assertFalse(self.immune(g))
                self.play(g,ILLUSIONIST if method=='play' else 'summon'); self.assertTrue(self.immune(g)); self.play(g,'hurt')
                self.assertEqual(self.hero(g).health,60); self.portable(g)

    def test_source_silence_death_return_and_transform_remove_only_live_contribution(self):
        for method in ('silence','destroy','bounce','transform'):
            with self.subTest(method=method):
                g=self.game(hand=(method,'hurt')); self.play(g,method,g.state.players[1].board[0]); self.assertFalse(self.immune(g))
                self.play(g,'hurt'); self.assertEqual(self.hero(g).health,56); self.portable(g)

    def test_sleep_and_wake_recompute_current_turn_without_new_keyword_grant(self):
        g=self.game(hand=('sleep','wake','hurt')); self.play(g,'sleep',g.state.players[1].board[0]); self.assertFalse(self.immune(g))
        self.play(g,'wake'); self.assertTrue(self.immune(g)); self.play(g,'hurt'); self.portable(g)

    def test_control_change_uses_new_controller_and_copy_keeps_distinct_live_source(self):
        g=self.game(hand=('control',)); self.play(g,'control',g.state.players[1].board[0])
        self.assertEqual((self.immune(g),self.immune(g,2)),(False,False)); g.apply(EndTurn(1))
        self.assertEqual((self.immune(g),self.immune(g,2)),(False,True)); self.portable(g)
        g=self.game(hand=('copy','silence','destroy')); self.play(g,'copy',g.state.players[1].board[0]); ids=g.state.players[1].board
        self.play(g,'silence',ids[0]); self.assertTrue(self.immune(g)); self.play(g,'destroy',ids[1]); self.assertFalse(self.immune(g)); self.portable(g)

    def test_hero_replacement_receives_existing_active_aura(self):
        g=self.game(hand=('replace-hero','hurt')); self.play(g,'replace-hero'); self.assertTrue(self.immune(g)); self.play(g,'hurt')
        self.assertEqual(self.hero(g).health,60); self.portable(g)

    def test_extra_or_skipped_slot_keeps_actual_player_condition(self):
        for name in ('extra','skip'):
            with self.subTest(name=name):
                g=self.game(hand=(name,)); self.play(g,name); g.apply(EndTurn(1))
                self.assertEqual(g.state.active_player,1); self.assertTrue(self.immune(g)); self.portable(g)

    def test_waiting_restore_then_source_loss_changes_following_damage(self):
        g=self.game(hand=('wait',)); self.play(g,'wait'); wait=self.portable(g); h=Game.from_snapshot(deepcopy(wait),registry())
        choice=g.state.pending_choice.id; g.apply(SelectChoice(1,choice,('silence',))); h.apply(SelectChoice(1,choice,('silence',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(self.hero(g).health,56); self.portable(g)

    def test_failure_rolls_back_source_keyword_and_waiting_choice(self):
        g=self.game(hand=('fault','wait')); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'fault')
        self.assertEqual(g.snapshot(),before); self.play(g,'wait'); before=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before); self.assertTrue(self.immune(g)); self.portable(g)

    def test_player_views_expose_public_immunity_without_internal_aura_state(self):
        g=self.game(); before=g.snapshot()
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())
            for key in ('controller_turn','keyword_auras','source_sha256','aura_keywords'): self.assertNotIn(key,text)
        self.assertEqual(g.snapshot(),before)

    def test_native_condition_and_lifecycle_tampering_cannot_turn_it_permanent(self):
        g=self.game(); snapshot=g.snapshot()
        for what in ('condition','origin','silence','expiry'):
            bad=deepcopy(snapshot); ability=next(a for a in bad['state']['entities'][str(g.state.players[1].board[0])]['abilities'] if a['kind']=='keyword_aura')
            if what=='condition': ability['keyword_aura']['condition']='always'
            elif what=='origin': ability['origin']='granted'
            elif what=='silence': ability['remove_on_silence']=False
            else: ability['expires_turn']=1
            with self.subTest(what=what),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

if __name__=='__main__': unittest.main()
