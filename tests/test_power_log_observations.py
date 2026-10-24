"""Client evidence must retain observation time and expose incomplete parsing."""
from contextlib import redirect_stderr, redirect_stdout
import gzip
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import import_power_log as log


ALICE = 'PrivateAlice#12345'
BOB = 'PrivateBob#67890'


def descriptor(eid=8, card='', zone='HAND', name='PrivateDisplayName', player=1):
    return f'[entityName={name} id={eid} zone={zone} zonePos=1 cardId={card} player={player}]'


def power(text):
    return 'GameState.DebugPrintPower() - ' + text


def lines(*records):
    return ('\n'.join('D 20:46:22.1234567 ' + r for r in records) + '\n').encode('utf-8')


def opening(build=255026):
    return [power('CREATE_GAME'), power('GameEntity EntityID=1'),
            power('tag=TURN value=0'),
            power('Player EntityID=2 PlayerID=1 GameAccountId=[hi=123456789 lo=987654321]'),
            power('Player EntityID=3 PlayerID=2 GameAccountId=[hi=123456789 lo=123456789]'),
            'GameState.DebugPrintGame() - BuildNumber=' + str(build),
            'GameState.DebugPrintGame() - GameType=GT_RANKED',
            'GameState.DebugPrintGame() - FormatType=FT_STANDARD',
            'GameState.DebugPrintGame() - ScenarioID=2',
            'GameState.DebugPrintGame() - PlayerID=1, PlayerName=' + ALICE,
            'GameState.DebugPrintGame() - PlayerID=2, PlayerName=' + BOB]


