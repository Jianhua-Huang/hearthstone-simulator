"""Actual Flames of Infinity scenarios under an explicit uncalibrated numeric policy."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from hs_sim.engine import Keyword, PlayerSetup, Scenario
from hs_sim.engine.infinite_damage import INFINITE_HEALTH_POLICY, INFINITE_HEALTH_VALUE


def main():
    scenarios = []
    for enemy, expected in ((('CORE_CS2_182', 'CORE_EX1_008'), INFINITE_HEALTH_VALUE),
                            (('CORE_EX1_008',), 0)):
        trace = {}
        def run(game, play, end, submit):
            play(1, 'END_024'); end(1); end(2)
            rows = [row.health_result for row in game.state.damage_history
                    if row.health_result.source_card_id == 'END_024']
            assert len(rows) == 1
            result = rows[0]
            assert (result.damage_kind, result.source_controller, result.damage_dealt) == ('spell', 1, expected)
            assert result.target_card_id == ('CORE_CS2_182' if expected else 'CORE_EX1_008')
            assert not game.state.players[1].secrets
            if not expected:
                survivor = game.state.entities[game.state.players[2].board[0]]
                assert survivor.health == 1 and Keyword.DIVINE_SHIELD not in survivor.keywords
            trace.update(target=result.target_card_id, modified_amount=result.modified_amount,
                         damage_dealt=result.damage_dealt, prevention=result.prevention,
                         random_draws=sum(event.kind == 'random_choice' for event in game.events))
        row = exercise(Scenario((
            PlayerSetup('HERO_08', hand=('END_024',), deck=('CORE_CS2_182',)*2, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, deck=('CORE_CS2_182',)*2, mana=10, max_mana=10)), seed=229), run)
        row.update(trace); scenarios.append(row)
    result = dict(content_version='constructed-cn37-preview-v16', schema_version=SNAPSHOT_SCHEMA_VERSION, formal_pool_complete=False,
                  numeric_policy=INFINITE_HEALTH_POLICY, numeric_cn_calibrated=False, roots=1, scenarios=scenarios,
                  actions=sum(row['actions'] for row in scenarios),
                  checkpoints=sum(len(row['checkpoints']) for row in scenarios), waiting_choices=0)
    assert (result['actions'], result['checkpoints']) == (6, 8)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
