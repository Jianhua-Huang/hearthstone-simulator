"""Small reproducible drivers, not a strategic Hearthstone AI."""
from __future__ import annotations

import json
from pathlib import Path

from .actions import Attack, EndTurn, PlayCard, action_from_dict, action_to_dict
from dataclasses import asdict
from .game import Game, Scenario
from .construction import MatchSetup
from .replay import load_replay, save_replay
from .serialization import event_to_dict
from .synthetic import build_registry, demo_scenario
from .rules import Ruleset


def add_commands(commands, positive_int):
    demo = commands.add_parser('demo', help='运行无动画的合成机制演示（不是真实卡池）')
    demo.add_argument('--seed', type=int, default=7)
    demo.add_argument('--max-actions', type=positive_int, default=200)
    demo.add_argument('--replay-out', type=Path)
    demo.add_argument('--events', action='store_true', help='输出每条结算事件')
    simulate = commands.add_parser('simulate', help='按 JSON 场景及操作序列运行所选实验卡包')
    simulate.add_argument('scenario', type=Path)
    simulate.add_argument('--actions', type=Path, required=True)
    simulate.add_argument('--replay-out', type=Path)
    simulate.add_argument('--events', action='store_true')
    simulate.add_argument('--card-set', choices=('synthetic', 'representative'), default='synthetic')
    match = commands.add_parser('match', help='校验卡组并运行洗牌、换牌和正常对局；未提供动作时停在第一个选择')
    match.add_argument('setup', type=Path)
    match.add_argument('--actions', type=Path)
    match.add_argument('--replay-out', type=Path)
    match.add_argument('--snapshot-out', type=Path)
    match.add_argument('--events', action='store_true')
    match.add_argument('--card-set', choices=('synthetic', 'representative'), default='representative')
    replay = commands.add_parser('replay', help='重算回放并验证每步状态与事件摘要')
    replay.add_argument('path', type=Path)
    replay.add_argument('--card-set', choices=('synthetic', 'representative'), default='synthetic')


def choose_demo_action(game):
    """Fixed, deterministic priorities for exercising the engine, not good play."""
    state = game.state
    player = state.players[state.active_player]
    enemy = state.players[3 - player.id]
    actions = game.legal_actions()
    if state.pending_choice is not None:
        return actions[0]
    plays = [action for action in actions if isinstance(action, PlayCard)]
    if plays:
        def priority(action):
            target = state.entities.get(action.target_id)
            # Prefer opposing targets for damage and damaged friendly targets
            # for the explicit friendly-only healing test definition.
            definition = game.registry.card(state.entities[action.entity_id].card_id)
            if definition.target_rule == 'test.friendly':
                target_score = -target.damage if target is not None else 0
            else:
                target_score = 0 if target is not None and target.controller == enemy.id else 1
            return (target_score, action.entity_id, action.target_id or 0, -(action.position or 0))
        return min(plays, key=priority)
    attacks = [action for action in actions if isinstance(action, Attack)]
    if attacks:
        return min(attacks, key=lambda a: (a.defender_id != enemy.hero_id, a.attacker_id, a.defender_id))
    return EndTurn(player.id)


def summary(game):
    state = game.state
    return {'status': state.status, 'winner': state.winner, 'turn': state.turn,
            'actions': state.action_number, 'events': len(game.events), 'state_hash': game.state_hash(),
            'pending_choice': asdict(state.pending_choice) if state.pending_choice is not None else None,
            'opening_stage': state.opening.stage if state.opening is not None else None,
            'deck_policy': game._match_setup.policy.id if game._match_setup is not None else None,
            'players': {str(p.id): {'health': state.entities[p.hero_id].health,
                                     'armor': state.entities[p.hero_id].armor,
                                     'board': len(p.board), 'hand': len(p.hand), 'deck': len(p.deck)}
                        for p in state.players.values()}}


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON field: {key}')
            result[key] = value
        return result
    def reject(value):
        raise ValueError(f'Non-finite JSON number: {value}')
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique, parse_constant=reject)


def run_command(args):
    if getattr(args, 'card_set', 'synthetic') == 'representative':
        from .representative import build_registry as representative_registry
        registry = representative_registry()
        label = '真实代表卡的实验子集'
    else:
        registry = build_registry()
        label = '合成测试机制'
    print(f'规则：{Ruleset().id}；使用{label}，尚未覆盖官方完整规则和真实卡池。')
    if args.command == 'replay':
        game = load_replay(args.path, registry)
        print('回放逐步校验通过。')
    else:
        if args.command == 'demo':
            game = Game.from_scenario(demo_scenario(args.seed), registry)
            steps = range(args.max_actions)
        elif args.command == 'match':
            game = Game.from_decks(MatchSetup.from_dict(_read_json(args.setup)), registry)
            raw_actions = _read_json(args.actions) if args.actions else []
            if not isinstance(raw_actions, list):
                raise ValueError('Action file must contain an array')
            steps = [action_from_dict(action) for action in raw_actions]
        else:
            game = Game.from_scenario(Scenario.from_dict(_read_json(args.scenario)), registry)
            raw_actions = _read_json(args.actions)
            if not isinstance(raw_actions, list):
                raise ValueError('Action file must contain an array')
            # Validate all action schemas before executing the script.
            steps = [action_from_dict(action) for action in raw_actions]
        for step in steps:
            if args.command == 'demo':
                if game.state.status != 'playing':
                    break
                action = choose_demo_action(game)
            else:
                action = step
            result = game.apply(action)
            print(f'{game.state.action_number:03d} {json.dumps(action_to_dict(action), ensure_ascii=False)}')
            if args.events:
                for event in result.events:
                    print('  ' + json.dumps(event_to_dict(event), ensure_ascii=False))
        if args.replay_out:
            save_replay(game, args.replay_out)
            print(f'回放已保存：{args.replay_out.resolve()}')
        if getattr(args, 'snapshot_out', None):
            args.snapshot_out.parent.mkdir(parents=True, exist_ok=True)
            args.snapshot_out.write_text(json.dumps(game.snapshot(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(f'快照已保存：{args.snapshot_out.resolve()}')
        if args.command == 'demo' and game.state.status == 'playing':
            print('演示达到操作上限，对局尚未结束。')
    print(json.dumps(summary(game), ensure_ascii=False, indent=2))
    return 0
