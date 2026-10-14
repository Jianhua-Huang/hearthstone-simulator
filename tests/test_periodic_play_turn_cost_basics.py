"""Periodic minion prices use the original player turn ordinal, not source uses."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostAuraSpec, CostSpec, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, ResolutionError,
    Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, quote_input
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, GrantCostAura,
    InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='1ad581cc25921e0a17135cac8658563883cb8206d00f6db15d1e1a903c3839de'
KAEL='REV_021'
AURA=CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.MINION,)),every_nth_per_turn=3)

def evidence():
    p=json.loads((ROOT/'data/support/periodic-play-turn-cost-basics.json').read_bytes())
    if canonical_digest(p)!=PIN: raise ValueError('Periodic full raw changed')
    return p

def registry():
    r=Registry('isolated-periodic-minion-price-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    raw=next(x for x in evidence()['records'] if x['id']==KAEL)
    r.register_card(CardDefinition(KAEL,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        cost_auras=(AURA,),metadata=metadata_from_record(raw)))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,cost=1,attack=1,health=5,metadata=metadata(tribes=())))
    def source(c): return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==KAEL)
    def fail(c): raise ResolutionError('Diagnostic periodic failure')
    def wait(c): return (RequestChoice(c.player_id,(
        ChoiceOption('silence','Silence',(Silence(source(c)),)),
        ChoiceOption('fault','Fail',(Silence(source(c)),InvokeBehavior('fault',c.source_id,c.player_id))),
    ),c.source_id),)
    r.register_behavior('fault',fail); r.register_behavior('wait',wait)
    for name,body in (('waiting','wait'),('failing','fault')):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.MINION,cost=4,health=5,
            battlecry=body,metadata=metadata(tribes=())))
    targeted={'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'plain'),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),)}
    scripts={'noop':lambda c:(), 'summon':lambda c:(Summon(c.player_id,KAEL),),
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy)),)}
    for name,fn in {**targeted,**scripts}.items():
        r.register_behavior(name,fn)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r

class PeriodicPlayTurnCostTests(unittest.TestCase):
    def game(self,hand=('plain',)*6,board=(KAEL,),enemy=(),enemy_hand=('plain',)*4,mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*6,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*6,mana=10,max_mana=10),
        ),seed=130),registry())
    def card(self,g,name='plain',player=1): return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
    def play(self,g,name='plain',target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def fact(self,g,name='plain',player=1): return quote_input(g.state,g.registry,capture_cost_input(g.state.entities[self.card(g,name,player)]))
    def cost(self,g,name='plain',player=1): return self.fact(g,name,player).amount
    def prepare(self,g): self.play(g); self.play(g)
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return s

    def test_full_rows_one_source_and_unverified_spell_origin_are_not_silently_adapted(self):
        p=evidence(); self.assertEqual({x['id'] for x in p['records']},{KAEL,'CORE_REV_021','BT_255'})
        self.assertFalse(p['CN_calibrated']); self.assertFalse(p['formal_pool_verified'])
        self.assertNotIn('BT_255',registry().cards); self.assertEqual(p['new_combinations'],0)

    def test_periodic_interval_is_typed_and_independent_of_other_predicates(self):
        self.assertIsNone(CostAuraSpec(CostSpec()).every_nth_per_turn)
        for n in (True,0,1,-3,3.0,'3'):
            with self.subTest(n=n),self.assertRaises(ValueError): replace(AURA,every_nth_per_turn=n)
        for kw in ({'first_per_turn':True},{'relation':'enemy'},{'tribes_any':('dragon',)},
                {'cost':CostSpec(set_to=1,card_types=(CardType.WEAPON,))}):
            with self.subTest(kw=kw),self.assertRaises(ValueError): replace(AURA,**kw)
        with self.assertRaises(ValueError): GrantCostAura(3,AURA)
        with self.assertRaises(ValueError): Registry('bad').register_card(replace(registry().card(KAEL),keywords=(Keyword.STARSHIP_PIECE,)))

    def test_third_and_sixth_minions_are_free_without_source_local_budget(self):
        g=self.game(); prices=[]; ordinals=[]
        for _ in range(6):
            prices.append(self.cost(g)); self.play(g)
            paid=g.state.play_history[-1].submitted_cost.quote
            if paid.contributions: ordinals.append(paid.contributions[0].first_play.ordinal)
        self.assertEqual(prices,[1,1,0,1,1,0]); self.assertEqual(ordinals,[3,6])
        self.assertEqual(g.state.players[1].mana,6); self.portable(g)

    def test_generated_and_physical_quotes_share_ordinal_and_are_pure(self):
        g=self.game(); self.prepare(g); before=g.snapshot(); physical=self.fact(g)
        self.assertEqual(physical.contributions[0].first_play.ordinal,3); validate_cost_quote_fact(g.registry,physical)
        generated=capture_generated_quote_fact(g.state,g.registry,1,'plain'); validate_generated_quote_fact(g.registry,generated)
        self.assertEqual((generated.amount,physical.amount),(0,0)); self.assertEqual(g.snapshot(),before)
        self.play(g); self.assertEqual(capture_generated_quote_fact(g.state,g.registry,1,'plain').amount,1)

    def test_unrelated_spell_does_not_advance_minion_ordinal(self):
        g=self.game(hand=('plain','noop','plain','plain')); self.play(g); self.play(g,'noop'); self.play(g)
        fact=self.fact(g); self.assertEqual(fact.amount,0); self.assertEqual(len(fact.contributions[0].first_play.rows),3)
        self.play(g); self.portable(g)

    def test_summoning_source_after_two_plays_keeps_the_upcoming_third(self):
        g=self.game(hand=('plain','plain','summon','plain'),board=()); self.prepare(g)
        self.play(g,'summon'); self.assertEqual(self.cost(g),0); self.play(g); self.portable(g)

    def test_actual_source_play_itself_advances_shared_minion_ordinal(self):
        g=self.game(hand=(KAEL,'plain','plain'),board=()); self.play(g,KAEL)
        self.assertEqual(self.cost(g),1); self.play(g); self.assertEqual(self.cost(g),0)
        self.play(g); self.assertEqual([p.cost for p in g.state.play_history],[8,1,0]); self.portable(g)

    def test_new_actual_turn_and_other_player_keep_separate_ordinals(self):
        g=self.game(enemy=(KAEL,)); self.prepare(g); self.assertEqual((self.cost(g),self.cost(g,player=2)),(0,1))
        g.apply(EndTurn(1)); self.prepare(g); self.assertEqual(self.cost(g,player=2),0)
        g.apply(EndTurn(2)); self.assertEqual(self.cost(g),1); self.portable(g)

    def test_two_physical_sources_do_not_make_adjacent_minions_free(self):
        g=self.game(hand=('plain',)*4,board=(KAEL,KAEL)); self.prepare(g); fact=self.fact(g)
        self.assertEqual((fact.amount,len(fact.modifier_ids)),(0,2)); self.play(g)
        self.assertEqual(self.cost(g),1)
        self.assertEqual(g.state.play_history[-1].cost,0); self.portable(g)

    def test_source_silence_death_return_transform_and_sleep_stop_ordinal_price(self):
        for name in ('silence','destroy','bounce','transform','sleep'):
            with self.subTest(name=name):
                g=self.game(hand=('plain','plain',name,'plain')); self.prepare(g); self.assertEqual(self.cost(g),0)
                self.play(g,name,g.state.players[1].board[0]); self.assertEqual(self.cost(g),1); self.portable(g)

    def test_waking_and_control_change_rejudge_player_history_not_source_uses(self):
        g=self.game(hand=('plain','plain','sleep','wake','plain')); self.prepare(g); source=g.state.players[1].board[0]
        self.play(g,'sleep',source); self.assertEqual(self.cost(g),1); self.play(g,'wake'); self.assertEqual(self.cost(g),0); self.portable(g)
        g=self.game(hand=('plain','plain','control','plain')); self.prepare(g); self.play(g,'control',g.state.players[1].board[0])
        self.assertEqual((self.cost(g),self.cost(g,player=2)),(1,1)); g.apply(EndTurn(1)); self.prepare(g)
        self.assertEqual(self.cost(g,player=2),0); self.portable(g)

    def test_paid_third_waits_and_resumes_after_source_removal_with_original_price(self):
        g=self.game(hand=('plain','plain','waiting','plain')); self.prepare(g); self.play(g,'waiting')
        wait=self.portable(g); paid=g.state.play_history[-1].submitted_cost.quote; self.assertEqual(paid.amount,0)
        h=Game.from_snapshot(deepcopy(wait),registry()); choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('silence',))); h.apply(SelectChoice(1,choice,('silence',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(g.state.play_history[-1].submitted_cost.quote,paid); self.portable(g)

    def test_failed_third_submission_and_failed_choice_keep_correct_commit_boundary(self):
        g=self.game(hand=('plain','plain','failing','plain')); self.prepare(g); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'failing')
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.cost(g),0)
        g=self.game(hand=('plain','plain','waiting','plain')); self.prepare(g); self.play(g,'waiting'); before=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.cost(g),1); self.portable(g)

    def test_zero_mana_third_is_legal_but_fourth_is_not_and_views_hide_operands(self):
        g=self.game(hand=('plain',)*4,mana=2); self.prepare(g)
        self.assertTrue(any(isinstance(a,PlayCard) and a.entity_id==self.card(g) for a in g.legal_actions()))
        before=g.snapshot()
        for player in (1,2):
            view=json.dumps(g.for_player(player).observe())
            for private in ('first_play','contributions','next_entity_id','every_nth_per_turn'): self.assertNotIn(private,view)
        self.assertEqual(g.snapshot(),before); self.play(g); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_frozen_ordinal_cannot_lose_prefix_or_borrow_interval_and_old_schema(self):
        g=self.game(); self.prepare(g); self.play(g); snapshot=self.portable(g)
        for mutation in ('interval','prefix','payer','missing'):
            bad=deepcopy(snapshot); c=bad['state']['play_history'][2]['submitted_cost']['quote']['contributions'][0]
            if mutation=='interval': c['ability']['cost_aura']['every_nth_per_turn']=2
            elif mutation=='prefix': c['first_play']['rows']=c['first_play']['rows'][:1]; c['first_play']['play_history_length']=1
            elif mutation=='payer': c['first_play']['player_id']=2
            else: del c['ability']['cost_aura']['every_nth_per_turn']
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        bad=deepcopy(snapshot); bad['schema_version']=235
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())

if __name__=='__main__': unittest.main()