class PowerLogObservationTests(unittest.TestCase):
    def parse(self, *records):
        return log.parse_bytes(lines(*opening(), *records))

    def clean(self, result):
        self.assertEqual(result['coverage']['issues'], [])
        self.assertTrue(result['coverage']['selected_stream_parse_complete'])

    def test_nested_damage_death_and_subspell_keep_order_and_real_packet_parent(self):
        entity = descriptor(8, 'TLC_600', zone='PLAY')
        result = self.parse(
            power(f'BLOCK_START BlockType=ATTACK Entity={entity} EffectCardId= EffectIndex=-1 Target=3 SubOption=-1 TriggerKeyword=TAG_NOT_SET'),
            power(f'TAG_CHANGE Entity={entity} tag=DAMAGE value=3'),
            power('SUB_SPELL_START - SpellPrefabGUID=Test:1234 Source=8 TargetCount=1'),
            power('Source = ' + entity), power('Targets[0] = 3'),
            power('META_DATA - Meta=DAMAGE Data=3 InfoCount=1'),
            power('Info[0] = 3'), power('SUB_SPELL_END'),
            power(f'TAG_CHANGE Entity={entity} tag=ZONE value=GRAVEYARD'), power('BLOCK_END'))
        self.clean(result)
        events = result['events'][-10:]
        self.assertEqual([e['kind'] for e in events], [
            'block_start', 'tag_change', 'sub_spell_start', 'sub_spell_source',
            'sub_spell_target', 'metadata', 'metadata_info', 'sub_spell_end', 'tag_change', 'block_end'])
        self.assertEqual(events[1]['parent'], events[0]['line'])
        self.assertEqual(events[6]['parent'], events[2]['line'])
        self.assertEqual(events[6]['packet_line'], events[5]['line'])
        self.assertEqual(events[7]['start_line'], events[2]['line'])
        self.assertEqual(events[9]['start_line'], events[0]['line'])
        self.assertEqual(events[8]['value'], 'GRAVEYARD')
        self.assertEqual(events[0]['time'], '20:46:22.1234567')
        self.assertEqual(result['games'][0]['metadata']['BuildNumber'], 255026)

    def test_duplicate_renderer_is_excluded_without_deduplicating_real_equal_events(self):
        records = [power('TAG_CHANGE Entity=1 tag=TURN value=1')] * 2
        duplicates = [r.replace('GameState.', 'PowerTaskList.') for r in records]
        result = self.parse(*records, *duplicates)
        self.clean(result)
        self.assertEqual(len([e for e in result['events'] if e['kind'] == 'tag_change']), 2)
        self.assertEqual(result['coverage']['counts']['excluded_power_task_list_lines'], 2)

    def test_later_reveal_and_transform_do_not_backfill_hidden_hand_identity(self):
        hidden = descriptor()
        result = self.parse(power('FULL_ENTITY - Creating ID=8 CardID='),
                            power('tag=ZONE value=HAND'),
                            power(f'TAG_CHANGE Entity={hidden} tag=COST value=2'),
                            power(f'SHOW_ENTITY - Updating Entity={hidden} CardID=TLC_600'),
                            power(f'CHANGE_ENTITY - Updating Entity={descriptor(card="TLC_600")} CardID=GAME_005'),
                            power(f'HIDE_ENTITY - Entity={descriptor(card="GAME_005")} tag=ZONE value=DECK'))
        self.clean(result)
        events = result['events'][-6:]
        self.assertIsNone(events[0]['card_id'])
        self.assertIsNone(events[2]['entity']['card_id'])
        self.assertIsNone(events[3]['entity']['card_id'])
        self.assertEqual(events[3]['card_id'], 'TLC_600')
        self.assertEqual(events[4]['card_id'], 'GAME_005')
        self.assertFalse(result['boundary']['later_reveals_backfilled'])

    def test_account_names_and_unparsed_text_never_leave_memory(self):
        result = self.parse(power(f'TAG_CHANGE Entity={ALICE} tag=ARMOR value=2'),
                            power('TAG_CHANGE Entity=SecretUnresolvedPlayer tag=HEALTH value=30'),
                            power('FUTURE_PACKET PrivateSecretToken account=SecretAccount'),
                            power('TAG_CHANGE Entity=1 tag=99999 value=-1'))
        serialized = json.dumps(result)
        for secret in (ALICE, BOB, '987654321', '123456789', 'SecretUnresolvedPlayer',
                       'PrivateSecretToken', 'SecretAccount'):
            self.assertNotIn(secret, serialized)
        tags = [e for e in result['events'] if e['kind'] == 'tag_change']
        self.assertEqual(tags[0]['entity'], {'entity_id': 2})
        self.assertEqual(tags[1]['entity'], {'opaque_ref': 1})
        self.assertEqual((tags[2]['tag'], tags[2]['value']), (99999, -1))
        self.assertFalse(result['coverage']['selected_stream_parse_complete'])

    def test_empty_or_duplicate_only_file_is_not_a_successful_capture(self):
        for raw in (b'', lines('PowerTaskList.DebugPrintPower() - CREATE_GAME')):
            with self.subTest(raw=raw):
                result = log.parse_bytes(raw)
                self.assertFalse(result['coverage']['selected_stream_parse_complete'])
                self.assertIn('no_canonical_games', [i['code'] for i in result['coverage']['issues']])

    def test_unknown_records_or_partial_line_remain_explicit_failures(self):
        result = self.parse(power('FUTURE_PACKET value=77'),
                            'GameState.FutureHandler() - PrivateName',
                            power('SHOW_ENTITY - Updating Entity='))
        self.assertEqual(len(result['coverage']['issues']), 3)
        self.assertNotIn('PrivateName', json.dumps(result))
        self.assertFalse(result['coverage']['selected_stream_parse_complete'])

    def test_unbalanced_blocks_and_incomplete_metadata_are_reported(self):
        result = self.parse(power('BLOCK_END'),
                            power('BLOCK_START BlockType=TRIGGER Entity=1 EffectCardId= EffectIndex=-1 Target=0'),
                            power('META_DATA - Meta=DAMAGE Data=3 InfoCount=2'),
                            power('Info[0] = 2'))
        codes = {i['code'] for i in result['coverage']['issues']}
        self.assertEqual(codes, {'unmatched_block_end', 'incomplete_or_duplicate_detail_list',
                                 'unclosed_blocks_at_eof'})

    def test_detail_list_indices_are_checked_even_when_item_counts_match(self):
        result = self.parse(power('META_DATA - Meta=DAMAGE Data=3 InfoCount=2'),
                            power('Info[0] = 2'), power('Info[0] = 3'))
        codes = {i['code'] for i in result['coverage']['issues']}
        self.assertIn('invalid_detail_index', codes)
        self.assertIn('incomplete_or_duplicate_detail_list', codes)

    def test_choice_offers_submissions_and_server_choices_have_separate_contexts(self):
        option = descriptor(20, 'TLC_600', 'SETASIDE')
        result = self.parse(
            'GameState.OnEntityChoices() - id=4 playerId=1 queued',
            f'GameState.DebugPrintEntityChoices() - id=4 Player={ALICE} TaskList=77 ChoiceType=GENERAL CountMin=1 CountMax=1',
            'GameState.DebugPrintEntityChoices() - Source=8',
            'GameState.DebugPrintEntityChoices() - Entities[0]=' + option,
            'GameState.SendChoices() - id=4 ChoiceType=GENERAL',
            'GameState.SendChoices() - m_chosenEntities[0]=' + option,
            f'GameState.DebugPrintEntitiesChosen() - id=4 Player={ALICE} EntitiesCount=1',
            'GameState.DebugPrintEntitiesChosen() - Entities[0]=' + option)
        self.clean(result)
        self.assertEqual(result['events'][-8]['kind'], 'choice_queued')
        self.assertEqual(result['events'][-8]['player_id'], 1)
        events = result['events'][-7:]
        self.assertEqual([e['kind'] for e in events], ['choice', 'choice_source', 'choice_entity',
                         'send_choices', 'send_choices_entity', 'chosen', 'chosen_entity'])
        self.assertTrue(all(e['choice_id'] == 4 for e in events))
        self.assertEqual(events[0]['player'], {'entity_id': 2})
        self.assertEqual(events[-1]['entity']['entity_id'], 20)

    def test_truncated_chosen_list_and_orphan_items_are_not_accepted(self):
        result = self.parse(
            'GameState.SendChoices() - m_chosenEntities[0]=' + descriptor(),
            'GameState.DebugPrintEntitiesChosen() - id=4 Player=2 EntitiesCount=2',
            'GameState.DebugPrintEntitiesChosen() - Entities[0]=8')
        codes = {i['code'] for i in result['coverage']['issues']}
        self.assertEqual(codes, {'orphan_choice_item', 'incomplete_chosen_list'})

    def test_options_errors_and_actual_selected_action_retain_menu_identity(self):
        result = self.parse('GameState.DebugPrintOptions() - id=9',
                            'GameState.DebugPrintOptions() - option 0 type=END_TURN mainEntity= error=INVALID errorParam=',
                            'GameState.DebugPrintOptions() - option 1 type=POWER mainEntity=' + descriptor(),
                            'GameState.DebugPrintOptions() - target 0 entity=3 error=NONE errorParam=',
                            'GameState.DebugPrintOptions() - subOption 0 entity=8',
                            'GameState.SendOption() - selectedOption=1 selectedSubOption=-1 selectedTarget=3 selectedPosition=0')
        self.clean(result)
        events = result['events'][-6:]
        self.assertIsNone(events[1]['entity'])
        self.assertEqual(events[1]['error'], 'INVALID')
        self.assertEqual(events[3]['option_index'], 1)
        self.assertEqual(events[-1]['options_id'], 9)
        self.assertEqual(events[-1]['target'], 3)

    def test_games_keep_their_own_build_metadata_turns_and_entity_id_scopes(self):
        result = log.parse_bytes(lines(*opening(254477),
            power('TAG_CHANGE Entity=1 tag=TURN value=5'), *opening(255026),
            power('TAG_CHANGE Entity=1 tag=TURN value=1')))
        self.clean(result)
        self.assertEqual([g['metadata']['BuildNumber'] for g in result['games']], [254477, 255026])
        self.assertEqual([g['first_observed_turn'] for g in result['games']], [0, 0])
        self.assertEqual(result['games'][0]['end_line'] + 1, result['games'][1]['start_line'])
        turns = [e for e in result['events'] if e['kind'] == 'tag_change']
        self.assertEqual([e['game'] for e in turns], [1, 2])

    def test_nonserialized_effect_ids_remain_unknown_instead_of_inventing_a_card(self):
        result = self.parse(power('BLOCK_START BlockType=TRIGGER Entity=1 EffectCardId=' +
                            log.COLLECTION + ' EffectIndex=-1 Target=0'), power('BLOCK_END'))
        self.clean(result)
        self.assertEqual(result['events'][-2]['effect_card_id'], {'unavailable': 'client_collection_string'})
        self.assertEqual(result['coverage']['counts']['unavailable_effect_card_ids'], 1)
        for key in ('complete_server_execution', 'full_game_capture_verified', 'cn_region_verified',
                    'fixed_target_verified', 'accepted_calibration_case', 'player_dto'):
            self.assertFalse(result['boundary'][key])

    def test_malformed_scalar_or_descriptor_cannot_escape_into_export(self):
        result = self.parse(power('TAG_CHANGE Entity=1 tag=HEALTH value=Private value'),
                            power('SHOW_ENTITY - Updating Entity=[SecretMalformedName] CardID=TLC_600'))
        self.assertFalse(result['coverage']['selected_stream_parse_complete'])
        self.assertNotIn('SecretMalformedName', json.dumps(result))
        self.assertNotIn('Private value', json.dumps(result))

    def test_invalid_encoding_nul_and_nonbytes_are_rejected_without_replacement(self):
        for raw in (b'\xff', b'\x00'):
            with self.assertRaises(ValueError):
                log.parse_bytes(raw)
        with self.assertRaises(TypeError):
            log.parse_bytes('not bytes')
        result = log.parse_bytes(b'\xef\xbb\xbf' + lines(*opening()))
        self.clean(result)

    def test_observed_prefab_apostrophe_signed_tags_and_nonpower_diagnostics(self):
        result = log.parse_bytes(lines(
            'GameState.DebugPrintPowerList() - Count=72', *opening(),
            power('FULL_ENTITY - Creating ID=8 CardID=TLC_600'),
            power('tag=COST value=-1'),
            power("SUB_SPELL_START - SpellPrefabGUID=CATAFX_Al'Akir_SpawntoHand:1234 Source=8 TargetCount=0"),
            power('Source = ' + descriptor()), power('SUB_SPELL_END'),
            'HistoryManager.MarkCurrentHistoryEntryAsCompleted: There is no current History Entry!',
            power('TAG_CHANGE Entity=8 tag=COST value=-2 DEF CHANGE')))
        self.clean(result)
        events = result['events'][-6:]
        self.assertEqual(events[1]['value'], -1)
        self.assertEqual(events[-1]['value'], -2)
        self.assertTrue(events[-1]['definition_change'])
        self.assertEqual(result['coverage']['counts']['excluded_unstructured_diagnostics'], 1)
        self.assertEqual(result['coverage']['counts']['power_list_headers'], 1)

    def test_unresolved_full_entity_update_keeps_initial_tags_without_guessing_identity(self):
        result = self.parse(power('RESET_GAME'),
                            power('FULL_ENTITY - Updating PrivateUnresolvedPlayer CardID='),
                            power('tag=CARDTYPE value=PLAYER'),
                            power('tag=PLAYER_ID value=1'),
                            power('tag=ENTITY_ID value=2'))
        self.clean(result)
        events = result['events'][-5:]
        self.assertEqual(events[1]['entity'], {'opaque_ref': 1})
        self.assertTrue(all(e['entity'] == {'opaque_ref': 1} for e in events[2:]))
        self.assertEqual(events[-1]['value'], 2)
        self.assertEqual(result['coverage']['counts']['observed_game_resets'], 1)
        self.assertNotIn('PrivateUnresolvedPlayer', json.dumps(result))
        self.assertFalse(result['boundary']['complete_server_execution'])

    def test_client_diagnostics_keep_positions_and_do_not_repair_broken_packet_stack(self):
        raw = lines(*opening(), power('SUB_SPELL_END')) + (
            b'E 20:46:22.1234567 PowerProcessor.BuildTaskList(): Hit a SUB_SPELL_END task '
            b'without a corresponding open SubSpellOrigin!\n'
            b'W 20:46:22.1234567 OtherHandler(): PrivateDiagnosticName\n')
        result = log.parse_bytes(raw)
        self.assertFalse(result['coverage']['selected_stream_parse_complete'])
        diagnostics = result['coverage']['client_diagnostics']
        self.assertEqual([d['level'] for d in diagnostics], ['E', 'W'])
        self.assertEqual(diagnostics[0]['code'], 'client_reported_orphan_subspell_origin')
        self.assertEqual(diagnostics[0]['line'], result['events'][-1]['line'] + 1)
        self.assertNotIn('PrivateDiagnosticName', json.dumps(result))

    def test_file_import_pins_original_bytes_compresses_and_preserves_old_outputs(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'Power.log'
            output = Path(directory) / 'observations.json.gz'
            raw = lines(*opening())
            source.write_bytes(raw)
            result = log.import_file(source, output)
            with gzip.open(output, 'rt', encoding='utf-8') as f:
                self.assertEqual(json.load(f), result)
            self.assertEqual(result['source']['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(source.read_bytes(), raw)
            old = output.read_bytes()
            with self.assertRaises(ValueError):
                log.import_file(source, output)
            self.assertEqual(output.read_bytes(), old)
            with self.assertRaises(ValueError):
                log.import_file(source, source)
            self.assertEqual(source.read_bytes(), raw)

    def test_source_change_or_python_change_rejects_export_before_writing(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'Power.log'
            output = Path(directory) / 'new.json'
            raw = lines(*opening())
            source.write_bytes(raw)
            original = Path.read_bytes
            reads = 0

            def changed(path):
                nonlocal reads
                if path == source:
                    reads += 1
                    return raw if reads == 1 else raw + b'\n'
                return original(path)

            with patch.object(Path, 'read_bytes', changed):
                with self.assertRaisesRegex(ValueError, 'Source changed'):
                    log.import_file(source, output)
            self.assertFalse(output.exists())
            with patch.object(log.batch, 'source_guard', side_effect=[{'a': 'old'}, {'a': 'new'}]):
                with self.assertRaisesRegex(ValueError, 'Python source changed'):
                    log.import_file(source, output)
            self.assertFalse(output.exists())

    def test_cli_writes_incomplete_evidence_but_returns_failure_without_leaking_input(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / 'Power.log'
            output = Path(directory) / 'new.json'
            source.write_bytes(lines(*opening(), power('FUTURE_PACKET PrivateCLISecret')))
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = log.main(['--source', str(source), '--output', str(output)])
            self.assertEqual(status, 1)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertFalse(result['coverage']['selected_stream_parse_complete'])
            self.assertNotIn('PrivateCLISecret', stdout.getvalue() + stderr.getvalue() + json.dumps(result))
            self.assertFalse(json.loads(stdout.getvalue())['accepted_calibration_case'])
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(log.main(['--source', str(source), '--output', str(output)]), 2)
            self.assertNotIn(str(source), stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
