"""Synthetic H2 public-player example; internal prototype, no CN calibration."""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    CostSpec, Game, IntrinsicCostSpec, PlayerSetup, Registry, Scenario,
    SpellSchool, TriggerSpec)
from hs_sim.engine.costs import capture_cost_input, capture_quote_fact, capture_generated_quote_fact
from hs_sim.engine.effects import AddCostModifier, ChoiceOption, GainArmor, ModifyCost, RequestChoice
from hs_sim.engine.replay import build_replay, replay


MINION = 'native.h2.minion'
SPELL = 'native.h2.arcane'
FALSE = 'native.h2.fire'
PREP = 'native.h2.prepare'
WATCH = 'native.h2.watcher'


def build_registry():
    registry = Registry('intrinsic-cost-native-v1')
    empty = CardMetadata(False, (CardClass.MAGE,), None, tribes=())
    def meta(tribes): return CardMetadata(False, (CardClass.MAGE,), None, tribes=tribes)
    for name in ('hero.one', 'hero.two'):
        registry.register_card(CardDefinition(name, name, CardType.HERO, health=30, metadata=empty))
    registry.register_behavior('nothing', lambda c: [])
    registry.register_behavior('body-choice', lambda c: [RequestChoice(c.player_id,
        (ChoiceOption('ok', 'Resolve body', (GainArmor(c.player_id, 1),)),), source_id=c.source_id)])
    def after_play(c):
        if c.play is None or c.play.card_id != MINION or c.play.player_id != c.player_id: return []
        return [RequestChoice(c.player_id, (ChoiceOption('ok', 'Resolve card_played reaction',
            (GainArmor(c.player_id, 1),)),), source_id=c.source_id)]
    registry.register_behavior('after-play', after_play)
    def prepare(c):
        sources = [i for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id == SPELL]
        return [*(ModifyCost(i, CostSpec(delta=1), c.source_id) for i in sources),
            AddCostModifier(c.player_id, CostSpec(delta=-1, card_types=(CardType.SPELL,),
                card_ids=(SPELL,)), uses_remaining=1, source_id=c.source_id)]
    registry.register_behavior('prepare', prepare)
    for name, tribes in (('dragon', ('dragon',)), ('beast', ('beast',)), ('hidden', ())):
        registry.register_card(CardDefinition(name, name, CardType.MINION,
            attack=1, health=4, metadata=meta(tribes)))
    for name, school in (('arcane', SpellSchool.ARCANE), ('frost', SpellSchool.FROST), ('unschooled', None)):
        registry.register_card(CardDefinition(name, name, CardType.SPELL,
            on_play='nothing', spell_school=school, metadata=empty))
    registry.register_card(CardDefinition(PREP, PREP, CardType.SPELL, on_play='prepare', metadata=empty))
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=8, metadata=empty,
        triggers=(TriggerSpec('card_played', 'after-play'),)))
    registry.register_card(CardDefinition(MINION, MINION, CardType.MINION, cost=5, attack=1, health=5,
        metadata=meta(('dragon',)), battlecry='body-choice', intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
    for name, school in ((SPELL, SpellSchool.ARCANE), (FALSE, SpellSchool.FIRE)):
        registry.register_card(CardDefinition(name, name, CardType.SPELL, cost=5, metadata=empty,
            spell_school=school, on_play='body-choice', intrinsic_costs=(IntrinsicCostSpec(delta=-3),)))
    return registry


def submit(game, kind, card_id=None, position=None):
    player = game.state.pending_choice.player_id if game.state.pending_choice else game.state.active_player
    port = game.for_player(player)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    actions = [a for a in listing['actions'] if a['type'] == kind]
    if card_id is not None:
        own = next(p for p in listing['observation']['players'] if p['id'] == player)
        reference = next(c['ref'] for c in own['hand'] if c['card_id'] == card_id)
        actions = [a for a in actions if a['card'] == reference]
    if position is not None: actions = [a for a in actions if a.get('position') == position]
    assert len(actions) == 1, (kind, card_id, actions)
    result = port.submit({'revision': listing['revision'], 'action': actions[0]})
    assert result['accepted'], result


def player_boundary(game):
    forbidden = ('owner_turn_history', 'played_face', 'submitted_cost', 'intrinsic',
        'condition_facts', 'paid_hand_close', 'paid_hand_interrupt', 'paid_hand_acceptances',
        'paid_hand_choice_boundary', '_paid_hand_choice_boundary',
        'resolution_frame', 'cost_use_history', 'rng_state')
    for pid in (1, 2):
        port = game.for_player(pid)
        encoded = json.dumps((port.observe(), port.legal_actions(), port.events()), sort_keys=True)
        assert all('"'+name+'"' not in encoded for name in forbidden), encoded
        observation = port.observe()['observation']
        own = next(p for p in observation['players'] if p['id'] == pid)
        enemy = next(p for p in observation['players'] if p['id'] == 3-pid)
        assert all(card['card_id'] is None and 'cost' not in card for card in enemy['hand'])
        assert all('card_id' in card and 'cost' in card for card in own['hand'])


def portable(game):
    saved = json.loads(json.dumps(game.snapshot()))
    branches = (Game.from_snapshot(saved, build_registry()), game.clone(),
                replay(build_replay(game), build_registry()))
    for branch in branches:
        assert branch.snapshot() == saved
        for pid in (1, 2): assert branch.for_player(pid).observe() == game.for_player(pid).observe()
        player_boundary(branch)
    return saved, list(branches)


def quote(game, pid, card_id):
    source = next(game.state.entities[i] for i in game.state.players[pid].hand
                  if game.state.entities[i].card_id == card_id)
    return capture_quote_fact(game.state, game.registry, capture_cost_input(source))


def summarize_quote(fact):
    condition, = fact.intrinsic.condition_facts
    return {'intrinsic': fact.intrinsic.amount, 'local': fact.local_amount, 'amount': fact.amount,
        'owner_turn': None if condition.owner_turn is None else condition.owner_turn.id,
        'matched': condition.matched, 'rows': [row.matched for row in condition.rows]}


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero.one', hand=('beast','dragon','unschooled','arcane',PREP,MINION,SPELL,SPELL,FALSE),
            board=(WATCH,), deck=('hidden',)*8, mana=10, max_mana=10),
        PlayerSetup('hero.two', hand=('beast','frost',MINION,SPELL,'hidden'),
            board=(WATCH,), deck=('hidden',)*8, mana=10, max_mana=10)), seed=159), build_registry())
    branches, waiting, checkpoints = [], [], []
    def step(kind, card=None, position=None):
        nonlocal branches
        submit(game, kind, card, position)
        for branch in branches:
            submit(branch, kind, card, position)
            assert branch.snapshot() == game.snapshot()
        branches = []
        player_boundary(game)
        if game.state.pending_choice:
            saved, branches = portable(game)
            root = game.state.play_history[-1]
            assert root.submitted_cost is not None
            if root.kind is CardType.MINION:
                assert root.paid_hand_close is None
                assert root.id in game._frame.paid_hand_acceptances
            waiting.append(saved)
            checkpoints.append({'card':root.card_id, 'completed':root.completed,
                'cost':root.cost, 'action':game.state.action_number})
    for card in ('beast','dragon'): step('play_card', card, 0)
    for card in ('unschooled','arcane',PREP): step('play_card',card)
    step('end_turn')
    step('play_card','beast',0); step('play_card','frost'); step('end_turn')
    quotes = {f'p{pid}.{card}': summarize_quote(quote(game,pid,card))
              for pid in (1,2) for card in (MINION,SPELL)}
    quotes['p1.false'] = summarize_quote(quote(game,1,FALSE))
    assert [quotes[f'p{pid}.{card}']['amount'] for pid in (1,2) for card in (MINION,SPELL)] == [2,2,5,5]
    assert quotes['p1.false']['rows'] == [False,False,False]
    before = game.snapshot()
    generated = capture_generated_quote_fact(game.state,game.registry,1,SPELL,cost=CostSpec(set_to=4))
    floor = capture_generated_quote_fact(game.state,game.registry,1,SPELL,cost=CostSpec(set_to=4),minimum_cost=6)
    assert (generated.intrinsic.amount,generated.local_amount,generated.amount,floor.amount) == (2,4,3,6)
    assert game.snapshot() == before
    step('play_card',MINION,0); step('select_choice'); step('select_choice')
    assert game.state.play_history[-1].paid_hand_close is not None
    step('play_card',SPELL); step('select_choice')
    quotes['p1.after-finite-use'] = summarize_quote(quote(game,1,SPELL))
    assert quotes['p1.after-finite-use']['amount'] == 3
    step('end_turn')
    step('play_card',MINION,0); step('select_choice'); step('select_choice')
    step('play_card',SPELL); step('select_choice')
    assert [p.cost for p in game.state.play_history[-4:]] == [2,2,5,5]
    assert len(waiting) == 6
    assert all(p.completed for p in game.state.play_history)
    assert all(p.paid_hand_close is not None for p in game.state.play_history if p.kind is CardType.MINION)
    portable(game)
    return game,waiting,checkpoints,quotes,{'intrinsic':generated.intrinsic.amount,
        'initial':generated.local_amount,'external':generated.amount,'minimum_final':floor.amount}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--replay')
    parser.add_argument('--output-dir',required=False)
    args=parser.parse_args()
    if args.replay:
        game=replay(json.loads(Path(args.replay).read_text(encoding='utf-8')),build_registry())
        print(json.dumps({'replayed':True,'actions':len(game.history),'state_hash':game.state_hash()})); return
    game,waiting,checkpoints,quotes,generated=run()
    summary={'candidate_installed':True,'synthetic':True,'cn_calibrated':False,'real_cards_added':0,
        'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'waiting':len(waiting),'checkpoints':checkpoints,'quotes':quotes,'generated':generated,
        'paid_amounts':[p.cost for p in game.state.play_history],
        'restored_cloned_replayed':True,'both_player_boundaries':True}
    if args.output_dir:
        output=Path(args.output_dir).resolve(); output.mkdir(parents=True,exist_ok=True)
        for name,value in (('summary',summary),('snapshot',game.snapshot()),('waiting',waiting),
                           ('replay',build_replay(game)),('view1',game.observe(1)),('view2',game.observe(2))):
            with (output/(name+'.json')).open('x',encoding='utf-8') as stream: json.dump(value,stream,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__': main()
