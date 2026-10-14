"""Native first-type cost auras share paid-hand history and live source lifetime."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostAuraSpec, CostSpec, EndTurn,
    FirstPlayCostFact, Game, IllegalAction, Keyword, PlayCard, PlayerSetup,
    Registry, ResolutionError, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.costs import capture_cost_input, capture_generated_quote_fact, quote_input
from hs_sim.engine.dormancy import AwakenMinion, MakeDormant
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GrantCostAura, InvokeBehavior, RequestChoice, ReturnToHand, Silence, Summon, Transform)
from hs_sim.engine.intrinsic_costs import validate_generated_quote_fact
from hs_sim.engine.representative import metadata_from_record
from hs_sim.engine.repeat_matching import validate_cost_quote_fact
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata

ROOT=Path(__file__).resolve().parents[1]
PIN='08c44555a4c077a927ebf50a3acc2d241dc806fea2b69cb5bd848a0dc53efa4b'
SUMMONER='EX1_076'
AURA=CostAuraSpec(CostSpec(delta=-1,card_types=(CardType.MINION,)),first_per_turn=True)
SPELL_AURA=CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.SPELL,)),first_per_turn=True)

def evidence():
    value=json.loads((ROOT/'data/support/first-play-turn-cost-basics.json').read_bytes())
    if canonical_digest(value)!=PIN: raise ValueError('First-play full raw evidence changed')
    return value

def registry():
    r=Registry('isolated-first-play-turn-cost-basics-v1')
    r.register_card(CardDefinition('hero','Diagnostic hero',CardType.HERO,health=60,metadata=metadata()))
    x=next(x for x in evidence()['records'] if x['id']==SUMMONER)
    r.register_card(CardDefinition(SUMMONER,x['name'],CardType.MINION,cost=x['cost'],attack=x['attack'],health=x['health'],
        metadata=metadata_from_record(x),cost_auras=(AURA,)))
    r.register_card(CardDefinition('plain','Diagnostic minion',CardType.MINION,cost=3,attack=2,health=5,metadata=metadata(tribes=())))
    r.register_card(CardDefinition('spell-aura','Diagnostic first-spell aura',CardType.MINION,health=5,
        cost_auras=(SPELL_AURA,),metadata=metadata(tribes=())))
    r.register_behavior('noop',lambda c:())
    r.register_card(CardDefinition('spell','Diagnostic spell',CardType.SPELL,cost=3,on_play='noop',metadata=metadata()))
    def source(c): return next(i for i in c.state.players[c.player_id].board if c.state.entities[i].card_id==SUMMONER)
    def fail(c): raise ResolutionError('Diagnostic first-play failure')
    def wait(c): return (RequestChoice(c.player_id,(
        ChoiceOption('silence','Silence',(Silence(source(c)),)),
        ChoiceOption('fault','Fail',(Silence(source(c)),InvokeBehavior('fault',c.source_id,c.player_id))),
    ),c.source_id),)
    r.register_behavior('fault',fail); r.register_behavior('wait',wait)
    for name,body in (('waiting','wait'),('failing','fault')):
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.MINION,cost=3,health=5,battlecry=body,metadata=metadata(tribes=())))
    targeted={'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'plain'),),
        'control':lambda c:(ChangeControl(c.target_id,2),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'sleep':lambda c:(MakeDormant(c.target_id,None),)}
    scripts={'summon':lambda c:(Summon(c.player_id,SUMMONER),),
        'wake':lambda c:(AwakenMinion(next(i for i in c.state.players[c.player_id].board if c.state.entities[i].dormancy)),)}
    for name,fn in {**targeted,**scripts}.items():
        r.register_behavior(name,fn)
        r.register_card(CardDefinition(name,'Diagnostic '+name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r

class FirstPlayTurnCostTests(unittest.TestCase):
    def game(self,hand=('plain','plain'),board=(SUMMONER,),enemy=(),enemy_hand=('plain','plain'),mana=10):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*5,mana=mana,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*5,mana=10,max_mana=10),
        ),seed=129),registry())
    def card(self,g,name='plain',player=1): return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id==name)
    def play(self,g,name='plain',target=None): return g.apply(PlayCard(g.state.active_player,self.card(g,name,g.state.active_player),target))
    def cost(self,g,name='plain',player=1): return self.fact(g,name,player).amount
    def fact(self,g,name='plain',player=1):
        return quote_input(g.state,g.registry,capture_cost_input(g.state.entities[self.card(g,name,player)]))
    def portable(self,g):
        s=g.snapshot(); self.assertEqual(Game.from_snapshot(json.loads(json.dumps(s)),registry()).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s); self.assertEqual(replay(build_replay(g),registry()).snapshot(),s)
        return s

    def test_three_complete_rows_one_native_adapter_and_no_full_scope_claim(self):
        value=evidence(); self.assertEqual({x['id'] for x in value['records']},{SUMMONER,'DAL_609','CORE_DAL_609'})
        self.assertFalse(value['full_card_adaptation']); self.assertFalse(value['CN_calibrated'])
        self.assertEqual(value['new_combinations'],0)

    def test_strict_native_qualifier_rejects_unreviewed_filters_and_grants(self):
        self.assertFalse(CostAuraSpec(CostSpec()).first_per_turn)
        for fields in ({'first_per_turn':1},{'relation':'enemy'},{'tribes_any':('mech',)},
                {'cost':CostSpec(delta=-1)},{'cost':CostSpec(delta=-1,card_types=(CardType.MINION,),card_ids=('plain',))}):
            with self.subTest(fields=fields),self.assertRaises(ValueError): replace(AURA,**fields)
        with self.assertRaises(ValueError): GrantCostAura(3,AURA)
        with self.assertRaises(ValueError): Registry('bad').register_card(replace(registry().card(SUMMONER),keywords=(Keyword.MAGNETIC,)))

    def test_first_minion_quote_payment_and_all_later_minions_use_same_player_history(self):
        g=self.game(); q=self.fact(g); self.assertEqual(q.amount,2)
        self.assertTrue(q.contributions[0].first_play.is_first); validate_cost_quote_fact(g.registry,q)
        self.play(g); self.assertEqual((g.state.players[1].mana,self.cost(g)),(8,3))
        paid=g.state.play_history[0].submitted_cost.quote
        self.assertEqual((paid.amount,paid.modifier_ids),(q.amount,q.modifier_ids)); self.portable(g)

    def test_queries_do_not_consume_history_or_leak_price_operands(self):
        g=self.game(); before=g.snapshot(); own=g.for_player(1).observe(); other=g.for_player(2).observe()
        for _ in range(2): self.fact(g); g.legal_actions(); g.for_player(1).observe()
        self.assertEqual(g.snapshot(),before); self.assertEqual(g.for_player(1).observe(),own); self.assertEqual(g.for_player(2).observe(),other)
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe())
            for private in ('first_play','contributions','next_entity_id','play_history'): self.assertNotIn(private,text)

    def test_unrelated_spell_does_not_spend_minion_qualification_and_prefix_keeps_it(self):
        g=self.game(hand=('spell','plain','plain')); self.play(g,'spell')
        q=self.fact(g); self.assertEqual(q.amount,2); self.assertEqual(len(q.contributions[0].first_play.rows),1)
        self.play(g); self.assertEqual(self.cost(g),3); self.portable(g)

    def test_playing_source_is_already_a_first_minion_before_its_aura_enters(self):
        g=self.game(hand=(SUMMONER,'plain'),board=()); self.play(g,SUMMONER)
        self.assertEqual((g.state.play_history[0].cost,self.cost(g)),(2,3)); self.portable(g)

    def test_summoning_source_does_not_reset_prior_player_history(self):
        for first in (False,True):
            with self.subTest(first=first):
                g=self.game(hand=('plain','summon','plain'),board=())
                if first: self.play(g)
                self.play(g,'summon'); self.assertEqual(self.cost(g),3 if first else 2); self.portable(g)

    def test_two_physical_sources_share_first_minion_and_each_contributes_once(self):
        g=self.game(board=(SUMMONER,SUMMONER)); q=self.fact(g); self.assertEqual(q.amount,1)
        self.assertEqual(len(set(q.modifier_ids)),2); self.play(g); self.assertEqual(self.cost(g),3); self.portable(g)

    def test_each_actual_turn_reopens_qualification_and_other_player_is_independent(self):
        g=self.game(enemy=(SUMMONER,)); self.play(g); self.assertEqual(self.cost(g,player=2),2)
        g.apply(EndTurn(1)); self.play(g); self.assertEqual(self.cost(g,player=2),3)
        g.apply(EndTurn(2)); self.assertEqual(self.cost(g),2); self.portable(g)

    def test_source_removal_silence_return_transform_and_sleep_use_existing_lifetime(self):
        for name in ('silence','destroy','bounce','transform','sleep'):
            with self.subTest(name=name):
                g=self.game(hand=(name,'plain')); target=g.state.players[1].board[0]
                self.assertEqual(self.cost(g),2); self.play(g,name,target); self.assertEqual(self.cost(g),3); self.portable(g)

    def test_waking_source_uses_current_player_history_without_new_budget(self):
        g=self.game(hand=('sleep','wake','plain','plain')); source=g.state.players[1].board[0]
        self.play(g,'sleep',source); self.play(g); self.play(g,'wake'); self.assertEqual(self.cost(g),3); self.portable(g)

    def test_control_change_moves_aura_but_does_not_move_player_play_history(self):
        g=self.game(hand=('control','plain')); source=g.state.players[1].board[0]; self.play(g,'control',source)
        self.assertEqual((self.cost(g),self.cost(g,player=2)),(3,2))
        g.apply(EndTurn(1)); self.play(g); self.assertEqual(self.cost(g,player=2),3); self.portable(g)

    def test_generated_quote_uses_same_first_rule_without_creation_or_consumption(self):
        g=self.game(); before=g.snapshot(); fact=capture_generated_quote_fact(g.state,g.registry,1,'plain')
        validate_generated_quote_fact(g.registry,fact); self.assertEqual(fact.amount,2); self.assertEqual(g.snapshot(),before)
        self.play(g); fact=capture_generated_quote_fact(g.state,g.registry,1,'plain')
        self.assertEqual(fact.amount,3); validate_generated_quote_fact(g.registry,fact)

    def test_spell_set_zero_qualifier_uses_spell_type_and_same_shared_quote(self):
        g=self.game(hand=('spell','spell','plain'),board=('spell-aura',))
        self.assertEqual((self.cost(g,'spell'),self.cost(g)),(0,3))
        self.play(g); self.assertEqual(self.cost(g,'spell'),0)
        self.play(g,'spell'); self.assertEqual((g.state.play_history[-1].cost,self.cost(g,'spell')),(0,3)); self.portable(g)

    def test_waiting_paid_first_minion_recovers_then_source_silence_keeps_old_price(self):
        g=self.game(hand=('waiting','plain')); self.play(g,'waiting'); self.assertEqual(self.cost(g),3)
        wait=self.portable(g); h=Game.from_snapshot(deepcopy(wait),registry())
        choice=g.state.pending_choice.id
        g.apply(SelectChoice(1,choice,('silence',))); h.apply(SelectChoice(1,choice,('silence',)))
        self.assertEqual(g.snapshot(),h.snapshot()); self.assertEqual(g.state.play_history[0].cost,2); self.portable(g)

    def test_failed_paid_first_minion_rolls_back_payment_history_and_qualification(self):
        g=self.game(hand=('failing','plain')); before=g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g,'failing')
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.cost(g),2)

    def test_failed_choice_retains_prior_paid_qualification_and_original_wait(self):
        g=self.game(hand=('waiting','plain')); self.play(g,'waiting'); before=g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(SelectChoice(1,g.state.pending_choice.id,('fault',)))
        self.assertEqual(g.snapshot(),before); self.assertEqual(self.cost(g),3); self.portable(g)

    def test_low_mana_legal_enumeration_matches_first_price_and_failure_is_atomic(self):
        g=self.game(mana=2); self.assertTrue(any(isinstance(a,PlayCard) and a.entity_id==self.card(g) for a in g.legal_actions()))
        self.play(g); before=g.snapshot()
        with self.assertRaises(IllegalAction): self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_tampered_prefix_payer_clock_native_declaration_and_old_schema_rejected(self):
        g=self.game(hand=('spell','plain','plain')); self.play(g,'spell'); self.play(g); snapshot=g.snapshot()
        contribution=snapshot['state']['play_history'][1]['submitted_cost']['quote']['contributions'][0]
        for mutation in ('prefix','payer','clock','native','missing'):
            bad=deepcopy(snapshot); c=bad['state']['play_history'][1]['submitted_cost']['quote']['contributions'][0]
            if mutation=='prefix': c['first_play']['rows']=[]; c['first_play']['play_history_length']=0
            elif mutation=='payer': c['first_play']['player_id']=2
            elif mutation=='clock': c['first_play']['turn']+=1
            elif mutation=='native': c['ability']['cost_aura']['first_per_turn']=False
            else: del c['first_play']
            with self.subTest(mutation=mutation),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        for version in (1,233,234):
            bad=deepcopy(snapshot); bad['schema_version']=version
            with self.subTest(version=version),self.assertRaises(SnapshotError): Game.from_snapshot(bad,registry())
        self.assertEqual(contribution['first_play']['play_history_length'],1)

if __name__=='__main__': unittest.main()
